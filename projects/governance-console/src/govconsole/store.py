"""Event store: SQLite by default, Postgres when DATABASE_URL is set (durable history for a hosted console).

Three tables:
  events           one row per governance event from any workflow (visit, run, approval, eval, blocked …)
  workflow_state   the kill switch: enabled / disabled, why, by whom
  control_changes  append-only audit log of every switch change
Timestamps are ISO-8601 UTC text and `day` is YYYY-MM-DD, so the same SQL runs on both databases.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[2]

SCHEMA = """
create table if not exists events (
  event_id text primary key, ts text not null, day text not null, workflow text not null,
  event_type text not null, status text not null, actor text, actor_type text, session_id text,
  environment text, app_version text, run_id text, model text,
  input_tokens integer default 0, output_tokens integer default 0, cost_usd real default 0,
  latency_ms integer default 0, records_in integer default 0, records_out integer default 0,
  flags text, detail text, source text not null, received_at text not null
);
create index if not exists ix_events_day on events (day, workflow);
create index if not exists ix_events_wf on events (workflow, ts);
create table if not exists workflow_state (
  workflow text primary key, enabled integer not null, reason text, changed_by text, changed_at text, expires_at text
);
create table if not exists workflow_meta (
  workflow text primary key, meta text not null, environment text, registered_at text not null
);
create table if not exists attestations (
  attestation_id text primary key, ts text not null, workflow text not null, control_id text not null,
  verdict text not null, reviewer text not null, note text, source text not null
);
create table if not exists control_changes (
  change_id text primary key, ts text not null, workflow text not null, action text not null,
  reason text, actor text, source text not null
)
"""
EVENT_COLS = ["event_id", "ts", "day", "workflow", "event_type", "status", "actor", "actor_type", "session_id",
              "environment", "app_version", "run_id", "model", "input_tokens", "output_tokens", "cost_usd",
              "latency_ms", "records_in", "records_out", "flags", "detail", "source", "received_at"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def database_url() -> str:
    return os.getenv("DATABASE_URL") or str(PKG_ROOT / "warehouse" / "console.sqlite")


class Store:
    """Thread-safe enough for a single-process web app: one connection per call."""

    def __init__(self, url: str | None = None):
        self.url = url or database_url()
        self.pg = self.url.startswith(("postgres://", "postgresql://"))
        self._lock = threading.Lock()
        if not self.pg:
            Path(self.url).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            for stmt in [s for s in SCHEMA.split(";") if s.strip()]:
                c.execute(stmt.replace("real", "double precision") if self.pg else stmt)

    # -------------------------------------------------------------- plumbing
    def _conn(self):
        if self.pg:
            import psycopg  # pip install '.[postgres]'

            return _PgConn(psycopg.connect(self.url, autocommit=False))
        con = sqlite3.connect(self.url, timeout=30)
        con.execute("pragma journal_mode=wal")
        return _SqliteConn(con)

    def query(self, sql: str, params: tuple | list = ()) -> list[dict]:
        with self._conn() as c:
            return c.query(sql, params)

    def execute(self, sql: str, params: tuple | list = ()) -> None:
        with self._lock, self._conn() as c:
            c.execute(sql, params)

    # -------------------------------------------------------------- events
    def insert_events(self, events: list[dict]) -> int:
        """Insert, ignoring duplicates (event_id is the idempotency key). Returns rows inserted."""
        if not events:
            return 0
        ph = ",".join("?" * len(EVENT_COLS))
        conflict = "on conflict (event_id) do nothing"
        sql = f"insert into events ({','.join(EVENT_COLS)}) values ({ph}) {conflict}"
        rows = [tuple(_row(e)[k] for k in EVENT_COLS) for e in events]
        with self._lock, self._conn() as c:
            before = c.query("select count(*) as n from events")[0]["n"]
            c.executemany(sql, rows)
            return c.query("select count(*) as n from events")[0]["n"] - before

    def delete_source(self, source: str) -> None:
        self.execute("delete from events where source = ?", (source,))
        self.execute("delete from control_changes where source = ?", (source,))
        self.execute("delete from attestations where source = ?", (source,))

    # -------------------------------------------------------------- kill switch
    def workflow_state(self) -> dict[str, dict]:
        return {r["workflow"]: r for r in self.query("select * from workflow_state")}

    def set_enabled(self, workflow: str, enabled: bool, reason: str, actor: str, source: str = "live",
                    ts: str | None = None, expires_at: str | None = None) -> None:
        """Flip the kill switch. `expires_at`: a temporary switch-off (public demo) that lapses on its own."""
        ts = ts or now_iso()
        with self._lock, self._conn() as c:
            c.execute("delete from workflow_state where workflow = ?", (workflow,))
            c.execute("insert into workflow_state values (?,?,?,?,?,?)",
                      (workflow, int(enabled), reason, actor, ts, expires_at))
            c.execute("insert into control_changes values (?,?,?,?,?,?,?)",
                      (os.urandom(8).hex(), ts, workflow, "enable" if enabled else "disable", reason, actor, source))


    def effective_state(self) -> dict[str, dict]:
        """Kill-switch state with expired temporary switch-offs treated as enabled again."""
        out, now = {}, now_iso()
        for wf, r in self.workflow_state().items():
            if not r["enabled"] and r.get("expires_at") and r["expires_at"] <= now:
                r = {**r, "enabled": 1, "reason": f"temporary switch-off by {r['changed_by']} expired", "expires_at": None}
            out[wf] = r
        return out

    # -------------------------------------------------------------- self-registration + attestations
    def upsert_meta(self, workflow: str, meta: dict, environment: str, ts: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("delete from workflow_meta where workflow = ?", (workflow,))
            c.execute("insert into workflow_meta values (?,?,?,?)", (workflow, json.dumps(meta), environment, ts))

    def workflow_meta(self) -> dict[str, dict]:
        return {r["workflow"]: {**json.loads(r["meta"]), "_environment": r["environment"], "_registered_at": r["registered_at"]}
                for r in self.query("select * from workflow_meta")}

    def attest(self, workflow: str, control_id: str, verdict: str, reviewer: str, note: str, source: str = "live",
               ts: str | None = None) -> None:
        self.execute("insert into attestations values (?,?,?,?,?,?,?,?)",
                     (os.urandom(8).hex(), ts or now_iso(), workflow, control_id, verdict, reviewer, note, source))

    def latest_attestations(self, include_simulated: bool = True) -> dict[tuple[str, str], dict]:
        src = "" if include_simulated else "where source = 'live'"
        out = {}
        for r in self.query(f"select * from attestations {src} order by ts"):
            out[(r["workflow"], r["control_id"])] = r
        return out


def _row(e: dict) -> dict:
    r = {k: e.get(k) for k in EVENT_COLS}
    r["day"] = r.get("day") or str(r["ts"])[:10]
    r["flags"] = json.dumps(sorted(set(e.get("flags") or []))) if not isinstance(e.get("flags"), str) else e["flags"]
    r["detail"] = json.dumps(e.get("detail") or {}) if not isinstance(e.get("detail"), str) else e["detail"]
    r["received_at"] = r.get("received_at") or now_iso()
    r["source"] = r.get("source") or "live"
    for k in ("input_tokens", "output_tokens", "latency_ms", "records_in", "records_out"):
        r[k] = int(r[k] or 0)
    r["cost_usd"] = float(r["cost_usd"] or 0)
    return r


class _SqliteConn:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        (self.con.commit if et is None else self.con.rollback)()
        self.con.close()

    def execute(self, sql, params=()):
        self.con.execute(sql, params)

    def executemany(self, sql, rows):
        self.con.executemany(sql, rows)

    def query(self, sql, params=()):
        cur = self.con.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


class _PgConn(_SqliteConn):
    @staticmethod
    def _sql(sql):
        return sql.replace("%", "%%").replace("?", "%s")

    def execute(self, sql, params=()):
        self.con.execute(self._sql(sql), params)

    def executemany(self, sql, rows):
        with self.con.cursor() as cur:
            cur.executemany(self._sql(sql), rows)

    def query(self, sql, params=()):
        with self.con.cursor() as cur:
            cur.execute(self._sql(sql), params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
