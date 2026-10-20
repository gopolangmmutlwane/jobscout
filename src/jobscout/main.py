import argparse
import sys
from datetime import date

import requests
from sqlalchemy import select

from jobscout.collectors.adzuna import AdzunaCollector
from jobscout.collectors.base import BotCheckError
from jobscout.collectors.graduates24 import Graduates24Collector
from jobscout.config import SETTINGS, SOURCES
from jobscout.db.models import Job, Run
from jobscout.db.session import get_session
from jobscout.matching.baseline import rank_jobs
from jobscout.processing.dedupe import save_new_jobs


def _enabled(name: str) -> bool:
    return bool(SOURCES.get("sources", {}).get(name, {}).get("enabled"))


def run_collect(max_pages=None, limit=None, dry_run=False) -> int:
    session = get_session()
    known = set(session.scalars(select(Job.url)))
    postings, seen, stopped = [], 0, False

    if _enabled("graduates24"):
        g24 = Graduates24Collector(known_urls=known, max_pages=max_pages, max_details=limit)
        try:
            postings += g24.collect()
            seen += g24.cards_seen
        except BotCheckError as e:
            print(f"[graduates24] stopped: {e}")
            stopped = True

    if _enabled("adzuna"):
        try:
            found = AdzunaCollector().collect()
            fresh = [p for p in found if p.url not in known]
            if limit:
                fresh = fresh[:limit]
            seen += len(found)
            postings += fresh
        except (RuntimeError, requests.RequestException) as e:
            print(f"[adzuna] skipped: {e}")

    print(f"Listings seen: {seen}; new ads fetched: {len(postings)}")
    if dry_run:
        for p in postings:
            print(f"- [{p.source}] {p.title} | {p.company} | {p.location} | closes {p.closing_date} "
                  f"| description {len(p.description or '')} chars")
        print("Dry run: nothing saved.")
        return 1 if stopped else 0

    new_jobs = save_new_jobs(session, postings)
    session.add(Run(jobs_found=seen, jobs_new=len(new_jobs), notes="collect"))
    session.commit()
    print(f"Saved {len(new_jobs)} new jobs.")
    return 1 if stopped else 0


def run_match(top=None, include_closed=False, show_all=False) -> int:
    session = get_session()
    jobs = list(session.scalars(select(Job)))
    if not jobs:
        print("No jobs stored yet. Run: python -m jobscout.main collect")
        return 0

    ranked, dropped = rank_jobs(jobs, include_closed=include_closed)
    for job, score, _why in ranked:
        job.match_score = score
    session.commit()

    top = top or SETTINGS["search"]["digest_size"]
    today = date.today()
    print(f"{len(jobs)} jobs stored; {len(ranked)} kept after filters.")
    for reason, n in sorted(dropped.items()):
        print(f"  dropped {n}: {reason}")
    floor = SETTINGS["search"]["min_match_score"]
    shown = ranked if show_all else [r for r in ranked if r[1] >= floor]
    hidden = len(ranked) - len(shown)
    if hidden:
        print(f"  ({hidden} more kept ads are below the relevance floor of {floor}; use --all to see them)")
    for i, (job, score, why) in enumerate(shown[:top], 1):
        if job.closing_date:
            days = (job.closing_date - today).days
            label = "today" if days == 0 else ("1 day" if days == 1 else f"{days} days")
            closes = f"{job.closing_date.isoformat()} ({label})"
        else:
            closes = "n/a"
        print(f"\n{i}. [{score:.3f}] {job.title}")
        print(f"   {job.company or '?'} | {job.location or '?'} | closes {closes}")
        print(f"   why: {', '.join(why)}")
        print(f"   {job.url}")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="jobscout")
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("collect", help="fetch new job ads and store them")
    c.add_argument("--pages", type=int, default=None, help="listing pages per category")
    c.add_argument("--limit", type=int, default=None, help="max ads to fetch per source")
    c.add_argument("--dry-run", action="store_true", help="fetch and print, do not save")

    m = sub.add_parser("match", help="rank stored jobs against your profile")
    m.add_argument("--top", type=int, default=None, help="how many to show")
    m.add_argument("--include-closed", action="store_true", help="keep ads past their closing date")
    m.add_argument("--all", action="store_true", help="also show ads below the relevance floor")

    args = parser.parse_args()
    if args.command == "collect":
        return run_collect(max_pages=args.pages, limit=args.limit, dry_run=args.dry_run)
    if args.command == "match":
        return run_match(top=args.top, include_closed=args.include_closed, show_all=args.all)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())