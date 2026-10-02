"""Run dbt-postgres (models + tests) for an as-of time. Detection is SQL; this is the DATA-02 gate."""
from __future__ import annotations

import json
import os
import subprocess

from .store import ROOT, Settings, dbt_env, ensure_database, workspace


def run_dbt(settings: Settings, as_of: str) -> dict:
    """`dbt build` with thresholds and the as-of time as vars. Returns status, summary and per-node results."""
    ensure_database(settings)
    target = workspace() / "dbt" / "target"
    v = {**settings["detection"], "as_of": as_of}
    r = subprocess.run(["dbt", "build", "--project-dir", str(ROOT / "dbt"), "--profiles-dir", str(ROOT / "dbt"),
                        "--target-path", str(target), "--log-path", str(workspace() / "dbt" / "logs"),
                        "--vars", json.dumps(v)],
                       env={**os.environ, **dbt_env(settings)}, capture_output=True, text=True, cwd=ROOT)
    results = []
    rr = target / "run_results.json"
    if rr.exists():
        results = [{"node": x["unique_id"].split(".", 2)[-1], "status": x["status"]}
                   for x in json.loads(rr.read_text())["results"]]
    summary = next((ln for ln in reversed(r.stdout.splitlines()) if "PASS=" in ln), "").split("Done.")[-1].strip()
    return {"ok": r.returncode == 0, "summary": summary, "results": results, "log": r.stdout[-4000:]}
