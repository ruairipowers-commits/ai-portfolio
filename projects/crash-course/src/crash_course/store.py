"""Learner data in SQLite (stdlib). One file, `<data>/warehouse/course.db`; the same SQL runs on Postgres.

What is stored (DATA-03): an email (for sign-in and notifications), a display name, enrolments, progress, quiz
attempts (question ids and chosen option indexes, no free text), feedback, suggestions and approvals. Run and cost
logs carry hashes and counts only (OBS-01). Telemetry to the governance console never carries any of it.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS learners (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, created_at TEXT, last_seen TEXT,
  is_owner INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS login_tokens (
  token_hash TEXT PRIMARY KEY, learner_id INTEGER, expires_at TEXT, used_at TEXT);
CREATE TABLE IF NOT EXISTS courses (            -- approved suggestions (tech-page courses come from sources/)
  slug TEXT PRIMARY KEY, title TEXT, category TEXT, summary TEXT, docs TEXT, source_text TEXT,
  suggestion_id INTEGER, status TEXT DEFAULT 'active', created_at TEXT);
CREATE TABLE IF NOT EXISTS enrollments (
  learner_id INTEGER, course TEXT, enrolled_at TEXT, PRIMARY KEY (learner_id, course));
CREATE TABLE IF NOT EXISTS progress (
  learner_id INTEGER, course TEXT, level TEXT, unlocked_at TEXT, quiz_best INTEGER DEFAULT 0,
  quiz_passed_at TEXT, modules_passed TEXT DEFAULT '[]', project_done_at TEXT, completed_at TEXT,
  PRIMARY KEY (learner_id, course, level));
CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY, token TEXT UNIQUE, learner_id INTEGER, course TEXT, level TEXT, part TEXT,
  version INTEGER, question_ids TEXT, option_orders TEXT, started_at TEXT, submitted_at TEXT,
  answers TEXT, score INTEGER, total INTEGER, passed INTEGER);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY, learner_id INTEGER, course TEXT, level TEXT, version INTEGER, rating INTEGER,
  unclear TEXT, add_text TEXT, created_at TEXT, status TEXT DEFAULT 'new');
CREATE TABLE IF NOT EXISTS suggestions (
  id INTEGER PRIMARY KEY, learner_id INTEGER, text TEXT, created_at TEXT, status TEXT,
  screen TEXT, assessment TEXT, decided_by TEXT, decided_at TEXT, decision_note TEXT, course_slug TEXT);
CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY, course TEXT, level TEXT, version INTEGER, payload TEXT, created_at TEXT,
  status TEXT DEFAULT 'pending', decided_by TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY, kind TEXT, course TEXT, level TEXT, status TEXT, created_at TEXT, started_at TEXT,
  finished_at TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS runs (                -- OBS-01 / COST-02: one row per model call
  id INTEGER PRIMARY KEY, at TEXT, action TEXT, alias TEXT, model TEXT, prompt_hash TEXT, input_hash TEXT,
  input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, latency_ms INTEGER, outcome TEXT, used_fallback INTEGER);
CREATE TABLE IF NOT EXISTS approvals (           -- HITL-02: every owner decision, by whom and when
  id INTEGER PRIMARY KEY, at TEXT, actor TEXT, kind TEXT, ref TEXT, decision TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY, to_hash TEXT, kind TEXT, subject TEXT, status TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS invites (code_hash TEXT PRIMARY KEY, created_at TEXT, used_by INTEGER);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db_path() -> Path:
    p = data_dir() / "warehouse" / "course.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def connect(path: Path | None = None):
    conn = sqlite3.connect(path or db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _add_columns(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Columns added after the first release; existing databases get them on the next connect.
COLUMNS = {
    "courses": {"tags": "TEXT"},                     # {"industry": [...], "function": [...], "tech": [...]}
    "suggestions": {"source": "TEXT DEFAULT 'learner'", "client_ref": "TEXT", "tags": "TEXT", "demand": "REAL"},
}


def _add_columns(conn) -> None:
    for table, cols in COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_suggestions_client_ref ON suggestions(client_ref) "
                 "WHERE client_ref IS NOT NULL")


def one(conn, sql: str, *args) -> dict | None:
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


def rows(conn, sql: str, *args) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def insert(conn, table: str, **values) -> int:
    cols = ", ".join(values)
    q = ", ".join("?" for _ in values)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({q})", tuple(values.values()))
    return cur.lastrowid


def log_run(conn, action: str, res, alias: str, prompt_hash: str, input_hash: str, outcome: str) -> None:
    insert(conn, "runs", at=now(), action=action, alias=alias, model=res.model.name, prompt_hash=prompt_hash,
           input_hash=input_hash, input_tokens=res.input_tokens, output_tokens=res.output_tokens,
           cost_usd=round(res.cost_usd, 6), latency_ms=res.latency_ms, outcome=outcome,
           used_fallback=int(res.used_fallback))


def approval(conn, actor: str, kind: str, ref: str, decision: str, note: str = "") -> None:
    insert(conn, "approvals", at=now(), actor=actor, kind=kind, ref=ref, decision=decision, note=note)


def j(v) -> str:
    return json.dumps(v, separators=(",", ":"))
