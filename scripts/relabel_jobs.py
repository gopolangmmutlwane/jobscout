from jobscout.db.models import Job, Label
from jobscout.db.session import get_session


def main():
    session = get_session()
    rows = (
        session.query(Label, Job)
        .join(Job, Job.id == Label.job_id)
        .filter(Label.label == "interested")
        .order_by(Label.id)
        .all()
    )
    print(f"{len(rows)} 'interested' labels. Enter = keep, s = change to skip, q = quit.\n")
    changed = 0
    for n, (lab, job) in enumerate(rows, 1):
        print(f"[{n}/{len(rows)}] {job.title}")
        print(f"   {job.company or '?'} | {job.location or '?'}")
        while True:
            ans = input("   [Enter/s/q] > ").strip().lower()
            if ans in ("", "s", "q"):
                break
        if ans == "q":
            break
        if ans == "s":
            lab.label = "skip"
            job.status = "skipped"
            session.commit()
            changed += 1
        print()
    print(f"Changed {changed} labels to skip.")


if __name__ == "__main__":
    main()