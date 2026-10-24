"""The households' weeks on a timer. One job, `tick`, runs every 15 minutes (APScheduler inside the API process) and,
for each household in its own time zone, does whatever is due and hasn't been done yet:

  draft      Saturday morning: draft next week (and the weeks after, up to `plan_ahead_weeks`, for forecasts and
             buy-aheads); push "next week is ready" to the adults. Nothing is bought; an adult still approves.
  email      the household's email day and time: the week's plan, jobs, savings.
  trip       an hour before each scheduled shopping trip: push the list to whoever's going.
  rate       a little after dinner: push "how was dinner?" to the people who were there (one tap in the app).
  restock    Wednesday afternoon: anything the rest of the week is short of, and the dog's food.

Each job also runs on its own from the CLI (`helper job draft|email|restock|tick`). A small `sent` table in each
household's database records what's been done, so a restart never sends anything twice.
"""
from __future__ import annotations

import datetime as dt
import os
from zoneinfo import ZoneInfo

from . import accounts, notify, outputs, store, telemetry, week
from .config import DAYS, Settings, load_household, tenant
from .prices import week_start

DUE_WINDOW = dt.timedelta(minutes=45)        # a job counts as due for this long after its time (covers restarts)


def next_monday(today: dt.date | None = None) -> dt.date:
    today = today or dt.date.today()
    return week_start(today) + dt.timedelta(weeks=1)


def _done(con, key: str) -> bool:
    con.execute("CREATE TABLE IF NOT EXISTS sent (key TEXT PRIMARY KEY, ts TEXT)")
    return con.execute("SELECT 1 FROM sent WHERE key = ?", (key,)).fetchone() is not None


def _mark(con, key: str) -> None:
    con.execute("INSERT OR IGNORE INTO sent VALUES (?, ?)", (key, store.now()))
    con.commit()


# ---------------------------------------------------------------- the jobs (one household; tenant already set)
def job_draft(today: dt.date | None = None, hid: str | None = None) -> dict:
    h = load_household()
    wk = next_monday(today)
    con = store.connect()
    existing = store.get_week(con, wk.isoformat())
    con.close()
    out = {"week_of": wk.isoformat()}
    if existing and existing.get("status") == "approved":
        out["skipped"] = "already approved"
    else:
        r = week.draft(wk, actor="scheduler")
        out.update(meals=len(r.plan.entries), flags=r.flags)
    ahead = int(h.raw.get("plan_ahead_weeks", 0) or 0)
    con = store.connect()
    for n in range(1, ahead):
        later = wk + dt.timedelta(weeks=n)
        rec = store.get_week(con, later.isoformat())
        if not rec:
            week.draft(later, ideas=False, actor="scheduler")
    con.close()
    if hid and "skipped" not in out:
        _push_adults(hid, "Next week's plan is ready", "Swap anything you like, then approve.", "lilhelper://week")
    return out


def job_email(today: dt.date | None = None) -> dict:
    """The coming week (approved or still a draft — the email says which)."""
    today = today or dt.date.today()
    wk = next_monday(today) if today.weekday() >= 5 else week_start(today)
    h = load_household()
    con = store.connect()
    rec = store.get_week(con, wk.isoformat())
    con.close()
    if not rec:
        return {"week_of": wk.isoformat(), "skipped": "no plan"}
    return {"week_of": wk.isoformat(), "sent": outputs.send_week_email(h, rec, {"app": "lilhelper://week"})}


def job_restock(today: dt.date | None = None) -> dict:
    """Mid-week: what the rest of this week's approved plan needs that the pantry is short of."""
    from . import catalog
    today = today or dt.date.today()
    wk = week_start(today)
    h = load_household()
    c = catalog.for_household(h)
    con = store.connect()
    rec = store.get_week(con, wk.isoformat())
    pantry = store.pantry(con)
    con.close()
    if not rec or rec.get("status") != "approved":
        return {"week_of": wk.isoformat(), "skipped": "no approved plan"}
    # Approving a week already took the whole week's planned use out of the pantry, so what's left is the projected
    # stock at the end of the week. Anything below zero is short; the dog's food should keep a 3-day buffer.
    used = {i for e in rec["plan"]["entries"] if DAYS.index(e["day"]) >= today.weekday() and e.get("kind", "cook") == "cook"
            for i in (c.recipes[e["recipe"]].ing if e["recipe"] in c.recipes else {})}
    short = {i: round(-q, 2) for i, q in pantry.items() if q < -0.01 and i in used}
    for p in h.pets.values():
        food = p.food["ingredient"]
        if pantry.get(food, 0) < p.food["cups_per_day"] * 3:
            short[food] = round(p.food["cups_per_day"] * 3 - pantry.get(food, 0), 1)
    telemetry.emit("restock_check", records_out=len(short))
    return {"week_of": wk.isoformat(), "short": short}


def _push_adults(hid: str, title: str, body: str, link: str) -> None:
    con = accounts.connect()
    uids = [m["user_id"] for m in accounts.members(con, hid) if m["role"] in ("admin", "adult")]
    con.close()
    notify.send(hid, title, body, to_users=uids, link=link, kind="plan")


def _users_for(hid: str, people: list[str]) -> list[str]:
    con = accounts.connect()
    uids = [m["user_id"] for m in accounts.members(con, hid) if m["person_id"] in people]
    con.close()
    return uids


def tick(now: dt.datetime | None = None, hid: str | None = None) -> list[str]:
    """Everything due for the current household at `now` (aware datetime). Returns what was done."""
    h = load_household()
    tz = ZoneInfo(h.info.get("timezone", "America/New_York"))
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(tz)
    today = now.date()
    s = Settings.load().get("schedule", {})
    con = store.connect()
    done = []

    def due(when: dt.datetime) -> bool:
        return when <= now < when + DUE_WINDOW

    def at(d: dt.date, hhmm: str) -> dt.datetime:
        hh, mm = map(int, str(hhmm).split(":"))
        return dt.datetime.combine(d, dt.time(hh, mm), tz)

    # Saturday draft
    if DAYS[today.weekday()] == s.get("draft_day", "sat") and due(at(today, f"{int(s.get('draft_hour', 7)):02d}:00")):
        key = f"draft:{next_monday(today)}"
        if not _done(con, key):
            job_draft(today, hid)
            _mark(con, key)
            done.append(key)
    # the weekly email
    em = (h.raw.get("outputs") or {}).get("email") or {}
    if em.get("to") and DAYS[today.weekday()] == em.get("day", "sun") and due(at(today, em.get("time", "08:00"))):
        key = f"email:{today}"
        if not _done(con, key):
            job_email(today)
            _mark(con, key)
            done.append(key)
    # restock check
    if DAYS[today.weekday()] == s.get("restock_day", "wed") and due(at(today, f"{int(s.get('restock_hour', 15)):02d}:00")):
        key = f"restock:{week_start(today)}"
        if not _done(con, key):
            job_restock(today)
            _mark(con, key)
            done.append(key)
    for wk in (week_start(today), week_start(today) + dt.timedelta(weeks=1)):
        rec = store.get_week(con, wk.isoformat())
        if not rec or rec.get("status") != "approved":
            continue
        # an hour before each shopping trip: the list, to whoever's going (everyone adult if nobody is named)
        choice = rec.get("shopping_choice") or "balanced"
        for o in rec["split"][choice]["orders"]:
            if not o.get("day") or not o.get("time"):
                continue
            off = {"sun_before": -1, "sat_before": -2}.get(o["day"], DAYS.index(o["day"]) if o["day"] in DAYS else 0)
            trip = at(wk + dt.timedelta(days=off), o["time"])
            key = f"trip:{wk}:{o.get('session')}"
            if due(trip - dt.timedelta(hours=1)) and not _done(con, key):
                if hid:
                    uids = _users_for(hid, [o["who"]]) if o.get("who") else None
                    notify.send(hid, f"Shopping at {o['store_name']} in an hour",
                                f"{len(o['lines'])} items on the list.", to_users=uids, link="lilhelper://shopping",
                                kind="trip")
                _mark(con, key)
                done.append(key)
        # a little after dinner: how was it?
        if wk == week_start(today):
            day = DAYS[today.weekday()]
            e = next((e for e in rec["plan"]["entries"] if e["day"] == day and e["meal"] == "dinner"), None)
            if e and due(at(today, h.dinner_time(day)) + dt.timedelta(minutes=75)):
                key = f"rate:{wk}:{day}"
                if not _done(con, key):
                    if hid:
                        notify.send(hid, "How was dinner?", f"{e['name']}: one tap to rate it and say what's left.",
                                    to_users=_users_for(hid, e.get("eaters") or []),
                                    link=f"lilhelper://meals?day={day}", kind="rate")
                    _mark(con, key)
                    done.append(key)
    con.close()
    return done


def tick_all(now: dt.datetime | None = None) -> dict[str, list[str]]:
    """Run `tick` for every household on this server (or the single local one if there are no accounts)."""
    con = accounts.connect()
    hs = accounts.households(con)
    out = {"billing": billing_tick(con, now)}
    con.close()
    if not hs:
        out["local"] = tick(now)
        return out
    for row in hs:
        with tenant(row["id"]):
            try:
                out[row["id"]] = tick(now, row["id"])
            except Exception as e:                      # one household's problem never stops the others
                out[row["id"]] = [f"error: {type(e).__name__}"]
    return out


def billing_tick(con, now: dt.datetime | None = None) -> list[str]:
    """Renew subscriptions that are due, and email anyone whose price goes up at a renewal in the next 30 days."""
    import html
    from . import billing, outputs
    from .config import data_root
    at = now.astimezone(dt.timezone.utc) if now and now.tzinfo else (now.replace(tzinfo=dt.timezone.utc) if now else None)
    done = [f"renewed {r['id']}" for r in billing.renew_due(con, at)]
    for s in billing.notices_due(con, at):
        if s["who"]["email"]:
            body = (f"<p>Your {html.escape(billing.plans.TIERS[s['plan']]['label'])} plan for "
                    f"{html.escape(s['who']['name'])} renews on {s['renews'][:10]} at "
                    f"${s['next_price']:.2f} ({s['interval']}), up from ${float(s['price']):.2f}.</p>"
                    "<p>You can change or cancel it any time before then in the app (More, then Plans).</p>")
            outputs.send_mail(s["who"]["email"], "Your DinnerPeace plan's price at renewal", body, "price-notice",
                              data_root() / "outbox")
        billing.mark_noticed(con, s["id"], s["renews"])
        done.append(f"noticed {s['id']}")
    return done


def start():
    """Start the background scheduler (the API calls this when HELPER_SCHEDULER=1)."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(tick_all, IntervalTrigger(minutes=int(os.getenv("HELPER_TICK_MINUTES", "15"))), id="tick",
                  replace_existing=True, next_run_time=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=30))
    sched.start()
    return sched
