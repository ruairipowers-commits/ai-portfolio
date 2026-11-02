"""Signed, expiring, single-use links for the owner's buttons (HITL-02, SEC-01): Pick / Dismiss in the topic email,
Approve / Archive in each draft post's email (postmail.py). The secret never leaves this service.

The link only opens a confirmation page; the change happens on a POST from that page. Email security scanners
follow GET links in messages, so a GET that changed state would pick topics on its own.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from .config import link_secret, settings

ACTIONS = ("pick", "dismiss", "unpick", "approve", "archive")
POST_ACTIONS = ("approve", "archive")       # act on a drafted post, not a queued topic


def sign(topic_id: str, action: str, ttl_days: int | None = None, now: float | None = None) -> str:
    if action not in ACTIONS:
        raise ValueError(action)
    days = ttl_days or settings()["links"]["post_ttl_days" if action in POST_ACTIONS else "ttl_days"]
    exp = int((now or time.time()) + 86400 * days)
    payload = f"{topic_id}|{action}|{exp}|{secrets.token_hex(6)}"
    mac = hmac.new(link_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}|{mac}".encode()).decode().rstrip("=")


def verify(token: str, now: float | None = None) -> dict:
    """{topic_id, action, nonce} or ValueError (bad signature, expired, malformed)."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        tid, action, exp, nonce, mac = raw.split("|")
    except Exception as e:  # noqa: BLE001
        raise ValueError("malformed link") from e
    want = hmac.new(link_secret(), f"{tid}|{action}|{exp}|{nonce}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(want, mac):
        raise ValueError("bad signature")
    if int(exp) < (now or time.time()):
        raise ValueError("link expired")
    if action not in ACTIONS:
        raise ValueError("unknown action")
    return {"topic_id": tid, "action": action, "nonce": nonce}
