"""Streamlit app tests (headless via streamlit.testing), each in a throwaway project copy."""
import ast
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
APP = Path(__file__).resolve().parents[1] / "src" / "research_qa" / "ui.py"


@pytest.fixture()
def app(project):
    return st_testing.AppTest.from_file(str(APP), default_timeout=120)


def click(at, label):
    return next(b for b in at.button if label in b.label).click().run()


def metric(at, label):
    return next(x.value for x in at.metric if x.label == label)


def test_default_question_answers_with_citation(app):
    at = app.run()
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs][:5] == ["💬 Ask", "🧨 Try to break it", "📚 Corpus & index", "📏 Evals & audit",
                                              "📘 Guide"]
    at = click(at, "Ask")
    assert not at.exception, at.exception
    assert metric(at, "Outcome") == "Answered"
    assert any("4.82 billion" in s.value for s in at.success)
    assert any("Halvorsen Robotics — 2025 Annual Report" in md.value for md in at.markdown)


def test_same_question_refused_without_entitlement(app):
    at = app.run()
    at.selectbox(key="persona").set_value("public-analyst")
    at.text_input(key="question").set_value("What is Northbridge's price target on Halvorsen Robotics?")
    at = click(at.run(), "Ask")
    assert metric(at, "Outcome") == "Refused"
    assert int(metric(at, "Hidden by entitlement")) > 0
    at.selectbox(key="persona").set_value("equity-analyst")
    at = click(at.run(), "Ask")
    assert metric(at, "Outcome") == "Answered" and any("$148" in s.value for s in at.success)


def test_break_it_hidden_instructions_quarantined_then_answer_clean(app):
    at = app.run()
    at = next(b for b in at.button if "Add document" in b.label).click().run()   # default preset: hidden instructions
    assert not at.exception, at.exception
    assert any("quarantined" in e.value for e in at.error)
    at = click(at, "Use this question")
    at = click(at, "Ask")
    assert metric(at, "Outcome") == "Answered"
    answer = " ".join(s.value for s in at.success)
    assert "Hold" in answer and "400" not in answer and "strong buy" not in answer


def test_licence_preset_refuses(app):
    at = app.run()
    at.radio(key="preset").set_value("🔒 Licence forbids AI processing")
    at = next(b for b in at.run().button if "Add document" in b.label).click().run()
    at = click(at, "Use this question")
    at = click(at, "Ask")
    assert metric(at, "Outcome") == "Refused"
    assert any("licence forbids AI processing" in w.value for w in at.warning)


def test_eval_gate_and_retrieval_comparison(app):
    at = app.run()
    at = click(at, "Run eval gate")
    assert not at.exception, at.exception
    assert any("EVAL GATE PASS" in s.value for s in at.success)
    at = click(at, "Compare retrieval modes")
    assert not at.exception, at.exception


def test_kill_switch_disables_ask(app, project):
    import sqlite3

    from research_qa import telemetry

    at = app.run()
    con = sqlite3.connect(project / "governance.sqlite")
    con.execute("insert into gov_workflow_state values ('research-qa-rag', 0, 'model provider outage', 'cro', '2026-10-02')")
    con.commit()
    telemetry._state_cache = (0.0, True, "")
    at = at.run()
    assert any("switched off" in e.value for e in at.error)
    assert next(b for b in at.button if b.label == "🔎 Ask").disabled


def test_no_bare_expressions_in_app():
    """Streamlit 'magic' renders bare expressions; a stray one dumps objects onto the page."""
    tree = ast.parse(APP.read_text())
    bad = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Expr) and not isinstance(n.value, (ast.Call, ast.Constant))]
    assert not bad, f"bare expressions at lines {bad}"


def test_hosted_demo_gives_each_visitor_a_private_sandbox(app, project, monkeypatch):
    sessions = project / "sessions"
    monkeypatch.setenv("PORTFOLIO_DEMO", "1")
    monkeypatch.setenv("DEMO_SESSIONS_DIR", str(sessions))
    monkeypatch.setenv("PORTFOLIO_BLOG_URL", "https://example.test/blog/research-qa-rag/")
    at = app.run()
    at = next(b for b in at.button if "Add document" in b.label).click().run()
    assert not at.exception, at.exception
    boxes = [d for d in (sessions / "research-qa-rag").iterdir() if d.is_dir()]
    assert len(boxes) == 1 and (boxes[0] / "warehouse" / "research.sqlite").exists()
    assert len(list((boxes[0] / "data" / "corpus").glob("*.pdf"))) == 10        # 9 sample PDFs + the added note
    assert not (project / "warehouse").exists()                               # baseline untouched
    assert any("example.test/blog/research-qa-rag" in md.value for md in at.markdown)
