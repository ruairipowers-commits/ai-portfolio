"""A fictional personal chef with three client households, for trying Dinner Peace Pro (`helper chef-demo`).

Every name here is made up. Visits are set relative to today so the cockpit always has kitchens to show.
"""
from __future__ import annotations

import datetime as dt

from . import accounts, plans, pro, store
from .config import DAYS, load_household, save_household, tenant

FAMILIES = [
    {"name": "Miller family", "contact": "Jordan Miller", "email": "jordan.miller@example.com",
     "people": {"sam": {"name": "Sam", "age_band": "adult", "likes": ["salmon_rice_broccoli"]},
                "ava": {"name": "Ava", "age_band": "kid", "age": 9, "allergies": ["tree_nut"], "dislikes": ["mushrooms"]},
                "leo": {"name": "Leo", "age_band": "kid", "age": 6}},
     "brands": {"milk": {"prefer": "Horizon Organic"}}, "billing": "chef_card_reimburse", "budget": 220,
     "visit": (0, "09:30", "12:30", 3), "priority": 1, "address": "12 Orchard Lane", "gate": "4417#",
     "access": "Side door; the dog is friendly", "emergency": "Jordan 555-0142"},
    {"name": "Henderson family", "contact": "Priya Henderson", "email": "priya.h@example.com",
     "people": {"tom": {"name": "Tom", "age_band": "adult"},
                "mia": {"name": "Mia", "age_band": "kid", "age": 11, "allergies": ["dairy"]}},
     "brands": {"chicken_breast": {"prefer": "Bell & Evans"}}, "billing": "chef_card_reimburse", "budget": 180,
     "visit": (0, "13:30", "16:30", 2), "priority": 2, "address": "7 Harbor Road", "gate": "",
     "access": "Key in the lockbox, code 2210", "emergency": "Priya 555-0177"},
    {"name": "Davis household", "contact": "Morgan Davis", "email": "morgan.davis@example.com",
     "people": {"alex": {"name": "Alex", "age_band": "adult", "diet": ["pescatarian"]}},
     "brands": {}, "billing": "client_card_on_file", "budget": 150, "client_card": "Davis Amex",
     "visit": (1, "10:00", "12:00", 3), "priority": 3, "address": "88 Mill Pond Way", "gate": "1990",
     "access": "Doorman building, apartment 4B", "emergency": "Morgan 555-0119"},
]


def _times(now: dt.datetime) -> list[tuple[str, str]]:
    """Today's two visits around the current hour, so the cockpit shows a kitchen in progress and one after it."""
    a = min(max(now.hour - 1, 6), 17)
    return [(f"{a:02d}:30", f"{a + 3:02d}:00"), (f"{a + 3:02d}:30", f"{min(a + 6, 23):02d}:00")]


def seed(email: str, today: dt.date | None = None) -> dict:
    from . import week
    today = today or dt.date.today()
    times = _times(dt.datetime.now())
    con = accounts.connect()
    u = accounts.get_or_create_user(con, email, "Chef Ruairi")
    plans.set_chef_plan(con, u["id"], "chef_studio")
    existing = {r["name"]: r["household_id"] for r in con.execute(
        "SELECT h.name, h.id AS household_id FROM members m JOIN households h ON h.id = m.household_id "
        "WHERE m.user_id = ? AND m.role = 'chef'", (u["id"],))}
    db = pro.chef_db(u["id"])
    pro.put_setting(db, "cards", ["amex_gold", "costco_anywhere_visa"])
    pro.put_setting(db, "memberships", ["costco"])
    pro.put_setting(db, "stores", ["costco", "whole_foods", "trader_joes", "stop_and_shop"])
    pro.put_setting(db, "branding", {"business": "Ruairi's Kitchen", "footer": "Questions? Text Chef Ruairi."})
    out = {}
    for f in FAMILIES:
        hid = existing.get(f["name"])
        if not hid:
            pid = f["contact"].split()[0].lower()
            hid = accounts.create_household(con, u["id"], f["name"], "northeast-us",
                                            {"id": pid, "name": f["contact"], "email": f["email"], "can_cook": True},
                                            as_chef=True)
        out[hid] = f["name"]
        off, arrive, leave, span = f["visit"]
        if off == 0:
            arrive, leave = times[f["priority"] - 1]
        day = today + dt.timedelta(days=off)
        covers = [DAYS[(day + dt.timedelta(days=n)).weekday()] for n in range(span)]
        pro.save_client(db, hid, priority=f["priority"], billing=f["billing"], budget=f["budget"],
                        client_card=f.get("client_card"), address=f["address"], gate_code=f["gate"],
                        access_notes=f["access"], emergency=f["emergency"],
                        notes="Plates go on the second shelf; label every lid.",
                        visits=[{"day": DAYS[day.weekday()], "arrive": arrive, "leave": leave, "covers": covers}])
        with tenant(hid):
            h = load_household()
            raw = h.raw
            raw["people"].update(f["people"])
            raw["brands"] = f["brands"]
            save_household(raw)
            for wk in {week.week_start(today), week.week_start(today + dt.timedelta(days=6))}:
                hc = store.connect()
                have = store.get_week(hc, wk.isoformat())
                hc.close()
                if not have:
                    week.draft(wk, ideas=False, actor="chef-demo")
            hc = store.connect()
            if f["priority"] == 2 and not pro.open_containers(hc):
                y = today - dt.timedelta(days=3)
                pro.log_container(hc, "Turkey chili", 3, "fridge", "chef-demo", prepared=y)
                pro.log_container(hc, "Lemon chicken & green beans", 2, "fridge", "chef-demo",
                                  prepared=today - dt.timedelta(days=1))
                pro.make_card(load_household(), hc, "Turkey chili", "stovetop", 8, "chef-demo", covered=True,
                              containers=[1], prepared=y)
            hc.close()
    db.close()
    # the marketplace: the chef's public profile, and a family nearby that is looking for a chef
    from . import market
    market.save_profile(con, u["id"], display_name="Chef Ruairi", business="Ruairi's Kitchen", listed=True,
                        bio="Weeknight family dinners, allergy-aware, glass containers labelled and ready to reheat.",
                        cuisines=["italian", "mediterranean", "kid_friendly", "meal_prep"], rate_per_visit=225,
                        radius_miles=20, address={"city": "Westport", "state": "CT", "zip": "06880",
                                                  "lat": 41.1415, "lon": -73.3579})
    fam = accounts.get_or_create_user(con, "sam.nguyen@example.com", "Sam Nguyen")
    if not any(m["name"] == "Nguyen household" for m in accounts.memberships(con, fam["id"])):
        nh = accounts.create_household(con, fam["id"], "Nguyen household", "northeast-us",
                                       {"id": "sam", "name": "Sam Nguyen", "email": "sam.nguyen@example.com"})
        with tenant(nh):
            raw = load_household().raw
            raw["people"]["kim"] = {"name": "Kim", "age_band": "adult"}
            raw["people"]["bo"] = {"name": "Bo", "age_band": "kid", "age": 7, "allergies": ["peanut", "sesame"]}
            raw["address"] = {"line1": "40 Post Rd", "city": "Fairfield", "state": "CT", "zip": "06824",
                              "lat": 41.1408, "lon": -73.2637}
            save_household(raw)
        market.save_listing(con, nh, open=True, budget_per_week=450, visits_per_week=2, cuisines=["asian", "healthy"],
                            note="Two weeknight dinners for four; our son can't have peanuts or sesame.")
    con.close()
    return {"user": u["id"], "clients": out}
