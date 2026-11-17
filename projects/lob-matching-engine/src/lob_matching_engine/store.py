"""Config loading, the SQLite store and the audit log (OBS-01).

Tables: runs, events (the engine event log for each run), alerts, ai_calls, narratives, dispositions.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import demo


def _find_root() -> Path:
    if os.getenv("LOB_ROOT"):
        return Path(os.environ["LOB_ROOT"])
    if (Path.cwd() / "config" / "settings.yaml").exists() and (Path.cwd() / "prompts").exists():
        return Path.cwd()
    return Path(__file__).resolve().parents[2]


ROOT = _find_root()


def workspace() -> Path:
    """Where mutable data lives: the project root, or this visitor's sandbox in the hosted demo."""
    return demo.current() or ROOT


@dataclass
class Settings:
    raw: dict

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        return cls(yaml.safe_load((path or ROOT / "config" / "settings.yaml").read_text()))

    def __getitem__(self, k):
        return self.raw[k]

    @property
    def db_path(self) -> Path:
        return workspace() / os.getenv("LOB_STORE", self.raw["store_path"])


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA = """
create table if not exists runs (run_id text primary key, started text, source text, commands integer,
    gate_ok integer, gate_errors text, stats text, alerts integer, spend_usd real, seconds real);
create table if not exists events (run_id text, event_id integer, cmd_seq integer, ts_ms integer, event text,
    order_id integer, trader text, side text, price integer, qty integer, reason text, maker_id integer,
    maker_trader text);
create index if not exists events_run on events(run_id, event_id);
create table if not exists alerts (run_id text, alert_id text, pattern text, severity text, trader text,
    event_ids text, facts text);
create table if not exists ai_calls (run_id text, call_ts text, purpose text, alert_id text, alias text,
    model_name text, provider text, model_id text, prompt_version text, prompt_sha text, input_sha text,
    input_tokens integer, output_tokens integer, cost_usd real, latency_ms integer, used_fallback integer,
    status text, error text);
create table if not exists narratives (run_id text, result_ts text, alert_id text, pattern text, severity text,
    model_name text, model_suggestion text, final_suggestion text, policy_overrides text, citation_errors text,
    schema_valid integer, injection_suspected integer, pii_redactions integer, narrative_json text);
create table if not exists dispositions (review_ts text, run_id text, alert_id text, severity text, reviewer text,
    ai_suggestion text, decision text, agrees_with_ai integer, reason text);
"""


def connect(settings: Settings) -> sqlite3.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def log_call(con, **kw) -> None:
    cols = ["run_id", "call_ts", "purpose", "alert_id", "alias", "model_name", "provider", "model_id",
            "prompt_version", "prompt_sha", "input_sha", "input_tokens", "output_tokens", "cost_usd",
            "latency_ms", "used_fallback", "status", "error"]
    kw.setdefault("call_ts", now())
    con.execute(f"insert into ai_calls ({','.join(cols)}) values ({','.join('?' * len(cols))})",
                [kw.get(c) for c in cols])
    con.commit()


def log_result(con, run_id: str, r) -> None:
    con.execute("insert into narratives values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [run_id, now(), r.alert_id, r.pattern, r.severity, r.model_name, r.model_suggestion,
                 r.final_suggestion, json.dumps(r.policy_overrides), json.dumps(r.citation_errors),
                 int(r.schema_valid), int(r.injection_suspected), r.pii_redactions, r.narrative.model_dump_json()])
    con.commit()


def save_events(con, run_id: str, events) -> None:
    cols = ["event_id", "cmd_seq", "ts_ms", "event", "order_id", "trader", "side", "price", "qty", "reason",
            "maker_id", "maker_trader"]
    rows = [[run_id] + [None if (v != v) else v for v in (r[c] for c in cols)]   # NaN -> NULL
            for r in events[cols].astype(object).to_dict("records")]
    con.executemany(f"insert into events (run_id,{','.join(cols)}) values ({','.join('?' * (len(cols) + 1))})", rows)
    con.commit()


def save_alerts(con, run_id: str, alerts: list[dict]) -> None:
    con.executemany("insert into alerts values (?,?,?,?,?,?,?)",
                    [[run_id, a["alert_id"], a["pattern"], a["severity"], a["trader"], json.dumps(a["event_ids"]),
                      json.dumps(a["facts"])] for a in alerts])
    con.commit()


def rows(con, sql: str, args=()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, args).fetchall()]
