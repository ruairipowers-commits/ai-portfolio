"""SQLite on the household's own server: weeks (plan, list, approvals), feedback, specials, pantry, chores load.
The run log (logs/runs.jsonl) holds counts, hashes and model usage — never names or what anyone ate (OBS-01)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

import yaml

from .config import ROOT, current_tenant, work_root

SCHEMA = """
CREATE TABLE IF NOT EXISTS weeks (week_of TEXT PRIMARY KEY, plan TEXT, split TEXT, chores TEXT, pets TEXT,
    savings TEXT, status TEXT, locks TEXT, approved_by TEXT, approved_at TEXT, approve_seconds REAL,
    shopping_choice TEXT, eating_out TEXT, extras TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS feedback (week_of TEXT, day TEXT, meal TEXT, recipe TEXT, eaten TEXT, rating INTEGER,
    by TEXT, ts TEXT, PRIMARY KEY (week_of, day, meal));
CREATE TABLE IF NOT EXISTS specials (id INTEGER PRIMARY KEY, week_of TEXT, store TEXT, ingredient TEXT, price REAL,
    regular REAL, source TEXT, confirmed_by TEXT, ts TEXT, channel TEXT DEFAULT 'any', repeat_weekly INTEGER DEFAULT 0,
    valid_to TEXT, note TEXT, pack REAL);
CREATE TABLE IF NOT EXISTS pantry (ingredient TEXT PRIMARY KEY, qty REAL, updated TEXT, frozen REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS history (recipe TEXT, date TEXT);
CREATE TABLE IF NOT EXISTS portions (recipe TEXT PRIMARY KEY, factor REAL, leftover_streak INTEGER, updated TEXT);
CREATE TABLE IF NOT EXISTS loads (person TEXT, week_of TEXT, load INTEGER, PRIMARY KEY (person, week_of));
CREATE TABLE IF NOT EXISTS audit (ts TEXT, actor TEXT, action TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS spend (id INTEGER PRIMARY KEY, date TEXT, week_of TEXT, merchant TEXT, store TEXT,
    category TEXT, amount REAL, card TEXT, rewards REAL, credit REAL, source TEXT, ref TEXT UNIQUE, note TEXT,
    by TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS prices_seen (store TEXT, ingredient TEXT, price REAL, pack REAL, date TEXT, source TEXT,
    confirmed_by TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS custom_recipes (id TEXT PRIMARY KEY, data TEXT, active INTEGER DEFAULT 1, created_by TEXT,
    updated TEXT);
CREATE TABLE IF NOT EXISTS custom_ingredients (id TEXT PRIMARY KEY, data TEXT, created_by TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS overrides (week_of TEXT, day TEXT, kind TEXT, person TEXT, value TEXT, by TEXT, ts TEXT,
    PRIMARY KEY (week_of, day, kind, person));
CREATE TABLE IF NOT EXISTS freezer (id INTEGER PRIMARY KEY, recipe TEXT, name TEXT, portions REAL, frozen_on TEXT,
    use_by TEXT, used_on TEXT);
CREATE TABLE IF NOT EXISTS outcomes (week_of TEXT, day TEXT, meal TEXT, outcome TEXT, frozen REAL, by TEXT, ts TEXT,
    PRIMARY KEY (week_of, day, meal));
CREATE TABLE IF NOT EXISTS book_shares (code TEXT PRIMARY KEY, created TEXT, by TEXT, revoked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS containers (id INTEGER PRIMARY KEY, number INTEGER, dish TEXT, portions REAL, location TEXT,
    prepared TEXT, use_by TEXT, status TEXT DEFAULT 'in', closed TEXT, card TEXT, by TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS reheat_cards (id TEXT PRIMARY KEY, prepared TEXT, meal TEXT, method TEXT, temp_f INTEGER,
    minutes INTEGER, covered INTEGER, notes TEXT, containers TEXT, contains TEXT, by TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS chef_list (id INTEGER PRIMARY KEY, ingredient TEXT, name TEXT, qty REAL, unit TEXT,
    note TEXT, done INTEGER DEFAULT 0, by TEXT, ts TEXT);
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
    con.execute("PRAGMA busy_timeout=5000")
    con.executescript(SCHEMA)
    # the fictional example household starts with a stocked pantry; a real household starts empty
    if current_tenant() is None and not con.execute("SELECT 1 FROM pantry LIMIT 1").fetchone():
        seed = yaml.safe_load((ROOT / "config" / "pantry.example.yaml").read_text())["items"]
        con.executemany("INSERT INTO pantry (ingredient, qty, updated) VALUES (?,?,?)",
                        [(k, float(v), now()) for k, v in seed.items()])
        con.commit()
    return con


def audit(con, actor: str, action: str, detail: dict) -> None:
    con.execute("INSERT INTO audit VALUES (?,?,?,?)", (now(), actor, action, json.dumps(detail, default=str)))
    con.commit()


def frozen(con) -> dict[str, float]:
    """How much of each ingredient's stock is in the freezer (part of the pantry quantity)."""
    return {r["ingredient"]: r["frozen"] for r in con.execute("SELECT ingredient, frozen FROM pantry") if r["frozen"]}


def freezer_meals(con) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM freezer WHERE used_on IS NULL AND portions > 0 "
                                         "ORDER BY COALESCE(use_by, '9999'), frozen_on")]


def overrides(con, week_of: str) -> tuple[dict[str, set[str]], dict[str, str]]:
    """This week's app changes: (day → people away, day → night kind)."""
    away: dict[str, set[str]] = {}
    nights: dict[str, str] = {}
    for r in con.execute("SELECT day, kind, person, value FROM overrides WHERE week_of = ?", (week_of,)):
        if r["kind"] == "away" and r["value"] == "1":
            away.setdefault(r["day"], set()).add(r["person"])
        elif r["kind"] == "night" and r["value"]:
            nights[r["day"]] = r["value"]
    return away, nights


def picks(con, week_of: str) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], str]]:
    """Meals a person chose for a slot this week, and what was planned there before their first change:
    ({(day, meal): recipe}, {(day, meal): original recipe})."""
    chosen, original = {}, {}
    for r in con.execute("SELECT day, kind, person, value FROM overrides WHERE week_of = ? AND kind IN "
                         "('pick', 'original')", (week_of,)):
        (chosen if r["kind"] == "pick" else original)[(r["day"], r["person"])] = r["value"]
    return chosen, original


def set_pick(con, week_of: str, day: str, meal: str, recipe: str | None, original: str | None, by: str) -> None:
    for kind, value in (("pick", recipe), ("original", original)):
        if value is None:
            con.execute("DELETE FROM overrides WHERE week_of=? AND day=? AND kind=? AND person=?",
                        (week_of, day, kind, meal))
        else:
            con.execute("INSERT OR IGNORE INTO overrides VALUES (?,?,?,?,?,?,?)" if kind == "original" else
                        "INSERT OR REPLACE INTO overrides VALUES (?,?,?,?,?,?,?)",
                        (week_of, day, kind, meal, value, by, now()))
    con.commit()


def pantry(con) -> dict[str, float]:
    return {r["ingredient"]: r["qty"] for r in con.execute("SELECT * FROM pantry")}


def set_pantry(con, items: dict[str, float], frozen: dict[str, float] | None = None) -> None:
    """Set stock levels (never below zero). `frozen`: how much of that stock is in the freezer."""
    con.executemany("INSERT INTO pantry (ingredient, qty, updated) VALUES (?,?,?) ON CONFLICT(ingredient) DO UPDATE "
                    "SET qty = excluded.qty, updated = excluded.updated",
                    [(k, round(max(0.0, v), 3), now()) for k, v in items.items()])
    for k, f in (frozen or {}).items():
        con.execute("UPDATE pantry SET frozen = ? WHERE ingredient = ?", (round(max(0.0, f), 3), k))
    con.execute("UPDATE pantry SET frozen = MIN(frozen, qty)")
    con.commit()


def history(con) -> dict[str, dt.date]:
    out: dict[str, dt.date] = {}
    for r in con.execute("SELECT recipe, MAX(date) d FROM history GROUP BY recipe"):
        out[r["recipe"]] = dt.date.fromisoformat(r["d"])
    return out


def history_all(con) -> dict[str, list[dt.date]]:
    out: dict[str, list[dt.date]] = {}
    for r in con.execute("SELECT recipe, date FROM history"):
        out.setdefault(r["recipe"], []).append(dt.date.fromisoformat(r["date"]))
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
    for k in ("plan", "split", "chores", "pets", "savings", "locks", "shopping_choice", "eating_out", "extras"):
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
