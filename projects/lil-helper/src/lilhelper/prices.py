"""This week's prices: shelf prices per store, confirmed specials on top, and the household's brand rules.

Where a price comes from, most trusted first:
  1. what the household actually paid (a confirmed receipt, last 60 days) — replaces the shelf price for that pack
  2. prices the household entered for its own ingredients
  3. data/prices.yaml (the starter price list, with a `verified` date per store)
Specials sit on top: from the household (entered in the app or read from a flyer and confirmed, one week or every
week), member deals that need a membership the household has (e.g. Prime at Whole Foods), and the starter flyers.
A special can be in-store only, online only (pickup or delivery) or both.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import yaml

from .config import ROOT, Household, stores as load_stores

ONLINE = ("pickup", "delivery")


@dataclass
class Offer:
    store: str
    ingredient: str
    brand: str
    pack: float
    price: float
    organic: bool = False
    special: bool = False
    regular: float | None = None
    preferred: bool = True
    channel: str = "any"          # where the special applies: any | in_store | online
    seen: bool = False            # price from a receipt the household confirmed

    @property
    def unit(self) -> float:
        return self.price / self.pack

    def for_mode(self, mode: str) -> "Offer":
        """This offer as priced for one way of shopping: a special for the other channel doesn't apply."""
        if not self.special or self.channel == "any" or (self.channel == "in_store") == (mode == "in_store"):
            return self
        return Offer(self.store, self.ingredient, self.brand, self.pack, self.regular or self.price, self.organic,
                     False, None, self.preferred, "any", self.seen)


def week_start(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


class PriceBook:
    def __init__(self, h: Household, week_of: dt.date, extra_specials: list[dict] | None = None,
                 enabled: list[str] | None = None, observed: dict[tuple[str, str], float] | None = None,
                 catalog=None):
        self.h = h
        self.week_of = week_start(week_of)
        cfg = load_stores()
        self.store_cfg = cfg["stores"]
        self.max_stores = int(cfg.get("max_stores_per_week", 3))
        members = set(h.raw.get("memberships", []))
        wanted = enabled or h.raw.get("stores", list(self.store_cfg))
        self.stores = [s for s in wanted if s in self.store_cfg
                       and (not self.store_cfg[s].get("needs") or self.store_cfg[s]["needs"] in members)]
        shelf = yaml.safe_load((ROOT / "data" / "prices.yaml").read_text())["stores"]
        self.shelf = {s: dict(shelf.get(s, {})) for s in self.stores}
        # the household's own ingredients carry their own prices
        for iid, ing in ((catalog.ingredients.items()) if catalog is not None else []):
            for st, p in (getattr(ing, "prices", None) or {}).items():
                if st in self.shelf and iid not in self.shelf[st]:
                    self.shelf[st][iid] = [{"brand": p.get("brand", "any"), "pack": float(p.get("pack", 1)),
                                            "price": float(p["price"]), "organic": bool(p.get("organic"))}]
        # prices the household actually paid (confirmed receipts) replace the file's shelf price for that pack
        self.observed = dict(observed or {})
        for (st, iid), price in self.observed.items():
            if st in self.shelf and self.shelf[st].get(iid):
                first = dict(self.shelf[st][iid][0])
                first["price"], first["seen"] = price, True
                self.shelf[st] = {**self.shelf[st], iid: [first] + list(self.shelf[st][iid][1:])}
        from .money import member_deals
        allowed = member_deals(h)
        self.specials = [sp for sp in self._load_specials() + list(extra_specials or [])
                         if not sp.get("member") or sp["member"] in allowed]
        self.brand_rules = h.raw.get("brands", {}) or {}

    def _load_specials(self) -> list[dict]:
        p = ROOT / "data" / "specials" / f"week-{self.week_of.isoformat()}.yaml"
        return (yaml.safe_load(p.read_text()) or {}).get("items", []) if p.exists() else []

    def offers(self, iid: str, store: str | None = None, mode: str | None = None) -> list[Offer]:
        out: list[Offer] = []
        rule = self.brand_rules.get(iid, {}) or {}
        if rule.get("banned"):
            return []
        for s in ([store] if store else self.stores):
            for o in self.shelf.get(s, {}).get(iid, []):
                off = Offer(s, iid, o["brand"], float(o["pack"]), float(o["price"]), bool(o.get("organic")),
                            seen=bool(o.get("seen")))
                for sp in self.specials:
                    if (sp["store"] == s and sp["ingredient"] == iid and sp.get("brand", off.brand) in (off.brand, "any")
                            and not sp.get("flagged") and float(sp["price"]) < off.price):
                        off.regular, off.price, off.special = off.price, float(sp["price"]), True
                        off.channel = sp.get("channel") or "any"
                if rule.get("organic") and not off.organic:
                    continue
                if rule.get("prefer"):
                    off.preferred = rule["prefer"].lower() in off.brand.lower()
                out.append(off.for_mode(mode) if mode else off)
        return out

    def best_unit(self, iid: str) -> float | None:
        """Cheapest price per unit anywhere this week (the planner's cost estimate; the shopper does the real split)."""
        units = [o.unit for o in self.offers(iid)]
        return min(units) if units else None

    def regular_unit_at(self, iid: str, store: str) -> float | None:
        """Shelf price per unit at one store, ignoring specials (the "before" baseline)."""
        rule = self.brand_rules.get(iid, {}) or {}
        units = [float(o["price"]) / float(o["pack"]) for o in self.shelf.get(store, {}).get(iid, [])
                 if not (rule.get("organic") and not o.get("organic"))]
        return min(units) if units else None

    def on_special(self, iid: str) -> bool:
        return any(o.special for o in self.offers(iid))

    def sold_anywhere(self, iid: str) -> bool:
        return bool(self.offers(iid))
