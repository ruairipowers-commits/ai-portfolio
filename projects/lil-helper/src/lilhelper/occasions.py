"""Special occasions: birthdays (from people's profiles), anniversaries and the household's own dates, and holidays.

An occasion on a day shapes that day's plan: a set recipe if the household chose one ("make John's favourite" →
his favourite), otherwise a bonus for the birthday person's favourites or recipes with the occasion's tags ("festive"
for Thanksgiving, "party" for a pizza night). On someone's birthday they have no jobs.

Holidays are the US calendar by default (the household can turn any off, or all of them, under occasions).
"""
from __future__ import annotations

import datetime as dt

# id → (name, rule, tags). Rules: "MM-DD" fixed, or (month, weekday 0=Mon, n) for the nth weekday (n=-1: last).
HOLIDAYS = {
    "new_years_day": ("New Year's Day", "01-01", ["festive"]),
    "super_bowl": ("Super Bowl Sunday", (2, 6, 2), ["party"]),
    "valentines": ("Valentine's Day", "02-14", ["special"]),
    "st_patricks": ("St Patrick's Day", "03-17", ["festive"]),
    "easter": ("Easter", "easter", ["festive"]),
    "mothers_day": ("Mother's Day", (5, 6, 2), ["special"]),
    "memorial_day": ("Memorial Day", (5, 0, -1), ["grill"]),
    "fathers_day": ("Father's Day", (6, 6, 3), ["special", "grill"]),
    "july_4": ("Fourth of July", "07-04", ["grill", "party"]),
    "labor_day": ("Labor Day", (9, 0, 1), ["grill"]),
    "halloween": ("Halloween", "10-31", ["party", "kid_friendly"]),
    "thanksgiving": ("Thanksgiving", (11, 3, 4), ["festive"]),
    "christmas_eve": ("Christmas Eve", "12-24", ["festive"]),
    "christmas": ("Christmas Day", "12-25", ["festive"]),
    "new_years_eve": ("New Year's Eve", "12-31", ["party"]),
}


def easter(year: int) -> dt.date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return dt.date(year, month, day)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    if n > 0:
        d = dt.date(year, month, 1)
        d += dt.timedelta(days=(weekday - d.weekday()) % 7)
        return d + dt.timedelta(weeks=n - 1)
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def holiday_date(hid: str, year: int) -> dt.date:
    rule = HOLIDAYS[hid][1]
    if rule == "easter":
        return easter(year)
    if isinstance(rule, tuple):
        return nth_weekday(year, *rule)
    mm, dd = map(int, rule.split("-"))
    return dt.date(year, mm, dd)


def yearly_on(date_str: str, day: dt.date) -> bool:
    """'1990-03-07' or '03-07' falls on `day` (any year); 29 February is kept on 28 February in other years."""
    parts = date_str.split("-")
    mm, dd = int(parts[-2]), int(parts[-1])
    if (mm, dd) == (2, 29) and not _leap(day.year):
        return (day.month, day.day) == (2, 28)
    return (day.month, day.day) == (mm, dd)


def _leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def on_day(raw: dict, people: dict, day: dt.date) -> list[dict]:
    """Every occasion on a date: [{id, name, kind, people, recipe, tags, guests, meal}]."""
    out = []
    for p in people.values():
        if p.birthday and yearly_on(p.birthday, day):
            out.append({"id": f"birthday:{p.id}", "name": f"{p.name}'s birthday", "kind": "birthday",
                        "people": [p.id], "recipe": None, "tags": ["festive"], "guests": 0, "meal": "dinner"})
    for i, o in enumerate(raw.get("occasions") or []):
        d = str(o.get("date") or "")
        if not d:
            continue
        hit = (d == day.isoformat()) if len(d) == 10 and not o.get("yearly", True) else yearly_on(d, day)
        if hit:
            out.append({"id": o.get("id") or f"occasion:{i}", "name": o.get("name", "Special occasion"),
                        "kind": o.get("kind", "custom"), "people": list(o.get("people") or []),
                        "recipe": o.get("recipe"), "tags": list(o.get("tags") or []), "guests": int(o.get("guests") or 0),
                        "meal": o.get("meal", "dinner")})
    hol = raw.get("holidays", "us")
    off = set((raw.get("holidays_off") or []))
    if hol:
        for hid, (name, _, tags) in HOLIDAYS.items():
            if hid in off:
                continue
            if holiday_date(hid, day.year) == day:
                out.append({"id": f"holiday:{hid}", "name": name, "kind": "holiday", "people": [], "recipe": None,
                            "tags": tags, "guests": 0, "meal": "dinner"})
    return out


def upcoming(raw: dict, people: dict, start: dt.date, days: int = 60) -> list[dict]:
    out = []
    for n in range(days):
        d = start + dt.timedelta(days=n)
        for o in on_day(raw, people, d):
            out.append({**o, "date": d.isoformat()})
    return out
