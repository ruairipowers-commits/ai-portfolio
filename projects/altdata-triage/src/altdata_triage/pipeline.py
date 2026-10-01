"""Programmatic pipeline used by the Streamlit app (and usable from notebooks).

Each step opens and closes its own DuckDB connection so dbt (a separate process) can take the
write lock in between. Nothing here bypasses the controls: triage still refuses to run unless
the last dbt build passed (DATA-02), and the same budgets, guardrails and policy apply.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import evals
from .llm import Budget, BudgetExceeded, LLMClient, Registry, RegistryError
from .store import ROOT, Settings, connect, ingest
from .workflow import (DataQualityGateError, assert_dbt_tests_passed, get_vendor_facts, list_vendors, new_run_id,
                       render_memo_md, triage_vendor)

INCOMING = ROOT / "data" / "incoming"
PRISTINE = ROOT / "data" / "pristine"   # untouched copy of every delivery, for per-vendor reset
SAMPLE_COLUMNS = ["obs_date", "ticker", "metric_value"]
PROVIDER_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


@dataclass
class StepResult:
    ok: bool
    message: str
    detail: str = ""


@dataclass
class TriageRun:
    run_id: str
    spend_usd: float
    rows: list[dict] = field(default_factory=list)   # one per vendor, ready for a table
    memos: dict[str, str] = field(default_factory=dict)
    facts: dict[str, dict] = field(default_factory=dict)
    error: str | None = None


# ------------------------------------------------------------------ inputs
def generate_sample() -> StepResult:
    """Fresh synthetic deliveries (deterministic) — the default input."""
    shutil.rmtree(INCOMING, ignore_errors=True)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_sample_data.py")],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode == 0:
        shutil.rmtree(PRISTINE, ignore_errors=True)
        shutil.copytree(INCOMING, PRISTINE)
    return StepResult(r.returncode == 0, r.stdout.strip() or r.stderr.strip()[-500:])


def vendor_dirs() -> dict[str, Path]:
    out = {}
    for d in sorted(p for p in INCOMING.glob("*") if p.is_dir()):
        m = re.search(r"(?m)^vendor_id:\s*(\S+)", (d / "questionnaire.md").read_text())
        if m:
            out[m.group(1)] = d
    return out


def read_questionnaire(vendor_id: str) -> tuple[dict, str]:
    text = (vendor_dirs()[vendor_id] / "questionnaire.md").read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    return yaml.safe_load(m.group(1)), re.sub(r"^\s*## Vendor notes\s*", "", m.group(2)).strip()


def write_questionnaire(path: Path, meta: dict, notes: str) -> None:
    fm = "\n".join(f"{k}: {str(v).lower() if isinstance(v, bool) else v}" for k, v in meta.items())
    path.write_text(f"---\n{fm}\n---\n\n## Vendor notes\n\n{notes.strip()}\n")


def set_vendor_notes(vendor_id: str, notes: str) -> None:
    """'Try to break it': replace a vendor's free-text notes (the untrusted input the model reads)."""
    meta, _ = read_questionnaire(vendor_id)
    write_questionnaire(vendor_dirs()[vendor_id] / "questionnaire.md", meta, notes)


def add_vendor(csv_bytes: bytes, meta: dict, notes: str) -> StepResult:
    """Add an uploaded vendor sample. CSV must have columns obs_date,ticker,metric_value."""
    header = csv_bytes[:200].decode("utf-8", "replace").splitlines()[0].strip().lower().replace(" ", "")
    if header != "obs_date,ticker,metric_value":
        return StepResult(False, f"CSV header must be 'obs_date,ticker,metric_value' (got '{header[:60]}')")
    if len(csv_bytes) > 20 * 1024 * 1024:
        return StepResult(False, "CSV larger than 20 MB")
    existing = vendor_dirs()
    vid = f"u{len([v for v in existing if v.startswith('u')]) + 1:02d}"
    d = INCOMING / f"{vid}_{re.sub(r'[^a-z0-9]', '', meta['vendor_name'].lower())[:20] or 'upload'}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "sample.csv").write_bytes(csv_bytes)
    write_questionnaire(d / "questionnaire.md", {"vendor_id": vid, **meta}, notes)
    shutil.copytree(d, PRISTINE / d.name, dirs_exist_ok=True)   # "reset" returns to the uploaded file
    return StepResult(True, f"Added {meta['vendor_name']} as {vid}")


# ------------------------------------------------------------------ view / edit / reset vendor data
def read_sample(vendor_id: str):
    """The vendor's panel (sample.csv) as a DataFrame: obs_date (date), ticker (str), metric_value (float)."""
    import pandas as pd

    df = pd.read_csv(vendor_dirs()[vendor_id] / "sample.csv", dtype={"obs_date": str, "ticker": str},
                     keep_default_na=False, na_values={"metric_value": [""]})   # a ticker like "NAN" stays a ticker
    df["obs_date"] = pd.to_datetime(df["obs_date"], errors="coerce").dt.date
    df["metric_value"] = pd.to_numeric(df["metric_value"], errors="coerce")
    return df[SAMPLE_COLUMNS]


def write_sample(vendor_id: str, df) -> StepResult:
    """Validate and save an edited panel. Bad rows are rejected here; subtler problems are dbt's job."""
    import pandas as pd

    if list(df.columns) != SAMPLE_COLUMNS:
        return StepResult(False, f"Columns must be {SAMPLE_COLUMNS}")
    df = df.dropna(how="all")
    bad_date = df["obs_date"].isna().sum()
    bad_ticker = df["ticker"].fillna("").astype(str).str.strip().eq("").sum()
    if bad_date or bad_ticker:
        return StepResult(False, f"{bad_date} row(s) missing a date and {bad_ticker} missing a ticker — fix or delete them")
    out = df.copy()
    out["obs_date"] = pd.to_datetime(out["obs_date"]).dt.strftime("%Y-%m-%d")
    out["ticker"] = out["ticker"].astype(str).str.strip().str.upper()
    out = out.sort_values(["obs_date", "ticker"])
    out.to_csv(vendor_dirs()[vendor_id] / "sample.csv", index=False, float_format="%.2f")
    return StepResult(True, f"Saved {len(out):,} rows for {vendor_id}")


def sample_bytes(vendor_id: str) -> bytes:
    return (vendor_dirs()[vendor_id] / "sample.csv").read_bytes()


def sample_stats(df) -> dict:
    if df.empty:
        return {"rows": 0, "tickers": 0, "first": None, "last": None, "null_pct": 0.0}
    return {"rows": len(df), "tickers": df["ticker"].nunique(), "first": df["obs_date"].min(),
            "last": df["obs_date"].max(), "null_pct": round(100 * df["metric_value"].isna().mean(), 1)}


def update_questionnaire_meta(vendor_id: str, meta: dict) -> StepResult:
    old, notes = read_questionnaire(vendor_id)
    write_questionnaire(vendor_dirs()[vendor_id] / "questionnaire.md", {**old, **meta, "vendor_id": vendor_id}, notes)
    return StepResult(True, f"Saved questionnaire for {vendor_id}")


def _pristine_dir(vendor_id: str) -> Path | None:
    p = PRISTINE / vendor_dirs()[vendor_id].name
    return p if p.exists() else None


def is_modified(vendor_id: str) -> dict:
    """Which of the vendor's files differ from the original delivery."""
    src, orig = vendor_dirs()[vendor_id], _pristine_dir(vendor_id)
    if orig is None:
        return {"sample.csv": False, "questionnaire.md": False}
    return {f: (src / f).read_bytes() != (orig / f).read_bytes() for f in ("sample.csv", "questionnaire.md")}


def reset_vendor(vendor_id: str, files: tuple[str, ...] = ("sample.csv", "questionnaire.md")) -> StepResult:
    orig = _pristine_dir(vendor_id)
    if orig is None:
        return StepResult(False, "No original copy on file; use Reset to sample vendors")
    for f in files:
        shutil.copy2(orig / f, vendor_dirs()[vendor_id] / f)
    return StepResult(True, f"Restored original {', '.join(files)} for {vendor_id}")


def usable_aliases(settings: Settings) -> dict[str, str]:
    """Aliases/models that can actually run here: approved, priced, and with a key if one is needed."""
    reg = Registry(ROOT / "config" / "models.yaml")
    out = {}
    targets = set(reg.aliases.values())
    for name in list(reg.aliases) + [m for m in reg.models if m not in targets]:
        try:
            spec = reg.resolve(name)
        except RegistryError:
            continue
        if not spec.priced() and not settings["cost"]["allow_unpriced_models"]:
            continue
        key = PROVIDER_KEYS.get(spec.provider)
        if key and not os.getenv(key):
            continue
        label = f"{name} → {spec.name}" if name in reg.aliases else name
        out[label] = name
    return out


# ------------------------------------------------------------------ steps
def ingest_step(settings: Settings) -> StepResult:
    try:
        con = connect(settings)
        n = ingest(con)
        con.close()
        return StepResult(True, f"Ingested {n} vendor deliveries")
    except Exception as e:  # surfaced in the UI, not swallowed
        return StepResult(False, f"Ingest failed: {e}")


def transform_step(settings: Settings) -> StepResult:
    env = {**os.environ, "DUCKDB_PATH": str(settings.db_path)}
    r = subprocess.run(["dbt", "build", "--project-dir", str(ROOT / "dbt"), "--profiles-dir", str(ROOT / "dbt"),
                        "--vars", json.dumps({"as_of_date": settings["as_of_date"]})],
                       env=env, cwd=ROOT, capture_output=True, text=True)
    summary = next((ln for ln in reversed(r.stdout.splitlines()) if "PASS=" in ln), "").split("Done.")[-1].strip()
    if r.returncode:
        return StepResult(False, "dbt build failed — AI triage blocked (DATA-02)", r.stdout[-3000:])
    return StepResult(True, f"dbt build passed: {summary}", r.stdout[-3000:])


def dbt_test_results() -> list[dict]:
    rr = ROOT / "dbt" / "target" / "run_results.json"
    if not rr.exists():
        return []
    return [{"node": r["unique_id"].split(".")[-1] if r["unique_id"].startswith("model") else r["unique_id"].split(".")[2],
             "type": r["unique_id"].split(".")[0], "status": r["status"]}
            for r in json.loads(rr.read_text())["results"]]


def triage_step(settings: Settings, alias: str | None = None) -> TriageRun:
    run = TriageRun(run_id=new_run_id(), spend_usd=0.0)
    try:
        if settings["data"]["require_dbt_tests_pass"]:
            assert_dbt_tests_passed()
        c = settings["cost"]
        client = LLMClient(Registry(ROOT / "config" / "models.yaml"),
                           Budget(c["max_usd_per_run"], c["max_input_tokens_per_call"], c["allow_unpriced_models"]),
                           settings["llm"]["retries"])
        con = connect(settings)
        try:
            for v in list_vendors(con):
                r = triage_vendor(con, v, settings, client, run.run_id, alias=alias)
                f = get_vendor_facts(con, v)
                run.facts[v], run.memos[v] = f, render_memo_md(r, f)
                run.rows.append({
                    "vendor_id": v, "vendor": f["vendor_name"], "category": f["category"],
                    "rule_score": f["rule_score"], "model_draft": r.llm_recommendation,
                    "final": r.final_recommendation, "overrides": "; ".join(r.policy_overrides) or "—",
                    "injection_flag": r.injection_suspected, "pii_redactions": r.pii_redactions,
                    "citation_errors": len(r.citation_errors), "cost_usd": round(r.cost_usd, 5),
                })
        finally:
            con.close()
        run.spend_usd = client.budget.spent
    except (DataQualityGateError, BudgetExceeded, RegistryError) as e:
        run.error = str(e)
    return run


def run_all(settings: Settings, alias: str | None = None) -> tuple[list[StepResult], TriageRun | None]:
    """ingest -> dbt build -> triage, stopping at the first failed step."""
    steps = [ingest_step(settings)]
    if steps[-1].ok:
        steps.append(transform_step(settings))
    if not steps[-1].ok:
        return steps, None
    return steps, triage_step(settings, alias)


def record_review(settings: Settings, vendor_id: str, decision: str, reviewer: str, note: str) -> StepResult:
    con = connect(settings)
    try:
        row = con.execute("""select run_id, final_recommendation from audit.triage_results
                             where vendor_id = ? and run_id not like 'eval-%' order by result_ts desc limit 1""",
                          [vendor_id]).fetchone()
        if not row:
            return StepResult(False, "Run triage first")
        con.execute("insert into audit.reviews values (now(),?,?,?,?,?,?,?)",
                    [row[0], vendor_id, reviewer, row[1], decision, row[1] == decision, note])
        return StepResult(True, f"Recorded {reviewer}: {vendor_id} → {decision} (AI said {row[1]})")
    finally:
        con.close()


def eval_step(settings: Settings, alias: str = "triage-primary") -> dict:
    con = connect(settings)
    try:
        return evals.run_eval(con, settings, alias)
    finally:
        con.close()


def audit_tables(settings: Settings) -> dict[str, list[dict]]:
    if not settings.db_path.exists():
        return {}
    con = connect(settings)
    try:
        q = {
            "ai_calls": """select call_ts, run_id, vendor_id, model_name, prompt_version, input_tokens, output_tokens,
                                  round(cost_usd, 5) as cost_usd, latency_ms, status
                           from audit.ai_calls order by call_ts desc limit 200""",
            "reviews": "select * from audit.reviews order by review_ts desc",
            "cost_by_model": """select model_name, case when run_id like 'eval-%' then 'eval' else 'prod' end as kind,
                                       count(*) as calls, sum(input_tokens) as input_tokens,
                                       sum(output_tokens) as output_tokens, round(sum(cost_usd), 4) as usd
                                from audit.ai_calls where status = 'ok' group by all order by all""",
        }
        out = {}
        for k, sql in q.items():
            cur = con.execute(sql)
            cols = [c[0] for c in cur.description]
            out[k] = [dict(zip(cols, r)) for r in cur.fetchall()]
        return out
    finally:
        con.close()
