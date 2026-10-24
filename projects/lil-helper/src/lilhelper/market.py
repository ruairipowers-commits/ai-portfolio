"""Finding each other: chefs near a household, households near a chef looking for one, and requests to meet.

What's public is deliberately little. A chef's listing shows their name, business, bio, cuisines, rates and town.
A household's listing shows its town, roughly how far away it is, what it's willing to pay, how many people and how
many children (never names or ages), which allergens the cooking has to avoid, and a note the family wrote. Exact
addresses and emails are shared only when the other side accepts a request to meet. Only chefs on Dinner Peace Pro
are listed and can send requests; any household can list itself and search for free.
"""
from __future__ import annotations

import datetime as dt
import json
import secrets

from . import geo, plans

SCHEMA = """
CREATE TABLE IF NOT EXISTS chef_profiles (uid TEXT PRIMARY KEY, display_name TEXT, business TEXT, bio TEXT,
    cuisines TEXT, rate_per_visit REAL, rate_hourly REAL, radius_miles INTEGER DEFAULT 20, address TEXT,
    listed INTEGER DEFAULT 0, accepting INTEGER DEFAULT 1, updated TEXT);
CREATE TABLE IF NOT EXISTS household_listings (hid TEXT PRIMARY KEY, open INTEGER DEFAULT 0, budget_per_week REAL,
    budget_per_visit REAL, visits_per_week INTEGER, cuisines TEXT, note TEXT, start TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS meet_requests (id TEXT PRIMARY KEY, from_kind TEXT, chef_uid TEXT, hid TEXT, message TEXT,
    proposed TEXT, status TEXT DEFAULT 'pending', created TEXT, responded TEXT, by_uid TEXT);
"""
MAX_PENDING = 10          # open requests a chef or household can have out at once
CUISINES = ("american", "italian", "mexican", "mediterranean", "asian", "indian", "french", "southern", "vegetarian",
            "vegan", "gluten_free", "kid_friendly", "meal_prep", "healthy", "comfort")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def setup(con) -> None:
    con.executescript(SCHEMA)


def _cuisines(xs) -> list[str]:
    bad = [x for x in xs or [] if x not in CUISINES]
    if bad:
        raise ValueError(f"unknown cuisines {bad}")
    return list(dict.fromkeys(xs or []))


# ---------------------------------------------------------------- chef profiles
def save_profile(con, uid: str, **f) -> dict:
    setup(con)
    cur = profile(con, uid) or {}
    cur.update({k: v for k, v in f.items() if v is not None})
    if cur.get("rate_per_visit") is not None and not 0 <= float(cur["rate_per_visit"]) <= 5000:
        raise ValueError("a rate per visit between $0 and $5,000")
    if cur.get("rate_hourly") is not None and not 0 <= float(cur["rate_hourly"]) <= 1000:
        raise ValueError("an hourly rate between $0 and $1,000")
    if not 1 <= int(cur.get("radius_miles") or 20) <= 100:
        raise ValueError("travel up to 1–100 miles")
    con.execute("INSERT OR REPLACE INTO chef_profiles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (uid, (cur.get("display_name") or "")[:60], (cur.get("business") or "")[:60], (cur.get("bio") or "")[:600],
                 json.dumps(_cuisines(cur.get("cuisines"))), cur.get("rate_per_visit"), cur.get("rate_hourly"),
                 int(cur.get("radius_miles") or 20), json.dumps(cur.get("address") or {}), int(bool(cur.get("listed"))),
                 int(cur.get("accepting", True) is not False), now()))
    con.commit()
    return profile(con, uid)


def profile(con, uid: str) -> dict | None:
    setup(con)
    r = con.execute("SELECT * FROM chef_profiles WHERE uid = ?", (uid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["cuisines"], d["address"] = json.loads(d["cuisines"] or "[]"), json.loads(d["address"] or "{}")
    d["listed"], d["accepting"] = bool(d["listed"]), bool(d["accepting"])
    return d


def _public_chef(con, p: dict, miles: float | None) -> dict:
    plan = plans.chef_plan(con, p["uid"])
    cap = plans.client_limit(plan)
    n = len(plans.chef_client_ids(con, p["uid"]))
    return {"uid": p["uid"], "name": p["display_name"], "business": p["business"], "bio": p["bio"],
            "cuisines": p["cuisines"], "rate_per_visit": p["rate_per_visit"], "rate_hourly": p["rate_hourly"],
            "place": geo.place(p["address"]), "miles": round(miles) if miles is not None else None,
            "radius_miles": p["radius_miles"], "full": cap is not None and n >= cap, "clients": n}


def search_chefs(con, home: dict, radius: float = 25, cuisine: str | None = None) -> list[dict]:
    """Listed, accepting chefs on a Pro plan who travel as far as this household, nearest first."""
    setup(con)
    out = []
    for r in con.execute("SELECT uid FROM chef_profiles WHERE listed = 1 AND accepting = 1"):
        p = profile(con, r["uid"])
        if plans.chef_plan(con, p["uid"]) == "none":
            continue
        d = geo.distance(home, p["address"])
        if d is None or d > min(radius, p["radius_miles"]):
            continue
        if cuisine and cuisine not in p["cuisines"]:
            continue
        out.append(_public_chef(con, p, d))
    return sorted(out, key=lambda x: (x["full"], x["miles"] if x["miles"] is not None else 999))


# ---------------------------------------------------------------- household listings
def save_listing(con, hid: str, **f) -> dict:
    setup(con)
    cur = listing(con, hid) or {}
    cur.update({k: v for k, v in f.items() if v is not None})
    for k, hi in (("budget_per_week", 10000), ("budget_per_visit", 5000)):
        if cur.get(k) is not None and not 0 <= float(cur[k]) <= hi:
            raise ValueError(f"{k.replace('_', ' ')} between $0 and ${hi:,}")
    if cur.get("visits_per_week") is not None and not 1 <= int(cur["visits_per_week"]) <= 7:
        raise ValueError("1 to 7 visits a week")
    con.execute("INSERT OR REPLACE INTO household_listings VALUES (?,?,?,?,?,?,?,?,?)",
                (hid, int(bool(cur.get("open"))), cur.get("budget_per_week"), cur.get("budget_per_visit"),
                 cur.get("visits_per_week"), json.dumps(_cuisines(cur.get("cuisines"))), (cur.get("note") or "")[:600],
                 cur.get("start"), now()))
    con.commit()
    return listing(con, hid)


def listing(con, hid: str) -> dict | None:
    setup(con)
    r = con.execute("SELECT * FROM household_listings WHERE hid = ?", (hid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["cuisines"], d["open"] = json.loads(d["cuisines"] or "[]"), bool(d["open"])
    return d


def public_household(h, lst: dict, miles: float | None) -> dict:
    """What a chef sees before the family accepts: no names, no ages, no street."""
    people = list(h.people.values())
    return {"place": geo.place(h.raw.get("address")), "miles": round(miles) if miles is not None else None,
            "people": len(people), "kids": sum(p.is_kid for p in people),
            "allergens": sorted(h.everyone_allergies()),
            "diets": sorted({d for p in people for d in p.diet}),
            "budget_per_week": lst["budget_per_week"], "budget_per_visit": lst["budget_per_visit"],
            "visits_per_week": lst["visits_per_week"], "cuisines": lst["cuisines"], "note": lst["note"],
            "start": lst["start"]}


# ---------------------------------------------------------------- requests to meet
def request(con, from_kind: str, chef_uid: str, hid: str, by_uid: str, message: str, proposed: str = "") -> dict:
    setup(con)
    if from_kind not in ("chef", "household"):
        raise ValueError("bad sender")
    mine = con.execute("SELECT COUNT(*) AS n FROM meet_requests WHERE status = 'pending' AND by_uid = ?",
                       (by_uid,)).fetchone()["n"]
    if mine >= MAX_PENDING:
        raise ValueError(f"you have {MAX_PENDING} requests waiting for an answer; wait for some replies first")
    dup = con.execute("SELECT id FROM meet_requests WHERE chef_uid = ? AND hid = ? AND status = 'pending'",
                      (chef_uid, hid)).fetchone()
    if dup:
        raise ValueError("there's already a request waiting between you")
    rid = secrets.token_hex(6)
    con.execute("INSERT INTO meet_requests (id, from_kind, chef_uid, hid, message, proposed, status, created, by_uid) "
                "VALUES (?,?,?,?,?,?,?,?,?)", (rid, from_kind, chef_uid, hid, message[:600], proposed[:120], "pending",
                                               now(), by_uid))
    con.commit()
    return get_request(con, rid)


def get_request(con, rid: str) -> dict:
    r = con.execute("SELECT * FROM meet_requests WHERE id = ?", (rid,)).fetchone()
    if not r:
        raise ValueError("no such request")
    return dict(r)


def respond(con, rid: str, accept: bool, by_uid: str) -> dict:
    r = get_request(con, rid)
    if r["status"] != "pending":
        raise ValueError("that request has already been answered")
    con.execute("UPDATE meet_requests SET status = ?, responded = ? WHERE id = ?",
                ("accepted" if accept else "declined", now(), rid))
    con.commit()
    return get_request(con, rid)


def withdraw(con, rid: str, by_uid: str) -> None:
    r = get_request(con, rid)
    if r["by_uid"] != by_uid or r["status"] != "pending":
        raise ValueError("only a waiting request you sent can be withdrawn")
    con.execute("UPDATE meet_requests SET status = 'withdrawn', responded = ? WHERE id = ?", (now(), rid))
    con.commit()


def for_chef(con, uid: str) -> list[dict]:
    setup(con)
    return [dict(r) for r in con.execute("SELECT * FROM meet_requests WHERE chef_uid = ? ORDER BY created DESC LIMIT 100",
                                         (uid,))]


def for_household(con, hid: str) -> list[dict]:
    setup(con)
    return [dict(r) for r in con.execute("SELECT * FROM meet_requests WHERE hid = ? ORDER BY created DESC LIMIT 100",
                                         (hid,))]
