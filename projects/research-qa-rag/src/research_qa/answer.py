"""Answer a question: entitlements → retrieve → model (by alias, within budget) → verify → log.

The model only drafts. Code decides whether the draft is shown: every citation must quote a retrieved
excerpt word for word, the answer must be supported by those quotes, and anything that fails is turned into
a refusal with the reason recorded (OBS-02, SEC-04).
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

from . import guardrails as G
from . import telemetry
from .ingest import active_index
from .llm import Budget, BudgetExceeded, LLMClient, Registry, RegistryError
from .retrieve import retrieve
from .store import ROOT, Settings, connect, users


class IndexMismatch(RuntimeError):
    pass


def prompt(settings: Settings) -> tuple[str, str]:
    path = ROOT / settings["llm"]["prompt_file"]
    text = path.read_text()
    return text, hashlib.sha256(text.encode()).hexdigest()[:16]


def _esc(s: str) -> str:
    return s.replace("<", "&lt;").replace(">", "&gt;").replace('"', "'")


def build_user_prompt(question: str, chunks: list[dict]) -> str:
    ex = "\n".join(f'<excerpt id="{c["chunk_id"]}" meta="{_esc(c["company"])} · {_esc(c["source"])} · '
                   f'{_esc(c["title"])} · page {c["page"]}">{_esc(c["text"])}</excerpt>' for c in chunks)
    return f"<question>{_esc(question)}</question>\n<excerpts>\n{ex}\n</excerpts>"


def ask(settings: Settings, question: str, user_id: str, alias: str | None = None, mode: str | None = None,
        top_k: int | None = None, actor: str = "", run_id: str = "", action: str = "ask") -> dict:
    t0 = time.perf_counter()
    telemetry.require_enabled(action, actor or user_id)
    alias = alias or settings["llm"]["primary_alias"]
    people = users(settings)
    if user_id not in people:
        raise KeyError(f"Unknown user '{user_id}'")
    ents = people[user_id]["entitlements"]
    reg = Registry(ROOT / "config" / "models.yaml")
    con = connect(settings)
    try:
        idx = active_index(con)
        if not idx:
            raise IndexMismatch("No index yet: run `rqa ingest`")
        emb = reg.resolve(settings["llm"]["embedding_alias"])
        if idx["embedding_model"] != emb.name:
            raise IndexMismatch(f"Index {idx['index_version']} was built with {idx['embedding_model']} but "
                                f"{settings['llm']['embedding_alias']} is now {emb.name}: re-index first (`rqa ingest`)")
        ret = retrieve(con, question, ents, settings, reg, mode, top_k)
        system, prompt_sha = prompt(settings)
        res = {"answer_id": uuid.uuid4().hex[:12], "question": question, "user_id": user_id, "status": "refused",
               "answer": "", "refusal_reason": "", "citations": [], "flags": [], "context": ret.chunks,
               "trace": ret.trace, "excluded_entitlement": ret.excluded_entitlement,
               "excluded_licence": ret.excluded_licence, "runtime_dropped": ret.dropped_runtime,
               "index_version": idx["index_version"], "embedding_model": emb.name,
               "retrieval_mode": mode or settings["retrieval"]["mode"], "top_k": top_k or settings["retrieval"]["top_k"],
               "model_name": "", "model_id": "", "prompt_sha": prompt_sha, "input_tokens": 0, "output_tokens": 0,
               "cost_usd": 0.0, "supported_ratio": None, "citations_verified": 0, "used_fallback": False,
               "support": []}
        if ret.dropped_runtime:
            res["flags"].append("injection_text_dropped")
        if not ret.chunks:
            res["refusal_reason"] = "No documents you have access to match this question."
            res["flags"].append("no_evidence")
        else:
            c = settings["cost"]
            client = LLMClient(reg, Budget(c["max_usd_per_question"], c["max_input_tokens_per_call"],
                                           c["allow_unpriced_models"]), settings["llm"]["retries"])
            try:
                out = client.complete(alias, system, build_user_prompt(question, ret.chunks),
                                      settings["llm"]["max_output_tokens"], settings["llm"]["fallback_alias"])
                res.update(model_name=out.model.name, model_id=out.model.model_id, input_tokens=out.input_tokens,
                           output_tokens=out.output_tokens, cost_usd=out.cost_usd, used_fallback=out.used_fallback)
                _check(res, out.text, ret.chunks, settings)
            except (BudgetExceeded, RegistryError) as e:
                res["refusal_reason"] = f"Not run: {e}"
                res["flags"].append("blocked")
        res["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        if res["status"] == "refused" and ret.excluded_entitlement:
            res["flags"].append("entitlement_filtered")
        if ret.excluded_licence:
            res["flags"].append("licence_filtered")
            if res["status"] == "refused":   # the user may open these documents; only AI processing is barred
                res["refusal_reason"] += (" Matching passages exist in documents you can open, but their licence forbids"
                                          " AI processing — read them directly.")
        _log(con, res, run_id)
    finally:
        con.close()
    telemetry.record(action, actor=actor or user_id, status=res["status"], run_id=run_id or res["answer_id"],
                     model=res["model_name"], input_tokens=res["input_tokens"], output_tokens=res["output_tokens"],
                     cost_usd=res["cost_usd"], latency_ms=res["latency_ms"], items=1, rows_in=len(res["context"]),
                     flags=res["flags"] + ([f"refused"] if res["status"] == "refused" else []),
                     detail={"question_sha": telemetry.sha(question), "user": user_id,
                             "index_version": res["index_version"], "retrieval_mode": res["retrieval_mode"]})
    return res


def _check(res: dict, text: str, chunks: list[dict], settings: Settings) -> None:
    """Turn the model's draft into an answer only if it parses, cites retrieved text verbatim and is supported."""
    try:
        ans = G.parse_answer(text)
    except Exception as e:  # SEC-04: off-contract output is never shown
        res["refusal_reason"], res["flags"] = f"Model output failed validation ({type(e).__name__})", res["flags"] + ["invalid_output"]
        return
    if ans.refused:
        res["refusal_reason"] = ans.refusal_reason or "The documents available to you do not answer this question."
        res["flags"].append("model_refused")
        return
    by_id = {c["chunk_id"]: c for c in chunks}
    checks = G.verify_citations(ans, {k: v["text"] for k, v in by_id.items()})
    verified = [c for c in checks if c["verbatim"]]
    ratio, support = G.supported_ratio(ans.answer, [c["quote"] for c in verified])
    res.update(supported_ratio=round(ratio, 3), citations_verified=len(verified), support=support)
    res["citations"] = [{**c, "doc_id": by_id.get(c["chunk_id"], {}).get("doc_id"),
                         "title": by_id.get(c["chunk_id"], {}).get("title"),
                         "page": by_id.get(c["chunk_id"], {}).get("page"),
                         "section": by_id.get(c["chunk_id"], {}).get("section")} for c in checks]
    if G.scan_injection(ans.answer):
        res["refusal_reason"], res["flags"] = "Answer contained instruction-like text", res["flags"] + ["output_injection"]
    elif settings["answer"]["require_citation"] and not verified:
        res["refusal_reason"], res["flags"] = "No citation matched the retrieved text", res["flags"] + ["unverified"]
    elif ratio < settings["answer"]["min_supported_ratio"]:
        res["refusal_reason"] = f"Only {ratio:.0%} of the answer is supported by its citations"
        res["flags"].append("unsupported")
    else:
        res.update(status="answered", answer=ans.answer)
        if len(verified) < len(checks):
            res["flags"].append("dropped_bad_citation")
            res["citations"] = [c for c in res["citations"] if c["verbatim"]]


def _log(con, res: dict, run_id: str) -> None:
    con.execute("""insert into answers values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (res["answer_id"], datetime.now(timezone.utc).isoformat(timespec="seconds"), run_id, res["user_id"],
                 telemetry.sha(res["question"]), res["question"], res["status"], res["refusal_reason"], res["answer"],
                 json.dumps(res["citations"]), res["model_name"], res["model_id"], res["prompt_sha"],
                 res["index_version"], res["embedding_model"], res["retrieval_mode"], res["top_k"],
                 json.dumps([c["chunk_id"] for c in res["context"]]), res["excluded_entitlement"],
                 res["excluded_licence"], res["input_tokens"], res["output_tokens"], res["cost_usd"], res["latency_ms"],
                 res["supported_ratio"], res["citations_verified"], json.dumps(res["flags"]), int(res["used_fallback"])))
    con.commit()


def record_feedback(settings: Settings, answer_id: str, user_id: str, rating: str, note: str = "") -> None:
    """HITL-03: analysts mark answers useful / wrong; wrong answers become golden-set candidates."""
    con = connect(settings)
    try:
        con.execute("insert into feedback values (?,?,?,?,?)",
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"), answer_id, user_id, rating, note))
        con.commit()
    finally:
        con.close()
    telemetry.record("feedback", event_type="feedback", actor=user_id, status=rating, detail={"answer_id": answer_id})
