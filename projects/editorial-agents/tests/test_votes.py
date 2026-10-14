"""Readers' votes: one per visitor per topic per day, they order the queue after the owner's picks, the blog's
origin may cast them (nobody else's), and the owner's email shows them."""
from fastapi.testclient import TestClient

from editorial import digest, github_sync
from editorial.app import create_app


def _client(store, monkeypatch, origin="https://example.github.io"):
    monkeypatch.setenv("PORTFOLIO_SITE_URL", origin + "/ai-portfolio")
    return TestClient(create_app(store, background=False))


def test_one_vote_per_visitor_per_topic_per_day(scouted, monkeypatch):
    store, _ = scouted
    c = _client(store, monkeypatch)
    tid = store.queue()[5]["id"]
    first = c.post(f"/api/queue/{tid}/vote", headers={"user-agent": "reader-a"}).json()
    again = c.post(f"/api/queue/{tid}/vote", headers={"user-agent": "reader-a"}).json()
    other = c.post(f"/api/queue/{tid}/vote", headers={"user-agent": "reader-b"}).json()
    assert (first["counted"], again["counted"], other["counted"]) == (True, False, True)
    assert other["votes"] == 2
    assert c.post("/api/queue/0000000000000000/vote").status_code == 404


def test_votes_order_the_queue_after_picks(scouted, monkeypatch):
    store, _ = scouted
    c = _client(store, monkeypatch)
    q = store.queue()
    low, picked = q[7]["id"], q[9]["id"]
    for ua in ("a", "b", "c"):
        c.post(f"/api/queue/{low}/vote", headers={"user-agent": ua})
    assert store.queue()[0]["id"] == low                      # most-voted goes first…
    store.set_status(picked, "picked")
    assert [t["id"] for t in store.queue()[:2]] == [picked, low]   # …but the owner's pick still comes first
    rows = c.get("/api/queue").json()
    assert rows[1]["id"] == low and rows[1]["votes"] == 3
    assert "- votes: 3" in c.get("/queue.md").text


def test_votes_rate_limited(scouted, monkeypatch):
    store, _ = scouted
    c = _client(store, monkeypatch)
    monkeypatch.setattr("editorial.app.settings", lambda: {"votes": {"per_hour": 2}, "schedule": {}})
    ids = [t["id"] for t in store.queue()[:3]]
    codes = [c.post(f"/api/queue/{i}/vote", headers={"user-agent": "x"}).status_code for i in ids]
    assert codes == [200, 200, 429]


def test_only_the_blog_origin_gets_cors(scouted, monkeypatch):
    store, _ = scouted
    c = _client(store, monkeypatch)
    tid = store.queue()[0]["id"]
    ok = c.options(f"/api/queue/{tid}/vote", headers={"Origin": "https://example.github.io",
                                                       "Access-Control-Request-Method": "POST"})
    bad = c.options(f"/api/queue/{tid}/vote", headers={"Origin": "https://evil.example",
                                                        "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "https://example.github.io"
    assert "access-control-allow-origin" not in bad.headers


def test_digest_shows_votes_and_next_topic(scouted, monkeypatch):
    store, _ = scouted
    c = _client(store, monkeypatch)
    tid = store.queue()[4]["id"]
    for ua in ("a", "b"):
        c.post(f"/api/queue/{tid}/vote", headers={"user-agent": ua})
    mail = digest.render(store)
    assert "2 new reader votes" in mail["subject"]
    assert "Next to publish" in mail["html"] and "2 votes (+2 new)" in mail["html"]
    assert mail["text"].startswith("1. [NEXT]")
    digest.send(store)
    assert "new reader vote" not in digest.render(store)["subject"]     # counted once, then not "new" any more


def test_sync_tracks_auto_published_posts(scouted):
    store, _ = scouted
    tid = store.queue()[0]["id"]
    prs = [{"number": 9, "state": "closed", "merged_at": "2026-10-15T14:00:00Z",
            "labels": [{"name": "auto-published"}], "body": f"Topic: `{tid}`"}]
    import json
    assert github_sync.sync(store, get=lambda *a, **k: json.dumps(prs)) == {tid: "published"}
