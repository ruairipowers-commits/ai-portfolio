"""The Household Food Passport and client engagements over HTTP. Every read goes through PassportAccessService."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import accounts, market, passport, plans

router = APIRouter()
from .api import member, signed_in  # noqa: E402


def _api():
    from . import api
    return api


def _con():
    con = accounts.connect()
    passport.setup(con)
    return con


# ---------------------------------------------------------------- what a chef (or anyone) may see of a household
@router.get("/api/passport/{hid}")
def view(hid: str, ctx=Depends(signed_in)) -> dict:
    """The household as this viewer may see it. 404 for households that aren't listed and don't know the viewer."""
    con = _con()
    try:
        svc = passport.PassportAccessService(con)
        rel = svc.relation(ctx.uid, hid)
        listed = (market.listing(con, hid) or {}).get("open")
        if not (rel["member"] or rel["engagement"] or rel["granted"] or listed):
            raise HTTPException(404, "no such household")
        return svc.view(ctx.uid, hid)
    finally:
        con.close()


@router.get("/api/passport/{hid}/location")
def private_location(hid: str, ctx=Depends(signed_in)) -> dict:
    con = _con()
    try:
        return passport.PassportAccessService(con).private_location(ctx.uid, hid)
    except passport.AccessDenied as e:
        raise HTTPException(403, str(e))
    finally:
        con.close()


# ---------------------------------------------------------------- the household's own passport, grants and log
def _name(con, uid: str) -> str:
    p = market.profile(con, uid)
    u = accounts.user(con, uid)
    return (p or {}).get("display_name") or (u or {}).get("name", "")


@router.get("/api/household/passport")
def mine(ctx=Depends(member)) -> dict:
    con = _con()
    try:
        out = {"passport": passport.food_passport(ctx.hid).to_dict(),
               "location": passport.location(ctx.hid).private() if ctx.role != "chef" else None,
               "grants": [{**g, "name": _name(con, g["chef_uid"])} for g in passport.grants(con, ctx.hid)],
               "engagements": [{**passport.asdict(e), "name": _name(con, e.chef_uid)}
                               for e in passport.engagements_for(con, hid=ctx.hid)],
               "access_log": [{**a, "name": _name(con, a["viewer"])} for a in passport.access_log(con, ctx.hid)]}
        if ctx.role == "chef":
            raise HTTPException(403, "this is the family's own view")
        return out
    finally:
        con.close()


class GrantIn(BaseModel):
    chef_uid: str


@router.post("/api/household/passport/grants")
def grant(body: GrantIn, ctx=Depends(member)) -> dict:
    """Share the food passport (never the address) with a chef you're talking to."""
    _api().need(ctx, "admin")
    con = _con()
    try:
        if not market.profile(con, body.chef_uid) and not accounts.membership(con, body.chef_uid, ctx.hid):
            raise HTTPException(404, "no such chef")
        passport.grant(con, ctx.hid, body.chef_uid, ctx.uid)
        return {"granted": body.chef_uid}
    finally:
        con.close()


@router.delete("/api/household/passport/grants/{chef_uid}")
def revoke(chef_uid: str, ctx=Depends(member)) -> dict:
    _api().need(ctx, "admin")
    con = _con()
    passport.revoke(con, ctx.hid, chef_uid)
    con.close()
    return {"revoked": chef_uid}


@router.get("/api/household/passport/export")
def export(ctx=Depends(member)) -> Response:
    """The food passport as a file the family keeps or hands to any chef (no address, no gate code)."""
    if ctx.role == "chef":
        raise HTTPException(403, "only the family can export its passport")
    body = json.dumps({"format": "dinnerpeace-food-passport/1", **passport.food_passport(ctx.hid).to_dict()}, indent=1)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=food-passport.json"})


# ---------------------------------------------------------------- engagements
class MoveIn(BaseModel):
    status: str
    trial_at: str | None = Field(default=None, max_length=30)
    rate_per_visit: float | None = Field(default=None, ge=0, le=5000)


@router.get("/api/engagements")
def chef_engagements(ctx=Depends(signed_in)) -> dict:
    con = _con()
    out = []
    for e in passport.engagements_for(con, chef_uid=ctx.uid):
        name = con.execute("SELECT name FROM households WHERE id = ?", (e.household_id,)).fetchone()
        out.append({**passport.asdict(e), "household": name["name"] if name and e.status != "inquiry" else None,
                    "address_shared": e.shows_address})
    con.close()
    return {"engagements": out}


@router.put("/api/engagements/{eid}")
def move(eid: str, body: MoveIn, ctx=Depends(signed_in)) -> dict:
    """Household admins can schedule a trial, hire (active), pause, end or decline. The chef can propose a trial,
    pause, end or decline — but only the family makes it active."""
    con = _con()
    try:
        e = passport.get_engagement(con, eid)
        m = accounts.membership(con, ctx.uid, e.household_id)
        family_admin = bool(m and m["role"] == "admin")
        is_chef = ctx.uid == e.chef_uid
        if not (family_admin or is_chef):
            raise HTTPException(404, "no such engagement")
        if body.status == "active" and not family_admin:
            raise HTTPException(403, "only the family can hire")
        if body.status == "active":
            plans.check_new_client(con, e.chef_uid) if not accounts.membership(con, e.chef_uid, e.household_id) else None
        out = passport.move(con, eid, body.status, trial_at=body.trial_at, rate=body.rate_per_visit)
        if body.status in ("ended", "declined") and accounts.membership(con, e.chef_uid, e.household_id):
            accounts.remove_member(con, e.household_id, e.chef_uid)
            passport.revoke(con, e.household_id, e.chef_uid)
    except plans.PlanError:
        con.close()
        raise
    except ValueError as err:
        con.close()
        raise HTTPException(409, str(err))
    hire = None
    if body.status == "active" and not accounts.membership(con, out.chef_uid, out.household_id):
        email = (accounts.user(con, out.chef_uid) or {}).get("email")
        con.close()
        from . import pro_api
        hire = pro_api._invite(ctx, out.household_id, None, email, "chef")
    else:
        con.close()
    return {**passport.asdict(out), "invited": hire}
