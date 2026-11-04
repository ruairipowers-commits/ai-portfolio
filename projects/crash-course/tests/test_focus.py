"""The learner's own focus on the tracker: favourites, priority, their order, sorting and "up next"."""
import re

from crash_course import tracker
from crash_course.store import connect, one


def order(page: str) -> list[str]:
    return re.findall(r'class="card track" id="c-([a-z0-9-]+)"', page)


def lid():
    with connect() as c:
        return one(c, "SELECT id FROM learners WHERE email='ada@example.com'")["id"]


def test_new_courses_go_to_the_end_and_can_be_moved(learner):
    for slug in ("streamlit", "dbt", "duckdb"):
        learner.post("/enroll", data={"course": slug})
    assert order(learner.get("/tracker").text) == ["streamlit", "dbt", "duckdb"]
    learner.post("/tracker/focus", data={"course": "duckdb", "action": "top"})
    assert order(learner.get("/tracker").text) == ["duckdb", "streamlit", "dbt"]
    learner.post("/tracker/focus", data={"course": "duckdb", "action": "down"})
    learner.post("/tracker/focus", data={"course": "dbt", "action": "up"})
    assert order(learner.get("/tracker").text) == ["streamlit", "dbt", "duckdb"]
    learner.post("/enroll", data={"course": "pandas"})                   # after a move, still added at the end
    assert order(learner.get("/tracker").text)[-1] == "pandas"


def test_favourites_priority_and_sorting(learner):
    for slug in ("streamlit", "dbt", "duckdb"):
        learner.post("/enroll", data={"course": slug})
    learner.post("/tracker/focus", data={"course": "duckdb", "action": "favorite"})
    learner.post("/tracker/focus", data={"course": "dbt", "action": "priority:high"})
    learner.post("/tracker/focus", data={"course": "streamlit", "action": "priority:low"})
    page = learner.get("/tracker").text
    assert "★" in page and "high priority" in page and "Favourites only (1)" in page
    assert order(learner.get("/tracker?fav=1").text) == ["duckdb"]
    assert order(learner.get("/tracker?sort=priority").text) == ["dbt", "duckdb", "streamlit"]
    assert order(learner.get("/tracker?sort=recent").text) == ["duckdb", "dbt", "streamlit"]
    learner.post("/tracker/focus", data={"course": "duckdb", "action": "unfavorite"})
    assert "Favourites only (0)" in learner.get("/tracker").text


def test_up_next_prefers_favourites(learner, published):
    for slug in published:                                                 # streamlit, dbt: Familiar published
        learner.post("/enroll", data={"course": slug})
    assert re.search(r"Up next</span>\s*<b>Streamlit", learner.get("/tracker").text)
    learner.post("/tracker/focus", data={"course": "dbt", "action": "favorite"})
    assert re.search(r"Up next</span>\s*<b>dbt", learner.get("/tracker").text)


def test_focus_rules(learner, client):
    learner.post("/enroll", data={"course": "streamlit"})
    assert learner.post("/tracker/focus", data={"course": "dbt", "action": "favorite"}).status_code == 400
    assert learner.post("/tracker/focus", data={"course": "streamlit", "action": "priority:urgent"}).status_code == 400
    assert learner.post("/tracker/focus", data={"course": "streamlit", "action": "drop table"}).status_code == 400
    r = learner.post("/tracker/focus", data={"course": "streamlit", "action": "favorite", "back": "x/../evil"},
                     follow_redirects=False)
    assert r.headers["location"].endswith("/tracker#c-streamlit")         # a bad back value is dropped
    with connect() as c:
        assert one(c, "SELECT favorite FROM enrollments WHERE learner_id=?", lid())["favorite"] == 1


def test_focus_needs_sign_in(client):
    r = client.post("/tracker/focus", data={"course": "streamlit", "action": "favorite"}, follow_redirects=False)
    assert r.status_code == 303 and "/signin" in r.headers["location"]


def test_sort_entries_keeps_learner_order_on_ties():
    e = [{"course": n, "priority": p, "favorite": f, "done": d, "enrolled_at": t}
         for n, p, f, d, t in [("a", "normal", False, 1, "1"), ("b", "normal", True, 1, "1"), ("c", "high", False, 0, "2")]]
    assert [x["course"] for x in tracker.sort_entries(e, "priority")] == ["c", "b", "a"]
    assert [x["course"] for x in tracker.sort_entries(e, "progress")] == ["a", "b", "c"]
    assert [x["course"] for x in tracker.sort_entries(e, "mine")] == ["a", "b", "c"]
