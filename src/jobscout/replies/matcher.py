"""Link a reply to one of your Applied jobs.

(a) Company name tokens in the sender display name, sender domain, subject or the first 2000 characters
of the body. Mail from applicant-tracking systems (Workday, Greenhouse, ...) does not identify the
company by sender, so for those only the subject and body count.
(b) The job title's distinctive words or the ad's reference number in the subject.
"""
import re
from dataclasses import dataclass

BODY_CHARS = 2000
MIN_SCORE = 0.35

# Sender domains that belong to recruitment platforms, not employers.
ATS_DOMAINS = (
    "greenhouse.io", "greenhouse-mail.io", "myworkday.com", "myworkdayjobs.com", "workday.com",
    "successfactors.com", "successfactors.eu", "sapsf.com", "sapsf.eu", "smartrecruiters.com",
    "lever.co", "hire.lever.co", "bamboohr.com", "pnet.co.za", "careerjunction.co.za", "careers24.com",
    "icims.com", "taleo.net", "oracle.com", "oraclecloud.com", "jobvite.com", "teamtailor.com",
    "teamtailor-mail.com", "recruitee.com", "workable.com", "workablemail.com", "breezy.hr",
    "jazzhr.com", "applytojob.com", "linkedin.com", "indeed.com", "indeedemail.com", "adzuna.co.za",
    "graduates24.com", "jobmail.co.za", "offerzen.com", "simplify.hr", "hirevue.com", "shl.com",
    "talentq.com", "pinpointhq.com", "zohorecruit.com", "ashbyhq.com", "jobadder.com", "erecruit.co",
    "e-recruiter.co.za", "mail.com", "gmail.com", "outlook.com", "hotmail.com", "yahoo.com",
)

# Words that say nothing about which company it is.
GENERIC_WORDS = {
    "the", "and", "of", "for", "pty", "ltd", "limited", "inc", "group", "holdings", "company", "co",
    "south", "africa", "african", "sa", "za", "international", "services", "service", "solutions",
    "technologies", "technology", "tech", "consulting", "consultants", "bank", "financial", "finance",
    "professional", "software", "systems", "global", "management", "partners", "careers", "career",
    "recruitment", "talent", "jobs", "job", "hr", "people", "t/a", "ta",
    "graduate", "graduates", "programme", "program", "internship", "internships", "intern", "interns",
    "learnership", "learnerships", "opportunity", "opportunities", "trainee", "junior", "entry", "level",
    "2025", "2026", "2027", "2028", "role", "position", "vacancy", "new", "early",
}

_WORD = re.compile(r"[a-z0-9][a-z0-9&+]*")
_REF = re.compile(r"\bref(?:erence)?(?:\s*(?:no|number|nr|#))?\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/_\-.&]{3,})", re.I)


@dataclass
class Match:
    job_id: int
    confidence: float
    reason: str


def _words(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def company_tokens(company: str) -> list[str]:
    """Distinctive words of the company name ('Lesaka Technologies' -> ['lesaka'])."""
    words = [w for w in _words(company) if len(w) >= 3 and w not in GENERIC_WORDS]
    if words:
        return words
    full = " ".join(_words(company))
    return [full] if len(full) >= 3 else []


def title_tokens(title: str, company: str) -> list[str]:
    skip = set(_words(company))
    return [w for w in _words(title) if len(w) >= 4 and w not in GENERIC_WORDS and w not in skip]


def references(description: str) -> list[str]:
    return [m.group(1).strip(".-").lower() for m in _REF.finditer(description or "")][:5]


def is_ats(domain: str) -> bool:
    domain = (domain or "").lower()
    return any(domain == d or domain.endswith("." + d) for d in ATS_DOMAINS)


def _has_token(text: str, token: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", text) is not None


def _score(job, from_name, domain, subject, body, ats):
    reasons, score = [], 0.0
    tokens = company_tokens(job.company or "")
    if tokens:
        name_l, subj_l, body_l = (from_name or "").lower(), (subject or "").lower(), (body or "")[:BODY_CHARS].lower()
        domain_labels = (domain or "").lower().split(".")
        hits = []
        compact = [t.replace(" ", "") for t in tokens]
        if not ats and any(label == t or (len(t) >= 5 and t in label) for t in compact for label in domain_labels):
            hits.append(("sender domain", 0.6))
        if not ats and any(_has_token(name_l, t) for t in tokens):
            hits.append(("sender name", 0.55))
        if any(_has_token(subj_l, t) for t in tokens):
            hits.append(("subject", 0.5))
        if any(_has_token(body_l, t) for t in tokens):
            hits.append(("body", 0.35))
        if hits:
            best = max(w for _p, w in hits)
            score += best + 0.05 * (len(hits) - 1)
            reasons.append("company '" + " ".join(tokens) + "' in " + ", ".join(p for p, _w in hits))
    subj_words = set(_words(subject))
    t_tokens = title_tokens(job.title or "", job.company or "")
    if t_tokens:
        found = [t for t in t_tokens if t in subj_words]
        if found:
            frac = len(found) / len(t_tokens)
            score += 0.3 * frac
            reasons.append(f"title words in subject ({', '.join(found)})")
    subj_l = (subject or "").lower()
    refs = [r for r in references(job.description) if r in subj_l]
    if refs:
        score += 0.4
        reasons.append(f"reference {refs[0]} in subject")
    return score, reasons


def match(from_addr, from_name, subject, body, jobs) -> Match | None:
    """Best Applied job for this message, or None. jobs: Job rows with status 'applied'."""
    domain = (from_addr or "").rsplit("@", 1)[-1].lower()
    ats = is_ats(domain)
    scored = []
    for job in jobs:
        score, reasons = _score(job, from_name, domain, subject, body, ats)
        if score >= MIN_SCORE:
            scored.append((score, job, reasons))
    if not scored:
        return None
    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, best_job, reasons = scored[0]
    confidence = min(1.0, best_score)
    if ats:
        reasons.append(f"via {domain} (recruitment platform)")
    if len(scored) > 1:
        runner_up = scored[1][0]
        confidence *= max(0.3, 1 - runner_up / (best_score * 2))
        reasons.append(f"{len(scored)} applications matched; best chosen")
    return Match(job_id=best_job.id, confidence=round(confidence, 2), reason="; ".join(reasons)[:300])
