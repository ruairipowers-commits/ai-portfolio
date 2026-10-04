"""Tables (SQLAlchemy Core): SQLite by default, Postgres with DATABASE_URL — same code.

The answer key is never stored in plain text before close: `puzzles.answer_hashes` holds salted HMACs of the
accepted forms (enough to grade), `puzzles.sealed_key` holds the encrypted key + worked solution, and the
`reveal_*` columns are written only by the reveal step after submissions close.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table, Text,
                        UniqueConstraint, create_engine, event, select)
from sqlalchemy.engine import Engine

from .config import Settings

md = MetaData()

players = Table(
    "players", md,
    Column("id", Integer, primary_key=True),
    Column("email", String(320), unique=True, nullable=False),     # never shown publicly
    Column("handle", String(40), unique=True, nullable=False),
    Column("tracks", JSON, nullable=False),                         # tracks they want emailed
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("confirmed_at", DateTime(timezone=True)),                # double opt-in
    Column("unsubscribed_at", DateTime(timezone=True)),
    Column("simulated", Boolean, default=False),                    # synthetic players (demo / simulation)
)

tokens = Table(                                                     # confirm / sign-in / unsubscribe links
    "tokens", md,
    Column("token_hash", String(64), primary_key=True),
    Column("player_id", Integer, ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
    Column("purpose", String(16), nullable=False),                  # confirm | signin | unsubscribe
    Column("expires_at", DateTime(timezone=True)),
    Column("used_at", DateTime(timezone=True)),
)

suppression = Table(                                                # unsubscribed / deleted addresses (hash only)
    "suppression", md,
    Column("email_hash", String(64), primary_key=True),
    Column("reason", String(32)),
    Column("at", DateTime(timezone=True)),
)

puzzles = Table(
    "puzzles", md,
    Column("id", Integer, primary_key=True),
    Column("day", String(10)),                                      # YYYY-MM-DD for daily puzzles; null for packs
    Column("track", String(16), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("difficulty", String(8), nullable=False),
    Column("title", String(200), nullable=False),
    Column("statement", Text, nullable=False),
    Column("starter", Text),                                        # starter code for coding / AI puzzles
    Column("assets", JSON),                                         # [{id, files, revision, license}]
    Column("learning_objective", Text),
    Column("skill_tags", JSON),
    Column("answer_format", String(200)),                           # what to type, e.g. "an integer"
    Column("answer_type", String(8), nullable=False),               # text | int | float
    Column("decimals", Integer),                                    # float answers are compared rounded to this
    Column("salt", String(32), nullable=False),                     # per-puzzle HMAC salt
    Column("answer_hashes", JSON, nullable=False),                  # HMACs of accepted normalized forms
    Column("sealed_key", Text, nullable=False),                     # encrypted {answer, forms, solution, code}
    Column("status", String(12), nullable=False),                   # scheduled|open|closed|revealed|escalated|rejected|reserve|pack
    Column("source", String(12), nullable=False),                   # generated | reserve | pack
    Column("opens_at", DateTime(timezone=True)),
    Column("closes_at", DateTime(timezone=True)),
    Column("revealed_at", DateTime(timezone=True)),
    Column("reveal_answer", Text),                                  # written only after close
    Column("reveal_solution", Text),
    Column("reveal_code", Text),
    Column("verification", JSON),                                   # the verifier's report (no key material)
    Column("statement_hash", String(64)),                           # de-duplication
    Column("answer_fingerprint", String(64)),                       # kind + answer, hashed, for de-duplication
    Column("generator_model", String(80)),
    Column("solver_model", String(80)),
    Column("prompt_sha", String(16)),
    Column("run_id", String(32)),
    Column("pack_id", String(32)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

acceptances = Table(                                                # a player pressed Accept on a puzzle
    "acceptances", md,
    Column("player_id", Integer, ForeignKey("players.id", ondelete="CASCADE"), primary_key=True),
    Column("puzzle_id", Integer, ForeignKey("puzzles.id", ondelete="CASCADE"), primary_key=True),
    Column("accepted_at", DateTime(timezone=True), nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("solved_at", DateTime(timezone=True)),
    Column("points", Integer, nullable=False, default=0),
)

attempts = Table(
    "attempts", md,
    Column("id", Integer, primary_key=True),
    Column("player_id", Integer, ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
    Column("puzzle_id", Integer, ForeignKey("puzzles.id", ondelete="CASCADE"), nullable=False),
    Column("n", Integer, nullable=False),
    Column("answer", String(200), nullable=False),                  # what the player typed (truncated)
    Column("correct", Boolean, nullable=False),
    Column("flags", JSON),
    Column("at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("player_id", "puzzle_id", "n"),
)

ai_calls = Table(                                                   # OBS-01 / COST-02
    "ai_calls", md,
    Column("id", Integer, primary_key=True),
    Column("run_id", String(32)),
    Column("role", String(12)),                                     # generator | solver
    Column("purpose", String(12)),                                  # daily | pack | eval
    Column("alias", String(40)),
    Column("model", String(80)),
    Column("prompt_sha", String(16)),
    Column("input_sha", String(16)),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("cost_usd", Float),
    Column("latency_ms", Integer),
    Column("status", String(16)),
    Column("used_fallback", Boolean),
    Column("at", DateTime(timezone=True)),
)

sandbox_runs = Table(
    "sandbox_runs", md,
    Column("id", Integer, primary_key=True),
    Column("run_id", String(32)),
    Column("who", String(12)),                                      # reference | solver
    Column("code_sha", String(16)),
    Column("ok", Boolean),
    Column("seconds", Float),
    Column("violation", String(200)),
    Column("output_sha", String(16)),                               # hash only: the output may be the answer
    Column("at", DateTime(timezone=True)),
)

jobs = Table(                                                       # what the scheduler did, for the audit trail
    "jobs", md,
    Column("id", Integer, primary_key=True),
    Column("job", String(16)),
    Column("day", String(10)),
    Column("status", String(12)),
    Column("detail", JSON),
    Column("at", DateTime(timezone=True)),
)

reviews = Table(                                                    # HITL-02: operator decisions on escalations
    "reviews", md,
    Column("id", Integer, primary_key=True),
    Column("puzzle_id", Integer, ForeignKey("puzzles.id", ondelete="CASCADE")),
    Column("reviewer", String(80), nullable=False),
    Column("decision", String(12), nullable=False),                 # approve | reject
    Column("note", Text),
    Column("at", DateTime(timezone=True)),
)

outbox = Table(                                                     # every email, sent or (mock mode) only written
    "outbox", md,
    Column("id", Integer, primary_key=True),
    Column("to_hash", String(64)),                                  # who, as a hash (the address is in players)
    Column("kind", String(16)),                                     # confirm | signin | daily | escalation
    Column("subject", String(200)),
    Column("status", String(12)),                                   # sent | written | failed | suppressed
    Column("provider_id", String(80)),
    Column("at", DateTime(timezone=True)),
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(d: datetime | None) -> datetime | None:
    """SQLite gives back naive datetimes; everything here is UTC."""
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


_engines: dict[str, Engine] = {}


def engine(s: Settings | None = None) -> Engine:
    url = (s or Settings.load()).database_url
    if url not in _engines:
        eng = create_engine(url, future=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        if url.startswith("sqlite"):
            @event.listens_for(eng, "connect")
            def _pragmas(conn, _):
                cur = conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.close()
        md.create_all(eng)
        _engines[url] = eng
    return _engines[url]


def reset_engines() -> None:
    for e in _engines.values():
        e.dispose()
    _engines.clear()


def row(r) -> dict | None:
    if r is None:
        return None
    d = dict(r._mapping)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = aware(v)
    return d


def fetch_one(conn, stmt) -> dict | None:
    return row(conn.execute(stmt).first())


def fetch_all(conn, stmt) -> list[dict]:
    return [row(r) for r in conn.execute(stmt)]


def log_job(conn, job: str, day: str, status: str, detail: dict | None = None) -> None:
    conn.execute(jobs.insert().values(job=job, day=day, status=status, detail=json.loads(json.dumps(detail or {}, default=str)),
                                      at=now()))


def puzzle_for_day(conn, day: str) -> dict | None:
    return fetch_one(conn, select(puzzles).where(puzzles.c.day == day,
                                                 puzzles.c.status.in_(("scheduled", "open", "closed", "revealed")))
                     .order_by(puzzles.c.id.desc()))
