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
    monkeypatch.delenv("LAUNCHES_MODE", raising=False)
    return spool


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A fresh database on the offline sample, in a temp dir."""
    from launchtracker import db, load
    from launchtracker.config import Settings

    if not (ROOT / "data" / "fixture" / "gcat_launch.tsv").exists():
        import runpy
        runpy.run_path(str(ROOT / "scripts" / "generate_sample_data.py"), run_name="__main__")
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "t.duckdb"))
    s = Settings.load()
    con = db.connect(s)
    load.load_all(con, s)
    yield s, con
    con.close()
