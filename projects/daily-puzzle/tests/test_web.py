"""Player site: double opt-in, magic links, play through HTMX, unsubscribe, delete, abuse limits, operator page."""
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from daily_puzzle import cycle, game, generate, grading, mailer, puzzles
from daily_puzzle.store import engine, fetch_one, players, puzzles as P, suppression


@pytest.fixture()
def site(s, project):
    """An open puzzle right now, and a client."""
    from daily_puzzle.web import create_app
    eng = engine(s)
    now = datetime.now(timezone.utc)
    with eng.begin() as c:
        pid = generate.store_puzzle(c, s, puzzles.make("ordering", 3, "easy"),
                                    {"steps": []}, status="open", source="generated", day=now.date().isoformat())
        c.execute(P.update().where(P.c.id == pid).values(opens_at=now - timedelta(hours=1), closes_at=now + timedelta(hours=6)))
    return TestClient(create_app(scheduler=False)), pid, project


def last_link(project, kind):
    f = sorted((project / "output" / "outbox").glob(f"*-{kind}-*.eml"))[-1]
    return re.search(r"https?://\S+", f.read_text().split("\n\n", 1)[1]).group(0), f.read_text()


def signup(client, project, email="grace@example.com", handle="grace_h"):
    r = client.post("/subscribe", data={"email": email, "handle": handle, "tracks": ["logic", "ai_ml"]})
    assert r.status_code == 200 and "Check your email" in r.text
    link, _ = last_link(project, "confirm")
    r = client.get(link.split("testserver")[-1].replace("http://localhost:8800", ""), follow_redirects=False)
    assert r.status_code == 303 and "dp_session" in r.cookies
    return r


def test_double_opt_in_and_play(site, s):
    client, pid, project = site
    with engine(s).connect() as c:
        assert not fetch_one(c, select(players))
    signup(client, project)
    with engine(s).connect() as c:
        me = fetch_one(c, select(players))
        key = grading.unseal(fetch_one(c, select(P).where(P.c.id == pid))["sealed_key"])["answer"]
    assert me["confirmed_at"] and me["tracks"] == ["logic", "ai_ml"]
    page = client.get(f"/p/{pid}").text
    assert "Accept this puzzle" in page
    r = client.post(f"/accept/{pid}", headers={"HX-Request": "true"})
    assert "Your answer" in r.text
    r = client.post(f"/submit/{pid}", data={"answer": "Ava, Ben, Cal, Dee"}, headers={"HX-Request": "true"})
    if "Solved" not in r.text:
        assert "Not yet." in r.text and "5 attempts left" in r.text
    r = client.post(f"/submit/{pid}", data={"answer": key}, headers={"HX-Request": "true"})
    assert "Solved" in r.text
    assert "grace_h" in client.get("/leaderboard").text and "grace@example.com" not in client.get("/leaderboard").text


def test_existing_email_gets_signin_not_a_second_account(site, s):
    client, _, project = site
    signup(client, project)
    client.cookies.clear()
    client.post("/subscribe", data={"email": "GRACE@example.com", "handle": "another"})
    link, _ = last_link(project, "signin")
    assert client.get(link.replace("http://testserver", ""), follow_redirects=False).status_code == 303
    assert client.get(link.replace("http://testserver", ""), follow_redirects=False).status_code == 400   # one use
    with engine(s).connect() as c:
        assert len(c.execute(select(players)).all()) == 1


@pytest.mark.parametrize("handle,msg", [("<script>x</script>", "Handles are"), ("Ruairi", "reserved"),
                                         ("r.u.a.i.r.i", "reserved"), ("ab", "Handles are")])
def test_bad_handles(site, handle, msg):
    client, _, _ = site
    r = client.post("/subscribe", data={"email": "x@example.com", "handle": handle})
    assert r.status_code == 400 and msg in r.text and "<script>x" not in r.text


def test_signup_rate_limit(site):
    client, _, _ = site
    codes = [client.post("/subscribe", data={"email": f"u{i}@example.com", "handle": f"user_{i}"}).status_code for i in range(7)]
    assert codes[:5] == [200] * 5 and codes[-1] == 429


def test_submission_rate_limit(site, s):
    client, pid, project = site
    signup(client, project)
    client.post(f"/accept/{pid}")
    texts = [client.post(f"/submit/{pid}", data={"answer": "x"}, headers={"HX-Request": "true"}).text for _ in range(12)]
    assert any("Too many attempts" in t for t in texts)


def test_unsubscribe_one_click_and_suppression(site, s):
    client, pid, project = site
    signup(client, project)
    with engine(s).connect() as c:
        me = fetch_one(c, select(players))
    url = f"/u/{me['id']}/{game.unsub_token(me['id'])}"
    assert client.post(f"/u/{me['id']}/wrongtoken").status_code == 400
    assert "Unsubscribed" in client.post(url).text
    with engine(s).begin() as c:
        assert fetch_one(c, select(players))["unsubscribed_at"]
        assert mailer.suppressed(c, "grace@example.com")
        assert cycle.announce(c, s, fetch_one(c, select(P).where(P.c.id == pid)))["sent"] == 0
        # a bulk re-import can't bring the address back
        assert game.import_subscribers(c, s, [("grace@example.com", "grace2")])["suppressed"] == 1


def test_unconfirmed_get_no_daily_email(site, s):
    client, pid, project = site
    client.post("/subscribe", data={"email": "lazy@example.com", "handle": "lazy_one", "tracks": ["logic"]})
    with engine(s).begin() as c:
        res = cycle.announce(c, s, fetch_one(c, select(P).where(P.c.id == pid)))
    assert sum(res.values()) == 0


def test_delete_account(site, s):
    client, pid, project = site
    signup(client, project)
    client.post(f"/accept/{pid}")
    client.post(f"/submit/{pid}", data={"answer": "x"})
    assert "Account deleted" in client.post("/me/delete").text
    with engine(s).connect() as c:
        assert not c.execute(select(players)).all()
        assert c.execute(select(suppression)).first().reason == "deleted"


def test_operator_page_needs_token_and_reviews(site, s, monkeypatch):
    client, _, _ = site
    assert client.get("/admin").status_code == 404                         # off without a token
    monkeypatch.setenv("PUZZLE_ADMIN_TOKEN", "op-secret")
    assert "Operator sign-in" in client.get("/admin").text
    assert client.post("/admin/login", data={"token": "nope"}).status_code == 403
    assert client.post("/admin/tick", follow_redirects=False).headers["location"].endswith("/admin")
    client.post("/admin/login", data={"token": "op-secret"})
    assert "Review queue" in client.get("/admin").text
    r = client.post("/admin/pack", data={"count": 2, "tracks": ["logic"], "difficulty": "easy", "seed": "11"})
    assert "Pack" in r.text
    pack_id = re.search(r"pk11-[0-9a-f]+", r.text).group(0)
    pdf = client.get(f"/admin/pack/{pack_id}/questions.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_bundled_data_downloads_only_allow_listed(site):
    client, _, _ = site
    assert client.get("/data/flowers/flowers.csv").status_code == 200
    assert client.get("/data/flowers/..%2F..%2Fconfig%2Fsettings.yaml").status_code == 404
    assert client.get("/data/tiny-mlp/other.bin").status_code == 404


def test_kill_switch_pauses_submissions(site, s, monkeypatch):
    client, pid, project = site
    signup(client, project)
    client.post(f"/accept/{pid}")
    from daily_puzzle import telemetry
    monkeypatch.setattr(telemetry, "status", lambda *a, **k: telemetry.Status(False, "maintenance"))
    r = client.post(f"/submit/{pid}", data={"answer": "x"}, headers={"HX-Request": "true"})
    assert "paused" in r.text


@pytest.mark.parametrize("kind", sorted(puzzles.KINDS))
def test_every_kind_renders_open_and_revealed(s, project, kind):
    """Each kind's page renders while open (no answer) and after reveal (answer, solution, code)."""
    from daily_puzzle.web import create_app
    now = datetime.now(timezone.utc)
    with engine(s).begin() as c:
        d = puzzles.make(kind, 8, "medium")
        pid = generate.store_puzzle(c, s, d, {"steps": []}, status="open", source="generated", day=now.date().isoformat())
        c.execute(P.update().where(P.c.id == pid).values(opens_at=now - timedelta(hours=1), closes_at=now + timedelta(hours=1)))
    client = TestClient(create_app(scheduler=False))
    r = client.get(f"/p/{pid}")
    assert r.status_code == 200 and d["title"] in r.text and "Worked solution" not in r.text
    with engine(s).begin() as c:
        c.execute(P.update().where(P.c.id == pid).values(status="closed", closes_at=now - timedelta(minutes=10)))
        cycle.reveal(c, fetch_one(c, select(P).where(P.c.id == pid)), now)
    r = client.get(f"/p/{pid}")
    assert r.status_code == 200 and "Worked solution" in r.text


def test_health_endpoint_matches_the_uptime_check(site):
    """scripts/uptime.py polls <app>/api/health on every FastAPI demo and expects {"ok": true}."""
    client, _, _ = site
    for path in ("/api/health", "/healthz"):
        r = client.get(path)
        assert r.status_code == 200 and r.json()["ok"] is True
