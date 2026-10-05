"""The owner's side: the emailed list, signed pick / dismiss links, the confirmation step, GitHub sync."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from editorial import digest, github_sync, links
from editorial.app import create_app


def test_links_are_signed_expiring_and_specific():
    tok = links.sign("abc123abc123abc1", "pick")
    assert links.verify(tok)["action"] == "pick"
    with pytest.raises(ValueError):
        links.verify(tok[:-3] + ("AAA" if not tok.endswith("AAA") else "BBB"))
    with pytest.raises(ValueError):
        links.verify(links.sign("abc123abc123abc1", "pick", ttl_days=1, now=time.time() - 3 * 86400))


def test_digest_lists_the_queue_with_working_links(scouted):
    store, _ = scouted
    mail = digest.render(store)
    assert mail["count"] == 10 and "Pick for a post" in mail["html"]
    tok = mail["text"].split("/act?t=")[1].split()[0]
    assert links.verify(tok)["action"] == "pick"
    assert digest.send(store) == "written"                     # no SMTP settings: written to the outbox


def test_get_only_confirms_post_applies_once(scouted):
    store, _ = scouted
    c = TestClient(create_app(store, background=False))
    t = store.queue()[3]
    tok = links.sign(t["id"], "pick")
    r = c.get(f"/act?t={tok}")
    assert "Pick this topic" in r.text and store.topic(t["id"])["status"] == "queued"   # a GET changes nothing
    r = c.post("/act", data={"t": tok})
    assert "picked" in r.text and store.topic(t["id"])["status"] == "picked"
    assert "already been used" in c.post("/act", data={"t": tok}).text
    assert store.query("select action, actor from actions")[0] == {"action": "pick", "actor": "owner (signed email link)"}
    assert "not valid" in c.post("/act", data={"t": "garbage"}).text


def test_public_queue_views(scouted):
    store, _ = scouted
    c = TestClient(create_app(store, background=False))
    assert len(c.get("/api/queue").json()) == 10
    md = c.get("/queue.md").text
    assert md.startswith("# Topic queue") and "- id: `" in md
    assert "Blog topic queue" in c.get("/").text
    assert c.get("/api/health").json()["queue"] == 10


def test_github_sync_marks_drafted_published_dismissed(scouted):
    store, _ = scouted
    q = store.queue()
    prs = [{"number": 1, "state": "open", "merged_at": None, "labels": [{"name": "draft-post"}], "body": f"Topic: `{q[0]['id']}`"},
           {"number": 2, "state": "closed", "merged_at": "2026-10-09T10:00:00Z", "labels": [{"name": "draft-post"}],
            "body": f"Topic: {q[1]['id']}"},
           {"number": 3, "state": "closed", "merged_at": None, "labels": [{"name": "draft-post"}], "body": f"Topic: {q[2]['id']}"},
           {"number": 4, "state": "open", "merged_at": None, "labels": [], "body": f"Topic: {q[3]['id']}"}]
    changed = github_sync.sync(store, get=lambda url, **kw: json.dumps(prs))
    assert changed == {q[0]["id"]: "drafted", q[1]["id"]: "published", q[2]["id"]: "dismissed"}
    assert store.topic(q[3]["id"])["status"] == "queued"            # no label: not ours


def test_health_says_why_the_queue_is_empty_and_accepts_head(tmp_path):
    from editorial.store import Store
    store = Store(str(tmp_path / "e.sqlite"))
    c = TestClient(create_app(store, background=False))
    assert c.get("/api/health").json()["last_scout"] is None
    store.run("scout", "skipped", {"reason": "editorial-agents is switched off by governance: testing"})
    h = c.get("/api/health").json()
    assert h["queue"] == 0 and h["last_scout_status"] == "skipped" and "switched off" in h["last_scout_problem"]
    assert c.head("/queue.md").status_code == 200 and c.head("/api/health").status_code == 200
