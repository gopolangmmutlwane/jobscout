import hashlib
import re
from datetime import date, datetime
from typing import Optional

from bs4 import BeautifulSoup

_DATE_RE = re.compile(r"([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})")


def clean_text(html_or_text: str) -> str:
    text = BeautifulSoup(html_or_text or "", "lxml").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def parse_closing_date(text: str) -> Optional[date]:
    """Parse text like 'Closing date: October 30, 2026 | 10 Days left'."""
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date()
    except ValueError:
        return None


def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def make_hash(title: str, company: Optional[str], description: Optional[str]) -> str:
    """Stable fingerprint so the same job on two sites is stored once."""
    if company:
        key = f"{_norm(title)}|{_norm(company)}"
    else:
        key = f"{_norm(title)}|{_norm(description)[:300]}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


_ADZUNA_ID = re.compile(r"adzuna\.[a-z.]+/(?:details|land/ad)/(\d+)")


def canonical_url(url: str) -> str:
    """Stable key for an ad link. Adzuna links carry changing tracking tokens, so use the ad id."""
    m = _ADZUNA_ID.search(url or "")
    if m:
        return f"adzuna:{m.group(1)}"
    return (url or "").split("#")[0].rstrip("/")
