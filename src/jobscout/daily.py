import argparse
import smtplib
import sys

from jobscout.db.session import get_session
from jobscout.main import run_collect
from jobscout.notify.email_digest import (
    build_digest, build_subject, mark_notified, pick_digest_jobs, send_email,
)


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
        new, reminders = pick_digest_jobs(session)
        if not new and not reminders:
            print("Nothing to send.")
            return 0
        body = build_digest(new, reminders)
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