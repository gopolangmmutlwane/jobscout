"""Find replies to your applications and record them as EmailEvent rows (shared by
scripts/check_replies.py and the daily run)."""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select

from jobscout.config import EMAIL_ADDRESS, EMAIL_APP_PASSWORD
from jobscout.db.models import Application, EmailEvent, Job
from jobscout.replies.classifier import classify, looks_job_related
from jobscout.replies.imap_reader import fetch_messages
from jobscout.replies.matcher import match

SNIPPET_CHARS = 300


@dataclass
class ReplyResult:
    since: date | None = None
    scanned: int = 0
    matched: int = 0
    already_stored: int = 0
    unmatched_job_related: int = 0
    rows: list = field(default_factory=list)  # (received_at, from_addr, subject, category, job_id) for matches
    new: list = field(default_factory=list)  # (EmailEvent, Job) found in this run, stored unless dry run

    def by_category(self) -> dict:
        return dict(Counter(ev.category for ev, _job in self.new))


def applied_jobs(session):
    return list(session.scalars(select(Job).where(Job.status == "applied")))


def since_date(session, days=None, today=None):
    """--days back from today, else the earliest applied_on among Applied jobs minus one day."""
    today = today or date.today()
    if days is not None:
        return today - timedelta(days=days)
    earliest = session.scalar(
        select(func.min(Application.applied_on)).join(Job, Job.id == Application.job_id)
        .where(Job.status == "applied")
    )
    return earliest - timedelta(days=1) if earliest else None


def check_replies(session, days=None, dry_run=False, fetch=fetch_messages,
                  address=None, password=None, log=print) -> ReplyResult:
    """Scan the mailbox (read-only), link messages to Applied jobs, classify them and, unless dry_run,
    store new EmailEvent rows. Raises imap_reader.MailboxError if the mailbox cannot be read."""
    result = ReplyResult()
    jobs = applied_jobs(session)
    if not jobs:
        log("[replies] no Applied jobs yet; nothing to match.")
        return result
    result.since = since_date(session, days)
    if result.since is None:
        log("[replies] no application dates recorded; use --days.")
        return result

    messages, result.scanned = fetch(result.since, address or EMAIL_ADDRESS, password or EMAIL_APP_PASSWORD, log=log)
    by_id = {j.id: j for j in jobs}
    known = set(session.scalars(select(EmailEvent.message_id)))
    for m in messages:
        hit = match(m.from_addr, m.from_name, m.subject, m.body, jobs)
        if hit is None:
            if looks_job_related(m.subject, m.body):
                result.unmatched_job_related += 1
            continue
        category, cat_conf = classify(m.subject, m.body)
        result.matched += 1
        result.rows.append((m.received_at, m.from_addr, m.subject, category, hit.job_id))
        if m.message_id in known:
            result.already_stored += 1
            continue
        event = EmailEvent(
            message_id=m.message_id, job_id=hit.job_id, received_at=m.received_at,
            from_addr=m.from_addr[:320], from_name=(m.from_name or None) and m.from_name[:200],
            subject=(m.subject or "")[:500], snippet=(m.body or "")[:SNIPPET_CHARS] or None,
            category=category, confidence=round(cat_conf * hit.confidence, 2),
            match_reason=f"{hit.reason} (match {hit.confidence:.2f}, category {cat_conf:.2f})"[:300],
            handled=False,
        )
        known.add(m.message_id)
        result.new.append((event, by_id[hit.job_id]))
        if not dry_run:
            session.add(event)
    if not dry_run and result.new:
        session.commit()
    return result
