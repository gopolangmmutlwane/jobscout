import json
import time

from jobscout.collectors.base import Collector, JobPosting
from jobscout.config import ADZUNA_APP_ID, ADZUNA_APP_KEY, ROOT, SOURCES
from jobscout.processing.cleaner import clean_text

API = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
USAGE_FILE = ROOT / "data" / "output" / "adzuna_usage.json"


def _load_usage() -> dict:
    try:
        return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"calls": 0, "paused": False}


def _save_usage(usage: dict) -> None:
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(usage), encoding="utf-8")


class AdzunaCollector(Collector):
    name = "adzuna"

    def __init__(self, client=None):
        super().__init__(client)
        cfg = SOURCES["sources"]["adzuna"]
        self.country = cfg.get("country", "za")
        self.queries = cfg.get("queries", [])
        self.max_days_old = cfg.get("max_days_old", 14)
        self.per_query = cfg.get("results_per_query", 50)
        self.call_limit = cfg.get("call_limit")  # None means no local cap

    def _pause(self, usage: dict, reason: str) -> None:
        usage["paused"] = True
        _save_usage(usage)
        print(f"[adzuna] paused: {reason}. Delete data/output/adzuna_usage.json to resume.")

    def collect(self) -> list[JobPosting]:
        if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
            raise RuntimeError("Set ADZUNA_APP_ID and ADZUNA_APP_KEY in .env")
        usage = _load_usage()
        if usage.get("paused"):
            return []

        postings, seen = [], set()
        for query in self.queries:
            if self.call_limit is not None and usage["calls"] >= self.call_limit:
                self._pause(usage, "free calls used up")
                break
            params = {
                "app_id": ADZUNA_APP_ID,
                "app_key": ADZUNA_APP_KEY,
                "results_per_page": self.per_query,
                "what": query,
                "max_days_old": self.max_days_old,
                "sort_by": "date",
                "content-type": "application/json",
            }
            resp = self.client.session.get(
                API.format(country=self.country, page=1),
                params=params,
                timeout=self.client.timeout,
            )
            usage["calls"] += 1
            _save_usage(usage)
            if resp.status_code == 401:
                raise RuntimeError("Adzuna rejected the keys (HTTP 401)")
            if resp.status_code in (403, 429):
                self._pause(usage, f"quota reached (HTTP {resp.status_code})")
                break
            resp.raise_for_status()
            time.sleep(self.client.delay)
            for r in resp.json().get("results", []):
                url = r.get("redirect_url")
                title = clean_text(r.get("title") or "")
                if not url or not title or url in seen:
                    continue
                seen.add(url)
                postings.append(JobPosting(
                    source=self.name,
                    url=url,
                    title=title,
                    company=(r.get("company") or {}).get("display_name"),
                    location=(r.get("location") or {}).get("display_name"),
                    description=clean_text(r.get("description") or "") or None,
                ))
        return postings