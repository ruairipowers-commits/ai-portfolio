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
create table if not exists likes (path text not null, visitor text not null, day text not null, ts text not null,
  primary key (path, visitor, day));
create table if not exists suggestions (
  id integer primary key, ts text not null, day text not null, idea text not null, name text, contact text,
  visitor text, page text, status text not null default 'pending', updated_at text, updated_by text
);
create table if not exists suggestion_votes (sid integer not null, visitor text not null, day text not null,
  ts text not null, primary key (sid, visitor, day));
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

    # -------------------------------------------------------------- thumbs up on posts
    def like(self, path: str, visitor: str) -> bool:
        """One thumbs up per post per visitor per day (the visitor key itself rotates daily). True if counted."""
        ts = now_iso()
        with self._lock, self._conn() as c:
            cur = c.execute("insert or ignore into likes values (?,?,?,?)", (path, visitor, ts[:10], ts))
            return cur.rowcount == 1

    def like_counts(self, paths: list[str] | None = None) -> dict[str, int]:
        if paths:
            marks = ",".join("?" * len(paths))
            rows = self.query(f"select path, count(*) n from likes where path in ({marks}) group by path", paths)
        else:
            rows = self.query("select path, count(*) n from likes group by path")
        return {r["path"]: r["n"] for r in rows}

    def top_liked(self, limit: int = 10, since_day: str | None = None) -> list[dict]:
        where, params = ("where day >= ?", (since_day,)) if since_day else ("", ())
        return self.query(f"""select path, count(*) as likes, max(day) as last_day from likes {where}
                              group by path order by likes desc, last_day desc limit ?""", (*params, limit))

    # -------------------------------------------------------------- project suggestions + upvotes
    SUGGESTION_STATUSES = ("pending", "published", "hidden", "done")

    def add_suggestion(self, idea: str, name: str, contact: str, visitor: str, page: str, status: str) -> int:
        ts = now_iso()
        with self._lock, self._conn() as c:
            cur = c.execute("""insert into suggestions (ts, day, idea, name, contact, visitor, page, status)
                               values (?,?,?,?,?,?,?,?)""", (ts, ts[:10], idea, name, contact, visitor, page, status))
            return cur.lastrowid

    def suggestions(self, statuses: tuple[str, ...] | None = None, limit: int = 200) -> list[dict]:
        """Newest-voted first: votes, then newest. Each row carries its vote count."""
        where, params = "", ()
        if statuses:
            where, params = f"where s.status in ({','.join('?' * len(statuses))})", statuses
        return self.query(f"""select s.*, (select count(*) from suggestion_votes v where v.sid = s.id) as votes
                              from suggestions s {where} order by votes desc, s.ts desc limit ?""", (*params, limit))

    def suggestion(self, sid: int) -> dict | None:
        r = self.query("""select s.*, (select count(*) from suggestion_votes v where v.sid = s.id) as votes
                          from suggestions s where id = ?""", (sid,))
        return r[0] if r else None

    def vote(self, sid: int, visitor: str) -> bool:
        ts = now_iso()
        with self._lock, self._conn() as c:
            cur = c.execute("insert or ignore into suggestion_votes values (?,?,?,?)", (sid, visitor, ts[:10], ts))
            return cur.rowcount == 1

    def set_suggestion_status(self, sid: int, status: str, actor: str) -> None:
        self.execute("update suggestions set status = ?, updated_at = ?, updated_by = ? where id = ?",
                     (status, now_iso(), actor[:80], sid))

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
        self.execute("update suggestions set contact = '' where day < ?", (cutoff,))   # keep the idea, drop contact

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
