import argparse
import smtplib
import sys

from jobscout.config import SETTINGS
from jobscout.db.session import get_session
from jobscout.main import run_collect
from jobscout.notify.email_digest import (
    build_digest, build_subject, mark_notified, pick_digest_jobs, send_email,
)
from jobscout.replies.check import check_replies
from jobscout.replies.imap_reader import MailboxError


def check_replies_for_digest(session, dry_run=False):
    """Run the reply check when replies.enabled is set. Problems are printed (so they land in the
    daily log) and never stop the digest or appear in the email. Returns [(EmailEvent, Job)]."""
    if not SETTINGS.get("replies", {}).get("enabled"):
        return []
    try:
        result = check_replies(session, dry_run=dry_run)
    except MailboxError as e:
        print(f"[replies] skipped: {e}")
        return []
    except Exception as e:  # a reply-check bug must not cost you the digest
        session.rollback()
        print(f"[replies] failed: {e.__class__.__name__}: {e}")
        return []
    print(f"[replies] scanned {result.scanned}, matched {result.matched}, new {len(result.new)}, "
          f"job-related but unmatched {result.unmatched_job_related}")
    return result.new


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="jobscout.daily")
    p.add_argument("--no-collect", action="store_true", help="skip fetching new ads (works offline)")
    p.add_argument("--pages", type=int, default=3, help="listing pages per category")
    p.add_argument("--dry-run", action="store_true", help="print the digest; send and mark nothing")
    p.add_argument("--test", action="store_true", help="send a test email and exit")
    a = p.parse_args()

    try:
        if a.test:
            send_email("jobscout test", "If you can read this, email notifications work.")
            print("Test email sent.")
            return 0

        if not a.no_collect and run_collect(max_pages=a.pages) != 0:
            print("Collection stopped; continuing with ads already stored.")

        session = get_session()
        replies = check_replies_for_digest(session, dry_run=a.dry_run)
        new, reminders = pick_digest_jobs(session)
        if not new and not reminders and not replies:
            print("Nothing to send.")
            return 0
        body = build_digest(new, reminders, replies)
        subject = build_subject(new, reminders)
        if a.dry_run:
            print(subject)
            print()
            print(body)
            return 0
        send_email(subject, body)
        mark_notified(session, new)
        print(f"Digest sent: {len(new)} new, {len(reminders)} still open.")
        return 0
    except (smtplib.SMTPException, OSError, RuntimeError) as e:
        print(f"Email problem: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())