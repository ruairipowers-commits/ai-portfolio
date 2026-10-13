"""Ingredient forecast: pick an ingredient (or one of the most-used), and see how much the coming weeks' plans need,
when, what's already in the house, which shopping trip should buy it, how much to buy, and what it will cost.

Everything comes from the stored plans (this week and the next few, drafted ahead), the pantry, the price book and
the household's shopping trips. Stock is walked forward day by day: this week's planned purchases arrive on their
trip's day, each meal uses its share, and when stock would run out the shortfall is bought on the last trip before
it's needed — in whole packs, at the cheapest store that trip goes to (or anywhere, without scheduled trips).
"""
from __future__ import annotations

import datetime as dt
import math

from . import store
from .catalog import Catalog
from .config import DAYS, Household
from .prices import PriceBook, week_start
from .shopping import SESSION_DAY


def _week_records(con, start: dt.date, weeks: int) -> list[tuple[dt.date, dict | None]]:
    return [(start + dt.timedelta(weeks=n), store.get_week(con, (start + dt.timedelta(weeks=n)).isoformat()))
            for n in range(weeks)]


def uses(c: Catalog, records) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for wk, rec in records:
        if not rec:
            continue
        for e in rec["plan"]["entries"]:
            if e.get("kind", "cook") != "cook":
                continue
            r = c.recipes.get(e["recipe"])
            if not r:
                continue
            date = wk + dt.timedelta(days=DAYS.index(e.get("prep_day") or e["day"]))
            for iid, q in r.ing.items():
                out.setdefault(iid, []).append({"date": date, "qty": round(q * e["servings"], 3),
                                                "meal": f"{e['name']} ({e['day']} {e['meal']})"})
    return out


def common(c: Catalog, pb: PriceBook, records, top: int = 12) -> list[dict]:
    """The ingredients the coming weeks spend most on (a short list to pick from)."""
    rows = []
    for iid, us in uses(c, records).items():
        ing = c.ingredients[iid]
        if ing.staple:
            continue
        qty = sum(u["qty"] for u in us)
        unit = pb.best_unit(iid) or 0
        rows.append({"ingredient": iid, "name": ing.name, "unit": ing.unit, "qty": round(qty, 2),
                     "est_cost": round(qty * unit, 2), "meals": len(us)})
    rows.sort(key=lambda r: -r["est_cost"])
    return rows[:top]


def _trips(h: Household, start: dt.date, weeks: int) -> list[dict]:
    out = []
    for n in range(weeks):
        wk = start + dt.timedelta(weeks=n)
        for s in h.sessions():
            out.append({**s, "date": wk + dt.timedelta(days=SESSION_DAY[s["day"]])})
    return sorted(out, key=lambda t: t["date"])


def forecast(h: Household, c: Catalog, pb: PriceBook, iid: str, start: dt.date, weeks: int = 4,
             today: dt.date | None = None) -> dict:
    if iid not in c.ingredients:
        raise ValueError("unknown ingredient")
    ing = c.ingredients[iid]
    start = week_start(start)
    today = today or start
    con = store.connect()
    records = _week_records(con, start, weeks)
    on_hand = store.pantry(con).get(iid, 0.0)
    frozen = store.frozen(con).get(iid, 0.0)
    con.close()
    us = sorted(uses(c, records).get(iid, []), key=lambda u: u["date"])
    # this week's planned purchases arrive on their trip's day (or the start of the week)
    arrivals = []
    rec0 = records[0][1] if records else None
    if rec0:
        choice = rec0.get("shopping_choice") or "balanced"
        for o in (rec0.get("split") or {}).get(choice, {}).get("orders", []):
            for ln in o["lines"]:
                if ln["ingredient"] == iid:
                    day = start + dt.timedelta(days=SESSION_DAY.get(o.get("day") or "mon", 0))
                    arrivals.append({"date": day, "qty": ln["packs"] * ln["pack"], "store": o["store_name"],
                                     "mode": o["mode"], "packs": ln["packs"], "pack": ln["pack"],
                                     "cost": ln["cost"], "planned": True})
    offers = sorted(pb.offers(iid), key=lambda o: o.unit)
    trips = _trips(h, start, weeks)
    stock = on_hand
    events = sorted([("in", a["date"], a) for a in arrivals] + [("use", u["date"], u) for u in us],
                    key=lambda e: (e[1], e[0] != "in"))
    timeline, buys = [], []
    for kind, date, ev in events:
        if kind == "in":
            stock += ev["qty"]
            timeline.append({"date": date.isoformat(), "event": f"bought {ev['packs']} × {ev['pack']:g} {ing.unit} at "
                             f"{ev['store']} ({ev['mode'].replace('_', ' ')})", "stock": round(stock, 2)})
            continue
        if stock + 1e-9 < ev["qty"]:
            short = ev["qty"] - stock
            trip = next((t for t in reversed(trips) if t["date"] <= date and (date - t["date"]).days <= max(
                ing.shelf, ing.keeps_for(frozen=True))), None)
            stores_ok = [o for o in offers if not trip or o.store == trip["store"]] or offers
            if not stores_ok:
                timeline.append({"date": date.isoformat(), "event": f"needed for {ev['meal']}, but no store you use "
                                 "sells it", "stock": round(stock, 2)})
                stock -= ev["qty"]
                continue
            o = stores_ok[0]
            packs = max(1, math.ceil(short / o.pack - 1e-9))
            buy_date = trip["date"] if trip else max(today, date - dt.timedelta(days=min(ing.shelf, 3)))
            buys.append({"date": buy_date.isoformat(), "trip": trip["id"] if trip else None,
                         "when": f"{DAYS[buy_date.weekday()]} {trip.get('time', '')}".strip() if trip else "before it's needed",
                         "store": pb.store_cfg[o.store]["name"], "mode": trip["mode"] if trip else "any",
                         "packs": packs, "pack": o.pack, "unit": ing.unit, "brand": o.brand,
                         "price_each": o.price, "cost": round(packs * o.price, 2), "special": o.special,
                         "for": ev["meal"]})
            stock += packs * o.pack
            timeline.append({"date": buy_date.isoformat(), "event": f"buy {packs} × {o.pack:g} {ing.unit} at "
                             f"{pb.store_cfg[o.store]['name']}", "stock": round(stock, 2)})
        stock -= ev["qty"]
        timeline.append({"date": date.isoformat(), "event": f"use {ev['qty']:g} {ing.unit} for {ev['meal']}",
                         "stock": round(stock, 2)})
    need_total = round(sum(u["qty"] for u in us), 2)
    unit_prices = [{"store": pb.store_cfg[o.store]["name"], "brand": o.brand, "pack": o.pack, "price": o.price,
                    "per_unit": round(o.unit, 3), "special": o.special, "regular": o.regular,
                    "channel": o.channel} for o in offers]
    tips = []
    if offers and len(offers) > 1 and offers[-1].unit > 0:
        tips.append(f"Cheapest per {ing.unit}: {unit_prices[0]['store']} at ${offers[0].unit:.2f} "
                    f"(dearest ${offers[-1].unit:.2f}).")
    if us and (us[-1]["date"] - us[0]["date"]).days > ing.shelf:
        tips.append(f"It keeps about {ing.shelf} days" + (f" (or {ing.frozen_days} frozen)" if ing.freezable else "")
                    + ", so buy it in more than one trip" + (" or freeze part of it." if ing.freezable else "."))
    if any(o.special for o in offers):
        sp = next(o for o in offers if o.special)
        tips.append(f"On special at {pb.store_cfg[sp.store]['name']} this week (${sp.price:.2f}, usually "
                    f"${sp.regular:.2f})" + (" — in store only." if sp.channel == "in_store" else
                                              " — online orders only." if sp.channel == "online" else "."))
    return {"ingredient": iid, "name": ing.name, "unit": ing.unit, "storage": ing.storage,
            "keeps_days": ing.shelf, "freezable": ing.freezable, "on_hand": round(on_hand, 2),
            "on_hand_frozen": round(frozen, 2), "weeks": [w.isoformat() for w, _ in records],
            "weeks_planned": [w.isoformat() for w, r in records if r],
            "need_total": need_total, "uses": [{**u, "date": u["date"].isoformat()} for u in us],
            "planned_purchases": [{**a, "date": a["date"].isoformat()} for a in arrivals],
            "buys": buys, "buy_cost": round(sum(b["cost"] for b in buys), 2),
            "end_stock": round(stock, 2), "prices": unit_prices, "timeline": timeline, "tips": tips}
