"""Phone-first triage page: review ads one at a time, keep / skip / applied, track outcomes.

Run with:  python -m jobscout.web   (served by waitress on 0.0.0.0:WEB_PORT)
"""
import hmac
import logging
import secrets
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from math import ceil

from flask import Flask, abort, g, redirect, render_template, request, session, url_for
from jinja2 import DictLoader
from sqlalchemy import func, select

from jobscout import config
from jobscout.db.models import Application, Job, Label
from jobscout.db.session import get_session
from jobscout.matching import baseline
from jobscout.notify.email_digest import select_digest

REVIEW_STATUSES = ("new", "notified")
FOLLOW_UP_DAYS = 14  # same default as scripts/track.py
# Button text -> value stored in Application.outcome. "applied" means waiting for a reply, which keeps
# scripts/track.py 'list' and 'due' working.
OUTCOMES = [
    ("applied", "Waiting for reply"),
    ("follow_up", "Follow-up due"),
    ("interview", "Interview"),
    ("offer", "Offer"),
    ("rejected", "Rejected"),
]
OUTCOME_LABELS = dict(OUTCOMES) | {"no_reply": "No reply", "withdrawn": "Withdrawn"}
OPEN_OUTCOMES = ("applied", "follow_up")
STATUS_LABELS = {"new": "New", "notified": "In review", "shortlisted": "Kept", "applied": "Applied",
                 "skipped": "Skipped"}
TABS = [("review", "Review", "review"), ("kept", "Kept", "kept"), ("applied", "Applied", "applied"),
        ("skipped", "Skipped", "skipped")]
MAX_FAILS = 5
LOCK_SECONDS = 15 * 60
RANK_CACHE_SECONDS = 600
PLACEHOLDER = "change-me"
FONTS_URL = ("https://fonts.googleapis.com/css2?family=Fraunces:wght@500;600"
             "&family=IBM+Plex+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap")

CSS = """
:root{--bg:#FBFBFA;--card:#FFFFFF;--ink:#15181A;--mut:#4C5359;--faint:#868D8F;--line:#DDE0D9;--acc:#15181A;
--accfg:#F6F7F4;--brand:#1E6E4F;--red:#B0432A;--amb:#B0742A;--grn:#1E6E4F;--tint:#F3F4F1;--warn:#F8EFDC;
--serif:"Fraunces",Georgia,"Times New Roman",serif;
--sans:"Inter",system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;color-scheme:light}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:400 16px/1.5 var(--sans);overflow-x:clip;overflow-wrap:anywhere}
button,input{font:inherit}
.wrap{max-width:560px;margin:0 auto;padding-left:max(16px,env(safe-area-inset-left));padding-right:max(16px,env(safe-area-inset-right))}
.top{padding-top:max(14px,env(safe-area-inset-top));padding-bottom:10px}
.brand{display:flex;align-items:center;gap:10px}
.badge{flex:none;width:30px;height:30px;border-radius:6px;background:var(--acc);color:var(--accfg);font:700 12px/30px var(--mono);text-align:center}
.name{font:600 20px/1 var(--serif)}
.tabs{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:8px 0}
.tabrow{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}
.tab{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:48px;padding:5px 4px;border:1px solid var(--line);border-radius:20px;background:var(--card);color:var(--mut);text-decoration:none;font-family:var(--mono)}
.tab .n{font-size:15px;font-weight:700;line-height:1.15;color:var(--ink)}
.tab .l{font-size:11px;font-weight:500;line-height:1.2;letter-spacing:.04em;text-transform:uppercase}
.tab.on{background:var(--acc);border-color:var(--acc);color:var(--accfg)}
.tab.on .n{color:var(--accfg)}
main{padding-top:16px;padding-bottom:calc(88px + env(safe-area-inset-bottom))}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:20px 18px}
.state{display:inline-block;margin:0 0 10px;font:700 11px/1 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--brand)}
.title{font:600 24px/1.2 var(--serif);margin:0 0 8px}
.co{color:var(--brand);font-weight:600;margin:0}
.loc{color:var(--mut);margin:2px 0 12px}
.pill,.tag{display:inline-block;font:500 12px/1.2 var(--mono);padding:6px 12px;border-radius:20px;background:var(--tint);color:var(--mut);border:1px solid var(--line)}
.pill.amb,.tag.due{background:var(--warn);color:var(--amb);border-color:var(--amb)}
.pill.red{background:var(--card);color:var(--red);border-color:var(--red)}
.meta{font:400 12px/1.4 var(--mono);color:var(--faint);margin:12px 0}
.why{background:var(--tint);border:1px solid var(--line);border-radius:3px;padding:10px 12px;margin:0 0 6px}
.why .k{font:700 11px/1 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--mut)}
.why p{margin:6px 0 0;font-size:14px}
details.desc{border-bottom:1px solid var(--line);margin:0 0 16px}
details.desc summary{cursor:pointer;min-height:48px;display:flex;align-items:center;font:500 13px var(--mono);color:var(--mut)}
details.desc .body{white-space:pre-line;font-size:15px;padding:0 0 14px}
.open{display:flex;align-items:center;justify-content:center;min-height:52px;border-radius:3px;background:var(--acc);color:var(--accfg);font-weight:600;text-decoration:none;margin:0 0 10px}
.open:hover{background:var(--grn)}
.acts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.b{border:0;border-radius:3px;padding:17px 6px;min-height:48px;color:#fff;font-weight:600;font-size:16px;line-height:1;cursor:pointer}
.b2{border:0;border-radius:3px;min-height:48px;padding:0 10px;color:#fff;font-weight:600;font-size:15px;cursor:pointer}
.skip{background:var(--red)}.keep{background:var(--amb)}.appl{background:var(--grn)}
.ghost{background:var(--card);color:var(--ink);border:1px solid var(--line)}
.pager{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:12px}
.pg{min-height:48px;display:inline-flex;align-items:center;padding:0 14px;font:500 13px var(--mono);color:var(--ink);text-decoration:none;border:1px solid var(--line);border-radius:3px;background:var(--card)}
.pg.off{color:var(--faint);background:transparent}
.pos{font:500 13px var(--mono);color:var(--mut);text-align:center}
.h{font:600 22px/1.2 var(--serif);margin:4px 0 12px}
.rows{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.row{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:14px}
.rt{font:600 17px/1.3 var(--serif);color:var(--ink);text-decoration:none}
.rt:hover{text-decoration:underline}
.row .co{margin:4px 0 8px}
.rowacts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:12px}
.rowacts.one{grid-template-columns:1fr}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 0}
.small{font:400 12px/1.4 var(--mono);color:var(--faint);margin:0}
.outs{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.ob{min-height:48px;padding:0 14px;border-radius:20px;border:1px solid var(--line);background:var(--card);font:500 12px var(--mono);color:var(--ink);cursor:pointer}
.ob.on{background:var(--acc);color:var(--accfg);border-color:var(--acc)}
.empty{background:var(--card);border:1px dashed var(--line);border-radius:6px;padding:28px 18px;text-align:center;color:var(--mut)}
.empty h2{font:600 20px/1.2 var(--serif);color:var(--ink);margin:0 0 6px}
.foot{padding-bottom:calc(24px + env(safe-area-inset-bottom));font:400 12px var(--mono);color:var(--faint)}
.foot a{color:var(--mut)}
.toast{position:fixed;left:50%;transform:translateX(-50%);bottom:calc(16px + env(safe-area-inset-bottom));width:min(528px,calc(100% - 32px));display:flex;align-items:center;justify-content:space-between;gap:12px;background:var(--ink);color:var(--accfg);border-radius:6px;padding:8px 8px 8px 16px;z-index:10;font-size:14px}
.toast form{margin:0;flex:none}
.toast button{min-height:48px;padding:0 18px;border-radius:3px;border:1px solid var(--accfg);background:transparent;color:var(--accfg);font:600 14px var(--mono);cursor:pointer}
.login{max-width:360px;margin:8vh auto 0}
.login label{display:block;font:500 12px var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin:0 0 8px}
.login input{width:100%;min-height:52px;border:1px solid var(--line);border-radius:3px;background:var(--card);padding:0 14px;font:500 22px var(--mono);letter-spacing:.2em;color:var(--ink)}
.login .b{width:100%;margin-top:12px;background:var(--acc);color:var(--accfg)}
.err{color:var(--red);font-weight:500;margin:0 0 12px}
:focus-visible{outline:3px solid var(--brand);outline-offset:2px}
.tab.on:focus-visible,.open:focus-visible{outline-color:var(--amb)}
"""

TEMPLATES = {
    "base.html": """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="referrer" content="no-referrer">
<meta name="theme-color" content="#FBFBFA">
<title>{% block title %}jobscout{% endblock %}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{{ fonts_url }}">
<style>{{ css|safe }}</style>
</head>
<body>
<header class="top"><div class="wrap brand"><span class="badge" aria-hidden="true">JS</span><span class="name">jobscout</span></div></header>
{% if nav %}<nav class="tabs" aria-label="Sections"><div class="wrap tabrow">
{% for key, label, endpoint in tabs %}<a class="tab{% if key == active %} on{% endif %}" href="{{ url_for(endpoint) }}"{% if key == active %} aria-current="page"{% endif %}><span class="n">{{ counts[key] }}</span><span class="l">{{ label }}</span></a>{% endfor %}
</div></nav>{% endif %}
<main class="wrap">{% block main %}{% endblock %}</main>
<footer class="wrap foot">{% if show_adzuna %}<p>Listings provided by <a href="https://www.adzuna.co.za" target="_blank" rel="noopener noreferrer">Adzuna</a></p>{% endif %}</footer>
{% if toast %}<div class="toast" id="toast" role="status"><span>{{ toast }}</span>{% if can_undo %}<form method="post" action="{{ url_for('undo') }}"><input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="next" value="{{ here }}"><button type="submit">Undo</button></form>{% endif %}</div>
<script>setTimeout(function(){var t=document.getElementById("toast");if(t){t.remove();}},5000);</script>{% endif %}
</body>
</html>""",
    "login.html": """{% extends "base.html" %}{% block title %}jobscout · sign in{% endblock %}{% block main %}
<form class="login" method="post" action="{{ url_for('login') }}">
<h1 class="h">Sign in</h1>
{% if error %}<p class="err" role="alert">{{ error }}</p>{% endif %}
<input type="hidden" name="csrf" value="{{ csrf }}">
<label for="pin">PIN</label>
<input id="pin" name="pin" type="password" inputmode="numeric" autocomplete="current-password" required autofocus>
<button class="b" type="submit">Open jobscout</button>
</form>{% endblock %}""",
    "card.html": """<article class="card">
{% if job.status not in review_statuses %}<p class="state">{{ status_labels.get(job.status, job.status) }}</p>{% endif %}
<h1 class="title">{{ job.title }}</h1>
<p class="co">{{ job.company or "Company not stated" }}</p>
<p class="loc">{{ job.location or "Location not stated" }}</p>
<span class="pill {{ pill[1] }}">{{ pill[0] }}</span>
<p class="meta">{{ job.source }} · id {{ job.id }} · match {{ "%.2f"|format(score) if score is not none else "n/a" }}</p>
<div class="why"><span class="k">Why</span><p>{{ why }}</p></div>
{% if job.description %}<details class="desc"><summary>Read description</summary><div class="body">{{ job.description }}</div></details>{% endif %}
{% if open_url %}<a class="open" href="{{ open_url }}" target="_blank" rel="noopener noreferrer">Open ad</a>{% endif %}
<form class="acts" method="post" action="{{ url_for('act') }}">
<input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="job_id" value="{{ job.id }}"><input type="hidden" name="next" value="{{ next_url }}">
<button class="b skip" name="action" value="skip">Skip</button>
<button class="b keep" name="action" value="keep">Keep</button>
<button class="b appl" name="action" value="applied">Applied</button>
</form>
</article>""",
    "review.html": """{% extends "base.html" %}{% block main %}
{% if job %}{% include "card.html" %}
<div class="pager">
{% if i > 0 %}<a class="pg" href="{{ url_for('review', i=i-1) }}">&larr; Back</a>{% else %}<span class="pg off" aria-disabled="true">&larr; Back</span>{% endif %}
<span class="pos">Ad {{ i + 1 }} of {{ total }}</span>
{% if i + 1 < total %}<a class="pg" href="{{ url_for('review', i=i+1) }}">Later &rarr;</a>{% else %}<span class="pg off" aria-disabled="true">Later &rarr;</span>{% endif %}
</div>
{% else %}<div class="empty"><h2>All caught up</h2><p>No open ads waiting for review.</p></div>{% endif %}
{% endblock %}""",
    "ad.html": """{% extends "base.html" %}{% block main %}{% include "card.html" %}
<div class="pager"><a class="pg" href="{{ url_for('review') }}">&larr; Review</a><span></span></div>
{% endblock %}""",
    "kept.html": """{% extends "base.html" %}{% block main %}<h2 class="h">Kept</h2>
{% if items %}<ul class="rows">{% for job, pill in items %}<li class="row">
<a class="rt" href="{{ url_for('ad', job_id=job.id) }}">{{ job.title }}</a>
<p class="co">{{ job.company or "Company not stated" }}</p>
<span class="pill {{ pill[1] }}">{{ pill[0] }}</span>
<form class="rowacts" method="post" action="{{ url_for('act') }}">
<input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="job_id" value="{{ job.id }}"><input type="hidden" name="next" value="{{ url_for('kept') }}">
<button class="b2 appl" name="action" value="applied">Mark applied</button>
<button class="b2 skip" name="action" value="skip">Skip</button>
</form></li>{% endfor %}</ul>
{% else %}<div class="empty"><h2>Nothing kept</h2><p>Ads you keep from Review show up here.</p></div>{% endif %}
{% endblock %}""",
    "applied.html": """{% extends "base.html" %}{% block main %}<h2 class="h">Applied</h2>
{% if items %}<ul class="rows">{% for job, app, due in items %}<li class="row">
<a class="rt" href="{{ url_for('ad', job_id=job.id) }}">{{ job.title }}</a>
<p class="co">{{ job.company or "Company not stated" }}</p>
{% if app %}<p class="small">Applied {{ app.applied_on.strftime("%d/%m/%Y") }}</p>
<div class="tags"><span class="tag">{{ outcome_labels.get(app.outcome, app.outcome) }}</span>{% if due %}<span class="tag due">Follow-up DUE</span>{% endif %}</div>
<form class="outs" method="post" action="{{ url_for('outcome') }}">
<input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="job_id" value="{{ job.id }}">
{% for value, label in outcomes %}<button class="ob{% if app.outcome == value %} on{% endif %}" name="outcome" value="{{ value }}"{% if app.outcome == value %} aria-pressed="true"{% endif %}>{{ label }}</button>{% endfor %}
</form>{% else %}<p class="small">No application record for this ad.</p>{% endif %}
</li>{% endfor %}</ul>
{% else %}<div class="empty"><h2>No applications yet</h2><p>Tap Applied on an ad to start tracking it.</p></div>{% endif %}
{% endblock %}""",
    "skipped.html": """{% extends "base.html" %}{% block main %}<h2 class="h">Skipped</h2>
{% if items %}<ul class="rows">{% for job, pill in items %}<li class="row">
<a class="rt" href="{{ url_for('ad', job_id=job.id) }}">{{ job.title }}</a>
<p class="co">{{ job.company or "Company not stated" }}</p>
<span class="pill {{ pill[1] }}">{{ pill[0] }}</span>
<form class="rowacts one" method="post" action="{{ url_for('act') }}">
<input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="job_id" value="{{ job.id }}"><input type="hidden" name="next" value="{{ url_for('skipped') }}">
<button class="b2 ghost" name="action" value="restore">Restore to Review</button>
</form></li>{% endfor %}</ul>
{% else %}<div class="empty"><h2>Nothing skipped</h2></div>{% endif %}
{% endblock %}""",
    "error.html": """{% extends "base.html" %}{% block main %}<div class="empty"><h2>{{ heading }}</h2><p>{{ message }}</p>
<p><a class="pg" href="{{ url_for('review') }}">Back to Review</a></p></div>{% endblock %}""",
}


class _LoginLimiter:
    """Locks an IP for LOCK_SECONDS after MAX_FAILS wrong PINs. In memory, so a restart clears it."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {}  # ip -> [fails, locked_until]

    def locked_for(self, ip: str) -> float:
        with self._lock:
            fails, until = self._state.get(ip, (0, 0.0))
            now = time.time()
            if until > now:
                return until - now
            if until:
                self._state.pop(ip, None)
            return 0.0

    def fail(self, ip: str) -> bool:
        """Count a wrong PIN. Returns False when this attempt triggers the lock."""
        with self._lock:
            fails, _until = self._state.get(ip, (0, 0.0))
            fails += 1
            if fails >= MAX_FAILS:
                self._state[ip] = [fails, time.time() + LOCK_SECONDS]
                return False
            self._state[ip] = [fails, 0.0]
            return True

    def reset(self, ip: str) -> None:
        with self._lock:
            self._state.pop(ip, None)


_rank_lock = threading.Lock()
_rank_cache = {"key": None, "at": 0.0, "scores": {}}  # job id -> (score, why), in ranker order


def invalidate_rank_cache() -> None:
    with _rank_lock:
        _rank_cache["key"] = None


def _rank_scores(db, jobs=None):
    """Scores and reasons from rank_jobs() for all stored ads. Recomputed at most every
    RANK_CACHE_SECONDS, when ads are added, at midnight, or after invalidate_rank_cache()."""
    jobs = list(db.scalars(select(Job))) if jobs is None else jobs
    key = (date.today(), len(jobs), max((j.id for j in jobs), default=0))
    with _rank_lock:
        if _rank_cache["key"] != key or time.time() - _rank_cache["at"] > RANK_CACHE_SECONDS:
            ranked, _ = baseline.rank_jobs(jobs)
            _rank_cache.update(key=key, at=time.time(), scores={j.id: (s, why) for j, s, why in ranked})
        return _rank_cache["scores"]


def _review_items(db):
    """What the morning email lists (select_digest, without its size caps), minus anything kept,
    applied or skipped. Soonest closing first, ads with no closing date last, then highest score."""
    jobs = list(db.scalars(select(Job)))
    by_id = {j.id: j for j in jobs}
    ranked = [(by_id[i], s, why) for i, (s, why) in _rank_scores(db, jobs).items() if i in by_id]
    new, reminders = select_digest(ranked)
    items = [r for r in new + reminders if r[0].status not in ("applied", "skipped", "shortlisted")]
    items.sort(key=lambda r: (r[0].closing_date is None, r[0].closing_date or date.max, -r[1]))
    return items


def _why_text(db, job) -> str:
    """Match reasons from the ranker. They are not stored in the database, so they come from the cache."""
    hit = _rank_scores(db).get(job.id)
    if hit:
        return ", ".join(hit[1])
    reason = baseline._drop_reason(job, config.load_profile(), date.today(), False)
    return f"Filtered out by the ranker: {reason or 'no sign of your field'}."


def _closing_pill(job, today):
    if not job.closing_date:
        return "Closing date not stated", ""
    days = (job.closing_date - today).days
    dm = job.closing_date.strftime("%d/%m")
    if days < 0:
        return f"Closed ({dm})", "red"
    if days == 0:
        text = f"Closes today ({dm})"
    elif days == 1:
        text = f"Closes in 1 day ({dm})"
    else:
        text = f"Closes in {days} days ({dm})"
    return text, "red" if days <= 3 else "amb" if days <= 10 else ""


def _safe_next(value, default):
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return default


def _counts(db, review_count=None):
    by_status = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    review = len(_review_items(db)) if review_count is None else review_count
    return {"review": review, "kept": by_status.get("shortlisted", 0),
            "applied": by_status.get("applied", 0), "skipped": by_status.get("skipped", 0)}


def _latest_label(db, job_id):
    return db.scalars(select(Label).where(Label.job_id == job_id).order_by(Label.id.desc())).first()


def _do_action(db, job, action, today):
    """Apply an action and return what is needed to undo it."""
    undo = {"job": job.id, "status": job.status, "label": None, "app": None}
    if action in ("skip", "keep"):
        name = "skip" if action == "skip" else "interested"
        lab = _latest_label(db, job.id)
        if lab:
            undo["label"] = {"op": "updated", "id": lab.id, "prev": lab.label,
                             "at": lab.labelled_at.isoformat() if lab.labelled_at else None}
            lab.label = name
            lab.labelled_at = datetime.now(timezone.utc)
        else:
            lab = Label(job_id=job.id, label=name)
            db.add(lab)
            db.flush()
            undo["label"] = {"op": "created", "id": lab.id}
        job.status = "skipped" if action == "skip" else "shortlisted"
    elif action == "applied":
        app = db.scalars(select(Application).where(Application.job_id == job.id)).first()
        if app is None:
            app = Application(job_id=job.id, applied_on=today, outcome="applied",
                              follow_up_on=today + timedelta(days=FOLLOW_UP_DAYS))
            db.add(app)
            db.flush()
            undo["app"] = app.id
        job.status = "applied"
    elif action == "restore":
        removed = []
        for lab in db.scalars(select(Label).where(Label.job_id == job.id, Label.label == "skip")):
            removed.append([lab.label, lab.labelled_at.isoformat() if lab.labelled_at else None])
            db.delete(lab)
        undo["label"] = {"op": "deleted", "rows": removed}
        job.status = "notified"
    return undo


def _undo_action(db, undo):
    job = db.get(Job, undo["job"])
    if job is None:
        return None
    job.status = undo["status"]
    lab = undo.get("label")
    if lab and lab["op"] == "created":
        row = db.get(Label, lab["id"])
        if row:
            db.delete(row)
    elif lab and lab["op"] == "updated":
        row = db.get(Label, lab["id"])
        if row:
            row.label = lab["prev"]
            if lab.get("at"):
                row.labelled_at = datetime.fromisoformat(lab["at"])
    elif lab and lab["op"] == "deleted":
        for name, at in lab["rows"]:
            db.add(Label(job_id=job.id, label=name,
                         labelled_at=datetime.fromisoformat(at) if at else datetime.now(timezone.utc)))
    if undo.get("app"):
        row = db.get(Application, undo["app"])
        if row:
            db.delete(row)
    return job


ACTION_TOASTS = {"skip": "Skipped", "keep": "Kept", "applied": "Marked applied", "restore": "Back in Review"}


def create_app(pin=None, secret_key=None):
    pin = config.WEB_PIN if pin is None else pin
    secret_key = config.WEB_SECRET_KEY if secret_key is None else secret_key
    if not pin or not secret_key or PLACEHOLDER in (pin, secret_key):
        raise RuntimeError("Set WEB_PIN and WEB_SECRET_KEY in .env before starting the web app.")

    app = Flask(__name__)
    app.jinja_loader = DictLoader(TEMPLATES)
    app.config.update(
        SECRET_KEY=secret_key,
        SESSION_COOKIE_NAME="jobscout_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )
    limiter = _LoginLimiter()
    app.extensions["jobscout_limiter"] = limiter

    def db():
        if "db" not in g:
            g.db = get_session()
        return g.db

    @app.teardown_appcontext
    def _close_db(_exc):
        s = g.pop("db", None)
        if s is not None:
            s.close()

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    def check_csrf():
        token = session.get("csrf")
        sent = request.form.get("csrf", "")
        if not token or not hmac.compare_digest(token, sent):
            abort(400)

    @app.context_processor
    def _globals():
        return {"csrf": csrf_token(), "css": CSS, "fonts_url": FONTS_URL, "tabs": TABS,
                "review_statuses": REVIEW_STATUSES, "status_labels": STATUS_LABELS,
                "outcome_labels": OUTCOME_LABELS, "outcomes": OUTCOMES, "here": request.full_path.rstrip("?"),
                "toast": session.pop("toast", None), "can_undo": "undo" in session}

    @app.before_request
    def _require_login():
        if request.endpoint in ("login", None):
            return None
        if not session.get("auth"):
            if request.method == "GET":
                session["after_login"] = request.full_path.rstrip("?")
            return redirect(url_for("login"))
        if request.method == "POST":
            check_csrf()
        return None

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; script-src 'unsafe-inline'; img-src 'self'; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.errorhandler(400)
    def _bad_request(_e):
        return render_template("error.html", nav=False, heading="Form expired",
                               message="Reload the page and try again."), 400

    @app.errorhandler(404)
    def _not_found(_e):
        return render_template("error.html", nav=False, heading="Not found",
                               message="That ad or page does not exist."), 404

    def page(template, active, shown, review_count=None, **ctx):
        return render_template(template, nav=True, active=active, counts=_counts(db(), review_count),
                               show_adzuna=any(j.source == "adzuna" for j in shown), **ctx)

    def card_ctx(job, next_url):
        url = job.url or ""
        hit = _rank_scores(db()).get(job.id)
        return {"job": job, "pill": _closing_pill(job, date.today()), "why": _why_text(db(), job),
                "score": hit[0] if hit else job.match_score,
                "open_url": url if url.lower().startswith(("https://", "http://")) else None,
                "next_url": next_url}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        ip = request.remote_addr or "unknown"
        error, status = None, 200
        if request.method == "POST":
            check_csrf()
            wait = limiter.locked_for(ip)
            if wait:
                error, status = f"Too many wrong PINs. Try again in {ceil(wait / 60)} min.", 429
            elif hmac.compare_digest(request.form.get("pin", "").strip().encode(), pin.encode()):
                limiter.reset(ip)
                after = _safe_next(session.get("after_login"), url_for("review"))
                session.clear()
                session.permanent = True
                session["auth"] = True
                session["csrf"] = secrets.token_urlsafe(32)
                return redirect(after)
            elif limiter.fail(ip):
                error, status = "Wrong PIN.", 401
            else:
                error, status = "Too many wrong PINs. Locked for 15 minutes.", 429
        return render_template("login.html", nav=False, error=error), status

    @app.route("/")
    def home():
        return redirect(url_for("review"))

    @app.route("/review")
    def review():
        items = _review_items(db())
        if not items:
            return page("review.html", "review", [], review_count=0, job=None, i=0, total=0)
        i = max(0, min(request.args.get("i", 0, type=int), len(items) - 1))
        job = items[i][0]
        return page("review.html", "review", [job], review_count=len(items), i=i, total=len(items),
                    **card_ctx(job, url_for("review", i=i)))

    @app.route("/ad/<int:job_id>")
    def ad(job_id):
        job = db().get(Job, job_id)
        if job is None:
            abort(404)
        active = {"shortlisted": "kept", "applied": "applied", "skipped": "skipped"}.get(job.status, "review")
        return page("ad.html", active, [job], **card_ctx(job, url_for("ad", job_id=job.id)))

    @app.route("/kept")
    def kept():
        today = date.today()
        jobs = list(db().scalars(select(Job).where(Job.status == "shortlisted")
                                 .order_by(Job.closing_date.is_(None), Job.closing_date, Job.id)))
        return page("kept.html", "kept", jobs, items=[(j, _closing_pill(j, today)) for j in jobs])

    @app.route("/applied")
    def applied():
        today = date.today()
        rows = db().execute(
            select(Job, Application).outerjoin(Application, Application.job_id == Job.id)
            .where(Job.status == "applied")
            .order_by(Application.applied_on.is_(None), Application.applied_on.desc(), Job.id.desc())
        ).all()
        items = [(job, app_row, bool(app_row and app_row.follow_up_on and app_row.follow_up_on <= today
                                      and app_row.outcome in OPEN_OUTCOMES))
                 for job, app_row in rows]
        return page("applied.html", "applied", [j for j, _a in rows], items=items)

    @app.route("/skipped")
    def skipped():
        today = date.today()
        jobs = list(db().scalars(select(Job).where(Job.status == "skipped").order_by(Job.id.desc())))
        return page("skipped.html", "skipped", jobs, items=[(j, _closing_pill(j, today)) for j in jobs])

    @app.route("/act", methods=["POST"])
    def act():
        action = request.form.get("action", "")
        if action not in ACTION_TOASTS:
            abort(400)
        s = db()
        job = s.get(Job, request.form.get("job_id", type=int) or 0)
        if job is None:
            abort(404)
        undo = _do_action(s, job, action, date.today())
        s.commit()
        invalidate_rank_cache()
        session["undo"] = undo
        session["toast"] = f"{ACTION_TOASTS[action]}: {job.title}"
        return redirect(_safe_next(request.form.get("next"), url_for("review")))

    @app.route("/undo", methods=["POST"])
    def undo():
        data = session.pop("undo", None)
        nxt = _safe_next(request.form.get("next"), url_for("review"))
        if not data:
            session["toast"] = "Nothing to undo."
            return redirect(nxt)
        s = db()
        job = _undo_action(s, data)
        s.commit()
        invalidate_rank_cache()
        session["toast"] = "Undone."
        if job is not None and nxt.startswith(url_for("review")):
            ids = [j.id for j, _s, _w in _review_items(s)]
            if job.id in ids:
                nxt = url_for("review", i=ids.index(job.id))
        return redirect(nxt)

    @app.route("/outcome", methods=["POST"])
    def outcome():
        value = request.form.get("outcome", "")
        if value not in dict(OUTCOMES):
            abort(400)
        s = db()
        app_row = s.scalars(select(Application)
                            .where(Application.job_id == (request.form.get("job_id", type=int) or 0))).first()
        if app_row is None:
            abort(404)
        app_row.outcome = value
        app_row.updated_at = datetime.now(timezone.utc)
        s.commit()
        session.pop("undo", None)
        session["toast"] = f"Outcome: {OUTCOME_LABELS[value]}"
        return redirect(url_for("applied"))

    return app


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        app = create_app()
    except RuntimeError as e:
        print(f"Not starting: {e}", file=sys.stderr)
        return 1
    from waitress import serve

    print(f"jobscout web: serving on http://0.0.0.0:{config.WEB_PORT}", flush=True)
    serve(app, host="0.0.0.0", port=config.WEB_PORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
