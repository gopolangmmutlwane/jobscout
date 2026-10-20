import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


SETTINGS = _load_yaml(ROOT / "config" / "settings.yaml")
SOURCES = _load_yaml(ROOT / "config" / "sources.yaml")

PROFILE_PATH = ROOT / "data" / "profile" / "profile.yaml"
MASTER_CV_PATH = ROOT / "data" / "profile" / "master_cv.md"
RAW_DIR = ROOT / "data" / "raw"
CV_OUTPUT_DIR = ROOT / "data" / "output" / "cvs"
DIGEST_DIR = ROOT / "data" / "output" / "digests"

DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{(ROOT / 'jobscout.db').as_posix()}"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")

WEB_PIN = os.getenv("WEB_PIN", "")
WEB_SECRET_KEY = os.getenv("WEB_SECRET_KEY", "")
WEB_PORT = int(os.getenv("WEB_PORT") or 8765)
WEB_BASE_URL = os.getenv("WEB_BASE_URL", "").rstrip("/")


def load_profile() -> dict:
    return _load_yaml(PROFILE_PATH)