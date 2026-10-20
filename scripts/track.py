import argparse
from datetime import date, datetime, timedelta, timezone

from jobscout.db.models import Application, Job, Label
from jobscout.db.session import get_session

OUTCOMES = ["applied", "interview", "offer", "rejected", "no_reply", "withdrawn"]


def _matches(session, text, job_id):
    if job_id is not None:
        job = session.get(Job, job_id)
        return [job] if job else []
    t = (text or "").lower()
    if not t:
        return []
    return [j for j in session.query(Job).all()
            if t in (j.title or "").lower() or t in (j.company or "").lower()]


def _pick(session, text, job_id):
    jobs = _matches(session, text, job_id)
    if not jobs:
        print("No matching ad. Try:  python scripts\\track.py find <word>")
        return None
    if len(jobs) > 1:
        print(f"{len(jobs)} ads match. Re-run with --id <number>:")
        for j in jobs[:15]:
            print(f"  {j.id}: {j.title} | {j.company or '?'} | {j.location or '?'} [{j.status}]")
        return None
    return jobs[0]


def _set_label(session, job, name):
    lab = session.query(Label).filter_by(job_id=job.id).first()
    if lab:
        lab.label = name
    else:
        session.add(Label(job_id=job.id, label=name))


def cmd_find(a):
    s = get_session()
    jobs = _matches(s, a.text, None)
    if not jobs:
        print("No matches.")
        return 1
    for j in jobs[:25]:
        print(f"{j.id}: {j.title} | {j.company or '?'} | {j.location or '?'} [{j.status}]")
    return 0


def cmd_applied(a):
    s = get_session()
    job = _pick(s, a.text, a.id)
    if not job:
        return 1
    if s.query(Application).filter_by(job_id=job.id).first():
        print("Already recorded as applied.")
        return 0
    on = date.fromisoformat(a.date) if a.date else date.today()
    follow = on + timedelta(days=a.follow_up)
    s.add(Application(job_id=job.id, applied_on=on, notes=a.note, follow_up_on=follow))
    job.status = "applied"
    _set_label(s, job, "interested")
    s.commit()
    print(f"Recorded: {job.title} ({job.company or '?'}), applied {on}. Follow up on {follow}.")
    return 0


def cmd_outcome(a):
    s = get_session()
    job = _pick(s, a.text, a.id)
    if not job:
        return 1
    app = s.query(Application).filter_by(job_id=job.id).first()
    if not app:
        print("No application recorded for that ad. Use 'applied' first.")
        return 1
    app.outcome = a.outcome
    if a.note:
        app.notes = f"{app.notes} | {a.note}" if app.notes else a.note
    app.updated_at = datetime.now(timezone.utc)
    s.commit()
    print(f"Updated: {job.title} -> {a.outcome}")
    return 0


def cmd_skip(a):
    s = get_session()
    job = _pick(s, a.text, a.id)
    if not job:
        return 1
    job.status = "skipped"
    _set_label(s, job, "skip")
    s.commit()
    print(f"Skipped (will not be emailed again): {job.title}")
    return 0


def cmd_list(_a):
    s = get_session()
    rows = (s.query(Application, Job).join(Job, Job.id == Application.job_id)
            .order_by(Application.applied_on.desc()).all())
    if not rows:
        print("No applications recorded yet.")
        return 0
    print(f"{len(rows)} applications:")
    for app, job in rows:
        print(f"{app.applied_on} | {app.outcome:<9} | {job.title[:55]} | {job.company or '?'}"
              f" | follow-up {app.follow_up_on}")
    return 0


def cmd_due(_a):
    s = get_session()
    today = date.today()
    rows = (s.query(Application, Job).join(Job, Job.id == Application.job_id)
            .filter(Application.outcome == "applied", Application.follow_up_on <= today)
            .order_by(Application.follow_up_on).all())
    if not rows:
        print("No follow-ups due.")
        return 0
    for app, job in rows:
        print(f"Follow up: {job.title} | {job.company or '?'} | applied {app.applied_on}"
              f" | due {app.follow_up_on}")
    return 0


def main():
    p = argparse.ArgumentParser(prog="track")
    sub = p.add_subparsers(dest="cmd", required=True)

    def target(sp):
        sp.add_argument("text", nargs="?", help="a word from the job title or company")
        sp.add_argument("--id", type=int, help="job id (see 'find')")

    f = sub.add_parser("find", help="search stored ads")
    f.add_argument("text")

    ap = sub.add_parser("applied", help="record that you applied")
    target(ap)
    ap.add_argument("--date", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--note", help="free-text note")
    ap.add_argument("--follow-up", type=int, default=14, help="days until follow-up (default 14)")

    o = sub.add_parser("outcome", help="record a result")
    o.add_argument("outcome", choices=OUTCOMES)
    target(o)
    o.add_argument("--note")

    sk = sub.add_parser("skip", help="never email this ad again")
    target(sk)

    sub.add_parser("list", help="show all applications")
    sub.add_parser("due", help="show follow-ups that are due")

    a = p.parse_args()
    return {"find": cmd_find, "applied": cmd_applied, "outcome": cmd_outcome,
            "skip": cmd_skip, "list": cmd_list, "due": cmd_due}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
