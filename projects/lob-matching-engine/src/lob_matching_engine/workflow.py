"""The governed workflow: data gate → replay through the engine → detectors → per-alert narrative
(sanitize → model → validate → cite-check → policy) → audit log. A person disposes of every alert.

This is a workflow, not an agent: code decides what is an alert and computes every number; the model has no
tools and only drafts text inside a schema.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field

from pydantic import ValidationError

from . import detectors, guardrails as g, sessions
from .llm import Budget, BudgetExceeded, LLMClient, Registry, RegistryError
from .schemas import AlertResult, narrative_json_schema
from .store import ROOT, Settings, connect, log_call, log_result, now, rows, save_alerts, save_events, sha

PROVIDER_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


class DataGateError(RuntimeError):
    pass


@dataclass
class RunResult:
    run_id: str
    gate: sessions.GateResult
    replay: sessions.Replay | None = None
    alerts: list[dict] = field(default_factory=list)
    results: list[AlertResult] = field(default_factory=list)
    spend_usd: float = 0.0
    error: str = ""
    payloads: list[str] = field(default_factory=list)   # what was sent to the model (kept for the PII eval)


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def client_for(s: Settings, budget_usd: float | None = None) -> LLMClient:
    c = s["cost"]
    return LLMClient(Registry(ROOT / "config" / "models.yaml"),
                     Budget(budget_usd if budget_usd is not None else c["max_usd_per_run"],
                            c["max_input_tokens_per_call"], c["allow_unpriced_models"]), s["llm"]["retries"])


def build_prompt(s: Settings) -> tuple[str, str, str]:
    path = ROOT / s["llm"]["prompt_file"]
    template = path.read_text()
    return template.replace("{schema}", narrative_json_schema()), path.stem, sha(template)


def model_payload(alert: dict, orders, s: Settings, pseudo: dict[str, str]) -> tuple[str, dict]:
    """DATA-03: facts computed by code, the trader as a pseudonym, and sanitized memos of the alert's own orders."""
    d = s["data"]
    facts = {**alert["facts"], "event_count": len(alert["event_ids"])}
    payload = {"alert_id": alert["alert_id"], "pattern": alert["pattern"], "severity": alert["severity"],
               "trader": pseudo[alert["trader"]] if d["pseudonymise_traders"] else alert["trader"],
               "event_ids": alert["event_ids"][:40], "facts": facts}
    mine = orders[orders.trader == alert["trader"]]
    memos = [m for m in dict.fromkeys(mine.memo.astype(str)) if m.strip()][: d["max_memos_per_alert"]]
    flags = {"injection_suspected": False, "pii_redactions": 0}
    clean = []
    for m in memos:
        t, f = g.sanitize_untrusted(m, d["max_memo_chars"], d["redact_pii"])
        clean.append(t)
        flags["injection_suspected"] |= f["injection_suspected"]
        flags["pii_redactions"] += f["pii_redactions"]
    user = (f"<alert_facts>\n{json.dumps(payload)}\n</alert_facts>\n"
            f"<untrusted_order_memos>\n" + "\n".join(f"- {t}" for t in clean) + "\n</untrusted_order_memos>")
    return user, {**flags, "facts": facts}


def narrate(con, alert: dict, orders, s: Settings, client: LLMClient, run_id: str, pseudo: dict,
            alias: str | None = None) -> tuple[AlertResult, str]:
    alias = alias or s["llm"]["primary_alias"]
    user, flags = model_payload(alert, orders, s, pseudo)
    facts = flags.pop("facts")
    system, pver, psha = build_prompt(s)
    base = dict(run_id=run_id, purpose="alert_narrative", alert_id=alert["alert_id"], alias=alias,
                prompt_version=pver, prompt_sha=psha, input_sha=sha(user))
    schema_valid, cost, model_name = True, 0.0, ""
    try:
        res = client.complete(alias, system, user, s["llm"]["max_output_tokens"], s["llm"].get("fallback_alias"))
        cost, model_name = res.cost_usd, res.model.name
        log_call(con, **base, model_name=res.model.name, provider=res.model.provider, model_id=res.model.model_id,
                 input_tokens=res.input_tokens, output_tokens=res.output_tokens, cost_usd=res.cost_usd,
                 latency_ms=res.latency_ms, used_fallback=int(res.used_fallback), status="ok")
        try:
            n = g.parse_narrative(res.text)
        except (ValueError, ValidationError) as e:
            schema_valid = False
            n = g.fallback_narrative(alert, f"model output failed schema validation: {str(e)[:160]}")
    except (BudgetExceeded, RegistryError) as e:
        log_call(con, **base, status="budget_blocked" if isinstance(e, BudgetExceeded) else "not_approved", error=str(e))
        raise
    except Exception as e:
        log_call(con, **base, status="error", error=str(e)[:500])
        schema_valid = False
        n = g.fallback_narrative(alert, f"model call failed: {str(e)[:160]}")
    cerr = g.check_citations(n, alert, facts) if schema_valid else []
    final, overrides = g.apply_policy(n.suggested_disposition, alert["severity"], flags, s["policy"])
    if cerr and final != "ESCALATE":
        final, overrides = "ESCALATE", overrides + ["Narrative failed the citation check"]
    r = AlertResult(alert_id=alert["alert_id"], pattern=alert["pattern"], severity=alert["severity"], narrative=n,
                    model_suggestion=n.suggested_disposition, final_suggestion=final, policy_overrides=overrides,
                    citation_errors=cerr, schema_valid=schema_valid, injection_suspected=flags["injection_suspected"],
                    pii_redactions=flags["pii_redactions"], model_name=model_name, cost_usd=cost)
    log_result(con, run_id, r)
    return r, user


def run(s: Settings, session, alias: str | None = None, source: str = "synthetic", run_id: str | None = None,
        client: LLMClient | None = None, store_events: bool = True) -> RunResult:
    """End to end. Raises nothing for data problems: a failed gate is returned and nothing else runs."""
    from . import telemetry

    telemetry.require_enabled("surveillance_run")
    t0 = time.perf_counter()
    run_id = run_id or new_run_id()
    con = connect(s)
    band = tuple(s["engine"]["price_band"])
    gate = sessions.validate(session, band, s["gate"]["max_rows"], s["gate"]["require_monotonic_time"])
    out = RunResult(run_id, gate)
    if not gate.ok:
        con.execute("insert into runs values (?,?,?,?,?,?,?,?,?,?)",
                    [run_id, now(), source, gate.rows, 0, json.dumps(gate.errors), "{}", 0, 0.0, 0.0])
        con.commit()
        report_run(con, run_id, int((time.perf_counter() - t0) * 1000), status="blocked", flags=("data_gate_failed",))
        return out
    rep = sessions.replay(session, band, s["engine"]["stp"])
    out.replay = rep
    alerts = detectors.detect_all(rep.orders, rep.events, s["detectors"])
    out.alerts = alerts
    if store_events:
        save_events(con, run_id, rep.events)
    save_alerts(con, run_id, alerts)
    client = client or client_for(s)
    pseudo = g.pseudonymise([a["trader"] for a in alerts])
    try:
        for a in alerts:
            r, payload = narrate(con, a, rep.orders, s, client, run_id, pseudo, alias)
            out.results.append(r)
            out.payloads.append(payload)
    except (BudgetExceeded, RegistryError) as e:
        out.error = str(e)
    out.spend_usd = client.budget.spent
    secs = time.perf_counter() - t0
    con.execute("insert into runs values (?,?,?,?,?,?,?,?,?,?)",
                [run_id, now(), source, gate.rows, 1, "[]", json.dumps(rep.stats), len(alerts), out.spend_usd, secs])
    con.commit()
    report_run(con, run_id, int(secs * 1000), status="error" if out.error else "ok")
    return out


def dispose(s: Settings, run_id: str, alert_id: str, decision: str, reviewer: str, reason: str) -> tuple[bool, str]:
    """HITL-02: a named analyst closes or escalates an alert. High-severity closes need a written reason."""
    from . import telemetry

    if decision not in ("CLOSE", "ESCALATE"):
        return False, "Decision must be CLOSE or ESCALATE."
    if not reviewer.strip():
        return False, "A named reviewer is required."
    con = connect(s)
    row = con.execute("select severity, final_suggestion from narratives where run_id=? and alert_id=? "
                      "order by result_ts desc limit 1", [run_id, alert_id]).fetchone()
    if not row:
        return False, f"No narrative for {alert_id} in run {run_id}."
    sev, ai = row["severity"], row["final_suggestion"]
    need = s["policy"]["min_close_reason_chars"]
    if decision == "CLOSE" and sev == "high" and len(reason.strip()) < need:
        return False, f"Closing a high-severity alert needs a written reason (at least {need} characters)."
    con.execute("insert into dispositions values (?,?,?,?,?,?,?,?,?)",
                [now(), run_id, alert_id, sev, reviewer, ai, decision, int(ai == decision), reason])
    con.commit()
    telemetry.emit("review", actor=reviewer, actor_type="named", records_in=1, run_id=run_id,
                   flags=[] if ai == decision else ["human_override"], detail={"severity": sev})
    telemetry.flush()
    return True, f"Recorded {reviewer}: {alert_id} → {decision} (AI suggested {ai})."


def report_run(con, run_id: str, latency_ms: int, event_type: str = "surveillance_run", status: str = "ok",
               flags: tuple = (), detail: dict | None = None) -> None:
    """One governance event per run, summarised from the audit tables (counts and flags only)."""
    from . import telemetry

    c = con.execute("""select coalesce(group_concat(distinct model_name), ''), coalesce(sum(input_tokens),0),
                              coalesce(sum(output_tokens),0), coalesce(sum(cost_usd),0),
                              sum(status='budget_blocked') from ai_calls where run_id=?""", [run_id]).fetchone()
    n = con.execute("""select count(*), coalesce(sum(injection_suspected),0), coalesce(sum(final_suggestion='ESCALATE'),0),
                              coalesce(sum(final_suggestion<>model_suggestion),0),
                              coalesce(sum(citation_errors not in ('','[]')),0) from narratives where run_id=?""",
                    [run_id]).fetchone()
    cmds = con.execute("select coalesce(commands,0) from runs where run_id=?", [run_id]).fetchone()
    fl = [f for f, k in [("injection_detected", n[1]), ("escalated", n[2]), ("policy_override", n[3]),
                         ("citation_error", n[4]), ("budget_blocked", c[4] or 0)] if k] + list(flags)
    telemetry.emit(event_type, status=status, model=c[0], input_tokens=c[1], output_tokens=c[2], cost_usd=c[3],
                   latency_ms=latency_ms, records_in=cmds[0] if cmds else 0, records_out=n[0], flags=fl,
                   run_id=run_id, detail={"alerts": n[0], "escalated": n[2], "injections": n[1], **(detail or {})})
    telemetry.flush()


def usable_aliases(s: Settings) -> dict[str, str]:
    """Aliases/models that can actually run here: approved, priced, with a key if one is needed."""
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


def latest_run(s: Settings) -> dict | None:
    con = connect(s)
    r = rows(con, "select * from runs where gate_ok=1 and run_id not like 'eval-%' order by started desc limit 1")
    return r[0] if r else None
