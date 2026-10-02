"""Event store: SQLite by default, Postgres when DATABASE_URL is set (durable history for a hosted console).

Tables:
  events               one row per governance event from any workflow (visit, run, approval, eval, blocked …)
  workflow_state       the kill switch: enabled / disabled, why, by whom
  control_changes      append-only audit log of every switch change
  workflow_meta        what each workflow declares about itself (models, version) when it starts
  attestations         reviewers confirming controls
  incidents            governance issues the console detected, from detection to documented resolution
  incident_log         each incident's timeline: opened, repeats, auto-shutdown, emails, notes, fix, resolution
  notifications        every email (or ticket) the console sent or would have sent — the outbox
  escalation_settings  per-workflow alert and auto-shutdown choices from the Settings page
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
);
create table if not exists incidents (
  incident_id text primary key, number integer not null, opened_at text not null, workflow text not null,
  rule_id text not null, severity text not null, title text not null, control_id text, status text not null,
  summary text, evidence text, occurrences integer default 1, last_seen text, auto_shutdown integer default 0,
  resolved_at text, resolved_by text, resolution text, source text not null
);
create index if not exists ix_incidents_open on incidents (workflow, rule_id, status);
create table if not exists incident_log (
  entry_id text primary key, incident_id text not null, ts text not null, kind text not null, actor text,
  text text, source text not null
);
create table if not exists notifications (
  notification_id text primary key, ts text not null, incident_id text, channel text not null, recipients text,
  subject text, body_text text, body_html text, status text not null, error text, source text not null
);
create table if not exists escalation_settings (
  workflow text primary key, settings text not null, updated_by text, updated_at text
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
        for table in ("events", "control_changes", "attestations", "incidents", "incident_log", "notifications"):
            self.execute(f"delete from {table} where source = ?", (source,))

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

    # -------------------------------------------------------------- incidents
    def open_incident(self, workflow: str, rule_id: str) -> dict | None:
        rows = self.query("select * from incidents where workflow = ? and rule_id = ? and status <> 'resolved' "
                          "order by opened_at desc limit 1", (workflow, rule_id))
        return _incident(rows[0]) if rows else None

    def create_incident(self, inc: dict, source: str = "live") -> dict:
        with self._lock, self._conn() as c:
            n = (c.query("select max(number) as n from incidents")[0]["n"] or 0) + 1
            inc = {"incident_id": f"INC-{n:04d}", "number": n, "status": "open", "occurrences": 1,
                   "last_seen": inc["opened_at"], "auto_shutdown": 0, "resolved_at": None, "resolved_by": None,
                   "resolution": None, "source": source, **inc}
            cols = ["incident_id", "number", "opened_at", "workflow", "rule_id", "severity", "title", "control_id",
                    "status", "summary", "evidence", "occurrences", "last_seen", "auto_shutdown", "resolved_at",
                    "resolved_by", "resolution", "source"]
            row = {**inc, "evidence": json.dumps(inc.get("evidence") or [])}
            c.execute(f"insert into incidents ({','.join(cols)}) values ({','.join('?' * len(cols))})",
                      tuple(row[k] for k in cols))
        return inc

    def update_incident(self, incident_id: str, **fields) -> None:
        if "evidence" in fields:
            fields["evidence"] = json.dumps(fields["evidence"])
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.execute(f"update incidents set {sets} where incident_id = ?", (*fields.values(), incident_id))

    def incident(self, incident_id: str) -> dict | None:
        rows = self.query("select * from incidents where incident_id = ?", (incident_id,))
        return _incident(rows[0]) if rows else None

    def incidents(self, status: str | None = None, workflow: str | None = None, include_simulated: bool = True,
                  limit: int = 200) -> list[dict]:
        where, p = [], []
        if status == "open":
            where.append("status <> 'resolved'")
        elif status:
            where.append("status = ?"), p.append(status)
        if workflow:
            where.append("workflow = ?"), p.append(workflow)
        if not include_simulated:
            where.append("source = 'live'")
        sql = "select * from incidents" + (" where " + " and ".join(where) if where else "") + \
            f" order by opened_at desc limit {int(limit)}"
        return [_incident(r) for r in self.query(sql, p)]

    def log_incident(self, incident_id: str, kind: str, actor: str, text: str, source: str = "live",
                     ts: str | None = None) -> None:
        self.execute("insert into incident_log values (?,?,?,?,?,?,?)",
                     (os.urandom(8).hex(), incident_id,   # microseconds keep same-second entries in order
                      ts or datetime.now(timezone.utc).isoformat(timespec="microseconds"), kind, actor, text, source))

    def incident_log(self, incident_id: str) -> list[dict]:
        return self.query("select * from incident_log where incident_id = ? order by ts, entry_id", (incident_id,))

    # -------------------------------------------------------------- notifications (the outbox)
    def add_notification(self, n: dict, source: str = "live") -> str:
        nid = n.get("notification_id") or os.urandom(8).hex()
        cols = ["notification_id", "ts", "incident_id", "channel", "recipients", "subject", "body_text", "body_html",
                "status", "error", "source"]
        row = {"notification_id": nid, "ts": now_iso(), "error": "", "source": source, **n}
        row["recipients"] = ", ".join(row["recipients"]) if isinstance(row["recipients"], list) else row["recipients"]
        self.execute(f"insert into notifications ({','.join(cols)}) values ({','.join('?' * len(cols))})",
                     tuple(row.get(k) for k in cols))
        return nid

    def set_notification_status(self, nid: str, status: str, error: str = "") -> None:
        self.execute("update notifications set status = ?, error = ? where notification_id = ?", (status, error, nid))

    def notifications(self, incident_id: str | None = None, limit: int = 100, include_simulated: bool = True) -> list[dict]:
        where, p = [], []
        if incident_id:
            where.append("incident_id = ?"), p.append(incident_id)
        if not include_simulated:
            where.append("source = 'live'")
        return self.query("select * from notifications" + (" where " + " and ".join(where) if where else "") +
                          f" order by ts desc limit {int(limit)}", p)

    def notification(self, nid: str) -> dict | None:
        rows = self.query("select * from notifications where notification_id = ?", (nid,))
        return rows[0] if rows else None

    def emails_sent_since(self, ts: str) -> int:
        return self.query("select count(*) as n from notifications where channel = 'email' and status = 'sent' "
                          "and ts >= ? and source = 'live'", (ts,))[0]["n"]

    # -------------------------------------------------------------- escalation settings
    def escalation_settings(self) -> dict[str, dict]:
        return {r["workflow"]: {**json.loads(r["settings"]), "_updated_by": r["updated_by"], "_updated_at": r["updated_at"]}
                for r in self.query("select * from escalation_settings")}

    def save_escalation_settings(self, workflow: str, settings: dict, actor: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("delete from escalation_settings where workflow = ?", (workflow,))
            c.execute("insert into escalation_settings values (?,?,?,?)", (workflow, json.dumps(settings), actor, now_iso()))


def _incident(r: dict) -> dict:
    return {**r, "evidence": json.loads(r["evidence"] or "[]")}


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
