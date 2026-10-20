import re
from datetime import date

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from jobscout.config import MASTER_CV_PATH, load_profile

DEFAULT_FIT_FIELDS = [
    "mathematics", "mathematical", "computer science", "information technology",
    "information systems", "informatics", "ict", "computing", "statistics",
    "data science", "data analytics", "analytics", "actuarial", "quantitative", "software",
]
GENERIC_ROLES = {"internship", "traineeship", "graduate programme", "learnership"}
GENERIC_BOOSTS = {"graduate", "junior", "entry level", "internship", "bsc", "honours", "postgraduate"}
_REQ = re.compile(r"\b(degree|diploma|qualification|bsc|b\.sc|bcom|b\.com|honours|nqf)\b", re.I)
_HEAD = re.compile(r"\b(requirements?|qualifications?|minimum|must have|should have)\b", re.I)
_SCHOOL = re.compile(r"\b(matric|grade\s*1[0-2])\b", re.I)
_ANY = re.compile(
    r"\b(any|all|various|multiple)\s+(relevant\s+)?(degrees?|diplomas?|qualifications?|disciplines?|fields?)\b",
    re.I,
)
_NAMES_FIELD = re.compile(r"\b(degree|diploma|bachelor\S*|honours|qualification)s?\s+(in|of)\b", re.I)


def _has_phrase(text: str, phrase: str) -> bool:
    """Whole-word match for normal words; plain substring for things like 'c++'."""
    phrase = phrase.lower().strip()
    text = text.lower()
    if phrase and phrase[0].isalnum() and phrase[-1].isalnum():
        return re.search(r"\b" + re.escape(phrase) + r"\b", text) is not None
    return phrase in text


def _clean_role(role: str) -> str:
    return re.sub(r"\(.*?\)", "", role).strip().lower()


def _read_cv() -> str:
    text = MASTER_CV_PATH.read_text(encoding="utf-8")
    return re.sub(r"\[CONFIRM[^\]]*\]", " ", text)


def _experience_required(description: str, patterns) -> bool:
    """True only when a pattern like '5 years' sits next to the word 'experience'."""
    for p in patterns:
        p = re.escape(p.lower())
        if re.search(p + r".{0,40}experience|experience.{0,40}" + p, description, re.S):
            return True
    return False


def _requirement_text(description: str):
    """Collect the sentences that state qualification requirements, plus any list of fields
    that follows a heading ending in a colon. School-level (Matric / Grade 12) lines are skipped.
    Returns (text, listed) where listed means a field list was found."""
    lines = [ln.strip() for ln in (description or "").splitlines() if ln.strip()]
    chunks, listed = [], False
    for i, line in enumerate(lines):
        for sent in re.split(r"(?<=[.;])\s+", line):
            if _REQ.search(sent) and not _SCHOOL.search(sent):
                chunks.append(sent)
        if line.rstrip().endswith(":") and (_REQ.search(line) or _HEAD.search(line)):
            names_degree = bool(_REQ.search(line))
            for nxt in lines[i + 1:i + 13]:
                if len(nxt) > 120:
                    break
                if not _SCHOOL.search(nxt):
                    chunks.append(nxt)
                    if names_degree:
                        listed = True
    return " ".join(chunks), listed


def _fit_signal(description: str, fit_fields) -> int:
    """+1 if the requirements name one of your fields (or any degree); -1 if they explicitly name
    fields and none are yours; 0 if the ad says nothing specific."""
    req, listed = _requirement_text(description)
    if not req:
        return 0
    if _ANY.search(req) or any(_has_phrase(req, f) for f in fit_fields):
        return 1
    if listed or _NAMES_FIELD.search(req):
        return -1
    return 0


def _drop_reason(job, profile, today, include_closed):
    title = job.title or ""
    desc = (job.description or "").lower()
    if not include_closed and job.closing_date and job.closing_date < today:
        return "already closed"
    for kw in profile.get("exclude_title_keywords", []) + profile.get("avoid_title_keywords", []):
        if _has_phrase(title, kw):
            return "excluded word in title"
    if _experience_required(desc, profile.get("exclude_description_patterns", [])):
        return "asks for too much experience"
    loc = (job.location or "").lower()
    accepted = [a.lower() for a in profile.get("accepted_locations", [])]
    if loc and accepted and not any(a in loc for a in accepted):
        return "location not accepted"
    return None


def _job_text(job) -> str:
    return " ".join([(job.title or "")] * 3 + [job.company or "", job.description or ""])


def rank_jobs(jobs, include_closed=False):
    """Filter, then score. Returns (list of (job, score, why) best first, dict of drop reasons).

    Scores are for ranking only: relative to the other ads in this run, not percentages.
    """
    profile = load_profile()
    cv_text = _read_cv()
    today = date.today()
    fit_fields = profile.get("fit_fields") or DEFAULT_FIT_FIELDS

    kept, dropped = [], {}
    for job in jobs:
        reason = _drop_reason(job, profile, today, include_closed)
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
        else:
            kept.append(job)
    if not kept:
        return [], dropped

    roles = [_clean_role(r) for r in profile.get("target_roles", [])]
    boosts = profile.get("boost_keywords", [])
    profile_text = " ".join([cv_text] + roles + boosts)
    domain_terms = (
        {f.lower() for f in fit_fields}
        | {b.lower() for b in boosts if b.lower() not in GENERIC_BOOSTS}
        | {r for r in roles if r and r not in GENERIC_ROLES}
    )
    gated = []
    for job in kept:
        text = f"{job.title or ''} {job.description or ''}"
        if _fit_signal(job.description, fit_fields) == 1 or any(_has_phrase(text, t) for t in domain_terms):
            gated.append(job)
        else:
            dropped["no sign of your field"] = dropped.get("no sign of your field", 0) + 1
    kept = gated
    if not kept:
        return [], dropped

    docs = [profile_text] + [_job_text(j) for j in kept]
    matrix = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True).fit_transform(docs)
    sims = linear_kernel(matrix[0:1], matrix[1:]).ravel()
    top = float(sims.max()) or 1.0

    scored = []
    for job, sim in zip(kept, sims):
        text = f"{job.title or ''} {job.description or ''}"
        hits = sum(1 for k in boosts if _has_phrase(text, k))
        role = any(_has_phrase(job.title or "", r) for r in roles if r and r not in GENERIC_ROLES)
        fit = _fit_signal(job.description, fit_fields)
        sim_rel = float(sim) / top

        score = (
            0.5 * sim_rel
            + min(0.15, 0.01 * hits)
            + (0.10 if role else 0.0)
            + (0.15 if fit == 1 else -0.15 if fit == -1 else 0.0)
        )
        why = [f"text match {sim_rel:.2f}"]
        if hits:
            why.append(f"{hits} skill keywords")
        if role:
            why.append("role title match")
        if fit == 1:
            why.append("degree field fits")
        elif fit == -1:
            why.append("degree field not yours")
        scored.append((job, score, why))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored, dropped