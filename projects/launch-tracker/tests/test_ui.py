"""Streamlit app tests (headless, via streamlit.testing): default run, the break-it case, the human step."""
import shutil
import sys
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "launchtracker" / "ui.py"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    for d in ("config", "prompts", "evals", "data", "scripts", "docs"):
        if (ROOT / d).exists():
            shutil.copytree(ROOT / d, tmp_path / d, ignore=shutil.ignore_patterns("cache"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LAUNCHES_ROOT", str(tmp_path))
    monkeypatch.delenv("DUCKDB_PATH", raising=False)
    for m in [m for m in sys.modules if m.startswith("launchtracker")]:
        del sys.modules[m]
    return st_testing.AppTest.from_file(str(APP), default_timeout=180)


def click(at, label):
    return next(b for b in at.button if label in b.label).click().run()


def metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


def test_default_run(app):
    at = app.run()
    assert not at.exception, at.exception
    assert metric(at, "Upcoming") == "12"
    assert "fictional" in at.info[0].value
    at = click(at, "Summarise this launch")
    assert not at.exception, at.exception
    assert any("scheduled to launch" in m.value for m in at.markdown) or any("scheduled to launch" in w.value for w in at.get("text"))


def test_break_it_instruction_is_caught(app):
    at = app.run()
    # pick the upcoming launch whose description already carries an instruction, then pass it through to the model
    sb = at.selectbox(key="pick")
    target = next(o for o in sb.options if "Upcoming-4" in o)
    at = sb.select(target).run()
    at.checkbox(key="nodrop").check().run()
    at = click(at, "Summarise this launch")
    assert not at.exception, at.exception
    errors = " ".join(e.value for e in at.error)
    assert "Rejected the draft" in errors and "still scheduled" in errors


def test_cost_question_and_human_approval(app):
    at = app.run()
    at = click(at, "what did this launch cost")
    assert not at.exception
    at.text_input(key="who-sls-orion-oig-2021").input("Ruairi").run()
    at = next(b for b in at.button if b.key == "ok-sls-orion-oig-2021").click().run()
    assert not at.exception, at.exception
    assert any("Status: **approved**" in m.value for m in at.markdown)
