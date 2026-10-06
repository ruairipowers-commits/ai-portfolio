"""REST API (FastAPI): the catalog for operators, and each buyer firm's own view.

Auth: bearer tokens. `dlp api-token <customer_id>` issues a firm's token; `dlp api-token operator` the operator's.
A firm's identity comes only from its token, so `/me/...` can never return another firm's rows (NFR-3).
Writes to the catalog and decisions on approvals are operator-only; decisions need a named reviewer (HITL-02).
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import date

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import select

from . import catalog, commerce, context, licensing, pipeline, search, store
from .config import Settings

app = FastAPI(title="Data lifecycle platform", version="0.1.0")
OPERATOR = "operator"


def _secret() -> bytes:
    s = os.getenv("DLP_TOKEN_SECRET")
    if not s:
        if os.getenv("PORTFOLIO_DEMO") == "1":
            raise RuntimeError("DLP_TOKEN_SECRET must be set")
        s = "local-dev-only"                      # SEC-01: never used when a secret is configured
    return s.encode()


def issue_token(principal: str) -> str:
    return principal + "." + hmac.new(_secret(), principal.encode(), hashlib.sha256).hexdigest()[:32]


def principal(authorization: str = Header(default="")) -> str:
    tok = authorization.removeprefix("Bearer ").strip()
    who, _, sig = tok.rpartition(".")
    if not who or not hmac.compare_digest(issue_token(who), tok):
        raise HTTPException(401, "invalid token")
    return who


def operator(who: str = Depends(principal)) -> str:
    if who != OPERATOR:
        raise HTTPException(403, "operator only")
    return who


def customer(who: str = Depends(principal)) -> str:
    if who == OPERATOR:
        raise HTTPException(403, "use a customer token for /me")
    return who


S = Settings.load


@app.get("/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------------- catalog (everyone reads; operator writes)
@app.get("/vendors")
def list_vendors(_: str = Depends(principal)):
    with store.session(S()) as s:
        return store.rows(s.exec(select(store.Vendor)).all())


@app.get("/vendors/{vid}")
def get_vendor(vid: str, _: str = Depends(principal)):
    with store.session(S()) as s:
        v = s.get(store.Vendor, vid)
        if not v:
            raise HTTPException(404)
        return v


@app.put("/vendors/{vid}")
def put_vendor(vid: str, body: dict, who: str = Depends(operator)):
    with store.session(S()) as s:
        try:
            return catalog.upsert_vendor(s, {**body, "id": vid}, actor=who)
        except ValueError as e:
            raise HTTPException(422, str(e))


@app.delete("/vendors/{vid}")
def delete_vendor(vid: str, _: str = Depends(operator)):
    with store.session(S()) as s:
        try:
            catalog.delete(s, "vendor", vid)
        except (KeyError, ValueError) as e:
            raise HTTPException(409, str(e))
    return {"deleted": vid}


@app.get("/datasets")
def list_datasets(_: str = Depends(principal)):
    with store.session(S()) as s:
        return store.rows(s.exec(select(store.Dataset)).all())


@app.get("/datasets/{did}")
def get_dataset(did: str, _: str = Depends(principal)):
    with store.session(S()) as s:
        d = s.get(store.Dataset, did)
        if not d:
            raise HTTPException(404)
        return d


@app.put("/datasets/{did}")
def put_dataset(did: str, body: dict, who: str = Depends(operator)):
    body.pop("licence", None)            # the licence tag changes only through POST /datasets/{id}/licence
    with store.session(S()) as s:
        try:
            return catalog.upsert_dataset(s, {**body, "id": did}, actor=who)
        except ValueError as e:
            raise HTTPException(422, str(e))


class LicenceBody(BaseModel):
    licence: str
    set_by: str


@app.post("/datasets/{did}/licence")
def set_licence(did: str, body: LicenceBody, _: str = Depends(operator)):
    with store.session(S()) as s:
        return catalog.set_licence(s, did, body.licence, body.set_by)


@app.delete("/datasets/{did}")
def delete_dataset(did: str, _: str = Depends(operator)):
    with store.session(S()) as s:
        try:
            catalog.delete(s, "dataset", did)
        except (KeyError, ValueError) as e:
            raise HTTPException(409, str(e))
    return {"deleted": did}


class FieldDef(BaseModel):
    entity: str
    key: str
    label: str
    type: str
    options: list = []
    bind_to: str | None = None


@app.post("/custom-fields")
def add_field(f: FieldDef, _: str = Depends(operator)):
    with store.session(S()) as s:
        try:
            return catalog.define_custom_field(s, f.entity, f.key, f.label, f.type, f.options, f.bind_to)
        except ValueError as e:
            raise HTTPException(422, str(e))


# ---------------------------------------------------------------- approvals (operator)
@app.get("/approvals")
def approvals(_: str = Depends(operator)):
    with store.session(S()) as s:
        return store.rows(catalog.pending(s))


class Decision(BaseModel):
    reviewer: str
    approve: bool
    note: str = ""


@app.post("/approvals/{aid}/decide")
def decide(aid: str, d: Decision, _: str = Depends(operator)):
    try:
        a = catalog.decide(S(), aid, d.reviewer, d.approve, d.note)
    except ValueError as e:
        raise HTTPException(422, str(e))
    pipeline.refresh_graph(S())
    return {"id": a.id, "status": a.status, "decided_by": a.decided_by}


# ---------------------------------------------------------------- a firm's own view
@app.get("/me/contracts")
def my_contracts(cid: str = Depends(customer)):
    return commerce.contracts_for(S(), cid)


@app.get("/me/entitlements")
def my_entitlements(cid: str = Depends(customer)):
    with store.session(S()) as s:
        return [v.__dict__ for v in licensing.entitlements(s, S(), cid)]


class Registration(BaseModel):
    dataset_id: str
    uses: list[str] = ["v:InternalResearch"]
    actor: str


@app.post("/me/registrations")
def register(r: Registration, cid: str = Depends(customer)):
    try:
        return commerce.register(S(), cid, r.dataset_id, r.uses, r.actor)
    except (ValueError, KeyError) as e:
        raise HTTPException(422, str(e))


class Subscription(BaseModel):
    dataset_ids: list[str]
    start: date
    end: date
    price_usd: float
    permitted_use: list[str]
    actor: str
    notice_days: int = 30
    auto_renew: bool = False


@app.post("/me/subscriptions")
def subscribe(b: Subscription, cid: str = Depends(customer)):
    try:
        return commerce.subscribe(S(), cid, b.dataset_ids, b.start, b.end, b.price_usd, b.permitted_use, b.actor,
                                  b.notice_days, b.auto_renew)
    except (ValueError, KeyError) as e:
        raise HTTPException(422, str(e))


@app.get("/me/search")
def my_search(q: str, cid: str = Depends(customer)):
    return search.run(S(), q, cid, actor=cid)


class Question(BaseModel):
    question: str


@app.post("/me/ask")
def ask(q: Question, cid: str = Depends(customer)):
    r = context.answer(S(), q.question, cid, actor=cid)
    return {"status": r.status, "answer": r.answer, "citations": r.citations, "checks": r.checks}


@app.get("/me/datasets/{did}/download")
def download(did: str, cid: str = Depends(customer)):
    try:
        commerce.check_entitled(S(), cid, did)
    except commerce.NotEntitled as e:
        raise HTTPException(403, str(e))
    files = {"ds-options-iv": "options_iv.parquet", "ds-constituents": "constituents.parquet"}
    if did not in files:
        raise HTTPException(404, "No delivery file held for this dataset; use a feed")
    return FileResponse(S().path("landing") / files[did], filename=files[did])
