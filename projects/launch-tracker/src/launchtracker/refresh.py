"""One refresh cycle, and the loop the hosted demo runs in live mode.

A refresh copies the current database, loads the sources into the copy (keeping request counts, target-time
snapshots, reviews and the audit log, which live in the same file), then swaps it in with an atomic rename. Readers
never see a half-written database, and the Launch Library 2 budget carries across refreshes.
"""
from __future__ import annotations

import os
import shutil
import time

from . import db, load, telemetry
from .config import Settings, utcnow


def refresh_once(settings: Settings, live: bool | None = None) -> dict:
    telemetry.require_enabled("refresh", actor="service:refresh")    # the kill switch stops refreshes too
    path = settings.db_path
    nxt = path.with_suffix(".next.duckdb")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, nxt)
    elif nxt.exists():
        nxt.unlink()
    con = db.duckdb.connect(str(nxt))
    con.execute(db.SCHEMA)
    con.execute("set TimeZone = 'UTC'")
    t0 = time.perf_counter()
    try:
        stats = load.load_all(con, settings, fetch_live=live)
        con.execute("checkpoint")      # everything in the main file before the copy is swapped in
    finally:
        con.close()
    os.replace(nxt, path)
    telemetry.record("refresh", actor="service:refresh", items=stats["launches"], rows_in=stats["ll2_records"],
                     latency_ms=int((time.perf_counter() - t0) * 1000),
                     flags=["live"] if (live if live is not None else settings.mode == "live") else ["fixture"],
                     detail={"requests": stats["requests"]})
    return stats


def loop(settings: Settings) -> None:
    """The hosted demo's background refresher (live mode): every upcoming_refresh_minutes, within the request budget."""
    minutes = settings["sources"]["ll2"]["upcoming_refresh_minutes"]
    while True:
        try:
            s = refresh_once(settings, live=True)
            print(f"{utcnow():%Y-%m-%d %H:%M} refresh: {s}", flush=True)
        except telemetry.WorkflowDisabled as e:
            print(f"refresh skipped: {e}", flush=True)
        except Exception as e:                       # keep serving the last good data; say why
            print(f"refresh failed (serving the last good data): {e}", flush=True)
        time.sleep(minutes * 60)
