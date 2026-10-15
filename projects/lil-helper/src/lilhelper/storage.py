"""Fridge, freezer and pantry: how much room is left, what to buy ahead while it's on sale, and meals to freeze.

All arithmetic on the household's own numbers (`storage` in its settings: litres of fridge and freezer, and how full
is comfortable) and rough per-ingredient sizes (catalog.LITRES_PER_UNIT, overridable). Nothing here is bought: these
are suggestions a person can add to the list.

  usage        litres in the fridge and freezer now (pantry stock, the frozen part of it, and frozen meals)
  free_space   what's left under the comfortable fill line
  upcoming     what the next weeks' stored plans need, by ingredient and day
  buy_ahead    items on special this week that a later week needs, that keep until then (frozen if need be) and fit
  freezer_plan which dinner to cook extra of and freeze, when there's room and a freezer night ahead
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from . import store
from .catalog import Catalog
from .config import DAYS, Household
from .prices import PriceBook, week_start

MEAL_LITRES = 0.45          # one frozen portion in a container


def usage(con, c: Catalog) -> dict[str, float]:
    pantry = store.pantry(con)
    frozen = store.frozen(con)
    out = {"fridge": 0.0, "freezer": 0.0, "pantry": 0.0}
    for iid, qty in pantry.items():
        ing = c.ingredients.get(iid)
        if not ing or qty <= 0:
            continue
        fz = min(qty, frozen.get(iid, 0.0))
        out["freezer"] += fz * ing.litres
        out[ing.storage if ing.storage in out else "pantry"] += (qty - fz) * ing.litres
    out["freezer"] += sum(m["portions"] for m in store.freezer_meals(con)) * MEAL_LITRES
    return {k: round(v, 1) for k, v in out.items()}


def free_space(h: Household, con, c: Catalog) -> dict[str, float]:
    cap = h.storage()
    used = usage(con, c)
    fill = float(cap["fill_target"])
    return {"fridge": round(float(cap["fridge_l"]) * fill - used["fridge"], 1),
            "freezer": round(float(cap["freezer_l"]) * fill - used["freezer"], 1)}


def upcoming(con, c: Catalog, after: dt.date, weeks: int = 3) -> dict[str, list[dict]]:
    """Ingredient → [{date, qty, meal, week_of}] from the stored plans of the weeks after `after`'s week."""
    out: dict[str, list[dict]] = {}
    start = week_start(after)
    for n in range(1, weeks + 1):
        wk = start + dt.timedelta(weeks=n)
        rec = store.get_week(con, wk.isoformat())
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
                                                "meal": f"{e['day']} {e['meal']}: {e['name']}",
                                                "week_of": wk.isoformat()})
    return out


@dataclass
class Ahead:
    ingredient: str
    name: str
    store: str
    store_name: str
    packs: int
    pack: float
    unit: str
    price: float
    regular: float
    saving: float
    needed_on: str
    for_: list[str]
    keep: str            # pantry | fridge | freeze
    litres: float
    channel: str = "any"


def buy_ahead(h: Household, c: Catalog, pb: PriceBook, ahead: dict[str, list[dict]], free: dict[str, float],
              this_week_items: set[str] | None = None, min_saving: float = 1.0) -> list[Ahead]:
    """Specials this week worth buying now for a later week: they keep until needed (in the freezer if they must),
    the saving is at least `min_saving`, and they fit in what's left of the fridge and freezer."""
    out: list[Ahead] = []
    shop_day = pb.week_of
    for iid, uses in ahead.items():
        ing = c.ingredients.get(iid)
        if not ing:
            continue
        specials = [o for o in pb.offers(iid) if o.special and o.regular]
        if not specials:
            continue
        o = min(specials, key=lambda x: x.unit)
        first = min(u["date"] for u in uses)
        days = (first - shop_day).days
        if days <= ing.shelf:
            keep = "fridge" if ing.storage == "fridge" else ing.storage
        elif ing.freezable and days <= ing.frozen_days:
            keep = "freeze"
        else:
            continue
        qty = sum(u["qty"] for u in uses)
        packs = max(1, math.ceil(qty / o.pack - 1e-9))
        saving = round((o.regular - o.price) * packs, 2)
        if saving < min_saving:
            continue
        litres = round(packs * o.pack * ing.litres, 2)
        out.append(Ahead(iid, ing.name, o.store, pb.store_cfg[o.store]["name"], packs, o.pack, ing.unit, o.price,
                         o.regular, saving, first.isoformat(), sorted({u["meal"] for u in uses})[:4], keep, litres,
                         o.channel))
    out.sort(key=lambda a: -a.saving / max(a.litres, 0.1))          # most saved per litre first
    room = {"fridge": free.get("fridge", 0.0), "freezer": free.get("freezer", 0.0)}
    kept = []
    for a in out:
        where = "freezer" if a.keep == "freeze" else ("fridge" if a.keep == "fridge" else None)
        if where and a.litres > room[where]:
            continue
        if where:
            room[where] -= a.litres
        kept.append(a)
    return kept


def freezer_plan(h: Household, c: Catalog, plan, free_freezer: float, freezer_nights_ahead: int,
                 in_freezer: int) -> list[tuple]:
    """Dinners to cook extra of and freeze: (entry, portions). Only freezes-well recipes, only with room, and only
    as many as the household wants kept (`freezer_meals.keep`, default 2 meals)."""
    cfg = h.freezer_meals()
    if not cfg.get("cook_extra"):
        return []
    want = int(cfg.get("keep", 2)) + freezer_nights_ahead - in_freezer
    if want <= 0:
        return []
    portions = round(sum(p.portion for p in h.eaters("dinner")), 1)
    picks = []
    for e in plan.entries:
        r = c.recipes.get(e.recipe)
        if e.meal == "dinner" and e.kind == "cook" and r and r.has("freezes_well") and not e.double:
            if free_freezer >= portions * MEAL_LITRES and len(picks) < want:
                picks.append((e, portions))
                free_freezer -= portions * MEAL_LITRES
    return picks
