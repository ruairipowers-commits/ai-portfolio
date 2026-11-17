"""Streamlit app tests (headless). Each test runs in a throwaway project copy."""
import json
import shutil
import sys
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "event_backtester" / "ui.py"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    for d in ("config", "prompts", "evals", "scripts", "docs"):
        shutil.copytree(ROOT / d, tmp_path / d)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BT_ROOT", str(tmp_path))
    for m in [m for m in sys.modules if m.startswith("event_backtester") and m != "event_backtester._core"]:
        del sys.modules[m]
    return st_testing.AppTest.from_file(str(APP), default_timeout=600)


def click(at, label):
    return next(b for b in at.button if label in b.label).click().run()


def promotable(at):
    return next(m.value for m in at.metric if m.label == "Promotable")


def test_default_run_is_promotable(app):
    at = click(app.run(), "Run backtest")
    assert not at.exception, at.exception
    assert "yes" in promotable(at)


def test_inflated_sharpe_is_blocked(app):
    at = click(app.run(), "Inflate the Sharpe")
    at = click(at, "Run backtest")
    assert "no" in promotable(at)
    assert any("Promotion blocked" in e.value for e in at.error)


def test_leaky_strategy_rejected(app):
    at = app.run()
    at.selectbox(key="kind").set_value("Leaky (peeks at the next bar)").run()
    at = click(at, "Run backtest")
    assert "no" in promotable(at) and any("lookahead_clean" in e.value for e in at.error)


def test_corrupt_data_stopped_by_gate(app):
    at = click(app.run(), "Corrupt the data")
    at = click(at, "Run backtest")
    assert any("Data gate failed" in e.value for e in at.error)


def test_pm_cannot_approve_blocked_run_but_can_approve_clean_one(app):
    at = click(app.run(), "Lead with gross")
    at = click(at, "Run backtest")
    at = click(at, "Record decision")
    assert any("Promotion is blocked" in e.value for e in at.error)
    at = click(at, "Reset demo data")
    at = click(at, "Run backtest")
    at = click(at, "Record decision")
    assert any("APPROVE" in x.value for x in at.success)


def test_lab_pages_render(app):
    at = app.run()
    for page in ("lab/data.py", "lab/backtest.py", "lab/costs.py", "lab/optimize.py", "lab/lookahead.py"):
        at.switch_page(page)
        at.run()
        assert not at.exception, (page, at.exception)


def test_custom_code_hidden_in_hosted_demo(app, tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DEMO", "1")
    monkeypatch.setenv("DEMO_SESSIONS_DIR", str(tmp_path / "sessions"))
    at = app.run()
    at.switch_page("lab/backtest.py")
    at.run()
    assert "Custom Python" not in at.sidebar.selectbox[0].options
    from event_backtester.workflow import factory
    with pytest.raises(PermissionError):
        factory("Custom Python", {}, "def on_bar(ctx): return 1")


def test_run_emits_governance_events(app, governance_spool):
    at = click(app.run(), "Run backtest")
    events = [json.loads(l) for l in governance_spool.read_text().splitlines()]
    assert {"register", "visit", "backtest_run"} <= {e["event_type"] for e in events}
    run = next(e for e in events if e["event_type"] == "backtest_run")
    assert run["records_in"] > 100_000 and run["cost_usd"] > 0
