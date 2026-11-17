"""Offline end to end: data gate, replay, detectors, narratives, review, eval gate."""
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def workdir(tmp_path, monkeypatch):
    for d in ("config", "prompts", "evals", "scripts", "docs"):
        shutil.copytree(ROOT / d, tmp_path / d)
    monkeypatch.setenv("LOB_ROOT", str(tmp_path))
    import sys
    for m in [m for m in sys.modules if m.startswith("lob_matching_engine") and m != "lob_matching_engine._engine"]:
        del sys.modules[m]
    return tmp_path


def test_gate_blocks_bad_session(workdir):
    from lob_matching_engine import sessions
    from lob_matching_engine.store import Settings
    from lob_matching_engine.workflow import run
    df = sessions.generate(noise_commands=2000, behaviours=())
    df.loc[100, "ts_ms"] = -5
    res = run(Settings.load(), df)
    assert not res.gate.ok and res.replay is None and not res.results
    assert "time goes backwards" in res.gate.message


def test_end_to_end(workdir, governance_spool):
    from lob_matching_engine import evals, sessions
    from lob_matching_engine.store import Settings, connect, rows
    from lob_matching_engine.workflow import dispose, run
    s = Settings.load()
    res = run(s, sessions.generate())
    assert {a["pattern"] for a in res.alerts} == {"layering", "wash", "stuffing", "ignition"}
    assert all(r.schema_valid and not r.citation_errors for r in res.results)
    assert all("L07" not in p and "M05" not in p for p in res.payloads)          # pseudonyms only
    con = connect(s)
    assert rows(con, "select count(*) n from ai_calls where run_id=?", [res.run_id])[0]["n"] == 4
    high = next(r for r in res.results if r.severity == "high")
    ok, msg = dispose(s, res.run_id, high.alert_id, "CLOSE", "analyst", "")
    assert not ok and "reason" in msg                                              # HITL-02
    ok, _ = dispose(s, res.run_id, high.alert_id, "CLOSE", "analyst", "explained by a client unwind, see ticket 42")
    assert ok
    rep = evals.run_eval(s, "narrative-primary")
    assert rep["passed"], rep["failures"]
    assert rep["metrics"]["human_agreement"] == 0.0                                # the override is counted (HITL-03)
    kinds = [json.loads(l)["event_type"] for l in governance_spool.read_text().splitlines()]
    assert {"surveillance_run", "review"} <= set(kinds)
