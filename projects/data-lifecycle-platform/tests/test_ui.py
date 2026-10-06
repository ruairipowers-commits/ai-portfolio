"""The Streamlit app, headless: default run, a break-it case, and the human step."""
import pytest
from streamlit.testing.v1 import AppTest

from pathlib import Path

APP = str(Path(__file__).resolve().parents[1] / "src" / "dlp" / "ui.py")


@pytest.fixture()
def app(fresh):
    return AppTest.from_file(APP, default_timeout=180).run()


def _run(at):
    next(b for b in at.button if b.label.startswith("Run ·")).click().run()
    return at


def test_default_ask_as_a_firm(app):
    app.sidebar.selectbox[0].set_value("Harbor Point Capital — Avery Lin (vol desk)").run()
    app.radio(key="wf").set_value("Ask about our data").run()
    _run(app)
    assert not app.exception
    assert any("Answered" in m.value for m in app.subheader)
    assert any("SELECT" in c.value.upper() for c in app.code)               # the four-layer trace shows the SQL


def test_break_it_undefined_metric_and_not_entitled(app):
    app.sidebar.selectbox[0].set_value("Alder Asset Management — Jules Moreau (risk)").run()
    app.radio(key="wf").set_value("Ask about our data").run()
    app.text_area(key="question").set_value("What is the implied vol for JPM?").run()
    _run(app)
    assert any("Not Entitled" in m.value for m in app.subheader)
    app.text_area(key="question").set_value("What is the dark pool volume ratio for AAPL?").run()
    _run(app)
    assert any("Not Defined" in m.value for m in app.subheader)


def test_catalog_injection_then_human_approval(app):
    app.radio(key="wf").set_value("Catalog a source").run()
    app.selectbox[0].set_value("Larkspur vendor page — hidden injection").run()
    _run(app)
    assert any("injection_suspected" in w.value for w in app.warning)
    ok = next(b for b in app.button if b.label == "Approve")
    ok.click().run()
    assert not app.exception
    assert not any(b.label == "Approve" for b in app.button)              # queue emptied by a named reviewer
