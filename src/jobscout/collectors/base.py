import time
import urllib.robotparser
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Optional
from urllib.parse import urlparse

import requests

from jobscout.config import RAW_DIR, SETTINGS

HTTP = SETTINGS["http"]
BOT_CHECK_MARKERS = ("One moment, please...", "Just a moment...", "Attention Required")


class BotCheckError(RuntimeError):
    """The site served a bot-check page. We stop and never try to bypass it."""


class RobotsDisallowed(RuntimeError):
    """robots.txt does not allow this URL for our user agent."""


@dataclass
class JobPosting:
    source: str
    url: str
    title: str
    company: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    closing_date: Optional[date] = None


class PoliteClient:
    """requests wrapper: honest user agent, robots.txt check, delay between requests."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = HTTP["user_agent"]
        self.delay = HTTP["delay_seconds"]
        self.timeout = HTTP["timeout_seconds"]
        self._robots = {}
        self._last_request = 0.0

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser:
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            resp = self.session.get(base + "/robots.txt", timeout=self.timeout)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            elif resp.status_code in (404, 410):
                rp.parse(["User-agent: *", "Allow: /"])
            else:
                raise RobotsDisallowed(f"Could not read robots.txt for {base} (HTTP {resp.status_code})")
            self._robots[base] = rp
        return self._robots[base]

    def get(self, url: str) -> str:
        if not self._robots_for(url).can_fetch("jobscout", url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        wait = self.delay - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        resp = self.session.get(url, timeout=self.timeout)
        self._last_request = time.time()
        resp.raise_for_status()
        if any(marker in resp.text[:3000] for marker in BOT_CHECK_MARKERS):
            raise BotCheckError(f"Bot-check page served for {url}")
        return resp.text


def save_raw(name: str, html: str) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / name).write_text(html, encoding="utf-8")


class Collector(ABC):
    name: str = ""

    def __init__(self, client: Optional[PoliteClient] = None):
        self.client = client or PoliteClient()

    @abstractmethod
    def collect(self) -> list[JobPosting]:
        """Return the job postings found on this source."""