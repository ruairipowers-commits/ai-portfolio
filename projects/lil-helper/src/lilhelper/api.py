"""The API the phone app talks to (FastAPI). One server can hold many households; each household's data stays in
its own folder and database, and every request is pointed at the caller's household only.

Sign-in: type your email, get a one-time link (15 minutes); the app keeps a signed session (30 days) naming you and
your current household. New households need a sign-up code until open sign-up is turned on (HELPER_SIGNUP);
everyone else joins by invitation. Roles: admin (settings, people, invites), adult (plan, approve, shop, spend),
kid (see the week and jobs, say how much was eaten, rate). Nothing here buys anything.

Calendar: each person gets a private feed URL to subscribe to; events carry signed one-tap links back here (rate the
meal, how much was left, change it, the shopping list). Push: the app registers an Expo push token.

Secrets come from the environment (SEC-01): HELPER_SECRET signs links, sessions, feeds and tap-back links.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass

import httpx
import yaml
from urllib.parse import quote
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from . import (__version__, accounts, alexa, recipebook, ai, catalog, chores, cookfrom, feedback, forecast, money, notify, outputs,
               reports, spend, storage, store, telemetry, week)
from .config import (ROOT, ALLERGENS, DAYS, DIETS, MEALS, NIGHT_KINDS, HouseholdError, Settings, data_root, load_household,
                     reset_tenant, save_household, set_tenant, stores as load_stores, work_root)
from .prices import PriceBook, week_start

DEV_SECRET = "dev-only-not-secret"
LINK_TTL = 15 * 60
SESSION_TTL = 30 * 24 * 3600
TAP_TTL = 30 * 24 * 3600
INSTACART = {"development": "https://connect.dev.instacart.tools", "production": "https://connect.instacart.com"}

app = FastAPI(title="DinnerPeace", version=__version__, root_path=os.getenv("ROOT_PATH", ""))
app.include_router(alexa.router)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("HELPER_CORS", "*").split(","), allow_methods=["*"],
                   allow_headers=["*"])


@app.on_event("startup")
def _startup() -> None:
    _secret()                       # production: stop at start-up if HELPER_SECRET is missing, not at first sign-in
    if os.getenv("HELPER_SCHEDULER") == "1":
        from . import schedule
        schedule.start()


# ---------------------------------------------------------------- signing
def _secret() -> bytes:
    sec = os.getenv("HELPER_SECRET", "")
    if not sec:
        if os.getenv("HELPER_ENV") == "production":
            raise RuntimeError("HELPER_SECRET must be set in production")
        sec = DEV_SECRET
    return sec.encode()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def sign(kind: str, subject: str, ttl: int) -> str:
    body = json.dumps({"k": kind, "s": subject, "e": int(time.time()) + ttl}, separators=(",", ":")).encode()
    return _b64(body) + "." + _b64(hmac.new(_secret(), body, hashlib.sha256).digest())


def verify(kind: str, token: str) -> str:
    try:
        b64, m64 = token.split(".")
        body = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
        mac = base64.urlsafe_b64decode(m64 + "=" * (-len(m64) % 4))
    except Exception:
        raise HTTPException(401, "bad token")
    if not hmac.compare_digest(mac, hmac.new(_secret(), body, hashlib.sha256).digest()):
        raise HTTPException(401, "bad token")
    d = json.loads(body)
    if d["k"] != kind or d["e"] < time.time():
        raise HTTPException(401, "expired")
    return d["s"]


def public_url() -> str:
    return os.getenv("HELPER_PUBLIC_URL", "http://localhost:8650").rstrip("/")


def feed_sig(hid: str, uid: str, salt: str) -> str:
    return hmac.new(_secret(), f"feed|{hid}|{uid}|{salt}".encode(), hashlib.sha256).hexdigest()[:32]


# ---------------------------------------------------------------- who's calling
@dataclass
class Ctx:
    uid: str
    hid: str | None
    role: str | None
    person: str | None
    email: str
    name: str


def _session(authorization: str) -> tuple[str, str | None]:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "sign in first")
    sub = verify("session", authorization[7:])
    uid, _, hid = sub.partition("|")
    return uid, hid or None


async def signed_in(authorization: str = Header(default="")) -> Ctx:
    """Any signed-in person (no household needed: for the welcome wizard)."""
    uid, hid = _session(authorization)
    con = accounts.connect()
    u = accounts.user(con, uid)
    con.close()
    if not u:
        raise HTTPException(401, "that account no longer exists")
    return Ctx(uid, hid, None, None, u["email"], u["name"])


async def member(authorization: str = Header(default="")):
    """A member of the session's household. Points the engine at that household for the rest of the request."""
    uid, hid = _session(authorization)
    if not hid:
        raise HTTPException(409, "set up or join a household first")
    con = accounts.connect()
    u = accounts.user(con, uid)
    m = accounts.membership(con, uid, hid) if u else None
    if m:
        accounts.touch(con, uid)
    con.close()
    if not u or not m:
        raise HTTPException(403, "you're not a member of that household")
    tok = set_tenant(hid)
    try:
        yield Ctx(uid, hid, m["role"], m["person_id"], u["email"], u["name"])
    finally:
        reset_tenant(tok)


def need(ctx: Ctx, role: str) -> None:
    order = {"kid": 0, "adult": 1, "admin": 2}
    if order.get(ctx.role or "kid", 0) < order[role]:
        raise HTTPException(403, f"only {'an admin' if role == 'admin' else 'an adult'} in the household can do that")


def actor(ctx: Ctx) -> str:
    return ctx.person or ctx.uid


# ---------------------------------------------------------------- small helpers
_hits: dict[str, list[float]] = defaultdict(list)


def rate_limit(key: str, per_hour: int) -> None:
    now = time.time()
    _hits[key] = [t for t in _hits[key] if now - t < 3600]
    if len(_hits[key]) >= per_hour:
        raise HTTPException(429, "too many requests; try again later")
    _hits[key].append(now)


def _week(w: str | None) -> dt.date:
    return week_start(dt.date.fromisoformat(w) if w else dt.date.today())


def _stored(w: dt.date) -> dict:
    con = store.connect()
    rec = store.get_week(con, w.isoformat())
    con.close()
    if not rec:
        raise HTTPException(404, "no plan for that week yet")
    return rec


def _hh():
    try:
        return load_household()
    except HouseholdError as e:
        raise HTTPException(409, str(e))


def _send_email(to: str, subject: str, body_html: str, tag: str) -> str:
    # account emails aren't any one household's, so their outbox is the server's
    return outputs.send_mail(to, subject, body_html, tag, data_root() / "outbox")


# ---------------------------------------------------------------- sign-in and accounts
class EmailIn(BaseModel):
    email: str = Field(max_length=200)
    invite: str | None = Field(default=None, max_length=100)


class TokenIn(BaseModel):
    token: str = Field(max_length=600)
    invite: str | None = Field(default=None, max_length=100)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__, "signup": accounts.signup_mode(),
            "email": "resend" if os.getenv("RESEND_API_KEY") else "outbox (RESEND_API_KEY not set)"}


@app.post("/api/auth/request")
def auth_request(body: EmailIn, request: Request) -> dict:
    """Always answers the same way, so it doesn't reveal who has an account."""
    try:
        email = accounts.norm_email(body.email)
    except ValueError as e:
        raise HTTPException(422, str(e))
    rate_limit(f"ip:{request.client.host if request.client else '-'}", 30)
    rate_limit(f"email:{email}", 5)
    con = accounts.connect()
    known = accounts.user_by_email(con, email)
    con.close()
    if known or accounts.signup_mode() != "closed" or body.invite:
        q = f"token={sign('link', email, LINK_TTL)}" + (f"&invite={body.invite}" if body.invite else "")
        link = f"{os.getenv('HELPER_APP_LINK', 'lilhelper://signin')}?{q}"
        _send_email(email, "Your DinnerPeace sign-in link",
                    f"<p>Tap to sign in to DinnerPeace (valid 15 minutes):</p><p><a href='{html.escape(link)}'>"
                    f"{html.escape(link)}</a></p>", "signin")
    return {"sent": True, "message": "Check your email for a sign-in link."}


def _session_for(con, uid: str, hid: str | None) -> dict:
    ms = accounts.memberships(con, uid)
    if hid is None and ms:
        hid = ms[0]["household_id"]
    u = accounts.user(con, uid)
    return {"session": sign("session", f"{uid}|{hid or ''}", SESSION_TTL), "user": {"id": uid, "email": u["email"],
            "name": u["name"]}, "household": hid, "households": ms}


@app.post("/api/auth/verify")
def auth_verify(body: TokenIn) -> dict:
    email = verify("link", body.token)
    con = accounts.connect()
    u = accounts.get_or_create_user(con, email)
    hid = None
    if body.invite:
        try:
            hid = accounts.accept_invite(con, body.invite, u["id"], email)["household_id"]
        except ValueError as e:
            con.close()
            raise HTTPException(409, str(e))
    out = _session_for(con, u["id"], hid)
    con.close()
    return out


@app.get("/api/me")
def me(ctx: Ctx = Depends(signed_in)) -> dict:
    con = accounts.connect()
    ms = accounts.memberships(con, ctx.uid)
    con.close()
    cur = next((m for m in ms if m["household_id"] == ctx.hid), None)
    return {"user": {"id": ctx.uid, "email": ctx.email, "name": ctx.name}, "households": ms, "current": cur,
            "signup": accounts.signup_mode()}


class SwitchIn(BaseModel):
    household_id: str


@app.post("/api/session/household")
def switch_household(body: SwitchIn, ctx: Ctx = Depends(signed_in)) -> dict:
    con = accounts.connect()
    if not accounts.membership(con, ctx.uid, body.household_id):
        con.close()
        raise HTTPException(403, "you're not a member of that household")
    out = _session_for(con, ctx.uid, body.household_id)
    con.close()
    return out


class NewHouseholdIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    region: str = "northeast-us"
    timezone: str = Field(default="America/New_York", max_length=60)
    your_name: str = Field(min_length=1, max_length=40)
    signup_code: str | None = Field(default=None, max_length=100)


def _pid(name: str, taken) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:20] or "person"
    pid, n = base, 2
    while pid in taken:
        pid, n = f"{base}_{n}", n + 1
    return pid


@app.post("/api/households")
def create_household(body: NewHouseholdIn, ctx: Ctx = Depends(signed_in)) -> dict:
    """The welcome wizard's first step: a new household, with you as its admin."""
    if not accounts.signup_code_ok(body.signup_code):
        raise HTTPException(403, "a sign-up code is needed to start a new household (or ask to be invited)")
    con = accounts.connect()
    try:
        hid = accounts.create_household(con, ctx.uid, body.name, body.region,
                                        {"id": _pid(body.your_name, set()), "name": body.your_name,
                                         "email": ctx.email, "can_cook": True}, body.timezone)
    except (ValueError, HouseholdError) as e:
        con.close()
        raise HTTPException(422, str(e))
    out = _session_for(con, ctx.uid, hid)
    con.close()
    return out


@app.delete("/api/account")
def delete_account(ctx: Ctx = Depends(signed_in)) -> dict:
    """Delete my account (in the app, as the App Store requires). Households left with nobody are deleted too."""
    con = accounts.connect()
    gone = accounts.delete_user(con, ctx.uid)
    con.close()
    return {"deleted": True, "households_deleted": len(gone)}


class ConfirmName(BaseModel):
    confirm: str


@app.delete("/api/household")
def delete_household(body: ConfirmName, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "admin")
    h = _hh()
    if body.confirm.strip() != h.info.get("name"):
        raise HTTPException(422, "type the household's name to confirm")
    con = accounts.connect()
    accounts.delete_household(con, ctx.hid)
    con.close()
    return {"deleted": True}


# ---------------------------------------------------------------- household settings (admin)
def _version() -> str:
    from .config import household_path
    return hashlib.sha256(household_path().read_bytes()).hexdigest()[:12]


def _catalogs() -> dict:
    st = load_stores()["stores"]
    m = money.catalog()
    return {"allergens": list(ALLERGENS), "diets": list(DIETS), "night_kinds": list(NIGHT_KINDS),
            "days": DAYS, "meals": MEALS, "regions": ["northeast-us"],
            "stores": [{"id": k, "name": v["name"], "modes": list(v["modes"]), "needs": v.get("needs")}
                       for k, v in st.items()],
            "cards": [{"id": k, "name": v["name"], "verified": str(v.get("verified") or "")} for k, v in m["cards"].items()],
            "memberships": [{"id": k, "name": v["name"]} for k, v in m["memberships"].items()],
            "styles": ["kid_friendly", "kid_can_make", "one_pot", "sheet_pan", "slow_cooker", "batch", "leftovers",
                       "vegetarian", "freezes_well"]}


@app.get("/api/household/settings")
def get_settings(ctx: Ctx = Depends(member)) -> dict:
    h = _hh()
    return {"settings": h.raw, "version": _version(), "role": ctx.role, "me": ctx.person, "catalogs": _catalogs()}


class SettingsIn(BaseModel):
    settings: dict
    version: str


@app.put("/api/household/settings")
def put_settings(body: SettingsIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "admin")
    if body.version != _version():
        raise HTTPException(409, "someone else changed the settings; reload and try again")
    raw = body.settings
    raw["require_admin"] = True
    try:
        save_household(raw)
    except (HouseholdError, KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, str(e))
    con = store.connect()
    store.audit(con, actor(ctx), "settings", {"sections": sorted(raw)})
    con.close()
    return {"saved": True, "version": _version()}


SECTIONS = {"household", "meals", "dinner_times", "prep_minutes", "batch_day", "health", "brands", "stores",
            "home_store", "memberships", "cards", "suggestions", "chores", "outputs", "styles", "kid_chef", "leftovers",
            "eating_out", "cost_per_serving", "storage", "freezer_meals", "shopping_sessions", "pets",
            "plan_ahead_weeks", "recipe_sources", "occasions", "holidays", "holidays_off", "buffet",
            "ingredient_prefs", "use_book"}


class SectionIn(BaseModel):
    value: object = None


@app.patch("/api/household/settings/{section}")
def patch_section(section: str, body: SectionIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "admin")
    if section not in SECTIONS:
        raise HTTPException(404, "unknown settings section")
    h = _hh()
    raw = h.raw
    if body.value is None:
        raw.pop(section, None)
    else:
        raw[section] = body.value
    raw["require_admin"] = True
    try:
        save_household(raw)
    except (HouseholdError, KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, str(e))
    con = store.connect()
    store.audit(con, actor(ctx), "settings", {"section": section})
    con.close()
    return {"saved": True, "version": _version(), "value": raw.get(section)}


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    age_band: str = "adult"
    age: int | None = Field(default=None, ge=0, le=120)
    allergies: list[str] = []
    diet: list[str] = []
    portion: float = Field(default=1.0, ge=0.2, le=3.0)
    likes: list[str] = []
    dislikes: list[str] = []
    home: list[str] = Field(default_factory=lambda: list(DAYS))
    can_cook: bool = False
    email: str | None = None
    admin: bool = False
    birthday: str | None = Field(default=None, max_length=10)     # YYYY-MM-DD, or MM-DD
    can_approve: bool | None = None

    def model_post_init(self, _):
        # with a birthday, child or adult follows from it (under 12 is a child)
        if self.birthday and len(self.birthday) == 10:
            try:
                b = dt.date.fromisoformat(self.birthday)
            except ValueError:
                return
            t = dt.date.today()
            years = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
            self.age, self.age_band = years, ("kid" if years < 12 else "adult")


@app.get("/api/household/people")
def people(ctx: Ctx = Depends(member)) -> dict:
    h = _hh()
    con = accounts.connect()
    ms = accounts.members(con, ctx.hid)
    inv = accounts.pending_invites(con, ctx.hid)
    con.close()
    by_person = {m["person_id"]: m for m in ms}
    out = []
    for p in h.people.values():
        d = {k: v for k, v in h.raw["people"][p.id].items()}
        m = by_person.get(p.id)
        d.update({"id": p.id, "role": m["role"] if m else p.role, "age_now": p.current_age, "child": p.is_kid,
                  "teen": p.is_teen,
                  "signed_up": bool(m), "invited": any(i["person_id"] == p.id for i in inv),
                  "last_seen": m["last_seen"] if m else None})
        out.append(d)
    return {"people": out, "pets": h.raw.get("pets") or {}, "me": ctx.person, "role": ctx.role}


@app.post("/api/household/people")
def add_person(body: PersonIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "admin")
    h = _hh()
    pid = _pid(body.name, h.people)
    h.raw["people"][pid] = {k: v for k, v in body.model_dump().items() if v not in (None, [], False) or k in
                            ("home",)}
    h.raw["require_admin"] = True
    try:
        save_household(h.raw)
    except HouseholdError as e:
        raise HTTPException(422, str(e))
    return {"added": pid}


@app.put("/api/household/people/{pid}")
def edit_person(pid: str, body: PersonIn, ctx: Ctx = Depends(member)) -> dict:
    h = _hh()
    if pid not in h.people:
        raise HTTPException(404, "no such person")
    if ctx.role != "admin":
        # anyone may change their own likes and dislikes; everything else is the admin's
        if pid != ctx.person:
            raise HTTPException(403, "only an admin can change someone else's details")
        cur = h.raw["people"][pid]
        cur["likes"], cur["dislikes"] = body.likes, body.dislikes
    else:
        h.raw["people"][pid] = {k: v for k, v in body.model_dump().items() if v not in (None, [], False) or k in
                                ("home",)}
    h.raw["require_admin"] = True
    try:
        save_household(h.raw)
    except HouseholdError as e:
        raise HTTPException(422, str(e))
    con = accounts.connect()
    for m in accounts.members(con, ctx.hid):
        if m["person_id"] == pid and ctx.role == "admin":
            want = h2.people[pid].role if (h2 := _hh()) and pid in h2.people else m["role"]
            if want != m["role"]:
                try:
                    accounts.set_role(con, ctx.hid, m["user_id"], want)
                except ValueError as e:
                    con.close()
                    raise HTTPException(422, str(e))
    con.close()
    return {"saved": pid}


@app.delete("/api/household/people/{pid}")
def remove_person(pid: str, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "admin")
    h = _hh()
    if pid not in h.people:
        raise HTTPException(404, "no such person")
    if pid == ctx.person:
        raise HTTPException(422, "you can't remove yourself here; delete your account in Settings instead")
    con = accounts.connect()
    for m in accounts.members(con, ctx.hid):
        if m["person_id"] == pid:
            accounts.remove_member(con, ctx.hid, m["user_id"])
    con.close()
    del h.raw["people"][pid]
    for meal in MEALS:
        cfg = h.raw["meals"].get(meal) or {}
        if isinstance(cfg.get("eaters"), list) and pid in cfg["eaters"]:
            cfg["eaters"] = [x for x in cfg["eaters"] if x != pid] or "all"
    h.raw["kid_chef"] = {d: p for d, p in (h.raw.get("kid_chef") or {}).items() if p != pid}
    h.raw["require_admin"] = True
    try:
        save_household(h.raw)
    except HouseholdError as e:
        raise HTTPException(422, str(e))
    return {"removed": pid}


class InviteIn(BaseModel):
    person_id: str
    email: str = Field(max_length=200)


@app.post("/api/household/invites")
def invite(body: InviteIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "admin")
    h = _hh()
    if body.person_id not in h.people:
        raise HTTPException(404, "add the person first")
    p = h.people[body.person_id]
    role = p.role
    rate_limit(f"invite:{ctx.hid}", 20)
    con = accounts.connect()
    try:
        code = accounts.invite(con, ctx.hid, body.email, body.person_id, role, ctx.uid)
    except ValueError as e:
        con.close()
        raise HTTPException(422, str(e))
    con.close()
    email = accounts.norm_email(body.email)
    link = f"{os.getenv('HELPER_APP_LINK', 'lilhelper://signin')}?token={sign('link', email, accounts.INVITE_DAYS * 24 * 3600)}&invite={code}"
    _send_email(email, f"{ctx.name} invited you to {h.info.get('name')} on DinnerPeace",
                f"<p>{html.escape(ctx.name)} added you to <b>{html.escape(h.info.get('name', ''))}</b> on DinnerPeace, "
                f"the family meal planner.</p><p>Install DinnerPeace, then tap: <a href='{html.escape(link)}'>join "
                f"the household</a> (valid {accounts.INVITE_DAYS} days).</p>", "invite")
    return {"invited": email, "person": body.person_id, "role": role}


@app.delete("/api/household/members/{uid}")
def remove_member(uid: str, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "admin")
    con = accounts.connect()
    try:
        accounts.remove_member(con, ctx.hid, uid)
    except ValueError as e:
        con.close()
        raise HTTPException(422, str(e))
    con.close()
    return {"removed": uid}


@app.get("/api/occasions")
def upcoming_occasions(days: int = 60, ctx: Ctx = Depends(member)) -> dict:
    """Birthdays, anniversaries, the household's own dates and holidays coming up."""
    from . import occasions
    h = _hh()
    start = week.today_in(h)
    return {"upcoming": occasions.upcoming(h.raw, h.people, start, max(1, min(days, 366))),
            "holidays": [{"id": k, "name": v[0], "on": k not in set(h.raw.get("holidays_off") or [])}
                         for k, v in occasions.HOLIDAYS.items()],
            "occasions": h.raw.get("occasions") or []}


# ---------------------------------------------------------------- voice (the app's microphone, and Alexa)
class VoiceIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


def _say_list(items: list[str], n: int = 6) -> str:
    items = items[:n]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def run_voice(ctx: Ctx, text: str) -> dict:
    """Do what a spoken request asks (see voice.py) and say what happened."""
    from . import voice, workflows
    h = _hh()
    c = catalog.for_household(h)
    today = week.today_in(h)
    q = voice.parse(text, today)
    it = q["intent"]
    out = {"intent": it, "heard": text, "screen": None, "params": {}, "say": ""}
    wk = week_start(today)
    con = store.connect()
    rec = store.get_week(con, wk.isoformat())
    con.close()
    if it == "whats_for":
        e = next((e for e in (rec or {}).get("plan", {}).get("entries", []) if e["day"] == q["day"]
                  and e["meal"] == q["meal"]), None) if rec else None
        cook = next((a["name"] for a in (rec or {}).get("chores") or [] if a["day"] == q["day"] and a["job"] == "cook"), None)
        out["say"] = (f"{q['meal'].title()} {q['when']} is {e['name']}." + (f" {cook} is cooking." if cook else "")) if e \
            else f"There's no {q['meal']} planned {q['when']}."
        out.update(screen="week", params={"day": q["day"]})
    elif it == "shopping":
        if not rec or rec.get("status") != "approved":
            out["say"] = "This week's plan isn't approved yet, so there's no list."
        else:
            orders = week.orders(rec)
            if not orders:
                out["say"] = "Nothing to buy this week."
            else:
                o = orders[0]
                names = [ln["name"] for ln in o["lines"]]
                out["say"] = (f"{len(names)} things from {o['store_name']}: {_say_list(names, 8)}"
                              + (f", and {len(names) - 8} more." if len(names) > 8 else "."))
        out["screen"] = "shopping"
    elif it == "jobs":
        mine = [a["job"].replace("_", " ") for a in (rec or {}).get("chores") or []
                if a["day"] == q["day"] and a["person"] == ctx.person]
        out["say"] = f"Your jobs: {_say_list(mine)}." if mine else "No jobs for you today."
        out["screen"] = "jobs"
    elif it == "cook_with":
        res = cookfrom.suggest(h, c, PriceBook(h, today, catalog=c), text=q["have"], use_pantry=False, meal=q["meal"],
                               day=q["day"])
        top = res["ideas"][0] if res["ideas"] else None
        new = res.get("new_recipe")
        if top:
            out["say"] = f"How about {top['name']}? It " + ("uses everything you said." if len(top["uses_typed"]) ==
                                                             len(res["matched"]) or res["uses_everything"]
                                                             else f"uses the {', '.join(top['uses_typed'])}.")
        elif new:
            out["say"] = f"Nothing in your book uses all of that. Try {new['name']}; it's on your phone."
        else:
            out["say"] = "I couldn't match those. Try naming the main things you have."
        out.update(screen="cookfrom", params={"text": q["have"]}, data={"ideas": [i["name"] for i in res["ideas"][:3]]})
    elif it == "vibe":
        res = workflows.vibe(h, c, PriceBook(h, today, catalog=c), minutes=q["minutes"], moods=q["moods"], meal=q["meal"])
        names = [i["name"] for i in res["ideas"][:3]]
        out["say"] = f"In {q['minutes']} minutes: {_say_list(names)}." if names else "Nothing fits that; try more time."
        out.update(screen="vibe", params={"minutes": str(q["minutes"]), "moods": ",".join(q["moods"])})
    elif it == "surprise":
        r = workflows.surprise(h, c, meal=q["meal"], day=q["day"], seed=secrets.randbelow(10 ** 6))
        out["say"] = f"How about {r['name']}?" if r else "Nothing in the book fits tonight."
        out.update(screen="surprise", params={"recipe": r["recipe"]} if r else {})
    elif it == "buffet_count":
        items = workflows.buffet_restock(h, c, store.connect())
        hit = next((b for b in items if q["item"] and (q["item"] in b["name"].lower() or
                                                       all(w in b["name"].lower() for w in q["item"].split()))), None)
        if not hit:
            out["say"] = "I couldn't find that in your buffet."
        else:
            con = store.connect()
            workflows.set_buffet_stock(con, hit["meal"], hit["recipe"], float(q["count"]), actor(ctx))
            con.close()
            out["say"] = f"Got it: {q['count']:g} portions of {hit['name']} left."
        out["screen"] = "buffet"
    elif it in ("eaten", "rate"):
        try:
            r = _record_feedback(wk.isoformat(), q["day"], q["meal"], q.get("eaten"), q.get("rating"), actor(ctx))
            out["say"] = f"Thanks, saved for {r['meal']}."
        except HTTPException:
            out["say"] = f"There's no {q['meal']} planned that day."
    elif it == "plan":
        if ctx.role not in ("admin", "adult"):
            out["say"] = "Ask a grown-up to plan the week."
        else:
            target = wk + dt.timedelta(weeks=1) if q.get("next") else wk
            r = store.get_week(store.connect(), target.isoformat())
            if r and r.get("status") == "approved":
                out["say"] = "That week is already approved."
            else:
                week.draft(target, ideas=False, actor=actor(ctx))
                out["say"] = "Done. The plan is ready to look over on your phone."
        out.update(screen="week")
    else:
        out["say"] = ("Sorry, I didn't catch that. You can ask what's for dinner, what's on the shopping list, "
                      "what your jobs are, or tell me what you have to cook with.")
    return out


@app.post("/api/voice")
def voice_command(body: VoiceIn, ctx: Ctx = Depends(member)) -> dict:
    rate_limit(f"voice:{ctx.uid}", 120)
    return run_voice(ctx, body.text)


def run_as(uid: str, hid: str, text: str) -> dict:
    """Run a spoken request for a linked Alexa (same rules as the app: the person's own role)."""
    con = accounts.connect()
    u = accounts.user(con, uid)
    m = accounts.membership(con, uid, hid) if u else None
    con.close()
    if not u or not m:
        return {"say": "That Alexa link no longer works. Link it again from the DinnerPeace app."}
    rate_limit(f"voice:{uid}", 120)
    tok = set_tenant(hid)
    try:
        return run_voice(Ctx(uid, hid, m["role"], m["person_id"], u["email"], u["name"]), text)
    finally:
        reset_tenant(tok)


@app.get("/api/alexa")
def alexa_status(ctx: Ctx = Depends(member)) -> dict:
    return {"links": alexa.links(ctx.uid, ctx.hid), "configured": bool(os.getenv("HELPER_ALEXA_SKILL_ID")),
            "link_page": f"{public_url()}/alexa/link", "endpoint": f"{public_url()}/alexa"}


@app.post("/api/alexa/code")
def alexa_code(ctx: Ctx = Depends(member)) -> dict:
    rate_limit(f"alexa-code:{ctx.uid}", 10)
    return {"code": alexa.new_code(ctx.uid, ctx.hid), "minutes": alexa.CODE_TTL // 60}


@app.delete("/api/alexa")
def alexa_unlink(ctx: Ctx = Depends(member)) -> dict:
    return {"removed": alexa.unlink(ctx.uid, ctx.hid)}


# ---------------------------------------------------------------- bulk import / export (admin)
_bulk: dict[str, dict] = {}


@app.get("/api/bulk/export")
def bulk_export(ctx: Ctx = Depends(member)) -> Response:
    """Everything the planner uses, as one Excel workbook."""
    need(ctx, "admin")
    return _workbook()


@app.post("/api/bulk/link")
def bulk_link(ctx: Ctx = Depends(member)) -> dict:
    """A five-minute download link for the workbook (phones open downloads in the browser, without the session)."""
    need(ctx, "admin")
    return {"url": f"{public_url()}/bulk/{sign('bulk', f'{ctx.uid}|{ctx.hid}', 300)}/dinnerpeace.xlsx"}


@app.get("/bulk/{token}/dinnerpeace.xlsx")
def bulk_download(token: str) -> Response:
    uid, _, hid = verify("bulk", token).partition("|")
    con = accounts.connect()
    m = accounts.membership(con, uid, hid)
    con.close()
    if not m or m["role"] != "admin":
        raise HTTPException(403)
    tok = set_tenant(hid)
    try:
        return _workbook()
    finally:
        reset_tenant(tok)


def _workbook() -> Response:
    from . import bulk
    h = _hh()
    con = store.connect()
    data = bulk.export(h, catalog.for_household(h), con)
    con.close()
    name = re.sub(r"[^A-Za-z0-9]+", "-", h.info.get("name", "household")).strip("-").lower() or "household"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="dinnerpeace-{name}.xlsx"'})


@app.post("/api/bulk/import")
async def bulk_import(file: UploadFile = File(...), ctx: Ctx = Depends(member)) -> dict:
    """Read an edited workbook and show what it would change. Nothing is saved until you confirm."""
    need(ctx, "admin")
    from . import bulk
    data = await file.read()
    if len(data) > 10_000_000:
        raise HTTPException(413, "file too large (10 MB max)")
    h = _hh()
    con = store.connect()
    try:
        plan = bulk.plan_import(h, catalog.for_household(h), con, data)
    except Exception as e:                      # not a workbook, or one we can't read
        raise HTTPException(422, f"couldn't read that workbook ({type(e).__name__})")
    finally:
        con.close()
    token = secrets.token_urlsafe(8)
    _bulk[f"{ctx.hid}:{token}"] = plan
    return {"token": token, "changes": plan["changes"], "problems": plan["problems"]}


class BulkConfirmIn(BaseModel):
    token: str


@app.post("/api/bulk/import/confirm")
def bulk_confirm(body: BulkConfirmIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "admin")
    from . import bulk
    plan = _bulk.pop(f"{ctx.hid}:{body.token}", None)
    if not plan:
        raise HTTPException(404, "upload the workbook again")
    h = _hh()
    con = store.connect()
    try:
        return bulk.apply_import(h, catalog.for_household(h), con, plan, actor(ctx))
    except (HouseholdError, recipebook.RecipeError) as e:
        raise HTTPException(422, str(e))
    finally:
        con.close()


# ---------------------------------------------------------------- ways to decide: vibe, occasion, buffet, surprise, plan
class VibeIn(BaseModel):
    minutes: int = Field(default=45, ge=5, le=600)
    moods: list[str] = []
    meal: str = "dinner"
    day: str | None = None
    people: list[str] = []
    have: str = Field(default="", max_length=1000)


@app.post("/api/vibe")
def vibe_cooking(body: VibeIn, ctx: Ctx = Depends(member)) -> dict:
    """How much time you have and what you're in the mood for → ideas, with what's missing to order."""
    from . import workflows
    h = _hh()
    c = catalog.for_household(h)
    return workflows.vibe(h, c, PriceBook(h, dt.date.today(), catalog=c), minutes=body.minutes,
                          moods=[m for m in body.moods if m in workflows.MOODS], meal=body.meal, day=body.day,
                          people=body.people or None, have=body.have)


class MissingIn(BaseModel):
    recipe: str
    servings: float = Field(default=4, gt=0, le=60)


@app.post("/api/vibe/order")
def vibe_order(body: MissingIn, ctx: Ctx = Depends(member)) -> dict:
    """A quick list for one recipe (what isn't in the house), split the cheapest way, ready to hand to a store."""
    need(ctx, "adult")
    h = _hh()
    c = catalog.for_household(h)
    r = c.recipes.get(body.recipe)
    if not r:
        raise HTTPException(404, "no such recipe")
    con = store.connect()
    pantry = store.pantry(con)
    con.close()
    from .shopping import Need, split
    needs = [Need(i, c.ingredients[i].name, round(q * body.servings - max(0, pantry.get(i, 0)), 3), c.ingredients[i].unit,
                  ["now"], 0)
             for i, q in r.ing.items() if not c.ingredients[i].staple and pantry.get(i, 0) < q * body.servings]
    needs = [n for n in needs if n.qty > 0]
    if not needs:
        return {"orders": [], "note": "Everything's in the house."}
    pb = PriceBook(h, dt.date.today(), catalog=c)
    sp = split(h, c, pb, needs, Settings.load(), max_stores=1)
    out = []
    for o in sp.orders:
        d = o.to_dict() if hasattr(o, "to_dict") else o.__dict__
        lines = [ln if isinstance(ln, dict) else ln.__dict__ for ln in d["lines"]]
        item = {"store": d["store_name"], "mode": d["mode"], "total": d["total"],
                "lines": [{"name": ln["name"], "packs": ln["packs"], "brand": ln["brand"]} for ln in lines],
                "share_text": "\n".join(f"{ln['packs']} × {ln['name']}" for ln in lines), "url": None}
        if d.get("handoff") == "instacart" and d.get("payload"):
            item["url"], item["note"] = instacart_link(d["payload"])
        out.append(item)
    return {"orders": out}


class OccasionIdeasIn(BaseModel):
    people: list[str] = []
    tags: list[str] = []
    guests: int = Field(default=0, ge=0, le=60)
    meal: str = "dinner"


@app.post("/api/occasions/ideas")
def occasion_ideas(body: OccasionIdeasIn, ctx: Ctx = Depends(member)) -> dict:
    from . import workflows
    h = _hh()
    c = catalog.for_household(h)
    return workflows.occasion_ideas(h, c, PriceBook(h, dt.date.today(), catalog=c), people=body.people, tags=body.tags,
                                    guests=body.guests, meal=body.meal)


class OccasionIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    date: str
    kind: str = "custom"
    people: list[str] = []
    recipe: str | None = None
    guests: int = Field(default=0, ge=0, le=60)
    tags: list[str] = []
    yearly: bool = False
    meal: str = "dinner"


@app.post("/api/occasions")
def add_occasion(body: OccasionIn, ctx: Ctx = Depends(member)) -> dict:
    """Plan a special meal: it's added to the household's occasions and the plan for that week follows it."""
    need(ctx, "adult")
    h = _hh()
    occ = list(h.raw.get("occasions") or [])
    d = {k: v for k, v in body.model_dump().items() if v not in (None, [], "", 0) or k == "yearly"}
    d["id"] = "o_" + secrets.token_hex(4)
    occ.append(d)
    h.raw["occasions"] = occ
    h.raw["require_admin"] = True
    try:
        save_household(h.raw)
    except HouseholdError as e:
        raise HTTPException(422, str(e))
    if len(body.date) == 10:                          # re-plan that week if it's still a draft
        wk = week_start(dt.date.fromisoformat(body.date))
        rec = store.get_week(store.connect(), wk.isoformat())
        if rec and rec.get("status") != "approved":
            week.draft(wk, ideas=False, actor=actor(ctx))
        elif rec and body.recipe:
            day = DAYS[dt.date.fromisoformat(body.date).weekday()]
            try:
                week.change(wk, day, body.meal, body.recipe, actor(ctx))
            except ValueError:
                pass
    return {"added": d["id"]}


@app.delete("/api/occasions/{oid}")
def remove_occasion(oid: str, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    h = _hh()
    h.raw["occasions"] = [o for o in (h.raw.get("occasions") or []) if o.get("id") != oid]
    h.raw["require_admin"] = True
    save_household(h.raw)
    return {"removed": oid}


@app.get("/api/surprise")
def surprise_me(meal: str = "dinner", day: str | None = None, minutes: int | None = None, seed: int | None = None,
                ctx: Ctx = Depends(member)) -> dict:
    """Anything from the recipe book that's safe for the people eating."""
    from . import workflows
    h = _hh()
    r = workflows.surprise(h, catalog.for_household(h), meal=meal, day=day, minutes=minutes,
                           seed=seed if seed is not None else secrets.randbelow(10 ** 6))
    if not r:
        raise HTTPException(404, "nothing in the book fits")
    return r


@app.get("/api/buffet")
def get_buffet(ctx: Ctx = Depends(member)) -> dict:
    from . import workflows
    h = _hh()
    con = store.connect()
    out = workflows.buffet_restock(h, catalog.for_household(h), con)
    con.close()
    return {"config": h.raw.get("buffet") or {}, "items": out}


class BuffetCountIn(BaseModel):
    meal: str
    recipe: str
    on_hand: float = Field(ge=0, le=200)


@app.post("/api/buffet/count")
def buffet_count(body: BuffetCountIn, ctx: Ctx = Depends(member)) -> dict:
    """How many portions of a buffet item are left (anyone can update it)."""
    from . import workflows
    con = store.connect()
    workflows.set_buffet_stock(con, body.meal, body.recipe, body.on_hand, actor(ctx))
    con.close()
    return get_buffet(ctx)


class BuffetIn(BaseModel):
    meal: str
    on: bool = True
    items: list[dict] = []


@app.put("/api/buffet")
def set_buffet(body: BuffetIn, ctx: Ctx = Depends(member)) -> dict:
    """Keep a meal as a buffet: which recipes, and how many portions of each to have on hand each week."""
    need(ctx, "adult")
    if body.meal not in MEALS:
        raise HTTPException(422, "meal: breakfast, lunch or dinner")
    h = _hh()
    c = catalog.for_household(h)
    items = []
    for it in body.items[:12]:
        if it.get("recipe") not in c.recipes or not 0 < float(it.get("target") or 0) <= 100:
            raise HTTPException(422, "each item needs a recipe and a target of 1–100 portions")
        items.append({"recipe": it["recipe"], "target": float(it["target"])})
    buf = dict(h.raw.get("buffet") or {})
    buf[body.meal] = {"on": body.on, "items": items}
    h.raw["buffet"] = buf
    h.raw["require_admin"] = True
    try:
        save_household(h.raw)
    except HouseholdError as e:
        raise HTTPException(422, str(e))
    return get_buffet(ctx)


class AheadPlanIn(BaseModel):
    weeks: int = Field(default=4, ge=1, le=12)
    start: str | None = None


@app.post("/api/plan/ahead")
def plan_ahead(body: AheadPlanIn, ctx: Ctx = Depends(member)) -> dict:
    """Make a plan for the coming weeks (or months) and stick with it: drafts each week that has no plan yet."""
    need(ctx, "adult")
    weeks = [_week(body.start) + dt.timedelta(weeks=n) for n in range(body.weeks)]
    out = []
    con = store.connect()
    for wk in weeks:
        rec = store.get_week(con, wk.isoformat())
        if not rec:
            week.draft(wk, ideas=False, actor=actor(ctx))
            rec = store.get_week(con, wk.isoformat())
        dinners = [e["name"] for e in rec["plan"]["entries"] if e["meal"] == "dinner"]
        choice = rec.get("shopping_choice") or "balanced"
        out.append({"week_of": wk.isoformat(), "status": rec.get("status"), "dinners": dinners,
                    "total": rec["split"][choice]["total"] if rec.get("split") else None})
    con.close()
    return {"weeks": out}


# ---------------------------------------------------------------- the week
class WeekIn(BaseModel):
    week: str | None = None
    choice: str = "balanced"


class SwapIn(BaseModel):
    week: str | None = None
    day: str
    meal: str
    to: str | None = None


class ApproveIn(BaseModel):
    week: str | None = None
    choice: str = "balanced"
    seconds: float = Field(ge=0, le=36000)       # time the person spent in the app on this week (NFR-3)


class NightIn(BaseModel):
    week: str | None = None
    day: str
    kind: str


class AwayIn(BaseModel):
    week: str | None = None
    day: str
    person: str
    away: bool


class AheadIn(BaseModel):
    week: str | None = None
    ingredients: list[str]


def _view(rec: dict) -> dict:
    h = _hh()
    choice = rec.get("shopping_choice") or "balanced"
    con = store.connect()
    away, _ = store.overrides(con, rec["week_of"])
    _, original = store.picks(con, rec["week_of"])
    st = week.states(h, con, rec)
    con.close()
    h.week_of = dt.date.fromisoformat(rec["week_of"])
    occ = {d: [{"name": o["name"], "kind": o["kind"], "people": o["people"]} for o in h.occasions(d)] for d in DAYS}
    c = catalog.for_household(h)
    for e in rec["plan"]["entries"]:
        e.update(st.get((e["day"], e["meal"]), {}))
        o = original.get((e["day"], e["meal"]))
        e["original"] = {"recipe": o, "name": c.recipes[o].name if o in c.recipes else o} \
            if o and o != e["recipe"] else None
    return {"week_of": rec["week_of"], "status": rec.get("status"), "approved_by": rec.get("approved_by"),
            "plan": rec["plan"], "choice": choice, "today": week.today_in(h).isoformat(),
            "occasions": {d: v for d, v in occ.items() if v},
            "options": {k: {"total": v["total"], "minutes": v["minutes"], "flags": v.get("flags", []),
                            "storage_used": v.get("storage_used", {}),
                            "stores": [{"store": o["store_name"], "mode": o["mode"], "total": o["total"],
                                        "day": o.get("day"), "time": o.get("time"), "card": o.get("card_name")}
                                       for o in v["orders"]]} for k, v in rec["split"].items()},
            "chores": rec.get("chores", []), "pets": rec.get("pets", []), "savings": rec.get("savings"),
            "eating_out": rec.get("eating_out") or [], "extras": rec.get("extras") or {},
            "people": {p.id: p.name for p in h.people.values()},
            "dinner_times": {d: h.dinner_time(d) for d in DAYS},
            "away": {d: sorted(v) for d, v in away.items()},
            "home": {p.id: p.home for p in h.people.values()}}


@app.get("/api/week")
def get_week(week: str | None = None, ctx: Ctx = Depends(member)) -> dict:
    return _view(_stored(_week(week)))


@app.post("/api/week/draft")
def draft_week(body: WeekIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    week.draft(_week(body.week), choice=body.choice, actor=actor(ctx))
    return _view(_stored(_week(body.week)))


@app.post("/api/week/swap")
def swap_meal(body: SwapIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    if body.day not in DAYS:
        raise HTTPException(422, "day must be mon..sun")
    rec = _stored(_week(body.week))
    if rec.get("status") == "approved":
        raise HTTPException(409, "this week is approved; change it from next week, or use Cook from what I've got")
    try:
        week.swap(_week(body.week), body.day, body.meal, to=body.to, actor=actor(ctx))
    except ValueError as e:
        raise HTTPException(409, str(e))
    _notify_others(ctx, "The plan changed", f"{body.day.title()} {body.meal} was swapped.", f"lilhelper://week?day={body.day}")
    return _view(_stored(_week(body.week)))


@app.post("/api/week/night")
def set_night(body: NightIn, ctx: Ctx = Depends(member)) -> dict:
    """Make a night takeout, eating out, leftovers, a freezer meal, or cooked again — then the week re-plans."""
    need(ctx, "adult")
    rec = store.get_week(store.connect(), _week(body.week).isoformat())
    if rec and rec.get("status") == "approved" and body.kind == "cook" and not any(
            e["day"] == body.day and e["meal"] == "dinner" for e in rec["plan"]["entries"]):
        raise HTTPException(409, "this week's shopping is done, so there's nothing bought for that night; "
                                 "use Cook from what I've got to fill it")
    try:
        week.set_night(_week(body.week), body.day, body.kind, actor(ctx))
    except ValueError as e:
        raise HTTPException(422, str(e))
    _apply(body.week, ctx)
    _notify_others(ctx, "Dinner plans changed", f"{body.day.title()} is now {body.kind.replace('_', ' ')}.",
                   f"lilhelper://week?day={body.day}")
    return _view(_stored(_week(body.week)))


@app.post("/api/week/away")
def set_away(body: AwayIn, ctx: Ctx = Depends(member)) -> dict:
    """Someone's out for dinner on a day this week (anyone may mark themselves; adults may mark anyone)."""
    if body.person != ctx.person:
        need(ctx, "adult")
    h = _hh()
    if body.person not in h.people:
        raise HTTPException(404, "no such person")
    try:
        week.set_away(_week(body.week), body.day, body.person, body.away, actor(ctx))
    except ValueError as e:
        raise HTTPException(422, str(e))
    _apply(body.week, ctx)
    return _view(_stored(_week(body.week)))


def _apply(wk: str | None, ctx: Ctx) -> None:
    """After a night or who's-away change: re-plan a draft; change an approved week in place."""
    rec = store.get_week(store.connect(), _week(wk).isoformat())
    if rec and rec.get("status") == "approved":
        try:
            week.apply_to_approved(_week(wk), actor(ctx))
        except ValueError as e:
            raise HTTPException(409, str(e))
    else:
        week.draft(_week(wk), actor=actor(ctx), ideas=False)


@app.post("/api/week/ahead")
def buy_ahead(body: AheadIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    try:
        added = week.add_ahead(_week(body.week), body.ingredients, actor(ctx))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"added": added}


@app.post("/api/week/approve")
def approve_week(body: ApproveIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    try:
        week.approve(_week(body.week), ctx.person, body.seconds, body.choice)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(409, str(e))
    _notify_others(ctx, "This week's plan is set", f"Approved by {ctx.name}. Shopping lists are ready.",
                   "lilhelper://shopping")
    return _view(_stored(_week(body.week)))


class ChangeIn(BaseModel):
    week: str | None = None
    day: str
    meal: str = "dinner"
    recipe: str


class SlotIn(BaseModel):
    week: str | None = None
    day: str
    meal: str = "dinner"


class OutcomeIn(BaseModel):
    week: str | None = None
    day: str
    meal: str = "dinner"
    outcome: str
    frozen: float = Field(default=0, ge=0, le=40)


@app.post("/api/week/change")
def change_meal(body: ChangeIn, ctx: Ctx = Depends(member)) -> dict:
    """Put a chosen recipe (existing or just saved) on a planned meal. Undo with /api/week/revert."""
    need(ctx, "adult")
    try:
        out = week.change(_week(body.week), body.day, body.meal, body.recipe, actor(ctx))
    except ValueError as e:
        raise HTTPException(409, str(e))
    _notify_others(ctx, "The plan changed", f"{body.day.title()} {body.meal} changed.", f"lilhelper://week?day={body.day}")
    return {**_view(_stored(_week(body.week))), "missing": out["missing"]}


class PartsIn(BaseModel):
    week: str | None = None
    day: str
    meal: str = "dinner"
    parts: list[dict] = []


@app.post("/api/week/parts")
def meal_parts(body: PartsIn, ctx: Ctx = Depends(member)) -> dict:
    """More than one thing for a meal: e.g. cook the curry for three, and two heat up Monday's leftovers."""
    need(ctx, "adult")
    try:
        week.set_parts(_week(body.week), body.day, body.meal, body.parts, actor(ctx))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _view(_stored(_week(body.week)))


@app.post("/api/week/revert")
def revert_meal(body: SlotIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    try:
        week.revert(_week(body.week), body.day, body.meal, actor(ctx))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _view(_stored(_week(body.week)))


@app.post("/api/week/outcome")
def meal_outcome(body: OutcomeIn, ctx: Ctx = Depends(member)) -> dict:
    """What happened to a meal: finished, leftovers, some went in the freezer (how many portions), or skipped."""
    try:
        week.record_outcome(_week(body.week), body.day, body.meal, body.outcome, body.frozen, actor(ctx))
    except ValueError as e:
        raise HTTPException(422, str(e))
    if body.outcome in ("finished", "leftovers"):
        try:
            _record_feedback(_week(body.week).isoformat(), body.day, body.meal,
                             "all" if body.outcome == "finished" else "some_left", None, actor(ctx))
        except HTTPException:
            pass
    return _view(_stored(_week(body.week)))


def _notify_others(ctx: Ctx, title: str, body: str, link: str) -> None:
    con = accounts.connect()
    others = [m["user_id"] for m in accounts.members(con, ctx.hid) if m["user_id"] != ctx.uid]
    con.close()
    if others:
        notify.send(ctx.hid, title, body, to_users=others, link=link, kind="change")


# ---------------------------------------------------------------- shopping hand-offs
def _orders(rec: dict, choice: str) -> list[dict]:
    return week.orders(rec, choice)


@app.get("/api/week/shopping")
def shopping(week: str | None = None, choice: str | None = None, ctx: Ctx = Depends(member)) -> dict:
    rec = _stored(_week(week))
    if rec.get("status") != "approved":
        raise HTTPException(409, "approve the week first; nothing is handed to a store before that")
    choice = choice or rec.get("shopping_choice") or "balanced"
    h = _hh()
    out = []
    for o in _orders(rec, choice):
        item = {"store": o["store_name"], "mode": o["mode"], "handoff": o["handoff"], "total": o["total"],
                "day": o.get("day"), "time": o.get("time"),
                "who": h.people[o["who"]].name if o.get("who") in h.people else None,
                "card": o.get("card_name"), "card_note": o.get("card_note"), "rewards": o.get("rewards", 0),
                "lines": [{"name": ln["name"], "packs": ln["packs"], "brand": ln["brand"], "special": ln["special"],
                           "price": ln["price_each"]} for ln in o["lines"]],
                "credits": o.get("credits", 0), "url": None, "note": None}
        if o["handoff"] == "instacart":
            item["url"], item["note"] = instacart_link(o["payload"])
        lines = "\n".join(f"{ln['packs']} × {ln['name']}" + (f" ({ln['brand']})" if ln.get("brand") else "")
                          for ln in o["lines"])
        item["share_text"] = lines
        if o["handoff"] == "amazon":
            item["note"] = "Share to the Amazon or Whole Foods app, or to Reminders"
        elif o["handoff"] != "instacart":
            item["note"] = ("In-store list in aisle order; share it to Reminders or print it" if o["mode"] == "in_store"
                            else f"Order {o['mode']} in {o['store_name']}'s own app with this list")
        out.append(item)
    store.audit(store.connect(), actor(ctx), "handoff_view", {"week_of": rec["week_of"], "choice": choice})
    return {"week_of": rec["week_of"], "choice": choice, "orders": out}


def instacart_link(payload: dict) -> tuple[str | None, str]:
    """POST the shopping list to the Instacart Developer Platform; the person opens the link to pick a store and
    check out. Without a key (offline, CI, the public demo) nothing is sent."""
    key = os.getenv("INSTACART_API_KEY")
    if not key:
        return None, "Set INSTACART_API_KEY on the server to create an Instacart link"
    base = INSTACART[os.getenv("INSTACART_ENV", "development")]
    try:
        r = httpx.post(f"{base}/idp/v1/products/products_link", json=payload, timeout=20,
                       headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
        r.raise_for_status()
        return r.json().get("products_link_url"), "Opens Instacart; choose the store shown and check out there"
    except httpx.HTTPError as e:
        return None, f"Instacart didn't answer ({type(e).__name__}); the list below still works"


# ---------------------------------------------------------------- jobs and feedback
class JobSwapIn(BaseModel):
    week: str | None = None
    day: str
    job: str
    person: str


@app.post("/api/jobs/swap")
def swap_job(body: JobSwapIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    h = _hh()
    spec = ((h.raw.get("chores") or {}).get("jobs") or {}).get(body.job)
    p = h.people.get(body.person)
    if not spec or not p or not chores.eligible(p, body.job, spec, body.day):
        raise HTTPException(422, f"{body.person} can't do {body.job} on {body.day}")
    con = store.connect()
    wk = _week(body.week).isoformat()
    rec = store.get_week(con, wk)
    if not rec:
        raise HTTPException(404, "no plan for that week yet")
    jobs = rec.get("chores") or []
    for a in jobs:
        if a["day"] == body.day and a["job"] == body.job:
            a["person"], a["name"] = p.id, p.name
    store.save_week(con, wk, chores=jobs)
    store.audit(con, actor(ctx), "job_swap", body.model_dump())
    con.close()
    return {"chores": jobs}


class FeedbackIn(BaseModel):
    week: str | None = None
    day: str
    meal: str
    eaten: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)


def _record_feedback(wk: str, day: str, meal: str, eaten: str | None, rating: int | None, by: str) -> dict:
    con = store.connect()
    rec = store.get_week(con, wk)
    e = next((e for e in (rec or {}).get("plan", {}).get("entries", []) if e["day"] == day and e["meal"] == meal), None)
    if not e:
        con.close()
        raise HTTPException(404, "no such meal that week")
    prev = con.execute("SELECT eaten, rating FROM feedback WHERE week_of=? AND day=? AND meal=?", (wk, day, meal)).fetchone()
    eaten = eaten or (prev["eaten"] if prev else "all")
    rating = rating if rating is not None else (prev["rating"] if prev else None)
    try:
        feedback.record(con, wk, day, meal, e["recipe"], eaten, rating, by)
    except ValueError as ex:
        con.close()
        raise HTTPException(422, str(ex))
    changed = feedback.learn(con, Settings.load(), wk)
    con.close()
    return {"recorded": True, "meal": e["name"], "eaten": eaten, "rating": rating, "portions_changed": changed}


@app.post("/api/feedback")
def give_feedback(body: FeedbackIn, ctx: Ctx = Depends(member)) -> dict:
    return _record_feedback(_week(body.week).isoformat(), body.day, body.meal, body.eaten, body.rating, actor(ctx))


# ---------------------------------------------------------------- recipes and ingredients (the household's own)
class LineIn(BaseModel):
    text: str | None = Field(default=None, max_length=80)
    ingredient: str | None = None
    qty: float = Field(gt=0, le=1000)
    unit: str | None = None


class RecipeIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    meal: str = "dinner"
    meals: list[str] = []                                 # every meal it suits; blank → just `meal`
    kcal: int = Field(default=0, ge=0, le=5000)           # calories per serving, if you know them
    serves: float = Field(default=4, gt=0, le=40)        # the amounts below make this many servings
    active: int = Field(default=20, ge=1, le=300)
    total: int = Field(default=30, ge=1, le=1440)
    ingredients: list[LineIn]
    instructions: list[str] = []
    tags: list[str] = []
    season_months: list[int] = []
    want: dict = {}                                       # {times: 2, per_weeks: 4}
    kid_min_age: int = Field(default=0, ge=0, le=18)
    veg: float = Field(default=1, ge=0, le=6)
    protein: float = Field(default=20, ge=0, le=150)
    notes: str = Field(default="", max_length=500)
    credit: str = Field(default="", max_length=80)       # where it's from; blank → the person saving it
    url: str = Field(default="", max_length=500)


UNIT_TO = {("tbsp", "cup"): 1 / 16, ("cup", "tbsp"): 16, ("tsp", "tbsp"): 1 / 3, ("tsp", "cup"): 1 / 48,
           ("oz", "lb"): 1 / 16, ("lb", "oz"): 16, ("g", "lb"): 1 / 453.6, ("g", "oz"): 1 / 28.35, ("kg", "lb"): 2.2046,
           ("ml", "cup"): 1 / 236.6, ("l", "cup"): 4.227}


def _convert(qty: float, frm: str | None, to: str) -> float:
    if not frm or frm == to:
        return qty
    f = UNIT_TO.get((frm.lower().rstrip("s"), to))
    if f is None:
        raise HTTPException(422, f"can't convert {frm} to {to}; use {to}")
    return qty * f


@app.get("/api/recipes")
def list_recipes(q: str = "", meal: str | None = None, mine: bool = False, ctx: Ctx = Depends(member)) -> dict:
    c = catalog.for_household(_hh())
    out = []
    for r in c.recipes.values():
        if (meal and not r.suits(meal)) or (mine and r.source != "household") or (q and q.lower() not in r.name.lower()):
            continue
        out.append({"id": r.id, "name": r.name, "meal": r.meal, "meals": r.meals, "kcal": r.kcal,
                    "active": r.active, "total": r.total, "tags": r.tags,
                    "source": r.source, "season_months": r.season_months, "want": r.want,
                    "kid_min_age": r.kid_min_age, "credit": r.credit or ("DinnerPeace" if r.source == "book" else ""),
                    "url": r.url})
    out.sort(key=lambda r: (r["source"] != "household", r["meal"], r["name"]))
    return {"recipes": out}


@app.post("/api/recipes")
def save_recipe(body: RecipeIn, rid: str | None = None, ctx: Ctx = Depends(member)) -> dict:
    """Add (or, with ?rid=, replace) one of the household's own recipes. Amounts are for `serves` servings."""
    need(ctx, "adult")
    h = _hh()
    data = body.model_dump()
    data["ingredients"] = [ln.model_dump() for ln in body.ingredients]
    data["credit"] = body.credit.strip() or (h.people[ctx.person].name if ctx.person in h.people else ctx.name)
    con = store.connect()
    try:
        return recipebook.save(con, h, catalog.for_household(h), data, actor(ctx), rid)
    except recipebook.RecipeError as e:
        raise HTTPException(422, {"message": str(e), "unknown": e.unknown} if e.unknown else str(e))
    finally:
        con.close()


@app.get("/api/recipes/export")
def export_recipes(ctx: Ctx = Depends(member)) -> dict:
    h = _hh()
    con = store.connect()
    out = recipebook.export(con, catalog.for_household(h), h.info.get("name", ""))
    con.close()
    return out


class BookIn(BaseModel):
    book: dict


@app.post("/api/recipes/import")
def import_recipes(body: BookIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    h = _hh()
    con = store.connect()
    try:
        return recipebook.import_book(con, h, catalog.for_household(h), body.book, actor(ctx))
    except recipebook.RecipeError as e:
        raise HTTPException(422, str(e))
    finally:
        con.close()


@app.post("/api/recipes/share")
def share_recipes(ctx: Ctx = Depends(member)) -> dict:
    """A code (and link) another household can use to copy this household's recipes. Stop sharing any time."""
    need(ctx, "adult")
    nonce = secrets.token_urlsafe(8)
    con = store.connect()
    con.execute("INSERT INTO book_shares (code, created, by) VALUES (?,?,?)", (nonce, store.now(), actor(ctx)))
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM custom_recipes WHERE active = 1").fetchone()[0]
    con.close()
    code = sign("book", f"{ctx.hid}|{nonce}", 30 * 24 * 3600)
    return {"code": code, "link": f"{public_url()}/open/book?code={code}", "recipes": n,
            "note": "Anyone with this code can copy your recipes (not your plans or anything else) for 30 days."}


@app.delete("/api/recipes/share")
def stop_sharing(ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    con = store.connect()
    n = con.execute("UPDATE book_shares SET revoked = 1 WHERE revoked = 0").rowcount
    con.commit()
    con.close()
    return {"stopped": n}


def _shared_book(code: str) -> tuple[str, dict]:
    try:
        hid, nonce = verify("book", code.strip()).split("|", 1)
    except HTTPException:
        raise HTTPException(404, "that sharing code isn't valid (or has expired)")
    tok = set_tenant(hid)
    try:
        con = store.connect()
        ok = con.execute("SELECT 1 FROM book_shares WHERE code = ? AND revoked = 0", (nonce,)).fetchone()
        if not ok:
            con.close()
            raise HTTPException(404, "that household has stopped sharing its recipes")
        h = load_household()
        book = recipebook.export(con, catalog.for_household(h), h.info.get("name", ""))
        con.close()
    finally:
        reset_tenant(tok)
    return hid, book


class CodeIn(BaseModel):
    code: str = Field(max_length=500)


@app.post("/api/recipes/shared")
def preview_shared(body: CodeIn, ctx: Ctx = Depends(member)) -> dict:
    hid, book = _shared_book(body.code)
    return {"household": book["household"], "recipes": [r["name"] for r in book["recipes"]], "same": hid == ctx.hid}


@app.post("/api/recipes/import-shared")
def import_shared(body: CodeIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    hid, book = _shared_book(body.code)
    if hid == ctx.hid:
        raise HTTPException(409, "that's your own recipe book")
    h = _hh()
    con = store.connect()
    try:
        return recipebook.import_book(con, h, catalog.for_household(h), book, actor(ctx),
                                      credit=f"Shared by {book['household']}")
    finally:
        con.close()


class UrlIn(BaseModel):
    url: str = Field(max_length=1000)


@app.post("/api/recipes/from-url")
def recipe_from_url(body: UrlIn, ctx: Ctx = Depends(member)) -> dict:
    """A draft recipe from a web page (name, ingredients, times, servings, source and link); nothing is saved."""
    need(ctx, "adult")
    rate_limit(f"fetch:{ctx.hid}", 60)
    try:
        url, page = recipebook.fetch(body.url.strip())
        return recipebook.draft_from_page(catalog.for_household(_hh()), page, url)
    except recipebook.FetchError as e:
        raise HTTPException(422, str(e))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"couldn't load that page ({type(e).__name__})")


@app.get("/api/recipes/search")
def search_recipes(q: str, site: str | None = None, ctx: Ctx = Depends(member)) -> dict:
    """Recipes on the web from the household's favourite sites (Settings → recipe sources), or one site, or anywhere."""
    rate_limit(f"search:{ctx.hid}", 60)
    h = _hh()
    sites = [site] if site else ([] if site == "" else list(h.raw.get("recipe_sources") or []))
    return {**recipebook.search(q, [x for x in sites if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", x or "")]),
            "sites": sites}


@app.get("/api/recipes/{rid}")
def get_recipe(rid: str, ctx: Ctx = Depends(member)) -> dict:
    c = catalog.for_household(_hh())
    r = c.recipes.get(rid)
    if not r:
        raise HTTPException(404, "no such recipe")
    return {**r.__dict__, "ingredients": [{"ingredient": i, "name": c.ingredients[i].name, "per_serving": q,
                                           "unit": c.ingredients[i].unit} for i, q in r.ing.items()],
            "allergens": c.allergens_of(r), "credit": r.credit or ("DinnerPeace" if r.source == "book" else "")}


@app.delete("/api/recipes/{rid}")
def delete_recipe(rid: str, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    con = store.connect()
    con.execute("UPDATE custom_recipes SET active = 0, updated = ? WHERE id = ?", (store.now(), rid))
    con.commit()
    con.close()
    return {"removed": rid}


class IngredientIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    unit: str = "each"
    cat: str = "pantry"
    allergens: list[str] = []
    storage: str = ""
    freezable: bool | None = None
    shelf: int = Field(default=7, ge=1, le=1000)
    prices: dict = {}                                   # {store: {pack, price, brand?}}


class PrefIn(BaseModel):
    brand: str | None = Field(default=None, max_length=60)
    store: str | None = None
    price: float | None = Field(default=None, gt=0, le=1000)
    pack: float | None = Field(default=None, gt=0, le=1000)
    only_store: bool = True
    organic: bool = False


@app.get("/api/ingredients/{iid}")
def ingredient_detail(iid: str, ctx: Ctx = Depends(member)) -> dict:
    """One ingredient: what DinnerPeace's price list says at each of your stores, and your own choice for it."""
    h = _hh()
    c = catalog.for_household(h)
    ing = c.ingredients.get(iid)
    if not ing:
        raise HTTPException(404, "no such ingredient")
    shelf = yaml.safe_load((ROOT / "data" / "prices.yaml").read_text())["stores"]
    st = load_stores()["stores"]
    book = [{"store": sid, "store_name": st[sid]["name"], **o} for sid in (h.raw.get("stores") or [])
            for o in (shelf.get(sid, {}).get(iid, []) + [dict(p, brand=p.get("brand", "any"))
                                                          for s2, p in (ing.prices or {}).items() if s2 == sid])]
    used = sorted({r.name for r in c.recipes.values() if iid in r.ing})[:20]
    return {"id": iid, "name": ing.name, "unit": ing.unit, "cat": ing.cat, "allergens": ing.allergens,
            "source": ing.source, "storage": ing.storage, "book_prices": book,
            "mine": (h.raw.get("ingredient_prefs") or {}).get(iid), "used_in": used,
            "stores": [{"id": sid, "name": st[sid]["name"]} for sid in (h.raw.get("stores") or []) if sid in st]}


@app.put("/api/ingredients/{iid}/pref")
def set_ingredient_pref(iid: str, body: PrefIn, ctx: Ctx = Depends(member)) -> dict:
    """Your brand, store and price for an item — used in every plan and shopping list from now on."""
    need(ctx, "adult")
    h = _hh()
    if iid not in catalog.for_household(h).ingredients:
        raise HTTPException(404, "no such ingredient")
    if body.store and body.store not in (h.raw.get("stores") or []):
        raise HTTPException(422, "choose one of your stores")
    if body.price and not body.store:
        raise HTTPException(422, "say which store that price is at")
    prefs = dict(h.raw.get("ingredient_prefs") or {})
    prefs[iid] = {k: v for k, v in body.model_dump().items() if v not in (None, "", False) or k == "only_store"}
    h.raw["ingredient_prefs"] = prefs
    h.raw["require_admin"] = True
    try:
        save_household(h.raw)
    except HouseholdError as e:
        raise HTTPException(422, str(e))
    store.audit(store.connect(), actor(ctx), "ingredient_pref", {"ingredient": iid})
    return {"saved": iid, "mine": prefs[iid]}


@app.delete("/api/ingredients/{iid}/pref")
def clear_ingredient_pref(iid: str, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    h = _hh()
    prefs = dict(h.raw.get("ingredient_prefs") or {})
    prefs.pop(iid, None)
    h.raw["ingredient_prefs"] = prefs
    h.raw["require_admin"] = True
    save_household(h.raw)
    return {"cleared": iid}


@app.get("/api/ingredients")
def list_ingredients(q: str = "", ctx: Ctx = Depends(member)) -> dict:
    c = catalog.for_household(_hh())
    out = [{"id": i.id, "name": i.name, "unit": i.unit, "cat": i.cat, "source": i.source, "storage": i.storage}
           for i in c.ingredients.values() if not q or q.lower() in i.name.lower() or q.lower() in i.id]
    return {"ingredients": sorted(out, key=lambda x: x["name"])[:200]}


@app.post("/api/ingredients")
def add_ingredient(body: IngredientIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    from .catalog import LITRES_PER_UNIT, STORAGE_DEFAULTS
    if body.unit not in LITRES_PER_UNIT or body.cat not in STORAGE_DEFAULTS:
        raise HTTPException(422, f"unit one of {sorted(LITRES_PER_UNIT)}; category one of {sorted(STORAGE_DEFAULTS)}")
    if set(body.allergens) - set(ALLERGENS):
        raise HTTPException(422, f"allergens: {', '.join(ALLERGENS)}")
    for st, p in body.prices.items():
        if st not in load_stores()["stores"] or float(p.get("price", 0)) <= 0 or float(p.get("pack", 0)) <= 0:
            raise HTTPException(422, "prices: {store: {pack, price}} for stores DinnerPeace knows")
    iid = "h_" + re.sub(r"[^a-z0-9]+", "_", body.name.lower()).strip("_")[:40]
    c = catalog.for_household(_hh())
    found = c.text_allergens(body.name)
    data = {"id": iid, "name": body.name.lower(), "unit": body.unit, "cat": body.cat, "aisle": 5,
            "allergens": sorted(set(body.allergens) | set(found)), "shelf": body.shelf, "storage": body.storage,
            "freezable": body.freezable, "source": "household", "prices": body.prices}
    con = store.connect()
    con.execute("INSERT OR REPLACE INTO custom_ingredients VALUES (?,?,?,?)", (iid, json.dumps(data), actor(ctx),
                                                                              store.now()))
    con.commit()
    con.close()
    return {"saved": iid, "allergens": data["allergens"]}


# ---------------------------------------------------------------- specials
class SpecialIn(BaseModel):
    week: str | None = None
    store: str
    item: str | None = Field(default=None, max_length=80)
    ingredient: str | None = None
    price: float = Field(gt=0, le=500)
    per: str = "pack"                         # the price is for the store's usual pack, or per unit (per lb, each)
    regular: float | None = Field(default=None, gt=0, le=500)
    channel: str = "any"                      # any | in_store | online
    repeat_weekly: bool = False
    valid_to: str | None = None
    note: str = Field(default="", max_length=120)


@app.get("/api/specials")
def list_specials(week: str | None = None, ctx: Ctx = Depends(member)) -> dict:
    con = store.connect()
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM specials WHERE week_of = ? OR repeat_weekly = 1 ORDER BY store", (_week(week).isoformat(),))]
    con.close()
    c = catalog.for_household(_hh())
    for r in rows:
        r["name"] = c.ingredients[r["ingredient"]].name if r["ingredient"] in c.ingredients else r["ingredient"]
    return {"specials": rows}


@app.post("/api/specials")
def add_special(body: SpecialIn, ctx: Ctx = Depends(member)) -> dict:
    """A special the household knows about: this week only or every week, in store, online (pickup/delivery) or both."""
    need(ctx, "adult")
    h = _hh()
    c = catalog.for_household(h)
    if body.store not in load_stores()["stores"]:
        raise HTTPException(422, "unknown store")
    if body.channel not in ("any", "in_store", "online"):
        raise HTTPException(422, "channel: any, in_store or online")
    iid = body.ingredient if body.ingredient in c.ingredients else (c.match(body.item or "") if body.item else None)
    if not iid:
        raise HTTPException(422, "couldn't match that to an ingredient; add it as your own ingredient first")
    pb = PriceBook(h, _week(body.week), catalog=c, enabled=[body.store])
    shelf = pb.shelf.get(body.store, {}).get(iid, [])
    pack = float(shelf[0]["pack"]) if shelf else 1.0
    price = round(body.price * pack, 2) if body.per == "unit" else body.price
    regular = body.regular * (pack if body.per == "unit" else 1) if body.regular else (
        float(shelf[0]["price"]) if shelf else None)
    if regular and price < float(Settings.load()["shopping"]["typo_special_ratio"]) * regular:
        raise HTTPException(422, f"${price / pack:.2f} a {c.ingredients[iid].unit} is far below the usual "
                                 f"${regular / pack:.2f} — check the price (and whether it's per pack or per unit)")
    con = store.connect()
    con.execute("INSERT INTO specials (week_of, store, ingredient, price, regular, source, confirmed_by, ts, channel, "
                "repeat_weekly, valid_to, note, pack) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (_week(body.week).isoformat(), body.store, iid, price, regular, "entered", actor(ctx), store.now(),
                 body.channel, int(body.repeat_weekly), body.valid_to, body.note, pack if shelf else None))
    con.commit()
    con.close()
    return {"saved": iid, "pack": pack, "unit": c.ingredients[iid].unit, "price": price, "regular": regular,
            "note": None if shelf else
            "This store isn't on file as selling it; the special is kept but only counts once a price exists."}


@app.delete("/api/specials/{sid}")
def delete_special(sid: int, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    con = store.connect()
    con.execute("DELETE FROM specials WHERE id = ?", (sid,))
    con.commit()
    con.close()
    return {"removed": sid}


@app.post("/api/flyer")
async def flyer(store_id: str = Form(...), week: str | None = Form(None), image: UploadFile = File(...),
                ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    data = await image.read()
    if len(data) > 8_000_000:
        raise HTTPException(413, "photo too large (8 MB max)")
    h = _hh()
    s = Settings.load()
    c = catalog.for_household(h)
    pb = PriceBook(h, _week(week), catalog=c)
    res = ai.read_flyer(ai.AIContext.make(s), h, c, pb, store_id, image=data)
    return {"store": store_id, "flags": res.flags, "items": res.items, "note": "Nothing counts until you confirm it"}


class ConfirmIn(BaseModel):
    week: str | None = None
    store_id: str
    items: list[dict]
    channel: str = "any"


@app.post("/api/specials/confirm")
def confirm_specials(body: ConfirmIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    con = store.connect()
    wk = _week(body.week).isoformat()
    n = 0
    for it in body.items:
        if not it.get("ingredient") or it.get("price") is None:
            continue
        con.execute("INSERT INTO specials (week_of, store, ingredient, price, regular, source, confirmed_by, ts, "
                    "channel) VALUES (?,?,?,?,?,?,?,?,?)",
                    (wk, body.store_id, it["ingredient"], float(it["price"]), it.get("regular"), "flyer", actor(ctx),
                     store.now(), body.channel))
        n += 1
    con.commit()
    store.audit(con, actor(ctx), "specials_confirm", {"week_of": wk, "store": body.store_id, "count": n})
    con.close()
    return {"confirmed": n}


# ---------------------------------------------------------------- money: budget, spending, cards
class SpendIn(BaseModel):
    date: str | None = None
    amount: float = Field(gt=0, le=5000)
    store: str | None = None
    merchant: str = Field(default="", max_length=60)
    category: str = "groceries"
    card: str | None = None
    note: str = Field(default="", max_length=120)


@app.get("/api/money/summary")
def money_summary(week: str | None = None, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    con = store.connect()
    out = spend.summary(con, _hh(), _week(week))
    con.close()
    return out


@app.post("/api/money/spend")
def add_spend(body: SpendIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    con = store.connect()
    try:
        ok = spend.add(con, _hh(), date=dt.date.fromisoformat(body.date) if body.date else dt.date.today(),
                       amount=body.amount, store_id=body.store, merchant=body.merchant or body.store or "Purchase",
                       category=body.category, card=body.card, source="manual", by=actor(ctx), note=body.note)
    except ValueError as e:
        con.close()
        raise HTTPException(422, str(e))
    con.close()
    return {"recorded": ok}


@app.delete("/api/money/spend/{sid}")
def delete_spend(sid: int, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    con = store.connect()
    con.execute("DELETE FROM spend WHERE id = ?", (sid,))
    con.commit()
    con.close()
    return {"removed": sid}


@app.post("/api/money/statement")
async def import_statement(file: UploadFile = File(...), card: str | None = Form(None), ctx: Ctx = Depends(member)) -> dict:
    """A card statement CSV: only food purchases are kept (store, date, amount)."""
    need(ctx, "adult")
    data = await file.read()
    if len(data) > 2_000_000:
        raise HTTPException(413, "file too large (2 MB max)")
    con = store.connect()
    try:
        out = spend.import_statement(con, _hh(), data.decode("utf-8", errors="replace"), card or None, actor(ctx))
    except ValueError as e:
        con.close()
        raise HTTPException(422, str(e))
    con.close()
    return out


_receipts: dict[str, object] = {}


@app.post("/api/money/receipt")
async def read_receipt(image: UploadFile | None = File(None), text: str | None = Form(None),
                       ctx: Ctx = Depends(member)) -> dict:
    """A receipt photo or pasted email: read it, show it back; nothing counts until confirmed."""
    need(ctx, "adult")
    data = await image.read() if image else None
    if data and len(data) > 8_000_000:
        raise HTTPException(413, "photo too large (8 MB max)")
    if not data and not text:
        raise HTTPException(422, "send a photo or the receipt text")
    h = _hh()
    c = catalog.for_household(h)
    res = ai.read_receipt(ai.AIContext.make(Settings.load()), h, c, PriceBook(h, dt.date.today(), catalog=c),
                          image=data, text=text[:20000] if text else None)
    rid = hashlib.sha256(f"{ctx.hid}{time.time()}".encode()).hexdigest()[:12]
    _receipts[f"{ctx.hid}:{rid}"] = res
    best = money.best_card(h, res.store or "", "in_store", res.total or 0)
    return {"receipt": rid, **res.__dict__, "suggested_card": best.card}


class ReceiptConfirmIn(BaseModel):
    receipt: str
    card: str | None = None
    use_prices: bool = True


@app.post("/api/money/receipt/confirm")
def confirm_receipt(body: ReceiptConfirmIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    res = _receipts.pop(f"{ctx.hid}:{body.receipt}", None)
    if res is None:
        raise HTTPException(404, "read the receipt again")
    con = store.connect()
    try:
        out = spend.confirm_receipt(con, _hh(), res, body.card, actor(ctx), body.use_prices)
    except ValueError as e:
        con.close()
        raise HTTPException(422, str(e))
    con.close()
    return out


@app.get("/api/money/cards")
def cards(ctx: Ctx = Depends(member)) -> dict:
    """Which card to use where, with this year's progress toward each bonus cap."""
    h = _hh()
    con = store.connect()
    used = spend.ytd_used(con, dt.date.today().year)
    con.close()
    st = load_stores()["stores"]
    picks = []
    for sid in h.raw.get("stores", []):
        for mode in st.get(sid, {}).get("modes", {}):
            p = money.best_card(h, sid, mode, 100.0, {**st[sid]["modes"][mode], "_mode": mode}, used)
            picks.append({"store": st[sid]["name"], "mode": mode, "card": p.name, "per_100": p.earned, "note": p.note})
    return {"cards": [{"id": cid, "name": c.name, "network": c.network, "earn": c.earn, "credits": c.credits,
                       "verified": str(c.verified or "")} for cid, c in money.cards(h).items()],
            "best": picks, "ytd": [{"card": k[0], "category": k[1], "spent": round(v, 2)} for k, v in used.items()]}


# ---------------------------------------------------------------- reports, forecast, cook from, storage
@app.get("/api/reports/cost")
def cost_report(weeks: int = 8, end: str | None = None, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    h = _hh()
    return reports.cost_report(h, catalog.for_household(h), end=_week(end), weeks=max(1, min(weeks, 26)))


@app.get("/api/reports/activity")
def activity_report(weeks: int = 8, end: str | None = None, ctx: Ctx = Depends(member)) -> dict:
    h = _hh()
    return reports.activity_report(h, catalog.for_household(h), end=_week(end), weeks=max(1, min(weeks, 26)))


@app.get("/api/today")
def today_view(ctx: Ctx = Depends(member)) -> dict:
    """The home screen: what's next for me and for everyone — the next meal, jobs, shopping, things to answer."""
    from . import occasions, workflows
    h = _hh()
    today = week.today_in(h)
    day = DAYS[today.weekday()]
    wk = week_start(today)
    con = store.connect()
    rec = store.get_week(con, wk.isoformat())
    nxt_rec = store.get_week(con, (wk + dt.timedelta(weeks=1)).isoformat())
    states = week.states(h, con, rec, today) if rec else {}
    stock = workflows.buffet_restock(h, catalog.for_household(h), con)
    con.close()
    me = ctx.person
    tasks, everyone = [], {p.id: [] for p in h.people.values()}
    meals_today = []
    if rec:
        for e in rec["plan"]["entries"]:
            if e["day"] == day:
                cook = e.get("cook") or next((a["person"] for a in rec.get("chores") or []
                                              if a["day"] == day and a["job"] == "cook"), None)
                meals_today.append({"meal": e["meal"], "name": e["name"], "recipe": e["recipe"], "kind": e.get("kind"),
                                    "active": e.get("active"), "cook": h.people[cook].name if cook in h.people else None,
                                    "time": h.dinner_time(day) if e["meal"] == "dinner" else
                                    {"breakfast": "08:00", "lunch": "12:00"}.get(e["meal"], ""),
                                    "parts": e.get("parts") or []})
        for a in rec.get("chores") or []:
            if a["day"] == day and a["person"] in everyone:
                everyone[a["person"]].append({"kind": "job", "job": a["job"], "text": a["job"].replace("_", " ")})
        for (d, meal), st in states.items():
            if st["state"] == "to_confirm":
                tasks.append({"kind": "confirm", "day": d, "meal": meal, "text": f"How did {d.title()}'s {meal} go?"})
        choice = rec.get("shopping_choice") or "balanced"
        for o in (rec.get("split") or {}).get(choice, {}).get("orders", []):
            if o.get("day") == day and rec.get("status") == "approved":
                who = o.get("who")
                t = {"kind": "shop", "text": f"Shopping at {o['store_name']}" + (f" at {o['time']}" if o.get("time") else ""),
                     "items": len(o["lines"])}
                (everyone[who].append(t) if who in everyone else tasks.append(t))
        if rec.get("status") != "approved":
            tasks.append({"kind": "approve", "week": wk.isoformat(), "text": "This week's plan is waiting for an adult to approve"})
    if nxt_rec and nxt_rec.get("status") != "approved" and today.weekday() >= 4:
        tasks.append({"kind": "approve", "week": (wk + dt.timedelta(weeks=1)).isoformat(),
                      "text": "Next week's plan is ready to look over"})
    if any(b["cook"] > 0 for b in stock) and today.weekday() in (4, 5):
        tasks.append({"kind": "buffet", "text": "Count what's left in the buffet before shopping"})
    up = occasions.upcoming(h.raw, h.people, today, 14)
    mine = everyone.get(me, [])
    return {"date": today.isoformat(), "day": day, "me": me, "my_name": h.people[me].name if me in h.people else ctx.name,
            "role": ctx.role, "meals": meals_today, "my_jobs": mine, "tasks": tasks,
            "everyone": [{"person": pid, "name": h.people[pid].name, "jobs": j} for pid, j in everyone.items() if j],
            "occasions": up[:5], "birthday": any(o["kind"] == "birthday" and me in o["people"] and o["date"] == today.isoformat()
                                                 for o in up),
            "week_status": rec.get("status") if rec else None}


def _ensure_ahead(h, start: dt.date, weeks: int, by: str) -> None:
    """Draft any upcoming week that has no plan yet, so a forecast has something to look at."""
    con = store.connect()
    missing = [start + dt.timedelta(weeks=n) for n in range(weeks)
               if not store.get_week(con, (start + dt.timedelta(weeks=n)).isoformat())]
    con.close()
    for wk in missing:
        week.draft(wk, ideas=False, actor=by)


@app.get("/api/forecast/ingredients")
def forecast_list(weeks: int = 4, start: str | None = None, ctx: Ctx = Depends(member)) -> dict:
    h = _hh()
    s = _week(start)
    weeks = max(1, min(weeks, 8))
    _ensure_ahead(h, s, weeks, actor(ctx))
    c = catalog.for_household(h)
    con = store.connect()
    recs = forecast._week_records(con, s, weeks)
    con.close()
    return {"weeks": weeks, "ingredients": forecast.common(c, PriceBook(h, s, catalog=c), recs, top=20)}


@app.get("/api/forecast")
def forecast_one(ingredient: str, weeks: int = 4, start: str | None = None, ctx: Ctx = Depends(member)) -> dict:
    h = _hh()
    s = _week(start)
    weeks = max(1, min(weeks, 8))
    _ensure_ahead(h, s, weeks, actor(ctx))
    c = catalog.for_household(h)
    try:
        return forecast.forecast(h, c, PriceBook(h, s, catalog=c), ingredient, s, weeks, today=dt.date.today())
    except ValueError as e:
        raise HTTPException(404, str(e))


class CookFromIn(BaseModel):
    text: str = Field(default="", max_length=1000)
    use_soon: list[str] = []
    use_pantry: bool = True
    meal: str = "dinner"
    day: str | None = None
    max_minutes: int | None = Field(default=None, ge=5, le=300)


@app.post("/api/cookfrom")
def cook_from(body: CookFromIn, ctx: Ctx = Depends(member)) -> dict:
    h = _hh()
    c = catalog.for_household(h)
    return cookfrom.suggest(h, c, PriceBook(h, dt.date.today(), catalog=c), text=body.text, use_pantry=body.use_pantry,
                            use_soon=body.use_soon, meal=body.meal, day=body.day, max_minutes=body.max_minutes)


class UseIn(BaseModel):
    recipe: str
    day: str
    meal: str = "dinner"
    week: str | None = None


@app.post("/api/cookfrom/use")
def cook_from_use(body: UseIn, ctx: Ctx = Depends(member)) -> dict:
    """Put a "what I've got" idea on that day's plan (undo puts the planned meal back)."""
    return change_meal(ChangeIn(week=body.week, day=body.day, meal=body.meal, recipe=body.recipe), ctx)


@app.get("/api/storage")
def get_storage(ctx: Ctx = Depends(member)) -> dict:
    h = _hh()
    c = catalog.for_household(h)
    con = store.connect()
    out = {"capacity": h.storage(), "used": storage.usage(con, c), "free": storage.free_space(h, con, c),
           "freezer_meals": store.freezer_meals(con),
           "frozen": [{"ingredient": i, "name": c.ingredients[i].name if i in c.ingredients else i, "qty": q,
                       "unit": c.ingredients[i].unit if i in c.ingredients else ""} for i, q in store.frozen(con).items()]}
    con.close()
    return out


class FreezerIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    portions: float = Field(gt=0, le=40)
    recipe: str | None = None
    frozen_on: str | None = None


@app.post("/api/storage/freezer")
def add_freezer_meal(body: FreezerIn, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    d = dt.date.fromisoformat(body.frozen_on) if body.frozen_on else dt.date.today()
    con = store.connect()
    con.execute("INSERT INTO freezer (recipe, name, portions, frozen_on, use_by) VALUES (?,?,?,?,?)",
                (body.recipe or "h_freezer", body.name, body.portions, d.isoformat(),
                 (d + dt.timedelta(days=90)).isoformat()))
    con.commit()
    con.close()
    return {"added": body.name}


class FreezerEdit(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    portions: float = Field(ge=0, le=40)
    use_by: str | None = None


@app.put("/api/storage/freezer/{fid}")
def edit_freezer_meal(fid: int, body: FreezerEdit, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    if body.use_by:
        try:
            dt.date.fromisoformat(body.use_by)
        except ValueError:
            raise HTTPException(422, "use-by: YYYY-MM-DD")
    con = store.connect()
    n = con.execute("UPDATE freezer SET name = ?, portions = ?, use_by = COALESCE(?, use_by), "
                    "used_on = CASE WHEN ? <= 0 THEN date('now') ELSE NULL END WHERE id = ?",
                    (body.name, body.portions, body.use_by, body.portions, fid)).rowcount
    con.commit()
    con.close()
    if not n:
        raise HTTPException(404, "no such freezer item")
    return {"saved": fid}


@app.delete("/api/storage/freezer/{fid}")
def remove_freezer_meal(fid: int, ctx: Ctx = Depends(member)) -> dict:
    need(ctx, "adult")
    con = store.connect()
    con.execute("DELETE FROM freezer WHERE id = ?", (fid,))
    con.commit()
    con.close()
    return {"removed": fid}


# ---------------------------------------------------------------- calendar feeds and tap-back links
@app.get("/api/calendar/link")
def calendar_link(ctx: Ctx = Depends(member)) -> dict:
    con = accounts.connect()
    u = accounts.user(con, ctx.uid)
    con.close()
    path = f"/cal/{ctx.hid}/{ctx.uid}/{feed_sig(ctx.hid, ctx.uid, u['feed_salt'])}.ics"
    https = public_url() + path
    return {"https": https, "webcal": re.sub(r"^https?://", "webcal://", https),
            "google": "https://calendar.google.com/calendar/r?cid=" + re.sub(r"^https?://", "webcal://", https),
            "note": "Subscribe once; it updates itself (Apple about hourly, Google every few hours)."}


@app.post("/api/calendar/rotate")
def calendar_rotate(ctx: Ctx = Depends(member)) -> dict:
    con = accounts.connect()
    accounts.rotate_feed(con, ctx.uid)
    con.close()
    return calendar_link(ctx)


def _tap_links(hid: str, uid: str):
    def link(kind: str, **kw) -> str:
        if kind in ("app", "open"):
            screen = kw.pop("screen", "week")
            q = "&".join(f"{k}={v}" for k, v in kw.items() if k in ("day",) and v)
            return f"{public_url()}/open/{screen}" + (f"?{q}" if q else "")
        sub = json.dumps({"h": hid, "u": uid, "k": kind, **kw}, separators=(",", ":"), default=str)
        return f"{public_url()}/t/{sign('tap', sub, TAP_TTL)}"
    return link


@app.get("/cal/{hid}/{uid}/{sig}.ics")
def calendar_feed(hid: str, uid: str, sig: str) -> Response:
    """A person's private calendar feed. Revoke it with /api/calendar/rotate."""
    con = accounts.connect()
    u = accounts.user(con, uid)
    m = accounts.membership(con, uid, hid) if u else None
    con.close()
    if not u or not m or not hmac.compare_digest(sig, feed_sig(hid, uid, u["feed_salt"])):
        raise HTTPException(404)
    tok = set_tenant(hid)
    try:
        h = load_household()
        con = store.connect()
        today = week_start(dt.date.today())
        weeks = [store.get_week(con, (today + dt.timedelta(weeks=n)).isoformat()) for n in (-1, 0, 1, 2)]
        con.close()
        text = outputs.ics(h, [w for w in weeks if w], person=m["person_id"], links=_tap_links(hid, uid),
                           tz=h.info.get("timezone", "America/New_York"))
    finally:
        reset_tenant(tok)
    return Response(text, media_type="text/calendar")


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,
initial-scale=1"><title>DinnerPeace</title><style>body{{font-family:-apple-system,Helvetica,Arial,sans-serif;
background:#FFF8EC;color:#3A2A1E;max-width:520px;margin:0 auto;padding:24px}}h1{{font-size:22px;margin:0 0 8px}}
h1 span.l{{color:#D7392A}}h1 span.h{{color:#3E9E3A}}.card{{background:#fff;border:1px solid #F0E2CC;border-radius:14px;
padding:16px;margin:12px 0}}button,a.b{{display:inline-block;background:#D7392A;color:#fff;border:0;border-radius:12px;
padding:12px 16px;font-size:16px;font-weight:700;text-decoration:none}}li{{margin:4px 0}}.m{{color:#7A6A5C;font-size:14px}}
</style></head><body><h1><span class="l">Lil’</span><span class="h">Helper</span></h1>{body}</body></html>"""


OPEN_SCREENS = {"week", "shopping", "meals", "jobs", "money", "book", "signin"}


@app.get("/open/{screen}", response_class=HTMLResponse)
def open_in_app(screen: str, request: Request) -> str:
    """A web link that opens the app: calendar apps make https links tappable (not app links), so events link here
    and the page hands over to lilhelper://… on a phone with the app; elsewhere it says what to do."""
    if screen not in OPEN_SCREENS:
        raise HTTPException(404)
    q = "&".join(f"{k}={quote(v)}" for k, v in request.query_params.items() if k in ("day", "code", "token", "invite"))
    app_link = f"lilhelper://{screen}" + (f"?{q}" if q else "")
    label = {"week": "this week's plan", "shopping": "the shopping lists", "book": "the shared recipes",
             "meals": "rate meals", "jobs": "jobs", "money": "money", "signin": "sign in"}[screen]
    body = (f"<div class='card'><p>Opening DinnerPeace — {html.escape(label)}…</p>"
            f"<p><a class='b' href='{html.escape(app_link)}'>Open DinnerPeace</a></p>"
            "<p class='m'>Nothing happening? Open this on the phone where DinnerPeace is installed.</p></div>"
            f"<script>location.href={json.dumps(app_link)}</script>")
    return PAGE.format(body=body)


@app.get("/t/{token}", response_class=HTMLResponse)
def tap(token: str) -> str:
    """A link tapped from a calendar event. Feedback is recorded by the page's script (a real browser), not by the
    GET itself, so link previews and scanners can't record a rating nobody chose."""
    d = json.loads(verify("tap", token))
    kind = d["k"]
    if kind in ("rate", "eaten"):
        what = f"{d['value']} star{'s' if str(d['value']) != '1' else ''}" if kind == "rate" else \
            {"all": "all gone", "some_left": "some left", "lots_left": "lots left"}.get(d["value"], d["value"])
        body = (f"<div class='card'><p id='msg'>Saving “{html.escape(what)}”…</p><form method='post'>"
                f"<noscript><button>Save “{html.escape(what)}”</button></noscript></form></div>"
                "<script>fetch(location.href,{method:'POST'}).then(r=>r.json()).then(j=>{document.getElementById('msg')"
                ".textContent=j.ok?'Thanks! Saved for '+j.meal+'.':(j.detail||'Sorry, that did not save.')})"
                ".catch(()=>{document.getElementById('msg').textContent='Sorry, that did not save.'})</script>")
        return PAGE.format(body=body)
    if kind == "change":
        link = f"lilhelper://week?day={d.get('day', '')}"
        return PAGE.format(body=f"<div class='card'><p>Open DinnerPeace to change {html.escape(d.get('day', '').title())}"
                                f"'s {html.escape(d.get('meal', 'meal'))}.</p><a class='b' href='{link}'>Open "
                                "DinnerPeace</a></div>")
    if kind == "list":
        tok = set_tenant(d["h"])
        try:
            rec = store.get_week(store.connect(), d["week"])
            orders = _orders(rec, rec.get("shopping_choice") or "balanced") if rec else []
            o = orders[int(d["order"])] if int(d["order"]) < len(orders) else None
        finally:
            reset_tenant(tok)
        if not o:
            return PAGE.format(body="<div class='card'>That list has changed. Open DinnerPeace for the latest.</div>")
        items = "".join(f"<li>☐ {ln['packs']} × {html.escape(ln['name'])}</li>" for ln in o["lines"])
        return PAGE.format(body=f"<div class='card'><b>{html.escape(o['store_name'])}</b> "
                                f"<span class='m'>{html.escape(o['mode'].replace('_', ' '))} · about "
                                f"${o['total']:.2f}</span><ul>{items}</ul></div>")
    raise HTTPException(404)


@app.post("/t/{token}")
def tap_save(token: str) -> dict:
    d = json.loads(verify("tap", token))
    if d["k"] not in ("rate", "eaten"):
        raise HTTPException(404)
    con = accounts.connect()
    m = accounts.membership(con, d["u"], d["h"])
    con.close()
    if not m:
        raise HTTPException(403, "no longer a member of that household")
    tok = set_tenant(d["h"])
    try:
        out = _record_feedback(d["week"], d["day"], d["meal"], d["value"] if d["k"] == "eaten" else None,
                               int(d["value"]) if d["k"] == "rate" else None, m["person_id"] or d["u"])
    finally:
        reset_tenant(tok)
    return {"ok": True, "meal": out["meal"]}


# ---------------------------------------------------------------- devices, print, savings
class DeviceIn(BaseModel):
    token: str = Field(max_length=200)
    platform: str = "ios"


@app.post("/api/devices")
def add_device(body: DeviceIn, ctx: Ctx = Depends(member)) -> dict:
    con = accounts.connect()
    try:
        accounts.add_device(con, ctx.uid, ctx.hid, body.token, body.platform)
    except ValueError as e:
        con.close()
        raise HTTPException(422, str(e))
    con.close()
    return {"registered": True}


@app.get("/api/print/week.pdf")
def print_week(week: str | None = None, ctx: Ctx = Depends(member)) -> Response:
    return Response(outputs.week_pdf(_hh(), _stored(_week(week))), media_type="application/pdf")


@app.get("/api/print/month.pdf")
def print_month(month: str | None = None, ctx: Ctx = Depends(member)) -> Response:
    y, mth = map(int, (month or dt.date.today().strftime("%Y-%m")).split("-"))
    con = store.connect()
    weeks = [store.get_week(con, r["week_of"]) for r in con.execute("SELECT week_of FROM weeks ORDER BY week_of")]
    con.close()
    return Response(outputs.month_pdf(_hh(), y, mth, [w for w in weeks if w]), media_type="application/pdf")


@app.get("/api/savings")
def savings_report(weeks: int = 8, ctx: Ctx = Depends(member)) -> dict:
    con = store.connect()
    rows = con.execute("SELECT week_of FROM weeks WHERE status='approved' ORDER BY week_of DESC LIMIT ?",
                       (weeks,)).fetchall()
    out = []
    for r in rows:
        rec = store.get_week(con, r["week_of"])
        sv = rec.get("savings") or {}
        rs = feedback.ratings(con, r["week_of"])
        out.append({"week_of": r["week_of"], "dollars_saved": sv.get("dollars_saved"),
                    "minutes_saved": sv.get("minutes_saved"), "rating": round(sum(rs) / len(rs), 2) if rs else None})
    con.close()
    return {"weeks": out[::-1],
            "dollars_saved": round(sum(w["dollars_saved"] or 0 for w in out), 2),
            "minutes_saved": round(sum(w["minutes_saved"] or 0 for w in out), 1)}


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    return PAGE.format(body="<div class='card'><p>This is the DinnerPeace server the app talks to.</p>"
                            "<p class='m'>Get the app, then sign in with your email.</p></div>")
