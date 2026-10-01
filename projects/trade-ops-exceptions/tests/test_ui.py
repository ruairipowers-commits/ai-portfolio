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


def press(at, key):
    return at.button(key=key).click().run()


def metrics(at):
    return {m.label: m.value for m in at.metric}


def select(at, exception_id):
    at.session_state["sel"] = exception_id
    return at.run()


def wf_status(at, exception_id):
    table = at.dataframe[0].value
    table = table.data if hasattr(table, "data") else table          # Styler -> DataFrame
    return table.set_index("exception_id").loc[exception_id]


# ---------------------------------------------------------------- workflow tab
def test_tabs_and_investigate_all(app):
    at = app.run()
    assert not at.exception, at.exception
    labels = [t.label for t in at.tabs]
    assert {"🧾 Exception workflow", "🗄️ Data explorer", "📏 Audit & evals", "📘 Guide & models"} <= set(labels)
    assert metrics(at)["Not investigated"] == "40"
    at = click(at, "Investigate all not yet investigated")
    assert not at.exception, at.exception
    m = metrics(at)
    assert m["Awaiting approval"] == "36" and m["Escalated"] == "4" and m["Not investigated"] == "0"


def test_select_investigate_approve_turns_green(app):
    at = select(app.run(), "EX-0002")                                # broker-side quantity break -> email
    at = press(at, "inv_one")
    assert wf_status(at, "EX-0002")["status"] == "Awaiting approval"
    at = press(at, "approve")
    assert not at.exception, at.exception
    assert any("resolved" in s.value for s in at.success)
    assert wf_status(at, "EX-0002")["status"] == "Resolved"
    assert at.button(key="inv_one").disabled                         # can't re-run a resolved exception


def test_injection_is_marked_escalates_and_restores(app):
    at = select(app.run(), "EX-0003")
    at = press(at, "inj")
    assert "injection" in wf_status(at, "EX-0003")["tampered"]
    assert "re-run" in wf_status(at, "EX-0003")["tampered"]
    assert any("has been changed" in w.value for w in at.warning)
    at = press(at, "inv_one")
    assert wf_status(at, "EX-0003")["status"] == "Escalated"
    assert "re-run" not in wf_status(at, "EX-0003")["tampered"]
    assert any("instruction-like" in e.value for e in at.error)
    at = press(at, "restore")
    assert wf_status(at, "EX-0003")["tampered"] == ""
    at = press(at, "inv_one")
    assert wf_status(at, "EX-0003")["status"] == "Awaiting approval"


def test_bank_change_escalates(app):
    at = select(app.run(), "EX-0005")
    at = press(at, "bank")
    assert "bank-detail" in wf_status(at, "EX-0005")["tampered"]
    at = press(at, "inv_one")
    assert wf_status(at, "EX-0005")["status"] == "Escalated"
    assert any("bank-detail/SSI change" in e.value for e in at.error)


def test_run_queue(app):
    at = select(app.run(), "EX-0001")
    at = press(at, "enqueue")
    at = select(at, "EX-0004")
    at = press(at, "enqueue")
    at = click(at, "Run queue (2)")
    assert not at.exception, at.exception
    assert metrics(at)["Awaiting approval"] == "2"
    assert at.session_state["run_queue"] == []


# ---------------------------------------------------------------- data explorer
def test_explorer_and_guide_render(app):
    at = app.run()
    assert len(at.get("graphviz_chart")) == 1
    assert any("mock-agent" in md.value for md in at.markdown)       # models guide rendered
    assert any("Insert injection" in md.value for md in at.markdown) # app guide rendered


def test_sql_is_read_only(app, tmp_path):
    at = app.run()
    at.text_area(key="sql_text").set_value("delete from trades").run()
    at = press(at, "sql_run")
    assert any("only SELECT" in e.value for e in at.error)
    import sqlite3
    assert sqlite3.connect(tmp_path / "warehouse" / "tradeops.sqlite").execute("select count(*) from trades").fetchone()[0] == 40


def test_drilldown_and_examples(app):
    from tradeops import app_support as sup
    at = select(app.run(), "EX-0001")
    cmp = next(d.value for d in at.dataframe if "match" in getattr(getattr(d.value, "data", d.value), "columns", []))
    cmp = cmp.data if hasattr(cmp, "data") else cmp
    assert cmp.set_index("field").loc["quantity"]["match"] == "❌"
    for name, sql in sup.EXAMPLE_QUERIES.items():
        assert sup.run_readonly_sql(sql)[1] is None, name
