"""Tests share one embedded Postgres server (started once, stopped at exit) but each gets its own database and
its own copy of the project files."""
import importlib
import shutil
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def pg_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("pg")


@pytest.fixture()
def project(tmp_path, monkeypatch, pg_dir):
    for d in ("config", "prompts", "evals", "scripts", "docs", "kb", "dbt"):
        shutil.copytree(ROOT / d, tmp_path / d, ignore=shutil.ignore_patterns("target", "logs"))
    (tmp_path / "warehouse").symlink_to(pg_dir, target_is_directory=True)   # one server for the whole session
    cfg = tmp_path / "config" / "settings.yaml"
    cfg.write_text(cfg.read_text().replace("database_name: eod", f"database_name: eod_t{uuid.uuid4().hex[:8]}"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EOD_ROOT", str(tmp_path))
    monkeypatch.setenv("EOD_PG_CLEANUP", "stop")
    monkeypatch.setenv("GOVERNANCE_DB", str(tmp_path / "governance.sqlite"))
    monkeypatch.delenv("PORTFOLIO_DEMO", raising=False)
    monkeypatch.delenv("EOD_DATABASE_URL", raising=False)
    for m in [m for m in sys.modules if m.startswith("eod_heartbeat")]:
        del sys.modules[m]
    return tmp_path


@pytest.fixture()
def m(project):
    names = ["cli", "evals", "explain", "kb", "llm", "loader", "retention", "store", "telemetry", "transform"]
    return SimpleNamespace(**{n: importlib.import_module(f"eod_heartbeat.{n}") for n in names})


@pytest.fixture()
def ready(m):
    s = m.store.Settings.load()
    m.cli.reset_all(s)
    return s
