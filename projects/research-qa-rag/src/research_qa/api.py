"""FastAPI service: the same ask() the app and CLI use, behind HTTP.

Run: `rqa serve` (uvicorn on :8000, OpenAPI docs at /docs).
Identity: the demo takes X-User-Id from a fixed list of personas. In production the user and their
entitlements come from the SSO token (IAM Identity Center / Entra ID groups), never from the request body.
"""
from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import telemetry
from .answer import IndexMismatch, ask, record_feedback
from .ingest import active_index
from .store import Settings, connect, users

app = FastAPI(title="Research Q&A", version="0.1.0",
              description="Cited answers over filings and entitled broker research. Refuses when unsupported.")


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    retrieval_mode: str | None = Field(default=None, pattern="^(hybrid|bm25|vector)$")


class FeedbackIn(BaseModel):
    answer_id: str
    rating: str = Field(pattern="^(useful|wrong)$")
    note: str = Field(default="", max_length=500)


def _user(x_user_id: str | None) -> str:
    s = Settings.load()
    if not x_user_id or x_user_id not in users(s):
        raise HTTPException(401, f"Set X-User-Id to one of {sorted(users(s))}")
    return x_user_id


@app.get("/health")
def health():
    s = Settings.load()
    con = connect(s)
    try:
        idx = active_index(con)
    finally:
        con.close()
    enabled, reason = telemetry.status()
    return {"ok": bool(idx) and enabled, "index_version": idx and idx["index_version"], "enabled": enabled,
            "disabled_reason": reason}


@app.post("/ask")
def ask_endpoint(body: AskIn, x_user_id: str | None = Header(default=None)):
    user = _user(x_user_id)
    try:
        r = ask(Settings.load(), body.question, user, mode=body.retrieval_mode, actor=user)
    except telemetry.WorkflowDisabled as e:
        raise HTTPException(503, str(e))
    except IndexMismatch as e:
        raise HTTPException(409, str(e))
    return {k: r[k] for k in ("answer_id", "status", "answer", "refusal_reason", "flags", "index_version",
                              "model_name", "latency_ms", "cost_usd")} | {
        "citations": [{k: c[k] for k in ("doc_id", "title", "page", "section", "quote")} for c in r["citations"]]}


@app.get("/documents")
def documents(x_user_id: str | None = Header(default=None)):
    """Documents this user may see (entitlement filter), with licence status."""
    s = Settings.load()
    ents = users(s)[_user(x_user_id)]["entitlements"]
    con = connect(s)
    try:
        marks = ",".join("?" * len(ents))
        rows = con.execute(f"""select doc_id, title, company, doc_type, published, entitlement, ai_processing, pages
                               from documents where entitlement in ({marks}) order by company, published""", ents)
        return [dict(r) for r in rows]
    finally:
        con.close()


@app.post("/feedback")
def feedback(body: FeedbackIn, x_user_id: str | None = Header(default=None)):
    record_feedback(Settings.load(), body.answer_id, _user(x_user_id), body.rating, body.note)
    return {"recorded": True}
