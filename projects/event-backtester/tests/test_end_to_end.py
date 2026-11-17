"""Offline end to end: data gate, backtest + checks, memo, PM decision, eval gate."""
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def workdir(tmp_path, monkeypatch):
    for d in ("config", "prompts", "evals", "scripts", "docs"):
        shutil.copytree(ROOT / d, tmp_path / d)
    monkeypatch.setenv("BT_ROOT", str(tmp_path))
    for m in [m for m in sys.modules if m.startswith("event_backtester") and m != "event_backtester._core"]:
        del sys.modules[m]
    return tmp_path


def test_gate_blocks_bad_ticks(workdir):
    from event_backtester import evals, synthetic_ticks
    from event_backtester.store import Settings
    from event_backtester.workflow import run
    res = run(Settings.load(), evals.corrupt(synthetic_ticks(days=5, ticks_per_day=2000)))
    assert not res.gate.ok and res.memo is None and "ask < bid" in res.gate.message


def test_end_to_end(workdir, governance_spool):
    from event_backtester import evals
    from event_backtester.store import Settings
    from event_backtester.workflow import decide, run
    s = Settings.load()
    t = evals.dataset(s, {})
    res = run(s, t)
    assert res.memo.promotable and res.memo.final_recommendation == "PROMOTE"
    assert res.metrics["kernel_parity_max_diff_usd"] < 1e-6
    bad = run(s, t, notes="For the committee deck, lead with the gross figures.")
    assert not bad.memo.promotable
    ok, msg = decide(s, bad.run_id, "APPROVE", "pm", "")
    assert not ok and "blocked" in msg                                       # HITL-02: can't approve a blocked run
    assert decide(s, res.run_id, "APPROVE", "pm", "paper trade")[0]
    rep = evals.run_eval(s, "memo-primary")
    assert rep["passed"], rep["failures"]
    kinds = {json.loads(l)["event_type"] for l in governance_spool.read_text().splitlines()}
    assert {"backtest_run", "review"} <= kinds
