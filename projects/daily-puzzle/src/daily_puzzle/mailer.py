"""Email: double opt-in, magic links, the daily puzzle and operator escalations.

Sends through Resend's HTTP API when RESEND_API_KEY is set; otherwise (offline, CI, the operator demo) every message
is written to output/outbox/ instead. Either way a row goes in the `outbox` table (recipient as a hash only).
Daily emails carry one-click unsubscribe headers (RFC 8058) and go only to confirmed, subscribed players of that
track whose address isn't on the suppression list. Emails never contain an answer before the puzzle closes.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from sqlalchemy import select

from . import telemetry
from .config import TRACK_LABEL, Settings, data_dir
from .store import now, outbox, suppression


def email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def public_url() -> str:
    """Where players reach the site: PUZZLE_PUBLIC_URL, else the demos host + /daily-puzzle, else localhost."""
    if os.getenv("PUZZLE_PUBLIC_URL"):
        return os.environ["PUZZLE_PUBLIC_URL"].rstrip("/")
    if os.getenv("PORTFOLIO_DEMOS_URL") and "REPLACE" not in os.environ["PORTFOLIO_DEMOS_URL"]:
        return os.environ["PORTFOLIO_DEMOS_URL"].rstrip("/") + "/daily-puzzle"
    return f"http://localhost:{os.getenv('PORT', '8800')}"


def suppressed(conn, email: str) -> bool:
    return conn.execute(select(suppression.c.email_hash).where(suppression.c.email_hash == email_hash(email))).first() is not None


def send(conn, to: str, kind: str, subject: str, text: str, unsubscribe_url: str | None = None,
         transactional: bool = False) -> str:
    """Send (or write) one email. Returns the outbox status."""
    telemetry.require_enabled("email")
    if not transactional and suppressed(conn, to):
        status, pid = "suppressed", None
    elif os.getenv("RESEND_API_KEY"):
        status, pid = _resend(to, subject, text, unsubscribe_url)
    else:
        status, pid = _write(to, kind, subject, text, unsubscribe_url)
    conn.execute(outbox.insert().values(to_hash=email_hash(to), kind=kind, subject=subject[:200], status=status,
                                        provider_id=(pid or "")[:200] or None, at=now()))
    return status


def _resend(to, subject, text, unsub) -> tuple[str, str | None]:
    import httpx
    body = {"from": os.getenv("MAIL_FROM", "Daily puzzle <puzzle@example.com>"), "to": [to], "subject": subject,
            "text": text}
    if unsub:
        body["headers"] = {"List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    try:
        r = httpx.post("https://api.resend.com/emails", json=body, timeout=15,
                       headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"})
    except Exception as e:  # noqa: BLE001 — a mail failure must not stop the daily cycle
        why = f"{type(e).__name__}: {e}"[:200]
        print(f"email to {email_hash(to)[:8]} failed: {why}")
        return "failed", why
    if r.status_code >= 300:          # e.g. 403 "domain is not verified", 422 bad from-address: keep the reason
        try:
            msg = r.json().get("message") or r.text
        except ValueError:
            msg = r.text
        why = f"HTTP {r.status_code}: {msg}"[:200]
        print(f"email to {email_hash(to)[:8]} failed: {why}")
        return "failed", why
    return "sent", r.json().get("id")


def outbox_dir() -> Path:
    d = data_dir() / "output" / "outbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(to, kind, subject, text, unsub) -> tuple[str, str]:
    d = outbox_dir()
    n = len(list(d.glob("*.eml"))) + 1
    name = f"{n:05d}-{kind}-{re.sub(r'[^a-z0-9]+', '-', to.lower())[:40]}.eml"
    hdr = f"To: {to}\nSubject: {subject}\n" + (f"List-Unsubscribe: <{unsub}>\n" if unsub else "")
    (d / name).write_text(hdr + "\n" + text)
    return "written", name


# ---------------------------------------------------------------- messages
FOOT = "\n\n—\nYou get this because you subscribed to the daily puzzle. Change tracks or delete your account: {me}\nUnsubscribe in one click: {unsub}\n"


def confirm(conn, email: str, handle: str, link: str) -> str:
    return send(conn, email, "confirm", "Confirm your daily puzzle subscription",
                f"Hi {handle},\n\nConfirm your subscription to the daily puzzle:\n{link}\n\n"
                "If you didn't sign up, ignore this email and nothing will be sent again.", transactional=True)


def signin(conn, email: str, link: str, minutes: int) -> str:
    return send(conn, email, "signin", "Your daily puzzle sign-in link",
                f"Sign in to the daily puzzle (link valid for {minutes} minutes, one use):\n{link}\n\n"
                "If you didn't ask for this, ignore it.", transactional=True)


def daily(conn, s: Settings, puzzle: dict, recipients: list[dict], prev: dict | None, links) -> dict:
    """The morning email to each subscriber of the puzzle's track. `links(player)` → (play, me, unsub) URLs."""
    sent = {"sent": 0, "written": 0, "suppressed": 0, "failed": 0}
    teaser = puzzle["statement"]
    teaser = teaser if len(teaser) < 700 else teaser[:700].rsplit(" ", 1)[0] + " …"
    for p in recipients:
        play, me, unsub = links(p)
        body = (f"Hi {p['handle']},\n\nToday's puzzle — {TRACK_LABEL[puzzle['track']]} · {puzzle['difficulty']}\n"
                f"{puzzle['title']}\n\n{teaser}\n\nAccept it and answer here: {play}\n"
                f"Submissions close at {s.puzzles['window']['close_at']} ({s.puzzles['window']['timezone']}).")
        if puzzle.get("learning_objective"):
            body += f"\n\nWhat it teaches: {puzzle['learning_objective']}"
        if prev:
            body += f"\n\nYesterday's answer ({prev['title']}) is now public: {public_url()}/p/{prev['id']}"
        st = send(conn, p["email"], "daily", f"Daily puzzle: {puzzle['title']}", body + FOOT.format(me=me, unsub=unsub),
                  unsubscribe_url=unsub)
        sent[st] = sent.get(st, 0) + 1
    return sent


def escalation(conn, s: Settings, day: str, escalated_id: int | None, rounds: list[dict], reserve_id: int | None) -> None:
    to = os.getenv(s["governance"]["operator_email_env"], "")
    reasons = "\n".join(f"  round {r['round']}: " + "; ".join(r.get("reasons") or ["?"]) for r in rounds)
    text = (f"The generator couldn't produce a verified puzzle for {day}.\n\n{reasons}\n\n"
            + (f"A reserve puzzle (#{reserve_id}) was scheduled instead.\n" if reserve_id else
               "There was NO reserve puzzle left: no puzzle will open today. Run `puzzle reserve`.\n")
            + (f"Review the failed draft: {public_url()}/admin#p{escalated_id}\n" if escalated_id else ""))
    if to:
        send(conn, to, "escalation", f"Daily puzzle escalation for {day}", text, transactional=True)
    else:
        _write("operator@localhost", "escalation", f"Daily puzzle escalation for {day}", text, None)
