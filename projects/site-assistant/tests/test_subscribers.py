"""Blog subscriptions: double opt-in, no enumeration, scanner-safe unsubscribe that deletes, one email per new post."""
from email import message_from_bytes, policy
from pathlib import Path

from siteassistant import subscribers


def st(store) -> dict:
    return {k: v for k, v in subscribers.counts(store).items() if k != "by_role"}


def outbox(tmp_path) -> list:
    d = Path(tmp_path) / "outbox"
    return [message_from_bytes(p.read_bytes(), policy=policy.default) for p in sorted(d.glob("*.eml"))] if d.exists() else []


def _link(msg, marker: str) -> str:
    body = msg.get_body(("plain",)).get_content()
    return body.split(marker, 1)[1].split()[0]


def test_double_opt_in_and_unsubscribe_deletes(client, store, tmp_path):
    r = client.post("/api/subscribe", json={"email": "Reader@Example.com"})
    assert r.status_code == 202 and "confirm" in r.json()["message"].lower()
    assert st(store) == {"pending": 1}
    mails = outbox(tmp_path)
    assert len(mails) == 1 and mails[0]["Subject"] == "Confirm your subscription"
    token = _link(mails[0], "Confirm: ").split("t=")[1]
    assert "subscribed" in client.get(f"/subscribe/confirm?t={token}").text
    assert st(store) == {"confirmed": 1}
    assert "not valid" in client.get(f"/subscribe/confirm?t={token}").text          # single use
    # same response for an already-subscribed address: no enumeration, and no second email
    assert client.post("/api/subscribe", json={"email": "reader@example.com"}).json() == r.json()
    assert len(outbox(tmp_path)) == 1
    sid = store.query("select id from subscribers")[0]["id"]
    tok = subscribers.unsubscribe_token(sid)
    page = client.get(f"/unsubscribe?t={tok}")
    assert "<form method=post" in page.text and st(store) == {"confirmed": 1}   # GET changes nothing
    assert "deleted" in client.post(f"/unsubscribe?t={tok}").text
    assert store.query("select * from subscribers") == []                           # deleted, not flagged
    assert "not valid" in client.post(f"/unsubscribe?t={sid}.forged").text


def test_invalid_honeypot_and_rate_limit(client, store, tmp_path):
    assert client.post("/api/subscribe", json={"email": "not-an-email"}).status_code == 422
    assert client.post("/api/subscribe", json={"email": "bot@example.com", "website": "spam"}).status_code == 202
    assert st(store) == {} and outbox(tmp_path) == []                # bots get nothing stored
    codes = [client.post("/api/subscribe", json={"email": f"p{i}@example.com"}).status_code for i in range(5)]
    assert 429 in codes


def test_unsubscribe_page_escapes_the_token(client):
    r = client.get("/unsubscribe?t=1.'><script>alert(1)</script>")
    assert "<script>" not in r.text


def test_new_posts_are_announced_once_to_confirmed_only(store, tmp_path):
    store.execute("insert into subscribers (email, status, created_at) values ('a@example.com','confirmed','x'),"
                  "('b@example.com','pending','x')")
    pages = {"blog/old/": {"title": "Old", "date": "2026-09-01", "intro": "old"}}
    assert subscribers.notify(store, pages, "https://example.github.io/ai-portfolio") == []   # first run: seed only
    assert outbox(tmp_path) == []
    pages["blog/new-post/"] = {"title": "New post", "date": "2026-10-09", "intro": "What it is and why it matters."}
    assert subscribers.notify(store, pages, "https://example.github.io/ai-portfolio") == ["blog/new-post/"]
    mails = outbox(tmp_path)
    assert len(mails) == 1 and mails[0]["To"] == "a@example.com"                     # pending gets nothing
    assert mails[0]["Subject"] == "New post: New post" and mails[0]["List-Unsubscribe-Post"]
    assert "https://example.github.io/ai-portfolio/blog/new-post/" in mails[0].get_body(("plain",)).get_content()
    assert subscribers.notify(store, pages, "https://example.github.io/ai-portfolio") == []   # never twice
