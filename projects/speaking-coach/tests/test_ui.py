"""Streamlit app tests (headless, via streamlit.testing): default run, break-it cases, the human step, demo sandbox."""
import json
import shutil
import sys
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "speakingcoach" / "ui.py"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    for d in ("config", "prompts", "evals", "samples", "scripts", "docs"):
        if (ROOT / d).exists():
            shutil.copytree(ROOT / d, tmp_path / d)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPEAKINGCOACH_ROOT", str(tmp_path))
    for m in [m for m in sys.modules if m.startswith("speakingcoach")]:
        del sys.modules[m]
    return st_testing.AppTest.from_file(str(APP), default_timeout=120)


def click(at, label):
    return next(b for b in at.button if label in b.label).click().run()


def metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


def test_default_run(app):
    at = app.run()
    assert not at.exception
    at = click(at, "Analyse my speaking")
    assert not at.exception, at.exception
    assert metric(at, "Grade") == "F"
    assert float(metric(at, "Fillers")) == 17
    html = " ".join(m.value for m in at.markdown)
    assert "<mark" in html and "sentence starter" in html


def test_injection_is_flagged_and_does_not_change_counts(app):
    at = click(app.run(), "Analyse my speaking")
    before = metric(at, "Fillers")
    at = click(at, "Insert an instruction")
    at = click(at, "Analyse my speaking")
    assert metric(at, "Fillers") == before
    assert any("looks like an instruction" in w.value for w in at.warning)


def test_like_as_verb_sample(app):
    at = app.run()
    at.selectbox(key="sample").set_value("like-as-verb.txt").run()
    at = click(at, "Analyse my speaking")
    assert float(metric(at, "Fillers")) == 2          # the normal uses of like are not counted


def test_meeting_export_scores_one_speaker(app):
    at = app.run()
    at.selectbox(key="sample").set_value("team-update.txt").run()
    assert at.selectbox(key="speaker").value == "Sam Ortiz"
    at = click(at, "Analyse my speaking")
    assert float(metric(at, "Fillers")) == 10


def test_empty_word_list_warns(app):
    at = app.run()
    at.multiselect(key="presets").set_value([]).run()
    at = click(at, "Analyse my speaking")
    assert not at.exception
    assert float(metric(at, "Fillers")) == 0
    assert any("word list is empty" in c.value for c in at.caption)


def test_human_override_rescores_and_saves_case(app, tmp_path):
    at = click(app.run(), "Analyse my speaking")
    before = float(metric(at, "Fillers"))
    opt = next(o for o in at.selectbox(key="override_pick").options if " · So · " in o or " · so · " in o)
    at.selectbox(key="override_pick").set_value(opt).run()
    at.radio(key="override_to").set_value("Not a filler").run()
    at.checkbox(key="save_case").check().run()
    at = click(at, "Apply my calls")
    assert not at.exception, at.exception
    assert float(metric(at, "Fillers")) == before - 1
    saved = (tmp_path / "evals" / "feedback.yaml").read_text()
    assert "is_filler: false" in saved and "word: so" in saved


def test_hosted_demo_sandbox_and_links(app, tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("PORTFOLIO_DEMO", "1")
    monkeypatch.setenv("DEMO_SESSIONS_DIR", str(sessions))
    monkeypatch.setenv("PORTFOLIO_BLOG_URL", "https://example.test/personal/speaking-coach/")
    monkeypatch.setenv("PORTFOLIO_SOURCE_URL", "https://github.com/example/speaking-coach")
    at = click(app.run(), "Analyse my speaking")
    assert not at.exception, at.exception
    boxes = [d for d in (sessions / "speaking-coach").iterdir() if d.is_dir()]
    assert len(boxes) == 1 and (boxes[0] / "logs" / "runs.jsonl").exists()
    assert not (tmp_path / "logs").exists()                      # shared baseline untouched
    assert at.checkbox(key="history").disabled                   # no history in the public demo
    links = " ".join(m.value for m in at.markdown)
    assert "example.test/personal/speaking-coach" in links


def test_run_emits_governance_events_without_text(app, governance_spool):
    at = click(app.run(), "Analyse my speaking")
    assert not at.exception, at.exception
    raw = governance_spool.read_text()
    events = [json.loads(l) for l in raw.splitlines()]
    assert {"register", "visit", "analyze"} <= {e["event_type"] for e in events}
    run = next(e for e in events if e["event_type"] == "analyze")
    assert run["records_out"] == 17 and run["cost_usd"] > 0
    for phrase in ("working with data teams", "kind of a puzzle", "forty jobs"):
        assert phrase not in raw                                 # telemetry never carries transcript text
