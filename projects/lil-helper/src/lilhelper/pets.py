"""The dog's week: food and treats restocked with the groceries, and plain, dog-safe extras set aside from family
meals before they're seasoned. Every extra passes the toxic-food check; extras are capped at a share of daily
calories (common vet guidance is 10%). Not veterinary advice: the household's vet notes are blocked like the toxic
list."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import safety
from .catalog import Catalog
from .config import Household, Settings

# Rough calories per unit for the plain extras we suggest (for the cap only).
KCAL = {"chicken_breast": 750, "chicken_thighs": 800, "ground_turkey": 680, "salmon": 900, "cod": 380,
        "carrots": 180, "green_beans": 140, "sweet_potatoes": 390, "butternut_squash": 300, "pumpkin_puree": 80,
        "zucchini": 33, "apples": 95, "blueberries": 85, "rice": 220, "oats": 300, "eggs": 70, "frozen_peas": 120,
        "yogurt": 150, "cucumber": 45}
SERVING = {"lb": 0.06, "each": 0.25, "cup": 0.25, "can": 0.1}     # a dog-sized bit in the ingredient's unit


@dataclass
class PetWeek:
    pet: str
    name: str
    food_needed: float
    food_on_hand: float
    restock: dict[str, float]
    extras: list[dict] = field(default_factory=list)
    blocked: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def pet_week(h: Household, c: Catalog, plan, pantry: dict[str, float], s: Settings) -> list[PetWeek]:
    out = []
    ahead = int(s["pets"]["restock_days_ahead"])
    for pet in h.pets.values():
        food = pet.food
        need = food["cups_per_day"] * 7
        on_hand = pantry.get(food["ingredient"], 0)
        restock: dict[str, float] = {}
        if on_hand - need < food["cups_per_day"] * ahead:
            bags = math.ceil((need + food["cups_per_day"] * ahead - on_hand) / food["bag_cups"])
            restock[food["ingredient"]] = bags * food["bag_cups"]
        treats = pet.treats_per_day * 7
        if pantry.get("dog_treats", 0) < treats:
            restock["dog_treats"] = treats * 4
        pw = PetWeek(pet.id, pet.name, need, on_hand, restock)
        if pet.extras and plan is not None:
            cap = pet.kcal_per_day * float(s["pets"]["extras_max_share"])
            for e in plan.entries:
                r = c.recipes.get(e.recipe)
                if not r or e.meal != "dinner":
                    continue
                for iid in r.dog:
                    v = safety.dog_item(c, pet, iid)
                    if not v.ok:
                        pw.blocked.append({"day": e.day, "item": c.ingredients.get(iid, None) and c.ingredients[iid].name
                                           or iid, "why": v.reasons})
                        continue
                    if iid not in r.ing:
                        continue
                    ing = c.ingredients[iid]
                    amt = SERVING.get(ing.unit, 0.25)
                    kcal = KCAL.get(iid, 100) * amt
                    if kcal > cap:
                        amt = round(amt * cap / kcal, 3)
                        kcal = cap
                    pw.extras.append({"day": e.day, "item": ing.name, "amount": amt, "unit": ing.unit,
                                      "kcal": round(kcal), "from": e.name,
                                      "how": "set aside plain, before oil, salt, onion or garlic go in"})
                    break                                    # one extra per dinner is plenty
            pw.notes.append(f"Extras stay under {int(float(s['pets']['extras_max_share']) * 100)}% of "
                            f"{pet.name}'s daily calories. Check new foods with your vet.")
        out.append(pw)
    return out
