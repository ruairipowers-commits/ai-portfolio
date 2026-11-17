"""The governed workflow: request → sanitize → model parses legs (schema) → code validates against the chain and
the request → C++ engine prices + risk → permission and limit checks → model explains (schema, figures checked)
→ ticket BLOCKED or PENDING_APPROVAL → a named approver decides. Nothing is ever sent to a broker.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field

from pydantic import ValidationError

from . import guardrails as g, pricing
from .llm import Budget, BudgetExceeded, LLMClient, Registry, RegistryError
from .market import Market, load_accounts
from .schemas import RiskExplanation, TradeParse, explain_json_schema, parse_json_schema
from .store import ROOT, Settings, connect, log_call, now, rows, sha

PROVIDER_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


@dataclass
class Ticket:
    ticket_id: str
    account: str
    status: str                       # CLARIFY | INVALID | BLOCKED | PENDING_APPROVAL
    parse: TradeParse | None = None
    validation_errors: list[str] = field(default_factory=list)
    risk: dict | None = None
    checks: list[dict] = field(default_factory=list)
    cross_check: dict | None = None
    explanation: RiskExplanation | None = None
    citation_errors: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    injection_suspected: bool = False
    pii_redactions: int = 0
    schema_valid: bool = True
    spend_usd: float = 0.0
    payloads: list[str] = field(default_factory=list)


def market(s: Settings) -> Market:
    return Market.load(ROOT / s["market_file"])


def accounts(s: Settings) -> dict:
    return load_accounts(ROOT / s["accounts_file"])


def client_for(s: Settings, budget_usd: float | None = None) -> LLMClient:
    c = s["cost"]
    return LLMClient(Registry(ROOT / "config" / "models.yaml"),
                     Budget(budget_usd if budget_usd is not None else c["max_usd_per_run"],
                            c["max_input_tokens_per_call"], c["allow_unpriced_models"]), s["llm"]["retries"])


def prompt(s: Settings, key: str, schema: str) -> tuple[str, str, str]:
    path = ROOT / s["llm"][key]
    t = path.read_text()
    return t.replace("{schema}", schema), path.stem, sha(t)


def _call(con, client, s, alias, system, user, base) -> str:
    res = client.complete(alias, system, user, s["llm"]["max_output_tokens"], s["llm"].get("fallback_alias"))
    log_call(con, **base, model_name=res.model.name, provider=res.model.provider, model_id=res.model.model_id,
             input_tokens=res.input_tokens, output_tokens=res.output_tokens, cost_usd=res.cost_usd,
             latency_ms=res.latency_ms, used_fallback=int(res.used_fallback), status="ok")
    return res.text


def process(s: Settings, request: str, account_id: str, parse_alias: str | None = None, explain_alias: str | None = None,
            ticket_id: str | None = None, client: LLMClient | None = None) -> Ticket:
    from . import telemetry

    telemetry.require_enabled("ticket")
    t0 = time.perf_counter()
    tid = ticket_id or "T-" + uuid.uuid4().hex[:10]
    mk, accts = market(s), accounts(s)
    if account_id not in accts:
        raise KeyError(f"unknown account {account_id}")
    con = connect(s)
    client = client or client_for(s)
    tk = Ticket(tid, account_id, "INVALID")
    clean, flags = g.sanitize_untrusted(request, s["request"]["max_chars"], s["request"]["redact_pii"])
    tk.injection_suspected, tk.pii_redactions = flags["injection_suspected"], flags["pii_redactions"]

    # 1 · parse (model, schema)
    system, pver, psha = prompt(s, "parse_prompt", parse_json_schema())
    user = f"<chain>\n{json.dumps(mk.chain_summary())}\n</chain>\n<untrusted_request>\n{clean}\n</untrusted_request>"
    tk.payloads.append(user)
    base = dict(run_id=tid, purpose="parse_request", alias=parse_alias or s["llm"]["parse_alias"], prompt_version=pver,
                prompt_sha=psha, input_sha=sha(user))
    try:
        tk.parse = g.parse_trade(_call(con, client, s, base["alias"], system, user, base))
    except (BudgetExceeded, RegistryError) as e:
        log_call(con, **base, status="budget_blocked" if isinstance(e, BudgetExceeded) else "not_approved", error=str(e))
        raise
    except (ValueError, ValidationError) as e:
        tk.schema_valid = False
        tk.validation_errors = [f"model output failed schema validation: {str(e)[:160]}"]
    except Exception as e:
        log_call(con, **base, status="error", error=str(e)[:500])
        tk.validation_errors = [f"model call failed: {str(e)[:160]}"]
    if tk.parse and tk.parse.status == "CLARIFY":
        tk.status = "CLARIFY"
    elif tk.parse:
        # 2 · validate (code): listed, live, and actually in the request
        tk.validation_errors = g.validate_legs(tk.parse, mk, request, s["request"]["max_legs"])
        if not tk.validation_errors:
            # 3 · price + risk + checks (code)
            tk.risk = pricing.risk(tk.parse.legs, mk, s["pricing"])
            tk.checks = g.check_limits(tk.risk["summary"], tk.parse.legs, accts[account_id])
            tk.cross_check = pricing.cross_check(tk.parse.legs, mk, s["pricing"])
            p = tk.parse
            if p.limit_price is not None:
                fair = abs(tk.risk["summary"]["price_per_structure"])
                tol = s["pricing"]["limit_price_tolerance"]
                if (p.price_type == "DEBIT" and fair > p.limit_price * (1 + tol)) or (p.price_type == "CREDIT" and fair < p.limit_price * (1 - tol)):
                    tk.warnings.append(f"fair value {fair:.2f} vs requested {p.price_type.lower()} limit {p.limit_price:.2f}: may not fill")
            # 4 · explain (model, schema, figures checked)
            facts = {"ticket_id": tid, "summary": tk.risk["summary"], "legs": tk.risk["legs"], "checks": tk.checks}
            system, ever, esha = prompt(s, "explain_prompt", explain_json_schema())
            user2 = f"<ticket_risk>\n{json.dumps(facts)}\n</ticket_risk>"
            tk.payloads.append(user2)
            b2 = dict(run_id=tid, purpose="risk_explanation", alias=explain_alias or s["llm"]["explain_alias"],
                      prompt_version=ever, prompt_sha=esha, input_sha=sha(user2))
            try:
                tk.explanation = g.parse_explanation(_call(con, client, s, b2["alias"], system, user2, b2))
                tk.citation_errors = g.check_citations(tk.explanation, tk.risk["summary"])
            except (BudgetExceeded, RegistryError) as e:
                log_call(con, **b2, status="budget_blocked" if isinstance(e, BudgetExceeded) else "not_approved", error=str(e))
                raise
            except (ValueError, ValidationError) as e:
                tk.schema_valid = False
                tk.citation_errors = [f"explanation failed schema validation: {str(e)[:160]}"]
            except Exception as e:      # provider outage after retries + fallback: degraded, explicit, blocks approval
                log_call(con, **b2, status="error", error=str(e)[:500])
                tk.citation_errors = [f"explanation unavailable: {str(e)[:160]}"]
            tk.blockers = [(f"permission: {c['limit']}" if c["check"] == "permission" else f"{c['check']}: {c['value']} vs limit {c['limit']}")
                           for c in tk.checks if not c["passed"]]
            if s["policy"]["block_on_injection"] and tk.injection_suspected:
                tk.blockers.append("the request contains instructions about approvals or limits; resubmit it without them")
            if s["policy"]["block_on_citation_errors"] and tk.citation_errors:
                tk.blockers.append("the explanation doesn't match the engine's numbers")
            tk.status = "BLOCKED" if tk.blockers else "PENDING_APPROVAL"
    tk.spend_usd = client.budget.spent
    con.execute("insert or replace into tickets values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [tid, now(), account_id, sha(request), tk.status,
                 json.dumps([l.model_dump() for l in tk.parse.legs] if tk.parse else []),
                 json.dumps(tk.risk["summary"] if tk.risk else {}), json.dumps(tk.checks), json.dumps(tk.cross_check or {}),
                 tk.explanation.model_dump_json() if tk.explanation else "", json.dumps(
                     {"injection": tk.injection_suspected, "pii": tk.pii_redactions, "validation": tk.validation_errors,
                      "citation": tk.citation_errors, "warnings": tk.warnings}), json.dumps(tk.blockers), tk.spend_usd])
    con.commit()
    report(con, tk, int((time.perf_counter() - t0) * 1000))
    return tk


def decide(s: Settings, ticket_id: str, decision: str, approver: str, reason: str) -> tuple[bool, str]:
    """HITL-02: a named risk approver signs or rejects. BLOCKED / CLARIFY / INVALID tickets can't be approved."""
    from . import telemetry

    if decision not in ("APPROVE", "REJECT"):
        return False, "Decision must be APPROVE or REJECT."
    if not approver.strip():
        return False, "A named approver is required."
    if len(reason.strip()) < s["policy"]["min_approval_reason_chars"]:
        return False, f"A reason of at least {s['policy']['min_approval_reason_chars']} characters is required."
    con = connect(s)
    row = con.execute("select status, blockers from tickets where ticket_id=?", [ticket_id]).fetchone()
    if not row:
        return False, f"No ticket {ticket_id}."
    if row["status"] in ("APPROVED", "REJECTED"):
        return False, f"Ticket {ticket_id} was already {row['status'].lower()}."
    if decision == "APPROVE" and row["status"] != "PENDING_APPROVAL":
        why = "; ".join(json.loads(row["blockers"] or "[]")[:3]) or row["status"]
        return False, f"Ticket {ticket_id} can't be approved: {why}."
    status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    con.execute("update tickets set status=? where ticket_id=?", [status, ticket_id])
    con.execute("insert into decisions values (?,?,?,?,?)", [now(), ticket_id, approver, decision, reason])
    con.commit()
    telemetry.emit("review", actor=approver, actor_type="named", records_in=1, run_id=ticket_id, detail={"decision": decision})
    telemetry.flush()
    return True, f"{approver} {status.lower()} ticket {ticket_id}. Nothing was sent: the ticket is stored for booking."


def report(con, tk: Ticket, latency_ms: int, event_type: str = "ticket") -> None:
    from . import telemetry

    c = con.execute("""select coalesce(group_concat(distinct model_name), ''), coalesce(sum(input_tokens),0),
                              coalesce(sum(output_tokens),0), coalesce(sum(cost_usd),0), sum(status='budget_blocked')
                       from ai_calls where run_id=?""", [tk.ticket_id]).fetchone()
    flags = [f for f, ok in [("injection_detected", tk.injection_suspected), ("blocked", tk.status == "BLOCKED"),
                             ("clarification", tk.status == "CLARIFY"), ("invalid_legs", bool(tk.validation_errors)),
                             ("citation_error", bool(tk.citation_errors)), ("budget_blocked", bool(c[4]))] if ok]
    telemetry.emit(event_type, status="ok", model=c[0], input_tokens=c[1], output_tokens=c[2], cost_usd=c[3],
                   latency_ms=latency_ms, records_in=1, records_out=len(tk.parse.legs) if tk.parse else 0, flags=flags,
                   run_id=tk.ticket_id, detail={"status": tk.status})
    telemetry.flush()


def usable_aliases(s: Settings, prefix: str = "parse") -> dict[str, str]:
    reg = Registry(ROOT / "config" / "models.yaml")
    out, targets = {}, set(reg.aliases.values())
    for name in [a for a in reg.aliases if a.startswith(prefix)] + [m for m in reg.models if m not in targets]:
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


def tickets(s: Settings) -> list[dict]:
    return rows(connect(s), "select ticket_id, created, account, status, legs, blockers, spend_usd from tickets "
                            "where ticket_id not like 'eval-%' order by created desc limit 100")
