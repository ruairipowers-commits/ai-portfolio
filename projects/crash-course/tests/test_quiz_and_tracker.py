"""Server-side scoring, retries, unlocks and the completion rule (no model on any learner path)."""
import json

import pytest

from crash_course import catalog, quiz, tracker
from crash_course.store import insert, now, one
from crash_course.tracker import NotAllowed


def new_learner(conn, email="sam@example.com"):
    return insert(conn, "learners", email=email, name="Sam", created_at=now(), last_seen=now())


def answers(conn, a, course="streamlit", level="familiar", right=True):
    orders = json.loads(one(conn, "SELECT option_orders FROM attempts WHERE token=?", a["token"])["option_orders"])
    bank = {q.id: q for q in catalog.load_level(course, level).all_questions()}
    out = {}
    for q in a["questions"]:
        pos = orders[q["id"]].index(bank[q["id"]].answer)
        out[q["id"]] = pos if right else (pos + 1) % len(q["options"])
    return out


def test_attempt_view_has_no_answer_key(conn, s, published):
    lid = new_learner(conn)
    tracker.enroll(conn, s, lid, "streamlit")
    a = quiz.start(conn, s, lid, "streamlit", "familiar")
    blob = json.dumps(a)
    assert set(a) == {"token", "course", "level", "part", "pass_pct", "questions"}
    assert all(set(q) == {"id", "prompt", "options"} for q in a["questions"])
    lv = catalog.load_level("streamlit", "familiar")
    assert not any(q.explanation in blob or q.evidence in blob for q in lv.quiz if q.evidence not in " ".join(q.options))
    assert len(a["questions"]) == s.level("familiar")["quiz"]["questions"]


def test_scoring_maps_shuffled_positions_back(conn, s, published):
    lid = new_learner(conn)
    tracker.enroll(conn, s, lid, "streamlit")
    a = quiz.start(conn, s, lid, "streamlit", "familiar")
    r = quiz.submit(conn, s, lid, a["token"], answers(conn, a))
    assert (r["score"], r["total"], r["passed"]) == (10, 10, True)
    b = quiz.start(conn, s, lid, "streamlit", "familiar")
    r2 = quiz.submit(conn, s, lid, b["token"], answers(conn, b, right=False))
    assert r2["score"] == 0 and not r2["passed"]
    assert all("explanation" in x for x in r2["results"])          # explanations only after a wrong answer
    assert not any("explanation" in x for x in r["results"])


def test_retries_are_unlimited_and_draws_differ(conn, s, published):
    lid = new_learner(conn)
    tracker.enroll(conn, s, lid, "streamlit")
    draws = set()
    for _ in range(8):
        a = quiz.start(conn, s, lid, "streamlit", "familiar")
        draws.add(frozenset(q["id"] for q in a["questions"]))
        quiz.submit(conn, s, lid, a["token"], answers(conn, a, right=False))
    assert len(draws) > 1
    p = tracker.progress(conn, lid, "streamlit", "familiar")
    assert p["quiz_best"] == 0 and p["quiz_passed_at"] is None


def test_replayed_and_foreign_attempts_rejected(conn, s, published):
    a_id, b_id = new_learner(conn, "a@example.com"), new_learner(conn, "b@example.com")
    for lid in (a_id, b_id):
        tracker.enroll(conn, s, lid, "streamlit")
    a = quiz.start(conn, s, a_id, "streamlit", "familiar")
    with pytest.raises(NotAllowed):
        quiz.submit(conn, s, b_id, a["token"], answers(conn, a))       # someone else's token
    quiz.submit(conn, s, a_id, a["token"], answers(conn, a))
    with pytest.raises(NotAllowed, match="already submitted"):
        quiz.submit(conn, s, a_id, a["token"], answers(conn, a))


def test_locked_and_unknown_levels(conn, s, published):
    lid = new_learner(conn)
    with pytest.raises(NotAllowed, match="locked"):
        quiz.start(conn, s, lid, "streamlit", "familiar")             # not enrolled
    tracker.enroll(conn, s, lid, "streamlit")
    for level in ("beginner", "intermediate"):
        with pytest.raises(NotAllowed, match="locked"):
            quiz.start(conn, s, lid, "streamlit", level)
        with pytest.raises(NotAllowed):
            tracker.mark_project(conn, s, lid, "streamlit", level)
    with pytest.raises(NotAllowed):
        tracker.enroll(conn, s, lid, "no-such-course")


def test_completion_needs_quiz_pass_and_project(conn, s, published):
    lid = new_learner(conn)
    tracker.enroll(conn, s, lid, "streamlit")
    tracker.mark_project(conn, s, lid, "streamlit", "familiar")
    assert not tracker.progress(conn, lid, "streamlit", "beginner")      # project alone: still locked
    a = quiz.start(conn, s, lid, "streamlit", "familiar")
    r = quiz.submit(conn, s, lid, a["token"], answers(conn, a))
    assert r["level_complete"]
    assert tracker.progress(conn, lid, "streamlit", "beginner")          # unlocked
    job = one(conn, "SELECT * FROM jobs WHERE course='streamlit' AND level='beginner'")
    assert job and job["kind"] == "build" and job["status"] == "pending"   # drafted on demand, held for the owner
    st = tracker.state(conn, s, lid)[0]
    assert [x["state"] for x in st["levels"]] == ["complete", "preparing", "locked"]


def test_quiz_pass_alone_does_not_unlock(conn, s, published):
    lid = new_learner(conn)
    tracker.enroll(conn, s, lid, "streamlit")
    a = quiz.start(conn, s, lid, "streamlit", "familiar")
    quiz.submit(conn, s, lid, a["token"], answers(conn, a))
    assert not tracker.progress(conn, lid, "streamlit", "beginner")


def test_unpublished_level_is_being_prepared(conn, s):
    """Bundled levels are drafts until the owner publishes them: learners can enrol but not open them yet."""
    lid = new_learner(conn)
    tracker.enroll(conn, s, lid, "airflow")
    with pytest.raises(NotAllowed, match="being prepared"):
        tracker.require_open(conn, lid, "airflow", "familiar")
    assert tracker.state(conn, s, lid)[0]["levels"][0]["state"] == "preparing"


def test_item_stats_flag_most_missed(conn, s, published):
    lid = new_learner(conn)
    tracker.enroll(conn, s, lid, "streamlit")
    for _ in range(3):
        a = quiz.start(conn, s, lid, "streamlit", "familiar")
        quiz.submit(conn, s, lid, a["token"], answers(conn, a, right=False))
    st = quiz.item_stats(conn, "streamlit", "familiar")
    assert st and all(v["missed_pct"] == 100 for v in st.values())
