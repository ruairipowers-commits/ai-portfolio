"""Streamlit app tests (headless via streamlit.testing) against the real MCP server, in a throwaway copy."""
import os
import shutil
import sys
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "tradeops" / "ui.py"
pytestmark = pytest.mark.skipif(not (ROOT / "mcp-server" / "dist" / "index.js").exists(),
                                reason="MCP server not built (tradeops build-server)")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    for d in ("config", "prompts", "evals", "schema"):
        shutil.copytree(ROOT / d, tmp_path / d)
    (tmp_path / "mcp-server").mkdir()
    for d in ("dist", "node_modules"):
        os.symlink(ROOT / "mcp-server" / d, tmp_path / "mcp-server" / d)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRADEOPS_ROOT", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for m in [m for m in sys.modules if m.startswith("tradeops")]:
        del sys.modules[m]
    return st_testing.AppTest.from_file(str(APP), default_timeout=300)


def click(at, label):
    return next(b for b in at.button if label in b.label).click().run()


def metrics(at):
    return {m.label: m.value for m in at.metric}


def test_investigate_all(app):
    at = app.run()
    assert not at.exception
    at = click(at, "Investigate 40")
    assert not at.exception, at.exception
    m = metrics(at)
    assert m["Awaiting approval"] == "36" and m["Escalated"] == "4" and m["Resolved"] == "0"


def test_injection_on_clean_exception_escalates(app):
    at = app.run()
    at.radio[0].set_value("Selected exceptions").run()
    at.multiselect[0].set_value(["EX-0003"]).run()
    at.selectbox[0].set_value("EX-0003").run()
    at = click(at, "Insert injection")
    at = click(at, "Save confirm text")
    at = click(at, "Investigate 1")
    m = metrics(at)
    assert m["Escalated"] == "1" and m["Awaiting approval"] == "0"


def test_approve_records_and_queues_email(app):
    at = app.run()
    at.radio[0].set_value("Selected exceptions").run()
    at.multiselect[0].set_value(["EX-0002"]).run()          # broker-side quantity break -> email
    at = click(at, "Investigate 1")
    at = click(at, "Approve")
    assert not at.exception, at.exception
    assert any("resolved" in s.value for s in at.success)
    assert metrics(at)["Resolved"] == "1"
    outbox = at.tabs[2].dataframe[1].value
    assert len(outbox) == 1 and not bool(outbox.iloc[0]["sent"])
