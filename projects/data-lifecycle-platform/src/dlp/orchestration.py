"""Dagster definitions: the build as software-defined assets, plus the daily schedules.

    landing_files → semantic_layer (dbt build + tests, asset check) → knowledge_graph (SHACL, asset check)
    renewal_alerts (daily): contracts whose notice deadline is inside the alert window
Run the UI with `dagster dev -m dlp.orchestration`. The same functions back `dlp build`, so CI and the app don't
need Dagster running; lineage still lands in the graph from the dbt manifest Dagster's assets mirror.
"""
from __future__ import annotations

try:   # optional surface: not in the demo image; install with  pip install -e ".[orchestration]"
    from dagster import (AssetCheckResult, AssetExecutionContext, Definitions, MaterializeResult, ScheduleDefinition,
                         asset, asset_check, define_asset_job, job, op)
except ImportError as e:
    raise ImportError("orchestration.py needs the 'orchestration' extra: pip install -e \".[orchestration]\"") from e

from . import graph, licensing, pipeline, semantic, store
from .config import Settings


@asset(description="Landing files: real Hugging Face slices after `dlp fetch`, otherwise the offline fixture.")
def landing_files() -> MaterializeResult:
    src = pipeline.ensure_landing(Settings.load())
    return MaterializeResult(metadata={"source": src})


@asset(deps=[landing_files], description="dbt build of the semantic layer (models + data tests). DATA-02 gate.")
def semantic_layer() -> MaterializeResult:
    r = semantic.build(Settings.load())           # raises QualityGateError, failing the run
    return MaterializeResult(metadata={"models": r["models"], "tests_passed": r["tests_passed"]})


@asset_check(asset=semantic_layer, description="All dbt data tests passed")
def data_tests_pass() -> AssetCheckResult:
    return AssetCheckResult(passed=semantic.gate_passed(Settings.load()))


@asset(deps=[semantic_layer], description="Knowledge graph: catalog + warehouse facts → SHACL → Oxigraph.")
def knowledge_graph() -> MaterializeResult:
    r = graph.build(Settings.load())
    return MaterializeResult(metadata={k: r[k] for k in ("instance_triples", "conforms", "graph_version")})


@asset_check(asset=knowledge_graph, description="Graph conforms to the SHACL shapes")
def graph_conforms() -> AssetCheckResult:
    return AssetCheckResult(passed=bool(graph.info(Settings.load()).get("conforms")))


@op
def check_renewals(context) -> list:
    s = Settings.load()
    with store.session(s) as ss:
        due = licensing.renewals(ss, s)
    for r in due:
        context.log.warning(f"{r['contract_id']}: notice deadline {r['notice_deadline']} ({r['days_to_deadline']} days)")
    return due


@job
def renewal_alerts():
    check_renewals()


build_job = define_asset_job("build", selection=[landing_files, semantic_layer, knowledge_graph])

defs = Definitions(
    assets=[landing_files, semantic_layer, knowledge_graph],
    asset_checks=[data_tests_pass, graph_conforms],
    jobs=[build_job, renewal_alerts],
    schedules=[ScheduleDefinition(job=build_job, cron_schedule="15 6 * * *", execution_timezone="America/New_York"),
               ScheduleDefinition(job=renewal_alerts, cron_schedule="0 7 * * 1-5", execution_timezone="America/New_York")],
)
