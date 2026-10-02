"""Airflow DAG: the EOD heartbeat. Every 5 minutes, 17:00-21:00 ET on weekdays (NFR-1: alert within 5 minutes of an
SLA breach). Each run is idempotent: it reloads what has landed, rebuilds the dbt models for the as-of time, and only
explains and alerts on breaks that haven't been alerted yet (alerts are de-duplicated by break id).

The tasks call the same functions as `eodhb check` and the app, so local runs and Airflow runs behave the same.
Install the project into the Airflow image (`pip install .`) and set EOD_DATABASE_URL to the shared Postgres.
"""
from __future__ import annotations

import pendulum

try:  # Airflow 3
    from airflow.sdk import dag, task
except ImportError:  # Airflow 2.x
    from airflow.decorators import dag, task

ET = pendulum.timezone("America/New_York")


@dag(
    dag_id="eod_heartbeat",
    schedule="*/5 17-21 * * 1-5",
    start_date=pendulum.datetime(2026, 9, 1, tz=ET),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": pendulum.duration(minutes=1)},
    tags=["fund-ops", "eod", "ai-explainer"],
    doc_md=__doc__,
)
def eod_heartbeat():
    @task
    def as_of(logical_date=None, data_interval_end=None) -> dict:
        t = (data_interval_end or logical_date).in_timezone(ET)
        return {"business_date": t.to_date_string(), "as_of_time": t.strftime("%H:%M")}

    @task
    def load_feeds() -> dict:
        from eod_heartbeat.loader import load
        from eod_heartbeat.store import Settings

        return load(Settings.load())

    @task
    def dbt_build(ctx: dict, _loaded: dict) -> dict:
        from eod_heartbeat.store import Settings
        from eod_heartbeat.transform import run_dbt

        r = run_dbt(Settings.load(), f"{ctx['business_date']} {ctx['as_of_time']}")
        if not r["ok"]:   # DATA-02: fail the task, so no explanation is produced from data that failed its tests
            raise RuntimeError(f"dbt build failed: {r['summary']}\n{r['log'][-2000:]}")
        return {"summary": r["summary"], "ok": True, "results": [], "log": ""}

    @task
    def explain_and_alert(ctx: dict, dbt: dict) -> dict:
        from eod_heartbeat.explain import run_eod
        from eod_heartbeat.store import Settings

        r = run_eod(Settings.load(), ctx["business_date"], ctx["as_of_time"], actor="airflow", trigger="airflow",
                    reload=False, dbt_result=dbt)
        return r["summary"]

    @task
    def send_alerts(_summary: dict) -> int:
        from eod_heartbeat.explain import send_pending
        from eod_heartbeat.store import Settings

        return send_pending(Settings.load())

    ctx = as_of()
    built = dbt_build(ctx, load_feeds())
    send_alerts(explain_and_alert(ctx, built))


eod_heartbeat()
