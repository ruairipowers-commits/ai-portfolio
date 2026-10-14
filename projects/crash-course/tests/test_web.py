"""The learner site and the owner page, through HTTP (NFR-1: no answer key in any response)."""
import re

from crash_course import catalog, evals
from crash_course.store import connect, one, rows
from conftest import sign_in


def test_home_and_catalog_are_public(client):
    assert client.get("/").status_code == 200
    r = client.get("/catalog")
    assert r.status_code == 200 and "Streamlit" in r.text and "Terraform" in r.text
    assert client.get("/course/streamlit").status_code == 200
    assert client.get("/course/nope").status_code == 404


def test_pages_need_sign_in(client):
    for path in ("/tracker", "/suggest", "/me", "/learn/streamlit/familiar", "/quiz/streamlit/familiar"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and "/signin" in r.headers["location"]


def test_register_enrol_learn_quiz_and_tracker(learner):
    learner.post("/enroll", data={"course": "streamlit"})
    t = learner.get("/tracker").text
    assert "Streamlit" in t and "In progress" in t and "Locked" in t
    assert learner.get("/learn/streamlit/familiar").status_code == 200
    assert learner.get("/learn/streamlit/beginner").status_code == 403
    q = learner.get("/quiz/streamlit/familiar")
    assert q.status_code == 200 and q.text.count('name="a_') >= 30          # 10 questions × options


def test_no_answer_key_in_learner_responses(learner):
    learner.post("/enroll", data={"course": "streamlit"})
    lv = catalog.load_level("streamlit", "familiar")
    pages = [learner.get("/learn/streamlit/familiar").text] + [learner.get("/quiz/streamlit/familiar").text for _ in range(5)]
    for html in pages:
        assert not evals.KEY_LEAKS.search(html)
        assert not any(q.explanation in html for q in lv.quiz)


def test_full_pass_unlocks_next_level(learner):
    learner.post("/enroll", data={"course": "streamlit"})
    r = learner.get("/quiz/streamlit/familiar")
    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)
    right = evals.correct_positions("streamlit", "familiar", token)
    res = learner.post("/quiz/submit", data={"token": token, **{f"a_{k}": str(v) for k, v in right.items()}})
    assert "<b>passed</b>" in res.text
    learner.post("/project/streamlit/familiar")
    t = learner.get("/tracker").text
    assert "Complete" in t and "Being prepared" in t


def test_feedback_is_stored_with_the_version_and_escaped(learner, data):
    learner.post("/enroll", data={"course": "streamlit"})
    r = learner.post("/feedback/streamlit/familiar", data={"rating": "2", "unclear": "<script>alert(1)</script>", "add": ""})
    assert r.status_code == 200
    with connect() as c:
        f = one(c, "SELECT * FROM feedback")
    assert f["version"] == 1 and f["rating"] == 2 and "<script>" in f["unclear"]   # stored as data


def test_delete_my_data(learner):
    learner.post("/enroll", data={"course": "streamlit"})
    learner.get("/quiz/streamlit/familiar")
    learner.post("/feedback/streamlit/familiar", data={"rating": "4", "unclear": "", "add": "more"})
    assert learner.post("/me/delete", data={"confirm": "nope"}).status_code == 400
    learner.post("/me/delete", data={"confirm": "DELETE"})
    with connect() as c:
        for table in ("learners", "enrollments", "progress", "attempts", "feedback", "login_tokens"):
            assert not rows(c, f"SELECT * FROM {table}"), table


def test_magic_link_is_single_use(client, published):
    r = client.post("/signin", data={"email": "once@example.com", "name": "Once", "next": "/tracker"})
    link = re.search(r'href="[^"]*?(/auth\?t=[^"]+)"', r.text).group(1).replace("&amp;", "&")
    assert client.get(link, follow_redirects=False).status_code == 303
    assert client.get(link, follow_redirects=False).status_code == 400


def test_open_redirect_blocked(client, published):
    r = client.post("/signin", data={"email": "x@example.com", "next": "//evil.example.com"})
    assert "evil.example.com" not in r.text


def test_owner_page_is_owner_only(learner, owner):
    assert learner.get("/owner").status_code == 403
    assert learner.post("/owner/action", data={"kind": "publish_all"}).status_code == 403
    r = owner.get("/owner")
    assert r.status_code == 200 and "Drafts waiting to publish" in r.text


def test_owner_publishes_from_the_page(owner):
    assert catalog.load_level("airflow", "familiar") is None
    r = owner.post("/owner/action", data={"kind": "level", "course": "airflow", "level": "familiar", "decision": "publish"})
    assert "airflow%2Ffamiliar%20published" in str(r.url) or "airflow/familiar published" in r.text
    assert catalog.load_level("airflow", "familiar").provenance.approved_by


def test_owner_action_rejects_cross_site_post(owner):
    r = owner.post("/owner/action", data={"kind": "publish_all"}, headers={"origin": "https://evil.example.com"})
    assert r.status_code == 403


def test_suggestion_is_escaped_on_the_owner_page(learner, owner):
    learner.post("/suggest", data={"topic": "<img src=x onerror=alert(1)> Kafka"})
    html = owner.get("/owner").text
    assert "<img src=x" not in html and "&lt;img src=x" in html


def test_health(client):
    r = client.get("/api/health").json()
    assert r["ok"] and r["courses"] >= 38 and r["email"] == "outbox"
