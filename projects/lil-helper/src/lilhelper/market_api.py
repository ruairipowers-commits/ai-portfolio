"""Find a chef / find a household, requests to meet, hiring and switching chefs. Mounted by api.py."""
from __future__ import annotations

import html

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import accounts, geo, market, plans
from .config import load_household, tenant

router = APIRouter()
from .api import member, signed_in  # noqa: E402


def _api():
    from . import api
    return api


def _con():
    con = accounts.connect()
    market.setup(con)
    return con


def _admins(con, hid: str) -> list[dict]:
    return [m for m in accounts.members(con, hid) if m["role"] == "admin"]


def _hname(con, hid: str) -> str:
    r = con.execute("SELECT name FROM households WHERE id = ?", (hid,)).fetchone()
    return r["name"] if r else ""


# ---------------------------------------------------------------- the chef's profile and search
class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=60)
    business: str | None = Field(default=None, max_length=60)
    bio: str | None = Field(default=None, max_length=600)
    cuisines: list[str] | None = None
    rate_per_visit: float | None = Field(default=None, ge=0, le=5000)
    rate_hourly: float | None = Field(default=None, ge=0, le=1000)
    radius_miles: int | None = Field(default=None, ge=1, le=100)
    address: dict | None = None
    listed: bool | None = None
    accepting: bool | None = None


@router.get("/api/market/profile")
def get_profile(ctx=Depends(signed_in)) -> dict:
    con = _con()
    p = market.profile(con, ctx.uid) or {"display_name": ctx.name, "listed": False, "accepting": True, "radius_miles": 20,
                                          "cuisines": [], "address": {}}
    plan = plans.chef_plan(con, ctx.uid)
    con.close()
    return {"profile": p, "plan": plan, "cuisines": market.CUISINES}


@router.put("/api/market/profile")
def put_profile(body: ProfileIn, ctx=Depends(signed_in)) -> dict:
    con = _con()
    try:
        if body.listed:
            plans.require_chef(con, ctx.uid, "chef_clients")
        if body.address is not None:
            from .config import _check_address
            a = {k: v for k, v in body.address.items() if k in ("city", "state", "zip", "lat", "lon") and v not in ("", None)}
            _check_address(a)
            if a.get("state"):
                a["state"] = a["state"].upper()
            if a.get("lat") is None and (a.get("city") or a.get("zip")):
                pt = geo.forward(a)
                if pt:
                    a["lat"], a["lon"] = round(pt[0], 4), round(pt[1], 4)
            body.address = a
        p = market.save_profile(con, ctx.uid, **body.model_dump())
    except plans.PlanError:
        con.close()
        raise
    except ValueError as e:
        con.close()
        raise HTTPException(422, str(e))
    con.close()
    return {"profile": p}


@router.get("/api/market/households")
def find_households(radius: float = 25, cuisine: str | None = None, ctx=Depends(signed_in)) -> dict:
    """Households near the chef that are looking for one (Pro chefs only)."""
    con = _con()
    try:
        plans.require_chef(con, ctx.uid, "chef_clients")
        p = market.profile(con, ctx.uid)
        if not p or not (p["address"].get("zip") or p["address"].get("lat") is not None):
            raise HTTPException(409, "add your town or ZIP to your chef profile first")
        mine = set(plans.chef_client_ids(con, ctx.uid))
        rows = [dict(r) for r in con.execute("SELECT hid FROM household_listings WHERE open = 1")]
        sent = {r["hid"]: r["status"] for r in market.for_chef(con, ctx.uid)}
    except plans.PlanError:
        con.close()
        raise
    out = []
    for r in rows:
        if r["hid"] in mine:
            continue
        try:
            with tenant(r["hid"]):
                h = load_household()
        except Exception:
            continue
        d = geo.distance(p["address"], h.raw.get("address"))
        if d is None or d > min(radius, p["radius_miles"]):
            continue
        lst = market.listing(con, r["hid"])
        if cuisine and lst["cuisines"] and cuisine not in lst["cuisines"]:
            continue
        out.append({"household_id": r["hid"], "request": sent.get(r["hid"]), **market.public_household(h, lst, d)})
    con.close()
    return {"households": sorted(out, key=lambda x: x["miles"] if x["miles"] is not None else 999)}


class ChefRequestIn(BaseModel):
    household_id: str
    message: str = Field(min_length=1, max_length=600)
    proposed: str = Field(default="", max_length=120)


@router.post("/api/market/requests")
def chef_request(body: ChefRequestIn, ctx=Depends(signed_in)) -> dict:
    """A chef asks a household (that is looking) to meet."""
    a = _api()
    a.rate_limit(f"meet:{ctx.uid}", 20)
    con = _con()
    try:
        plans.require_chef(con, ctx.uid, "chef_clients")
        lst = market.listing(con, body.household_id)
        if not lst or not lst["open"]:
            raise ValueError("that household isn't looking for a chef right now")
        r = market.request(con, "chef", ctx.uid, body.household_id, ctx.uid, body.message, body.proposed)
        p = market.profile(con, ctx.uid) or {}
        for m in _admins(con, body.household_id):
            a._send_email(m["email"], f"A personal chef would like to meet you: {p.get('display_name') or ctx.name}",
                          f"<p><b>{html.escape(p.get('display_name') or ctx.name)}</b>"
                          f"{' (' + html.escape(p['business']) + ')' if p.get('business') else ''} saw that "
                          f"{html.escape(_hname(con, body.household_id))} is looking for a personal chef and would like to "
                          f"meet.</p><blockquote>{html.escape(body.message)}</blockquote>"
                          f"<p>Open DinnerPeace (More, then Find a chef) to accept or decline. Your contact details are "
                          f"shared only if you accept.</p>", "meet")
    except plans.PlanError:
        con.close()
        raise
    except ValueError as e:
        con.close()
        raise HTTPException(422, str(e))
    con.close()
    return r


@router.get("/api/market/requests")
def chef_requests(ctx=Depends(signed_in)) -> dict:
    con = _con()
    out = []
    for r in market.for_chef(con, ctx.uid):
        item = {**r, "household": None, "contact": None}
        try:
            with tenant(r["hid"]):
                h = load_household()
            lst = market.listing(con, r["hid"]) or {"budget_per_week": None, "budget_per_visit": None,
                                                    "visits_per_week": None, "cuisines": [], "note": "", "start": None}
            p = market.profile(con, ctx.uid) or {"address": {}}
            item["household"] = market.public_household(h, lst, geo.distance(p["address"], h.raw.get("address")))
            if r["status"] == "accepted":
                ad = _admins(con, r["hid"])
                item["contact"] = {"household": _hname(con, r["hid"]), "name": ad[0]["name"] if ad else "",
                                   "email": ad[0]["email"] if ad else "", "place": geo.place(h.raw.get("address"))}
        except Exception:
            pass
        out.append(item)
    con.close()
    return {"requests": out}


# ---------------------------------------------------------------- the household's listing and search
class ListingIn(BaseModel):
    open: bool | None = None
    budget_per_week: float | None = Field(default=None, ge=0, le=10000)
    budget_per_visit: float | None = Field(default=None, ge=0, le=5000)
    visits_per_week: int | None = Field(default=None, ge=1, le=7)
    cuisines: list[str] | None = None
    note: str | None = Field(default=None, max_length=600)
    start: str | None = Field(default=None, max_length=20)


@router.get("/api/market/listing")
def get_listing(ctx=Depends(member)) -> dict:
    con = _con()
    lst = market.listing(con, ctx.hid) or {"open": False, "cuisines": [], "note": "", "budget_per_week": None,
                                           "budget_per_visit": None, "visits_per_week": None, "start": None}
    con.close()
    h = _api()._hh()
    return {"listing": lst, "preview": market.public_household(h, lst, None), "has_address": bool(h.raw.get("address")),
            "cuisines": market.CUISINES}


@router.put("/api/market/listing")
def put_listing(body: ListingIn, ctx=Depends(member)) -> dict:
    a = _api()
    a.need(ctx, "admin")
    h = a._hh()
    if body.open and not h.raw.get("address"):
        raise HTTPException(409, "add your address first, so chefs nearby can find you (they see only your town)")
    con = _con()
    try:
        market.save_listing(con, ctx.hid, **body.model_dump())
    except ValueError as e:
        con.close()
        raise HTTPException(422, str(e))
    con.close()
    return get_listing(ctx)


@router.get("/api/market/chefs")
def find_chefs(radius: float = 25, cuisine: str | None = None, ctx=Depends(member)) -> dict:
    h = _api()._hh()
    if not h.raw.get("address"):
        raise HTTPException(409, "add your address first (More, then Home address) to find chefs near you")
    con = _con()
    chefs = market.search_chefs(con, h.raw["address"], radius, cuisine)
    sent = {r["chef_uid"]: r["status"] for r in market.for_household(con, ctx.hid)}
    current = {m["user_id"] for m in accounts.members(con, ctx.hid) if m["role"] == "chef"}
    con.close()
    for ch in chefs:
        ch["request"] = sent.get(ch["uid"])
        ch["your_chef"] = ch["uid"] in current
    return {"chefs": chefs, "place": geo.place(h.raw["address"])}


class HouseholdRequestIn(BaseModel):
    chef_uid: str
    message: str = Field(min_length=1, max_length=600)
    proposed: str = Field(default="", max_length=120)


@router.post("/api/market/chef-requests")
def household_request(body: HouseholdRequestIn, ctx=Depends(member)) -> dict:
    a = _api()
    a.need(ctx, "admin")
    a.rate_limit(f"meet:{ctx.hid}", 20)
    con = _con()
    try:
        p = market.profile(con, body.chef_uid)
        if not p or not p["listed"] or plans.chef_plan(con, body.chef_uid) == "none":
            raise ValueError("that chef isn't taking requests")
        r = market.request(con, "household", body.chef_uid, ctx.hid, ctx.uid, body.message, body.proposed)
        u = accounts.user(con, body.chef_uid)
        h = a._hh()
        a._send_email(u["email"], f"A family near you would like to meet: {geo.place(h.raw.get('address'))}",
                      f"<p>A household in {html.escape(geo.place(h.raw.get('address')))} found you on DinnerPeace and "
                      f"would like to meet.</p><blockquote>{html.escape(body.message)}</blockquote><p>Open Dinner Peace "
                      f"Pro (Clients, then Requests) to accept or decline.</p>", "meet")
    except ValueError as e:
        con.close()
        raise HTTPException(422, str(e))
    con.close()
    return r


@router.get("/api/market/household-requests")
def household_requests(ctx=Depends(member)) -> dict:
    con = _con()
    out = []
    for r in market.for_household(con, ctx.hid):
        p = market.profile(con, r["chef_uid"]) or {"uid": r["chef_uid"], "display_name": "", "business": "", "bio": "",
                                                   "cuisines": [], "rate_per_visit": None, "rate_hourly": None,
                                                   "address": {}, "radius_miles": 20}
        item = {**r, "chef": market._public_chef(con, {**p, "uid": r["chef_uid"]}, None), "contact": None}
        if r["status"] == "accepted":
            u = accounts.user(con, r["chef_uid"])
            item["contact"] = {"name": p.get("display_name") or (u or {}).get("name", ""), "email": (u or {}).get("email", ""),
                               "business": p.get("business", "")}
        out.append(item)
    con.close()
    return {"requests": out}


# ---------------------------------------------------------------- answering, hiring, switching
class RespondIn(BaseModel):
    accept: bool


@router.post("/api/market/requests/{rid}/respond")
def respond(rid: str, body: RespondIn, ctx=Depends(signed_in)) -> dict:
    """The side that received the request answers it: the chef for a household's request, the household's admin for a
    chef's. Accepting shares both sides' names and emails so you can arrange to meet."""
    con = _con()
    try:
        r = market.get_request(con, rid)
        if r["from_kind"] == "household":
            if r["chef_uid"] != ctx.uid:
                raise PermissionError
        else:
            m = accounts.membership(con, ctx.uid, r["hid"])
            if not m or m["role"] != "admin":
                raise PermissionError
        out = market.respond(con, rid, body.accept, ctx.uid)
    except PermissionError:
        con.close()
        raise HTTPException(403, "that request wasn't sent to you")
    except ValueError as e:
        con.close()
        raise HTTPException(409, str(e))
    a = _api()
    to = (accounts.user(con, r["by_uid"]) or {}).get("email")
    if to:
        a._send_email(to, f"Your request to meet was {'accepted' if body.accept else 'declined'}",
                      f"<p>Your DinnerPeace request to meet was {'accepted: open the app to see their contact details' if body.accept else 'declined'}.</p>",
                      "meet")
    con.close()
    return out


@router.delete("/api/market/requests/{rid}")
def withdraw(rid: str, ctx=Depends(signed_in)) -> dict:
    con = _con()
    try:
        market.withdraw(con, rid, ctx.uid)
    except ValueError as e:
        con.close()
        raise HTTPException(409, str(e))
    con.close()
    return {"withdrawn": rid}


@router.post("/api/market/requests/{rid}/hire")
def hire(rid: str, ctx=Depends(member)) -> dict:
    """After meeting: invite the chef into the household. A household that already has a chef keeps them until it
    removes them (switching chefs is fine)."""
    a = _api()
    a.need(ctx, "admin")
    con = _con()
    try:
        r = market.get_request(con, rid)
    except ValueError as e:
        con.close()
        raise HTTPException(404, str(e))
    if r["hid"] != ctx.hid or r["status"] != "accepted":
        con.close()
        raise HTTPException(409, "accept a request to meet before hiring")
    email = (accounts.user(con, r["chef_uid"]) or {}).get("email")
    con.close()
    from . import pro_api
    return {"invited": pro_api._invite(ctx, ctx.hid, None, email, "chef"), "role": "chef"}


@router.get("/api/household/chefs")
def my_chefs(ctx=Depends(member)) -> dict:
    con = _con()
    out = [{"uid": m["user_id"], "name": (market.profile(con, m["user_id"]) or {}).get("display_name") or m["name"],
            "email": m["email"], "since": m["joined"]} for m in accounts.members(con, ctx.hid) if m["role"] == "chef"]
    con.close()
    return {"chefs": out}


@router.delete("/api/household/chefs/{uid}")
def remove_chef(uid: str, ctx=Depends(member)) -> dict:
    """Switch chefs: the old chef loses access to your household at once (what they logged stays yours)."""
    a = _api()
    a.need(ctx, "admin")
    con = _con()
    m = accounts.membership(con, uid, ctx.hid)
    if not m or m["role"] != "chef":
        con.close()
        raise HTTPException(404, "that person isn't your chef")
    accounts.remove_member(con, ctx.hid, uid)
    con.close()
    return {"removed": uid}
