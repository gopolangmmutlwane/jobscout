"""Check the mailbox (read-only) for replies to your applications.

    python scripts\\check_replies.py --dry-run          # print matches, write nothing
    python scripts\\check_replies.py                    # store new replies as EmailEvent rows
    python scripts\\check_replies.py --days 30          # look back 30 days instead of since your first application
"""
import argparse
import sys

from jobscout.db.session import get_session
from jobscout.replies.check import check_replies
from jobscout.replies.imap_reader import MailboxError


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="check_replies")
    p.add_argument("--days", type=int, default=None,
                   help="look back this many days (default: since your earliest application, minus 1 day)")
    p.add_argument("--dry-run", action="store_true",
                   help="print date, sender, subject, category and job id of matches; write nothing")
    a = p.parse_args()

    session = get_session()
    try:
        result = check_replies(session, days=a.days, dry_run=a.dry_run)
    except MailboxError as e:
        print(f"Mailbox problem: {e}")
        return 1

    if result.since is None:
        return 0
    if a.dry_run:
        for received, sender, subject, category, job_id in result.rows:
            when = received.strftime("%Y-%m-%d") if received else "????-??-??"
            print(f"{when} | {sender} | {subject[:90]} | {category} | job {job_id}")
    print(f"Since {result.since}: scanned {result.scanned}, matched {result.matched} "
          f"({result.already_stored} already stored).")
    cats = result.by_category()
    label = "would add" if a.dry_run else "new events"
    print(f"{label}: {len(result.new)}" + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(cats.items())) + ")"
                                         if cats else ""))
    print(f"job-related emails that matched no application: {result.unmatched_job_related}")
    if a.dry_run:
        print("Dry run: nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
