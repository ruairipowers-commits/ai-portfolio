"""The live service never drafts placeholder levels, says what learners are waiting on, and the local writer uses its
own model. Also: a hand-written bundled version replaces a placeholder draft already on the live site."""
import json

import pytest

from conftest import sign_in
from crash_course import builder, catalog, evals, llm
from crash_course.schemas import Level


@pytest.fixture()
def live(monkeypatch):
    monkeypatch.setenv("COURSE_REQUIRE_SECRETS", "1")          # what Dockerfile.space sets
    monkeypatch.delenv("COURSE_ALLOW_MOCK_WRITER", raising=False)


def test_live_service_refuses_the_mock_writer(live, s, conn):
    lv, rep, err = builder.build(conn, s, "dbt", "beginner")
    assert lv is None and "COURSE_WRITER_MODEL" in err
    assert not list(catalog.runtime_dir("dbt").glob("beginner.v*.yaml"))   # nothing written
    assert catalog.level_status("dbt")["beginner"] == "missing"


def test_offline_and_demo_still_use_the_mock(monkeypatch, s, conn):
    lv, rep, err = builder.build(conn, s, "dbt", "beginner")            # offline: the mock writes a draft
    assert lv is not None and err == ""
    monkeypatch.setenv("COURSE_REQUIRE_SECRETS", "1")
    monkeypatch.setenv("COURSE_ALLOW_MOCK_WRITER", "1")                  # explicit opt-in on a demo host
    lv, rep, err = builder.build(conn, s, "streamlit", "beginner")
    assert lv is not None


def test_a_real_writer_is_not_blocked(live, monkeypatch, s):
    from crash_course import ai
    monkeypatch.setenv("COURSE_WRITER_MODEL", "local-qwen")
    assert not ai.placeholder_writer_blocked(s)


def _finish_familiar(c, slug):
    c.post("/enroll", data={"course": slug})
    r = c.get(f"/quiz/{slug}/familiar")
    token = r.text.split('name="token" value="')[1].split('"')[0]
    right = evals.correct_positions(slug, "familiar", token)
    c.post("/quiz/submit", data={"token": token, **{f"a_{k}": str(v) for k, v in right.items()}})
    c.post(f"/project/{slug}/familiar")


def test_owner_sees_what_learners_wait_on_and_why(live, client, owner):
    _finish_familiar(sign_in(client, "ada@example.com", "Ada"), "streamlit")
    page = owner.get("/owner").text
    assert "No writer model is set" in page
    assert "Learners are waiting on (1)" in page and "Streamlit" in page
    assert "Draft now" in page and "disabled" in page                  # can't queue a build without a writer
    r = owner.post("/owner/action", data={"kind": "build", "course": "streamlit", "level": "beginner"})
    assert "No writer model is set" in r.text
    assert catalog.level_status("streamlit")["beginner"] == "missing"


def test_draft_now_queues_a_build_once_a_writer_is_set(live, monkeypatch, client, owner, conn):
    monkeypatch.setenv("COURSE_WRITER_MODEL", "local-qwen")
    _finish_familiar(sign_in(client, "ada@example.com", "Ada"), "streamlit")
    r = owner.post("/owner/action", data={"kind": "build", "course": "streamlit", "level": "beginner"})
    assert "already being drafted" in r.text or "queued" in r.text      # the unlock may have queued it already
    from crash_course.store import one
    assert one(conn, "SELECT status FROM jobs WHERE kind='build' AND course='streamlit' AND level='beginner'")


def test_ollama_uses_its_own_model_not_the_shared_one(monkeypatch):
    sent = {}

    class R:
        status_code = 200

        @staticmethod
        def json():
            return {"message": {"content": "{}"}, "prompt_eval_count": 1, "eval_count": 1}

        @staticmethod
        def raise_for_status():
            pass

    def post(url, json, timeout):
        sent.update(json, timeout=timeout.read)
        return R()

    import httpx
    monkeypatch.setattr(httpx, "post", post)
    spec = type("S", (), {"model_id": "qwen3:14b"})()
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:e4b")                    # the site assistant's chat model
    monkeypatch.delenv("COURSE_OLLAMA_MODEL", raising=False)
    llm.OllamaProvider().complete(spec, "sys", "user", 12000)
    assert sent["model"] == "qwen3:14b" and sent["options"]["num_ctx"] >= 16384 + 12000
    assert sent["timeout"] >= 1200
    monkeypatch.setenv("COURSE_OLLAMA_MODEL", "qwen3-coder:30b")
    llm.OllamaProvider().complete(spec, "sys", "user", 12000)
    assert sent["model"] == "qwen3-coder:30b"


def test_missing_ollama_model_says_how_to_fix_it(monkeypatch):
    class R:
        status_code = 404

    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: R())
    with pytest.raises(RuntimeError, match="ollama pull qwen3:14b"):
        llm.OllamaProvider().complete(type("S", (), {"model_id": "qwen3:14b"})(), "s", "u", 10)


def test_hand_written_aws_beginner_replaces_a_placeholder_draft(s, conn):
    # the live site already holds the placeholder writer's v1 draft; the bundled level is v2
    bundled = catalog.load_level("aws", "beginner", include_drafts=True)
    assert bundled.version == 2 and "placeholder" not in bundled.provenance.written_by
    v1 = bundled.model_copy(update={"version": 1, "title": "placeholder"})
    v1.provenance.written_by = "course-writer → mock-writer"
    catalog.save_level(v1)
    newest = catalog.load_level("aws", "beginner", include_drafts=True)
    assert newest.version == 2 and newest.title == "AWS for AI workloads in 1 hour"
    ok, problems = builder.publish(conn, s, "aws", "beginner", "Test Owner")
    assert ok, problems
    assert catalog.load_level("aws", "beginner").version == 2
    assert catalog.level_status("aws")["beginner"] == "published"


def test_aws_beginner_passes_every_check(s, conn):
    from crash_course import checks
    lv = catalog.load_level("aws", "beginner", include_drafts=True)
    rep = checks.check_level(lv, catalog.all_courses(conn)["aws"], s)
    assert rep.ok, rep.problems
    assert rep.stats["minutes"] <= 60 and len(lv.quiz) >= 17
    assert isinstance(Level.model_validate(json.loads(lv.model_dump_json())), Level)
