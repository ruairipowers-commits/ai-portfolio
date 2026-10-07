"""Prefect flows for the scheduled refreshes (optional: `pip install -e ".[flows]"`, then `launches flows`).

The CLI and the hosted demo's loop run the same steps without Prefect; Prefect adds schedules, retries, run history
and a UI. Cadences come from config/settings.yaml (sources.*), so the Launch Library 2 budget is respected either way.
"""
from __future__ import annotations

try:   # optional surface: install with  pip install -e ".[flows]"
    from prefect import flow, serve, task
except ImportError as e:
    raise ImportError("flows.py needs the 'flows' extra: pip install -e \".[flows]\"") from e

from . import db, summaries
from .config import Settings
from .refresh import refresh_once


@task(retries=2, retry_delay_seconds=300)
def _refresh(live: bool) -> dict:
    return refresh_once(Settings.load(), live=live)


@task
def _changes() -> str:
    s = Settings.load()
    con = db.connect(s)
    try:
        return summaries.what_changed(con, s, actor="service:prefect").text
    finally:
        con.close()


@flow(name="refresh-launches", log_prints=True)
def refresh_launches(live: bool = True) -> dict:
    stats = _refresh(live)
    print(stats)
    print(_changes())
    return stats


@flow(name="weekly-digest", log_prints=True)
def weekly_digest() -> str:
    s = Settings.load()
    con = db.connect(s)
    try:
        r = summaries.digest(con, s, actor="service:prefect")
        print(r.text)
        return r.text
    finally:
        con.close()


def serve_all() -> None:
    s = Settings.load()
    minutes = s["sources"]["ll2"]["upcoming_refresh_minutes"]
    serve(refresh_launches.to_deployment(name="hourly", interval=minutes * 60, parameters={"live": True}),
          weekly_digest.to_deployment(name="mondays", cron="5 13 * * 1"))
