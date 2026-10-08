"""Players and play: subscribe (double opt-in), magic links, accept, submit, leaderboard, unsubscribe, delete.

Everything a player can trigger is code: their answer is normalized and compared with HMACs, never shown to a model.
"""
from __future__ import annotations

import hashlib
import os
import hmac
import re
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from . import grading, mailer, telemetry
from .config import TRACKS, Settings
from .store import acceptances, attempts, fetch_all, fetch_one, now, players, puzzles as P, suppression, tokens

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
HANDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{2,23}$")
RESERVED = {"admin", "administrator", "operator", "moderator", "official", "support", "ruairi", "ruairipowers",
            "dailypuzzle", "daily-puzzle", "system", "root"}
INJECTION = re.compile(r"ignore (all |any )?(previous|prior) instructions|system\s*:|mark (this|it) (as )?correct|"
                       r"show (me )?the answer|you are now", re.I)


class GameError(ValueError):
    pass


def _token(conn, pid: int, purpose: str, minutes: int | None) -> str:
    t = secrets.token_urlsafe(24)
    conn.execute(tokens.insert().values(token_hash=hashlib.sha256(t.encode()).hexdigest(), player_id=pid,
                                        purpose=purpose, expires_at=now() + timedelta(minutes=minutes) if minutes else None))
    return t


def use_token(conn, t: str, purpose: str) -> int | None:
    h = hashlib.sha256((t or "").encode()).hexdigest()
    row = fetch_one(conn, select(tokens).where(tokens.c.token_hash == h, tokens.c.purpose == purpose))
    if not row or row["used_at"] or (row["expires_at"] and row["expires_at"] < now()):
        return None
    conn.execute(update(tokens).where(tokens.c.token_hash == h).values(used_at=now()))
    return row["player_id"]


def unsub_token(pid: int) -> str:
    """Stateless one-click unsubscribe token (works forever, can't be guessed)."""
    key = grading._secret("PUZZLE_SALT").encode()
    return hmac.new(key, f"unsub:{pid}".encode(), hashlib.sha256).hexdigest()[:32]


def check_unsub(pid: int, token: str) -> bool:
    return hmac.compare_digest(unsub_token(pid), token or "")


# ---------------------------------------------------------------- accounts
def is_operator(email: str) -> bool:
    """The site owner (PUZZLE_OPERATOR_EMAIL) may use reserved handles such as their own name."""
    op = os.getenv("PUZZLE_OPERATOR_EMAIL", "").strip().lower()
    return bool(op) and (email or "").strip().lower() == op


def clean_handle(handle: str, email: str = "") -> str:
    h = (handle or "").strip()
    if not HANDLE.match(h):
        raise GameError("Handles are 3–24 letters, digits, dots, dashes or underscores, starting with a letter or digit.")
    # letters only, so "Ruairi_Powers" and "r.u.a.i.r.i" can't impersonate the owner; digits stay, so "admin1" is fine
    if re.sub(r"[^a-z0-9]", "", h.lower()) in {re.sub(r"[^a-z0-9]", "", r) for r in RESERVED} and not is_operator(email):
        raise GameError(f"“{h}” is reserved for the site (it looks like an official or the owner's name). "
                        "Please pick another handle.")
    return h


def subscribe(conn, s: Settings, email: str, handle: str, tracks: list[str], base_url: str) -> str:
    """Create an unconfirmed player and email a confirmation link. Same reply whether or not the email exists."""
    email = (email or "").strip().lower()
    if not EMAIL.match(email) or len(email) > 254:
        raise GameError("That doesn't look like an email address.")
    tracks = [t for t in tracks if t in TRACKS] or list(s.puzzles["players"]["default_tracks"])
    existing = fetch_one(conn, select(players).where(players.c.email == email))
    if existing:
        if existing["confirmed_at"]:
            link = f"{base_url}/auth/{_token(conn, existing['id'], 'signin', s['limits']['magic_link_minutes'])}"
            mailer.signin(conn, email, link, s["limits"]["magic_link_minutes"])
        else:
            mailer.confirm(conn, email, existing["handle"], f"{base_url}/confirm/{_token(conn, existing['id'], 'confirm', 7 * 24 * 60)}")
        return "check-email"
    handle = clean_handle(handle, email)
    if fetch_one(conn, select(players.c.id).where(func.lower(players.c.handle) == handle.lower())):
        raise GameError("That handle is taken. Please pick another.")
    pid = conn.execute(players.insert().values(email=email, handle=handle, tracks=tracks, created_at=now())).inserted_primary_key[0]
    mailer.confirm(conn, email, handle, f"{base_url}/confirm/{_token(conn, pid, 'confirm', 7 * 24 * 60)}")
    telemetry.record("subscribe", status="ok", items=1)
    return "check-email"


def confirm(conn, token: str) -> int | None:
    pid = use_token(conn, token, "confirm")
    if pid:
        p = fetch_one(conn, select(players).where(players.c.id == pid))
        conn.execute(update(players).where(players.c.id == pid).values(confirmed_at=now(), unsubscribed_at=None))
        conn.execute(delete(suppression).where(suppression.c.email_hash == mailer.email_hash(p["email"])))
    return pid


def request_signin(conn, s: Settings, email: str, base_url: str) -> None:
    p = fetch_one(conn, select(players).where(players.c.email == (email or "").strip().lower()))
    if p and p["confirmed_at"]:
        m = s["limits"]["magic_link_minutes"]
        mailer.signin(conn, p["email"], f"{base_url}/auth/{_token(conn, p['id'], 'signin', m)}", m)


def import_subscribers(conn, s: Settings, rows: list[tuple[str, str]]) -> dict:
    """Bulk add already-confirmed subscribers (e.g. from another list). Suppressed addresses are skipped."""
    out = {"added": 0, "suppressed": 0, "exists": 0}
    for email, handle in rows:
        email = email.strip().lower()
        if mailer.suppressed(conn, email):
            out["suppressed"] += 1
            continue
        try:
            conn.execute(players.insert().values(email=email, handle=clean_handle(handle, email), created_at=now(),
                                                 confirmed_at=now(), tracks=list(s.puzzles["players"]["default_tracks"])))
            out["added"] += 1
        except IntegrityError:
            out["exists"] += 1
    return out


def set_tracks(conn, pid: int, tracks: list[str]) -> None:
    conn.execute(update(players).where(players.c.id == pid).values(tracks=[t for t in tracks if t in TRACKS]))


def unsubscribe(conn, pid: int) -> None:
    p = fetch_one(conn, select(players).where(players.c.id == pid))
    if not p:
        return
    conn.execute(update(players).where(players.c.id == pid).values(unsubscribed_at=now()))
    _suppress(conn, p["email"], "unsubscribed")
    telemetry.record("unsubscribe", status="ok", items=1)


def delete_account(conn, pid: int) -> None:
    """Removes the player, their acceptances and attempts (cascade). The address is kept only as a hash, so it
    is never emailed again."""
    p = fetch_one(conn, select(players).where(players.c.id == pid))
    if not p:
        return
    _suppress(conn, p["email"], "deleted")
    conn.execute(delete(attempts).where(attempts.c.player_id == pid))
    conn.execute(delete(acceptances).where(acceptances.c.player_id == pid))
    conn.execute(delete(tokens).where(tokens.c.player_id == pid))
    conn.execute(delete(players).where(players.c.id == pid))
    telemetry.record("delete_account", status="ok", items=1)


def _suppress(conn, email: str, reason: str) -> None:
    h = mailer.email_hash(email)
    if not conn.execute(select(suppression.c.email_hash).where(suppression.c.email_hash == h)).first():
        conn.execute(suppression.insert().values(email_hash=h, reason=reason, at=now()))


# ---------------------------------------------------------------- play
def is_open(p: dict, at: datetime | None = None) -> bool:
    at = at or now()
    return p["status"] == "open" and p["opens_at"] <= at < p["closes_at"]


def accept(conn, pid: int, puzzle_id: int, at: datetime | None = None) -> bool:
    p = fetch_one(conn, select(P).where(P.c.id == puzzle_id))
    if not p or not is_open(p, at):
        raise GameError("This puzzle isn't open.")
    if not fetch_one(conn, select(acceptances).where(acceptances.c.player_id == pid, acceptances.c.puzzle_id == puzzle_id)):
        conn.execute(acceptances.insert().values(player_id=pid, puzzle_id=puzzle_id, accepted_at=at or now(), attempts=0, points=0))
        telemetry.record("accept", status="ok", items=1)
    return True


def submit(conn, s: Settings, pid: int, puzzle_id: int, answer: str, at: datetime | None = None) -> dict:
    """Grade one attempt. Returns {status, attempts_used, attempts_left, points} — never the answer."""
    at = at or now()
    mx = int(s.puzzles["attempts"]["max_per_puzzle"])
    p = fetch_one(conn, select(P).where(P.c.id == puzzle_id))
    if not p or p["status"] not in ("open", "closed", "revealed"):
        return {"status": "not_found"}
    acc = fetch_one(conn, select(acceptances).where(acceptances.c.player_id == pid, acceptances.c.puzzle_id == puzzle_id))
    used = acc["attempts"] if acc else 0
    base = {"attempts_used": used, "attempts_left": max(0, mx - used), "points": acc["points"] if acc else 0}
    if not is_open(p, at):
        return {**base, "status": "closed"}
    if not acc:
        return {**base, "status": "not_accepted"}
    if acc["solved_at"]:
        return {**base, "status": "already_solved"}
    if used >= mx:
        return {**base, "status": "out_of_attempts"}
    try:
        telemetry.require_enabled("submit")
    except telemetry.WorkflowDisabled:
        return {**base, "status": "paused"}
    answer = (answer or "").strip()[:200]
    if not answer:
        return {**base, "status": "empty"}
    ok, _ = grading.grade(answer, p["answer_type"], p["decimals"], p["answer_hashes"], p["salt"])
    n = used + 1
    flags = ["injection_text"] if INJECTION.search(answer) else []
    try:
        conn.execute(attempts.insert().values(player_id=pid, puzzle_id=puzzle_id, n=n, answer=answer, correct=ok,
                                              flags=flags, at=at))
    except IntegrityError:                                 # a double click: the same attempt number twice
        return {**base, "status": "duplicate"}
    pts = grading.points(n, ok, s.puzzles["scoring"], p["track"]) if ok else 0
    conn.execute(update(acceptances).where(acceptances.c.player_id == pid, acceptances.c.puzzle_id == puzzle_id)
                 .values(attempts=n, solved_at=at if ok else None, points=pts))
    telemetry.record("submit", status="ok", items=int(ok), flags=flags, detail={"attempt": n, "track": p["track"]})
    status = "solved" if ok else ("out_of_attempts" if n >= mx else "incorrect")
    return {"status": status, "attempts_used": n, "attempts_left": mx - n, "points": pts}


def my_state(conn, pid: int | None, puzzle_id: int) -> dict | None:
    if not pid:
        return None
    return fetch_one(conn, select(acceptances).where(acceptances.c.player_id == pid, acceptances.c.puzzle_id == puzzle_id))


# ---------------------------------------------------------------- leaderboard
def week_start(s: Settings, at: datetime | None = None) -> str:
    d = (at or now()).astimezone(ZoneInfo(s.puzzles["window"]["timezone"])).date()
    return (d - timedelta(days=d.weekday())).isoformat()


def leaderboard(conn, s: Settings, period: str = "all", track: str | None = None, limit: int = 100,
                at: datetime | None = None) -> list[dict]:
    """Handle, puzzles accepted / attempted / solved, total score. Ties: fewer attempts, then earlier last solve.
    Daily puzzles only (packs never count). Emails are never selected."""
    cond = [P.c.day.isnot(None), P.c.status.in_(("open", "closed", "revealed"))]
    if period == "week":
        cond.append(P.c.day >= week_start(s, at))
    if track in TRACKS:
        cond.append(P.c.track == track)
    q = (select(players.c.handle, players.c.simulated,
                func.count().label("accepted"),
                func.sum(case((acceptances.c.attempts > 0, 1), else_=0)).label("attempted"),
                func.sum(case((acceptances.c.solved_at.isnot(None), 1), else_=0)).label("solved"),
                func.sum(acceptances.c.points).label("score"),
                func.sum(acceptances.c.attempts).label("attempts"),
                func.max(acceptances.c.solved_at).label("last_solve"))
         .select_from(acceptances.join(players, players.c.id == acceptances.c.player_id)
                      .join(P, P.c.id == acceptances.c.puzzle_id))
         .where(and_(*cond)).group_by(players.c.id, players.c.handle, players.c.simulated))
    rows = fetch_all(conn, q)
    far = datetime.max.replace(tzinfo=None)
    rows.sort(key=lambda r: (-(r["score"] or 0), r["attempts"] or 0,
                             (r["last_solve"].replace(tzinfo=None) if r["last_solve"] else far), r["handle"].lower()))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows[:limit]
