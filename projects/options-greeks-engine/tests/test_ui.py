"""Streamlit app tests (headless). Each test runs in a throwaway project copy."""
import json
import shutil
import sys
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "options_greeks_engine" / "ui.py"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    for d in ("config", "prompts", "evals", "scripts", "docs"):
        shutil.copytree(ROOT / d, tmp_path / d)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPT_ROOT", str(tmp_path))
    for m in [m for m in sys.modules if m.startswith("options_greeks_engine") and m != "options_greeks_engine._optlib"]:
        del sys.modules[m]
    return st_testing.AppTest.from_file(str(APP), default_timeout=300)


def click(at, label):
    return next(b for b in at.button if label in b.label).click().run()


def heading(at):
    return " ".join(h.value for h in at.subheader)


def test_default_request_pending_then_approved(app):
    at = click(app.run(), "Build ticket")
    assert not at.exception, at.exception
    assert "PENDING APPROVAL" in heading(at)
    at.text_input(key="why").set_value("defined risk, within all limits").run()
    at = click(at, "Record decision")
    assert any("approved ticket" in x.value for x in at.success)


def test_injection_blocks_approval(app):
    at = click(app.run(), "Injection")
    at = click(at, "Build ticket")
    assert "BLOCKED" in heading(at)
    assert any("resubmit" in e.value for e in at.error)


def test_naked_short_call_long_only_blocked(app):
    at = click(app.run(), "Naked short call")
    at = click(at, "Build ticket")
    assert "BLOCKED" in heading(at) and any("permission" in e.value for e in at.error)
    at.text_input(key="why").set_value("override please, client asked").run()
    at = click(at, "Record decision")
    assert any("can't be approved" in e.value for e in at.error)


def test_no_expiry_asks_instead_of_guessing(app):
    at = click(app.run(), "No expiry")
    at = click(at, "Build ticket")
    assert "CLARIFICATION" in heading(at) and any("expiry" in w.value for w in at.warning)


def test_lab_pages_render(app):
    at = app.run()
    for page in ("lab/pricer.py", "lab/surfaces.py", "lab/strategies.py"):
        at.switch_page(page)
        at.run()
        assert not at.exception, (page, at.exception)


def test_heavy_lab_pages_render(app):
    at = app.run()
    for page in ("lab/convergence.py", "lab/exotics.py"):
        at.switch_page(page)
        at.run()
        assert not at.exception, (page, at.exception)


def test_hosted_demo_sandbox(app, tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DEMO", "1")
    monkeypatch.setenv("DEMO_SESSIONS_DIR", str(tmp_path / "sessions"))
    at = click(app.run(), "Build ticket")
    assert not at.exception, at.exception
    boxes = [d for d in (tmp_path / "sessions" / "options-greeks-engine").iterdir() if d.is_dir()]
    assert len(boxes) == 1 and (boxes[0] / "output" / "options.sqlite").exists()
    assert not (tmp_path / "output" / "options.sqlite").exists()


def test_run_emits_governance_events(app, governance_spool):
    click(app.run(), "Build ticket")
    events = [json.loads(l) for l in governance_spool.read_text().splitlines()]
    assert {"register", "visit", "ticket"} <= {e["event_type"] for e in events}
