"""Config loading, DuckDB access, ingestion and the audit log (OBS-01)."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import yaml

def _find_root() -> Path:
    if os.getenv("ALTDATA_ROOT"):
        return Path(os.environ["ALTDATA_ROOT"])
    if (Path.cwd() / "config" / "settings.yaml").exists():
        return Path.cwd()
    return Path(__file__).resolve().parents[2]


ROOT = _find_root()


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
        return ROOT / os.getenv("DUCKDB_PATH", self.raw["duckdb_path"])


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def now() -> datetime:
    return datetime.now(timezone.utc)


def connect(settings: Settings) -> duckdb.DuckDBPyConnection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(settings.db_path))
    init_audit(con)
    return con


# ---------------------------------------------------------------- ingestion
def _front_matter(md: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", md, re.S)
    if not m:
        raise ValueError("questionnaire.md is missing YAML front matter")
    return yaml.safe_load(m.group(1)), m.group(2).strip()


def ingest(con: duckdb.DuckDBPyConnection, incoming: Path | None = None) -> int:
    """Land every vendor folder into raw.* tables (idempotent full reload)."""
    incoming = incoming or ROOT / "data" / "incoming"
    vendor_dirs = sorted(p for p in incoming.iterdir() if p.is_dir())
    if not vendor_dirs:
        raise FileNotFoundError(f"No vendor folders in {incoming}; run `altdata-triage data` first")
    con.execute("create schema if not exists raw")
    con.execute("drop table if exists raw.vendor_panels")
    con.execute("drop table if exists raw.vendor_questionnaires")
    con.execute("""create table raw.vendor_panels (vendor_id varchar, obs_date varchar, ticker varchar,
                   metric_value varchar, source_file varchar, loaded_at timestamp)""")
    con.execute("""create table raw.vendor_questionnaires (vendor_id varchar, vendor_name varchar, category varchar,
                   pii_present boolean, point_in_time boolean, license_derived_use boolean, delivery varchar,
                   annual_price_usd integer, notes varchar, source_file varchar, loaded_at timestamp)""")
    for d in vendor_dirs:
        meta, notes = _front_matter((d / "questionnaire.md").read_text())
        vid = meta["vendor_id"]
        con.execute(
            f"""insert into raw.vendor_panels
                select ?, obs_date, ticker, metric_value, ?, now()
                from read_csv('{d / "sample.csv"}', header=true, all_varchar=true)""",
            [vid, str(d / "sample.csv")],
        )
        con.execute(
            "insert into raw.vendor_questionnaires values (?,?,?,?,?,?,?,?,?,?,now())",
            [vid, meta["vendor_name"], meta["category"], meta["pii_present"], meta["point_in_time"],
             meta["license_derived_use"], meta["delivery"], meta["annual_price_usd"], notes,
             str(d / "questionnaire.md")],
        )
    return len(vendor_dirs)


# ---------------------------------------------------------------- audit log
def init_audit(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("create schema if not exists audit")
    con.execute("""create table if not exists audit.ai_calls (
        run_id varchar, call_ts timestamp, purpose varchar, vendor_id varchar, alias varchar,
        model_name varchar, provider varchar, model_id varchar, prompt_version varchar, prompt_sha varchar,
        input_sha varchar, input_tokens integer, output_tokens integer, cost_usd double, latency_ms integer,
        used_fallback boolean, status varchar, error varchar)""")
    con.execute("""create table if not exists audit.triage_results (
        run_id varchar, result_ts timestamp, vendor_id varchar, model_name varchar,
        llm_recommendation varchar, final_recommendation varchar, confidence double, rule_score double,
        policy_overrides varchar, citation_errors varchar, schema_valid boolean,
        injection_suspected boolean, memo_json varchar)""")
    con.execute("""create table if not exists audit.reviews (
        review_ts timestamp, run_id varchar, vendor_id varchar, reviewer varchar,
        ai_recommendation varchar, decision varchar, agrees_with_ai boolean, note varchar)""")


def log_call(con, **kw) -> None:
    cols = ["run_id", "call_ts", "purpose", "vendor_id", "alias", "model_name", "provider", "model_id",
            "prompt_version", "prompt_sha", "input_sha", "input_tokens", "output_tokens", "cost_usd",
            "latency_ms", "used_fallback", "status", "error"]
    kw.setdefault("call_ts", now())
    con.execute(f"insert into audit.ai_calls ({','.join(cols)}) values ({','.join('?' * len(cols))})",
                [kw.get(c) for c in cols])


def log_result(con, run_id: str, result, rule_score: float) -> None:
    con.execute(
        "insert into audit.triage_results values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [run_id, now(), result.memo.vendor_id, result.model_name, result.llm_recommendation,
         result.final_recommendation, result.memo.confidence, rule_score,
         json.dumps(result.policy_overrides), json.dumps(result.citation_errors), result.schema_valid,
         result.injection_suspected, result.memo.model_dump_json()],
    )
