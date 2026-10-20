import re
from datetime import date, datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from jobscout.collectors.base import BotCheckError, Collector, JobPosting, RobotsDisallowed
from jobscout.config import SOURCES

_DAYFIRST = re.compile(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})")


def parse_dayfirst_date(text: str) -> Optional[date]:
    """Parse '31 Oct 2026' or '30 October 2026'."""
    m = _DAYFIRST.search(text or "")
    if not m:
        return None
    day, mon, year = m.groups()
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(f"{day} {mon} {year}", fmt).date()
        except ValueError:
            continue
    return None


def _clean(text: str) -> str:
    return re.sub(r"[ \t\r\f\v\u00a0]+", " ", text or "").strip()


def _text_of(el) -> str:
    """Readable text with paragraph breaks; Cloudflare-obfuscated emails become [email]."""
    for a in el.select("a[href^='/cdn-cgi/l/email-protection']"):
        a.replace_with("[email]")
    for span in el.select(".__cf_email__"):
        span.replace_with("[email]")
    lines = (_clean(line) for line in el.get_text("\n", strip=True).splitlines())
    return "\n".join(line for line in lines if line)


def parse_listing(html: str) -> list[dict]:
    """Read the job cards from a category page (sidebar widgets are ignored)."""
    soup = BeautifulSoup(html, "lxml")
    cards = []
    for card in soup.select("div.g24-job-card"):
        link = card.select_one("a.g24-card-link") or card.find("a", href=True)
        title_el = card.select_one(".g24-card-title")
        if not link or not title_el:
            continue
        for badge in title_el.select(".g24-badge-new"):
            badge.decompose()
        location = closing = posted = None
        for span in card.select(".g24-card-meta span"):
            text = _clean(span.get_text(" ", strip=True))
            if span.select_one("i.fa-map-marker"):
                location = text
            elif span.select_one("i.fa-calendar-times-o"):
                closing = parse_dayfirst_date(text)
            elif span.select_one("i.fa-clock-o"):
                posted = parse_dayfirst_date(text)
        excerpt = card.select_one(".g24-card-excerpt")
        cards.append({
            "url": urljoin("https://www.graduates24.com", link["href"]),
            "title": _clean(title_el.get_text(" ", strip=True)),
            "location": location,
            "closing_date": closing,
            "posted": posted,
            "excerpt": _clean(excerpt.get_text(" ", strip=True)) if excerpt else None,
        })
    return cards


def _meta_content(soup, itemprop: str) -> Optional[str]:
    el = soup.select_one(f'meta[itemprop="{itemprop}"]')
    return el.get("content") if el else None


def parse_detail(html: str) -> dict:
    """Read one ad page: title, company, location, dates and the ad text."""
    soup = BeautifulSoup(html, "lxml")
    out = {}

    h1 = soup.select_one("h1.g24-show-title")
    out["title"] = _clean(h1.get_text(" ", strip=True)) if h1 else None

    org = soup.select_one('[itemprop="hiringOrganization"] [itemprop="name"]')
    if org is None:
        icon = soup.select_one(".g24-show-meta-list i.fa-building-o")
        org = icon.parent if icon else None
    out["company"] = _clean(org.get_text(" ", strip=True)) if org else None

    loc = soup.select_one('[itemprop="jobLocation"] [itemprop="addressLocality"]')
    out["location"] = _clean(loc.get_text(" ", strip=True)) if loc else None

    closing = _meta_content(soup, "validThrough")
    out["closing_date"] = None
    if closing:
        try:
            out["closing_date"] = date.fromisoformat(closing[:10])
        except ValueError:
            pass
    posted = _meta_content(soup, "datePosted")
    out["posted"] = None
    if posted:
        try:
            out["posted"] = date.fromisoformat(posted[:10])
        except ValueError:
            pass
    out["employment_type"] = _meta_content(soup, "employmentType")

    description = None
    for sel in ('[itemprop="description"]', ".g24-show-description", ".g24-show-body", ".g24-show-content"):
        el = soup.select_one(sel)
        if el is not None:
            text = _text_of(el)
            if len(text) > 200:
                description = text
                break
    if description is None:
        # Fallback: paragraphs and list items of the page, minus navigation and sidebars.
        for junk in soup.select(
            "header, footer, nav, .modal, .g24-sidebar-card, .g24-mobile-related, "
            ".g24-show-header, .g24-show-actions, .g24-share-menu, .g24-job-summary"
        ):
            junk.decompose()
        parts = [_text_of(el) for el in soup.select("main p, main li")]
        description = "\n".join(p for p in parts if p)
    if description and out.get("title") and description.startswith(out["title"]):
        description = description[len(out["title"]):].lstrip()
    out["description"] = description or None
    return out


class Graduates24Collector(Collector):
    name = "graduates24"

    def __init__(self, client=None, known_urls=None, max_pages=None, max_details=None):
        super().__init__(client)
        cfg = SOURCES["sources"]["graduates24"]
        self.base = cfg["base_url"].rstrip("/")
        self.pages = cfg["pages"]
        self.max_pages = max_pages or cfg.get("max_pages", 2)
        self.max_details = max_details
        self.known_urls = known_urls or set()
        self.cards_seen = 0

    def collect(self) -> list[JobPosting]:
        cards = {}
        for path in self.pages:
            for n in range(1, self.max_pages + 1):
                url = f"{self.base}{path}" + (f"?page={n}" if n > 1 else "")
                try:
                    html = self.client.get(url)
                except BotCheckError:
                    raise
                except RobotsDisallowed as e:
                    print(f"[graduates24] skipped: {e}")
                    continue
                except requests.RequestException as e:
                    print(f"[graduates24] request failed for {url}: {e}")
                    break
                found = parse_listing(html)
                if not found:
                    print(f"[graduates24] no job cards found on {url}")
                    break
                for card in found:
                    cards.setdefault(card["url"], card)

        self.cards_seen = len(cards)
        today = date.today()
        todo = [
            c for u, c in cards.items()
            if u not in self.known_urls and not (c["closing_date"] and c["closing_date"] < today)
        ]
        if self.max_details is not None:
            todo = todo[: self.max_details]

        postings = []
        for card in todo:
            detail = {}
            try:
                detail = parse_detail(self.client.get(card["url"]))
            except BotCheckError:
                raise
            except (RobotsDisallowed, requests.RequestException) as e:
                print(f"[graduates24] detail page failed: {card['url']} ({e})")
            if not detail.get("description"):
                # Never store the card excerpt as the ad text; unsaved ads are retried next run.
                print(f"[graduates24] no full description, skipped: {card['url']}")
                continue
            postings.append(JobPosting(
                source=self.name,
                url=card["url"],
                title=detail.get("title") or card["title"],
                company=detail.get("company"),
                location=detail.get("location") or card["location"],
                description=detail["description"],
                closing_date=detail.get("closing_date") or card["closing_date"],
            ))
        return postings