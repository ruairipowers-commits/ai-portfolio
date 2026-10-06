"""From the plan to one shopping list, split across stores (OR-Tools CP-SAT).

1. Quantities: each meal's ingredients × servings, rounded up to whole packs later; minus the pantry; plus the
   dog's food and treats when the bag would run out soon.
2. Split: for every item, pick a store and a pack (this week's specials included, the household's brand rules
   applied); for every store used, pick how to get it (in store, pickup, delivery). Minimize
   item cost + service markup + fees − membership/card credits + your time × your hourly value,
   with order minimums, membership fee waivers and a cap on stores per week.
3. Hand-off: per store, in the format the app that already does it best wants — an Instacart shopping-list link
   (Costco, Stop & Shop delivery), an Amazon list (Whole Foods), an aisle-ordered list to print or send to Reminders
   (in-store trips; Trader Joe's is always in store). Nothing is bought here: a person taps through every one.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from .catalog import Catalog
from .config import Household, Settings, money
from .prices import Offer, PriceBook

CENTS = 100


@dataclass
class Need:
    ingredient: str
    name: str
    qty: float
    unit: str
    for_: list[str] = field(default_factory=list)


@dataclass
class Line:
    ingredient: str
    name: str
    brand: str
    packs: int
    pack: float
    unit: str
    price_each: float
    cost: float
    special: bool
    regular: float | None
    aisle: int
    need: float


@dataclass
class StoreOrder:
    store: str
    store_name: str
    mode: str
    lines: list[Line]
    items_cost: float
    markup: float
    fee: float
    credits: float
    minutes: int
    handoff: str
    total: float = 0.0
    payload: dict = field(default_factory=dict)


@dataclass
class Split:
    orders: list[StoreOrder]
    total: float
    minutes: int
    time_cost: float
    status: str
    solve_ms: int
    unavailable: list[str]
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"total": self.total, "minutes": self.minutes, "status": self.status, "flags": self.flags,
                "unavailable": self.unavailable, "solve_ms": self.solve_ms,
                "orders": [{**{k: v for k, v in o.__dict__.items() if k != "lines"},
                            "lines": [ln.__dict__ for ln in o.lines]} for o in self.orders]}


def needs(plan, c: Catalog, pantry: dict[str, float], pet_restock: dict[str, float]) -> list[Need]:
    total: dict[str, Need] = {}
    for e in plan.entries:
        r = c.recipes.get(e.recipe) or getattr(e, "_recipe", None)
        if r is None:
            continue
        for iid, q in r.ing.items():
            ing = c.ingredients[iid]
            n = total.setdefault(iid, Need(iid, ing.name, 0.0, ing.unit))
            n.qty += q * e.servings
            n.for_.append(f"{e.day} {e.meal}")
    out = []
    for iid, n in total.items():
        left = n.qty - pantry.get(iid, 0)
        if left > 1e-6:
            n.qty = round(left, 3)
            out.append(n)
    for iid, q in pet_restock.items():
        ing = c.ingredients[iid]
        out.append(Need(iid, ing.name, q, ing.unit, ["dog"]))
    return sorted(out, key=lambda n: (c.ingredients[n.ingredient].aisle, n.name))


def _credits(store: str, mode_cfg: dict, h: Household) -> tuple[float, list[dict]]:
    """(percent back on items, fee waivers that apply) from the household's memberships and cards."""
    m = money()
    pct = 0.0
    waivers = []
    for mid in h.raw.get("memberships", []):
        b = m.get("memberships", {}).get(mid, {})
        if (b.get("pct_back") or {}).get("store") == store:
            pct += float(b["pct_back"]["pct"])
        wf = b.get("waive_fee")
        if wf and ((wf.get("service") and wf["service"] == mode_cfg.get("service"))
                   or (wf.get("store") == store and mode_cfg.get("_mode") in wf.get("modes", []))):
            waivers.append({"by": b.get("name", mid), "minimum": float(wf.get("minimum", 0))})
    for cid in h.raw.get("cards", []):
        b = m.get("cards", {}).get(cid, {})
        pb = b.get("pct_back") or {}
        if store in pb.get("stores", []) and not mode_cfg.get("service"):
            pct += float(pb.get("pct", 0))
    return pct, waivers


def split(h: Household, c: Catalog, pb: PriceBook, items: list[Need], s: Settings, *,
          max_stores: int | None = None, only_store: str | None = None, regular_prices: bool = False,
          modes_allowed: tuple[str, ...] | None = None) -> Split:
    t0 = time.perf_counter()
    value_per_min = float(h.info.get("time_value_per_hour", 0)) / 60
    bulk_value = float(s["shopping"]["bulk_leftover_value"])
    stores = [only_store] if only_store else pb.stores
    m = cp_model.CpModel()
    y: dict[tuple, cp_model.IntVar] = {}         # (item idx, offer idx, store, mode)
    u: dict[tuple[str, str], cp_model.IntVar] = {}
    waive: dict[tuple[str, str], cp_model.IntVar] = {}
    offers_for: dict[int, list[tuple[Offer, int]]] = {}
    unavailable = []
    obj = []
    store_total: dict[tuple[str, str], list] = {}
    mode_cfgs: dict[tuple[str, str], dict] = {}
    for st in stores:
        for mode, mc in pb.store_cfg[st]["modes"].items():
            if modes_allowed and mode not in modes_allowed:
                continue
            mc = {**mc, "_mode": mode}
            mode_cfgs[(st, mode)] = mc
            u[(st, mode)] = m.NewBoolVar(f"u_{st}_{mode}")
            store_total[(st, mode)] = []
    for st in stores:
        m.Add(sum(u[(st, md)] for (s2, md) in u if s2 == st) <= 1)
    for k, n in enumerate(items):
        opts = []
        for st in stores:
            for o in pb.offers(n.ingredient, st):
                if regular_prices and o.special:
                    o = Offer(o.store, o.ingredient, o.brand, o.pack, o.regular or o.price, o.organic, False, None,
                              o.preferred)
                packs = max(1, math.ceil(n.qty / o.pack - 1e-9))
                shelf = c.ingredients[n.ingredient].shelf
                spare = packs * o.pack - n.qty
                spare_credit = (spare / o.pack) * o.price * bulk_value if shelf >= 14 else 0.0
                opts.append((o, packs))
                for (s2, md), mc in mode_cfgs.items():
                    if s2 != st:
                        continue
                    pct, _ = _credits(st, mc, h)
                    cost = packs * o.price * (1 + float(mc.get("markup", 0)))
                    v = m.NewBoolVar(f"y_{k}_{len(opts)}_{st}_{md}")
                    y[(k, len(opts) - 1, st, md)] = v
                    m.AddImplication(v, u[(st, md)])
                    store_total[(st, md)].append(int(round(cost * CENTS)) * v)
                    penalty = 0.0 if o.preferred else 0.75
                    obj.append(int(round((cost * (1 - pct) - spare_credit + penalty) * CENTS)) * v)
        offers_for[k] = opts
        vs = [v for (kk, _, _, _), v in y.items() if kk == k]
        if vs:
            m.AddExactlyOne(vs)
        else:
            unavailable.append(n.name)
    for (st, md), mc in mode_cfgs.items():
        uv = u[(st, md)]
        tot = sum(store_total[(st, md)]) if store_total[(st, md)] else 0
        minimum = float(mc.get("minimum", 0))
        if minimum and store_total[(st, md)]:
            m.Add(tot >= int(minimum * CENTS)).OnlyEnforceIf(uv)
        fee = float(mc.get("fee", 0))
        _, waivers = _credits(st, mc, h)
        if fee and waivers and store_total[(st, md)]:
            wv = m.NewBoolVar(f"w_{st}_{md}")
            waive[(st, md)] = wv
            m.AddImplication(wv, uv)
            m.Add(tot >= int(min(w["minimum"] for w in waivers) * CENTS)).OnlyEnforceIf(wv)
            obj.append(int(round(fee * CENTS)) * uv - int(round(fee * CENTS)) * wv)
        elif fee:
            obj.append(int(round(fee * CENTS)) * uv)
        obj.append(int(round(float(mc.get("minutes", 0)) * value_per_min * CENTS)) * uv)
        if not store_total[(st, md)]:
            m.Add(uv == 0)
    cap = max_stores if max_stores is not None else pb.max_stores
    m.Add(sum(u.values()) <= cap)
    m.Minimize(sum(obj))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(s["shopping"]["max_solver_seconds"])
    solver.parameters.num_workers = 1                # one worker: the same plan every run (reproducible)
    solver.parameters.random_seed = 1
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Split([], 0.0, 0, 0.0, solver.StatusName(status), int((time.perf_counter() - t0) * 1000),
                     unavailable, ["no_split"])
    orders: dict[tuple[str, str], StoreOrder] = {}
    for (k, oi, st, md), v in y.items():
        if not solver.Value(v):
            continue
        n = items[k]
        o, packs = offers_for[k][oi]
        mc = mode_cfgs[(st, md)]
        so = orders.setdefault((st, md), StoreOrder(st, pb.store_cfg[st]["name"], md, [], 0, 0, 0, 0,
                                                    int(mc.get("minutes", 0)),
                                                    mc.get("handoff") or pb.store_cfg[st].get("handoff", "print")))
        cost = packs * o.price
        so.lines.append(Line(n.ingredient, n.name, o.brand, packs, o.pack, n.unit, o.price, round(cost, 2), o.special,
                             o.regular, c.ingredients[n.ingredient].aisle, round(n.qty, 2)))
    total = 0.0
    minutes = 0
    for (st, md), so in orders.items():
        mc = mode_cfgs[(st, md)]
        pct, waivers = _credits(st, mc, h)
        so.lines.sort(key=lambda ln: (ln.aisle, ln.name))
        so.items_cost = round(sum(ln.cost for ln in so.lines), 2)
        so.markup = round(so.items_cost * float(mc.get("markup", 0)), 2)
        fee = float(mc.get("fee", 0))
        if (st, md) in waive and solver.Value(waive[(st, md)]):
            fee = 0.0
        so.fee = fee
        so.credits = round((so.items_cost + so.markup) * pct, 2)
        so.total = round(so.items_cost + so.markup + so.fee - so.credits, 2)
        so.payload = handoff_payload(so, h)
        total += so.total
        minutes += so.minutes
    out = sorted(orders.values(), key=lambda o: -o.total)
    return Split(out, round(total, 2), minutes, round(minutes * value_per_min, 2), solver.StatusName(status),
                 int((time.perf_counter() - t0) * 1000), unavailable)


def handoff_payload(so: StoreOrder, h: Household) -> dict:
    """What each hand-off sends. Instacart: the body for POST /idp/v1/products/products_link (Developer Platform),
    which returns a products_link_url the person opens to pick the store and check out."""
    if so.handoff == "instacart":
        org = (h.raw.get("brands") or {})
        return {"title": f"Lil'Helper: {so.store_name} this week", "link_type": "shopping_list", "expires_in": 7,
                "instructions": [f"Choose {so.store_name} if Instacart suggests another store."],
                "line_items": [{"name": ln.name, "quantity": ln.packs, "unit": "package",
                                "display_text": f"{ln.name} ({ln.brand})",
                                "filters": {"brand_filters": [ln.brand.replace(' Organic', '')],
                                            **({"health_filters": ["ORGANIC"]} if (org.get(ln.ingredient) or {}).get("organic") else {})}}
                               for ln in so.lines],
                "landing_page_configuration": {"enable_pantry_items": False}}
    if so.handoff == "amazon":
        return {"list_name": f"Lil'Helper {so.store_name}", "items": [f"{ln.packs} × {ln.name} ({ln.brand})" for ln in so.lines]}
    return {"aisle_ordered": [f"☐ {ln.packs} × {ln.name} — {ln.brand}{' (special)' if ln.special else ''}"
                              for ln in so.lines]}
