"""What leaves Lil'Helper: the Sunday email, a calendar feed for Google (or Apple) Calendar, and fridge PDFs.

Email goes through Resend when RESEND_API_KEY is set, otherwise it's written to output/outbox/ (offline, CI, demo).
The calendar is an .ics feed the household subscribes to once — we don't rebuild a calendar app.
"""
from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import os
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import telemetry
from .config import DAYS, ROOT, Household, work_root

TEMPLATES = Path(__file__).parent / "templates"
env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
DAY_NAME = dict(zip(DAYS, ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]))
JOB_LABEL = {"cook": "Cook", "dishes": "Dishes", "set_table": "Set table", "kid_assistant": "Kid helper",
             "feed_dog": "Feed the dog"}


def logo_svg() -> str:
    return (ROOT / "brand" / "icon.svg").read_text()


def week_context(h: Household, rec: dict, notes: dict | None = None) -> dict:
    """Template data from a stored week (the same JSON the API returns)."""
    plan = rec["plan"]
    week_of = dt.date.fromisoformat(plan["week_of"])
    choice = rec.get("shopping_choice") or "balanced"
    split = rec["split"][choice] if isinstance(rec.get("split"), dict) and choice in rec["split"] else rec["split"]
    days = []
    for i, d in enumerate(DAYS):
        meals = {e["meal"]: e for e in plan["entries"] if e["day"] == d}
        jobs = [a for a in rec.get("chores", []) if a["day"] == d]
        days.append({"key": d, "name": DAY_NAME[d], "date": week_of + dt.timedelta(days=i), "meals": meals,
                     "special": plan.get("special_nights", {}).get(d),
                     "jobs": [(JOB_LABEL.get(a["job"], a["job"]), a["name"]) for a in jobs],
                     "dog": [x for p in rec.get("pets", []) for x in p.get("extras", []) if x["day"] == d]})
    return {"h": h, "week_of": week_of, "days": days, "split": split, "choice": choice, "savings": rec.get("savings"),
            "pets": rec.get("pets", []), "notes": notes or {}, "logo": logo_svg(), "plan": plan,
            "household": h.info.get("name", "Your household")}


# ---------------------------------------------------------------- calendar feed
def _esc(t: str) -> str:
    return re.sub(r"([,;\\])", r"\\\1", t).replace("\n", "\\n")


def ics(h: Household, weeks: list[dict], person: str | None = None, links=None, tz: str = "America/New_York") -> str:
    """A calendar feed: dinners at each day's dinner time (who cooks, who does what), lunches from leftovers, nights
    out, batch prep and the shopping trips with their lists. With `person`, only what that person is part of.
    `links(kind, **kw)` builds signed links back to Lil'Helper (rate the meal, how much was left, change it, the list),
    which calendar apps show as tappable links in the event's notes."""
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = h.info.get("name", "Family") + (f" — {h.people[person].name}" if person in h.people else "")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Lil'Helper//Meal plan//EN", "CALSCALE:GREGORIAN",
           "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(name)} meals", f"X-WR-TIMEZONE:{tz}",
           "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]

    def event(uid: str, start: dt.datetime, minutes: int, summary: str, desc: str, url: str | None = None) -> None:
        end = start + dt.timedelta(minutes=minutes)
        out.extend(["BEGIN:VEVENT", f"UID:{uid}@lilhelper", f"DTSTAMP:{stamp}",
                    f"DTSTART;TZID={tz}:{start.strftime('%Y%m%dT%H%M%S')}",
                    f"DTEND;TZID={tz}:{end.strftime('%Y%m%dT%H%M%S')}",
                    f"SUMMARY:{_esc(summary)}", f"DESCRIPTION:{_esc(desc)}"] + ([f"URL:{url}"] if url else [])
                   + ["END:VEVENT"])

    def at(d: dt.date, hhmm: str) -> dt.datetime:
        hh, mm = map(int, hhmm.split(":"))
        return dt.datetime.combine(d, dt.time(hh, mm))

    def uid(*parts) -> str:
        return hashlib.sha1("|".join(str(p) for p in (person or "all",) + parts).encode()).hexdigest()[:16]

    def feedback_lines(wk, day, meal) -> list[str]:
        if not links:
            return []
        stars = " · ".join(f"{n}★ {links('rate', week=wk, day=day, meal=meal, value=n)}" for n in range(1, 6))
        left = " · ".join(f"{label} {links('eaten', week=wk, day=day, meal=meal, value=v)}"
                          for v, label in (("all", "All gone"), ("some_left", "Some left"), ("lots_left", "Lots left")))
        return ["", "After the meal, tap one:", f"Rate it: {stars}", f"How much was left: {left}",
                f"Change this meal: {links('change', week=wk, day=day, meal=meal)}"]

    for rec in weeks:
        plan = rec["plan"]
        wk = dt.date.fromisoformat(plan["week_of"])
        jobs = rec.get("chores", [])
        status = "" if rec.get("status") == "approved" else " (draft)"
        for e in plan["entries"]:
            eaters = e.get("eaters") or []
            if person and person not in eaters and e.get("cook") != person and not any(
                    a["person"] == person and a["day"] == e["day"] for a in jobs if e["meal"] == "dinner"):
                continue
            d = wk + dt.timedelta(days=DAYS.index(e["day"]))
            if e["meal"] == "dinner":
                mine = [JOB_LABEL.get(a["job"], a["job"]) for a in jobs if a["day"] == e["day"] and a["person"] == person]
                who = "; ".join(f"{JOB_LABEL.get(a['job'], a['job'])}: {a['name']}" for a in jobs
                                if a["day"] == e["day"] and a["job"] != "feed_dog")
                title = f"🍎 {e['name']}{status}" + (f" — you: {', '.join(mine)}" if mine else "")
                desc = [who, f"Hands-on {e['active']} min. {'; '.join(e.get('why', []))}"]
                event(uid(wk, e["day"], "dinner"), at(d, h.dinner_time(e["day"])), 45, title,
                      "\n".join(desc + feedback_lines(wk.isoformat(), e["day"], "dinner")),
                      links("app", week=wk.isoformat(), day=e["day"]) if links else None)
                if e.get("prep_day") and e["prep_day"] != e["day"]:
                    pd = wk + dt.timedelta(days=DAYS.index(e["prep_day"]))
                    event(uid(wk, e["day"], "prep"), at(pd, "15:00"), e["active"], f"Batch prep: {e['name']}",
                          f"For {DAY_NAME[e['day']]}")
            elif e["meal"] in ("lunch", "leftovers"):
                event(uid(wk, e["day"], e["meal"]), at(d, "12:00"), 30, f"🥪 {e['name']}",
                      "\n".join(["; ".join(e.get("why", []))] + feedback_lines(wk.isoformat(), e["day"], e["meal"])))
            elif e["meal"] == "breakfast":
                event(uid(wk, e["day"], "breakfast"), at(d, "08:00"), 30, f"🥣 {e['name']}",
                      "\n".join(feedback_lines(wk.isoformat(), e["day"], "breakfast")))
        for n in rec.get("eating_out") or []:
            if person and person not in n.get("eaters", []):
                continue
            d = wk + dt.timedelta(days=DAYS.index(n["day"]))
            label = "Takeout" if n["kind"] == "takeout" else "Eating out"
            pay = f"Pay with {n['card_name']}" + (f" ({n['credit_name']} applies)" if n.get("credit") else "") \
                if n.get("card") else ""
            event(uid(wk, n["day"], "out"), at(d, h.dinner_time(n["day"])), 60, f"🍽️ {label} night",
                  f"Budget ${n['budget']:.0f}. {pay}".strip())
        for night, kind in (plan.get("special_nights") or {}).items():
            if kind != "leftovers":
                continue
            d = wk + dt.timedelta(days=DAYS.index(night))
            event(uid(wk, night, "special"), at(d, h.dinner_time(night)), 30, "🍎 Leftovers night", "Eat up the fridge.")
        choice = rec.get("shopping_choice") or "balanced"
        split = rec["split"].get(choice) if isinstance(rec.get("split"), dict) else None
        for i, o in enumerate((split or {}).get("orders", [])):
            if person and o.get("who") and o["who"] != person:
                continue
            day = o.get("day") or "sun_before"
            offset = {"sun_before": -1, "sat_before": -2}.get(day, DAYS.index(day) if day in DAYS else -1)
            d = wk + dt.timedelta(days=offset)
            who = f" ({h.people[o['who']].name})" if o.get("who") in h.people else ""
            items = "\n".join(f"☐ {ln['packs']} × {ln['name']}" for ln in o["lines"][:40])
            list_link = links("list", week=wk.isoformat(), order=i) if links else None
            event(uid(wk, "shop", o.get("session") or o["store"], o["mode"]), at(d, o.get("time") or "10:00"),
                  max(10, int(o.get("minutes", 30))),
                  f"🛒 {o['store_name']} {o['mode'].replace('_', ' ')}{who}",
                  f"{len(o['lines'])} items, about ${o['total']:.2f}." + (f" Pay with {o['card_name']}." if o.get("card")
                                                                          else "")
                  + (f"\nList: {list_link}" if list_link else "") + f"\n{items}", list_link)
    out.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in out) + "\r\n"


def _fold(line: str) -> str:
    """iCalendar lines over 75 octets are folded (continuation lines start with a space)."""
    b = line.encode()
    if len(b) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        e = ch.encode()
        if len(cur) + len(e) > (75 if not parts else 74):
            parts.append(cur.decode())
            cur = b""
        cur += e
    parts.append(cur.decode())
    return "\r\n ".join(parts)


# ---------------------------------------------------------------- PDFs
def week_pdf(h: Household, rec: dict, notes: dict | None = None) -> bytes:
    from weasyprint import HTML
    html = env.get_template("week_print.html").render(**week_context(h, rec, notes))
    return HTML(string=html, base_url=str(TEMPLATES)).write_pdf()


def month_pdf(h: Household, year: int, month: int, weeks: list[dict]) -> bytes:
    from weasyprint import HTML
    dinners: dict[dt.date, str] = {}
    for rec in weeks:
        wk = dt.date.fromisoformat(rec["plan"]["week_of"])
        for e in rec["plan"]["entries"]:
            if e["meal"] == "dinner":
                dinners[wk + dt.timedelta(days=DAYS.index(e["day"]))] = e["name"]
        for night, kind in (rec["plan"].get("special_nights") or {}).items():
            dinners.setdefault(wk + dt.timedelta(days=DAYS.index(night)), kind.title() + " night")
    cal = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    html = env.get_template("month_print.html").render(
        h=h, household=h.info.get("name", "Your household"), title=dt.date(year, month, 1).strftime("%B %Y"),
        weeks=cal, month=month, dinners=dinners, logo=logo_svg())
    return HTML(string=html, base_url=str(TEMPLATES)).write_pdf()


# ---------------------------------------------------------------- email
def email_html(h: Household, rec: dict, links: dict, notes: dict | None = None) -> str:
    return env.get_template("email.html").render(**week_context(h, rec, notes), links=links)


def send_week_email(h: Household, rec: dict, links: dict, notes: dict | None = None) -> list[str]:
    telemetry.require_enabled("email")
    cfg = (h.raw.get("outputs") or {}).get("email", {})
    to = cfg.get("to", [])
    subject = f"Lil'Helper: the week of {dt.date.fromisoformat(rec['plan']['week_of']).strftime('%b %-d')}"
    html = email_html(h, rec, links, notes)
    out = []
    for addr in to:
        if os.getenv("RESEND_API_KEY"):
            import httpx
            r = httpx.post("https://api.resend.com/emails", timeout=15,
                           headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
                           json={"from": os.getenv("MAIL_FROM", "Lil'Helper <helper@example.com>"), "to": [addr],
                                 "subject": subject, "html": html})
            out.append("sent" if r.status_code < 300 else f"failed {r.status_code}")
        else:
            d = work_root() / "output" / "outbox"
            d.mkdir(parents=True, exist_ok=True)
            n = len(list(d.glob("*.html"))) + 1
            (d / f"{n:04d}-{re.sub(r'[^a-z0-9]+', '-', addr.lower())[:40]}.html").write_text(
                f"<!-- To: {addr} | Subject: {subject} -->\n" + html)
            out.append("written")
    telemetry.emit("email", records_out=len(out), detail={"recipients": len(to)})
    return out
