"""Withdraw / re-release a course, level versions, "Updated to vN" notices and rollback."""
import pytest

from crash_course import builder, catalog, lifecycle, quiz, tracker
from crash_course.store import connect, one, rows
from crash_course.tracker import NotAllowed
from test_quiz_and_tracker import answers, new_learner


def complete_familiar(conn, s, lid, course="streamlit"):
    tracker.mark_project(conn, s, lid, course, "familiar")
    a = quiz.start(conn, s, lid, course, "familiar")
    assert quiz.submit(conn, s, lid, a["token"], answers(conn, a, course))["level_complete"]


def new_version(conn, s, changes, course="streamlit", level="familiar"):
    """The owner publishes a new version of a level (a draft written from the current one)."""
    cur = catalog.load_level(course, level)
    catalog.save_level(cur.model_copy(update={"version": catalog.next_version(course, level), "status": "draft",
                                              "title": cur.title + " (revised)", "changes": ""}))
    ok, problems = builder.publish(conn, s, course, level, "Owner", changes)
    assert ok, problems
    return catalog.load_level(course, level)


# ---------------------------------------------------------------- withdraw / re-release
def test_withdrawn_course_takes_no_new_signups_but_keeps_its_learners(conn, s, published):
    early = new_learner(conn, "early@example.com")
    tracker.enroll(conn, s, early, "streamlit")
    lifecycle.set_state(conn, "streamlit", "withdrawn", "Owner", "new major version")
    assert lifecycle.is_withdrawn(conn, "streamlit")
    late = new_learner(conn, "late@example.com")
    with pytest.raises(NotAllowed, match="reworked"):
        tracker.enroll(conn, s, late, "streamlit")
    tracker.enroll(conn, s, early, "streamlit")                       # already on it: no error, nothing changes
    complete_familiar(conn, s, early)                                 # keeps progressing
    assert tracker.progress(conn, early, "streamlit", "beginner")
    lifecycle.set_state(conn, "streamlit", "active", "Owner")
    tracker.enroll(conn, s, late, "streamlit")                        # re-released: open again
    log = [(r["kind"], r["ref"], r["decision"]) for r in rows(conn, "SELECT * FROM approvals WHERE kind='course'")]
    assert log == [("course", "streamlit", "withdraw"), ("course", "streamlit", "release")]
    with pytest.raises(ValueError):
        lifecycle.set_state(conn, "no-such-course", "withdrawn", "Owner")


def test_pages_hide_a_withdrawn_course_from_new_learners(client, owner, s):
    from conftest import sign_in
    learner = sign_in(client, "ada@example.com", "Ada")
    learner.post("/enroll", data={"course": "streamlit"})
    r = owner.post("/owner/action", data={"kind": "course", "course": "streamlit", "decision": "withdraw",
                                          "notes": "rework"})
    assert "streamlit withdrawn" in r.text and "1 learner(s) keep access" in r.text
    # Ada is on it: still listed (badged), the course page, tracker and materials show the banner
    assert "Being reworked" in learner.get("/catalog").text
    assert "You keep full access" in learner.get("/course/streamlit").text
    assert "being reworked" in learner.get("/tracker").text
    assert "Being reworked" in learner.get("/learn/streamlit/familiar").text
    # a new visitor: not in the catalog, the course page says so, sign-up is refused, JobHunt's list leaves it out
    from fastapi.testclient import TestClient
    from crash_course.web import create_app
    anon = TestClient(create_app())
    assert 'id="c-streamlit"' not in anon.get("/catalog").text and 'id="c-dbt"' in anon.get("/catalog").text
    page = anon.get("/course/streamlit")
    assert page.status_code == 404 and "being reworked" in page.text
    bob = sign_in(TestClient(create_app()), "bob@example.com", "Bob")
    assert "taking new sign-ups" in bob.post("/enroll", data={"course": "streamlit"}).text
    with connect() as c:
        from crash_course import ownerapi
        assert "streamlit" not in {x["slug"] for x in ownerapi.catalog_list(c)}
    # the owner still sees it, then re-releases it
    assert "Withdrawn" in owner.get("/owner").text and "Re-release" in owner.get("/owner/course/streamlit").text
    owner.post("/owner/action", data={"kind": "course", "course": "streamlit", "decision": "release"})
    assert 'id="c-streamlit"' in anon.get("/catalog").text
    bob.post("/enroll", data={"course": "streamlit"})
    assert "Streamlit" in bob.get("/tracker").text


def test_course_actions_are_owner_only(learner):
    learner.post("/owner/action", data={"kind": "course", "course": "streamlit", "decision": "withdraw"})
    with connect() as c:
        assert not lifecycle.is_withdrawn(c, "streamlit")
    assert learner.get("/owner/course/streamlit").status_code == 403


# ---------------------------------------------------------------- versions and "Updated to vN"
def test_completed_learner_sees_what_changed_and_keeps_completion(conn, s, published):
    lid = new_learner(conn)
    tracker.enroll(conn, s, lid, "streamlit")
    complete_familiar(conn, s, lid)
    v1 = catalog.load_level("streamlit", "familiar").version
    assert one(conn, "SELECT completed_version FROM progress WHERE learner_id=? AND level='familiar'", lid)["completed_version"] == v1
    assert lifecycle.notices(conn, lid) == []                         # nothing newer yet
    new_version(conn, s, "Added caching with st.cache_data.")
    v3 = new_version(conn, s, "Rewrote the deployment section.").version
    [n] = lifecycle.notices(conn, lid)
    assert (n["from"], n["to"]) == (v1, v3)
    assert [c["text"] for c in n["changes"]] == ["Rewrote the deployment section.", "Added caching with st.cache_data."]
    p = tracker.progress(conn, lid, "streamlit", "familiar")
    assert p["completed_at"] and tracker.state(conn, s, lid)[0]["levels"][0]["state"] == "complete"
    assert lifecycle.dismiss(conn, lid, "streamlit", "familiar")
    assert lifecycle.notices(conn, lid) == []
    new_version(conn, s, "Fixed a typo.")
    assert [c["text"] for c in lifecycle.notices(conn, lid)[0]["changes"]] == [
        "Fixed a typo.", "Rewrote the deployment section.", "Added caching with st.cache_data."]


def test_learner_who_completes_the_newest_version_gets_no_notice(conn, s, published):
    new_version(conn, s, "Something new.")
    lid = new_learner(conn)
    tracker.enroll(conn, s, lid, "streamlit")
    complete_familiar(conn, s, lid)
    assert lifecycle.notices(conn, lid) == []


def test_notice_pages(learner, s):
    learner.post("/enroll", data={"course": "streamlit"})
    with connect() as c:
        lid = one(c, "SELECT id FROM learners WHERE email='ada@example.com'")["id"]
        complete_familiar(c, s, lid)
        new_version(c, s, "New section on session state.")
    assert "Updated to v" in learner.get("/tracker").text and "New section on session state." in learner.get("/tracker").text
    assert "New section on session state." in learner.get("/learn/streamlit/familiar").text
    assert "See what changed" in learner.get("/course/streamlit").text
    learner.post("/updates/seen", data={"course": "streamlit", "level": "familiar"})
    assert "Updated to v" not in learner.get("/tracker").text


def test_publish_records_what_changed_from_the_owner_form(owner, s):
    with connect() as c:
        cur = catalog.load_level("dbt", "familiar")
        catalog.save_level(cur.model_copy(update={"version": cur.version + 1, "status": "draft"}))
    page = owner.get("/owner").text
    assert f"What changed since v{cur.version}" in page
    owner.post("/owner/action", data={"kind": "level", "course": "dbt", "level": "familiar", "decision": "publish",
                                      "changes": "Updated for the new CLI."})
    lv = catalog.load_level("dbt", "familiar")
    assert (lv.version, lv.changes, lv.status) == (cur.version + 1, "Updated for the new CLI.", "published")


# ---------------------------------------------------------------- history and rollback
def test_history_and_rollback(conn, s, published):
    first = catalog.load_level("streamlit", "familiar")
    second = new_version(conn, s, "A rewrite that didn't land well.")
    hist = lifecycle.history("streamlit", "familiar")
    assert [h["version"] for h in hist] == [second.version, first.version]
    assert hist[0]["current"] and not hist[1]["current"] and hist[1]["status"] == "published"
    ok, problems, new_v = lifecycle.rollback(conn, s, "streamlit", "familiar", first.version, "Owner")
    assert ok, problems
    lv = catalog.load_level("streamlit", "familiar")
    assert lv.version == new_v == second.version + 1 and lv.title == first.title
    assert lv.changes.startswith(f"Rolled back to the content of version {first.version}")
    assert one(conn, "SELECT decision FROM approvals WHERE kind='level' AND ref=?",
               f"streamlit:familiar:v{new_v}")["decision"] == "rollback"
    assert not lifecycle.rollback(conn, s, "streamlit", "familiar", new_v, "Owner")[0]       # already live
    assert not lifecycle.rollback(conn, s, "streamlit", "familiar", 99, "Owner")[0]          # never published


def test_rollback_from_owner_page(owner):
    with connect() as c:
        from crash_course.config import Settings
        s = Settings.load()
        first = catalog.load_level("dbt", "familiar")
        new_version(c, s, "Experimental rewrite.", course="dbt")
    page = owner.get("/owner/course/dbt").text
    assert "Experimental rewrite." in page and "Roll back to this" in page
    r = owner.post("/owner/action", data={"kind": "rollback", "course": "dbt", "level": "familiar",
                                          "version": str(first.version)})
    assert "republished" in r.text
    assert catalog.load_level("dbt", "familiar").title == first.title
