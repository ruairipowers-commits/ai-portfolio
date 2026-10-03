import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def store(tmp_path):
    from govconsole.store import Store

    return Store(str(tmp_path / "console.sqlite"))


@pytest.fixture()
def client(store, monkeypatch, tmp_path):
    """Console over a fresh database with seeded history; local mode (admin open, no ingest token)."""
    from fastapi.testclient import TestClient

    from govconsole import app as appmod

    for k in ("PORTFOLIO_DEMO", "GOVERNANCE_ADMIN_TOKEN", "GOVERNANCE_INGEST_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GOVERNANCE_SPOOL", str(tmp_path / "no-spool.jsonl"))
    monkeypatch.setenv("GOVERNANCE_HOST_CHECK", "0")       # tests drive host.check() themselves
    appmod.S.hits.clear()
    return TestClient(appmod.create_app(store))


def event(**kw) -> dict:
    import uuid
    from datetime import datetime, timezone

    base = {"event_id": uuid.uuid4().hex, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "workflow": "altdata-triage", "event_type": "triage", "status": "ok", "actor": "tester", "actor_type": "named",
            "model": "mock-local", "input_tokens": 100, "output_tokens": 20, "cost_usd": 0.5, "latency_ms": 900,
            "records_in": 10, "records_out": 2, "flags": [], "detail": {}}
    return {**base, **kw}
