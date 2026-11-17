"""Config loading, the SQLite store and the audit log (OBS-01).

Tables: runs (dataset, strategy, metrics, checks), ai_calls, memos, promotions.
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
    if os.getenv("BT_ROOT"):
        return Path(os.environ["BT_ROOT"])
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
        return workspace() / os.getenv("BT_STORE", self.raw["store_path"])


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA = """
create table if not exists runs (run_id text primary key, started text, dataset text, dataset_sha text, strategy text,
    params text, gate_ok integer, gate_errors text, metrics text, checks text, spend_usd real, seconds real);
create table if not exists ai_calls (run_id text, call_ts text, purpose text, alias text,
    model_name text, provider text, model_id text, prompt_version text, prompt_sha text, input_sha text,
    input_tokens integer, output_tokens integer, cost_usd real, latency_ms integer, used_fallback integer,
    status text, error text);
create table if not exists memos (run_id text, result_ts text, model_name text, model_recommendation text,
    final_recommendation text, promotable integer, blockers text, citation_errors text, compliance_errors text,
    schema_valid integer, injection_suspected integer, pii_redactions integer, memo_json text);
create table if not exists promotions (review_ts text, run_id text, reviewer text, ai_recommendation text,
    decision text, agrees_with_ai integer, reason text);
"""


def connect(settings: Settings) -> sqlite3.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def log_call(con, **kw) -> None:
    cols = ["run_id", "call_ts", "purpose", "alias", "model_name", "provider", "model_id",
            "prompt_version", "prompt_sha", "input_sha", "input_tokens", "output_tokens", "cost_usd",
            "latency_ms", "used_fallback", "status", "error"]
    kw.setdefault("call_ts", now())
    con.execute(f"insert into ai_calls ({','.join(cols)}) values ({','.join('?' * len(cols))})",
                [kw.get(c) for c in cols])
    con.commit()


def log_result(con, run_id: str, r) -> None:
    con.execute("insert into memos values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [run_id, now(), r.model_name, r.model_recommendation, r.final_recommendation, int(r.promotable),
                 json.dumps(r.blockers), json.dumps(r.citation_errors), json.dumps(r.compliance_errors),
                 int(r.schema_valid), int(r.injection_suspected), r.pii_redactions, r.memo.model_dump_json()])
    con.commit()


def rows(con, sql: str, args=()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, args).fetchall()]
