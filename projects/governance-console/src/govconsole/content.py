"""Content governance: what visitors rate and suggest on the portfolio site, and what the owner lets them see.

The site assistant service owns the data (thumbs up on posts, project suggestions and their upvotes). The console
reads it through the assistant's owner API and changes a suggestion's status there:

  pending    new; not shown on the site (the default until approved, unless the assistant sets auto_publish)
  published  shown on the Suggestions page and open for upvotes
  hidden     not shown (spam, duplicate, not a fit)
  done       built or declined for good; not shown, kept for the record

    ASSISTANT_URL           e.g. http://site-assistant:7860 inside the self-host stack
    ASSISTANT_ADMIN_TOKEN   the assistant's owner token (falls back to GOVERNANCE_ADMIN_TOKEN)
"""
from __future__ import annotations

import os

import httpx

STATUSES = ("pending", "published", "hidden", "done")


def assistant_url() -> str:
    return os.getenv("ASSISTANT_URL", "").rstrip("/")


def _token() -> str:
    return os.getenv("ASSISTANT_ADMIN_TOKEN") or os.getenv("GOVERNANCE_ADMIN_TOKEN") or ""


def fetch() -> dict:
    """{"top_articles": [...], "suggestions": [...], "kickoff": {id: links}} or {"error": "..."}."""
    if not assistant_url():
        return {"error": "not connected (set ASSISTANT_URL)"}
    try:
        r = httpx.get(f"{assistant_url()}/admin/content", params={"token": _token()}, timeout=8)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001 — the page says so; nothing else breaks
        return {"error": f"the site assistant didn't answer ({type(e).__name__})"}


def set_status(sid: int, status: str, actor: str) -> dict:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    r = httpx.post(f"{assistant_url()}/admin/suggestions/{sid}", params={"token": _token()},
                   json={"status": status, "actor": actor}, timeout=8)
    r.raise_for_status()
    return r.json()
