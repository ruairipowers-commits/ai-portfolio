"""OBS-03 retention: archive audit rows older than the retention period, with a hash manifest, then delete.

Dry run by default. Each archive file is JSON Lines plus a manifest with row counts and SHA-256, so an auditor can
check nothing was altered. In AWS the archive goes to an S3 bucket with Object Lock (WORM) — see docs/aws-native.md.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from . import telemetry
from .store import Settings, connect, workspace

TABLES = {"audit.runs": "ts", "audit.explanations": "ts", "audit.alerts": "ts", "audit.feedback": "ts"}


def apply_retention(settings: Settings, days: int | None = None, apply: bool = False, actor: str = "cli") -> dict:
    days = settings["governance"]["log_retention_days"] if days is None else days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_dir = workspace() / settings["governance"]["archive_dir"] / stamp
    report = {"cutoff": cutoff.isoformat(timespec="seconds"), "apply": apply, "tables": {}}
    with connect(settings) as con:
        for table, col in TABLES.items():
            rows = con.execute(f"select * from {table} where {col} < %s", (cutoff,)).fetchall()
            report["tables"][table] = {"rows": len(rows)}
            if not rows or not apply:
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            body = "".join(json.dumps(r, default=str, sort_keys=True) + "\n" for r in rows)
            path = out_dir / f"{table.replace('.', '_')}.jsonl"
            path.write_text(body)
            report["tables"][table].update(file=str(path), sha256=hashlib.sha256(body.encode()).hexdigest())
            con.execute(f"delete from {table} where {col} < %s", (cutoff,))
        if apply and any(t["rows"] for t in report["tables"].values()):
            (out_dir / "manifest.json").write_text(json.dumps(report, indent=2))
        con.commit()
    telemetry.record("retention", event_type="admin", actor=actor, status="applied" if apply else "dry-run",
                     items=sum(t["rows"] for t in report["tables"].values()), detail={"cutoff": report["cutoff"]})
    return report
