"""Settings, paths and environment overrides."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]          # the project folder (config/, prompts/, fixtures/ live here)


@lru_cache(maxsize=1)
def settings() -> dict:
    s = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
    if os.getenv("EDITORIAL_QUEUE_SIZE"):
        s["queue"]["size"] = int(os.environ["EDITORIAL_QUEUE_SIZE"])
    if os.getenv("EDITORIAL_DIGEST_DAY"):
        s["schedule"]["digest_weekday"] = os.environ["EDITORIAL_DIGEST_DAY"].lower()[:3]
    return s


def feeds() -> list[dict]:
    rel = settings()["sources"]["rss"]["feeds"]
    return (yaml.safe_load((ROOT / rel).read_text()) or {}).get("feeds", [])


def data_dir() -> Path:
    d = Path(os.getenv("EDITORIAL_DATA", ROOT / "warehouse"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def public_url() -> str:
    """Where the service is reached from email links: EDITORIAL_PUBLIC_URL, else demos host + /editorial-agents."""
    if os.getenv("EDITORIAL_PUBLIC_URL"):
        return os.environ["EDITORIAL_PUBLIC_URL"].rstrip("/")
    demos = os.getenv("PORTFOLIO_DEMOS_URL", "")
    if demos and "REPLACE" not in demos:
        return demos.rstrip("/") + "/editorial-agents"
    return f"http://localhost:{os.getenv('PORT', '8810')}"


def site_url() -> str:
    return (os.getenv("PORTFOLIO_SITE_URL") or os.getenv("SITE_URL") or "").rstrip("/")


def repo() -> str:
    """owner/name of the blog repo whose pull requests carry draft posts."""
    return os.getenv("EDITORIAL_REPO") or (os.getenv("PORTFOLIO_GITHUB_OWNER", "") + "/ai-portfolio").lstrip("/")


def owner_email() -> list[str]:
    raw = os.getenv("EDITORIAL_EMAIL") or os.getenv("DIGEST_EMAIL") or os.getenv("GOVERNANCE_ALERT_EMAIL") or ""
    return [a.strip() for a in raw.split(",") if a.strip()]


def link_secret() -> bytes:
    """HMAC key for the pick / dismiss links. The live service refuses to start without one (SEC-01)."""
    s = os.getenv("EDITORIAL_LINK_SECRET", "")
    if not s:
        if os.getenv("EDITORIAL_REQUIRE_SECRETS") == "1":
            raise RuntimeError("EDITORIAL_LINK_SECRET is required in the live service (openssl rand -hex 32)")
        s = "dev-only-not-secret"
    return s.encode()
