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


# ---------------------------------------------------------------- data explorer
def test_explorer_available_before_any_run(app):
    at = app.run()
    assert not at.exception, at.exception
    assert any(h.value == "4 · Explore the data" for h in at.header)
    assert len(at.get("graphviz_chart")) == 1                      # ER diagram rendered
    assert any("Press **Investigate**" in i.value for i in at.info)


def test_drilldown_flags_the_mismatched_field(app):
    at = app.run()
    at.selectbox(key="dd_pick").set_value("EX-0001").run()          # internal quantity break
    cmp = next(d.value for d in at.dataframe if "match" in getattr(d.value, "columns", []))
    cmp = cmp.data if hasattr(cmp, "data") else cmp                 # Styler -> DataFrame
    q = cmp.set_index("field").loc["quantity"]
    assert q["match"] == "❌" and q["OMS (our booking)"] != q["Broker confirm"]


def test_sql_is_read_only(app, tmp_path):
    at = app.run()
    at.text_area(key="sql_text").set_value("delete from trades").run()
    at = click(at, "Run query")
    assert any("only SELECT" in e.value for e in at.error)
    at.text_area(key="sql_text").set_value("select count(*) as n from trades").run()
    at = click(at, "Run query")
    assert not at.error
    import sqlite3
    assert sqlite3.connect(tmp_path / "warehouse" / "tradeops.sqlite").execute("select count(*) from trades").fetchone()[0] == 40


def test_example_query_and_table_browser(app):
    from tradeops import app_support as sup
    at = app.run()
    for name, sql in sup.EXAMPLE_QUERIES.items():
        rows, err = sup.run_readonly_sql(sql)
        assert err is None, (name, err)
    at.selectbox(key="tb_name").set_value("broker_confirms").run()
    at.text_input(key="tb_search").set_value("bank details").run()
    assert not at.exception
    assert len(sup.table_rows("broker_confirms", "bank details")) == 1
