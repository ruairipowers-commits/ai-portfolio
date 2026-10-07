"""Savings in dollars, time and satisfaction — each against a stated baseline, so the number means something.

Dollars: the same list bought at the household's home store at regular shelf prices, in one trip (anything the
         home store doesn't carry priced at the cheapest regular price elsewhere, plus that second trip's time).
Time:    planning minutes before (the household's own estimate) vs the minutes a person spent approving this
         week (measured in the app), plus store minutes before vs after.
Satisfaction: the family's average meal rating this week, and the change vs the previous four weeks.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .config import Household
from .prices import PriceBook


@dataclass
class Savings:
    baseline_dollars: float
    plan_dollars: float
    dollars_saved: float
    specials_saved: float
    credits: float
    baseline_minutes: int
    plan_minutes: int
    planning_before: int
    planning_after: float
    minutes_saved: float
    rating: float | None
    rating_change: float | None
    notes: list[str]

    def to_dict(self) -> dict:
        return self.__dict__


def baseline(h: Household, pb: PriceBook, items) -> tuple[float, int, list[str]]:
    home = h.raw.get("home_store") or pb.stores[0]
    total = 0.0
    elsewhere = []
    for n in items:
        unit = pb.regular_unit_at(n.ingredient, home)
        where = home
        if unit is None:
            alts = [(pb.regular_unit_at(n.ingredient, s), s) for s in pb.stores if s != home]
            alts = [a for a in alts if a[0] is not None]
            if not alts:
                continue
            unit, where = min(alts)
            elsewhere.append(n.name)
        offers = pb.shelf[where][n.ingredient]
        pack = float(offers[0]["pack"])
        total += math.ceil(n.qty / pack - 1e-9) * pack * unit
    minutes = int(pb.store_cfg[home]["modes"]["in_store"]["minutes"])
    if elsewhere:
        minutes += 30
    return round(total, 2), minutes, elsewhere


def compute(h: Household, pb: PriceBook, items, split, approve_minutes: float, ratings_week: list[float],
            ratings_before: list[float]) -> Savings:
    base, base_min, elsewhere = baseline(h, pb, items)
    specials = round(sum((ln.regular - ln.price_each) * ln.packs for o in split.orders for ln in o.lines
                         if ln.special and ln.regular), 2)
    credits = round(sum(o.credits for o in split.orders), 2)
    before_plan = int(h.info.get("planning_minutes_before", 60))
    notes = []
    if elsewhere:
        notes.append(f"Baseline buys {', '.join(elsewhere)} elsewhere (not sold at the home store) — one more trip.")
    rating = round(sum(ratings_week) / len(ratings_week), 2) if ratings_week else None
    prev = round(sum(ratings_before) / len(ratings_before), 2) if ratings_before else None
    return Savings(base, split.total, round(base - split.total, 2), specials, credits, base_min, split.minutes,
                   before_plan, round(approve_minutes, 1),
                   round((before_plan - approve_minutes) + (base_min - split.minutes), 1),
                   rating, round(rating - prev, 2) if rating is not None and prev is not None else None, notes)
