"""The owner console's API: list prices, subscriptions, renewal policies (grandfather or upcharge), renewals.
Only people whose email is in HELPER_OWNER_EMAILS get in. Mounted by api.py."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import accounts, billing, plans

router = APIRouter()
from .api import signed_in  # noqa: E402


def owner(ctx=Depends(signed_in)):
    if not billing.is_owner(ctx.email):
        raise HTTPException(403, "the owner console is for DinnerPeace's owner")
    return ctx


def _con():
    con = accounts.connect()
    billing.setup(con)
    return con


@router.get("/api/owner")
def overview(ctx=Depends(owner)) -> dict:
    con = _con()
    try:
        subs = billing.listing(con)
        mrr = sum(s["price"] / (12 if s["interval"] == "yearly" else 1) for s in subs)
        return {"prices": billing.price_book(con), "subscriptions": subs,
                "renewals": billing.renewals(con, 30), "history": billing.history(con, 40),
                "totals": {"active": len(subs), "monthly_revenue": round(mrr, 2),
                           "grandfathered": sum(s["policy"] == "grandfather" for s in subs),
                           "price_rises_next_30_days": sum(s["change"] > 0 for s in billing.renewals(con, 30))},
                "policies": billing.POLICIES, "store_note": "App Store and Google Play subscribers are charged the "
                "prices in App Store Connect / Play Console; mirror price changes there (and choose whether existing "
                "subscribers keep their price)."}
    finally:
        con.close()


class PriceIn(BaseModel):
    monthly: float = Field(gt=0, le=10000)
    yearly: float | None = Field(default=None, gt=0)
    annual_discount_pct: float | None = Field(default=None, ge=0, lt=100)
    effective: str | None = None
    note: str = Field(default="", max_length=200)


@router.put("/api/owner/prices/{plan}")
def set_price(plan: str, body: PriceIn, ctx=Depends(owner)) -> dict:
    con = _con()
    try:
        eff = dt.datetime.fromisoformat(body.effective).replace(tzinfo=dt.timezone.utc) if body.effective else None
        return billing.set_price(con, plan, body.monthly, body.yearly, body.annual_discount_pct, eff, ctx.email, body.note)
    except ValueError as e:
        raise HTTPException(422, str(e))
    finally:
        con.close()


class SubEdit(BaseModel):
    policy: str | None = None
    custom_price: float | None = Field(default=None, ge=0, le=10000)
    interval: str | None = None
    plan: str | None = None
    status: str | None = Field(default=None, pattern="^(active|cancelled)$")


@router.put("/api/owner/subscriptions/{sid}")
def edit_sub(sid: str, body: SubEdit, ctx=Depends(owner)) -> dict:
    con = _con()
    try:
        s = billing.edit(con, sid, ctx.email, **body.model_dump())
        s["next_price"] = billing.next_price(con, s)
        return s
    except ValueError as e:
        raise HTTPException(422, str(e))
    finally:
        con.close()


class BulkIn(BaseModel):
    plan: str
    policy: str


@router.post("/api/owner/subscriptions/bulk")
def bulk(body: BulkIn, ctx=Depends(owner)) -> dict:
    con = _con()
    try:
        return {"changed": billing.bulk_policy(con, body.plan, body.policy, ctx.email)}
    except ValueError as e:
        raise HTTPException(422, str(e))
    finally:
        con.close()


class NewSubIn(BaseModel):
    email: str = Field(max_length=200)
    plan: str
    interval: str = "monthly"
    source: str = "admin"
    policy: str = "current_price"
    household_id: str | None = None


@router.post("/api/owner/subscriptions")
def new_sub(body: NewSubIn, ctx=Depends(owner)) -> dict:
    """Give someone a plan: a chef plan on their account, or Family on a household they're the admin of."""
    con = _con()
    try:
        u = accounts.get_or_create_user(con, body.email)
        if body.plan in plans.CHEF_PLANS:
            return billing.subscribe(con, "chef", u["id"], body.plan, body.interval, body.source, body.policy, by=ctx.email)
        hid = body.household_id or next((m["household_id"] for m in accounts.memberships(con, u["id"])
                                         if m["role"] == "admin"), None)
        if not hid:
            raise ValueError("that person isn't the admin of a household yet")
        return billing.subscribe(con, "household", hid, body.plan, body.interval, body.source, body.policy, by=ctx.email)
    except ValueError as e:
        raise HTTPException(422, str(e))
    finally:
        con.close()


@router.post("/api/owner/renew")
def renew_now(ctx=Depends(owner)) -> dict:
    con = _con()
    try:
        return {"renewed": billing.renew_due(con, by=ctx.email)}
    finally:
        con.close()
