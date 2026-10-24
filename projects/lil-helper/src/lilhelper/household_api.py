"""Household money and place: the card wallet, delivery services, and the home address. Mounted by api.py.

Cards are names, issuers, the last four digits at most, expiry month, rewards, limits, the stores each card is for,
and monthly credits — never a card number (refused). Any adult can manage the cards; the admin sets delivery
services and the address. Allergen and pet rules don't depend on any of this and are free on every plan.
"""
from __future__ import annotations

import datetime as dt
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import geo, money, spend, store
from .config import HouseholdError, delivery as load_delivery, load_household, save_household, stores as load_stores

router = APIRouter()
from .api import member, signed_in  # noqa: E402  (api.py imports this module at its end)


def _api():
    from . import api
    return api


def _wallet(h) -> dict:
    today = dt.date.today()
    con = store.connect()
    used = spend.ytd_used(con, today.year, today.month)
    credits_used = {}
    for c in money.cards(h).values():
        for cr in c.credits:
            credits_used[cr.get("name", "")] = sum(spend.credit_used(con, s, today) for s in cr.get("applies_to", []))
    con.close()
    st = load_stores()["stores"]
    where = []
    for sid in h.raw.get("stores", []):
        for mode, mc in st.get(sid, {}).get("modes", {}).items():
            p = money.best_card(h, sid, mode, 100.0, {**mc, "_mode": mode}, used)
            where.append({"store": sid, "store_name": st[sid]["name"], "mode": mode, "card": p.card, "card_name": p.name,
                          "per_100": p.earned, "note": p.note})
    m = money.catalog()
    return {"cards": money.card_status(h, used, credits_used, today), "where": where,
            "templates": [{"id": k, "name": v.get("name", k), "issuer": v.get("issuer", ""), "network": v.get("network", ""),
                           "earn": v.get("earn", {}), "credits": v.get("credits", []), "verified": str(v.get("verified") or "")}
                          for k, v in m.get("cards", {}).items() if k != "example_grocery_card"],
            "categories": sorted(set(m.get("categories", {}).values()) | {"default"}),
            "stores": [{"id": s, "name": st[s]["name"]} for s in h.raw.get("stores", []) if s in st],
            "services": [{"id": k, "name": v["name"]} for k, v in load_delivery()["services"].items()]}


@router.get("/api/wallet")
def wallet(ctx=Depends(member)) -> dict:
    _api().need(ctx, "adult")
    return _wallet(_api()._hh())


class CardsIn(BaseModel):
    cards: list[dict | str] = Field(max_length=20)


def _slug(name: str, taken: set) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30] or "card"
    sid, n = base, 2
    while sid in taken:
        sid, n = f"{base}_{n}", n + 1
    return sid


@router.put("/api/wallet/cards")
def save_cards(body: CardsIn, ctx=Depends(member)) -> dict:
    """Replace the household's cards. Each card: a template id, or {id?, template?, name, issuer, network, last4,
    expires, earn, credit_limit, monthly_limit, stores, primary, credits, active}."""
    a = _api()
    a.need(ctx, "adult")
    h = a._hh()
    raw = h.raw
    clean, taken = [], set()
    for c in body.cards:
        if isinstance(c, dict):
            c = {k: v for k, v in c.items() if v not in (None, "", [])}
            c["id"] = c.get("id") or _slug(c.get("name") or c.get("template") or "card", taken)
        cid = c if isinstance(c, str) else c["id"]
        if cid in taken:
            raise HTTPException(422, f"two cards share the id {cid}")
        taken.add(cid)
        clean.append(c)
    raw["cards"] = clean
    try:
        save_household(raw)
    except (HouseholdError, KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, str(e))
    con = store.connect()
    store.audit(con, a.actor(ctx), "cards", {"count": len(clean)})
    con.close()
    return _wallet(load_household())


@router.post("/api/wallet/cards/{cid}/primary")
def make_primary(cid: str, ctx=Depends(member)) -> dict:
    """Make this the everyday card (the suggestion when another card's bonus runs out)."""
    a = _api()
    a.need(ctx, "adult")
    raw = a._hh().raw
    out, found = [], False
    for c in raw.get("cards", []) or []:
        c = {"id": c, "template": c} if isinstance(c, str) else dict(c)
        c["primary"] = c.get("id") == cid
        found |= c["primary"]
        out.append(c)
    if not found:
        raise HTTPException(404, "no such card")
    raw["cards"] = out
    save_household(raw)
    return _wallet(load_household())


# ---------------------------------------------------------------- delivery services
@router.get("/api/delivery")
def delivery(ctx=Depends(member)) -> dict:
    h = _api()._hh()
    m = money.catalog().get("memberships", {})
    mine = set(h.raw.get("delivery_services") or [])
    members = set(h.raw.get("memberships") or [])
    return {"services": [{"id": k, "name": v["name"], "kinds": v["kinds"], "url": v["url"], "note": v.get("note", ""),
                          "handoff": v["handoff"], "on": k in mine,
                          "membership": {"id": v.get("membership"), "name": m.get(v.get("membership"), {}).get("name", ""),
                                         "on": v.get("membership") in members,
                                         "price_per_month": m.get(v.get("membership"), {}).get("price_per_month"),
                                         "waive": m.get(v.get("membership"), {}).get("waive_fee"),
                                         "verified": str(m.get(v.get("membership"), {}).get("verified") or "")}}
                         for k, v in load_delivery()["services"].items()],
            "takeout_service": ((h.raw.get("eating_out") or {}).get("takeout") or {}).get("service")}


class DeliveryIn(BaseModel):
    services: list[str]
    memberships: list[str] | None = None
    takeout_service: str | None = None


@router.put("/api/delivery")
def save_delivery(body: DeliveryIn, ctx=Depends(member)) -> dict:
    a = _api()
    a.need(ctx, "admin")
    raw = a._hh().raw
    cat = load_delivery()["services"]
    raw["delivery_services"] = body.services
    if body.memberships is not None:
        # only the delivery memberships change here; others (Costco, Prime deals) stay as they were
        dm = {v.get("membership") for v in cat.values()}
        raw["memberships"] = [x for x in raw.get("memberships") or [] if x not in dm] + [x for x in body.memberships if x in dm]
    if body.takeout_service:
        if body.takeout_service not in cat or "takeout" not in cat[body.takeout_service]["kinds"]:
            raise HTTPException(422, "pick a takeout service")
        eo = raw.setdefault("eating_out", {})
        eo.setdefault("takeout", {})["service"] = body.takeout_service
    try:
        save_household(raw)
    except (HouseholdError, KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, str(e))
    return delivery(ctx)


def handoffs(h, order: dict, share_text: str) -> list[dict]:
    """Other ways to get this order delivered, through the services the household uses (for the shopping screen)."""
    cat = load_delivery()["services"]
    out = []
    for sid in h.raw.get("delivery_services") or []:
        v = cat.get(sid)
        if not v or "grocery" not in v["kinds"] or (order.get("handoff") == "instacart" and sid == "instacart"):
            continue
        out.append({"service": sid, "name": v["name"], "url": v["url"],
                    "how": "Share the list, then open " + v["name"] if v["handoff"] == "link" else "One-tap list link"})
    return out


# ---------------------------------------------------------------- the home address
class AddressIn(BaseModel):
    line1: str = Field(default="", max_length=120)
    line2: str = Field(default="", max_length=120)
    city: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=2)
    zip: str = Field(default="", max_length=10)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    source: str = Field(default="typed", max_length=20)
    gate_code: str | None = Field(default=None, max_length=40)
    access_notes: str | None = Field(default=None, max_length=400)
    kitchen_notes: str | None = Field(default=None, max_length=600)


@router.get("/api/household/address")
def get_address(ctx=Depends(member)) -> dict:
    h = _api()._hh()
    return {"address": h.raw.get("address") or {}, "access": h.raw.get("access") or {}, "geocoder": geo._mode() or None}


@router.put("/api/household/address")
def set_address(body: AddressIn, ctx=Depends(member)) -> dict:
    """Typed, or from the phone's location. Missing parts are filled by the geocoder when one is set up."""
    a = _api()
    a.need(ctx, "admin")
    extra = {k: getattr(body, k) for k in ("gate_code", "access_notes", "kitchen_notes")}
    addr = {k: v for k, v in body.model_dump().items() if v not in (None, "") and k not in extra}
    addr["state"] = addr.get("state", "").upper() or None
    if addr.get("lat") is not None and not addr.get("line1"):
        found = geo.reverse(addr["lat"], addr["lon"])
        if found:
            addr = {**{k: v for k, v in found.items() if v}, **addr}
    elif addr.get("line1") and addr.get("lat") is None:
        pt = geo.forward(addr)
        if pt:
            addr["lat"], addr["lon"] = round(pt[0], 6), round(pt[1], 6)
    addr = {k: v for k, v in addr.items() if v not in (None, "")}
    raw = a._hh().raw
    raw["address"] = addr
    acc = dict(raw.get("access") or {})
    for k, v in (("gate_code", extra["gate_code"]), ("notes", extra["access_notes"]), ("kitchen_notes", extra["kitchen_notes"])):
        if v is not None:
            acc[k] = v.strip()
    raw["access"] = {k: v for k, v in acc.items() if v}
    try:
        save_household(raw)
    except (HouseholdError, ValueError) as e:
        raise HTTPException(422, str(e))
    from . import accounts, passport
    con = accounts.connect()
    passport.refresh_location(con, ctx.hid, addr)
    con.close()
    return {"address": addr, "access": raw["access"]}


@router.get("/api/geo/reverse")
def reverse(lat: float, lon: float, ctx=Depends(signed_in)) -> dict:
    a = _api()
    a.rate_limit(f"geo:{ctx.uid}", 30)
    return {"address": geo.reverse(lat, lon) or {}, "geocoder": geo._mode() or None}
