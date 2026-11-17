"""Streamlit app tests (headless, via streamlit.testing). Each test runs in a throwaway project copy."""
import json
import shutil
import sys
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "lob_matching_engine" / "ui.py"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    for d in ("config", "prompts", "evals", "scripts", "docs"):
        shutil.copytree(ROOT / d, tmp_path / d)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOB_ROOT", str(tmp_path))
    for m in [m for m in sys.modules if m.startswith("lob_matching_engine") and m != "lob_matching_engine._engine"]:
        del sys.modules[m]
    return st_testing.AppTest.from_file(str(APP), default_timeout=300)


def click(at, label):
    return next(b for b in at.button if label in b.label).click().run()


def alerts(at):
    return next(d.value for d in at.dataframe if "final suggestion" in d.value.columns).set_index("pattern")


def test_default_run(app):
    at = app.run()
    assert not at.exception
    at = click(at, "Run surveillance")
    assert not at.exception, at.exception
    a = alerts(at)
    assert set(a.index) == {"layering", "wash", "stuffing", "ignition"}
    assert a.loc["layering", "final suggestion"].endswith("ESCALATE")


def test_injection_is_flagged_and_kept_at_escalate(app):
    at = app.run()
    at = click(at, "Injection")
    at = click(at, "Run surveillance")
    a = alerts(at)
    assert bool(a.loc["layering", "injection flag"]) and a.loc["layering", "final suggestion"].endswith("ESCALATE")


def test_please_close_is_overruled_on_high_severity(app):
    at = app.run()
    at = click(at, '"Please close"')
    at = click(at, "Run surveillance")
    a = alerts(at)
    assert a.loc["layering", "model suggested"] == "CLOSE"            # the mock is gullible on purpose...
    assert a.loc["layering", "final suggestion"].endswith("ESCALATE")  # ...policy is not


def test_corrupt_session_stopped_by_gate(app):
    at = app.run()
    at = click(at, "Corrupt: time goes backwards")
    at = click(at, "Run surveillance")
    assert any("Data gate failed" in e.value for e in at.error)
    assert not any("final suggestion" in d.value.columns for d in at.dataframe)


def test_clean_session_no_alerts(app):
    at = app.run()
    at.radio(key="src").set_value("Clean session (no behaviours)").run()
    at = click(at, "Run surveillance")
    assert any("No alerts" in x.value for x in at.success)


def test_human_step_requires_reason_for_high_severity(app):
    at = click(app.run(), "Run surveillance")
    at.radio(key="dec_A001").set_value("CLOSE").run()
    at = click(at, "Record decision")
    assert any("written reason" in e.value for e in at.error)
    at.text_input(key="why_A001").set_value("client unwind confirmed on the recorded line").run()
    at = click(at, "Record decision")
    assert any("Recorded demo-analyst" in x.value for x in at.success)


def test_lab_pages_render(app):
    at = app.run()
    for page in ("lab/desk.py", "lab/simulator.py", "lab/benchmark.py", "lab/scenarios.py"):
        at.switch_page(page)
        at.run()
        assert not at.exception, (page, at.exception)


def test_hosted_demo_gives_each_visitor_a_private_sandbox(app, tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setenv("PORTFOLIO_DEMO", "1")
    monkeypatch.setenv("DEMO_SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setenv("PORTFOLIO_BLOG_URL", "https://example.test/blog/lob-matching-engine/")
    at = click(app.run(), "Run surveillance")
    assert not at.exception, at.exception
    boxes = [d for d in (sessions_dir / "lob-matching-engine").iterdir() if d.is_dir()]
    assert len(boxes) == 1 and (boxes[0] / "output" / "lob.sqlite").exists()
    assert not (tmp_path / "output" / "lob.sqlite").exists()            # baseline untouched
    assert any("Public demo" in i.value for i in at.sidebar.info)


def test_run_emits_governance_events(app, governance_spool):
    at = click(app.run(), "Run surveillance")
    assert not at.exception, at.exception
    events = [json.loads(l) for l in governance_spool.read_text().splitlines()]
    assert {"register", "visit", "surveillance_run"} <= {e["event_type"] for e in events}
    run = next(e for e in events if e["event_type"] == "surveillance_run")
    assert run["records_out"] == 4 and run["records_in"] > 10_000 and run["cost_usd"] > 0
