"""The verifier: everything a draft must pass before it can be published.

    schema → content → learning fields → data allow-list → de-duplication → proof by code (formal kinds)
           → reference code reproduces the key (code kinds) → blind solver agrees and finds no other answer

The report records each step's result and reason but never the answer itself, so it can be stored and shown to the
operator without leaking the key.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy import select

from . import assets, grading, llm, puzzles, sandbox
from .config import Settings
from .schemas import Draft, SolverReply
from .store import ai_calls, now, puzzles as puzzles_t, sandbox_runs


@dataclass
class Ctx:
    s: Settings
    client: llm.LLMClient
    conn: object = None                   # SQLAlchemy connection (None in some evals: nothing is logged)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    purpose: str = "daily"
    history: list[dict] = field(default_factory=list)   # extra past puzzles for de-duplication (evals)
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    calls: int = 0
    models: set = field(default_factory=set)


def make_client(s: Settings, max_usd: float | None = None) -> llm.LLMClient:
    reg = llm.Registry(s.models_path)
    c = s["cost"]
    return llm.LLMClient(reg, llm.Budget(max_usd if max_usd is not None else c["max_usd_per_run"],
                                         c["max_input_tokens_per_call"], c.get("allow_unpriced_models", False)),
                         retries=s["llm"]["retries"])


def prompt(s: Settings, key: str) -> tuple[str, str]:
    """(text, sha) of a versioned prompt file (MODEL-04)."""
    text = s.path(s["llm"][key]).read_text()
    return text, hashlib.sha256(text.encode()).hexdigest()[:12]


def call_model(ctx: Ctx, role: str, alias: str, system: str, user: str, prompt_sha: str) -> llm.LLMResult:
    """One logged model call (OBS-01, COST-02). Fallback alias on provider failure (MODEL-05)."""
    from . import telemetry
    telemetry.require_enabled(role)
    t0 = time.perf_counter()
    status, res = "ok", None
    try:
        res = ctx.client.complete(alias, system, user, ctx.s["llm"]["max_output_tokens"],
                                  fallback_alias=ctx.s["llm"]["fallback_alias"] if role == "generator" else None)
        return res
    except llm.BudgetExceeded:
        status = "budget_blocked"
        raise
    except Exception:
        status = "error"
        raise
    finally:
        if res:
            ctx.tokens_in += res.input_tokens
            ctx.tokens_out += res.output_tokens
            ctx.cost += res.cost_usd
            ctx.calls += 1
            ctx.models.add(res.model.name)
        if ctx.conn is not None:
            ctx.conn.execute(ai_calls.insert().values(
                run_id=ctx.run_id, role=role, purpose=ctx.purpose, alias=alias,
                model=res.model.name if res else ctx.client.registry.name_of(alias), prompt_sha=prompt_sha,
                input_sha=hashlib.sha256(user.encode()).hexdigest()[:16],
                input_tokens=res.input_tokens if res else 0, output_tokens=res.output_tokens if res else 0,
                cost_usd=res.cost_usd if res else 0.0, latency_ms=int((time.perf_counter() - t0) * 1000),
                status=status, used_fallback=bool(res and res.used_fallback), at=now()))


def run_code(ctx: Ctx, who: str, code: str, refs: list[dict]) -> sandbox.Result:
    res = sandbox.run(code, refs, cfg=ctx.s.puzzles.get("sandbox", {}))
    if ctx.conn is not None:
        ctx.conn.execute(sandbox_runs.insert().values(
            run_id=ctx.run_id, who=who, code_sha=sandbox.sha(code), ok=res.ok, seconds=res.seconds,
            violation=(res.problem or None) if not res.ok or res.violations else None,
            output_sha=sandbox.sha(res.answer), at=now()))
    return res


# ---------------------------------------------------------------- individual checks
def norm_text(t: str) -> str:
    return re.sub(r"\s+", " ", t.lower()).strip()


def fingerprints(d: dict) -> tuple[str, str]:
    """(statement hash, content hash): the same wording, or the same structured puzzle / program, is a repeat."""
    st = hashlib.sha256(norm_text(d["statement"]).encode()).hexdigest()
    spec = {k: v for k, v in (d.get("spec") or {}).items() if k != "solver_code"}
    body = json.dumps(spec, sort_keys=True) if spec else norm_text(d.get("reference_code") or d["statement"])
    return st, hashlib.sha256(f"{d['kind']}|{body}".encode()).hexdigest()


def content_problems(d: dict, s: Settings) -> list[str]:
    cfg = s["content"]
    text = " ".join([d["title"], d["statement"], d.get("solution", ""), d.get("starter", "")])
    out = []
    terms = [l.strip().lower() for l in s.path(cfg["blocked_terms_file"]).read_text().splitlines()
             if l.strip() and not l.startswith("#")]
    hits = [t for t in terms if re.search(rf"\b{re.escape(t)}\b", text, re.I)]
    if hits:
        out.append(f"content policy: blocked term(s) ({len(hits)})")      # not echoed: the term itself may be abusive
    for q in re.findall(r"[\"“]([^\"”]{20,})[\"”]", d["statement"]):
        if len(q.split()) > cfg["max_quoted_words"]:
            out.append(f"content policy: a {len(q.split())}-word quotation looks copied from published text")
    if len(d["statement"]) > cfg["max_statement_chars"]:
        out.append("statement too long")
    return out


def learning_problems(d: dict, s: Settings) -> list[str]:
    cfg = s.puzzles["learning"]
    out = []
    if d["track"] in cfg["require_objective_for"]:
        if len(d.get("learning_objective", "").strip()) < 15:
            out.append("coding / AI puzzles must state a learning objective")
        if len(d.get("skill_tags") or []) < cfg["min_skill_tags"]:
            out.append("coding / AI puzzles need skill tags")
    if cfg.get("require_worked_solution") and len(d.get("solution", "").strip()) < 15:
        out.append("no worked solution")
    if puzzles.KINDS.get(d["kind"], {}).get("sandbox") and not d.get("reference_code", "").strip():
        out.append("code kinds need reference code that prints the answer")
    return out


def duplicate_problems(d: dict, ctx: Ctx) -> list[str]:
    st, fp = fingerprints(d)
    for h in ctx.history:
        if fingerprints(h) in ((st, fp),) or fingerprints(h)[0] == st or fingerprints(h)[1] == fp:
            return ["repeat of an earlier puzzle"]
    if ctx.conn is not None:
        from datetime import timedelta
        since = now() - timedelta(days=int(ctx.s.puzzles["generation"]["dedup_days"]))
        hit = ctx.conn.execute(select(puzzles_t.c.id).where(
            (puzzles_t.c.statement_hash == st) | (puzzles_t.c.answer_fingerprint == fp),
            # a pack is regenerated from its seed, so packs don't block each other; daily puzzles avoid packs too
            puzzles_t.c.status.notin_(("rejected", "escalated", "pack") if ctx.purpose == "pack" else ("rejected", "escalated")),
            puzzles_t.c.created_at >= since)).first()
        if hit:
            return [f"repeat of puzzle #{hit[0]}"]
    return []


def public_view(d: dict, for_mock: bool) -> dict:
    """What the solver (and a player) is allowed to see. Never the key, solution or reference code."""
    spec = dict(d.get("spec") or {})
    if not for_mock:
        spec.pop("solver_code", None)
    return {"track": d["track"], "kind": d["kind"], "difficulty": d["difficulty"], "title": d["title"],
            "statement": d["statement"], "answer_format": d.get("answer_format", ""), "starter": d.get("starter", ""),
            "assets": d.get("assets", []), "spec": spec}


# ---------------------------------------------------------------- the whole verification
@dataclass
class Report:
    decision: str = "REJECT"              # PUBLISH | REJECT
    steps: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    solver_model: str = ""

    def step(self, name: str, ok: bool, detail: str = "") -> bool:
        self.steps.append({"step": name, "ok": ok, "detail": detail})
        if not ok:
            self.reasons.append(f"{name}: {detail}")
        return ok

    def as_dict(self) -> dict:
        return {"decision": self.decision, "steps": self.steps, "reasons": self.reasons, "flags": self.flags,
                "solver_model": self.solver_model}


def verify(raw: dict | str, ctx: Ctx) -> tuple[dict | None, Report]:
    rep = Report()
    s = ctx.s
    # 1. schema (SEC-04)
    try:
        data = llm.extract_json(raw) if isinstance(raw, str) else raw
        d = Draft.model_validate(data).model_dump()
    except (ValueError, ValidationError) as e:
        rep.step("schema", False, f"invalid draft ({str(e).splitlines()[0][:160]})")
        rep.flags.append("schema_invalid")
        return None, rep
    rep.step("schema", True)
    kind = puzzles.KINDS.get(d["kind"])
    if not kind or kind["track"] != d["track"]:
        rep.step("kind", False, f"unknown kind {d['kind']} for track {d['track']}")
        return d, rep
    # 2. content, learning, data, repeats
    ok = rep.step("content", not (p := content_problems(d, s)), "; ".join(p))
    if not ok:
        rep.flags.append("content_policy")
    rep.step("learning", not (p := learning_problems(d, s)), "; ".join(p))
    if not rep.step("data", not (p := assets.check(d["assets"], s)), "; ".join(p)):
        rep.flags.append("data_rights")
    rep.step("repeat", not (p := duplicate_problems(d, ctx)), "; ".join(p))
    if rep.reasons:
        return d, rep
    key = d["answer"]
    same = lambda a: grading.same_answer(a, key, d["answer_type"], d["decimals"])   # noqa: E731
    # 3. proof by code (formal kinds): exactly one solution, and it is the key
    if kind.get("check"):
        try:
            sols = kind["check"](d["spec"])
        except Exception as e:  # noqa: BLE001
            rep.step("proof", False, f"spec can't be checked by code ({type(e).__name__})")
            return d, rep
        if len(sols) != 1:
            rep.step("proof", False, f"{len(sols)} solutions found by exhaustive search (need exactly 1)")
            rep.flags.append("ambiguous" if len(sols) > 1 else "unsolvable")
            return d, rep
        if not same(sols[0]):
            rep.step("proof", False, "the key does not satisfy the clues")
            rep.flags.append("wrong_key")
            return d, rep
        rep.step("proof", True, "exhaustive search: exactly one solution, equal to the key")
    # 4. reference code reproduces the key (code kinds)
    if kind.get("sandbox"):
        runs = int(s.puzzles["sandbox"].get("reproducibility_runs", 2))
        outs = []
        for _ in range(runs):
            r = run_code(ctx, "reference", d["reference_code"], d["assets"])
            if r.violations:
                rep.flags.append("sandbox_violation")
            if r.problem:
                rep.step("reference", False, r.problem)
                return d, rep
            outs.append(r.answer)
        if len({grading.normalize(o, d["answer_type"], d["decimals"]) for o in outs}) > 1:
            rep.step("reference", False, f"not reproducible: {runs} runs gave different results")
            rep.flags.append("nondeterministic")
            return d, rep
        if not same(outs[0]):
            rep.step("reference", False, "reference code prints a different answer than the key")
            rep.flags.append("wrong_key")
            return d, rep
        rep.step("reference", True, f"{runs} sandbox runs, same result, equal to the key")
    # 5. blind solver (a different model; sees only the public puzzle)
    alias = s["llm"]["solver_alias"]
    spec = ctx.client.registry.resolve(alias)
    rep.solver_model = spec.name
    system, sha = prompt(s, "solver_prompt")
    user = f"<puzzle>{json.dumps(public_view(d, spec.provider == 'mock'))}</puzzle>"
    try:
        res = call_model(ctx, "solver", alias, system, user, sha)
        reply = SolverReply.model_validate(llm.extract_json(res.text))
    except llm.BudgetExceeded as e:
        rep.step("solver", False, f"budget: {e}")
        rep.flags.append("budget")
        return d, rep
    except (ValueError, ValidationError) as e:
        rep.step("solver", False, f"solver reply invalid ({str(e).splitlines()[0][:120]})")
        return d, rep
    got = reply.answer or ""
    if reply.code:
        r = run_code(ctx, "solver", reply.code, d["assets"])
        if r.problem:
            rep.step("solver", False, f"solver's code {r.problem}")
            return d, rep
        got = r.answer
    if not same(got):
        rep.step("solver", False, "the independent solver reached a different answer (ambiguous puzzle or wrong key)")
        rep.flags.append("solver_disagrees")
        return d, rep
    others = [a for a in reply.other_valid_answers if a and not same(a)]
    if others:
        rep.step("solver", False, f"the solver found {len(others)} other valid answer(s)")
        rep.flags.append("ambiguous")
        return d, rep
    rep.step("solver", True, f"{spec.name} reached the same answer independently"
             + (" by writing and running its own code" if reply.code else ""))
    rep.decision = "PUBLISH"
    return d, rep
