"""Make a meal from what I've got: rank recipes by how much of them is already in the house.

Input: what someone types ("chicken thighs, half a bag of spinach, rice, eggs"), plus the pantry DinnerPeace keeps,
optionally flagged "use soon". Every recipe — the book and the household's own — is checked the same way as in a
plan (allergies of anyone in the house, diets of tonight's eaters, tonight's cooking-time limit), then ranked by code:

  score = 6 × how many of the things you typed it uses (each phrase counts once: "half a chicken" is one thing)
        + 4 × share of its ingredients already in the house (staples count as in the house)
        + a bonus per "use soon" item it uses up
        − the cost of what's missing
        + small nudges for likes and kid-friendliness

When you typed something, every idea uses at least one of those things. When nothing in the book uses all of them,
DinnerPeace also writes a simple new recipe from them (protein + vegetables + a starch, amounts from similar recipes)
that you can save to your book, and offers a web search for a recipe with them.

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
    uses_typed: list[str] = field(default_factory=list)      # which of the typed things it uses
    draft: dict | None = None                                  # a new recipe (not in the book yet)
    credit: str = ""


def parse_groups(text: str, c: Catalog) -> tuple[list[tuple[str, set[str]]], list[str]]:
    """Free text → [(phrase, ingredient ids it could mean)], and the phrases that matched nothing."""
    groups, unknown = [], []
    for part in re.split(r"[,\n;]+| and ", text or ""):
        part = part.strip()
        if not part:
            continue
        ids = c.match_all(part)
        if ids:
            groups.append((part, set(ids)))
        else:
            unknown.append(part)
    return groups, unknown


def parse_have(text: str, c: Catalog) -> tuple[set[str], list[str]]:
    groups, unknown = parse_groups(text, c)
    return set().union(*[g for _, g in groups]) if groups else set(), unknown


STARCH = {"rice", "pasta", "potatoes", "sweet_potatoes", "tortillas", "bread", "quinoa", "noodles", "couscous", "gf_pasta"}
PROTEIN_CATS = {"meat", "fish"}
PROTEIN_IDS = {"tofu", "eggs", "black_beans", "chickpeas", "white_beans", "shrimp"}


FILLER = {"half", "a", "an", "bag", "of", "some", "leftover", "leftovers", "box", "the", "pack", "few", "bit", "little",
          "bunch", "can", "jar", "quarter", "whole", "one", "two", "lb", "lbs", "cup", "cups"}


def plain(phrase: str) -> str:
    """'half a bag of broccoli' → 'broccoli'."""
    return " ".join(w for w in re.findall(r"[a-z]+", phrase.lower()) if w not in FILLER) or phrase


def _usual_amount(c: Catalog, iid: str, meal: str) -> float | None:
    qs = sorted(r.ing[iid] for r in c.recipes.values() if iid in r.ing and r.suits(meal))
    return qs[len(qs) // 2] if qs else None


def compose(c: Catalog, groups: list[tuple[str, set[str]]], meal: str, eaters, house,
            unknown: list[str] | None = None) -> dict | None:
    """A simple new recipe from what was typed: one protein, the vegetables, one starch, plus oil and garlic.
    Amounts per serving are the median of the book's recipes that use each ingredient."""
    from .catalog import Recipe
    pick = []
    for phrase, ids in groups:
        best = sorted(ids, key=lambda i: -sum(1 for r in c.recipes.values() if i in r.ing))[0]
        pick.append(best)
    protein = [i for i in pick if c.ingredients[i].cat in PROTEIN_CATS or i in PROTEIN_IDS][:1]
    starch = [i for i in pick if i in STARCH][:1]
    veg = [i for i in pick if c.ingredients[i].cat == "produce" and i not in starch][:3]
    if not protein:
        return None
    ing = {}
    for iid in protein + veg + starch:
        q = _usual_amount(c, iid, meal) or (0.3 if c.ingredients[iid].unit in ("lb", "cup") else 1)
        ing[iid] = q
    for iid, q in (("olive_oil", 1), ("garlic", 0.25)):
        if iid in c.ingredients and iid not in ing:
            ing[iid] = q
    nm = lambda i: c.ingredients[i].name   # noqa: E731
    said = {i: plain(ph) for (ph, _), i in zip(groups, pick)}
    say = lambda i: said.get(i) or nm(i)   # noqa: E731
    extra = [plain(u) for u in (unknown or [])][:2]          # things DinnerPeace doesn't know yet, likely vegetables
    if not (veg or starch or extra):
        return None
    p, v, st = say(protein[0]), [say(i) for i in veg] + extra, (say(starch[0]) if starch else "")
    name = f"One-pan {p}" + (f" with {' and '.join(v)}" if v else "") + (f" and {st}" if st else "")
    steps = ([f"Start the {st} (follow the packet)."] if st else []) + [
        f"Cut the {p} into bite-size pieces; season with salt and pepper.",
        f"Heat the oil in a large pan and brown the {p}, 6–8 minutes, until cooked through.",
    ] + ([f"Add the garlic and {', '.join(v)}; cook 4–5 minutes until just tender."] if v else []) + [
        "Taste, season, and serve" + (f" over the {st}." if st else ".")]
    r = Recipe("draft", name, meal, 20, 35, ing, tags=["one_pot"])
    ok = safety.recipe_for(c, r, eaters, house).ok
    if not ok:
        return None
    return {"name": name[:80], "meal": meal, "serves": 4, "active": 20, "total": 35,
            "ingredients": [{"ingredient": i, "text": nm(i), "qty": round(q * 4, 2), "unit": c.ingredients[i].unit}
                            for i, q in ing.items()] + [{"text": x, "qty": 1, "unit": "", "known": False} for x in extra],
            "unknown": extra,
            "instructions": steps, "tags": ["one_pot"], "credit": "DinnerPeace"}


def suggest(h: Household, c: Catalog, pb: PriceBook, *, text: str = "", use_pantry: bool = True,
            use_soon: list[str] | None = None, meal: str = "dinner", day: str | None = None,
            max_minutes: int | None = None, top: int = 5) -> dict:
    con = store.connect()
    pantry = store.pantry(con) if use_pantry else {}
    con.close()
    groups, unknown = parse_groups(text, c)
    typed = set().union(*[g for _, g in groups]) if groups else set()
    have = typed | {i for i, q in pantry.items() if q > 0}
    soon = set()
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
        if not r.suits(meal) or r.active > limit:
            continue
        used = [phrase for phrase, ids in groups if ids & set(r.ing)]
        if groups and not used:
            continue                                     # you said what you've got: use some of it
        if not safety.recipe_for(c, r, eaters, house).ok:
            continue
        got, miss, missing_cost = [], [], 0.0
        for iid, q in r.ing.items():
            ing = c.ingredients[iid]
            cost = (pb.best_unit(iid) or 0.0) * q * servings
            if iid in have or ing.staple:
                got.append(ing.name)
            else:
                miss.append({"ingredient": iid, "name": ing.name, "qty": round(q * servings, 2), "unit": ing.unit,
                             "est_cost": round(cost, 2)})
                missing_cost += cost
        if not groups and not [i for i in r.ing if i in have and not c.ingredients[i].staple]:
            continue
        coverage = len(got) / len(r.ing) if r.ing else 1.0
        used_soon = [c.ingredients[i].name for i in r.ing if i in soon]
        likes = sum(1 for p in eaters if r.id in p.likes)
        kids = r.has("kid_friendly") and any(p.is_kid for p in eaters)
        score = 6 * len(used) + 4 * coverage + 2 * len(used_soon) - 0.3 * missing_cost + 1.5 * likes + (1 if kids else 0)
        why = []
        if groups:
            why.append(f"uses the {', '.join(plain(u) for u in used)}" if len(used) < len(groups)
                       else "uses everything you listed")
        if not miss:
            why.append("everything's in the house")
        if likes:
            why.append("a favourite")
        ideas.append(Idea(r.id, r.name, meal, got, miss, round(missing_cost, 2), round(coverage, 2), used_soon,
                          r.active, r.total, servings, round(score, 2), list(r.instructions), why, used,
                          credit=r.credit or ("DinnerPeace" if r.source == "book" else "")))
    ideas.sort(key=lambda i: (-i.score, i.missing_cost, i.name))
    out = [i.__dict__ for i in ideas[:top]]
    all_used = any(len(i.uses_typed) == len(groups) for i in ideas) if groups else True
    new = None
    if groups and (not all_used or unknown):
        d = compose(c, groups, meal, eaters, house, unknown)
        if d:
            new = Idea("", d["name"], meal, [x["text"] for x in d["ingredients"]], [], 0.0, 1.0, [], d["active"],
                       d["total"], servings, 0.0, d["instructions"],
                       ["a new recipe from what you listed — save it to your book to plan it"]
                       + ([f"add {', '.join(d['unknown'])} as an ingredient when you save it"] if d["unknown"] else []),
                       [p for p, _ in groups], draft=d, credit="DinnerPeace").__dict__
    words = " ".join(plain(p) for p, _ in groups)
    return {"day": day, "meal": meal, "servings": servings, "max_minutes": limit,
            "matched": sorted(typed), "not_recognised": unknown, "use_soon": sorted(soon), "ideas": out,
            "uses_everything": all_used, "new_recipe": new,
            "search": f"{words} {meal} recipe".strip() if groups else ""}
