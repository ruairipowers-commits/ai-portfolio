"""Food facts: ingredients, recipes, the season, and the words that mean an allergen or a danger to a dog."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from .config import ROOT


@dataclass
class Ingredient:
    id: str
    name: str
    unit: str
    cat: str
    aisle: int
    allergens: list[str] = field(default_factory=list)
    dog: str = ""
    shelf: int = 7
    staple: bool = False
    storage: str = ""              # pantry | fridge | freezer (blank: from the category)
    freezable: bool | None = None  # can go in the freezer to keep longer (blank: from the category)
    frozen_days: int = 0           # how long it keeps frozen
    litres: float = 0.0            # space one unit takes (blank: from the unit)
    source: str = "book"           # book | household
    prices: dict = field(default_factory=dict)   # household-added: {store: {pack, price}}

    def __post_init__(self):
        d = STORAGE_DEFAULTS.get(self.cat, ("pantry", False, 0))
        if self.id in ROOM_TEMP_PRODUCE:
            d = ("pantry", False, 0)
        self.storage = self.storage or d[0]
        if self.freezable is None:
            self.freezable = d[1]
        self.frozen_days = self.frozen_days or d[2]
        self.litres = self.litres or LITRES_PER_UNIT.get(self.unit, 0.1)

    def keeps_for(self, frozen: bool = False) -> int:
        return self.frozen_days if (frozen and self.freezable) else self.shelf


@dataclass
class Recipe:
    id: str
    name: str
    meal: str
    active: int
    total: int
    ing: dict[str, float]
    veg: float = 0
    protein: float = 0
    tags: list[str] = field(default_factory=list)
    dog: list[str] = field(default_factory=list)
    source: str = "book"           # book | household | suggested
    kid_min_age: int = 0           # > 0: a kid this age or older can make it with an adult nearby
    instructions: list[str] = field(default_factory=list)
    season_months: list[int] = field(default_factory=list)   # only plan it in these months (blank: any time)
    want: dict = field(default_factory=dict)  # how often: {times: 2, per_weeks: 4} → due until had that often
    notes: str = ""
    created_by: str = ""

    def has(self, tag: str) -> bool:
        return tag in self.tags


# Where things keep, by category: (storage, can be frozen, days frozen). Rough guides; any ingredient can override.
STORAGE_DEFAULTS = {
    "produce": ("fridge", False, 0), "meat": ("fridge", True, 120), "fish": ("fridge", True, 90),
    "dairy": ("fridge", False, 0), "deli": ("fridge", True, 60), "bakery": ("pantry", True, 60),
    "frozen": ("freezer", True, 240), "pantry": ("pantry", False, 0), "pet": ("pantry", False, 0),
}
ROOM_TEMP_PRODUCE = {"potatoes", "sweet_potatoes", "onion", "garlic", "butternut_squash", "bananas", "avocado",
                     "lemons", "limes", "tomatoes"}
LITRES_PER_UNIT = {"lb": 0.6, "each": 0.3, "cup": 0.25, "oz": 0.04, "can": 0.45, "tbsp": 0.0, "slice": 0.02}


def _singular(w: str) -> str:
    """Crude singular so "sweet potato" matches "sweet potatoes" and "grape" matches "grapes". Applied to both
    sides, so an odd stem ("hummu") still matches itself; for safety rules a little over-matching is the safe side."""
    if len(w) > 4 and w.endswith("oes"):
        return w[:-2]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _norm(text: str) -> str:
    return " " + " ".join(_singular(w) for w in re.sub(r"[^a-z0-9]+", " ", text.lower()).split()) + " "


def words_in(text: str, words: list[str], except_: list[str] | None = None) -> list[str]:
    """Which of `words` (single words or phrases) appear in text as whole words, case-insensitive.
    Phrases in `except_` are blanked out first ("coconut milk" is not dairy)."""
    t = _norm(text)
    for e in sorted(except_ or [], key=len, reverse=True):
        t = t.replace(_norm(e), " ~ ")
    return [w for w in words if _norm(w) in t]


class Catalog:
    def __init__(self, region: str = "northeast-us"):
        raw = yaml.safe_load((ROOT / "data" / "ingredients.yaml").read_text())
        self.ingredients = {k: Ingredient(id=k, **v) for k, v in raw["ingredients"].items()}
        self.hidden: dict[str, list[str]] = raw["hidden_allergens"]
        self.dog_toxic_words: list[str] = raw["dog_toxic_words"]
        self.exceptions: dict[str, list[str]] = raw.get("hidden_exceptions", {})
        book = yaml.safe_load((ROOT / "data" / "recipes.yaml").read_text())
        self.recipes = {k: Recipe(id=k, **v) for k, v in book["recipes"].items()}
        for rid, age in (book.get("kid_can_make") or {}).items():
            if rid in self.recipes:
                self.recipes[rid].kid_min_age = int(age)
                self.recipes[rid].tags.append("kid_can_make")
        for rid in book.get("freezes_well") or []:
            if rid in self.recipes:
                self.recipes[rid].tags.append("freezes_well")
        season_file = ROOT / "data" / "season" / f"{region}.yaml"
        self.season = yaml.safe_load(season_file.read_text())["peak_months"] if season_file.exists() else {}

    # ---------------------------------------------------------------- allergens
    def allergens_of(self, r: Recipe) -> dict[str, list[str]]:
        """allergen → the reasons (ingredients or hidden words) it's in this recipe."""
        out: dict[str, list[str]] = {}
        for iid in r.ing:
            ing = self.ingredients.get(iid)
            for a in (ing.allergens if ing else []):
                out.setdefault(a, []).append(ing.name)
        text = " ".join([r.name] + [self.ingredients[i].name if i in self.ingredients else i for i in r.ing])
        for a, ws in self.hidden.items():
            for w in words_in(text, ws, self.exceptions.get(a)):
                out.setdefault(a, []).append(f'"{w}"')
        return {a: sorted(set(v)) for a, v in out.items()}

    def text_allergens(self, text: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for a, ws in self.hidden.items():
            hit = words_in(text, ws, self.exceptions.get(a))
            if hit:
                out[a] = hit
        return out

    # ---------------------------------------------------------------- diet / season
    def is_vegetarian(self, r: Recipe) -> bool:
        return all(self.ingredients[i].cat not in ("meat", "fish") for i in r.ing if i in self.ingredients)

    def is_fish(self, r: Recipe) -> bool:
        return any(self.ingredients[i].cat == "fish" for i in r.ing if i in self.ingredients)

    def in_season(self, iid: str, month: int) -> bool | None:
        """True in its peak months, False outside them, None if it has no local season (store-bought all year)."""
        months = self.season.get(iid)
        return None if not months else month in months

    def season_score(self, r: Recipe, month: int) -> tuple[int, int]:
        ins = outs = 0
        for i in r.ing:
            s = self.in_season(i, month)
            ins += s is True
            outs += s is False
        return ins, outs

    # ---------------------------------------------------------------- mapping free text to the catalog
    def match(self, text: str) -> str | None:
        """Best catalog ingredient for a product line ("Honeycrisp apples, 2 lb bag" → apples)."""
        t = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()) + " "
        best, score = None, 0
        for iid, ing in self.ingredients.items():
            for cand in {ing.name.lower(), iid.replace("_", " ")}:
                words = cand.split()
                if all(f" {w} " in t or f" {w}s " in t or (w.endswith("s") and f" {w[:-1]} " in t) for w in words):
                    if len(cand) > score:
                        best, score = iid, len(cand)
        return best


@lru_cache(maxsize=4)
def get(region: str = "northeast-us") -> Catalog:
    return Catalog(region)


_household_cache: dict[tuple, Catalog] = {}


def for_household(h) -> Catalog:
    """The book plus the household's own ingredients and recipes (from its database)."""
    from . import store
    base = get(h.info.get("region", "northeast-us"))
    con = store.connect()
    try:
        ver = con.execute("SELECT COALESCE(MAX(updated), '') AS v, COUNT(*) AS n FROM custom_recipes").fetchone()
        iver = con.execute("SELECT COALESCE(MAX(updated), '') AS v, COUNT(*) AS n FROM custom_ingredients").fetchone()
        key = (str(store.db_path()), ver["v"], ver["n"], iver["v"], iver["n"])
        if key in _household_cache:
            return _household_cache[key]
        ings = [json.loads(r["data"]) for r in con.execute("SELECT data FROM custom_ingredients")]
        recs = [json.loads(r["data"]) for r in con.execute("SELECT data FROM custom_recipes WHERE active = 1")]
    finally:
        con.close()
    if not ings and not recs:
        return base
    c = copy.copy(base)
    c.ingredients = dict(base.ingredients)
    c.recipes = dict(base.recipes)
    for d in ings:
        c.ingredients[d["id"]] = Ingredient(**{k: v for k, v in d.items() if k in Ingredient.__dataclass_fields__})
    for d in recs:
        c.recipes[d["id"]] = Recipe(**{k: v for k, v in d.items() if k in Recipe.__dataclass_fields__})
    if len(_household_cache) > 64:
        _household_cache.clear()
    _household_cache[key] = c
    return c
