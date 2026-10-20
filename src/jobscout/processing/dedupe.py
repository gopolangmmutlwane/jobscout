from sqlalchemy import select

from jobscout.db.models import Job
from jobscout.processing.cleaner import canonical_url, make_hash


def save_new_jobs(session, postings):
    """Insert postings not already stored (same canonical URL or same fingerprint). Returns the new Job rows."""
    seen_urls = {canonical_url(u) for u in session.scalars(select(Job.url))}
    seen_hashes = set(session.scalars(select(Job.content_hash)))
    new_jobs = []
    for p in postings:
        h = make_hash(p.title, p.company, p.description)
        key = canonical_url(p.url)
        if key in seen_urls or h in seen_hashes:
            continue
        job = Job(
            source=p.source, url=p.url, title=p.title, company=p.company,
            location=p.location, description=p.description,
            closing_date=p.closing_date, content_hash=h,
        )
        session.add(job)
        new_jobs.append(job)
        seen_urls.add(key)
        seen_hashes.add(h)
    session.commit()
    return new_jobs
