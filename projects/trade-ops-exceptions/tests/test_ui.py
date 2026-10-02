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
    """Row of the bulk-queue table (the one with status + tampered columns)."""
    for d in at.dataframe:
        table = d.value.data if hasattr(d.value, "data") else d.value   # Styler -> DataFrame
        if {"exception_id", "status", "tampered"} <= set(table.columns):
            return table.set_index("exception_id").loc[exception_id]
    raise AssertionError("bulk queue table not found")


# ---------------------------------------------------------------- workflow tab
def test_tabs_and_investigate_all(app):
    at = app.run()
    assert not at.exception, at.exception
    labels = [t.label for t in at.tabs]
    assert {"🧑‍🤝‍🧑 Single trade walkthrough", "📋 Bulk exception queue", "🗄️ Data explorer", "📏 Audit & evals",
            "📘 Guide & models"} <= set(labels)
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


def test_no_magic_expressions_in_apps():
    """Streamlit 'magic' renders any bare non-call expression (e.g. `a() if x else b()`) as a widget dump."""
    import ast
    apps = [APP, ROOT.parent / "altdata-triage" / "src" / "altdata_triage" / "ui.py"]
    for path in [a for a in apps if a.exists()]:
        bad = [n.lineno for n in ast.walk(ast.parse(path.read_text()))
               if isinstance(n, ast.Expr) and not isinstance(n.value, (ast.Call, ast.Constant, ast.Await))]
        assert not bad, f"{path.name}: bare expressions on lines {bad}"


def test_records_tab_has_no_object_dump(app):
    at = select(app.run(), "EX-0009")                     # missing confirm -> several empty tables ("No rows.")
    assert not any("DeltaGenerator" in str(getattr(e, "value", "")) for e in at.main)
    assert any(c.value == "No rows." for c in at.caption)


# ---------------------------------------------------------------- single-trade walkthrough
def walk(app, scenario, upto="inv"):
    at = app.run()
    at.selectbox(key="wt_scenario").set_value(scenario).run()
    at = press(at, "wt_load")
    for k in ["wt_book", "wt_send", "wt_cust", "wt_match", "wt_inv"]:
        if k == "wt_inv" and not at.session_state["wt"].get("exception_id"):
            break
        at = press(at, k)
        assert not at.exception, (k, at.exception)
        if k == upto:
            break
    return at


def test_walkthrough_broker_qty_to_resolved(app):
    at = walk(app, "Broker confirms the wrong quantity")
    ex = at.session_state["wt"]["exception_id"]
    assert ex.startswith("EX-9")
    wt = at.session_state["wt"]
    assert wt["custodian"]["quantity"] == 5000 and wt["confirm"]["quantity"] == 5250   # prefills survived the steps
    assert str(wt["custodian"]["settle_date"]) == str(wt["trade"]["settle_date"])
    assert any("Break found" in e.value for e in at.error)
    assert any("REQUEST_BROKER_CORRECTION" in m.value for m in at.markdown)
    at = press(at, "wt_approve")
    assert any("Resolved." in s.value for s in at.success)
    assert wf_status(at, ex)["status"] == "Resolved"            # same exception, green in the bulk queue


def test_walkthrough_our_qty_uses_scenario_custodian(app):
    at = walk(app, "We booked the wrong quantity")
    wt = at.session_state["wt"]
    assert wt["trade"]["quantity"] == 5250 and wt["custodian"]["quantity"] == 5000
    assert any("AMEND_INTERNAL" in m.value for m in at.markdown)


def test_walkthrough_clean_trade_opens_no_exception(app):
    at = walk(app, "Clean trade — everything matches")
    assert "exception_id" not in at.session_state["wt"]
    assert any("Matched." in s.value for s in at.success)


def test_walkthrough_injection_escalates_and_cannot_be_approved(app):
    at = walk(app, "💉 Broker confirm contains a prompt injection")
    assert any("instruction-like" in e.value for e in at.error)
    assert not [b for b in at.button if b.key == "wt_approve"]
    ex = at.session_state["wt"]["exception_id"]
    assert "injection" in wf_status(at, ex)["tampered"]          # marked in the bulk queue too


def test_walkthrough_missing_confirm_chases(app):
    at = walk(app, "Broker never sends a confirm")
    assert any("CHASE_CONFIRM" in m.value for m in at.markdown)


def test_hosted_demo_gives_each_visitor_a_private_sandbox(app, tmp_path, monkeypatch):
    """PORTFOLIO_DEMO=1: investigate + approve write only to this session's copy, never the baseline."""
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("PORTFOLIO_DEMO", "1")
    monkeypatch.setenv("DEMO_SESSIONS_DIR", str(sessions))
    monkeypatch.setenv("PORTFOLIO_BLOG_URL", "https://example.test/blog/trade-ops-exceptions/")
    monkeypatch.setenv("PORTFOLIO_SOURCE_URL", "https://github.com/example/trade-ops-exceptions")
    at = select(app.run(), "EX-0002")
    at = press(at, "inv_one")
    at = press(at, "approve")
    assert not at.exception, at.exception
    assert wf_status(at, "EX-0002")["status"] == "Resolved"
    boxes = [d for d in (sessions / "trade-ops-exceptions").iterdir() if d.is_dir()]
    assert len(boxes) == 1
    assert (boxes[0] / "warehouse" / "tradeops.sqlite").exists()
    assert (boxes[0] / "warehouse" / "checkpoints.sqlite").exists()
    assert not (tmp_path / "warehouse" / "tradeops.sqlite").exists()     # baseline untouched
    links = " ".join(m.value for m in at.markdown)
    assert "example.test/blog/trade-ops-exceptions" in links and "github.com/example/trade-ops-exceptions" in links
    assert any("Public demo" in i.value for i in at.sidebar.info)


def test_investigate_and_approve_emit_governance_events(app, governance_spool):
    import json
    at = select(app.run(), "EX-0037")                                 # injection case -> escalated
    at = press(at, "inv_one")
    at = select(at, "EX-0002")
    at = press(at, "inv_one")
    at = press(at, "approve")
    assert not at.exception, at.exception
    ev = [json.loads(l) for l in governance_spool.read_text().splitlines()]
    inv = {e["detail"]["exception_id"]: e for e in ev if e["event_type"] == "investigate"}
    assert inv["EX-0037"]["status"] == "escalated" and "injection_detected" in inv["EX-0037"]["flags"]
    assert inv["EX-0002"]["status"] == "ok" and inv["EX-0002"]["cost_usd"] > 0 and inv["EX-0002"]["model"] == "mock-agent"
    appr = next(e for e in ev if e["event_type"] == "approve")
    assert appr["actor"] == "demo-analyst" and appr["actor_type"] == "named" and appr["records_out"] == 1
