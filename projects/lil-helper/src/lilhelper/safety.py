"""Rules a model can't override: allergies and diets for people, toxic foods for pets, and treating outside text
as data. Every plan, suggestion, special and dog extra passes through here (NFR-1, SEC-02)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .catalog import Catalog, Recipe, words_in
from .config import Household, Person, Pet

DIET_RULES = {
    "vegetarian": lambda c, r: c.is_vegetarian(r),
    "pescatarian": lambda c, r: all(c.ingredients[i].cat != "meat" for i in r.ing if i in c.ingredients),
    "no_pork": lambda c, r: not any(i in ("pork_tenderloin", "bacon", "sausage") for i in r.ing),
}


@dataclass
class Verdict:
    ok: bool
    reasons: list[str]


def recipe_for(c: Catalog, r: Recipe, people: list[Person]) -> Verdict:
    """Can everyone eating this meal have it? Allergies (incl. hidden sources) and diets are hard rules."""
    reasons = []
    found = c.allergens_of(r)
    for p in people:
        for a in p.allergies:
            if a in found:
                reasons.append(f"{a} ({', '.join(found[a])}) — someone is allergic")
        for d in p.diet:
            rule = DIET_RULES.get(d)
            if rule and not rule(c, r):
                reasons.append(f"not {d}")
    unknown = [i for i in r.ing if i not in c.ingredients]
    if unknown:
        reasons.append(f"unknown ingredients {unknown}")
    return Verdict(not reasons, sorted(set(reasons)))


def dog_item(c: Catalog, pet: Pet, iid_or_text: str) -> Verdict:
    """Is this OK for the dog? Toxic list (word match, so "garlic chicken" fails too), plus anything the vet named."""
    ing = c.ingredients.get(iid_or_text)
    text = ing.name if ing else iid_or_text
    reasons = []
    if ing and ing.dog == "toxic":
        reasons.append(f"{ing.name} is toxic to dogs")
    hits = words_in(text, c.dog_toxic_words)
    if hits:
        reasons.append(f"contains {', '.join(hits)} (toxic to dogs)")
    vet = [w.strip() for w in re.split(r"[,;\n]", pet.vet_notes or "") if w.strip()]
    if vet and words_in(text, vet):
        reasons.append("your vet said to avoid it")
    if ing and ing.dog != "safe" and not reasons:
        reasons.append("not on the dog-safe list")
    return Verdict(not reasons, sorted(set(reasons)))


INSTRUCTION = re.compile(
    r"\b(ignore|disregard|override|forget)\b.{0,40}\b(instruction|rule|allerg|list|previous|above)|"
    r"^\s*(system|assistant|developer)\s*:|\byou are now\b|\badd .{0,30} to (every|all)\b",
    re.I | re.M)


def looks_like_instruction(text: str) -> bool:
    """Flag text from outside (flyers, recipe pages, a model's reply) that tries to give orders. It is never obeyed —
    outside text only ever fills data fields — this just tells the person it was there (SEC-02)."""
    return bool(INSTRUCTION.search(text or ""))


def check_card_name(name: str, pattern: str) -> None:
    if re.search(pattern, name or ""):
        raise ValueError("That looks like a card number. Lil'Helper only stores a name you'd recognise.")


def people_for(h: Household, meal: str) -> list[Person]:
    return h.eaters(meal)
