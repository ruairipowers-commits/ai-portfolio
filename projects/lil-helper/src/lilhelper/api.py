"""The API the phone app talks to (FastAPI). It runs on the household's own server; the family's data never leaves it.

Sign-in: an adult types their email, gets a one-time link (15 minutes), and the app keeps a signed session token
(30 days). Kids don't sign in. Only an adult can approve a week (HITL-02). Nothing here buys anything: the shopping
endpoint returns hand-offs (an Instacart link, a list to share, a printable aisle list) that a person opens.

Secrets come from the environment (SEC-01): HELPER_SECRET signs links, sessions and the calendar-feed URL.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import time

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from . import __version__, ai, catalog, chores, feedback, outputs, store, telemetry, week
from .config import DAYS, Settings, load_household, work_root
from .prices import PriceBook, week_start

DEV_SECRET = "dev-only-not-secret"
LINK_TTL = 15 * 60
SESSION_TTL = 30 * 24 * 3600
INSTACART = {"development": "https://connect.dev.instacart.tools", "production": "https://connect.instacart.com"}

app = FastAPI(title="Lil'Helper", version=__version__, root_path=os.getenv("ROOT_PATH", ""))


@app.on_event("startup")
def _start_scheduler() -> None:
    if os.getenv("HELPER_SCHEDULER") == "1":
        from . import schedule
        schedule.start()
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("HELPER_CORS", "*").split(","), allow_methods=["*"],
                   allow_headers=["*"])


# ---------------------------------------------------------------- signing
def _secret() -> bytes:
    sec = os.getenv("HELPER_SECRET", "")
    if not sec:
        if os.getenv("HELPER_ENV") == "production":
            raise RuntimeError("HELPER_SECRET must be set in production")
        sec = DEV_SECRET
    return sec.encode()


def sign(kind: str, subject: str, ttl: int) -> str:
    body = json.dumps({"k": kind, "s": subject, "e": int(time.time()) + ttl}, separators=(",", ":")).encode()
    mac = hmac.new(_secret(), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body).decode().rstrip("=") + "." + base64.urlsafe_b64encode(mac).decode().rstrip("=")


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


def feed_key() -> str:
    return hmac.new(_secret(), b"calendar-feed", hashlib.sha256).hexdigest()[:24]


def me(authorization: str = Header(default="")) -> str:
    """The signed-in adult's id."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "sign in first")
    pid = verify("session", authorization[7:])
    h = load_household()
    if pid not in h.people or h.people[pid].is_kid:
        raise HTTPException(403, "not an adult in this household")
    return pid


def _week(w: str | None) -> dt.date:
    return week_start(dt.date.fromisoformat(w) if w else dt.date.today())


def _stored(w: dt.date) -> dict:
    con = store.connect()
    rec = store.get_week(con, w.isoformat())
    con.close()
    if not rec:
        raise HTTPException(404, "no plan for that week yet")
    return rec


# ---------------------------------------------------------------- sign-in
class EmailIn(BaseModel):
    email: str = Field(max_length=200)


class TokenIn(BaseModel):
    token: str = Field(max_length=500)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@app.post("/api/auth/request")
def auth_request(body: EmailIn) -> dict:
    """Always answers the same way, so the endpoint doesn't reveal who's in the household."""
    h = load_household()
    who = next((p for p in h.people.values() if not p.is_kid and p.email and p.email.lower() == body.email.lower()), None)
    if who:
        link = f"{os.getenv('HELPER_APP_LINK', 'lilhelper://signin')}?token={sign('link', who.id, LINK_TTL)}"
        _send_link(who.email, link)
    return {"sent": True, "message": "If that email belongs to an adult in this household, a sign-in link is on its way."}


def _send_link(to: str, link: str) -> None:
    html = f"<p>Tap to sign in to Lil'Helper (valid 15 minutes):</p><p><a href='{link}'>{link}</a></p>"
    if os.getenv("RESEND_API_KEY"):
        httpx.post("https://api.resend.com/emails", timeout=15,
                   headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
                   json={"from": os.getenv("MAIL_FROM", "Lil'Helper <helper@example.com>"), "to": [to],
                         "subject": "Your Lil'Helper sign-in link", "html": html})
    else:
        d = work_root() / "output" / "outbox"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"signin-{hashlib.sha256(to.encode()).hexdigest()[:8]}.html").write_text(html)


@app.post("/api/auth/verify")
def auth_verify(body: TokenIn) -> dict:
    pid = verify("link", body.token)
    h = load_household()
    return {"session": sign("session", pid, SESSION_TTL), "person": pid, "name": h.people[pid].name}


# ---------------------------------------------------------------- household
@app.get("/api/household")
def household(pid: str = Depends(me)) -> dict:
    h = load_household()
    return {"name": h.info.get("name"), "me": pid,
            "people": [{"id": p.id, "name": p.name, "kid": p.is_kid, "allergies": p.allergies, "diet": p.diet}
                       for p in h.people.values()],
            "pets": [{"id": p.id, "name": p.name, "species": p.species, "food": p.food.get("brand")} for p in h.pets.values()],
            "meals": {k: v for k, v in h.meals.items() if k != "special_nights"},
            "prep_minutes": h.raw.get("prep_minutes", {}), "budget_per_week": h.info.get("budget_per_week"),
            "stores": h.raw.get("stores", []),
            "calendar_feed": f"/api/calendar/{feed_key()}.ics"}


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


def _view(rec: dict) -> dict:
    h = load_household()
    choice = rec.get("shopping_choice") or "balanced"
    return {"week_of": rec["week_of"], "status": rec.get("status"), "approved_by": rec.get("approved_by"),
            "plan": rec["plan"], "choice": choice,
            "options": {k: {"total": v["total"], "minutes": v["minutes"],
                            "stores": [{"store": o["store_name"], "mode": o["mode"], "total": o["total"]}
                                       for o in v["orders"]]} for k, v in rec["split"].items()},
            "chores": rec.get("chores", []), "pets": rec.get("pets", []), "savings": rec.get("savings"),
            "people": {p.id: p.name for p in h.people.values()}}


@app.get("/api/week")
def get_week(week: str | None = None, pid: str = Depends(me)) -> dict:
    return _view(_stored(_week(week)))


@app.post("/api/week/draft")
def draft_week(body: WeekIn, pid: str = Depends(me)) -> dict:
    week.draft(_week(body.week), choice=body.choice, actor=pid)
    return _view(_stored(_week(body.week)))


@app.post("/api/week/swap")
def swap_meal(body: SwapIn, pid: str = Depends(me)) -> dict:
    if body.day not in DAYS:
        raise HTTPException(422, "day must be mon..sun")
    try:
        week.swap(_week(body.week), body.day, body.meal, to=body.to, actor=pid)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _view(_stored(_week(body.week)))


@app.post("/api/week/approve")
def approve_week(body: ApproveIn, pid: str = Depends(me)) -> dict:
    try:
        week.approve(_week(body.week), pid, body.seconds, body.choice)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(409, str(e))
    return _view(_stored(_week(body.week)))


# ---------------------------------------------------------------- shopping hand-offs
@app.get("/api/week/shopping")
def shopping(week: str | None = None, choice: str | None = None, pid: str = Depends(me)) -> dict:
    rec = _stored(_week(week))
    if rec.get("status") != "approved":
        raise HTTPException(409, "approve the week first; nothing is handed to a store before that")
    choice = choice or rec.get("shopping_choice") or "balanced"
    out = []
    for o in rec["split"][choice]["orders"]:
        item = {"store": o["store_name"], "mode": o["mode"], "handoff": o["handoff"], "total": o["total"],
                "lines": [{"name": ln["name"], "packs": ln["packs"], "brand": ln["brand"], "special": ln["special"],
                           "price": ln["price_each"]} for ln in o["lines"]],
                "credits": o.get("credits", 0), "url": None, "note": None}
        if o["handoff"] == "instacart":
            item["url"], item["note"] = instacart_link(o["payload"])
        elif o["handoff"] == "amazon":
            item["share_text"] = "\n".join(o["payload"]["items"])
            item["note"] = "Share to the Amazon or Whole Foods app, or to Reminders"
        else:
            item["share_text"] = "\n".join(o["payload"]["aisle_ordered"])
            item["note"] = ("In-store list in aisle order; share it to Reminders or print it" if o["mode"] == "in_store"
                            else f"Order {o['mode']} in {o['store_name']}'s own app with this list")
        out.append(item)
    store.audit(store.connect(), pid, "handoff_view", {"week_of": rec["week_of"], "choice": choice})
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


# ---------------------------------------------------------------- jobs
class JobSwapIn(BaseModel):
    week: str | None = None
    day: str
    job: str
    person: str


@app.post("/api/jobs/swap")
def swap_job(body: JobSwapIn, pid: str = Depends(me)) -> dict:
    h = load_household()
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
    store.audit(con, pid, "job_swap", body.model_dump())
    con.close()
    return {"chores": jobs}


# ---------------------------------------------------------------- feedback
class FeedbackIn(BaseModel):
    week: str | None = None
    day: str
    meal: str
    eaten: str
    rating: int | None = Field(default=None, ge=1, le=5)


@app.post("/api/feedback")
def give_feedback(body: FeedbackIn, pid: str = Depends(me)) -> dict:
    con = store.connect()
    wk = _week(body.week).isoformat()
    rec = store.get_week(con, wk)
    e = next((e for e in (rec or {}).get("plan", {}).get("entries", [])
              if e["day"] == body.day and e["meal"] == body.meal), None)
    if not e:
        raise HTTPException(404, "no such meal that week")
    try:
        feedback.record(con, wk, body.day, body.meal, e["recipe"], body.eaten, body.rating, pid)
    except ValueError as ex:
        raise HTTPException(422, str(ex))
    changed = feedback.learn(con, Settings.load(), wk)
    con.close()
    return {"recorded": True, "portions_changed": changed}


# ---------------------------------------------------------------- specials from a flyer
@app.post("/api/flyer")
async def flyer(store_id: str = Form(...), week: str | None = Form(None), image: UploadFile = File(...),
                pid: str = Depends(me)) -> dict:
    data = await image.read()
    if len(data) > 8_000_000:
        raise HTTPException(413, "photo too large (8 MB max)")
    h = load_household()
    s = Settings.load()
    c = catalog.get(h.info.get("region", "northeast-us"))
    pb = PriceBook(h, _week(week))
    res = ai.read_flyer(ai.AIContext.make(s), h, c, pb, store_id, image=data)
    return {"store": store_id, "flags": res.flags, "items": res.items,
            "note": "Nothing counts until you confirm it"}


class ConfirmIn(BaseModel):
    week: str | None = None
    store_id: str
    items: list[dict]


@app.post("/api/specials/confirm")
def confirm_specials(body: ConfirmIn, pid: str = Depends(me)) -> dict:
    con = store.connect()
    wk = _week(body.week).isoformat()
    n = 0
    for it in body.items:
        if not it.get("ingredient") or it.get("price") is None:
            continue
        con.execute("INSERT INTO specials VALUES (?,?,?,?,?,?,?,?)",
                    (wk, body.store_id, it["ingredient"], float(it["price"]), it.get("regular"), "flyer", pid,
                     store.now()))
        n += 1
    con.commit()
    store.audit(con, pid, "specials_confirm", {"week_of": wk, "store": body.store_id, "count": n})
    con.close()
    return {"confirmed": n}


# ---------------------------------------------------------------- outputs
@app.get("/api/calendar/{key}.ics")
def calendar_feed(key: str) -> Response:
    """The one URL a household subscribes to in Google Calendar. Unguessable, revocable by changing HELPER_SECRET."""
    if not hmac.compare_digest(key, feed_key()):
        raise HTTPException(404)
    con = store.connect()
    weeks = [store.get_week(con, r["week_of"]) for r in con.execute("SELECT week_of FROM weeks ORDER BY week_of")]
    con.close()
    return Response(outputs.ics(load_household(), [w for w in weeks if w]), media_type="text/calendar")


@app.get("/api/print/week.pdf")
def print_week(week: str | None = None, pid: str = Depends(me)) -> Response:
    return Response(outputs.week_pdf(load_household(), _stored(_week(week))), media_type="application/pdf")


@app.get("/api/print/month.pdf")
def print_month(month: str | None = None, pid: str = Depends(me)) -> Response:
    y, m = map(int, (month or dt.date.today().strftime("%Y-%m")).split("-"))
    con = store.connect()
    weeks = [store.get_week(con, r["week_of"]) for r in con.execute("SELECT week_of FROM weeks ORDER BY week_of")]
    con.close()
    return Response(outputs.month_pdf(load_household(), y, m, [w for w in weeks if w]), media_type="application/pdf")


@app.get("/api/savings")
def savings_report(weeks: int = 8, pid: str = Depends(me)) -> dict:
    con = store.connect()
    rows = con.execute("SELECT week_of FROM weeks WHERE status='approved' ORDER BY week_of DESC LIMIT ?",
                       (weeks,)).fetchall()
    out = []
    for r in rows:
        rec = store.get_week(con, r["week_of"])
        sv = rec.get("savings") or {}
        out.append({"week_of": r["week_of"], "dollars_saved": sv.get("dollars_saved"),
                    "minutes_saved": sv.get("minutes_saved"), "rating": sv.get("rating") or
                    (sum(feedback.ratings(con, r["week_of"])) / max(1, len(feedback.ratings(con, r["week_of"])))
                     if feedback.ratings(con, r["week_of"]) else None)})
    con.close()
    return {"weeks": out[::-1],
            "dollars_saved": round(sum(w["dollars_saved"] or 0 for w in out), 2),
            "minutes_saved": round(sum(w["minutes_saved"] or 0 for w in out), 1)}


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    return ("<h1>Lil'Helper API</h1><p>This is the server the phone app talks to. "
            "See <a href='docs'>docs</a>.</p>")
