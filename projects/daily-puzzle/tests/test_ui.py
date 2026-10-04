"""Operator app (headless, streamlit.testing): default run, a break-it case that escalates, the human review, a pack."""
import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
from pathlib import Path  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "src" / "daily_puzzle" / "ui.py"


@pytest.fixture()
def app(project):
    """Fresh imports bound to the throwaway project; the original modules are put back afterwards so later
    tests' monkeypatches still reach the code they patch."""
    import sys
    saved = {m: mod for m, mod in sys.modules.items() if m.startswith("daily_puzzle")}
    for m in saved:
        del sys.modules[m]
    yield st_testing.AppTest.from_file(str(APP), default_timeout=300)
    for m in [m for m in sys.modules if m.startswith("daily_puzzle")]:
        del sys.modules[m]
    sys.modules.update(saved)


def click(at, label):
    return next(b for b in at.button if label in b.label).click().run()


def test_default_week(app):
    at = app.run()
    assert not at.exception
    at = click(at, "Run a simulated week")
    assert not at.exception, at.exception
    m = {x.label: x.value for x in at.metric}
    assert m["Daily puzzles"] == "8" and m["Escalated to you"] == "0"
    assert any("calm_zebra" in str(d.value) or "rank" in d.value.columns for d in at.dataframe)


def test_break_it_escalates_and_human_reviews(app):
    at = app.run()
    at.selectbox(key="break").set_value("Ambiguous logic puzzle (two valid answers)").run()
    at.checkbox(key="every").check().run()
    at = click(at, "Run a simulated week")
    assert not at.exception, at.exception
    m = {x.label: x.value for x in at.metric}
    assert m["Escalated to you"] == "1" and m["From reserve"] == "1"
    esc_id = next(t.key for t in at.text_input if t.key and t.key.startswith("who_")).split("_")[1]
    at.text_input(key=f"who_{esc_id}").set_value("Ruairi").run()
    at = next(b for b in at.button if b.key == f"reject_{esc_id}").click().run()
    assert not at.exception
    assert {x.label: x.value for x in at.metric}["Escalated to you"] == "0"


def test_pack_from_ui(app):
    at = app.run()
    at = click(at, "Run a simulated week")
    at = click(at, "Make pack")
    assert not at.exception, at.exception
    assert any("verified puzzles" in x.value for x in at.success)
