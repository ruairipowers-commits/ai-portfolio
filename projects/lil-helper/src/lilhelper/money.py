"""Cards, memberships and partnerships: what a household earns back, and which card to pay with where.

Everything here is arithmetic on the household's own settings (config/money.yaml templates, overridden or extended in
the household's settings). A model is never asked which card to use.

  best_card    for one order (store, mode, amount): the accepted card that earns the most, counting this calendar
               year's spending against each card's category cap
  order_pct    the rate the store split uses while it chooses stores (best uncapped card + store rewards)
  credits_for  monthly credits (e.g. Uber Cash) that a takeout night can use
"""
from __future__ import annotations

import copy
import datetime as dt
from dataclasses import dataclass, field

from .config import Household, money as load_money


@dataclass
class Card:
    id: str
    name: str
    network: str
    earn: dict
    credits: list[dict] = field(default_factory=list)
    verified: object = None


@dataclass
class Pick:
    card: str | None
    name: str
    pct: float
    earned: float
    category: str
    note: str = ""


def catalog() -> dict:
    return load_money()


def cards(h: Household) -> dict[str, Card]:
    """The household's cards: template ids, or {template: id, ...overrides}, or a full card of its own."""
    m = catalog()
    out = {}
    for entry in h.raw.get("cards", []) or []:
        if isinstance(entry, str):
            cid, base, over = entry, m.get("cards", {}).get(entry, {}), {}
        else:
            cid = entry.get("id") or entry.get("template")
            base = copy.deepcopy(m.get("cards", {}).get(entry.get("template", cid), {}))
            over = {k: v for k, v in entry.items() if k not in ("id", "template")}
        if not base and not over:
            continue
        c = {**base, **over}
        out[cid] = Card(cid, c.get("name", cid), c.get("network", "visa"), c.get("earn", {"default": {"pct": 0.0}}),
                        c.get("credits", []) or [], c.get("verified"))
    return out


def memberships(h: Household) -> dict[str, dict]:
    m = catalog().get("memberships", {})
    return {mid: m.get(mid, {}) for mid in h.raw.get("memberships", []) or []}


def category(store: str, mode_cfg: dict | None = None) -> str:
    cats = catalog().get("categories", {})
    service = (mode_cfg or {}).get("service")
    if service and service in cats:
        return cats[service]
    return cats.get(store, "default")


def accepted(card: Card, store: str, mode: str) -> bool:
    nets = (catalog().get("acceptance", {}).get(store) or {}).get(mode)
    return nets is None or card.network in nets


def rate(card: Card, cat: str) -> tuple[float, float | None]:
    """(rate as a fraction of spend, annual cap on the bonus or None) for one category."""
    pv = catalog().get("point_value_cents", {})
    rule = card.earn.get(cat) or card.earn.get("default") or {}
    if "pct" in rule:
        r = float(rule["pct"])
    else:
        r = float(rule.get("points", 0)) * float(pv.get(rule.get("program", ""), 1.0)) / 100
    return r, (float(rule["annual_cap"]) if rule.get("annual_cap") else None)


def default_rate(card: Card) -> float:
    return rate(card, "default")[0]


def best_card(h: Household, store: str, mode: str, amount: float, mode_cfg: dict | None = None,
              used: dict[tuple[str, str], float] | None = None) -> Pick:
    """The accepted card that earns the most on this order. `used`: this year's spend per (card, category) so far."""
    used = used or {}
    cat = category(store, mode_cfg)
    best = Pick(None, "any card", 0.0, 0.0, cat, "no card in the household settings")
    for c in cards(h).values():
        if not accepted(c, store, mode):
            continue
        r, cap = rate(c, cat)
        if cap is not None:
            room = max(0.0, cap - used.get((c.id, cat), 0.0))
            bonus_part = min(amount, room)
            earned = bonus_part * r + (amount - bonus_part) * default_rate(c)
            note = f"{r:.0%} on {cat.replace('_', ' ')} up to ${cap:,.0f} a year" + \
                   (f" (${room:,.0f} left)" if room < amount else "")
        else:
            earned = amount * r
            note = f"{r:.0%} on {cat.replace('_', ' ')}" if cat in c.earn else f"{r:.0%} base rate"
        if earned > best.earned + 1e-9:
            best = Pick(c.id, c.name, round(earned / amount, 4) if amount else r, round(earned, 2), cat, note)
    if best.card is None and store in catalog().get("acceptance", {}):
        best.note = "none of your cards is accepted here"
    return best


def store_reward(h: Household, store: str) -> tuple[float, float | None, str]:
    """A store's own reward from a membership (e.g. Costco Executive 2%): (pct, annual cap $, name)."""
    for mid, b in memberships(h).items():
        pb = b.get("pct_back") or {}
        if pb.get("store") == store:
            return float(pb.get("pct", 0)), (float(pb["annual_cap"]) if pb.get("annual_cap") else None), b.get("name", mid)
    return 0.0, None, ""


def waivers(h: Household, store: str, mode_cfg: dict) -> list[dict]:
    out = []
    for mid, b in memberships(h).items():
        wf = b.get("waive_fee")
        if wf and ((wf.get("service") and wf["service"] == mode_cfg.get("service"))
                   or (wf.get("store") == store and mode_cfg.get("_mode") in wf.get("modes", []))):
            out.append({"by": b.get("name", mid), "minimum": float(wf.get("minimum", 0))})
    return out


def member_deals(h: Household) -> set[str]:
    """Membership ids whose member-only specials apply (e.g. Prime deals at Whole Foods)."""
    return {mid for mid, b in memberships(h).items() if b.get("member_deals")}


def order_pct(h: Household, store: str, mode_cfg: dict) -> float:
    """What the store split counts as coming back on an order here: the best card's uncapped rate plus the store's
    own reward. Caps are applied afterwards, when each order is given a card (best_card)."""
    cat = category(store, mode_cfg)
    mode = mode_cfg.get("_mode", "in_store")
    card_r = max((rate(c, cat)[0] for c in cards(h).values() if accepted(c, store, mode)), default=0.0)
    return card_r + store_reward(h, store)[0]


def credits_for(h: Household, service: str, when: dt.date, already_used: float = 0.0) -> tuple[float, str]:
    """Monthly credits a takeout order through `service` can use this month: (amount left, which card)."""
    for c in cards(h).values():
        for cr in c.credits:
            if service in cr.get("applies_to", []):
                total = float(cr.get("monthly", 0)) + (float(cr.get("december_extra", 0)) if when.month == 12 else 0)
                return max(0.0, total - already_used), f"{cr['name']} ({c.name})"
    return 0.0, ""
