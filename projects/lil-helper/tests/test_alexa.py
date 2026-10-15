"""Alexa endpoint: request verification, account linking, intents → the same answers as the app's microphone."""
import base64
import datetime as dt
import json
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from lilhelper import alexa

SKILL = "amzn1.ask.skill.test-123"
W = "2026-10-19"
REDIRECT = "https://pitangui.amazon.com/api/skill/link/M2ABCDEF"


def _cert():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "echo-api.amazon.com")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("echo-api.amazon.com")]), critical=False)
            .sign(key, hashes.SHA256()))
    return key, cert


def _req(kind="IntentRequest", intent=None, token=None, skill=SKILL, ts=None):
    ts = ts or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = {"type": kind, "requestId": "r1", "timestamp": ts, "locale": "en-US"}
    if intent:
        r["intent"] = intent
    user = {"userId": "amzn1.ask.account.X", **({"accessToken": token} if token else {})}
    return {"version": "1.0", "session": {"application": {"applicationId": skill}, "user": user},
            "context": {"System": {"application": {"applicationId": skill}, "user": user}}, "request": r}


def _intent(name, **slots):
    return {"name": name, "slots": {k: {"name": k, "value": v} for k, v in slots.items()}}


def test_cert_url_rules():
    ok = ["https://s3.amazonaws.com/echo.api/echo-api-cert.pem", "https://s3.amazonaws.com:443/echo.api/echo-api-cert.pem",
          "https://s3.amazonaws.com/echo.api/../echo.api/echo-api-cert.pem", "HTTPS://s3.amazonaws.com/echo.api/x.pem"]
    bad = ["http://s3.amazonaws.com/echo.api/echo-api-cert.pem", "https://notamazon.com/echo.api/echo-api-cert.pem",
           "https://s3.amazonaws.com/EcHo.aPi/echo-api-cert.pem", "https://s3.amazonaws.com/invalid.path/echo-api-cert.pem",
           "https://s3.amazonaws.com:563/echo.api/echo-api-cert.pem", "https://s3.amazonaws.com/echo.api/../evil/x.pem"]
    for u in ok:
        alexa.check_cert_url(u)
    for u in bad:
        with pytest.raises(alexa.Invalid):
            alexa.check_cert_url(u)


def test_signature_timestamp_and_skill(monkeypatch):
    monkeypatch.setenv("HELPER_ALEXA_SKILL_ID", SKILL)
    key, cert = _cert()
    req = _req("LaunchRequest")
    body = json.dumps(req).encode()
    sig = base64.b64encode(key.sign(body, padding.PKCS1v15(), hashes.SHA256())).decode()
    h = {"signaturecertchainurl": "https://s3.amazonaws.com/echo.api/echo-api-cert.pem", "signature-256": sig}
    fetch, trust = (lambda url: [cert]), (lambda chain: None)
    alexa.verify(h, body, req, fetch=fetch, chain_check=trust)                       # good
    with pytest.raises(alexa.Invalid):                                               # body changed after signing
        alexa.verify(h, body.replace(b"Launch", b"Intent"), req, fetch=fetch, chain_check=trust)
    with pytest.raises(alexa.Invalid):                                               # someone else's key
        k2, _ = _cert()
        bad = base64.b64encode(k2.sign(body, padding.PKCS1v15(), hashes.SHA256())).decode()
        alexa.verify({**h, "signature-256": bad}, body, req, fetch=fetch, chain_check=trust)
    old = _req("LaunchRequest", ts="2026-01-01T00:00:00Z")
    with pytest.raises(alexa.Invalid, match="too old"):
        alexa.check_request(old, SKILL)
    with pytest.raises(alexa.Invalid, match="wrong skill"):
        alexa.check_request(_req("LaunchRequest", skill="amzn1.ask.skill.other"), SKILL)
    with pytest.raises(alexa.Invalid, match="not trusted"):                          # a self-signed cert isn't Amazon's
        alexa.check_chain([cert])


def test_link_and_ask(server, monkeypatch):
    from lilhelper import api
    monkeypatch.setenv("HELPER_ALEXA_SKILL_ID", SKILL)
    monkeypatch.setenv("HELPER_ALEXA_VERIFY", "0")
    c = server.client
    H, _ = server.household()
    c.post("/api/week/draft", headers=H, json={"week": W})
    c.post("/api/week/approve", headers=H, json={"week": W, "seconds": 5})
    monkeypatch.setattr(api.week, "today_in", lambda h: dt.date(2026, 10, 21))
    ask = lambda req: c.post("/alexa", json=req).json()["response"]   # noqa: E731

    # not linked yet → a LinkAccount card
    r = ask(_req(intent=_intent("WhatsForIntent", meal="dinner")))
    assert r["card"]["type"] == "LinkAccount"

    # linking: the page only works for Amazon's redirect addresses; the code works once
    assert c.get("/alexa/link", params={"redirect_uri": "https://evil.example/api/skill/link/x", "state": "s",
                                        "response_type": "token"}).status_code == 400
    page = c.get("/alexa/link", params={"redirect_uri": REDIRECT, "state": "st8", "response_type": "token"})
    assert page.status_code == 200 and "Get a code" in page.text
    code = c.post("/api/alexa/code", headers=H).json()["code"]
    assert c.post("/alexa/link", data={"code": "WRONG123", "state": "st8", "redirect_uri": REDIRECT}).status_code == 400
    back = c.post("/alexa/link", data={"code": code.lower(), "state": "st8", "redirect_uri": REDIRECT},
                  follow_redirects=False)
    assert back.status_code == 302 and back.headers["location"].startswith(REDIRECT + "#")
    frag = parse_qs(urlparse(back.headers["location"]).fragment)
    assert frag["state"] == ["st8"] and frag["token_type"] == ["Bearer"]
    token = frag["access_token"][0]
    assert c.post("/alexa/link", data={"code": code, "state": "s", "redirect_uri": REDIRECT}).status_code == 400  # used
    assert len(c.get("/api/alexa", headers=H).json()["links"]) == 1

    r = ask(_req("LaunchRequest", token=token))
    assert r["shouldEndSession"] is False and "Lil'Helper" in r["outputSpeech"]["text"]
    r = ask(_req(intent=_intent("WhatsForIntent", meal="dinner"), token=token))
    assert r["outputSpeech"]["text"].startswith("Dinner today is")
    r = ask(_req(intent=_intent("CookWithIntent", items="half a chicken, rice and broccoli"), token=token))
    assert "How about" in r["outputSpeech"]["text"]
    r = ask(_req(intent=_intent("ShoppingIntent"), token=token))
    assert "things from" in r["outputSpeech"]["text"]
    r = ask(_req(intent=_intent("RateIntent", meal="dinner", stars="5"), token=token))
    assert r["outputSpeech"]["text"].startswith("Thanks")
    assert ask(_req(intent=_intent("AMAZON.StopIntent"), token=token))["outputSpeech"]["text"] == "Bye!"
    assert c.post("/alexa", json=_req("SessionEndedRequest", token=token)).json()["response"] == {}

    # wrong skill id is refused even in local mode; unlinking stops it working
    assert c.post("/alexa", json=_req("LaunchRequest", token=token, skill="amzn1.other")).status_code == 400
    assert c.request("DELETE", "/api/alexa", headers=H).json()["removed"] == 1
    assert ask(_req("LaunchRequest", token=token))["card"]["type"] == "LinkAccount"


def test_verification_is_on_by_default(server, monkeypatch):
    monkeypatch.setenv("HELPER_ALEXA_SKILL_ID", SKILL)
    monkeypatch.delenv("HELPER_ALEXA_VERIFY", raising=False)
    r = server.client.post("/alexa", json=_req("LaunchRequest"))
    assert r.status_code == 400 and "certificate URL" in r.json()["detail"]
