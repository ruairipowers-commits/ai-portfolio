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


def ics(h: Household, weeks: list[dict], dinner_time: str = "18:00") -> str:
    """One VCALENDAR with dinners (who cooks / does dishes), batch-prep reminders and the shopping run."""
    hh, mm = map(int, dinner_time.split(":"))
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Lil'Helper//Meal plan//EN", "CALSCALE:GREGORIAN",
           "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(h.info.get('name', 'Family'))} meals", "X-WR-TIMEZONE:America/New_York"]

    def event(uid: str, start: dt.datetime, minutes: int, summary: str, desc: str) -> None:
        end = start + dt.timedelta(minutes=minutes)
        out.extend(["BEGIN:VEVENT", f"UID:{uid}@lilhelper", f"DTSTAMP:{stamp}",
                    f"DTSTART;TZID=America/New_York:{start.strftime('%Y%m%dT%H%M%S')}",
                    f"DTEND;TZID=America/New_York:{end.strftime('%Y%m%dT%H%M%S')}",
                    f"SUMMARY:{_esc(summary)}", f"DESCRIPTION:{_esc(desc)}", "END:VEVENT"])

    for rec in weeks:
        plan = rec["plan"]
        wk = dt.date.fromisoformat(plan["week_of"])
        jobs = rec.get("chores", [])
        for e in plan["entries"]:
            if e["meal"] != "dinner":
                continue
            d = wk + dt.timedelta(days=DAYS.index(e["day"]))
            who = "; ".join(f"{JOB_LABEL.get(a['job'], a['job'])}: {a['name']}" for a in jobs if a["day"] == e["day"]
                            and a["job"] != "feed_dog")
            event(hashlib.sha1(f"{wk}{e['day']}dinner".encode()).hexdigest()[:16],
                  dt.datetime.combine(d, dt.time(hh, mm)), 45, f"🍎 {e['name']}",
                  f"{who}\nHands-on {e['active']} min. {'; '.join(e.get('why', []))}")
            if e.get("prep_day") and e["prep_day"] != e["day"]:
                pd = wk + dt.timedelta(days=DAYS.index(e["prep_day"]))
                event(hashlib.sha1(f"{wk}{e['day']}prep".encode()).hexdigest()[:16],
                      dt.datetime.combine(pd, dt.time(15, 0)), e["active"], f"Batch prep: {e['name']}",
                      f"For {DAY_NAME[e['day']]}")
        for night, kind in (plan.get("special_nights") or {}).items():
            d = wk + dt.timedelta(days=DAYS.index(night))
            event(hashlib.sha1(f"{wk}{night}special".encode()).hexdigest()[:16],
                  dt.datetime.combine(d, dt.time(hh, mm)), 30, f"🍎 {kind.title()} night", "Eat up the fridge.")
        choice = rec.get("shopping_choice") or "balanced"
        split = rec["split"].get(choice) if isinstance(rec.get("split"), dict) else None
        if split and split.get("orders"):
            shop_day = wk - dt.timedelta(days=1)                       # Sunday before the week
            stores = ", ".join(f"{o['store_name']} ({o['mode'].replace('_', ' ')})" for o in split["orders"])
            event(hashlib.sha1(f"{wk}shop".encode()).hexdigest()[:16], dt.datetime.combine(shop_day, dt.time(10, 0)),
                  max(15, split["minutes"]), "🛒 Groceries", f"{stores}. Total about ${split['total']:.2f}.")
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


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
