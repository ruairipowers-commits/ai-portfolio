"""SQLite on the household's own server: weeks (plan, list, approvals), feedback, specials, pantry, chores load.
The run log (logs/runs.jsonl) holds counts, hashes and model usage — never names or what anyone ate (OBS-01)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

import yaml

from .config import ROOT, work_root

SCHEMA = """
CREATE TABLE IF NOT EXISTS weeks (week_of TEXT PRIMARY KEY, plan TEXT, split TEXT, chores TEXT, pets TEXT,
    savings TEXT, status TEXT, locks TEXT, approved_by TEXT, approved_at TEXT, approve_seconds REAL,
    shopping_choice TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS feedback (week_of TEXT, day TEXT, meal TEXT, recipe TEXT, eaten TEXT, rating INTEGER,
    by TEXT, ts TEXT, PRIMARY KEY (week_of, day, meal));
CREATE TABLE IF NOT EXISTS specials (week_of TEXT, store TEXT, ingredient TEXT, price REAL, regular REAL,
    source TEXT, confirmed_by TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS pantry (ingredient TEXT PRIMARY KEY, qty REAL, updated TEXT);
CREATE TABLE IF NOT EXISTS history (recipe TEXT, date TEXT);
CREATE TABLE IF NOT EXISTS portions (recipe TEXT PRIMARY KEY, factor REAL, leftover_streak INTEGER, updated TEXT);
CREATE TABLE IF NOT EXISTS loads (person TEXT, week_of TEXT, load INTEGER, PRIMARY KEY (person, week_of));
CREATE TABLE IF NOT EXISTS audit (ts TEXT, actor TEXT, action TEXT, detail TEXT);
"""


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def db_path() -> Path:
    return work_root() / "warehouse" / "lilhelper.sqlite"


def connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    if not con.execute("SELECT 1 FROM pantry LIMIT 1").fetchone():
        seed = yaml.safe_load((ROOT / "config" / "pantry.example.yaml").read_text())["items"]
        con.executemany("INSERT INTO pantry VALUES (?,?,?)", [(k, float(v), now()) for k, v in seed.items()])
        con.commit()
    return con


def audit(con, actor: str, action: str, detail: dict) -> None:
    con.execute("INSERT INTO audit VALUES (?,?,?,?)", (now(), actor, action, json.dumps(detail, default=str)))
    con.commit()


def pantry(con) -> dict[str, float]:
    return {r["ingredient"]: r["qty"] for r in con.execute("SELECT * FROM pantry")}


def set_pantry(con, items: dict[str, float]) -> None:
    con.executemany("INSERT OR REPLACE INTO pantry VALUES (?,?,?)",
                    [(k, round(max(0.0, v), 3), now()) for k, v in items.items()])
    con.commit()


def history(con) -> dict[str, dt.date]:
    out: dict[str, dt.date] = {}
    for r in con.execute("SELECT recipe, MAX(date) d FROM history GROUP BY recipe"):
        out[r["recipe"]] = dt.date.fromisoformat(r["d"])
    return out


def portions(con) -> dict[str, float]:
    return {r["recipe"]: r["factor"] for r in con.execute("SELECT * FROM portions")}


def past_load(con, before: str, weeks: int) -> dict[str, int]:
    rows = con.execute("SELECT person, SUM(load) l FROM loads WHERE week_of < ? AND week_of >= ? GROUP BY person",
                       (before, (dt.date.fromisoformat(before) - dt.timedelta(weeks=weeks)).isoformat()))
    return {r["person"]: int(r["l"]) for r in rows}


def save_week(con, week_of: str, **fields) -> None:
    cur = con.execute("SELECT week_of FROM weeks WHERE week_of=?", (week_of,)).fetchone()
    fields = {k: (json.dumps(v, default=str) if not isinstance(v, (str, float, int, type(None))) else v)
              for k, v in fields.items()}
    fields["updated"] = now()
    if cur:
        sets = ", ".join(f"{k}=?" for k in fields)
        con.execute(f"UPDATE weeks SET {sets} WHERE week_of=?", (*fields.values(), week_of))
    else:
        cols = ", ".join(["week_of", *fields])
        con.execute(f"INSERT INTO weeks ({cols}) VALUES ({', '.join('?' * (len(fields) + 1))})",
                    (week_of, *fields.values()))
    con.commit()


def get_week(con, week_of: str) -> dict | None:
    r = con.execute("SELECT * FROM weeks WHERE week_of=?", (week_of,)).fetchone()
    if not r:
        return None
    out = dict(r)
    for k in ("plan", "split", "chores", "pets", "savings", "locks", "shopping_choice"):
        if out.get(k):
            try:
                out[k] = json.loads(out[k])
            except (TypeError, json.JSONDecodeError):
                pass
    return out


def runlog(record: dict) -> None:
    p = work_root() / "logs" / "runs.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps({"ts": now(), **record}, default=str) + "\n")
