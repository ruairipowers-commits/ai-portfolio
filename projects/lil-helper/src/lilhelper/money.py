"""Cards, memberships and partnerships: what a household earns back, and which card to pay with where.

Everything here is arithmetic on the household's own settings (config/money.yaml templates, overridden or extended in
the household's settings). A model is never asked which card to use.

  best_card    for one order (store, mode, amount): the household's own pick for that store (its ranking) or its
               primary card, unless that card has used up its bonus cap, is past its spending limit or has
               expired — then the next best card, and the note says why. Otherwise the card that earns the most,
               counting this calendar year's spending against each card's category cap
  card_status  every card: this year's spend against each cap, this month's spend against its limit, expiry,
               monthly credits, and what takes over when its bonus runs out
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
    issuer: str = ""                    # the company: "American Express", "Citi", "Chase"
    last4: str = ""                     # optional, to tell two cards apart; never the full number
    expires: str = ""                   # "2028-07"
    credit_limit: float | None = None   # the card's limit: orders that would go over it pick another card
    monthly_limit: float | None = None  # your own cap on food spending on this card per month
    stores: list[str] = field(default_factory=list)   # stores where this is your card, in your order
    primary: bool = False               # your everyday card, when no store ranking says otherwise
    active: bool = True
    template: str = ""

    def expired(self, today: dt.date | None = None) -> bool:
        if not self.expires:
            return False
        y, m = map(int, self.expires.split("-"))
        today = today or dt.date.today()
        return (today.year, today.month) > (y, m)


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
        num = lambda k: float(c[k]) if c.get(k) not in (None, "") else None
        out[cid] = Card(cid, c.get("name", cid), c.get("network", "visa"), c.get("earn", {"default": {"pct": 0.0}}),
                        c.get("credits", []) or [], c.get("verified"), issuer=c.get("issuer", ""),
                        last4=str(c.get("last4") or ""), expires=str(c.get("expires") or ""),
                        credit_limit=num("credit_limit"), monthly_limit=num("monthly_limit"),
                        stores=list(c.get("stores") or []), primary=bool(c.get("primary")),
                        active=c.get("active", True) is not False,
                        template=(entry.get("template", "") if isinstance(entry, dict) else entry) or "")
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


MONTH = "__month__"     # key in `used` for this month's spend on a card: used[(card, MONTH)]


def _earn(c: Card, cat: str, amount: float, used: dict) -> tuple[float, str, bool]:
    """(dollars back, note, bonus cap used up) for `amount` on this card in this category."""
    r, cap = rate(c, cat)
    if cap is None:
        return amount * r, (f"{r:.0%} on {cat.replace('_', ' ')}" if cat in c.earn else f"{r:.0%} base rate"), False
    room = max(0.0, cap - used.get((c.id, cat), 0.0))
    bonus_part = min(amount, room)
    earned = bonus_part * r + (amount - bonus_part) * default_rate(c)
    note = f"{r:.0%} on {cat.replace('_', ' ')} up to ${cap:,.0f} a year" + (f" (${room:,.0f} left)" if room < amount else "")
    return earned, note, room <= 0 and r > default_rate(c)


def _over_limit(c: Card, amount: float, used: dict) -> str:
    month = used.get((c.id, MONTH), 0.0)
    for lim, what in ((c.monthly_limit, "your monthly limit"), (c.credit_limit, "its credit limit")):
        if lim is not None and month + amount > lim:
            return f"{c.name} would go over {what} (${lim:,.0f})"
    return ""


def best_card(h: Household, store: str, mode: str, amount: float, mode_cfg: dict | None = None,
              used: dict[tuple[str, str], float] | None = None, today: dt.date | None = None) -> Pick:
    """The card to pay with for one order. `used`: this year's spend per (card, category), plus this month's spend
    per card under (card, MONTH)."""
    used = used or {}
    cat = category(store, mode_cfg)
    best = Pick(None, "any card", 0.0, 0.0, cat, "no card in the household settings")
    eligible, skipped = [], []
    all_cards = list(cards(h).values())
    for c in all_cards:
        if not c.active:
            continue
        if c.expired(today):
            skipped.append(f"{c.name} has expired ({c.expires})")
            continue
        if not accepted(c, store, mode):
            continue
        why = _over_limit(c, amount, used)
        if why:
            skipped.append(why)
            continue
        earned, note, capped = _earn(c, cat, amount, used)
        eligible.append((c, earned, note, capped))
    if not eligible:
        if all_cards:
            best.note = "; ".join(skipped) or "none of your cards is accepted here"
        return best
    # the household's own order for this store, then its primary card
    ranked = sorted([e for e in eligible if store in e[0].stores], key=lambda e: e[0].stores.index(store))
    ranked += [e for e in eligible if e[0].primary and store not in e[0].stores]
    choice, passed = None, []
    for e in ranked:
        if e[3]:
            passed.append(e[0])
            continue
        choice = (e, "your card here")
        break
    if choice is None:
        e = max(eligible, key=lambda e: (e[1], e[0].primary))
        choice = (e, "")
    (c, earned, note, capped), why = choice
    gone = [x for x in passed if x.id != c.id]
    if gone:
        full = (f"{', '.join(x.name for x in gone)} has used its {cat.replace('_', ' ')} bonus for the year, "
                f"so {c.name} is next best · {note}")
    elif capped:
        full = f"{c.name} has used its {cat.replace('_', ' ')} bonus for the year (base rate now) · {note}"
    else:
        full = f"{why} · {note}" if why else note
    if skipped:
        full += " · " + "; ".join(skipped)
    return Pick(c.id, c.name, round(earned / amount, 4) if amount else rate(c, cat)[0], round(earned, 2), cat, full)


def add_use(used: dict, pick: Pick, amount: float) -> None:
    """Count an order against the picked card's cap and this month's limit."""
    if pick.card:
        used[(pick.card, pick.category)] = used.get((pick.card, pick.category), 0.0) + amount
        used[(pick.card, MONTH)] = used.get((pick.card, MONTH), 0.0) + amount


def card_status(h: Household, used: dict, credits_used: dict[str, float] | None = None,
                today: dt.date | None = None) -> list[dict]:
    """Each card: caps and how much is left, this month against its limit, expiry, credits, and what takes over."""
    today = today or dt.date.today()
    credits_used = credits_used or {}
    out = []
    for c in cards(h).values():
        caps = []
        for cat, rule in c.earn.items():
            if cat == "default":
                continue
            r, cap = rate(c, cat)
            spent = round(used.get((c.id, cat), 0.0), 2)
            item = {"category": cat, "rate": round(r, 4), "spent": spent, "cap": cap,
                    "left": round(max(0.0, cap - spent), 2) if cap else None,
                    "pct_used": round(min(1.0, spent / cap), 3) if cap else None}
            if cap and spent >= cap:
                # what to use for this category now
                alt = max((o for o in cards(h).values() if o.id != c.id and o.active and not o.expired(today)),
                          key=lambda o: _earn(o, cat, 100.0, used)[0], default=None)
                item["next_best"] = alt.name if alt else None
            caps.append(item)
        days_left = None
        if c.expires:
            y, m = map(int, c.expires.split("-"))
            end = (dt.date(y, m, 28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
            days_left = (end - today).days
        month = round(used.get((c.id, MONTH), 0.0), 2)
        lim = c.monthly_limit if c.monthly_limit is not None else c.credit_limit
        out.append({"id": c.id, "name": c.name, "issuer": c.issuer, "network": c.network, "last4": c.last4,
                    "expires": c.expires, "expires_in_days": days_left,
                    "warn": ("expired" if days_left is not None and days_left < 0 else
                             "expires soon" if days_left is not None and days_left <= 60 else ""),
                    "primary": c.primary, "stores": c.stores, "active": c.active, "template": c.template,
                    "credit_limit": c.credit_limit, "monthly_limit": c.monthly_limit, "month_spent": month,
                    "month_left": round(lim - month, 2) if lim is not None else None,
                    "caps": caps, "earn": c.earn, "verified": str(c.verified or ""),
                    "credits": [{**cr, "used": round(credits_used.get(cr.get("name", ""), 0.0), 2)} for cr in c.credits]})
    return out


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
