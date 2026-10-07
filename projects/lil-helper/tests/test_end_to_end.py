"""Offline end to end (NFR-6): the CLI's simulation of several weeks — draft, approve, feedback, learn — with the
mock model and the fictional family. Also renders the printouts and the calendar feed."""
import datetime as dt
import time

from lilhelper import outputs, simulate, store
from lilhelper.config import load_household


def test_four_weeks_offline(workspace):
    t0 = time.perf_counter()
    res = simulate.run(4, start=dt.date(2026, 10, 5), fresh=True)
    s = res["summary"]
    assert time.perf_counter() - t0 < 120
    assert s["unsafe_meals"] == 0
    assert s["dollars_saved_total"] > 0 and s["minutes_saved_per_week"] > 0
    assert s["adult_load_gap"] <= 3
    assert all(w["status"] in ("OPTIMAL", "FEASIBLE") for w in res["weeks"])
    con = store.connect()
    weeks = [store.get_week(con, r["week_of"]) for r in con.execute("SELECT week_of FROM weeks ORDER BY week_of")]
    h = load_household()
    assert outputs.week_pdf(h, weeks[0])[:4] == b"%PDF"
    assert outputs.month_pdf(h, 2026, 10, weeks)[:4] == b"%PDF"
    ics = outputs.ics(h, weeks)
    assert ics.count("BEGIN:VEVENT") >= 4 * 6
    sent = outputs.send_week_email(h, weeks[0], {})
    assert sent == ["written", "written"]


def test_simulation_is_reproducible(workspace):
    a = simulate.run(2, fresh=True)["summary"]
    b = simulate.run(2, fresh=True)["summary"]
    for k in ("dollars_saved_total", "avg_rating", "food_left_last_week", "job_load_total"):
        assert a[k] == b[k]
