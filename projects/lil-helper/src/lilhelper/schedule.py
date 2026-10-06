"""The household's week on a timer (APScheduler inside the API process; every job also runs from the CLI).

  Saturday  draft next week's plan (nothing is bought; an adult still approves it in the app)
  Sunday    the weekly email at the household's chosen time (plan, jobs, savings; links open the app)
  Wednesday restock check: anything the rest of the week needs that the pantry is short of, plus the dog's food

Times come from the household file (`outputs.email`) and `schedule.*` in settings; the time zone is the household's.
"""
from __future__ import annotations

import datetime as dt
import os

from . import outputs, store, telemetry, week
from .config import DAYS, Settings, load_household
from .prices import week_start


def next_monday(today: dt.date | None = None) -> dt.date:
    today = today or dt.date.today()
    return week_start(today) + dt.timedelta(weeks=1)


def job_draft(today: dt.date | None = None) -> dict:
    wk = next_monday(today)
    con = store.connect()
    existing = store.get_week(con, wk.isoformat())
    con.close()
    if existing and existing.get("status") == "approved":
        return {"week_of": wk.isoformat(), "skipped": "already approved"}
    r = week.draft(wk, actor="scheduler")
    return {"week_of": wk.isoformat(), "meals": len(r.plan.entries), "flags": r.flags}


def job_email(today: dt.date | None = None) -> dict:
    """Sunday: the coming week (approved or still a draft — the email says which)."""
    wk = next_monday(today) if (today or dt.date.today()).weekday() == 6 else week_start(today or dt.date.today())
    h = load_household()
    con = store.connect()
    rec = store.get_week(con, wk.isoformat())
    con.close()
    if not rec:
        return {"week_of": wk.isoformat(), "skipped": "no plan"}
    link = os.getenv("HELPER_APP_LINK", "lilhelper://")
    return {"week_of": wk.isoformat(), "sent": outputs.send_week_email(h, rec, {"app": link})}


def job_restock(today: dt.date | None = None) -> dict:
    """Mid-week: what the rest of this week's approved plan needs that the pantry is short of."""
    from . import catalog
    today = today or dt.date.today()
    wk = week_start(today)
    h = load_household()
    c = catalog.get(h.info.get("region", "northeast-us"))
    con = store.connect()
    rec = store.get_week(con, wk.isoformat())
    pantry = store.pantry(con)
    con.close()
    if not rec or rec.get("status") != "approved":
        return {"week_of": wk.isoformat(), "skipped": "no approved plan"}
    # Approving a week already took the whole week's planned use out of the pantry, so what's left is the projected
    # stock at the end of the week. Anything below zero is short; the dog's food should keep a 3-day buffer.
    used = {i for e in rec["plan"]["entries"] if DAYS.index(e["day"]) >= today.weekday()
            for i in (c.recipes[e["recipe"]].ing if e["recipe"] in c.recipes else {})}
    short = {i: round(-q, 2) for i, q in pantry.items() if q < -0.01 and i in used}
    for p in h.pets.values():
        food = p.food["ingredient"]
        if pantry.get(food, 0) < p.food["cups_per_day"] * 3:
            short[food] = round(p.food["cups_per_day"] * 3 - pantry.get(food, 0), 1)
    telemetry.emit("restock_check", records_out=len(short))
    return {"week_of": wk.isoformat(), "short": short}


def start(s: Settings | None = None):
    """Start the background scheduler (the API calls this when HELPER_SCHEDULER=1)."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    s = s or Settings.load()
    h = load_household()
    cfg = s.get("schedule", {})
    tz = cfg.get("timezone", "America/New_York")
    email = (h.raw.get("outputs") or {}).get("email", {})
    eh, em = map(int, str(email.get("time", "08:00")).split(":"))
    sched = BackgroundScheduler(timezone=tz)
    sched.add_job(job_draft, CronTrigger(day_of_week=cfg.get("draft_day", "sat"), hour=cfg.get("draft_hour", 7), timezone=tz),
                  id="draft", replace_existing=True)
    sched.add_job(job_email, CronTrigger(day_of_week=email.get("day", "sun"), hour=eh, minute=em, timezone=tz),
                  id="email", replace_existing=True)
    sched.add_job(job_restock, CronTrigger(day_of_week=cfg.get("restock_day", "wed"), hour=cfg.get("restock_hour", 15),
                                           timezone=tz), id="restock", replace_existing=True)
    sched.start()
    return sched
