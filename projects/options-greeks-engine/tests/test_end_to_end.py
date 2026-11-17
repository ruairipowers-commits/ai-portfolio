"""Offline end to end: request → ticket → approval rules → eval gate."""
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
    monkeypatch.setenv("OPT_ROOT", str(tmp_path))
    for m in [m for m in sys.modules if m.startswith("options_greeks_engine") and m != "options_greeks_engine._optlib"]:
        del sys.modules[m]
    return tmp_path


def test_end_to_end(workdir, governance_spool):
    from options_greeks_engine import evals
    from options_greeks_engine.store import Settings
    from options_greeks_engine.workflow import decide, process
    s = Settings.load()
    good = process(s, "Buy 20 Dec 105/115 call spreads, max debit 3.10", "DR-02")
    assert good.status == "PENDING_APPROVAL" and not good.citation_errors
    cc = good.cross_check
    assert abs(cc["bsm"] - cc["lr_tree"]) < 1 and abs(cc["bsm"] - cc["mc"]) < max(cc["mc_ci95_usd"], 1)
    assert not decide(s, good.ticket_id, "APPROVE", "risk", "ok")[0]                      # reason too short
    assert decide(s, good.ticket_id, "APPROVE", "risk", "within limits, defined risk")[0]
    assert not decide(s, good.ticket_id, "REJECT", "risk", "changed my mind entirely")[0]  # already decided
    bad = process(s, "Sell 15 Dec 120 calls", "LO-01")
    ok, msg = decide(s, bad.ticket_id, "APPROVE", "risk", "trying anyway, see notes")
    assert not ok and "permission" in msg
    rep = evals.run_eval(s, "parse-primary")
    assert rep["passed"], rep["failures"]
    kinds = {json.loads(l)["event_type"] for l in governance_spool.read_text().splitlines()}
    assert {"ticket", "review"} <= kinds
