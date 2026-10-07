"""Offline end to end: sample → load → analytics → summaries → eval gate."""
from launchtracker import analytics as A
from launchtracker import evals, forecast, orbit, summaries


def test_end_to_end(env):
    s, con = env
    h = A.headline(con, s)
    assert h["upcoming"] == 12 and h["in_orbit"] > 1000
    up = A.upcoming(con, s)
    assert up[0]["seconds_to_go"] > 0
    assert summaries.mission(con, s, up[0]["launch_id"]).accepted
    assert summaries.digest(con, s).accepted
    fc = forecast.project(con, s)
    assert fc["projection"] and fc["backtest"]["mape_pct"] < 50
    assert orbit.crowding(con, s)["busiest_shell_km"] == 550
    rep = evals.run_eval(con, s)
    assert rep["passed"], rep["failures"]
