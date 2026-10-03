"""Everything the assistant logs, in one SQLite file (env SITE_ASSISTANT_DB, default warehouse/assistant.sqlite).

  passages        the blog, split into sections, with an FTS5 index (rebuilt from the site's search index)
  activity        one row per page view, site search, assistant search and question — query text as typed,
                  never an IP address; `visitor` is a salted hash that changes every day
  daily_metrics   one value per day, source and metric (blog, searches, demos, Cloudflare, GitHub)
  digests         every engagement email: when, to whom, status
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = """
create table if not exists passages (
  pid integer primary key, url text not null, page_title text not null, section text, text text not null
);
create virtual table if not exists passages_fts using fts5(page_title, section, text, content='passages',
  content_rowid='pid', tokenize='porter unicode61');
create table if not exists index_runs (ts text not null, source text, passages integer, pages integer, status text);
create table if not exists activity (
  id integer primary key, ts text not null, day text not null, kind text not null, visitor text, page text,
  query text, results integer default 0, status text default 'ok', model text, input_tokens integer default 0,
  output_tokens integer default 0, latency_ms integer default 0, referrer text, flags text
);
create index if not exists ix_activity_day on activity (day, kind);
create table if not exists daily_metrics (
  day text not null, source text not null, metric text not null, value real, detail text,
  primary key (day, source, metric)
);
create table if not exists kv (key text primary key, value text, ts text);
create table if not exists digests (
  ts text not null, day text not null, recipients text, subject text, status text, error text, body_html text
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> str:
    return os.getenv("SITE_ASSISTANT_DB") or str(ROOT / "warehouse" / "assistant.sqlite")


class Store:
    def __init__(self, path: str | None = None):
        self.path = path or db_path()
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)
            cols = {r[1] for r in c.execute("pragma table_info(activity)")}
            if "answer" not in cols:              # older databases: answers weren't kept before
                c.execute("alter table activity add column answer text")

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("pragma journal_mode=wal")
        return c

    def query(self, sql: str, params=()) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def execute(self, sql: str, params=()) -> None:
        with self._lock, self._conn() as c:
            c.execute(sql, params)

    # -------------------------------------------------------------- passages
    def replace_passages(self, rows: list[dict], source: str) -> int:
        with self._lock, self._conn() as c:
            c.execute("delete from passages")
            c.executemany("insert into passages (url, page_title, section, text) values (?,?,?,?)",
                          [(r["url"], r["page_title"], r.get("section", ""), r["text"]) for r in rows])
            c.execute("insert into passages_fts(passages_fts) values ('rebuild')")
            c.execute("insert into index_runs values (?,?,?,?,?)",
                      (now_iso(), source, len(rows), len({r["url"].split("#")[0] for r in rows}), "ok"))
        return len(rows)

    def index_failed(self, source: str, error: str) -> None:
        self.execute("insert into index_runs values (?,?,?,?,?)", (now_iso(), source, 0, 0, f"failed: {error[:200]}"))

    def last_index(self) -> dict | None:
        r = self.query("select * from index_runs order by ts desc limit 1")
        return r[0] if r else None

    def passage_count(self) -> int:
        return self.query("select count(*) n from passages")[0]["n"]

    # -------------------------------------------------------------- small key/value facts (the profile card, post dates)
    def set_kv(self, key: str, value) -> None:
        self.execute("insert or replace into kv values (?,?,?)", (key, json.dumps(value), now_iso()))

    def get_kv(self, key: str, default=None):
        r = self.query("select value from kv where key = ?", (key,))
        return json.loads(r[0]["value"]) if r else default

    # -------------------------------------------------------------- activity
    def log(self, kind: str, visitor: str = "", page: str = "", query: str = "", results: int = 0,
            status: str = "ok", model: str = "", input_tokens: int = 0, output_tokens: int = 0,
            latency_ms: int = 0, referrer: str = "", flags: list[str] | None = None, answer: str = "") -> None:
        ts = now_iso()
        self.execute("""insert into activity (ts, day, kind, visitor, page, query, results, status, model, input_tokens,
                        output_tokens, latency_ms, referrer, flags, answer) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (ts, ts[:10], kind, visitor, page[:300], query[:500], results, status, model, input_tokens,
                      output_tokens, latency_ms, referrer[:300], json.dumps(flags or []), answer[:4000]))

    def count_since(self, kind: str, visitor: str | None, minutes: int) -> int:
        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
        sql, p = "select count(*) n from activity where kind = ? and ts >= ?", [kind, since]
        if visitor is not None:
            sql, p = sql + " and visitor = ?", p + [visitor]
        return self.query(sql, p)[0]["n"]

    def tokens_today(self) -> int:
        day = now_iso()[:10]
        return self.query("select coalesce(sum(input_tokens + output_tokens), 0) n from activity where day = ?",
                          (day,))[0]["n"]

    def purge(self, retention_days: int) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).date().isoformat()
        self.execute("delete from activity where day < ?", (cutoff,))

    # -------------------------------------------------------------- daily metrics + digests
    def put_metric(self, day: str, source: str, metric: str, value: float | None, detail=None) -> None:
        self.execute("insert or replace into daily_metrics values (?,?,?,?,?)",
                     (day, source, metric, value, json.dumps(detail) if detail is not None else None))

    def metrics(self, day: str) -> dict[tuple[str, str], dict]:
        return {(r["source"], r["metric"]): {**r, "detail": json.loads(r["detail"]) if r["detail"] else None}
                for r in self.query("select * from daily_metrics where day = ?", (day,))}

    def metric_history(self, source: str, metric: str, days: int, until: str) -> list[float]:
        return [r["value"] for r in self.query(
            "select value from daily_metrics where source = ? and metric = ? and day < ? and value is not null "
            "order by day desc limit ?", (source, metric, until, days))]

    def add_digest(self, day: str, recipients: list[str], subject: str, status: str, error: str, html: str) -> None:
        self.execute("insert into digests values (?,?,?,?,?,?,?)",
                     (now_iso(), day, ", ".join(recipients), subject, status, error, html))

    def digest_sent(self, day: str) -> bool:
        return bool(self.query("select 1 from digests where day = ? and status = 'sent' limit 1", (day,)))
