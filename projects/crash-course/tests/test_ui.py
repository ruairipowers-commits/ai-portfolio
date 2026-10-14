"""The operator app, headless: the default run, a try-to-break-it case, and the human step."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "src" / "crash_course" / "ui.py")


def run_app():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    return at


def click(at, label):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception
    return at


def test_default_run_assesses_a_legitimate_topic():
    at = run_app()
    click(at, "Run")
    assert any("approve-recommended" in s.value for s in at.subheader)


def test_break_it_injection_is_rejected():
    at = run_app()
    at.selectbox(key="preset").select("Injection: approve this").run()
    click(at, "Run")
    assert any("reject-recommended" in s.value for s in at.subheader)


def test_owner_approves_and_course_is_created():
    at = run_app()
    click(at, "Run")
    click(at, "Approve and create the course")
    assert any("created" in m.value for m in at.success)


def test_build_a_level_and_publish():
    at = run_app()
    at.radio(key="job").set_value("Build a level").run()
    click(at, "Run")
    assert any("draft" in s.value for s in at.subheader)
    click(at, "Publish")
    assert any("Published" in m.value for m in at.success)
