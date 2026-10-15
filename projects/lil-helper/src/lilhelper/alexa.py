"""Alexa: "Alexa, ask Lil'Helper what's for dinner."

The skill itself lives in the Amazon developer console (docs/alexa.md has the steps); this module is the endpoint it
calls, and it does the same things as the app's microphone button (voice.py → api.run_voice).

Every request is checked the way Amazon requires for a self-hosted skill (SEC-03):
  - the certificate URL is https://s3.amazonaws.com/echo.api/… on port 443
  - the certificate chain is valid today, chains to a trusted root, and names echo-api.amazon.com
  - the Signature-256 header is an RSA-SHA256 signature of the exact request body by that certificate
  - the request timestamp is within 150 seconds
  - the skill id matches HELPER_ALEXA_SKILL_ID
Anything else gets a 400 and is not read.

Account linking (no passwords): in the app, an adult taps "Link Alexa" and gets a short code that works once, for ten
minutes. In the Alexa app they're sent to /alexa/link, type the code, and Amazon gets a long random token tied to that
person and household. We store only its hash; "Unlink Alexa" in the app removes it.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import html
import json
import os
import secrets
import time
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import accounts

router = APIRouter()
CODE_TTL = 10 * 60
MAX_SKEW = 150
CERT_HOST = "s3.amazonaws.com"
CERT_PATH = "/echo.api/"
CERT_SAN = "echo-api.amazon.com"
# Where Amazon may ask us to send the linked account back to (Alexa app, by region).
REDIRECT_HOSTS = {"pitangui.amazon.com", "layla.amazon.com", "alexa.amazon.co.jp"}
_certs: dict[str, tuple[float, list]] = {}

LINK_SCHEMA = """
CREATE TABLE IF NOT EXISTS voice_codes (code TEXT PRIMARY KEY, user_id TEXT, household_id TEXT, expires REAL);
CREATE TABLE IF NOT EXISTS voice_links (token_hash TEXT PRIMARY KEY, user_id TEXT, household_id TEXT, created TEXT,
    last_used TEXT);
"""


# ---------------------------------------------------------------- linking (accounts database)
def _con():
    con = accounts.connect()
    con.executescript(LINK_SCHEMA)
    return con


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_code(uid: str, hid: str) -> str:
    """A one-time code a person types into the Alexa app to link it (ten minutes)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I
    code = "".join(secrets.choice(alphabet) for _ in range(8))
    con = _con()
    con.execute("DELETE FROM voice_codes WHERE expires < ? OR (user_id = ? AND household_id = ?)", (time.time(), uid, hid))
    con.execute("INSERT INTO voice_codes VALUES (?,?,?,?)", (code, uid, hid, time.time() + CODE_TTL))
    con.commit()
    con.close()
    return code


def redeem(code: str) -> str | None:
    """Swap a code for a long-lived token (only its hash is kept)."""
    code = "".join(ch for ch in (code or "").upper() if ch.isalnum())
    con = _con()
    row = con.execute("SELECT * FROM voice_codes WHERE code = ? AND expires >= ?", (code, time.time())).fetchone()
    if not row:
        con.close()
        return None
    con.execute("DELETE FROM voice_codes WHERE code = ?", (code,))
    token = secrets.token_urlsafe(32)
    con.execute("INSERT INTO voice_links VALUES (?,?,?,?,?)",
                (_hash(token), row["user_id"], row["household_id"], accounts.now(), None))
    con.commit()
    con.close()
    return token


def linked(token: str | None) -> tuple[str, str] | None:
    if not token:
        return None
    con = _con()
    row = con.execute("SELECT * FROM voice_links WHERE token_hash = ?", (_hash(token),)).fetchone()
    if row:
        con.execute("UPDATE voice_links SET last_used = ? WHERE token_hash = ?", (accounts.now(), row["token_hash"]))
        con.commit()
    con.close()
    return (row["user_id"], row["household_id"]) if row else None


def links(uid: str, hid: str) -> list[dict]:
    con = _con()
    rows = [{"created": r["created"], "last_used": r["last_used"]} for r in
            con.execute("SELECT * FROM voice_links WHERE user_id = ? AND household_id = ?", (uid, hid))]
    con.close()
    return rows


def unlink(uid: str, hid: str) -> int:
    con = _con()
    n = con.execute("DELETE FROM voice_links WHERE user_id = ? AND household_id = ?", (uid, hid)).rowcount
    con.commit()
    con.close()
    return n


def ok_redirect(uri: str) -> bool:
    u = urlparse(uri or "")
    return u.scheme == "https" and u.hostname in REDIRECT_HOSTS and u.path.startswith("/api/skill/link/")


# ---------------------------------------------------------------- request verification
class Invalid(Exception):
    pass


def check_cert_url(url: str) -> None:
    u = urlparse(url or "")
    path = os.path.normpath(u.path) + ("/" if u.path.endswith("/") else "")
    if u.scheme.lower() != "https" or (u.hostname or "").lower() != CERT_HOST or u.port not in (None, 443) \
            or not path.startswith(CERT_PATH):
        raise Invalid("certificate URL is not Amazon's")


def _fetch_chain(url: str) -> list:
    from cryptography import x509
    hit = _certs.get(url)
    if hit and hit[0] > time.time():
        return hit[1]
    r = httpx.get(url, timeout=5, follow_redirects=False)
    r.raise_for_status()
    chain = x509.load_pem_x509_certificates(r.content)
    _certs[url] = (time.time() + 3600, chain)
    return chain


def check_chain(chain: list, when: dt.datetime | None = None) -> None:
    """Valid now, chains to a trusted root (certifi's), and issued to echo-api.amazon.com."""
    import certifi
    from cryptography import x509
    from cryptography.x509.verification import PolicyBuilder, Store
    if not chain:
        raise Invalid("no certificate")
    roots = Store(x509.load_pem_x509_certificates(open(certifi.where(), "rb").read()))
    try:
        (PolicyBuilder().store(roots).time(when or dt.datetime.now(dt.timezone.utc))
         .build_server_verifier(x509.DNSName(CERT_SAN)).verify(chain[0], chain[1:]))
    except Exception as e:   # noqa: BLE001 — any failure means "don't trust it"
        raise Invalid(f"certificate not trusted: {e}") from None


def check_signature(cert, signature_b64: str, body: bytes) -> None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    try:
        cert.public_key().verify(base64.b64decode(signature_b64 or ""), body, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError, TypeError):
        raise Invalid("signature doesn't match") from None


def check_request(req: dict, skill_id: str, now: float | None = None) -> None:
    ts = (req.get("request") or {}).get("timestamp", "")
    try:
        when = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        raise Invalid("no timestamp") from None
    if abs((now or time.time()) - when) > MAX_SKEW:
        raise Invalid("request too old")
    app_id = ((req.get("context") or {}).get("System") or {}).get("application", {}).get("applicationId") or \
        ((req.get("session") or {}).get("application") or {}).get("applicationId")
    if not skill_id or app_id != skill_id:
        raise Invalid("wrong skill")


def verify(headers, body: bytes, req: dict, fetch=_fetch_chain, chain_check=check_chain) -> None:
    check_cert_url(headers.get("signaturecertchainurl", ""))
    chain = fetch(headers.get("signaturecertchainurl"))
    chain_check(chain)
    check_signature(chain[0], headers.get("signature-256", ""), body)
    check_request(req, os.getenv("HELPER_ALEXA_SKILL_ID", ""))


# ---------------------------------------------------------------- what Alexa asked → a sentence for run_voice
def _slot(intent: dict, name: str) -> str:
    s = (intent.get("slots") or {}).get(name) or {}
    res = (((s.get("resolutions") or {}).get("resolutionsPerAuthority") or [{}])[0].get("values") or [{}])[0]
    return ((res.get("value") or {}).get("name") or s.get("value") or "").strip()


def sentence(intent: dict) -> str | None:
    """Turn an Alexa intent into the same words the app's microphone would hear."""
    n = intent.get("name", "")
    meal, day = _slot(intent, "meal") or "dinner", _slot(intent, "day")
    if n == "WhatsForIntent":
        return f"what's for {meal} {day or 'today'}"
    if n == "ShoppingIntent":
        return "what's on the shopping list"
    if n == "JobsIntent":
        return f"what are my jobs {day}".strip()
    if n == "CookWithIntent":
        have = _slot(intent, "items")
        return f"I have {have}" if have else None
    if n == "VibeIntent":
        return f"I have {_slot(intent, 'minutes') or 45} minutes and feel like something {_slot(intent, 'mood')}".strip()
    if n == "SurpriseIntent":
        return f"surprise me {meal}"
    if n == "BuffetCountIntent":
        return f"{_slot(intent, 'count') or 0} portions of {_slot(intent, 'item')} left"
    if n == "LeftoversIntent":
        amount = {"all": "all gone", "some": "some left", "lots": "lots left"}.get(_slot(intent, "amount"), "some left")
        return f"{meal} {day} was {amount}"
    if n == "RateIntent":
        return f"rate {meal} {_slot(intent, 'stars') or 0} stars {day}".strip()
    if n == "PlanWeekIntent":
        return f"plan {'next' if _slot(intent, 'which') == 'next' else 'this'} week"
    return None


def speak(text: str, end: bool = True, card: dict | None = None, reprompt: str | None = None) -> dict:
    resp = {"outputSpeech": {"type": "PlainText", "text": text}, "shouldEndSession": end}
    if reprompt:
        resp["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": reprompt}}
    if card:
        resp["card"] = card
    return {"version": "1.0", "response": resp}


HELP = ("You can ask what's for dinner, what's on the shopping list, or what your jobs are. Or tell me what you have, "
        "like: I have chicken, rice and broccoli.")


def handle(req: dict, run) -> dict:
    """run(uid, hid, text) → run_voice's answer. Kept separate from the web layer so it's easy to test."""
    r = req.get("request") or {}
    kind = r.get("type")
    if kind == "SessionEndedRequest":
        return {"version": "1.0", "response": {}}
    token = ((req.get("context") or {}).get("System") or {}).get("user", {}).get("accessToken") or \
        ((req.get("session") or {}).get("user") or {}).get("accessToken")
    who = linked(token)
    if not who:
        return speak("First, link Lil'Helper: in the Lil'Helper app go to Settings, then Alexa, and get a code. "
                     "Then open the Alexa app and link the skill.", card={"type": "LinkAccount"})
    if kind == "LaunchRequest":
        return speak("Hi, it's Lil'Helper. " + HELP, end=False, reprompt="What would you like?")
    if kind != "IntentRequest":
        return speak("Sorry, I can't do that yet.")
    intent = r.get("intent") or {}
    name = intent.get("name", "")
    if name in ("AMAZON.StopIntent", "AMAZON.CancelIntent", "AMAZON.NavigateHomeIntent"):
        return speak("Bye!")
    if name == "AMAZON.HelpIntent":
        return speak(HELP, end=False, reprompt="What would you like?")
    text = sentence(intent)
    if not text:
        return speak("Sorry, I didn't catch that. " + HELP, end=False, reprompt="What would you like?")
    out = run(who[0], who[1], text)
    card = {"type": "Simple", "title": "Lil'Helper", "content": out["say"]}
    return speak(out["say"], card=card)


# ---------------------------------------------------------------- web endpoints
@router.post("/alexa")
async def alexa_endpoint(request: Request) -> JSONResponse:
    body = await request.body()
    if len(body) > 64_000:
        raise HTTPException(413)
    try:
        req = json.loads(body)
        if os.getenv("HELPER_ALEXA_VERIFY", "1") == "0" and os.getenv("HELPER_ENV") != "production":
            check_request(req, os.getenv("HELPER_ALEXA_SKILL_ID", ""))   # local testing only
        else:
            verify(request.headers, body, req)
    except (Invalid, ValueError, httpx.HTTPError) as e:
        raise HTTPException(400, f"not a valid Alexa request: {e}") from None
    from .api import run_as
    return JSONResponse(handle(req, run_as))


LINK_PAGE = """<div class='card'><h2>Link Alexa to Lil'Helper</h2>
<p class='m'>In the Lil'Helper app, open <b>Settings → Alexa</b> and tap <b>Get a code</b>. Type it here.</p>
<form method='post' action='{action}'>
<input type='hidden' name='state' value='{state}'><input type='hidden' name='redirect_uri' value='{redirect}'>
<p><input name='code' autocomplete='one-time-code' autocapitalize='characters' placeholder='e.g. K7Q2M9XD'
style='font-size:22px;letter-spacing:3px;padding:10px;width:12em'></p>
<p><button class='b' type='submit'>Link</button></p>{error}</form></div>"""


def link_page(page: str, redirect_uri: str, state: str, error: str = "") -> str:
    from .api import public_url
    return page.format(body=LINK_PAGE.format(
        action=html.escape(public_url() + "/alexa/link"), state=html.escape(state), redirect=html.escape(redirect_uri),
        error=f"<p style='color:#b42318'>{html.escape(error)}</p>" if error else ""))


@router.get("/alexa/link", response_class=HTMLResponse)
def link_start(redirect_uri: str = "", state: str = "", response_type: str = "token", client_id: str = "") -> str:
    """Amazon's account-linking page (implicit grant)."""
    from .api import PAGE
    if response_type != "token" or not ok_redirect(redirect_uri):
        raise HTTPException(400, "this page is opened from the Alexa app")
    return link_page(PAGE, redirect_uri, state)


@router.post("/alexa/link")
def link_finish(request: Request, code: str = Form(""), state: str = Form(""), redirect_uri: str = Form("")):
    from .api import PAGE, rate_limit
    if not ok_redirect(redirect_uri):
        raise HTTPException(400, "this page is opened from the Alexa app")
    rate_limit(f"alexa-link:{request.client.host if request.client else '-'}", 20)
    token = redeem(code)
    if not token:
        return HTMLResponse(link_page(PAGE, redirect_uri, state, "That code didn't work. Codes last ten minutes and "
                                                                   "work once; get a new one in the app."), 400)
    frag = urlencode({"state": state, "access_token": token, "token_type": "Bearer"})
    return RedirectResponse(f"{redirect_uri}#{frag}", 302)
