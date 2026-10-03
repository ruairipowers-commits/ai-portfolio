"""Content tab: top-rated articles and suggestion moderation, through the site assistant's owner API (faked here)."""
import httpx

DATA = {"top_articles": [{"path": "blog/eod-heartbeat/", "title": "EOD heartbeat", "likes": 5, "last_day": "2026-10-03",
                          "url": "https://x/blog/eod-heartbeat/", "last_7_days": 2}],
        "suggestions": [
            {"id": 1, "idea": "Corporate-actions reconciliation agent", "votes": 4, "status": "published", "day": "2026-10-02",
             "name": "Pat", "contact": "pat@example.com", "visitor": "v", "updated_by": "Ruairi"},
            {"id": 2, "idea": "Spammy idea about watches", "votes": 0, "status": "pending", "day": "2026-10-03",
             "name": "", "contact": "spam@example.com", "visitor": "w", "updated_by": None}],
        "kickoff": {"1": {"industry": "https://claude.ai/new?q=a", "personal": "https://claude.ai/new?q=b"},
                    "2": {"industry": "https://claude.ai/new?q=c", "personal": "https://claude.ai/new?q=d"}}}


def fake(monkeypatch, calls):
    from govconsole import content

    def get(url, **kw):
        calls.append(("GET", url, kw.get("params")))
        return httpx.Response(200, json=DATA, request=httpx.Request("GET", url))

    def post(url, **kw):
        calls.append(("POST", url, kw.get("json"), kw.get("params")))
        return httpx.Response(200, json={"id": 2, "status": kw["json"]["status"]}, request=httpx.Request("POST", url))
    monkeypatch.setattr(content.httpx, "get", get)
    monkeypatch.setattr(content.httpx, "post", post)
    monkeypatch.setenv("ASSISTANT_URL", "http://site-assistant:7860")
    monkeypatch.setenv("ASSISTANT_ADMIN_TOKEN", "tok")


def test_content_tab_admin_sees_everything_and_can_publish(client, monkeypatch):
    calls = []
    fake(monkeypatch, calls)
    page = client.get("/content").text                 # local mode: admin
    assert "Top rated articles" in page and "EOD heartbeat" in page and "<b>5</b>" in page
    assert "Spammy idea about watches" in page and "spam@example.com" in page and "https://claude.ai/new?q=c" in page
    r = client.post("/content/suggestions/2", data={"status": "published"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/content?saved=2#s-2")
    assert calls[-1][0] == "POST" and calls[-1][1].endswith("/admin/suggestions/2")
    assert calls[-1][2]["status"] == "published" and calls[-1][3] == {"token": "tok"}
    assert client.post("/content/suggestions/2", data={"status": "bogus"}).status_code == 422


def test_content_tab_public_sees_only_published_without_contacts(client, monkeypatch):
    calls = []
    fake(monkeypatch, calls)
    monkeypatch.setenv("PORTFOLIO_DEMO", "1")
    monkeypatch.setenv("GOVERNANCE_ADMIN_TOKEN", "adm1n")
    page = client.get("/content").text
    assert "Corporate-actions reconciliation agent" in page and "Spammy idea" not in page
    assert "pat@example.com" not in page and "claude.ai/new" not in page
    assert client.post("/content/suggestions/1", data={"status": "hidden"}).status_code == 403


def test_content_tab_says_when_the_assistant_is_not_connected(client, monkeypatch):
    monkeypatch.delenv("ASSISTANT_URL", raising=False)
    page = client.get("/content").text
    assert "not connected (set ASSISTANT_URL)" in page and "No thumbs up yet" in page
