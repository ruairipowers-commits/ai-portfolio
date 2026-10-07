"""The weekly timer: Saturday draft, Sunday email, Wednesday restock check."""
import datetime as dt

from lilhelper import schedule, store, week


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


def test_scheduler_registers_three_jobs():
    s = schedule.start()
    try:
        assert {j.id for j in s.get_jobs()} == {"draft", "email", "restock"}
    finally:
        s.shutdown()
