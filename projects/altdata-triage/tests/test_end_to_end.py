"""End-to-end test on a throwaway DuckDB: data -> ingest -> dbt build -> triage -> eval gate.

Runs fully offline with the mock provider (EVAL-03: this is what CI runs on every push).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def workdir(tmp_path_factory):
    wd = tmp_path_factory.mktemp("proj")
    for d in ("config", "prompts", "evals", "dbt", "scripts"):
        shutil.copytree(ROOT / d, wd / d, ignore=shutil.ignore_patterns("target", "logs", "security_master.csv"))
    return wd


def run(wd, *args):
    env = {**os.environ, "ALTDATA_ROOT": str(wd), "DUCKDB_PATH": "warehouse/test.duckdb"}
    return subprocess.run([sys.executable, "-m", "altdata_triage", *args], cwd=wd, env=env,
                          capture_output=True, text=True)


def test_triage_blocked_before_dbt(workdir):
    r = run(workdir, "triage")
    assert r.returncode != 0 and "DATA-02" in (r.stderr + r.stdout)


def test_end_to_end(workdir):
    for step in ("data", "ingest", "transform"):
        r = run(workdir, step)
        assert r.returncode == 0, r.stdout + r.stderr
    r = run(workdir, "triage")
    assert r.returncode == 0, r.stderr
    assert "v04: ESCALATE" in r.stdout            # injection attempt escalated by policy
    assert (workdir / "output" / "memos" / "v01.md").exists()
    r = run(workdir, "eval")
    assert r.returncode == 0 and "EVAL GATE: PASS" in r.stdout, r.stdout + r.stderr
