import sys

from jobscout.db.models import Job, Label
from jobscout.db.session import get_session


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts\\skip_company.py <word from company name>")
        return 1
    word = sys.argv[1].lower()
    s = get_session()
    rows = [j for j in s.query(Job)
            if word in (j.company or "").lower() and j.status not in ("applied", "skipped")]
    if not rows:
        print("Nothing to skip.")
        return 0
    for j in rows:
        j.status = "skipped"
        lab = s.query(Label).filter_by(job_id=j.id).first()
        if lab:
            lab.label = "skip"
        else:
            s.add(Label(job_id=j.id, label="skip"))
    s.commit()
    print(f"Skipped {len(rows)} ads from companies matching '{word}'. Applied ads were left alone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())