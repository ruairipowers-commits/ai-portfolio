"""Email: sign-in links, approval requests to the owner, and outcomes to learners.

Sends through Resend's HTTP API when RESEND_API_KEY is set; otherwise (offline, CI, the demo) every message is
written to <data>/output/outbox/ instead. Either way a row goes in the `outbox` table, with the recipient as a hash.

Approval links (HITL-02) are signed with COURSE_SECRET, expire (approvals.link_ttl_days) and open a confirmation
page with a button: a GET never decides anything, so a mail scanner that follows links can't approve a topic.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
import warnings
from pathlib import Path

from . import telemetry
from .config import Settings, data_dir
from .store import insert, now, one

_DEV_SECRET = "dev-only-secret-change-me"


def secret() -> str:
    v = os.getenv("COURSE_SECRET", "")
    if v:
        return v
    if os.getenv("COURSE_REQUIRE_SECRETS") == "1":
        raise RuntimeError("COURSE_SECRET is required in the live service (openssl rand -hex 32)")
    warnings.warn("COURSE_SECRET not set; using a development secret")
    return _DEV_SECRET


def sign(*parts: str) -> str:
    return hmac.new(secret().encode(), "|".join(parts).encode(), hashlib.sha256).hexdigest()[:32]


def signed_link(kind: str, ref: str, decision: str, ttl_days: int) -> str:
    exp = str(int(time.time()) + ttl_days * 86400)
    return f"{public_url()}/owner/decide?k={kind}&r={ref}&d={decision}&e={exp}&sig={sign(kind, ref, decision, exp)}"


def verify(kind: str, ref: str, decision: str, exp: str, sig: str) -> bool:
    try:
        fresh = int(exp) > time.time()
    except ValueError:
        return False
    return fresh and hmac.compare_digest(sig or "", sign(kind, ref, decision, exp))


def email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def public_url() -> str:
    if os.getenv("COURSE_PUBLIC_URL"):
        return os.environ["COURSE_PUBLIC_URL"].rstrip("/")
    if os.getenv("PORTFOLIO_DEMOS_URL") and "REPLACE" not in os.environ["PORTFOLIO_DEMOS_URL"]:
        return os.environ["PORTFOLIO_DEMOS_URL"].rstrip("/") + "/crash-course"
    return f"http://localhost:{os.getenv('PORT', '8810')}" + os.getenv("ROOT_PATH", "").rstrip("/")


def owner_email(s: Settings) -> str:
    return os.getenv(s["approvals"]["owner_email_env"], "")


def send(conn, to: str, kind: str, subject: str, text: str) -> str:
    telemetry.require_enabled("email")
    if os.getenv("RESEND_API_KEY"):
        status = _resend(to, subject, text)
    else:
        status = _write(to, kind, subject, text)
    insert(conn, "outbox", to_hash=email_hash(to), kind=kind, subject=subject[:200], status=status, at=now())
    return status


def _resend(to: str, subject: str, text: str) -> str:
    import httpx
    body = {"from": os.getenv("MAIL_FROM", "Crash course <courses@example.com>"), "to": [to], "subject": subject,
            "text": text}
    try:
        r = httpx.post("https://api.resend.com/emails", json=body, timeout=15,
                       headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"})
    except Exception as e:  # noqa: BLE001 — a mail failure must not break the request
        print(f"email to {email_hash(to)[:8]} failed: {type(e).__name__}")
        return "failed"
    if r.status_code >= 300:
        print(f"email to {email_hash(to)[:8]} failed: HTTP {r.status_code}")
        return "failed"
    return "sent"


def outbox_dir() -> Path:
    d = data_dir() / "output" / "outbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(to: str, kind: str, subject: str, text: str) -> str:
    d = outbox_dir()
    n = len(list(d.glob("*.eml"))) + 1
    (d / f"{n:05d}-{kind}-{re.sub(r'[^a-z0-9]+', '-', to.lower())[:40]}.eml").write_text(
        f"To: {to}\nSubject: {subject}\n\n{text}")
    return "written"


# ---------------------------------------------------------------- messages
def signin(conn, email: str, link: str, minutes: int) -> str:
    return send(conn, email, "signin", "Your crash course sign-in link",
                f"Sign in to Crash course (link valid for {minutes} minutes, one use):\n{link}\n\n"
                "If you didn't ask for this, ignore it.")


def approval_request(conn, s: Settings, sid: int, text: str, a) -> str:
    to = owner_email(s) or "owner@localhost"
    ttl = s["approvals"]["link_ttl_days"]
    body = (f"A new crash course topic was suggested (#{sid}):\n\n  {text.strip()}\n\n"
            f"Agent assessment: {a.verdict.upper()}\n"
            + "".join(f"  - {r}\n" for r in a.reasons)
            + (f"Categories: {', '.join(a.categories)}\n" if a.categories else "")
            + (f"Duplicate of: {a.duplicate_of}\n" if a.duplicate_of else "")
            + (f"Proposed title: {a.proposed_title}\n" if a.proposed_title else "")
            + ("Proposed outline:\n" + "".join(f"  - {o}\n" for o in a.proposed_outline) if a.proposed_outline else "")
            + f"\nApprove (you can edit the title and docs link first): {signed_link('suggestion', str(sid), 'approve', ttl)}\n"
            f"Reject: {signed_link('suggestion', str(sid), 'reject', ttl)}\n\n"
            f"Nothing is created until you approve. Links expire in {ttl} days; the operator app has the same queue.")
    return send(conn, to, "approval", f"Approve crash course topic #{sid}? ({a.verdict})", body)


def draft_ready(conn, s: Settings, course: str, level: str, report_ok: bool, problems: list[str]) -> str:
    to = owner_email(s) or "owner@localhost"
    ttl = s["approvals"]["link_ttl_days"]
    ref = f"{course}:{level}"
    body = (f"A draft of {course} / {level} is ready.\n\nContent checks: "
            + ("all passed" if report_ok else "FAILED:\n" + "".join(f"  - {p}\n" for p in problems[:10]))
            + f"\n\nReview it: {preview_link(course, level, ttl)}\n"
            + (f"Publish: {signed_link('level', ref, 'publish', ttl)}\n" if report_ok else "")
            + f"Reject: {signed_link('level', ref, 'reject', ttl)}\n")
    return send(conn, to, "draft", f"Crash course draft ready: {course} / {level}", body)


def suggestion_outcome(conn, s: Settings, learner_id: int, text: str, decision: str, slug: str | None) -> str | None:
    row = one(conn, "SELECT email, name FROM learners WHERE id=?", learner_id)
    if not row:
        return None
    if decision == "approve":
        msg = (f"Hi {row['name']},\n\nYour suggestion \"{text.strip()}\" was approved. Its first level is being "
               f"written now; it will appear in the catalog at {public_url()}/catalog once it's published.")
    else:
        msg = (f"Hi {row['name']},\n\nThanks for suggesting \"{text.strip()}\". It won't become a course this time. "
               f"You can suggest another topic at {public_url()}/suggest.")
    return send(conn, row["email"], "outcome", "Your crash course suggestion", msg)


def preview_link(course: str, level: str, ttl_days: int) -> str:
    exp = str(int(time.time()) + ttl_days * 86400)
    return f"{public_url()}/owner/preview/{course}/{level}?e={exp}&sig={sign('preview', course, level, exp)}"
