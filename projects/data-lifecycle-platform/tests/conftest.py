import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def governance_spool(tmp_path, monkeypatch):
    """Telemetry goes to a per-test spool file, never to ~/.ai-portfolio or a real console."""
    spool = tmp_path / "governance-events.jsonl"
    monkeypatch.setenv("GOVERNANCE_SPOOL", str(spool))
    monkeypatch.delenv("GOVERNANCE_URL", raising=False)
    monkeypatch.delenv("GOVERNANCE_TELEMETRY", raising=False)
    return spool


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    """One full offline build in a scratch workspace, shared by the tests that only read."""
    ws = tmp_path_factory.mktemp("ws")
    os.environ["DLP_WORKSPACE"] = str(ws)
    os.environ["GOVERNANCE_TELEMETRY"] = "off"
    from dlp import pipeline
    from dlp.config import Settings

    s = Settings.load()
    rep = pipeline.build(s)
    os.environ.pop("GOVERNANCE_TELEMETRY", None)
    yield s, rep


@pytest.fixture()
def fresh(built):
    """A writable store for tests that change the catalog: reseed (fast) and rebuild the graph afterwards."""
    from dlp import pipeline

    s, _ = built
    pipeline.seed_all(s)
    yield s
    pipeline.seed_all(s)
    pipeline.refresh_graph(s)
