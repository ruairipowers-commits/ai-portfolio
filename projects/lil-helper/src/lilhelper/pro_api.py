"""Dinner Peace Pro endpoints (the personal-chef app) and plans. Mounted by api.py.

Every chef endpoint that touches a client household checks that the caller is a chef member of that household
(SEC-04: a chef sees only their own clients), then points the engine at it for the length of the call. What each
plan unlocks is decided here, through plans.py, never by the app.
"""
from __future__ import annotations

import datetime as dt
import html
import os
import secrets

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from . import accounts, catalog, plans, pro, store
from .config import HouseholdError, load_household, tenant
from .prices import week_start

router = APIRouter()
# api.py imports this module at its end, so its sign-in dependencies already exist
from .api import member, signed_in  # noqa: E402


def _api():
    from . import api
    return api


def _err(e: Exception, code: int = 422):
    raise HTTPException(code, str(e))


def _chef_clients(con, uid: str) -> dict[str, str]:
    return {r["household_id"]: r["name"] for r in con.execute(
        "SELECT m.household_id, h.name FROM members m JOIN households h ON h.id = m.household_id "
        "WHERE m.user_id = ? AND m.role = 'chef' AND h.status = 'active' ORDER BY m.joined", (uid,))}


def _gate(uid: str, feature: str) -> str:
    con = accounts.connect()
    try:
        return plans.require_chef(con, uid, feature)
    finally:
        con.close()


def _client_of(uid: str, hid: str) -> str:
    con = accounts.connect()
    names = _chef_clients(con, uid)
    con.close()
    if hid not in names:
        raise HTTPException(403, "you're not the chef for that household")
    return names[hid]


def _today(hid: str | None = None) -> dt.date:
    if hid:
        from . import week
        with tenant(hid):
            return week.today_in(load_household())
    return dt.date.today()


# ---------------------------------------------------------------- plans and billing
@router.get("/api/plans")
def plan_catalog(ctx=Depends(signed_in)) -> dict:
    con = accounts.connect()
    chef = plans.chef_plan(con, ctx.uid)
    hp = plans.household_plan(con, ctx.hid) if ctx.hid else None
    n = len(plans.chef_client_ids(con, ctx.uid))
    tiers = plans.catalog(con)
    con.close()
    return {"tiers": tiers, "chef_plan": chef, "household": hp, "clients": n,
            "client_limit": plans.client_limit(chef),
            "billing": "revenuecat" if os.getenv("REVENUECAT_WEBHOOK_AUTH") else "admin",
            "terms_url": os.getenv("HELPER_TERMS_URL", "https://dinnerpeace.app/#support"),
            "privacy_url": os.getenv("HELPER_PRIVACY_URL", "https://dinnerpeace.app/#support")}


@router.post("/api/billing/revenuecat")
async def revenuecat(request: Request, authorization: str = Header(default="")) -> dict:
    """RevenueCat webhook: set the Authorization value in the RevenueCat dashboard and REVENUECAT_WEBHOOK_AUTH here."""
    want = os.getenv("REVENUECAT_WEBHOOK_AUTH", "")
    if not want:
        raise HTTPException(503, "billing isn't set up on this server")
    if not secrets.compare_digest(authorization, want):
        raise HTTPException(401, "bad webhook authorization")
    body = await request.json()
    con = accounts.connect()
    out = plans.apply_revenuecat(con, body.get("event") or {})
    con.close()
    return out


# ---------------------------------------------------------------- the chef's account
class ChefSettingsIn(BaseModel):
    cards: list[str] | None = None
    stores: list[str] | None = None
    memberships: list[str] | None = None
    business: str | None = Field(default=None, max_length=60)
    footer: str | None = Field(default=None, max_length=120)


@router.get("/api/chef")
def chef_home(ctx=Depends(signed_in)) -> dict:
    con = accounts.connect()
    plan = plans.chef_plan(con, ctx.uid)
    names = _chef_clients(con, ctx.uid)
    con.close()
    db = pro.chef_db(ctx.uid)
    out = {"plan": plan, "label": plans.TIERS[plan]["label"], "client_limit": plans.client_limit(plan),
           "clients": [{"household_id": h, "name": n, **{k: v for k, v in pro.client(db, h).items()
                                                         if k in ("priority", "billing", "budget", "visits")},
                        "spent_this_week": pro.week_spend(db, h, dt.date.today())} for h, n in names.items()],
           "cards": pro.get_setting(db, "cards", []), "stores": pro.get_setting(db, "stores",
                                                                                ["costco", "whole_foods", "trader_joes", "stop_and_shop"]),
           "memberships": pro.get_setting(db, "memberships", ["costco"]),
           "branding": pro.branding(db, plan), "features": {f: plans.has(plan, f) for f in plans.FEATURES
                                                            if plans.TIERS[plans.FEATURES[f]]["kind"] == "chef"}}
    db.close()
    out["clients"].sort(key=lambda c: c["priority"])
    return out


@router.put("/api/chef/settings")
def chef_settings(body: ChefSettingsIn, ctx=Depends(signed_in)) -> dict:
    from . import money
    from .config import stores as load_stores
    plan = _gate(ctx.uid, "cockpit")
    db = pro.chef_db(ctx.uid)
    try:
        if body.cards is not None:
            known = money.catalog().get("cards", {})
            pro.no_card_numbers(*body.cards)
            bad = [c for c in body.cards if c not in known]
            if bad:
                raise pro.ProError(f"unknown card templates {bad}; pick from {', '.join(sorted(known))}")
            pro.put_setting(db, "cards", body.cards)
        if body.stores is not None:
            bad = [s for s in body.stores if s not in load_stores()["stores"]]
            if bad or not body.stores:
                raise pro.ProError(f"unknown stores {bad}")
            pro.put_setting(db, "stores", body.stores)
        if body.memberships is not None:
            pro.put_setting(db, "memberships", body.memberships)
        if body.business is not None or body.footer is not None:
            if not plans.has(plan, "branding"):
                raise plans.PlanError("branding", "chef_studio")
            b = pro.get_setting(db, "branding", {}) or {}
            b.update({k: v for k, v in {"business": body.business, "footer": body.footer}.items() if v is not None})
            pro.put_setting(db, "branding", b)
    except pro.ProError as e:
        _err(e)
    finally:
        db.close()
    return chef_home(ctx)


class NewClientIn(BaseModel):
    family_name: str = Field(min_length=1, max_length=60)
    contact_name: str = Field(min_length=1, max_length=40)
    contact_email: str | None = Field(default=None, max_length=200)
    region: str = "northeast-us"
    timezone: str = Field(default="America/New_York", max_length=60)
    invite: bool = True


@router.post("/api/chef/clients")
def new_client(body: NewClientIn, ctx=Depends(signed_in)) -> dict:
    """A chef sets up a client household for a family (Dinner Peace Pro), then invites the family's admin, who
    gets the app free while the chef's plan is active."""
    a = _api()
    con = accounts.connect()
    try:
        plans.require_chef(con, ctx.uid, "chef_clients")
        plans.check_new_client(con, ctx.uid)
        person = {"id": a._pid(body.contact_name, set()), "name": body.contact_name, "can_cook": True}
        if body.contact_email:
            person["email"] = accounts.norm_email(body.contact_email)
        hid = accounts.create_household(con, ctx.uid, body.family_name, body.region, person, body.timezone,
                                        as_chef=True)
    except plans.PlanError:
        con.close()
        raise
    except (ValueError, HouseholdError) as e:
        con.close()
        _err(e)
    con.close()
    db = pro.chef_db(ctx.uid)
    pro.save_client(db, hid)
    db.close()
    invited = None
    if body.invite and body.contact_email:
        invited = _invite(ctx, hid, person["id"], person["email"], "admin")
    return {"household_id": hid, "invited": invited}


def _invite(ctx, hid: str, person_id: str | None, email: str, role: str) -> str:
    a = _api()
    con = accounts.connect()
    code = accounts.invite(con, hid, email, person_id or "", role, ctx.uid)
    name = con.execute("SELECT name FROM households WHERE id = ?", (hid,)).fetchone()["name"]
    con.close()
    link = (f"{os.getenv('HELPER_APP_LINK', 'lilhelper://signin')}?token="
            f"{a.sign('link', email, accounts.INVITE_DAYS * 24 * 3600)}&invite={code}")
    what = ("set up <b>{}</b> on Dinner Peace for your family's meals: what they cook, what's in your fridge and how "
            "to reheat it, free while they're your chef".format(html.escape(name)) if role == "admin" else
            "asked you to be the chef for <b>{}</b> on Dinner Peace Pro".format(html.escape(name)))
    a._send_email(email, f"{ctx.name} invited you to {name} on DinnerPeace",
                  f"<p>{html.escape(ctx.name)} {what}.</p><p>Install DinnerPeace, then tap: "
                  f"<a href='{html.escape(link)}'>join</a> (valid {accounts.INVITE_DAYS} days).</p>",
                  "invite" if role != "chef" else "chef-invite")
    return email


class ClientIn(BaseModel):
    priority: int | None = Field(default=None, ge=1, le=999)
    billing: str | None = None
    client_card: str | None = Field(default=None, max_length=40)
    budget: float | None = Field(default=None, ge=0, le=10000)
    visits: list[dict] | None = None
    address: str | None = Field(default=None, max_length=200)
    gate_code: str | None = Field(default=None, max_length=40)
    access_notes: str | None = Field(default=None, max_length=400)
    emergency: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=800)


@router.put("/api/chef/clients/{hid}")
def edit_client(hid: str, body: ClientIn, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "dossier")
    _client_of(ctx.uid, hid)
    db = pro.chef_db(ctx.uid)
    try:
        return pro.save_client(db, hid, **body.model_dump())
    except pro.ProError as e:
        _err(e)
    finally:
        db.close()


@router.get("/api/chef/clients/{hid}")
def client_detail(hid: str, ctx=Depends(signed_in)) -> dict:
    """The dossier (from the family's own settings), the chef's own notes, the fridge and the chef's list."""
    _gate(ctx.uid, "dossier")
    name = _client_of(ctx.uid, hid)
    db = pro.chef_db(ctx.uid)
    cl = pro.client(db, hid)
    spent = pro.week_spend(db, hid, dt.date.today())
    db.close()
    con = accounts.connect()
    has_admin = accounts.admin_count(con, hid) > 0
    pending = accounts.pending_invites(con, hid)
    con.close()
    with tenant(hid):
        h = load_household()
        dz = pro.dossier(h)
        hc = store.connect()
        boxes, cards, lst = pro.open_containers(hc), pro.recent_cards(hc), pro.open_list(hc)
        hc.close()
    return {"household_id": hid, "name": name, "dossier": dz, "client": cl, "containers": boxes, "cards": cards,
            "list": lst, "spent_this_week": spent, "family_joined": has_admin,
            "invites": [{"email": i["email"], "expires": i["expires"]} for i in pending]}


# ---------------------------------------------------------------- the cockpit
@router.get("/api/chef/cockpit")
def chef_cockpit(clock: str | None = None, ctx=Depends(signed_in)) -> dict:
    plan = _gate(ctx.uid, "cockpit")
    con = accounts.connect()
    names = _chef_clients(con, ctx.uid)
    con.close()
    now = dt.datetime.now()
    out = pro.cockpit(ctx.uid, list(names), names, now.date(), clock or now.strftime("%H:%M"))
    out.update({"chef": ctx.name, "plan": plan, "studio": plan == "chef_studio"})
    return out


# ---------------------------------------------------------------- containers and reheat cards
class ContainerIn(BaseModel):
    dish: str = Field(min_length=1, max_length=80)
    portions: float = Field(gt=0, le=50)
    location: str = "fridge"
    number: int | None = Field(default=None, ge=1, le=99)
    shelf_days: int | None = Field(default=None, ge=1, le=180)


@router.post("/api/chef/clients/{hid}/containers")
def add_container(hid: str, body: ContainerIn, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "containers")
    _client_of(ctx.uid, hid)
    with tenant(hid):
        hc = store.connect()
        try:
            return pro.log_container(hc, body.dish, body.portions, body.location, f"chef:{ctx.uid}", body.number,
                                     body.shelf_days)
        except pro.ProError as e:
            _err(e)
        finally:
            hc.close()


class CloseIn(BaseModel):
    status: str = "eaten"


@router.post("/api/chef/clients/{hid}/containers/{cid}/close")
def chef_close_container(hid: str, cid: int, body: CloseIn, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "containers")
    _client_of(ctx.uid, hid)
    with tenant(hid):
        hc = store.connect()
        try:
            pro.close_container(hc, cid, body.status, f"chef:{ctx.uid}")
        except pro.ProError as e:
            _err(e, 404)
        finally:
            hc.close()
    return {"closed": cid, "status": body.status}


class CardIn(BaseModel):
    meal: str = Field(min_length=1, max_length=80)
    method: str = "oven"
    minutes: int = Field(ge=1, le=240)
    temp_f: int | None = Field(default=None, ge=150, le=550)
    covered: bool = False
    notes: str = Field(default="", max_length=400)
    containers: list[int] = Field(default_factory=list)
    confirm: bool = False


@router.post("/api/chef/clients/{hid}/reheat")
def add_card(hid: str, body: CardIn, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "reheat")
    _client_of(ctx.uid, hid)
    with tenant(hid):
        h = load_household()
        hc = store.connect()
        try:
            return pro.make_card(h, hc, body.meal, body.method, body.minutes, f"chef:{ctx.uid}", body.temp_f,
                                 body.covered, body.notes, body.containers, body.confirm)
        except pro.ProError as e:
            _err(e, 409 if "allergic" in str(e) else 422)
        finally:
            hc.close()


def _cards_for(hid: str, ids: str | None) -> tuple:
    with tenant(hid):
        h = load_household()
        hc = store.connect()
        try:
            cards = ([pro.card(hc, i) for i in ids.split(",") if i] if ids else pro.recent_cards(hc, 2))
        except pro.ProError as e:
            hc.close()
            _err(e, 404)
        hc.close()
    if not cards:
        raise HTTPException(404, "no reheat cards from the last two days")
    return h, cards


def _brand(uid: str) -> dict:
    con = accounts.connect()
    plan = plans.chef_plan(con, uid)
    con.close()
    db = pro.chef_db(uid)
    b = pro.branding(db, plan)
    db.close()
    return b


@router.get("/api/chef/clients/{hid}/reheat.pdf")
def card_pdf(hid: str, size: str = "4x6", ids: str | None = None, ctx=Depends(signed_in)) -> Response:
    _gate(ctx.uid, "reheat")
    _client_of(ctx.uid, hid)
    if size not in ("4x6", "letter"):
        raise HTTPException(422, "size is 4x6 or letter")
    h, cards = _cards_for(hid, ids)
    pdf = pro.card_pdf(h, cards, _brand(ctx.uid), size)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=reheat-{size}.pdf"})


@router.post("/api/chef/clients/{hid}/reheat/link")
def card_link(hid: str, size: str = "4x6", ids: str | None = None, ctx=Depends(signed_in)) -> dict:
    """A five-minute link to the labels PDF, for the phone's browser and AirPrint (they open it without the session)."""
    _gate(ctx.uid, "reheat")
    _client_of(ctx.uid, hid)
    if size not in ("4x6", "letter"):
        raise HTTPException(422, "size is 4x6 or letter")
    _cards_for(hid, ids)
    a = _api()
    tok = a.sign("reheat", f"{ctx.uid}|{hid}|{size}|{ids or ''}", 300)
    return {"url": f"{a.public_url()}/pro/reheat/{tok}.pdf"}


@router.get("/pro/reheat/{token}.pdf")
def card_link_pdf(token: str) -> Response:
    uid, hid, size, ids = _api().verify("reheat", token).split("|")
    _client_of(uid, hid)
    h, cards = _cards_for(hid, ids or None)
    return Response(pro.card_pdf(h, cards, _brand(uid), size), media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=reheat-{size}.pdf"})


@router.post("/api/chef/clients/{hid}/reheat/email")
def card_email(hid: str, ids: str | None = None, ctx=Depends(signed_in)) -> dict:
    """Email the reheat cards to the household's adults who have an email address."""
    _gate(ctx.uid, "reheat")
    _client_of(ctx.uid, hid)
    h, cards = _cards_for(hid, ids)
    to = sorted({p.email for p in h.people.values() if p.email and not p.is_kid})
    if not to:
        raise HTTPException(409, "nobody in the household has an email address yet")
    body = pro.card_html(h, cards, _brand(ctx.uid), "letter")
    from . import outputs
    from .config import household_dir
    res = [outputs.send_mail(addr, f"Reheating tonight's meals from {ctx.name}", body, "reheat",
                             household_dir(hid) / "output" / "outbox") for addr in to]
    return {"sent_to": len(to), "results": res}


# ---------------------------------------------------------------- voice notes
class VoiceNoteIn(BaseModel):
    text: str = Field(min_length=2, max_length=1000)
    household_id: str | None = None


@router.post("/api/chef/voice")
def voice_preview(body: VoiceNoteIn, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "voice_log")
    con = accounts.connect()
    names = _chef_clients(con, ctx.uid)
    con.close()
    parsed = pro.parse_note(body.text, names)
    if body.household_id:
        if body.household_id not in names:
            raise HTTPException(403, "you're not the chef for that household")
        parsed["household"] = body.household_id
    flags = []
    if parsed["household"]:
        with tenant(parsed["household"]):
            h = load_household()
            hc = store.connect()
            for a in parsed["actions"]:
                if a["kind"] in ("toss", "eaten"):
                    box = pro.find_container(hc, a["what"])
                    a["match"] = f"#{box['number']} {box['dish']}" if box else None
                if a["kind"] in ("made", "reheat") and (a.get("dish") or a.get("meal")):
                    hits = pro.allergen_hits(h, a.get("dish") or a.get("meal"))
                    if hits:
                        a["allergens"] = hits
                        flags.append(f"{(a.get('dish') or a.get('meal'))}: {', '.join(hits)}, and someone in "
                                     f"{h.info.get('name')} is allergic")
            hc.close()
    return {**parsed, "household_name": names.get(parsed["household"] or "", None), "flags": list(dict.fromkeys(flags)),
            "say": _say(parsed, names)}


def _say(p: dict, names: dict) -> str:
    if not p["household"]:
        return "Which kitchen is this for? Say the family's name, or pick it."
    bits = []
    for a in p["actions"]:
        if a["kind"] == "made":
            bits.append(f"{a['portions']:g} portions of {a['dish']} in " +
                        " and ".join(f"{c['portions']:g} {c['location']}" for c in a["containers"]))
        elif a["kind"] == "reheat":
            bits.append(f"a reheat card ({a['method']}{', ' + str(a['temp_f']) + '°F' if a.get('temp_f') else ''}, "
                        f"{a['minutes']} min)")
        elif a["kind"] in ("toss", "eaten"):
            bits.append(f"{'toss' if a['kind'] == 'toss' else 'finish'} {a['what']}")
        elif a["kind"] == "shop":
            bits.append(f"add {a['item']} to their list")
    return f"For {names.get(p['household'], 'them')}: " + "; ".join(bits) + ". Confirm?" if bits else \
        "I didn't catch anything to log. Try: made 4 portions of chili, fridge two, freeze two."


class VoiceApplyIn(BaseModel):
    household_id: str
    actions: list[dict]
    confirm_allergen: bool = False


@router.post("/api/chef/voice/apply")
def voice_apply(body: VoiceApplyIn, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "voice_log")
    _client_of(ctx.uid, body.household_id)
    with tenant(body.household_id):
        h = load_household()
        hc = store.connect()
        try:
            return pro.apply_note(h, hc, {"actions": body.actions}, f"chef:{ctx.uid}", body.confirm_allergen)
        except pro.ProError as e:
            _err(e, 409 if "allergic" in str(e) else 422)
        except (KeyError, TypeError, ValueError):
            _err(ValueError("that preview doesn't look right; say it again"))
        finally:
            hc.close()


# ---------------------------------------------------------------- shopping across homes, ledger, invoices
def _homes(uid: str, start: dt.date, days: int) -> tuple[list[dict], dict[str, str]]:
    con = accounts.connect()
    names = _chef_clients(con, uid)
    con.close()
    db = pro.chef_db(uid)
    cls = {h: pro.client(db, h) for h in names}
    db.close()
    homes = [pro.home_needs(h, cls[h], start, days) for h in names]
    return [hm for hm in homes if hm["need"]], {h: cls[h]["billing"] for h in names}


@router.get("/api/chef/shopping")
def chef_shopping(start: str | None = None, days: int = 3, ctx=Depends(signed_in)) -> dict:
    """Solo: each home's list for the next visits. Studio: one trip across homes (merged, split, routed)."""
    plan = _gate(ctx.uid, "cockpit")
    d0 = dt.date.fromisoformat(start) if start else dt.date.today()
    days = max(1, min(days, 7))
    homes, billing = _homes(ctx.uid, d0, days)
    c = catalog.get()
    per_home = [{"household_id": hm["household_id"], "name": hm["name"], "visits": hm["visits"],
                 "items": [{"name": c.ingredients[i].name if i in c.ingredients else i, "qty": n["qty"],
                            "unit": c.ingredients[i].unit if i in c.ingredients else "", "brand": n["brand"],
                            "for": n["for"]} for i, n in sorted(hm["need"].items(), key=lambda kv:
                                                                  c.ingredients[kv[0]].aisle if kv[0] in c.ingredients else 99)]}
                for hm in homes]
    out = {"start": d0.isoformat(), "days": days, "per_home": per_home, "trip": None, "studio": plan == "chef_studio"}
    if plan == "chef_studio" and homes:
        out["trip"] = pro.build_trip(ctx.uid, homes, billing, d0)
    return out


class TripIn(BaseModel):
    start: str | None = None
    days: int = Field(default=3, ge=1, le=7)


@router.post("/api/chef/trips")
def save_trip(body: TripIn, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "batch_trip")
    d0 = dt.date.fromisoformat(body.start) if body.start else dt.date.today()
    homes, billing = _homes(ctx.uid, d0, body.days)
    if not homes:
        raise HTTPException(409, "nothing to buy for the next visits (no planned meals, or the pantries cover them)")
    trip = pro.build_trip(ctx.uid, homes, billing, d0)
    tid = pro.save_trip(ctx.uid, trip)
    return {"id": tid, **trip}


@router.get("/api/chef/trips/{tid}")
def get_trip(tid: str, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "batch_trip")
    db = pro.chef_db(ctx.uid)
    try:
        return pro.get_trip(db, tid)
    except pro.ProError as e:
        _err(e, 404)
    finally:
        db.close()


class PaidIn(BaseModel):
    store: str
    paid_by: str = "chef"
    household_id: str | None = None
    actual: float | None = Field(default=None, ge=0, le=10000)


@router.post("/api/chef/trips/{tid}/paid")
def trip_paid(tid: str, body: PaidIn, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "card_routing")
    db = pro.chef_db(ctx.uid)
    try:
        rows = pro.record_checkout(db, tid, body.store, body.paid_by, body.household_id, body.actual)
    except pro.ProError as e:
        _err(e)
    finally:
        db.close()
    return {"ledger": rows}


class ReceiptIn(BaseModel):
    household_id: str
    store: str = Field(min_length=1, max_length=40)
    amount: float = Field(gt=0, le=10000)
    card: str | None = Field(default=None, max_length=40)
    date: str | None = None
    note: str = Field(default="", max_length=200)
    paid_by: str = "chef"


@router.post("/api/chef/ledger")
def add_receipt(body: ReceiptIn, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "client_ledger")
    _client_of(ctx.uid, body.household_id)
    if body.paid_by not in ("chef", "client"):
        raise HTTPException(422, "paid_by is chef or client")
    db = pro.chef_db(ctx.uid)
    try:
        rid = pro.add_receipt(db, body.household_id, body.store, body.amount, body.card,
                              dt.date.fromisoformat(body.date) if body.date else dt.date.today(), body.note, body.paid_by)
    except pro.ProError as e:
        _err(e)
    finally:
        db.close()
    return {"id": rid}


@router.get("/api/chef/ledger")
def get_ledger(household_id: str | None = None, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "client_ledger")
    con = accounts.connect()
    names = _chef_clients(con, ctx.uid)
    con.close()
    if household_id and household_id not in names:
        raise HTTPException(403, "you're not the chef for that household")
    db = pro.chef_db(ctx.uid)
    rows = [r for r in pro.ledger(db, household_id) if r["household_id"] in names]
    inv = [dict(r) for r in db.execute("SELECT id, household_id, created, total, status FROM invoices ORDER BY created DESC")
           if r["household_id"] in names]
    budgets = {h: {"budget": pro.client(db, h)["budget"], "spent": pro.week_spend(db, h, dt.date.today())} for h in names}
    db.close()
    for r in rows:
        r["name"] = names.get(r["household_id"], "")
    totals = {"pending": round(sum(r["amount"] for r in rows if r["status"] == "pending"), 2),
              "rewards": round(sum(r["rewards"] or 0 for r in rows), 2)}
    return {"rows": rows[:200], "invoices": inv, "budgets": budgets, "totals": totals, "names": names}


class InvoiceIn(BaseModel):
    household_id: str
    send: bool = True


@router.post("/api/chef/invoices")
def new_invoice(body: InvoiceIn, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "invoices")
    name = _client_of(ctx.uid, body.household_id)
    db = pro.chef_db(ctx.uid)
    try:
        inv = pro.make_invoice(db, body.household_id, name)
    except pro.ProError as e:
        db.close()
        _err(e, 409)
    db.close()
    sent = []
    if body.send:
        from . import outputs
        from .config import household_dir
        with tenant(body.household_id):
            h = load_household()
        for p in h.people.values():
            if p.admin and p.email:
                sent.append(outputs.send_mail(p.email, f"Grocery expenses from {ctx.name}: ${inv['total']:.2f}",
                                              pro.invoice_html(inv, _brand(ctx.uid)), "invoice",
                                              household_dir(body.household_id) / "output" / "outbox"))
    return {**inv, "sent": sent}


@router.post("/api/chef/invoices/{iid}/paid")
def invoice_paid(iid: str, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "invoices")
    db = pro.chef_db(ctx.uid)
    try:
        inv = pro.invoice(db, iid)
        _client_of(ctx.uid, inv["household_id"])
        pro.mark_paid(db, iid)
    except pro.ProError as e:
        _err(e, 404)
    finally:
        db.close()
    return {"paid": iid}


# ---------------------------------------------------------------- coverage packs
class CoverIn(BaseModel):
    sub_name: str = Field(min_length=1, max_length=60)
    sub_email: str = Field(max_length=200)
    start: str
    end: str
    households: list[str]
    level: str = "view_recipes_and_routines"
    password: str = Field(min_length=8, max_length=100)


@router.post("/api/chef/coverage")
def new_coverage(body: CoverIn, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "coverage")
    for h in body.households:
        _client_of(ctx.uid, h)
    db = pro.chef_db(ctx.uid)
    try:
        email = accounts.norm_email(body.sub_email)
        row = pro.make_coverage(db, body.sub_name, email, dt.date.fromisoformat(body.start),
                                dt.date.fromisoformat(body.end), body.households, body.level, body.password)
    except ValueError as e:
        db.close()
        _err(e)
    db.close()
    a = _api()
    url = f"{a.public_url()}/pro/cover/{ctx.uid}/{row['id']}"
    a._send_email(email, f"{ctx.name} shared a coverage pack with you",
                  f"<p>{html.escape(ctx.name)} asked you to cover their Dinner Peace Pro kitchens from {row['start']} "
                  f"to {row['end']}.</p><p><a href='{html.escape(url)}'>Open the coverage pack</a>. {html.escape(ctx.name)} "
                  f"will send you the password separately.</p>", "coverage")
    return {**row, "url": url}


@router.get("/api/chef/coverage")
def list_coverage(ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "coverage")
    db = pro.chef_db(ctx.uid)
    rows = [pro.coverage_row(db, r["id"]) for r in db.execute("SELECT id FROM coverage ORDER BY created DESC")]
    db.close()
    a = _api()
    for r in rows:
        r["url"] = f"{a.public_url()}/pro/cover/{ctx.uid}/{r['id']}"
    return {"packs": rows}


@router.delete("/api/chef/coverage/{cid}")
def revoke_coverage(cid: str, ctx=Depends(signed_in)) -> dict:
    _gate(ctx.uid, "coverage")
    db = pro.chef_db(ctx.uid)
    n = db.execute("UPDATE coverage SET revoked = 1 WHERE id = ?", (cid,)).rowcount
    db.commit()
    db.close()
    if not n:
        raise HTTPException(404, "no such coverage pack")
    return {"revoked": cid}


FORM = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='robots' content='noindex'><title>Coverage pack</title><style>body{{font-family:Nunito,Arial,sans-serif;"
        "background:#FAF7F2;color:#2B231D;display:flex;justify-content:center;padding:40px 16px}}form{{background:#FFFDF9;"
        "border:1px solid #E8E0D5;border-radius:24px;padding:24px;max-width:360px;width:100%}}input{{width:100%;padding:12px;"
        "border-radius:12px;border:1px solid #E8E0D5;font-size:16px;box-sizing:border-box}}button{{margin-top:12px;"
        "width:100%;padding:12px;border:0;border-radius:12px;background:#8E683E;color:#FFFDF9;font-weight:800;font-size:16px}}"
        ".e{{color:#9B2C24}}</style></head><body><form method='post'><h2>Coverage pack</h2><p>Enter the password the chef "
        "sent you.</p><p class='e'>{error}</p><input type='password' name='password' autocomplete='current-password' "
        "required><button>Open</button></form></body></html>")


@router.get("/pro/cover/{uid}/{cid}", response_class=HTMLResponse)
def cover_form(uid: str, cid: str) -> str:
    return FORM.format(error="")


@router.post("/pro/cover/{uid}/{cid}", response_class=HTMLResponse)
def cover_open(uid: str, cid: str, request: Request, password: str = Form(default="")) -> HTMLResponse:
    a = _api()
    try:
        a.rate_limit(f"cover:{cid}:{request.client.host if request.client else '-'}", 10)
    except HTTPException:
        return HTMLResponse(FORM.format(error="Too many tries; wait an hour."), status_code=429)
    try:
        db = pro.chef_db(uid)
    except pro.ProError:
        return HTMLResponse(FORM.format(error="This coverage pack isn't available."), status_code=404)
    try:
        row = pro.coverage_open(db, cid, password, dt.date.today())
    except pro.ProError as e:
        db.close()
        return HTMLResponse(FORM.format(error=html.escape(str(e).capitalize() + ".")), status_code=403)
    db.close()
    con = accounts.connect()
    still = plans.has(plans.chef_plan(con, uid), "coverage")
    names = _chef_clients(con, uid)
    chef = accounts.user(con, uid)
    con.close()
    if not still:
        return HTMLResponse(FORM.format(error="This coverage pack isn't available."), status_code=403)
    homes = pro.coverage_content(uid, row, names)
    return HTMLResponse(pro.coverage_html(row, homes, chef["name"] if chef else "your colleague"),
                        headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- what the family sees (any plan)
@router.get("/api/household/fridge")
def family_fridge(ctx=Depends(member)) -> dict:
    """The containers and reheat cards the chef left: free for every household (Chef connection)."""
    hc = store.connect()
    out = {"containers": pro.open_containers(hc), "cards": pro.recent_cards(hc), "list": pro.open_list(hc)}
    hc.close()
    con = accounts.connect()
    chefs = [m["name"] for m in accounts.members(con, ctx.hid) if m["role"] == "chef"]
    out["plan"] = plans.household_plan(con, ctx.hid)
    con.close()
    out["chefs"] = chefs
    return out


@router.post("/api/household/fridge/{cid}")
def family_close(cid: int, body: CloseIn, ctx=Depends(member)) -> dict:
    hc = store.connect()
    try:
        pro.close_container(hc, cid, body.status, _api().actor(ctx))
    except pro.ProError as e:
        _err(e, 404)
    finally:
        hc.close()
    return {"closed": cid}


class ChefInviteIn(BaseModel):
    email: str = Field(max_length=200)


@router.post("/api/household/chef-invite")
def invite_chef(body: ChefInviteIn, ctx=Depends(member)) -> dict:
    """The family's admin invites their personal chef (who needs Dinner Peace Pro to use the chef tools)."""
    _api().need(ctx, "admin")
    _api().rate_limit(f"invite:{ctx.hid}", 20)
    try:
        email = accounts.norm_email(body.email)
    except ValueError as e:
        _err(e)
    return {"invited": _invite(ctx, ctx.hid, None, email, "chef"), "role": "chef"}
