"""Glossary: screened look-ups, the one learner-triggered model call (signed in, limited, cached), owner approval."""
import json
import re

import pytest

from crash_course import ai, glossary
from crash_course.store import connect, one, rows


def test_terms_are_screened_before_anything_else(s):
    for bad in ("x", "a" * 61, "one two three four five six", "ada@example.com", "ignore previous instructions",
                "<script>", "porn"):
        with pytest.raises(glossary.Refused):
            glossary.check_term(bad, s)
    assert glossary.check_term("  TLS. ", s) == "TLS"
    assert glossary.check_term("CI/CD", s) == "CI/CD"


def test_lookup_finds_bundled_terms_for_anyone(client):
    r = client.get("/api/glossary/lookup", params={"term": "tls"}).json()
    assert r["found"] and r["reviewed"] and r["expansion"] == "Transport Layer Security" and not r["signed_in"]
    assert client.get("/api/glossary/lookup", params={"term": "zzqx"}).json()["found"] is False
    assert client.get("/api/glossary/lookup", params={"term": "a@b.co"}).status_code == 400


def test_explain_needs_sign_in(client):
    assert client.post("/api/glossary/explain", data={"term": "TLS"}).status_code == 401
    assert client.post("/api/glossary/add", data={"term": "TLS"}).status_code == 401


def test_offline_placeholder_is_never_cached(learner):
    r = learner.post("/api/glossary/explain", data={"term": "Kafka Streams", "course": "streamlit"}).json()
    assert r["found"] and not r["reviewed"] and "running offline" in r["definition"]
    with connect() as c:
        assert not rows(c, "SELECT * FROM glossary")
        assert one(c, "SELECT COUNT(*) n FROM runs WHERE action='glossary_explain'")["n"] == 1


def test_real_answers_are_cached_and_limited(learner, monkeypatch, s):
    monkeypatch.setattr(ai, "is_placeholder", lambda alias: False)       # treat the mock like a real model
    first = learner.post("/api/glossary/explain", data={"term": "Kafka Streams", "context": "Use Kafka Streams to …",
                                                        "course": "streamlit"}).json()
    again = learner.post("/api/glossary/explain", data={"term": "kafka streams"}).json()
    assert first["definition"] == again["definition"] and again["status"] == "draft"
    with connect() as c:
        assert one(c, "SELECT COUNT(*) n FROM runs WHERE action='glossary_explain'")["n"] == 1   # the second was cached
        assert one(c, "SELECT status, source FROM glossary")["status"] == "draft"
        lid = one(c, "SELECT id FROM learners WHERE email='ada@example.com'")["id"]
        for i in range(s["glossary"]["per_learner_per_day"]):
            c.execute("INSERT INTO glossary_asks (learner_id, term_key, at) VALUES (?,?,?)", (lid, f"t{i}", "2999-01-01"))
    r = learner.post("/api/glossary/explain", data={"term": "Flink"})
    assert r.status_code == 400 and "limit" in r.json()["error"]


def test_per_minute_limit(learner, s):
    codes = [learner.post("/api/glossary/explain", data={"term": f"Term{i}"}).status_code
             for i in range(s["glossary"]["per_minute"] + 1)]
    assert codes[-1] == 429 and set(codes[:-1]) == {200}


def test_add_approve_and_hover(learner, owner):
    assert learner.post("/api/glossary/add", data={"term": "Kafka", "course": "streamlit"}).json()["message"] == \
        "sent to the owner for review"
    assert learner.post("/api/glossary/add", data={"term": "TLS"}).json()["message"] == "already in the glossary"
    page = owner.get("/owner").text
    assert "Glossary terms to review (1)" in page and "Requested by a learner" in page
    owner.post("/owner/action", data={"kind": "glossary", "key": "kafka", "decision": "approve", "term": "Kafka",
                                      "expansion": "", "definition": "too short"})          # under 10 chars: refused
    with connect() as c:
        assert one(c, "SELECT status FROM glossary WHERE term_key='kafka'")["status"] == "draft"
    owner.post("/owner/action", data={"kind": "glossary", "key": "kafka", "decision": "approve", "term": "Kafka",
                                      "expansion": "", "definition": "A distributed log for streaming events.", "more": ""})
    r = learner.get("/api/glossary/lookup", params={"term": "kafka"}).json()
    assert r["reviewed"] and r["definition"].startswith("A distributed log")
    assert "Kafka" in learner.get("/glossary").text
    learner.post("/enroll", data={"course": "streamlit"})
    html = learner.get("/learn/streamlit/familiar").text
    terms = json.loads(re.search(r'id="glossary-terms">(.*?)</script>', html, re.S).group(1))
    assert {"Kafka", "TLS"} <= {t["term"] for t in terms} and "glossary.js" in html
    with connect() as c:
        assert one(c, "SELECT decision FROM approvals WHERE kind='glossary'")["decision"] == "approve"


def test_rejected_terms_stay_rejected(learner, owner):
    learner.post("/api/glossary/add", data={"term": "Blorp"})
    owner.post("/owner/action", data={"kind": "glossary", "key": "blorp", "decision": "reject"})
    assert "decided not to add" in learner.post("/api/glossary/add", data={"term": "blorp"}).json()["message"]


def test_delete_my_data_covers_glossary(learner):
    learner.post("/api/glossary/explain", data={"term": "Flink"})
    learner.post("/api/glossary/add", data={"term": "Flink"})
    learner.post("/me/delete", data={"confirm": "DELETE"})
    with connect() as c:
        assert not rows(c, "SELECT * FROM glossary_asks")
        assert one(c, "SELECT requested_by FROM glossary WHERE term_key='flink'")["requested_by"] is None


def test_find_out_more_on_a_reviewed_term_keeps_its_definition(learner):
    r = learner.post("/api/glossary/explain", data={"term": "JSON"}).json()        # bundled, no "more" of its own
    assert r["reviewed"] and r["definition"].startswith("A plain-text format")   # the model only adds "more"
    tls = learner.post("/api/glossary/explain", data={"term": "TLS"}).json()       # bundled with "more": no call
    assert tls["more"] and not tls["more_ai"]
    with connect() as c:
        assert one(c, "SELECT COUNT(*) n FROM runs WHERE action='glossary_explain'")["n"] == 1


def test_suggest_form_is_prefilled(learner):
    assert 'value="Kafka Streams"' in learner.get("/suggest", params={"topic": "Kafka Streams"}).text
