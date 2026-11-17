"""The governed workflow: data gate → event-driven backtest + stress/holdout runs → promotion checks (code) →
research memo (sanitize → model → validate → figure check → compliance → policy) → audit. A PM decides promotion.

A workflow, not an agent: the engine and the gate compute every number; the model only drafts text in a schema.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field

import numpy as np
from pydantic import ValidationError

from . import demo, gates, guardrails as g
from .engine import ExecConfig, run_kernel
from .llm import Budget, BudgetExceeded, LLMClient, Registry, RegistryError
from .schemas import MemoResult, memo_json_schema
from .store import ROOT, Settings, connect, log_call, log_result, now, rows, sha
from .strategies import BollingerReversion, CodeStrategy, DonchianBreakout, LeakyStrategy, MACross, VolTargetMomentum

PROVIDER_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
STRATEGIES = {
    "MA crossover": (MACross, {"fast": 10, "slow": 40}),
    "Donchian breakout": (DonchianBreakout, {"entry": 40, "exit": 20}),
    "Bollinger mean reversion": (BollingerReversion, {"window": 30, "entry_z": 2.0, "exit_z": 0.5}),
    "Vol-target momentum": (VolTargetMomentum, {"lookback": 48, "vol_window": 96, "target_vol_bps": 15.0}),
    "Leaky (peeks at the next bar)": (LeakyStrategy, {}),
}


@dataclass
class RunResult:
    run_id: str
    gate: gates.GateResult
    metrics: dict = field(default_factory=dict)
    checks: list = field(default_factory=list)
    result: object = None
    memo: MemoResult | None = None
    spend_usd: float = 0.0
    error: str = ""
    payload: str = ""


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def factory(kind: str, params: dict, code: str | None = None):
    if kind == "Custom Python":
        if demo.enabled():
            raise PermissionError("Custom strategy code is disabled in the hosted demo (it would run on a shared server).")
        return lambda: CodeStrategy(code or "", "Custom")
    cls, defaults = STRATEGIES[kind]
    p = {**defaults, **(params or {})}
    return lambda: cls(**p)


def client_for(s: Settings, budget_usd: float | None = None) -> LLMClient:
    c = s["cost"]
    return LLMClient(Registry(ROOT / "config" / "models.yaml"),
                     Budget(budget_usd if budget_usd is not None else c["max_usd_per_run"],
                            c["max_input_tokens_per_call"], c["allow_unpriced_models"]), s["llm"]["retries"])


def build_prompt(s: Settings) -> tuple[str, str, str]:
    path = ROOT / s["llm"]["prompt_file"]
    template = path.read_text()
    return template.replace("{schema}", memo_json_schema()), path.stem, sha(template)


def draft_memo(con, s: Settings, run_id: str, metrics: dict, checks: list, notes: str, client: LLMClient,
               alias: str | None = None) -> tuple[MemoResult, str]:
    alias = alias or s["llm"]["primary_alias"]
    clean, flags = g.sanitize_untrusted(notes or "", s["data"]["max_notes_chars"], s["data"]["redact_pii"])
    user = (f"<run_metrics>\n{json.dumps(metrics)}\n</run_metrics>\n<promotion_checks>\n{json.dumps(checks)}\n"
            f"</promotion_checks>\n<untrusted_research_notes>\n{clean}\n</untrusted_research_notes>")
    system, pver, psha = build_prompt(s)
    base = dict(run_id=run_id, purpose="research_memo", alias=alias, prompt_version=pver, prompt_sha=psha, input_sha=sha(user))
    schema_valid, cost, model_name = True, 0.0, ""
    try:
        res = client.complete(alias, system, user, s["llm"]["max_output_tokens"], s["llm"].get("fallback_alias"))
        cost, model_name = res.cost_usd, res.model.name
        log_call(con, **base, model_name=res.model.name, provider=res.model.provider, model_id=res.model.model_id,
                 input_tokens=res.input_tokens, output_tokens=res.output_tokens, cost_usd=res.cost_usd,
                 latency_ms=res.latency_ms, used_fallback=int(res.used_fallback), status="ok")
        try:
            memo = g.parse_memo(res.text)
        except (ValueError, ValidationError) as e:
            schema_valid = False
            memo = g.fallback_memo(run_id, metrics["strategy"], metrics, f"memo failed schema validation: {str(e)[:160]}")
    except (BudgetExceeded, RegistryError) as e:
        log_call(con, **base, status="budget_blocked" if isinstance(e, BudgetExceeded) else "not_approved", error=str(e))
        raise
    except Exception as e:
        log_call(con, **base, status="error", error=str(e)[:500])
        schema_valid = False
        memo = g.fallback_memo(run_id, metrics["strategy"], metrics, f"model call failed: {str(e)[:160]}")
    cite = g.check_citations(memo, metrics, checks) if schema_valid else []
    comp = g.check_compliance(memo, s["memo"]["required_disclosures"], checks) if schema_valid else ["no valid memo"]
    final, promotable, blockers = g.apply_policy(memo.recommendation, checks, flags, cite, comp, s["policy"])
    if not schema_valid:
        promotable, blockers = False, blockers + ["no valid memo"]
    r = MemoResult(memo=memo, model_recommendation=memo.recommendation, final_recommendation=final,
                   promotable=promotable, blockers=blockers, citation_errors=cite, compliance_errors=comp,
                   schema_valid=schema_valid, injection_suspected=flags["injection_suspected"],
                   pii_redactions=flags["pii_redactions"], model_name=model_name, cost_usd=cost)
    log_result(con, run_id, r)
    return r, user


def run(s: Settings, ticks, kind: str = "MA crossover", params: dict | None = None, notes: str = "",
        cfg: ExecConfig | None = None, alias: str | None = None, trials: int = 1, code: str | None = None,
        dataset: str = "synthetic", run_id: str | None = None, client: LLMClient | None = None) -> RunResult:
    from . import telemetry

    telemetry.require_enabled("backtest_run")
    t0 = time.perf_counter()
    run_id = run_id or new_run_id()
    cfg = cfg or ExecConfig()
    con = connect(s)
    gate = gates.validate_ticks(ticks, s["gate"])
    out = RunResult(run_id, gate)
    dsha = sha(str(len(ticks)) + str(ticks.iloc[0].to_dict() if len(ticks) else "") + str(ticks.iloc[-1].to_dict() if len(ticks) else ""))
    if not gate.ok:
        con.execute("insert into runs values (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [run_id, now(), dataset, dsha, kind, json.dumps(params or {}), 0, json.dumps(gate.errors), "{}", "[]", 0.0, 0.0])
        con.commit()
        report_run(con, run_id, int((time.perf_counter() - t0) * 1000), len(ticks), status="blocked", flags=("data_gate_failed",))
        return out
    metrics, checks, res = gates.compute(ticks, factory(kind, params, code), cfg, s["promotion"], trials)
    metrics["run_id"] = run_id
    if kind == "MA crossover" and cfg.order_type == "market" and cfg.fill_mode == "next_tick":
        p = {**STRATEGIES[kind][1], **(params or {})}
        k = run_kernel(ticks, int(p["fast"]), int(p["slow"]), cfg)
        metrics["kernel_parity_max_diff_usd"] = (float(np.max(np.abs(k["equity"] - res.bars.equity.values)))
                                                 if len(k["equity"]) == len(res.bars) else None)
    out.metrics, out.checks, out.result = metrics, checks, res
    client = client or client_for(s)
    try:
        out.memo, out.payload = draft_memo(con, s, run_id, metrics, checks, notes, client, alias)
    except (BudgetExceeded, RegistryError) as e:
        out.error = str(e)
    out.spend_usd = client.budget.spent
    secs = time.perf_counter() - t0
    con.execute("insert into runs values (?,?,?,?,?,?,?,?,?,?,?,?)",
                [run_id, now(), dataset, dsha, kind, json.dumps(params or {}), 1, "[]", json.dumps(metrics),
                 json.dumps(checks), out.spend_usd, secs])
    con.commit()
    report_run(con, run_id, int(secs * 1000), len(ticks), status="error" if out.error else "ok")
    return out


def decide(s: Settings, run_id: str, decision: str, reviewer: str, reason: str) -> tuple[bool, str]:
    """HITL-02: a named PM approves or rejects promotion to paper trading. Approval is blocked unless the run is
    promotable (every check passed, memo figures and disclosures clean, no injection flag)."""
    from . import telemetry

    if decision not in ("APPROVE", "REJECT"):
        return False, "Decision must be APPROVE or REJECT."
    if not reviewer.strip():
        return False, "A named reviewer is required."
    con = connect(s)
    m = con.execute("select final_recommendation, promotable, blockers from memos where run_id=? "
                    "order by result_ts desc limit 1", [run_id]).fetchone()
    if not m:
        return False, f"No memo for run {run_id}."
    if decision == "APPROVE" and not m["promotable"]:
        return False, "Promotion is blocked: " + "; ".join(json.loads(m["blockers"])[:3])
    ai_says = "APPROVE" if m["final_recommendation"] == "PROMOTE" else "REJECT"
    con.execute("insert into promotions values (?,?,?,?,?,?,?)",
                [now(), run_id, reviewer, m["final_recommendation"], decision, int(ai_says == decision), reason])
    con.commit()
    telemetry.emit("review", actor=reviewer, actor_type="named", records_in=1, run_id=run_id,
                   flags=[] if ai_says == decision else ["human_override"], detail={"decision": decision})
    telemetry.flush()
    return True, f"Recorded {reviewer}: run {run_id} → {decision} (memo recommended {m['final_recommendation']})."


def report_run(con, run_id: str, latency_ms: int, records_in: int, event_type: str = "backtest_run",
               status: str = "ok", flags: tuple = (), detail: dict | None = None) -> None:
    from . import telemetry

    c = con.execute("""select coalesce(group_concat(distinct model_name), ''), coalesce(sum(input_tokens),0),
                              coalesce(sum(output_tokens),0), coalesce(sum(cost_usd),0), sum(status='budget_blocked')
                       from ai_calls where run_id=?""", [run_id]).fetchone()
    m = con.execute("select injection_suspected, promotable, citation_errors, compliance_errors, model_recommendation, "
                    "final_recommendation from memos where run_id=?", [run_id]).fetchone()
    fl = list(flags)
    if m:
        fl += [f for f, ok in [("injection_detected", m[0]), ("blocked", not m[1]), ("citation_error", m[2] not in ("", "[]")),
                               ("compliance_error", m[3] not in ("", "[]")), ("policy_override", m[4] != m[5])] if ok]
    if c[4]:
        fl.append("budget_blocked")
    telemetry.emit(event_type, status=status, model=c[0], input_tokens=c[1], output_tokens=c[2], cost_usd=c[3],
                   latency_ms=latency_ms, records_in=records_in, records_out=1 if m else 0, flags=fl, run_id=run_id,
                   detail=detail or {})
    telemetry.flush()


def usable_aliases(s: Settings) -> dict[str, str]:
    reg = Registry(ROOT / "config" / "models.yaml")
    out, targets = {}, set(reg.aliases.values())
    for name in list(reg.aliases) + [m for m in reg.models if m not in targets]:
        try:
            spec = reg.resolve(name)
        except RegistryError:
            continue
        if not spec.priced() and not s["cost"]["allow_unpriced_models"]:
            continue
        key = PROVIDER_KEYS.get(spec.provider)
        if key and not os.getenv(key):
            continue
        out[f"{name} → {spec.name}" if name in reg.aliases else name] = name
    return out


def history(s: Settings) -> list[dict]:
    return rows(connect(s), "select run_id, started, dataset, strategy, params, gate_ok, spend_usd, seconds "
                            "from runs where run_id not like 'eval-%' order by started desc limit 50")
