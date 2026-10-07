"""This week's prices: shelf prices per store, confirmed specials on top, and the household's brand rules."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import ROOT, Household, stores as load_stores


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

    @property
    def unit(self) -> float:
        return self.price / self.pack


def week_start(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


class PriceBook:
    def __init__(self, h: Household, week_of: dt.date, extra_specials: list[dict] | None = None,
                 enabled: list[str] | None = None):
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
        self.shelf = {s: shelf.get(s, {}) for s in self.stores}
        self.specials = self._load_specials() + list(extra_specials or [])
        self.brand_rules = h.raw.get("brands", {}) or {}

    def _load_specials(self) -> list[dict]:
        p = ROOT / "data" / "specials" / f"week-{self.week_of.isoformat()}.yaml"
        return (yaml.safe_load(p.read_text()) or {}).get("items", []) if p.exists() else []

    def offers(self, iid: str, store: str | None = None) -> list[Offer]:
        out: list[Offer] = []
        rule = self.brand_rules.get(iid, {}) or {}
        if rule.get("banned"):
            return []
        for s in ([store] if store else self.stores):
            for o in self.shelf.get(s, {}).get(iid, []):
                off = Offer(s, iid, o["brand"], float(o["pack"]), float(o["price"]), bool(o.get("organic")))
                for sp in self.specials:
                    if (sp["store"] == s and sp["ingredient"] == iid and sp.get("brand", off.brand) == off.brand
                            and not sp.get("flagged")):
                        off.regular, off.price, off.special = off.price, float(sp["price"]), True
                if rule.get("organic") and not off.organic:
                    continue
                if rule.get("prefer"):
                    off.preferred = rule["prefer"].lower() in off.brand.lower()
                out.append(off)
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
