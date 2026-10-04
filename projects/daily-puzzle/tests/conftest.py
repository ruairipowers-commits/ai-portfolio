import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ["PUZZLE_SCHEDULER"] = "0"


@pytest.fixture(autouse=True)
def governance_spool(tmp_path, monkeypatch):
    """Telemetry goes to a per-test spool file, never to ~/.ai-portfolio or a real console."""
    spool = tmp_path / "governance-events.jsonl"
    monkeypatch.setenv("GOVERNANCE_SPOOL", str(spool))
    monkeypatch.delenv("GOVERNANCE_URL", raising=False)
    monkeypatch.delenv("GOVERNANCE_TELEMETRY", raising=False)
    return spool


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """A throwaway project root (config, prompts, evals, fixtures) with its own database and outbox."""
    for d in ("config", "prompts", "evals", "fixtures"):
        shutil.copytree(ROOT / d, tmp_path / d)
    monkeypatch.setenv("PUZZLE_ROOT", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/warehouse/test.db")
    for k in ("RESEND_API_KEY", "PUZZLE_ADMIN_TOKEN", "PUZZLE_PUBLIC_URL", "ROOT_PATH"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "warehouse").mkdir()
    from daily_puzzle import store
    store.reset_engines()
    yield tmp_path
    store.reset_engines()


@pytest.fixture()
def s(project):
    from daily_puzzle.config import Settings
    return Settings.load()


@pytest.fixture()
def conn(s):
    from daily_puzzle.store import engine
    with engine(s).begin() as c:
        yield c
