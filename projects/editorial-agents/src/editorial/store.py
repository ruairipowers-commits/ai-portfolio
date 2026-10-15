"""SQLite store: candidate topics (one row each, with status), owner actions, runs.

Topic status: candidate → queued (in the top N) → picked / dismissed by the owner → drafted (a draft PR exists) →
published (merged). Readers vote on queued topics (one vote per anonymous visitor per topic per day); votes order the
queue after the owner's picks, so the most-wanted topic is written next. Also: escalated (failed the injection screen), expired (too old), similar (too close to a
published post or a better queue topic). Every owner action is a row in `actions` (HITL-02).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import data_dir

SCHEMA = """
create table if not exists topics (
  id text primary key, source text not null, title text not null, url text not null, summary text,
  published text, signals text, fetched_at text not null, status text not null default 'candidate',
  analysis text, scores text, rank integer, flags text, updated_at text
);
create index if not exists ix_topics_status on topics (status);
create table if not exists actions (ts text not null, topic_id text not null, action text not null, actor text,
  detail text);
create table if not exists runs (ts text not null, kind text not null, status text, detail text);
create table if not exists used_links (nonce text primary key, ts text not null);
create table if not exists kv (key text primary key, value text, ts text);
create table if not exists topic_votes (topic_id text not null, visitor text not null, day text not null,
  ts text not null, primary key (topic_id, visitor, day));
"""
OPEN = ("candidate", "queued", "picked")          # still eligible for the queue


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or data_dir() / "editorial.sqlite")
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def query(self, sql: str, params=()) -> list[dict]:
        with self._conn() as c:
            return [_decode(dict(r)) for r in c.execute(sql, params).fetchall()]

    def execute(self, sql: str, params=()) -> None:
        with self._conn() as c:
            c.execute(sql, params)

    # ---- topics
    def upsert_candidate(self, t: dict) -> bool:
        """Insert a newly seen candidate; refresh the signals of one we already have. True if new."""
        with self._conn() as c:
            old = c.execute("select id from topics where id = ?", (t["id"],)).fetchone()
            if old:
                c.execute("update topics set signals = ?, updated_at = ? where id = ?",
                          (json.dumps(t.get("signals", {})), now(), t["id"]))
                return False
            c.execute("insert into topics (id, source, title, url, summary, published, signals, fetched_at, flags, "
                      "updated_at) values (?,?,?,?,?,?,?,?,?,?)",
                      (t["id"], t["source"], t["title"][:300], t["url"], (t.get("summary") or "")[:2000],
                       t.get("published", ""), json.dumps(t.get("signals", {})), now(),
                       json.dumps(t.get("flags", [])), now()))
            return True

    def topic(self, tid: str) -> dict | None:
        r = self.query("select * from topics where id = ?", (tid,))
        return r[0] if r else None

    def topics(self, statuses: tuple[str, ...]) -> list[dict]:
        q = ",".join("?" * len(statuses))
        return self.query(f"select * from topics where status in ({q}) order by coalesce(rank, 9999), "
                          "coalesce(nullif(published, ''), fetched_at) desc, id",
                          statuses)

    def set_status(self, tid: str, status: str, **fields) -> None:
        sets, vals = ["status = ?", "updated_at = ?"], [status, now()]
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            vals.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
        self.execute(f"update topics set {', '.join(sets)} where id = ?", (*vals, tid))

    def set_fields(self, tid: str, **fields) -> None:
        sets, vals = ["updated_at = ?"], [now()]
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            vals.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
        self.execute(f"update topics set {', '.join(sets)} where id = ?", (*vals, tid))

    def queue(self) -> list[dict]:
        """The live queue: picked topics first (the owner chose them), then by readers' votes, then by rank."""
        rows = self.topics(("picked", "queued"))
        votes = self.vote_counts()
        for r in rows:
            r["votes"] = votes.get(r["id"], 0)
        return sorted(rows, key=lambda r: (r["status"] != "picked", -r["votes"], r.get("rank") or 9999))

    # ---- reader votes
    def vote(self, tid: str, visitor: str) -> bool:
        """One vote per visitor per topic per day. True if this one counted."""
        ts = now()
        with self._conn() as c:
            cur = c.execute("insert or ignore into topic_votes values (?,?,?,?)", (tid, visitor, ts[:10], ts))
            return cur.rowcount == 1

    def vote_counts(self, since: str = "") -> dict[str, int]:
        """Votes per topic; with `since`, only those cast after that time (e.g. since the last owner email)."""
        rows = self.query("select topic_id, count(*) n from topic_votes where ts > ? group by topic_id", (since,))
        return {r["topic_id"]: r["n"] for r in rows}

    def votes_by(self, visitor: str, minutes: int = 60) -> int:
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return self.query("select count(*) n from topic_votes where visitor = ? and ts >= ?",
                          (visitor, since.isoformat(timespec="seconds")))[0]["n"]

    # ---- owner actions, runs
    def action(self, tid: str, action: str, actor: str, detail: dict | None = None) -> None:
        self.execute("insert into actions values (?,?,?,?,?)", (now(), tid, action, actor, json.dumps(detail or {})))

    def run(self, kind: str, status: str, detail: dict) -> None:
        self.execute("insert into runs values (?,?,?,?)", (now(), kind, status, json.dumps(detail, default=str)))

    def last_run(self, kind: str) -> dict | None:
        r = self.query("select * from runs where kind = ? order by ts desc limit 1", (kind,))
        return r[0] if r else None

    def use_nonce(self, nonce: str) -> bool:
        """Single-use links: True the first time a nonce is seen."""
        try:
            self.execute("insert into used_links values (?, ?)", (nonce, now()))
            return True
        except sqlite3.IntegrityError:
            return False

    def set_kv(self, key: str, value) -> None:
        self.execute("insert or replace into kv values (?, ?, ?)", (key, json.dumps(value), now()))

    def get_kv(self, key: str, default=None):
        r = self.query("select value from kv where key = ?", (key,))
        return r[0]["value"] if r else default


def _decode(row: dict) -> dict:
    for k in ("signals", "analysis", "scores", "flags", "detail", "value"):
        if isinstance(row.get(k), str) and row[k][:1] in "{[\"0123456789tfn":
            try:
                row[k] = json.loads(row[k])
            except ValueError:
                pass
    return row
