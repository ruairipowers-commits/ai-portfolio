"""Ways to decide what to eat, besides the weekly plan:

  vibe        how much time you have and what you're in the mood for → a few ideas, with what's missing to order
  occasion    a birthday, a party, a holiday → the person's favourites or recipes that fit, sized for the guests
  buffet      no recipe per day: keep N portions of a few things on hand; restock them each week
  surprise    anything from the recipe book that's safe for tonight's eaters

Everything here is decided by code (no model), and every idea passes the same allergy and diet rules as a plan.
"""
from __future__ import annotations

import datetime as dt
import random
import re

from . import safety, store
from .catalog import Catalog, Recipe
from .config import DAYS, Household
from .prices import PriceBook

MOODS = {
    "quick": "ready fast", "comfort": "comfort food", "light": "something light", "veggie": "vegetarian",
    "kid_pleaser": "the kids will eat it", "cozy": "warm and cozy", "fresh": "fresh and bright",
    "adventurous": "something different", "party": "a crowd-pleaser", "special": "a bit special",
}
COZY = re.compile(r"soup|stew|chili|risotto|roast|bolognese|mac|curry", re.I)
FRESH = re.compile(r"salad|grilled|lemon|summer|shrimp|salmon|cod|taco", re.I)
COMFORT = re.compile(r"mac|pasta|pizza|chili|stew|meatball|burger|soup|grilled cheese|pancake", re.I)


def mood_score(r: Recipe, mood: str, recent: set[str], likes: set[str]) -> tuple[float, str | None]:
    if mood == "quick":
        return (2.0, "quick") if r.active <= 15 and r.total <= 30 else (0.0, None)
    if mood == "comfort":
        return (2.0, "comfort food") if COMFORT.search(r.name) or r.has("kid_friendly") and r.has("one_pot") else (0, None)
    if mood == "light":
        light = r.has("vegetarian") and (r.kcal or 500) <= 480 or (r.kcal and r.kcal <= 430)
        return (2.0, "light") if light else (0.0, None)
    if mood == "veggie":
        return (2.0, "vegetarian") if r.has("vegetarian") else (-5.0, None)
    if mood == "kid_pleaser":
        return (2.0, "kid-friendly") if r.has("kid_friendly") else (0.0, None)
    if mood == "cozy":
        return (2.0, "warm and cozy") if COZY.search(r.name) else (0.0, None)
    if mood == "fresh":
        return (2.0, "fresh") if FRESH.search(r.name) or r.has("grill") else (0.0, None)
    if mood == "adventurous":
        return (2.5, "something different") if r.id not in recent and r.id not in likes else (-1.0, None)
    if mood in ("party", "special", "festive", "grill"):
        return (2.0, mood) if r.has(mood) else (0.0, None)
    return 0.0, None


def _eaters(h: Household, meal: str, day: str | None, people: list[str] | None):
    if people:
        return [h.people[p] for p in people if p in h.people]
    return h.eaters(meal, day) or h.eaters(meal) or list(h.people.values())


def vibe(h: Household, c: Catalog, pb: PriceBook, *, minutes: int, moods: list[str], meal: str = "dinner",
         day: str | None = None, people: list[str] | None = None, have: str = "", top: int = 5) -> dict:
    from . import cookfrom
    eaters = _eaters(h, meal, day, people)
    house = h.everyone_allergies()
    con = store.connect()
    pantry = store.pantry(con)
    recent = {rid for rid, d in store.history(con).items() if (dt.date.today() - d).days < 21}
    con.close()
    groups, unknown = cookfrom.parse_groups(have, c)
    typed = set().union(*[g for _, g in groups]) if groups else set()
    likes = {rid for p in eaters for rid in p.likes}
    servings = round(sum(p.portion for p in eaters), 2)
    out = []
    for r in c.recipes.values():
        if not r.suits(meal) or r.total > minutes:
            continue
        if not safety.recipe_for(c, r, eaters, house).ok:
            continue
        score, why = 0.0, []
        for m in moods:
            sc, label = mood_score(r, m, recent, likes)
            score += sc
            if label:
                why.append(label)
        if moods and not why:
            continue
        uses = [p for p, ids in groups if ids & set(r.ing)]
        score += 2 * len(uses) + 1.5 * sum(1 for p in eaters if r.id in p.likes) - (1.5 if r.id in recent else 0)
        missing = [{"ingredient": i, "name": c.ingredients[i].name, "qty": round(q * servings, 2),
                    "unit": c.ingredients[i].unit, "est_cost": round((pb.best_unit(i) or 0) * q * servings, 2)}
                   for i, q in r.ing.items() if not c.ingredients[i].staple and i not in typed
                   and pantry.get(i, 0) < q * servings * 0.8]
        score -= 0.15 * sum(m["est_cost"] for m in missing)
        if uses:
            why.append("uses " + ", ".join(cookfrom.plain(u) for u in uses))
        if r.id in likes:
            why.append("a favourite")
        out.append({"recipe": r.id, "name": r.name, "active": r.active, "total": r.total, "kcal": r.kcal,
                    "servings": servings, "why": why, "missing": missing,
                    "missing_cost": round(sum(m["est_cost"] for m in missing), 2), "score": round(score, 2),
                    "credit": r.credit or ("Lil'Helper" if r.source == "book" else "")})
    out.sort(key=lambda x: (-x["score"], x["missing_cost"], x["name"]))
    return {"meal": meal, "minutes": minutes, "moods": moods, "servings": servings, "ideas": out[:top],
            "not_recognised": unknown, "mood_names": MOODS}


def occasion_ideas(h: Household, c: Catalog, pb: PriceBook, *, people: list[str], tags: list[str], guests: int,
                   meal: str = "dinner", top: int = 6) -> dict:
    """Favourites of the people it's for first, then recipes with the occasion's tags; sized for everyone + guests."""
    eaters = list(h.people.values())
    house = h.everyone_allergies()
    fans = {rid: [h.people[p].name for p in people if p in h.people and rid in h.people[p].likes] for rid in c.recipes}
    servings = round(sum(p.portion for p in eaters) + guests, 2)
    out = []
    for r in c.recipes.values():
        if not r.suits(meal) or not safety.recipe_for(c, r, eaters, house).ok:
            continue
        hit = [t for t in tags if r.has(t)]
        if not fans[r.id] and not hit:
            continue
        score = 5 * len(fans[r.id]) + 2 * len(hit)
        why = ([f"{', '.join(fans[r.id])}'s favourite"] if fans[r.id] else []) + [t.replace("_", " ") for t in hit]
        cost = round(sum((pb.best_unit(i) or 0) * q * servings for i, q in r.ing.items()), 2)
        out.append({"recipe": r.id, "name": r.name, "why": why, "servings": servings, "est_cost": cost,
                    "active": r.active, "total": r.total, "score": score})
    out.sort(key=lambda x: (-x["score"], x["est_cost"]))
    return {"servings": servings, "ideas": out[:top]}


def surprise(h: Household, c: Catalog, *, meal: str = "dinner", day: str | None = None, seed: int | None = None,
             minutes: int | None = None) -> dict | None:
    eaters = _eaters(h, meal, day, None)
    house = h.everyone_allergies()
    limit = minutes or (h.prep_limit(day) if day else 120)
    pool = sorted([r for r in c.recipes.values() if r.suits(meal) and r.active <= limit
                   and safety.recipe_for(c, r, eaters, house).ok], key=lambda r: r.id)
    if not pool:
        return None
    r = random.Random(seed).choice(pool)
    return {"recipe": r.id, "name": r.name, "active": r.active, "total": r.total, "kcal": r.kcal,
            "credit": r.credit or ("Lil'Helper" if r.source == "book" else ""), "steps": r.instructions,
            "pool": len(pool)}


# ---------------------------------------------------------------- weekly buffet
def buffet_cfg(h: Household) -> dict[str, dict]:
    """{meal: {on, items: [{recipe, target}]}} — meals kept as a buffet instead of a recipe per day."""
    return {m: v for m, v in (h.raw.get("buffet") or {}).items() if v and v.get("on")}


def buffet_stock(con) -> dict[tuple[str, str], float]:
    con.execute("CREATE TABLE IF NOT EXISTS buffet_stock (meal TEXT, recipe TEXT, on_hand REAL, updated TEXT, by TEXT, "
                "PRIMARY KEY (meal, recipe))")
    return {(r["meal"], r["recipe"]): r["on_hand"] for r in con.execute("SELECT * FROM buffet_stock")}


def set_buffet_stock(con, meal: str, recipe: str, on_hand: float, by: str) -> None:
    buffet_stock(con)
    con.execute("INSERT OR REPLACE INTO buffet_stock VALUES (?,?,?,?,?)", (meal, recipe, max(0.0, on_hand), store.now(), by))
    con.commit()


def buffet_restock(h: Household, c: Catalog, con) -> list[dict]:
    """What to cook this week to bring each buffet item back to its target number of portions."""
    stock = buffet_stock(con)
    out = []
    for meal, cfg in buffet_cfg(h).items():
        for it in cfg.get("items") or []:
            r = c.recipes.get(it.get("recipe"))
            if not r:
                continue
            target = float(it.get("target") or 0)
            have = stock.get((meal, r.id), 0.0)
            cook = max(0.0, round(target - have, 1))
            out.append({"meal": meal, "recipe": r.id, "name": r.name, "target": target, "on_hand": have,
                        "cook": cook, "active": r.active})
    return out


def plan_dates(start: dt.date, weeks: int) -> list[dt.date]:
    from .prices import week_start
    s = week_start(start)
    return [s + dt.timedelta(weeks=n) for n in range(weeks)]


__all__ = ["vibe", "occasion_ideas", "surprise", "buffet_cfg", "buffet_stock", "set_buffet_stock", "buffet_restock",
           "MOODS", "DAYS"]
