import smtplib
import ssl
from datetime import date
from email.message import EmailMessage

from sqlalchemy import select

from jobscout.config import EMAIL_ADDRESS, EMAIL_APP_PASSWORD, EMAIL_TO, SETTINGS
from jobscout.db.models import Job
from jobscout.matching.baseline import rank_jobs


def pick_digest_jobs(session, limit=None):
    """Open, not-yet-notified, unlabelled ads that clear the relevance floor, best first."""
    jobs = list(session.scalars(select(Job)))
    ranked, _ = rank_jobs(jobs)
    floor = SETTINGS["search"]["min_match_score"]
    limit = limit or SETTINGS["search"]["digest_size"]
    picks = [(j, s, why) for j, s, why in ranked if j.status == "new" and s >= floor]
    return picks[:limit]


def build_digest(picks):
    today = date.today()
    lines = [f"{len(picks)} new matches for you ({today.isoformat()})", ""]
    for i, (job, _score, why) in enumerate(picks, 1):
        if job.closing_date:
            days = (job.closing_date - today).days
            when = "today" if days == 0 else ("1 day" if days == 1 else f"{days} days")
            closes = f"{job.closing_date.isoformat()} ({when})"
        else:
            closes = "not stated"
        lines += [
            f"{i}. {job.title}",
            f"   {job.company or '?'} | {job.location or '?'} | closes {closes}",
            f"   why: {', '.join(why)}",
            f"   {job.url}",
            "",
        ]
    lines.append("To apply: open an ad you like, copy its text into Claude, and ask for a tailored CV and cover letter.")
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


def mark_notified(session, picks):
    for job, _score, _why in picks:
        job.status = "notified"
    session.commit()