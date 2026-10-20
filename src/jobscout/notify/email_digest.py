import smtplib
import ssl
from datetime import date
from email.message import EmailMessage

from sqlalchemy import select

from jobscout.config import EMAIL_ADDRESS, EMAIL_APP_PASSWORD, EMAIL_TO, SETTINGS, WEB_BASE_URL
from jobscout.db.models import Job
from jobscout.matching.baseline import rank_jobs

SOON_DAYS = 3


def pick_digest_jobs(session):
    """Returns (new, reminders).

    new: first-time matches that clear the relevance floor, best first.
    reminders: ads you were already told about or marked interested that are still open,
    not applied to and not skipped, soonest closing first. Closed ads are dropped by rank_jobs.
    """
    jobs = list(session.scalars(select(Job)))
    ranked, _ = rank_jobs(jobs)
    new, reminders = select_digest(ranked)
    new_limit = SETTINGS["search"]["digest_size"]
    reminder_limit = SETTINGS["search"].get("reminder_size", 10)
    return new[:new_limit], reminders[:reminder_limit]


def select_digest(ranked):
    """The digest rules without the size caps. ranked is rank_jobs() output (closed ads already dropped).
    Also used by the web Review tab, so both always agree."""
    floor = SETTINGS["search"]["min_match_score"]
    new = [(j, s, why) for j, s, why in ranked if j.status == "new" and s >= floor]
    reminders = [
        (j, s, why) for j, s, why in ranked
        if j.status in ("notified", "shortlisted") and (s >= floor or j.status == "shortlisted")
    ]
    reminders.sort(key=lambda r: (r[0].closing_date or date.max, -r[1]))
    return new, reminders


def _closes(job, today):
    if not job.closing_date:
        return "not stated", None
    days = (job.closing_date - today).days
    when = "today" if days == 0 else ("1 day" if days == 1 else f"{days} days")
    return f"{job.closing_date.isoformat()} ({when})", days


def _block(n, job, why, today):
    closes, days = _closes(job, today)
    flag = "  ** CLOSING SOON **" if days is not None and days <= SOON_DAYS else ""
    return [
        f"{n}. {job.title}{flag}",
        f"   id {job.id} | {job.company or '?'} | {job.location or '?'} | closes {closes}",
        f"   why: {', '.join(why)}",
        f"   source: {job.source}",
        f"   {job.url}",
    ] + ([f"   skip / keep / applied: {WEB_BASE_URL}/ad/{job.id}"] if WEB_BASE_URL else []) + [""]


def build_subject(new, reminders):
    today = date.today()
    soon = sum(
        1 for j, _s, _w in new + reminders
        if j.closing_date and (j.closing_date - today).days <= SOON_DAYS
    )
    subject = f"jobscout: {len(new)} new, {len(reminders)} still open"
    if soon:
        subject += f" ({soon} closing within {SOON_DAYS} days)"
    return subject


def build_digest(new, reminders, replies=()):
    """replies: [(EmailEvent, Job)] found by this run's reply check (empty when it is switched off)."""
    today = date.today()
    review_line = [f"Open jobscout: {WEB_BASE_URL}/review"] if WEB_BASE_URL else []
    lines = [f"jobscout digest, {today.isoformat()}"] + review_line + [""]
    if replies:
        lines += [f"NEW REPLIES ({len(replies)})", ""]
        for event, job in replies:
            when = event.received_at.strftime("%Y-%m-%d") if event.received_at else "date unknown"
            lines.append(f"- {job.company or job.title} | {event.category} | {when}")
        lines.append("")
    n = 0
    if new:
        lines += [f"NEW ({len(new)})", ""]
        for job, _score, why in new:
            n += 1
            lines += _block(n, job, why, today)
    if reminders:
        lines += [f"STILL OPEN, NOT APPLIED ({len(reminders)})", ""]
        for job, _score, why in reminders:
            n += 1
            lines += _block(n, job, why, today)
    if any(job.source == "adzuna" for job, _s, _w in new + reminders):
        lines += ["Adzuna listings are provided by the Adzuna API (https://www.adzuna.co.za).", ""]
    lines += [
        "Applied? python scripts\\track.py applied --id <id>   (stops the reminders, keeps the record)",
        "Not interested? python scripts\\track.py skip --id <id>",
        "To apply: open an ad you like, copy its full text into Claude, and ask for a tailored CV and cover letter.",
    ] + review_line
    return "\n".join(lines)


def send_email(subject, body):
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        raise RuntimeError("Set EMAIL_ADDRESS and EMAIL_APP_PASSWORD in .env")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_TO or EMAIL_ADDRESS
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as smtp:
        smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD.replace(" ", ""))
        smtp.send_message(msg)


def mark_notified(session, new):
    """Only first-time matches change status; reminders stay as they are."""
    for job, _score, _why in new:
        if job.status == "new":
            job.status = "notified"
    session.commit()