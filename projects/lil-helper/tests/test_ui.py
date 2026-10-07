"""Streamlit demo tests (headless): default run, break-it inputs, and the human step (approve)."""
import shutil
import sys
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "lilhelper" / "ui.py"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    for d in ("config", "data", "prompts", "evals", "brand", "scripts", "docs"):
        if (ROOT / d).exists():
            shutil.copytree(ROOT / d, tmp_path / d)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LILHELPER_ROOT", str(tmp_path))
    for m in [m for m in sys.modules if m.startswith("lilhelper")]:
        del sys.modules[m]
    return st_testing.AppTest.from_file(str(APP), default_timeout=180)


def click(at, label):
    return next(b for b in at.button if label in b.label).click().run()


def metric(at, label):
    return next(m.value for m in at.metric if m.label.startswith(label))


def test_default_run_then_approve(app):
    at = app.run()
    assert not at.exception
    at = click(at, "Plan the week")
    assert not at.exception, at.exception
    assert int(metric(at, "Meals planned")) >= 10
    assert metric(at, "Status") == "draft"
    at = click(at, "Approve as Dana")
    assert not at.exception, at.exception
    assert metric(at, "Status") == "approved"
    assert any("Approved by Dana" in s.value for s in at.success)


def test_flyer_with_an_instruction_is_flagged(app):
    at = click(app.run(), "Read this flyer")
    assert not at.exception
    assert any("looks like an instruction" in w.value for w in at.warning)


def test_dog_toxic_check(app):
    at = app.run()
    at.text_input(key="dog_try").set_value("grapes").run()
    assert any("toxic" in e.value for e in at.error)
    at.text_input(key="dog_try").set_value("carrots").run()
    assert any("OK as a plain extra" in s.value for s in at.success)


def test_small_budget_warns(app):
    at = app.run()
    at.number_input(key="budget").set_value(100).run()
    at = click(at, "Plan the week")
    assert any("Over budget" in w.value for w in at.warning)
