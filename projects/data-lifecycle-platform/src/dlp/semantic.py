"""LAYER 3 — the semantic layer: governed metrics computed in SQL (dbt + MetricFlow on DuckDB).

What lives here: metric definitions (semantic/models/marts/semantic.yml), the dbt build and its tests (the DATA-02
gate), and `query()` — the only way anything above this layer gets a number. Every query returns the SQL that
produced it so the run log can show where each number came from (NFR-2).
What does not: meaning (ontology), relationships between things (graph), or what a model may see (context).
"""
from __future__ import annotations

import functools
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd
import yaml
from sqlmodel import select

from . import store
from .config import ROOT, Settings, sha


class QualityGateError(RuntimeError):
    """DATA-02: a data test failed, so nothing downstream may run."""


class MetricNotDefined(KeyError):
    pass


# ---------------------------------------------------------------- build
def export_catalog(settings: Settings) -> dict:
    """Write the catalog tables the semantic layer reads (contracts, datasets, customers) to the landing zone."""
    landing = settings.path("landing")
    landing.mkdir(parents=True, exist_ok=True)
    with store.session(settings) as s:
        contracts = s.exec(select(store.Contract)).all()
        datasets = s.exec(select(store.Dataset)).all()
        customers = s.exec(select(store.Customer)).all()
    crow = [{"id": c.id, "customer_id": c.customer_id, "dataset_id": d, "start_date": c.start.isoformat(),
             "end_date": c.end.isoformat(), "price_usd": c.price_usd, "n_datasets": len(c.datasets), "status": c.status}
            for c in contracts for d in c.datasets]
    pd.DataFrame(crow).to_parquet(landing / "catalog_contracts.parquet", index=False)
    pd.DataFrame([{"id": d.id, "title": d.title, "vendor_id": d.vendor_id, "category": d.category,
                   "licence": d.licence, "price_model": d.price_model, "list_price_usd": d.list_price_usd}
                  for d in datasets]).to_parquet(landing / "catalog_datasets.parquet", index=False)
    pd.DataFrame([{"id": c.id, "name": c.name} for c in customers]).to_parquet(
        landing / "catalog_customers.parquet", index=False)
    return {"contracts": len(crow), "datasets": len(datasets), "customers": len(customers)}


def _env(settings: Settings) -> dict:
    env = dict(os.environ)
    env["DLP_LANDING"] = str(settings.path("landing").resolve())
    env["DLP_WAREHOUSE"] = str(settings.path("warehouse_db").resolve())
    env.setdefault("DBT_SEND_ANONYMOUS_USAGE_STATS", "false")
    return env


def _project(settings: Settings) -> Path:
    return settings.layer("semantic_project")


def _target(settings: Settings) -> Path:
    from .config import workspace
    return workspace() / "semantic" / "target"


def _dbt(settings: Settings, *args: str) -> subprocess.CompletedProcess:
    proj = _project(settings)
    cmd = [sys.executable, "-m", "dbt.cli.main", *args, "--project-dir", str(proj), "--profiles-dir", str(proj),
           "--target-path", str(_target(settings)), "--log-path", str(_target(settings).parent / "logs")]
    return subprocess.run(cmd, capture_output=True, text=True, env=_env(settings))


def build(settings: Settings) -> dict:
    """dbt build (models + tests). Raises QualityGateError when a test fails (DATA-02)."""
    settings.path("warehouse_db").parent.mkdir(parents=True, exist_ok=True)
    export_catalog(settings)
    proc = _dbt(settings, "build", "--quiet")
    results = _target(settings) / "run_results.json"
    summary = {"models": 0, "tests_passed": 0, "tests_failed": 0, "failures": []}
    if results.exists():
        for r in json.loads(results.read_text())["results"]:
            uid = r["unique_id"]
            if uid.startswith("test."):
                if r["status"] == "pass":
                    summary["tests_passed"] += 1
                else:
                    summary["tests_failed"] += 1
                    summary["failures"].append(f"{uid.split('.')[2]}: {r['status']} ({r.get('failures')} rows)")
            elif uid.startswith("model."):
                summary["models"] += r["status"] == "success"
    if proc.returncode != 0 and not summary["failures"]:
        raise QualityGateError(f"dbt build failed:\n{(proc.stdout + proc.stderr)[-2500:]}")
    if summary["failures"] and settings["data"]["require_dbt_tests_pass"]:
        raise QualityGateError("Data quality gate failed: " + "; ".join(summary["failures"]))
    _write_gate(settings, summary)
    return summary


def _write_gate(settings: Settings, summary: dict) -> None:
    p = settings.path("warehouse_db").parent / "quality_gate.json"
    p.write_text(json.dumps(summary, indent=2))


def gate_passed(settings: Settings) -> bool:
    p = settings.path("warehouse_db").parent / "quality_gate.json"
    return p.exists() and json.loads(p.read_text())["tests_failed"] == 0


# ---------------------------------------------------------------- the metric catalog
@dataclass
class MetricDef:
    name: str
    label: str
    type: str
    ontology_iri: str
    dataset_id: str
    unit: str
    measure: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    expr: str | None = None
    inputs: list[str] = field(default_factory=list)


def _semantic_yaml() -> dict:
    return yaml.safe_load((ROOT / "semantic" / "models" / "marts" / "semantic.yml").read_text())


def metrics() -> dict[str, MetricDef]:
    out = {}
    for m in _semantic_yaml()["metrics"]:
        tp, meta = m.get("type_params", {}), m.get("meta", {})
        out[m["name"]] = MetricDef(
            name=m["name"], label=m.get("label", m["name"]), type=m["type"], ontology_iri=meta.get("ontology_iri", ""),
            dataset_id=meta.get("dataset_id", ""), unit=meta.get("unit", ""), measure=tp.get("measure"),
            numerator=tp.get("numerator"), denominator=tp.get("denominator"), expr=tp.get("expr"),
            inputs=[x["name"] for x in tp.get("metrics", [])])
    return out


def semantic_models() -> dict[str, dict]:
    return {sm["name"]: sm for sm in _semantic_yaml()["semantic_models"]}


# ---------------------------------------------------------------- querying
@dataclass
class MetricResult:
    metric: str
    group_by: list[str]
    where: dict
    rows: list[dict]
    sql: str
    query_id: str
    compiled_by: str

    def value(self, name: str | None = None) -> float | None:
        """The single value of one metric when the result has exactly one row."""
        name = name or self.metric.split(",")[0]
        return self.rows[0].get(name) if len(self.rows) == 1 else None


@functools.lru_cache(maxsize=1)
def _engine():
    """MetricFlow over the dbt semantic manifest (built by `dlp build`). Compiles metric requests to SQL."""
    from dbt_metricflow.cli.cli_configuration import CLIConfiguration

    proj = ROOT / "semantic"
    cfg = CLIConfiguration()
    cfg.setup(dbt_profiles_path=proj, dbt_project_path=proj, configure_file_logging=False)
    return cfg


def _lit(v) -> str:
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def compile_sql(metric_names: list[str], group_by: list[str] | None = None, where: dict | None = None,
                start: str | None = None, end: str | None = None) -> str:
    """Compile metrics to SQL with MetricFlow. Group-by and filter names use MetricFlow's entity__dimension form
    (e.g. option_day__symbol, dataset__title, metric_time__day)."""
    from datetime import datetime

    from metricflow.engine.metricflow_engine import MetricFlowQueryRequest

    defs = metrics()
    for m in metric_names:
        if m not in defs:
            raise MetricNotDefined(f"Metric '{m}' is not defined in the semantic layer")
    conds = []
    for k, v in (where or {}).items():
        vals = v if isinstance(v, (list, tuple)) else [v]
        conds.append("{{ Dimension('%s') }} in (%s)" % (k, ", ".join(_lit(x) for x in vals)))
    req = MetricFlowQueryRequest.create(
        metric_names=list(metric_names), group_by_names=list(group_by or []) or None, where_constraints=conds or None,
        time_constraint_start=datetime.fromisoformat(start) if start else None,
        time_constraint_end=datetime.fromisoformat(end) if end else None,
        order_by_names=list(group_by or []) or None)
    try:
        return _engine().mf.explain(mf_request=req).sql_statement.without_descriptions.sql
    except Exception as e:   # unknown dimension, unsupported join, …
        raise MetricNotDefined(f"MetricFlow could not plan {metric_names} by {group_by}: {str(e).splitlines()[0][:300]}")


def query(settings: Settings, metric: str | list[str], group_by: list[str] | None = None, where: dict | None = None,
          start: str | None = None, end: str | None = None, limit: int = 200) -> MetricResult:
    """The only way a number leaves the semantic layer: MetricFlow compiles, DuckDB (read-only) executes."""
    if settings["data"]["require_dbt_tests_pass"] and not gate_passed(settings):
        raise QualityGateError("The semantic layer has not passed its data tests; run `dlp build`")
    names = [metric] if isinstance(metric, str) else list(metric)
    sql = compile_sql(names, group_by, where, start, end)
    con = duckdb.connect(str(settings.path("warehouse_db")), read_only=True)
    try:
        cur = con.execute(sql)
        cols = [c[0] for c in cur.description]
        data = [dict(zip(cols, r)) for r in cur.fetchmany(limit)]
    finally:
        con.close()
    for r in data:
        for k, v in r.items():
            if isinstance(v, float):
                r[k] = round(v, 4)
            elif hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    return MetricResult(",".join(names), list(group_by or []), where or {}, data, sql, "mq-" + sha(sql), "metricflow")


def table(settings: Settings, sql: str) -> list[dict]:
    """Read-only SQL against the warehouse, for profiling and coverage (never for metric values in answers)."""
    con = duckdb.connect(str(settings.path("warehouse_db")), read_only=True)
    try:
        cur = con.execute(sql)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


def metricflow_validate(settings: Settings) -> dict:
    """Run MetricFlow's own validation over the semantic manifest (`mf validate-configs`), when installed."""
    exe = Path(sys.executable).with_name("mf")
    if not exe.exists():
        return {"ran": False, "reason": "MetricFlow CLI not installed"}
    proc = subprocess.run([str(exe), "validate-configs", "--skip-dw"], capture_output=True, text=True,
                          cwd=_project(settings), env=_env(settings) | {"DBT_PROFILES_DIR": str(_project(settings))})
    out = proc.stdout + proc.stderr
    return {"ran": True, "ok": proc.returncode == 0 and "ERROR" not in out, "output": out[-1500:]}
