"""Streamlit app tests (headless via streamlit.testing), each with its own project copy and database."""
import ast
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
APP = Path(__file__).resolve().parents[1] / "src" / "eod_heartbeat" / "ui.py"


@pytest.fixture()
def app(project):
    return st_testing.AppTest.from_file(str(APP), default_timeout=240)


def click(at, label):
    return next(b for b in at.button if label in b.label).click().run()


def metric(at, label):
    return next(x.value for x in at.metric if x.label == label)


def test_default_run_explains_breaks_with_citations(app):
    at = app.run()
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs][:6] == ["🫀 EOD check", "🧨 Try to break it", "📚 Runbooks & incidents",
                                              "🗄️ Pipeline data", "📏 Evals & audit", "📘 Guide"]
    at = click(at, "Run EOD checks")
    assert not at.exception, at.exception
    assert metric(at, "Breaks") == "2" and metric(at, "Explained") == "2"
    text = " ".join(m.value for m in at.markdown)
    assert "RB-11#steps" in text and "Next step." in text


def test_critical_date_and_outage(app):
    at = app.run()
    at.selectbox(key="bdate").set_value("2026-09-18")
    at.selectbox(key="outage").set_value("All models down")
    at = click(at.run(), "Run EOD checks")
    assert metric(at, "Critical") == "2"
    assert any("blocked" in e.value for e in at.error)
    assert "Degraded" in " ".join(m.value for m in at.markdown)


def test_break_it_unsafe_step_is_blocked(app):
    at = app.run()
    at = click(at, "Make step 1 unsafe")
    at = click(at, "Save and re-index")
    assert not at.exception, at.exception
    at = click(at, "Run EOD checks")
    text = " ".join(m.value for m in at.markdown)
    assert "Blocked by policy" in text and "unsafe_action" in " ".join(c.value for c in at.caption)


def test_break_it_instruction_is_quarantined(app):
    at = app.run()
    at = click(at, "Add an instruction for the AI")
    at = click(at, "Save and re-index")
    assert any("Quarantined" in e.value for e in at.error)


def test_eval_gate(app):
    at = click(app.run(), "Run eval gate")
    assert not at.exception, at.exception
    assert any("EVAL GATE PASS" in s.value for s in at.success)


def test_no_bare_expressions_in_app():
    tree = ast.parse(APP.read_text())
    bad = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Expr) and not isinstance(n.value, (ast.Call, ast.Constant))]
    assert not bad, f"bare expressions at lines {bad}"


def test_hosted_demo_gives_each_visitor_a_private_database(app, project, m, monkeypatch):
    s = m.store.Settings.load()
    m.cli.reset_all(s)                                    # the baseline the image builds
    monkeypatch.setenv("PORTFOLIO_DEMO", "1")
    monkeypatch.setenv("DEMO_SESSIONS_DIR", str(project / "sessions"))
    at = click(app.run(), "Run EOD checks")
    assert not at.exception, at.exception
    assert metric(at, "Breaks") == "2"
    boxes = [d for d in (project / "sessions" / "eod-heartbeat").iterdir() if d.is_dir()]
    assert len(boxes) == 1 and (boxes[0] / "data" / "landing").exists()
    import psycopg

    with psycopg.connect(m.store.dsn(s, "postgres")) as admin:
        dbs = [r[0] for r in admin.execute("select datname from pg_database where datname like %s",
                                           (s["database_name"] + "_s_%",))]
    assert len(dbs) == 1
    with m.store.connect(s) as con:                       # baseline database: nobody's runs land here
        assert con.execute("select count(*) as n from audit.runs").fetchone()["n"] == 0
