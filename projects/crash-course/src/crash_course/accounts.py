"""Learners: magic-link sign-in (no passwords), signed session cookies, delete-my-data.

The email address is stored for sign-in and notifications only. A sign-in token is stored as a hash, works once and
expires (registration.magic_link_minutes). Registration is open by default; set registration.open=false and give
invite codes in COURSE_INVITE_CODES (comma-separated) to make it invite-only.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from . import mailer, telemetry
from .config import Settings
from .store import insert, now, one

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,24}$", re.I)


class SignupClosed(Exception):
    pass


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_owner_email(s: Settings, email: str) -> bool:
    owner = mailer.owner_email(s).strip().lower()
    return bool(owner) and email.strip().lower() == owner


def request_link(conn, s: Settings, email: str, name: str = "", invite: str = "") -> str:
    """Create the learner if new (open sign-up or a valid invite) and email a one-use link. Returns the link
    (shown on screen only in the offline demo, where no email is sent)."""
    email = email.strip().lower()
    if not EMAIL.match(email):
        raise ValueError("enter a valid email address")
    row = one(conn, "SELECT * FROM learners WHERE email=?", email)
    if not row:
        reg = s["registration"]
        codes = [c.strip() for c in os.getenv(reg["invite_codes_env"], "").split(",") if c.strip()]
        if not reg["open"] and not (invite and any(hmac.compare_digest(invite, c) for c in codes)):
            raise SignupClosed("sign-up is by invitation")
        name = re.sub(r"[^\w .'-]", "", name).strip()[:40] or email.split("@")[0][:40]
        lid = insert(conn, "learners", email=email, name=name, created_at=now(), last_seen=now(),
                     is_owner=int(is_owner_email(s, email)))
        telemetry.record("register", items=1)
    else:
        lid = row["id"]
    token = secrets.token_urlsafe(24)
    exp = datetime.now(timezone.utc) + timedelta(minutes=s["registration"]["magic_link_minutes"])
    insert(conn, "login_tokens", token_hash=_h(token), learner_id=lid, expires_at=exp.isoformat())
    link = f"{mailer.public_url()}/auth?t={token}"
    mailer.signin(conn, email, link, s["registration"]["magic_link_minutes"])
    return link


def consume(conn, token: str) -> int | None:
    row = one(conn, "SELECT * FROM login_tokens WHERE token_hash=?", _h(token or ""))
    if not row or row["used_at"] or datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        return None
    conn.execute("UPDATE login_tokens SET used_at=? WHERE token_hash=?", (now(), row["token_hash"]))
    conn.execute("UPDATE learners SET last_seen=? WHERE id=?", (now(), row["learner_id"]))
    return row["learner_id"]


def session_value(lid: int, days: int) -> str:
    exp = str(int(time.time()) + days * 86400)
    return f"{lid}.{exp}.{mailer.sign('session', str(lid), exp)}"


def session_learner(v: str | None) -> int | None:
    try:
        lid, exp, sig = (v or "").split(".")
        if int(exp) > time.time() and hmac.compare_digest(sig, mailer.sign("session", lid, exp)):
            return int(lid)
    except ValueError:
        pass
    return None


def delete(conn, lid: int) -> None:
    """Delete-my-data: every row that belongs to the learner (DATA-03, OBS-03)."""
    for table, col in (("login_tokens", "learner_id"), ("enrollments", "learner_id"), ("progress", "learner_id"),
                       ("attempts", "learner_id"), ("feedback", "learner_id"), ("suggestions", "learner_id"),
                       ("learners", "id")):
        conn.execute(f"DELETE FROM {table} WHERE {col}=?", (lid,))
    telemetry.record("delete_account", items=1)


def prune_inactive(conn, s: Settings) -> int:
    """OBS-03 retention: learners not seen for privacy.inactive_retention_days are deleted."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=s["privacy"]["inactive_retention_days"])).isoformat()
    ids = [r["id"] for r in conn.execute("SELECT id FROM learners WHERE last_seen < ? AND is_owner=0", (cutoff,))]
    for lid in ids:
        delete(conn, lid)
    return len(ids)
