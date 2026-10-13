"""The households' timer: Saturday draft, Sunday email, Wednesday restock, trip reminders and "how was dinner?"
pushes, each done once per household in its own time zone (HITL-02: drafts only; an adult still approves)."""
import datetime as dt
import json
from zoneinfo import ZoneInfo

from lilhelper import accounts, schedule, store, week
from lilhelper.config import tenant, work_root

NY = ZoneInfo("America/New_York")


def test_draft_email_restock(workspace):
    sat = dt.date(2026, 10, 10)
    r = schedule.job_draft(sat)
    assert r["week_of"] == "2026-10-12" and r["meals"] > 0
    week.approve(dt.date(2026, 10, 12), "dana", 80)
    assert schedule.job_draft(sat)["skipped"] == "already approved"     # never overwrites an approved week
    assert schedule.job_email(dt.date(2026, 10, 11))["sent"] == ["written", "written"]
    assert schedule.job_restock(dt.date(2026, 10, 14))["short"] == {}   # just shopped: nothing short
    con = store.connect()
    con.execute("UPDATE pantry SET qty = 1 WHERE ingredient = 'dog_food'")
    con.commit()
    assert "dog_food" in schedule.job_restock(dt.date(2026, 10, 14))["short"]


def test_scheduler_runs_one_tick_job():
    s = schedule.start()
    try:
        assert {j.id for j in s.get_jobs()} == {"tick"}
    finally:
        s.shutdown()


def _pushes(hid):
    with tenant(hid):
        d = work_root() / "output" / "outbox"
        return [m for f in sorted(d.glob("push-*.json")) for m in json.loads(f.read_text())] if d.exists() else []


def test_tick_drafts_pushes_and_never_repeats(server):
    H, hid = server.household()
    tok = "ExponentPushToken[abcdefghijklmnop]"
    assert server.client.post("/api/devices", headers=H, json={"token": tok, "platform": "ios"}).status_code == 200
    sat = dt.datetime(2026, 10, 17, 7, 10, tzinfo=NY)
    assert schedule.tick_all(sat)[hid] == ["draft:2026-10-19"]
    assert schedule.tick_all(sat + dt.timedelta(minutes=15))[hid] == []        # done once, even inside the window
    p = _pushes(hid)
    assert len(p) == 1 and p[0]["to"] == tok and p[0]["data"]["url"] == "lilhelper://week"
    with tenant(hid):
        rec = store.get_week(store.connect(), "2026-10-19")
        assert rec["status"] == "draft"                                         # drafted, not approved
        week.approve(dt.date(2026, 10, 19), "ruairi", 60)
    # Monday, 75 minutes after dinner at 18:00
    done = schedule.tick_all(dt.datetime(2026, 10, 19, 19, 20, tzinfo=NY))[hid]
    assert done == ["rate:2026-10-19:mon"]
    rate = _pushes(hid)[-1]
    assert rate["title"] == "How was dinner?" and "?day=mon" in rate["data"]["url"]
    # nothing about money or children in a push
    assert all("$" not in m["body"] for m in _pushes(hid))


def test_one_household_failing_doesnt_stop_the_others(server, monkeypatch):
    _, h1 = server.household("one@example.com", "One", "House one")
    _, h2 = server.household("two@example.com", "Two", "House two")
    real = schedule.tick

    def flaky(now=None, hid=None):
        if hid == h1:
            raise ValueError("bad settings")
        return real(now, hid)

    monkeypatch.setattr(schedule, "tick", flaky)
    out = schedule.tick_all(dt.datetime(2026, 10, 17, 7, 5, tzinfo=NY))
    assert out[h1] == ["error: ValueError"] and out[h2] == ["draft:2026-10-19"]
