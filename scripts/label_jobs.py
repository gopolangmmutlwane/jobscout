from datetime import date

from jobscout.db.models import Job, Label
from jobscout.db.session import get_session
from jobscout.matching.baseline import rank_jobs


def main():
    session = get_session()
    jobs = session.query(Job).all()
    ranked, _ = rank_jobs(jobs, include_closed=True)
    labelled = {row.job_id for row in session.query(Label)}
    todo = [(j, s, why) for j, s, why in ranked if j.id not in labelled]
    if not todo:
        print("Nothing left to label. Run collect to fetch more ads.")
        return

    print(f"{len(todo)} ads to label. For each, answer: would I actually apply?")
    print("  i = interested   s = skip   Enter = decide later   q = quit\n")
    today = date.today()
    counts = {"interested": 0, "skip": 0}
    for n, (job, score, why) in enumerate(todo, 1):
        status = ""
        if job.closing_date:
            status = " (CLOSED)" if job.closing_date < today else ""
        print(f"[{n}/{len(todo)}] {job.title}{status}")
        print(f"   {job.company or '?'} | {job.location or '?'} | closes {job.closing_date or 'n/a'}")
        print(f"   why: {', '.join(why)}")
        print(f"   {job.url}")
        while True:
            ans = input("   [i/s/Enter/q] > ").strip().lower()
            if ans in ("i", "s", "", "q"):
                break
        if ans == "q":
            break
        if ans in ("i", "s"):
            name = "interested" if ans == "i" else "skip"
            session.add(Label(job_id=job.id, label=name))
            job.status = "shortlisted" if ans == "i" else "skipped"
            session.commit()
            counts[name] += 1
        print()
    print(f"Saved this session: {counts['interested']} interested, {counts['skip']} skip.")


if __name__ == "__main__":
    main()
