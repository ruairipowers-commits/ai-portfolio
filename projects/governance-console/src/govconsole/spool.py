"""Import events that local runs wrote to the spool file (apps with no GOVERNANCE_URL set).

Default path matches the client: GOVERNANCE_SPOOL or ~/.ai-portfolio/governance/events.jsonl.
Reads incrementally (byte offset kept next to the database) and relies on event_id for idempotency.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .store import PKG_ROOT


def spool_path() -> Path:
    return Path(os.getenv("GOVERNANCE_SPOOL") or Path.home() / ".ai-portfolio" / "governance" / "events.jsonl")


def import_spool(store, path: Path | None = None) -> int:
    path = path or spool_path()
    if not path.exists():
        return 0
    marker = PKG_ROOT / "warehouse" / f"spool-{hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:10]}.offset"
    offset = int(marker.read_text()) if marker.exists() else 0
    if offset > path.stat().st_size:      # file was truncated / replaced
        offset = 0
    events = []
    with path.open("rb") as f:
        f.seek(offset)
        for line in f:
            if not line.endswith(b"\n"):
                break                     # partial line still being written
            offset += len(line)
            try:
                e = json.loads(line)
                e["source"] = "live"
                events.append(e)
            except ValueError:
                continue
    n = store.insert_events(events) if events else 0
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(offset))
    return n
