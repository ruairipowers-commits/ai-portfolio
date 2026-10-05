"""The pipeline: ingest → detect (code) → disambiguate (model, only the unclear hits) → score (code) →
coach + rewrite (model) → guard (code) → report.

If a model is unavailable, over budget or switched off, the run still finishes in an explicit degraded mode:
counts and grade are complete, unclear hits stay "disputed", and coaching says it was skipped (MODEL-05).
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from . import lexicon as lexmod
from . import privacy, rewrite, score as scoremod, store, telemetry
from .detect import Hit, detect
from .ingest import Transcript
from .llm import Budget, BudgetExceeded, LLMClient, Registry
from .text import tokenize

ROOT = store.ROOT


# ---------------------------------------------------------------- model output schemas (SEC-04)
class Verdict(BaseModel):
    id: str
    is_filler: bool
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(default="", max_length=200)


class Verdicts(BaseModel):
    verdicts: list[Verdict]


class Pattern(BaseModel):
    title: str = Field(max_length=120)
    where: str = Field(default="", max_length=200)
    tip: str = Field(max_length=300)


class Rewrite(BaseModel):
    passage_id: str
    rewrite: str = Field(max_length=4000)
    note: str = Field(default="", max_length=200)


class CoachOut(BaseModel):
    patterns: list[Pattern] = Field(default_factory=list, max_length=3)
    rewrites: list[Rewrite] = Field(default_factory=list)


# ---------------------------------------------------------------- result
@dataclass
class Result:
    run_id: str
    text: str
    hits: list[Hit]
    score: scoremod.Score
    lexicon: lexmod.Lexicon
    speaker: str = ""
    spans: list = field(default_factory=list)
    patterns: list[dict] = field(default_factory=list)
    rewrites: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    injection: list[str] = field(default_factory=list)
    model_payloads: list[str] = field(default_factory=list)   # in memory only, for the privacy test; never saved

    @property
    def cost_usd(self) -> float:
        return round(sum(c["cost_usd"] for c in self.calls), 6)


@dataclass
class Options:
    presets: list[str] | None = None
    custom_words: str | None = None
    ignore: list[str] | None = None
    repetition: bool | None = None
    speaker: str | None = None
    target: float | None = None
    disambiguator_alias: str | None = None
    coach_alias: str | None = None
    names: list[str] | None = None
    decisions: dict[str, str] = field(default_factory=dict)    # hit id → filler | not_filler (the speaker's call)
    coach: bool = True
    save_history: bool | None = None


def build_lexicon(s: store.Settings, o: Options) -> lexmod.Lexicon:
    L = s["lexicon"]
    rep = o.repetition if o.repetition is not None else L.get("repetition")
    return lexmod.build(ROOT, o.presets if o.presets is not None else L["presets"],
                        o.custom_words if o.custom_words is not None else L.get("custom_words", ""),
                        (o.ignore if o.ignore is not None else []) + list(L.get("ignore") or []),
                        L.get("repetition_allow"), L.get("max_custom_entries", 200), rep)


def _client(s: store.Settings) -> LLMClient:
    c = s["cost"]
    return LLMClient(Registry(ROOT / "config" / "models.yaml"),
                     Budget(c["max_usd_per_run"], c["max_input_tokens_per_call"], c.get("allow_unpriced_models", False)),
                     s["llm"].get("retries", 2))


def _prompt(s: store.Settings, role: str) -> tuple[str, str]:
    path = ROOT / s["llm"]["prompts"][role]
    text = path.read_text()
    return text, f"{path.name}@{store.sha(text)[:8]}"


def _call(res: Result, client: LLMClient, s: store.Settings, role: str, alias: str, system: str, prompt_id: str,
          user: str) -> str | None:
    """One model call with kill switch, local-only check, budget, fallback and a text-free log entry."""
    spec = client.registry.resolve(alias)
    if s["privacy"].get("local_only") and spec.provider not in ("mock", "ollama"):
        raise PermissionError(f"local_only is on: '{alias}' uses {spec.provider}")
    telemetry.require_enabled("analyze")
    res.model_payloads.append(user)
    entry = {"role": role, "alias": alias, "model": spec.name, "prompt": prompt_id, "input_sha": store.sha(user),
             "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "latency_ms": 0, "status": "ok",
             "used_fallback": False}
    try:
        r = client.complete(alias, system, user, s["llm"]["max_output_tokens"], s["llm"].get("fallback_alias"))
        entry.update(model=r.model.name, input_tokens=r.input_tokens, output_tokens=r.output_tokens,
                     cost_usd=round(r.cost_usd, 6), latency_ms=r.latency_ms, used_fallback=r.used_fallback)
        res.calls.append(entry)
        return r.text
    except BudgetExceeded as e:
        entry["status"] = "budget_blocked"
        res.calls.append(entry)
        res.flags.append("budget_blocked")
        res.warnings.append(f"{role} skipped: {e}")
    except telemetry.WorkflowDisabled:
        raise
    except Exception as e:  # provider down after retries and fallback
        entry["status"] = "error"
        res.calls.append(entry)
        res.flags.append("model_error")
        res.warnings.append(f"{role} model unavailable ({type(e).__name__}); running without it")
    return None


def _json(text: str | None):
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[-1]
    a, b = t.find("{"), t.rfind("}")
    return json.loads(t[a:b + 1]) if a >= 0 and b > a else None


# ---------------------------------------------------------------- steps
def disambiguate(res: Result, s: store.Settings, o: Options, client: LLMClient, pz: privacy.Pseudonymizer) -> None:
    unclear = [h for h in res.hits if h.verdict == "ambiguous"]
    if not unclear:
        return
    toks = tokenize(res.text)
    k = int(s["disambiguation"]["context_words"])
    system, pid = _prompt(s, "disambiguator")
    alias = o.disambiguator_alias or s["llm"]["disambiguator_alias"]
    by_id = {h.id: h for h in unclear}
    size = int(s["disambiguation"].get("batch_size", 40))
    for i in range(0, len(unclear), size):
        batch = unclear[i:i + size]
        occ = []
        for h in batch:
            j = h.token_index
            last = j + len(h.entry.split()) - 1 if h.entry != "repetition" else j
            a = toks[max(0, j - k)].start
            b = toks[min(len(toks) - 1, last + k)].end
            occ.append({"id": h.id, "word": h.entry,
                        "before": privacy.fence(pz.apply(res.text[a:h.start])),
                        "after": privacy.fence(pz.apply(res.text[h.end:b]))})
        user = "<occurrences>\n" + json.dumps({"occurrences": occ}, ensure_ascii=False) + "\n</occurrences>"
        out = _call(res, client, s, "disambiguator", alias, system, pid, user)
        try:
            parsed = Verdicts.model_validate(_json(out)) if out else None
        except (ValidationError, ValueError):
            parsed = None
            res.flags.append("schema_invalid")
            res.calls[-1]["status"] = "schema_invalid"
        min_conf = float(s["disambiguation"]["min_confidence"])
        for v in (parsed.verdicts if parsed else []):
            h = by_id.get(v.id)
            if h is None or h.verdict != "ambiguous":
                continue                                      # unknown or repeated id: ignored
            h.source, h.confidence, h.reason = "model", round(v.confidence, 2), v.reason[:120]
            h.verdict = ("filler" if v.is_filler else "not_filler") if v.confidence >= min_conf else "disputed"
    for h in unclear:
        if h.verdict == "ambiguous":
            h.verdict, h.reason = "disputed", h.reason or "no model verdict"
            h.confidence = 0.0


def apply_decisions(hits: list[Hit], decisions: dict[str, str]) -> None:
    """HITL: the speaker's call overrides any rule or model verdict."""
    for h in hits:
        d = decisions.get(h.id)
        if d in ("filler", "not_filler"):
            h.verdict, h.source, h.reason = d, "speaker", "your call"


def coach(res: Result, s: store.Settings, o: Options, client: LLMClient, pz: privacy.Pseudonymizer) -> None:
    n = int(s["coaching"]["rewrite_passages"])
    passages = scoremod.worst_passages(res.text, res.hits, n)
    if not passages and not res.score.fillers:
        return
    marked = {p["id"]: pz.apply(rewrite.mark(p["text"], p["start"], p["hits"])) for p in passages}
    stats = {"words": res.score.words, "fillers": res.score.fillers, "rate_per_100": res.score.rate_per_100,
             "target_per_100": res.score.target_per_100, "grade": res.score.grade,
             "by_category": res.score.by_category, "top": res.score.top,
             "top_by_category": res.score.top_by_category, "by_position": res.score.by_position,
             "clusters": len(res.score.clusters), "repetitions": res.score.repetitions}
    if res.score.timing:
        stats["words_per_minute"] = res.score.timing.words_per_minute
    system, pid = _prompt(s, "coach")
    system = system.replace("{tone}", s["coaching"]["tone"]).replace("{audience}", s["coaching"]["audience"])
    alias = o.coach_alias or s["llm"]["coach_alias"]
    pending = dict(marked)
    results: dict[str, dict] = {}
    attempts = int(s["coaching"].get("max_rewrite_attempts", 2))
    feedback: dict[str, list[str]] = {}
    for attempt in range(1, attempts + 1):
        payload = {"stats": stats, "plan": s["coaching"].get("practice_plan", []),
                   "passages": [{"id": pid_, "marked": privacy.fence(m),
                                 **({"problems_last_time": feedback[pid_]} if pid_ in feedback else {})}
                                for pid_, m in pending.items()]}
        out = _call(res, client, s, "coach", alias, system, pid,
                    "<analysis>\n" + json.dumps(payload, ensure_ascii=False) + "\n</analysis>")
        try:
            parsed = CoachOut.model_validate(_json(out)) if out else None
        except (ValidationError, ValueError):
            parsed = None
            res.flags.append("schema_invalid")
            res.calls[-1]["status"] = "schema_invalid"
        if parsed is None:
            break
        if attempt == 1:
            res.patterns = [{k: pz.restore(v) for k, v in p.model_dump().items()} for p in parsed.patterns]
        for r in parsed.rewrites:
            if r.passage_id not in pending:
                continue
            text = r.rewrite.replace("‹", "<").replace("›", ">")
            problems = rewrite.check(pending[r.passage_id], text, res.lexicon)
            results[r.passage_id] = {"rewrite": text, "note": r.note, "problems": problems, "attempts": attempt}
            if problems:
                feedback[r.passage_id] = problems
            else:
                pending.pop(r.passage_id)
        if not pending:
            break
    for p in passages:
        r = results.get(p["id"], {"rewrite": "", "note": "", "problems": ["no rewrite returned"], "attempts": 0})
        ok = not r["problems"]
        if not ok:
            res.flags.append("rewrite_rejected")
        res.rewrites.append({"id": p["id"], "start": p["start"], "end": p["end"], "original": p["text"],
                             "rewrite": pz.restore(r["rewrite"]) if ok else "", "note": pz.restore(r["note"]),
                             "status": "ok" if ok else "dropped", "problems": r["problems"],
                             "attempts": r["attempts"], "fillers": len(p["hits"])})


# ---------------------------------------------------------------- entry points
def analyze(transcript: Transcript, o: Options | None = None, settings: store.Settings | None = None) -> Result:
    o = o or Options()
    s = settings or store.Settings.load()
    t0 = time.perf_counter()
    lex = build_lexicon(s, o)
    text, spans = transcript.layout(o.speaker)
    th = dict(s["thresholds"])
    if o.target is not None:
        th["target_per_100_words"] = o.target
    res = Result(uuid.uuid4().hex[:12], text, detect(text, lex), None, lex, o.speaker or "", spans)  # type: ignore[arg-type]
    res.warnings += transcript.warnings + lex.warnings
    if not lex.active():
        res.warnings.append("the word list is empty: choose a preset or add words")
    wc = len(tokenize(text))
    if wc > int(th.get("max_words", 15000)):
        res.warnings.append(f"{wc:,} words: analysed in full; model calls were batched")
    res.injection = privacy.scan_injection(text)
    if res.injection:
        res.flags.append("injection_detected")
    pz = privacy.Pseudonymizer(o.names)
    if s["privacy"].get("pseudonymize", True):
        pz.learn_names(text)
    else:
        pz.forward = {}
        pz.apply = lambda x: x      # type: ignore[method-assign]
    client = _client(s)
    try:
        disambiguate(res, s, o, client, pz)
        apply_decisions(res.hits, o.decisions)
        res.score = scoremod.score(text, res.hits, th, spans)
        if o.coach and text.strip():
            coach(res, s, o, client, pz)
    except telemetry.WorkflowDisabled as e:
        res.flags.append("kill_switch")
        res.warnings.append(str(e))
        for h in res.hits:
            if h.verdict == "ambiguous":
                h.verdict = "disputed"
        res.score = scoremod.score(text, res.hits, th, spans)
    if pz.forward:
        res.flags.append("pii_pseudonymized")
    if res.score.disputed:
        res.flags.append("disputed")
    res.flags = sorted(set(res.flags))
    latency = int((time.perf_counter() - t0) * 1000)
    _record(res, s, transcript, latency, o)
    return res


def rescore(res: Result, decisions: dict[str, str], settings: store.Settings | None = None,
            target: float | None = None) -> Result:
    """The human step: re-apply the speaker's calls and recompute every number. No model call."""
    s = settings or store.Settings.load()
    th = dict(s["thresholds"])
    if target is not None:
        th["target_per_100_words"] = target
    apply_decisions(res.hits, decisions)
    res.score = scoremod.score(res.text, res.hits, th, res.spans)
    telemetry.emit("review", records_in=len(decisions),
                   records_out=sum(1 for d in decisions.values() if d == "not_filler"), run_id=res.run_id,
                   flags=["speaker_override"] if decisions else [],
                   detail={"marked_filler": sum(1 for d in decisions.values() if d == "filler"),
                           "marked_not_filler": sum(1 for d in decisions.values() if d == "not_filler")})
    return res


def _record(res: Result, s: store.Settings, transcript: Transcript, latency: int, o: Options) -> None:
    sc = res.score
    store.log_run({"run_id": res.run_id, "ts": store.now(), "input_sha": store.sha(res.text),
                   "lexicon_sha": store.sha(res.lexicon.to_text()), "source": transcript.source,
                   "words": sc.words, "hits": len(res.hits), "fillers": sc.fillers, "disputed": sc.disputed,
                   "rate_per_100": sc.rate_per_100, "grade": sc.grade, "flags": res.flags,
                   "rewrites_ok": sum(1 for r in res.rewrites if r["status"] == "ok"),
                   "rewrites_dropped": sum(1 for r in res.rewrites if r["status"] != "ok"),
                   "latency_ms": latency, "calls": res.calls})
    save = o.save_history if o.save_history is not None else s["privacy"].get("save_history", False)
    if save:
        store.save_history(s, res.speaker, res.run_id, sc)
    models = sorted({c["model"] for c in res.calls})
    telemetry.emit("analyze", status="ok" if "model_error" not in res.flags else "degraded",
                   model=",".join(models), input_tokens=sum(c["input_tokens"] for c in res.calls),
                   output_tokens=sum(c["output_tokens"] for c in res.calls), cost_usd=res.cost_usd,
                   latency_ms=latency, records_in=sc.words, records_out=sc.fillers, run_id=res.run_id,
                   flags=res.flags, detail={"grade": sc.grade, "rate_per_100": sc.rate_per_100,
                                            "hits": len(res.hits), "disputed": sc.disputed,
                                            "rewrites_ok": sum(1 for r in res.rewrites if r["status"] == "ok"),
                                            "rewrites_dropped": sum(1 for r in res.rewrites if r["status"] != "ok"),
                                            "source": transcript.source, "timed": bool(sc.timing),
                                            "presets": len(o.presets or s["lexicon"]["presets"])})


def load_file(path: str | Path) -> Transcript:
    from .ingest import load
    p = Path(path)
    return load(p.name, p.read_bytes())
