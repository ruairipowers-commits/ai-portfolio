import json
from datetime import date, timedelta

import httpx


def test_digest_collects_every_source_and_emails(client, store, monkeypatch):
    from siteassistant import app as A, digest

    day = date.today().isoformat()
    for body in ({"kind": "pageview", "path": "/ai-portfolio/blog/", "referrer": "https://news.ycombinator.com/"},
                 {"kind": "pageview", "path": "/ai-portfolio/blog/"}, {"kind": "site-search", "q": "dbt tests"}):
        client.post("/api/track", content=json.dumps(body))
    client.get("/api/search", params={"q": "zzzz unknowable"})
    store.put_metric((date.today() - timedelta(days=1)).isoformat(), "blog", "page_views", 1)

    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if url.endswith("/api/summary"):
            assert kw["params"] == {"days": 1, "sim": 0, "end": day}
            return httpx.Response(200, json={"kpi": {"visits": 7, "runs": 4, "users": 3, "tokens": 900, "cost": 0.01},
                                             "series": {"runs": {"eod-heartbeat": [3], "research-qa-rag": [1]}}},
                                  request=httpx.Request("GET", url))
        if "/traffic/views" in url:
            return httpx.Response(200, json={"views": [{"timestamp": f"{day}T00:00:00Z", "count": 12, "uniques": 5}]},
                                  request=httpx.Request("GET", url))
        if "/traffic/clones" in url:
            return httpx.Response(200, json={"clones": [{"timestamp": f"{day}T00:00:00Z", "count": 2, "uniques": 2}]},
                                  request=httpx.Request("GET", url))
        return httpx.Response(200, json={"stargazers_count": 9, "forks_count": 1}, request=httpx.Request("GET", url))

    def fake_post(url, **kw):
        assert kw["headers"]["Authorization"] == "Bearer cf-token" and kw["json"]["variables"]["zone"] == "zone1"
        return httpx.Response(200, json={"data": {"viewer": {"zones": [{"httpRequests1dGroups": [
            {"dimensions": {"date": day}, "sum": {"requests": 900, "pageViews": 120, "bytes": 1, "threats": 0},
             "uniq": {"uniques": 41}}]}]}}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(digest.httpx, "get", fake_get)
    monkeypatch.setattr(digest.httpx, "post", fake_post)
    sent = []
    monkeypatch.setattr(digest, "send", lambda to, subj, text, html: sent.append((to, subj, text, html)))
    for k, v in {"GOVERNANCE_URL": "http://console", "CF_API_TOKEN": "cf-token", "CF_ZONE_ID": "zone1",
                 "GITHUB_TRAFFIC_TOKEN": "gh", "GITHUB_REPOS": "me/ai-portfolio", "DIGEST_EMAIL": "me@example.com",
                 "SMTP_HOST": "smtp", "SMTP_USER": "u", "SMTP_PASSWORD": "p"}.items():
        monkeypatch.setenv(k, v)

    r = digest.run(store, A.SETTINGS, day, send_email=True)
    assert r["status"] == "sent" and sent[0][0] == ["me@example.com"]
    text = sent[0][2]
    for s in ("Blog page views: 2", "Demo runs: 4", "Cloudflare page views: 120", "GitHub repo views: 12",
              "Repo clones (downloads): 2", "news.ycombinator.com", "dbt tests", "zzzz unknowable", "eod-heartbeat"):
        assert s in text, s
    assert "▲ vs 7-day avg 1.0" in text
    assert store.digest_sent(day)


def test_digest_reports_missing_sources_instead_of_failing(store):
    from siteassistant import app as A, digest

    r = digest.run(store, A.SETTINGS, date.today().isoformat(), send_email=True)
    assert r["status"] == "not sent" and "no recipient" in r["error"]
    assert "Not included: demos: not configured" in r["html"] or "not configured" in r["html"]


def test_stats_page_needs_the_owner_token_in_public(client, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DEMO", "1")
    monkeypatch.setenv("ASSISTANT_ADMIN_TOKEN", "s3cret")
    assert client.get("/stats").status_code == 403
    assert "Recent searches" in client.get("/stats", params={"token": "s3cret"}).text
