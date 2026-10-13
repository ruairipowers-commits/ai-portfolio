"""From the plan to one shopping list, split across stores and shopping trips (OR-Tools CP-SAT).

1. Quantities: each meal's ingredients × servings, rounded up to whole packs later; minus the pantry; plus the
   dog's food and treats when the bag would run out soon. Each item knows the first day it's needed.
2. Split: for every item, pick a store, a way to get it and a pack (this week's specials included — an in-store
   special doesn't apply to a delivery order — and the household's brand rules applied). If the household has
   scheduled shopping trips (e.g. Costco Saturday morning, Whole Foods pickup Wednesday), items go to a trip before
   the day they're needed, and perishables to one close enough that they'll still be good. Minimize
   item cost + service markup + fees − card and membership rewards + your time × your hourly value,
   with order minimums, membership fee waivers, a cap on stores per week (without scheduled trips) and the free
   space in the fridge and freezer (so a giant Costco pack that won't fit costs more than it saves).
3. Hand-off: per store and trip, in the format the app that already does it best wants — an Instacart
   shopping-list link, an Amazon list (Whole Foods), an aisle-ordered list to print or send to Reminders (in-store
   trips; Trader Joe's is always in store). Nothing is bought here: a person taps through every one.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from . import money
from .catalog import Catalog
from .config import DAYS, Household, Settings
from .prices import Offer, PriceBook

CENTS = 100
SESSION_DAY = {**{d: i for i, d in enumerate(DAYS)}, "sun_before": -1, "sat_before": -2}


@dataclass
class Need:
    ingredient: str
    name: str
    qty: float
    unit: str
    for_: list[str] = field(default_factory=list)
    need_day: int = 0                       # index into the week of the first use (0 = Monday)


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
    storage: str = "pantry"
    litres: float = 0.0
    need_day: int = 0


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
    session: str | None = None              # scheduled trip id
    day: str | None = None                  # the trip's day (mon..sun, or sun_before)
    time: str | None = None
    who: str | None = None
    card: str | None = None                 # the card that earns the most here
    card_name: str = ""
    card_note: str = ""
    rewards: float = 0.0                    # what that card (plus any store reward) earns on this order


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
    storage_used: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"total": self.total, "minutes": self.minutes, "status": self.status, "flags": self.flags,
                "unavailable": self.unavailable, "solve_ms": self.solve_ms, "storage_used": self.storage_used,
                "orders": [{**{k: v for k, v in o.__dict__.items() if k != "lines"},
                            "lines": [ln.__dict__ for ln in o.lines]} for o in self.orders]}


def needs(plan, c: Catalog, pantry: dict[str, float], pet_restock: dict[str, float]) -> list[Need]:
    total: dict[str, Need] = {}
    for e in plan.entries:
        if getattr(e, "kind", "cook") != "cook":
            continue
        r = c.recipes.get(e.recipe) or getattr(e, "_recipe", None)
        if r is None:
            continue
        first = DAYS.index(getattr(e, "prep_day", e.day) or e.day)
        for iid, q in r.ing.items():
            ing = c.ingredients[iid]
            n = total.setdefault(iid, Need(iid, ing.name, 0.0, ing.unit, [], 6))
            n.qty += q * e.servings
            n.for_.append(f"{e.day} {e.meal}")
            n.need_day = min(n.need_day, first)
    out = []
    for iid, n in total.items():
        left = n.qty - pantry.get(iid, 0)
        if left > 1e-6:
            n.qty = round(left, 3)
            out.append(n)
    for iid, q in pet_restock.items():
        ing = c.ingredients[iid]
        out.append(Need(iid, ing.name, q, ing.unit, ["dog"], 0))
    return sorted(out, key=lambda n: (c.ingredients[n.ingredient].aisle, n.name))


def _credits(store: str, mode_cfg: dict, h: Household) -> tuple[float, list[dict]]:
    """(share of the order that comes back, fee waivers that apply) from the household's cards and memberships."""
    return money.order_pct(h, store, mode_cfg), money.waivers(h, store, mode_cfg)


def _options(h: Household, pb: PriceBook, stores: list[str], modes_allowed, sessions: list[dict] | None):
    """Ways to buy: (key, store, mode, mode config, session). Without scheduled trips, one per store and mode."""
    out = []
    if sessions:
        for sess in sessions:
            st, md = sess["store"], sess["mode"]
            if st not in stores or md not in pb.store_cfg[st]["modes"]:
                continue
            mc = {**pb.store_cfg[st]["modes"][md], "_mode": md}
            out.append((sess["id"], st, md, mc, sess))
        return out
    for st in stores:
        for md, mc in pb.store_cfg[st]["modes"].items():
            if modes_allowed and md not in modes_allowed:
                continue
            out.append((f"{st}:{md}", st, md, {**mc, "_mode": md}, None))
    return out


def split(h: Household, c: Catalog, pb: PriceBook, items: list[Need], s: Settings, *,
          max_stores: int | None = None, only_store: str | None = None, regular_prices: bool = False,
          modes_allowed: tuple[str, ...] | None = None, sessions: list[dict] | None = None,
          storage_free: dict[str, float] | None = None, ytd: dict | None = None) -> Split:
    t0 = time.perf_counter()
    value_per_min = float(h.info.get("time_value_per_hour", 0)) / 60
    bulk_value = float(s["shopping"]["bulk_leftover_value"])
    stores = [only_store] if only_store else pb.stores
    sessions = sessions if sessions is not None else (h.sessions() if not only_store else None)
    opts_all = _options(h, pb, stores, modes_allowed, sessions)
    m = cp_model.CpModel()
    y: dict[tuple, cp_model.IntVar] = {}             # (item idx, offer idx, option key)
    u: dict[str, cp_model.IntVar] = {}
    waive: dict[str, cp_model.IntVar] = {}
    offers_for: dict[int, list[tuple[Offer, int]]] = {}
    unavailable, flags = [], []
    obj = []
    opt_total: dict[str, list] = {}
    opt = {k: (st, md, mc, sess) for k, st, md, mc, sess in opts_all}
    for k in opt:
        u[k] = m.NewBoolVar(f"u_{k}")
        opt_total[k] = []
    if not sessions:
        for st in stores:
            m.Add(sum(u[k] for k, (s2, _, _, _) in opt.items() if s2 == st) <= 1)
    vol: dict[str, list] = {"fridge": [], "freezer": []}
    late = []
    for k_i, n in enumerate(items):
        ing = c.ingredients[n.ingredient]
        keeps = max(ing.shelf, ing.keeps_for(frozen=True))
        okeys = list(opt)
        if sessions:
            fit = [k for k in okeys if SESSION_DAY[opt[k][3]["day"]] <= n.need_day
                   and n.need_day - SESSION_DAY[opt[k][3]["day"]] <= keeps]
            if not fit:                               # no trip early enough: the earliest trip, flagged
                fit = sorted(okeys, key=lambda k: SESSION_DAY[opt[k][3]["day"]])[:1]
                if fit:
                    late.append(n.name)
            okeys = fit
        offers: list[tuple[Offer, int]] = []
        for key in okeys:
            st, md, mc, sess = opt[key]
            for o in pb.offers(n.ingredient, st, md):
                if regular_prices and o.special:
                    o = Offer(o.store, o.ingredient, o.brand, o.pack, o.regular or o.price, o.organic, False, None,
                              o.preferred)
                packs = max(1, math.ceil(n.qty / o.pack - 1e-9))
                spare = packs * o.pack - n.qty
                spare_credit = (spare / o.pack) * o.price * bulk_value if ing.shelf >= 14 else 0.0
                offers.append((o, packs))
                pct, _ = _credits(st, mc, h)
                cost = packs * o.price * (1 + float(mc.get("markup", 0)))
                v = m.NewBoolVar(f"y_{k_i}_{len(offers)}_{key}")
                y[(k_i, len(offers) - 1, key)] = v
                m.AddImplication(v, u[key])
                opt_total[key].append(int(round(cost * CENTS)) * v)
                penalty = 0.0 if o.preferred else 0.75
                obj.append(int(round((cost * (1 - pct) - spare_credit + penalty) * CENTS)) * v)
                if ing.storage in vol:
                    vol[ing.storage].append(int(round(packs * o.pack * ing.litres * 10)) * v)   # decilitres
        offers_for[k_i] = offers
        vs = [v for (kk, _, _), v in y.items() if kk == k_i]
        if vs:
            m.AddExactlyOne(vs)
        else:
            unavailable.append(n.name)
    for key, (st, md, mc, sess) in opt.items():
        uv = u[key]
        tot = sum(opt_total[key]) if opt_total[key] else 0
        minimum = float(mc.get("minimum", 0))
        if minimum and opt_total[key]:
            m.Add(tot >= int(minimum * CENTS)).OnlyEnforceIf(uv)
        fee = float(mc.get("fee", 0))
        _, waivers = _credits(st, mc, h)
        if fee and waivers and opt_total[key]:
            wv = m.NewBoolVar(f"w_{key}")
            waive[key] = wv
            m.AddImplication(wv, uv)
            m.Add(tot >= int(min(w["minimum"] for w in waivers) * CENTS)).OnlyEnforceIf(wv)
            obj.append(int(round(fee * CENTS)) * uv - int(round(fee * CENTS)) * wv)
        elif fee:
            obj.append(int(round(fee * CENTS)) * uv)
        obj.append(int(round(float(mc.get("minutes", 0)) * value_per_min * CENTS)) * uv)
        if not opt_total[key]:
            m.Add(uv == 0)
    if not sessions:
        cap = max_stores if max_stores is not None else pb.max_stores
        m.Add(sum(u.values()) <= cap)
    # space: going over the free fridge or freezer space costs $2 a litre (it won't fit, or something spoils)
    for kind, terms in vol.items():
        free = (storage_free or {}).get(kind)
        if free is not None and terms:
            over = m.NewIntVar(0, 10 ** 7, f"over_{kind}")
            m.Add(sum(terms) - over <= int(max(0.0, free) * 10))
            obj.append(20 * over)                   # 200 cents per litre = 20 per decilitre
    m.Minimize(sum(obj))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(s["shopping"]["max_solver_seconds"])
    solver.parameters.num_workers = 1                # one worker: the same plan every run (reproducible)
    solver.parameters.random_seed = 1
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Split([], 0.0, 0, 0.0, solver.StatusName(status), int((time.perf_counter() - t0) * 1000),
                     unavailable, ["no_split"])
    orders: dict[str, StoreOrder] = {}
    for (k_i, oi, key), v in y.items():
        if not solver.Value(v):
            continue
        n = items[k_i]
        o, packs = offers_for[k_i][oi]
        st, md, mc, sess = opt[key]
        so = orders.get(key)
        if so is None:
            so = orders[key] = StoreOrder(st, pb.store_cfg[st]["name"], md, [], 0, 0, 0, 0, int(mc.get("minutes", 0)),
                                          mc.get("handoff") or pb.store_cfg[st].get("handoff", "print"))
            if sess:
                so.session, so.day, so.time, so.who = sess["id"], sess["day"], sess.get("time"), sess.get("who")
        ing = c.ingredients[n.ingredient]
        so.lines.append(Line(n.ingredient, n.name, o.brand, packs, o.pack, n.unit, o.price, round(packs * o.price, 2),
                             o.special, o.regular, ing.aisle, round(n.qty, 2), ing.storage,
                             round(packs * o.pack * ing.litres, 2), n.need_day))
    total = 0.0
    minutes = 0
    used = dict(ytd or {})
    for key in sorted(orders, key=lambda k: SESSION_DAY.get((opt[k][3] or {}).get("day"), 0)):
        so = orders[key]
        st, md, mc, sess = opt[key]
        _, waivers = _credits(st, mc, h)
        so.lines.sort(key=lambda ln: (ln.aisle, ln.name))
        so.items_cost = round(sum(ln.cost for ln in so.lines), 2)
        so.markup = round(so.items_cost * float(mc.get("markup", 0)), 2)
        fee = float(mc.get("fee", 0))
        if key in waive and solver.Value(waive[key]):
            fee = 0.0
        so.fee = fee
        amount = so.items_cost + so.markup + so.fee
        pick = money.best_card(h, st, md, amount, mc, used)
        store_pct, store_cap, _ = money.store_reward(h, st)
        so.card, so.card_name, so.card_note = pick.card, pick.name, pick.note
        so.rewards = round(pick.earned + (so.items_cost + so.markup) * store_pct, 2)
        if pick.card:
            used[(pick.card, pick.category)] = used.get((pick.card, pick.category), 0.0) + amount
        so.credits = so.rewards
        so.total = round(amount - so.credits, 2)
        so.payload = handoff_payload(so, h)
        total += so.total
        minutes += so.minutes
    if late:
        flags.append(f"no scheduled trip early enough for: {', '.join(sorted(set(late)))}")
    used_l = {k: round(sum(ln.litres for o in orders.values() for ln in o.lines if ln.storage == k), 1)
              for k in ("fridge", "freezer")}
    for k, v in used_l.items():
        free = (storage_free or {}).get(k)
        if free is not None and v > free:
            flags.append(f"this shop needs about {v:.0f} L of {k} space; about {free:.0f} L is free")
    out = sorted(orders.values(), key=lambda o: (SESSION_DAY.get(o.day, 0) if o.day else 0, -o.total))
    return Split(out, round(total, 2), minutes, round(minutes * value_per_min, 2), solver.StatusName(status),
                 int((time.perf_counter() - t0) * 1000), unavailable, flags, used_l)


def handoff_payload(so: StoreOrder, h: Household) -> dict:
    """What each hand-off sends. Instacart: the body for POST /idp/v1/products/products_link (Developer Platform),
    which returns a products_link_url the person opens to pick the store and check out."""
    when = f" ({so.day} {so.time})" if so.day and so.time else ""
    if so.handoff == "instacart":
        org = (h.raw.get("brands") or {})
        return {"title": f"Lil'Helper: {so.store_name}{when}", "link_type": "shopping_list", "expires_in": 7,
                "instructions": [f"Choose {so.store_name} if Instacart suggests another store."],
                "line_items": [{"name": ln.name, "quantity": ln.packs, "unit": "package",
                                "display_text": f"{ln.name} ({ln.brand})",
                                "filters": {"brand_filters": [ln.brand.replace(' Organic', '')],
                                            **({"health_filters": ["ORGANIC"]} if (org.get(ln.ingredient) or {}).get("organic") else {})}}
                               for ln in so.lines],
                "landing_page_configuration": {"enable_pantry_items": False}}
    if so.handoff == "amazon":
        return {"list_name": f"Lil'Helper {so.store_name}{when}",
                "items": [f"{ln.packs} × {ln.name} ({ln.brand})" for ln in so.lines]}
    return {"aisle_ordered": [f"☐ {ln.packs} × {ln.name} — {ln.brand}{' (special)' if ln.special else ''}"
                              for ln in so.lines]}
