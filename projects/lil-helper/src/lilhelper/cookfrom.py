"""Make a meal from what I've got: rank recipes by how much of them is already in the house.

Input: what someone types ("chicken thighs, half a bag of spinach, rice, eggs"), plus the pantry Lil'Helper keeps,
optionally flagged "use soon". Every recipe — the book and the household's own — is checked the same way as in a
plan (allergies of anyone in the house, diets of tonight's eaters, tonight's cooking-time limit), then ranked by code:

  score = share of the recipe (by cost) already in the house
        + a bonus per "use soon" item it uses up
        − the cost of what's missing
        + small nudges for likes and kid-friendliness

Staples (oil, salt, flour, spices) count as in the house. Each result says what's missing and what it would cost, and
can replace tonight's planned dinner (the rest of the week stays put). No model involved.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from . import safety, store
from .catalog import Catalog
from .config import DAYS, Household
from .prices import PriceBook

SOON_DAYS = 3


@dataclass
class Idea:
    recipe: str
    name: str
    meal: str
    have: list[str]
    missing: list[dict]
    missing_cost: float
    coverage: float              # share of the ingredient cost already in the house
    uses_soon: list[str]
    active: int
    total: int
    servings: float
    score: float
    instructions: list[str] = field(default_factory=list)
    why: list[str] = field(default_factory=list)


def parse_have(text: str, c: Catalog) -> tuple[set[str], list[str]]:
    """Free text → ingredient ids, and the phrases that matched nothing."""
    have, unknown = set(), []
    for part in re.split(r"[,\n;]+| and ", text or ""):
        part = part.strip()
        if not part:
            continue
        ids = c.match_all(part)
        if ids:
            have.update(ids)
        else:
            unknown.append(part)
    return have, unknown


def suggest(h: Household, c: Catalog, pb: PriceBook, *, text: str = "", use_pantry: bool = True,
            use_soon: list[str] | None = None, meal: str = "dinner", day: str | None = None,
            max_minutes: int | None = None, top: int = 5) -> dict:
    con = store.connect()
    pantry = store.pantry(con) if use_pantry else {}
    con.close()
    typed, unknown = parse_have(text, c)
    have = typed | {i for i, q in pantry.items() if q > 0}
    soon = set(use_soon or [])
    for p in use_soon or []:
        soon.update(c.match_all(p))
    soon |= {i for i in typed if c.ingredients[i].shelf <= SOON_DAYS}
    day = day or DAYS[dt.date.today().weekday()]
    eaters = h.eaters(meal, day) or h.eaters(meal)
    house = h.everyone_allergies()
    limit = max_minutes or h.prep_limit(day)
    servings = round(sum(p.portion for p in eaters), 2)
    ideas: list[Idea] = []
    for r in c.recipes.values():
        if r.meal != meal or r.active > limit:
            continue
        if not safety.recipe_for(c, r, eaters, house).ok:
            continue
        got, miss, cost_have, cost_all, missing_cost = [], [], 0.0, 0.0, 0.0
        for iid, q in r.ing.items():
            ing = c.ingredients[iid]
            unit = pb.best_unit(iid) or 0.0
            cost = unit * q * servings
            cost_all += cost
            if iid in have or ing.staple:
                got.append(ing.name)
                cost_have += cost
            else:
                miss.append({"ingredient": iid, "name": ing.name, "qty": round(q * servings, 2), "unit": ing.unit,
                             "est_cost": round(cost, 2)})
                missing_cost += cost
        if not got:
            continue
        coverage = cost_have / cost_all if cost_all else 1.0
        if coverage < 0.25 and len(miss) > 2:
            continue
        used_soon = [c.ingredients[i].name for i in r.ing if i in soon]
        likes = sum(1 for p in eaters if r.id in p.likes)
        kids = r.has("kid_friendly") and any(p.is_kid for p in eaters)
        score = 10 * coverage + 3 * len(used_soon) - missing_cost + 1.5 * likes + (1 if kids else 0)
        why = []
        if not miss:
            why.append("everything's in the house")
        if used_soon:
            why.append(f"uses up {', '.join(used_soon)}")
        if likes:
            why.append("a favourite")
        ideas.append(Idea(r.id, r.name, r.meal, got, miss, round(missing_cost, 2), round(coverage, 2), used_soon,
                          r.active, r.total, servings, round(score, 2), list(r.instructions), why))
    ideas.sort(key=lambda i: (-i.score, i.missing_cost, i.name))
    return {"day": day, "meal": meal, "servings": servings, "max_minutes": limit, "matched": sorted(typed),
            "not_recognised": unknown, "use_soon": sorted(soon), "ideas": [i.__dict__ for i in ideas[:top]]}
