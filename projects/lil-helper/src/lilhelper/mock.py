"""Offline stand-ins for the three model jobs. Deterministic, so tests and the demo don't need keys.

They behave like a plausible model, mistakes included: one recipe idea hides an allergen in its name, one uses an
ingredient that isn't in the catalog, and the flyer reader copies every line it sees — including printed
instructions — so the code checks around them have real work to do.
"""
from __future__ import annotations

import re

IDEAS = {
    "fall": [
        {"name": "Apple, sausage and butternut squash sheet pan", "meal": "dinner", "active": 15, "total": 40,
         "veg": 2, "protein": 22, "tags": ["sheet_pan", "kid_friendly"],
         "ing": {"sausage": 0.2, "apples": 0.5, "butternut_squash": 0.25, "olive_oil": 1, "maple_syrup": 0.5},
         "why": "Apples and squash are at their best in October and both are on special."},
        {"name": "Thai satay noodle bowls", "meal": "dinner", "active": 20, "total": 25, "veg": 1.5, "protein": 20,
         "tags": [], "ing": {"chicken_thighs": 0.3, "pasta": 2.5, "carrots": 0.15, "cucumber": 0.3, "soy_sauce": 1},
         "why": "A quick weeknight bowl the kids can build themselves."},
        {"name": "Pumpkin and turkey baked ziti", "meal": "dinner", "active": 20, "total": 45, "veg": 1.5,
         "protein": 26, "tags": ["batch", "leftovers", "kid_friendly"],
         "ing": {"ground_turkey": 0.25, "pasta": 3, "pumpkin_puree": 0.15, "marinara": 0.3, "mozzarella": 1.5},
         "why": "Cook it Sunday; it reheats well for a busy night."},
        {"name": "Gochujang chicken lettuce cups", "meal": "dinner", "active": 15, "total": 20, "veg": 1,
         "protein": 28, "tags": [], "ing": {"chicken_thighs": 0.35, "gochujang": 1, "lettuce": 0.3, "rice": 0.3},
         "why": "Something new and fast."},
    ],
    "summer": [
        {"name": "Grilled chicken, corn and tomato salad", "meal": "dinner", "active": 20, "total": 25, "veg": 2.5,
         "protein": 30, "tags": ["kid_friendly"],
         "ing": {"chicken_breast": 0.35, "corn": 0.5, "cherry_tomatoes": 0.4, "basil": 0.1, "olive_oil": 1},
         "why": "Corn and tomatoes are in season."},
        {"name": "Pesto zucchini pasta", "meal": "dinner", "active": 15, "total": 20, "veg": 1.5, "protein": 12,
         "tags": ["vegetarian"], "ing": {"pasta": 3, "zucchini": 0.5, "parmesan": 0.3, "olive_oil": 1},
         "why": "Zucchini season."},
    ],
}


def season_of(month: int) -> str:
    return "fall" if month in (9, 10, 11, 12, 1, 2) else "summer"


def suggest(household: dict) -> dict:
    ideas = IDEAS[season_of(int(household.get("month", 10)))]
    n = int(household.get("count", 2))
    return {"recipes": ideas[: max(n, 1) + 2]}           # a model often returns a few more than asked


PRICE = re.compile(r"(\$\s?\d+(?:\.\d{1,2})?|\d+\s*for\s*\$\s?\d+(?:\.\d{1,2})?)", re.I)


def flyer(text: str) -> dict:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    store = lines[0].split(":")[0] if lines else ""
    items, other = [], []
    for ln in lines[1:]:
        m = PRICE.search(ln)
        if m:
            items.append({"text": re.sub(r"\s*\.{2,}\s*", " ", ln[: m.start()]).strip(" .-"), "price": m.group(1)})
        else:
            other.append(ln)
    return {"store": store, "valid_from": None, "valid_to": None, "items": items, "other": other}


def notes(plan: dict) -> dict:
    out = []
    for e in plan.get("entries", []):
        why = e.get("why") or []
        bits = []
        if "a favourite" in why:
            bits.append("a family favourite")
        if "in season" in why:
            bits.append("uses what's in season")
        sp = next((w for w in why if w.endswith("on special")), None)
        if sp:
            n = int(sp.split()[0])
            bits.append("an ingredient on special" if n == 1 else f"{n} ingredients on special")
        if any(w.startswith("cooked double") for w in why):
            bits.append("makes enough for leftovers night")
        if any(w.startswith("prep on") for w in why):
            bits.append(next(w for w in why if w.startswith("prep on")))
        if e.get("active", 0) and e.get("active") <= 20:
            bits.append(f"{e['active']} minutes hands-on")
        note = (", ".join(bits) or "keeps the week varied").capitalize() + "."
        out.append({"day": e["day"], "meal": e["meal"], "note": note[:120]})
    return {"notes": out}
