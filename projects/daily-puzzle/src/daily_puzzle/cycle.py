"""The daily cycle as one idempotent state machine: `tick(now)` brings everything up to date.

APScheduler calls it every minute inside the service; `puzzle tick` runs it from the CLI; the simulator calls it with
a moving clock. Missed steps (server down overnight) are caught up in order the next time it runs.

    scheduled ──open_at──▶ open (email subscribers) ──close_at──▶ closed ──+reveal_after──▶ revealed (answer public)
    (generate_at: generate + verify, or escalate and use a reserve puzzle)
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from . import game, generate, grading, mailer, telemetry
from .config import Settings, validate_puzzles
from .store import fetch_all, fetch_one, jobs, log_job, now, players, puzzle_for_day, puzzles as P


def tz(s: Settings) -> ZoneInfo:
    return ZoneInfo(s.puzzles["window"]["timezone"])


def generate_time(day, s: Settings) -> datetime:
    return datetime.combine(day, dtime.fromisoformat(s.puzzles["window"]["generate_at"]), tz(s))


def tick(conn, s: Settings, at: datetime | None = None, links=None, scenario: dict | None = None) -> list[dict]:
    """`scenario` (operator demo / tests only): {"scenario": name, "kind": kind, "every_round": bool} for today's draft."""
    at = at or now()
    out: list[dict] = []
    if problems := validate_puzzles(s.puzzles):
        log_job(conn, "tick", "", "config_error", {"problems": problems})
        return [{"job": "config_error", "problems": problems}]
    reveal_delay = timedelta(minutes=int(s.puzzles["window"]["reveal_after_min"]))
    # 1. close and reveal anything due (oldest first)
    for p in fetch_all(conn, select(P).where(P.c.status == "open", P.c.closes_at <= at).order_by(P.c.closes_at)):
        conn.execute(update(P).where(P.c.id == p["id"]).values(status="closed"))
        log_job(conn, "close", p["day"], "ok", {"puzzle_id": p["id"]})
        out.append({"job": "close", "puzzle_id": p["id"]})
    for p in fetch_all(conn, select(P).where(P.c.status == "closed", P.c.closes_at <= at - reveal_delay)):
        reveal(conn, p, at)
        out.append({"job": "reveal", "puzzle_id": p["id"]})
    # 2. today's puzzle: generate once, after generate_at
    today = at.astimezone(tz(s)).date()
    if at >= generate_time(today, s) and not puzzle_for_day(conn, today.isoformat()) and not _tried(conn, today.isoformat()):
        try:
            res = generate.daily(conn, s, today, **(scenario or {}))
            out.append({"job": "generate", **{k: res[k] for k in ("status", "puzzle_id", "track", "kind", "rounds")}})
        except telemetry.WorkflowDisabled as e:
            out.append({"job": "generate", "status": "blocked", "why": str(e)})
        except Exception as e:  # noqa: BLE001 — log, don't crash the scheduler; tried once per day
            log_job(conn, "generate", today.isoformat(), "failed", {"error": f"{type(e).__name__}: {e}"[:300]})
            out.append({"job": "generate", "status": "failed", "error": str(e)[:200]})
    # 3. open what's due (and skip straight to closed if its whole window was missed)
    for p in fetch_all(conn, select(P).where(P.c.status == "scheduled", P.c.opens_at <= at).order_by(P.c.opens_at)):
        if at >= p["closes_at"]:
            conn.execute(update(P).where(P.c.id == p["id"]).values(status="closed"))
            log_job(conn, "open", p["day"], "missed", {"puzzle_id": p["id"]})
            continue
        conn.execute(update(P).where(P.c.id == p["id"]).values(status="open"))
        sent = announce(conn, s, p, links)
        log_job(conn, "open", p["day"], "ok", {"puzzle_id": p["id"], "emails": sent})
        out.append({"job": "open", "puzzle_id": p["id"], "emails": sent})
    return out


def maintain(conn, s: Settings, min_per_track: int = 1, top_up_to: int = 2) -> int:
    """Keep at least one reserve puzzle per enabled track (a fresh install starts with none)."""
    from sqlalchemy import func
    low = [t for t in s.enabled_tracks()
           if conn.execute(select(func.count()).where(P.c.status == "reserve", P.c.track == t)).scalar() < min_per_track]
    if not low:
        return 0
    try:
        return len(generate.build_reserve(conn, s, per_track=top_up_to))
    except Exception as e:  # noqa: BLE001
        log_job(conn, "reserve", "", "failed", {"error": f"{type(e).__name__}: {e}"[:300]})
        return 0


def _tried(conn, day: str) -> bool:
    return conn.execute(select(jobs.c.id).where(jobs.c.job == "generate", jobs.c.day == day)).first() is not None


def reveal(conn, p: dict, at: datetime) -> None:
    """After close only: decrypt the key and publish answer, worked solution and reference code."""
    if p["status"] != "closed" or p["closes_at"] > at:
        raise RuntimeError(f"puzzle {p['id']} is not closed; its answer can't be revealed")
    key = grading.unseal(p["sealed_key"])
    conn.execute(update(P).where(P.c.id == p["id"]).values(
        status="revealed", revealed_at=at, reveal_answer=key["answer"], reveal_solution=key.get("solution", ""),
        reveal_code=key.get("code", "")))
    log_job(conn, "reveal", p["day"], "ok", {"puzzle_id": p["id"]})


def announce(conn, s: Settings, p: dict, links=None) -> dict:
    """Email today's puzzle to confirmed, subscribed (non-simulated) players of its track."""
    base = mailer.public_url()
    links = links or (lambda pl: (f"{base}/p/{p['id']}", f"{base}/me", f"{base}/u/{pl['id']}/{game.unsub_token(pl['id'])}"))
    rows = fetch_all(conn, select(players).where(players.c.confirmed_at.isnot(None), players.c.unsubscribed_at.is_(None),
                                                 players.c.simulated.isnot(True)))
    recipients = [r for r in rows if p["track"] in (r["tracks"] or [])]
    prev = fetch_one(conn, select(P).where(P.c.status == "revealed", P.c.day < p["day"]).order_by(P.c.day.desc()))
    try:
        return mailer.daily(conn, s, p, recipients, prev, links)
    except telemetry.WorkflowDisabled:
        return {"blocked": len(recipients)}
