"""Explain breaks, post alerts and run the whole EOD check. The Airflow DAG, the CLI and the app call these.

The model only explains rows that SQL already found. After it answers, code checks the answer: it must cite at
least one runbook section that was retrieved (NFR-2), its next step must come from a cited runbook, and nothing
unsafe (forced or full reruns, skipping reconciliation, deleting data, publishing NAV) gets through. Critical
breaks always go to a human. If no model is available the break is still alerted with its runbook sections
(degraded mode, MODEL-05).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.request
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from . import kb, telemetry
from .llm import Budget, BudgetExceeded, LLMClient, Registry, RegistryError, tokens
from .loader import SCHEMA, load
from .store import ROOT, Settings, connect
from .transform import run_dbt


class Explanation(BaseModel):
    likely_cause: str = Field(default="", max_length=1000)
    next_step: str = Field(default="", max_length=600)
    runbook_refs: list[str] = Field(default_factory=list, max_length=8)
    incident_refs: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(default=0.0, ge=0, le=1)
    needs_human: bool = False


def prompt(settings: Settings) -> tuple[str, str]:
    text = (ROOT / settings["llm"]["prompt_file"]).read_text()
    return text, hashlib.sha256(text.encode()).hexdigest()[:16]


def _esc(s: str) -> str:
    return str(s).replace("<", "&lt;").replace(">", "&gt;").replace('"', "'")


def build_user_prompt(brk: dict, runbooks: list[dict], incidents: list[dict]) -> str:
    facts = {k: (str(v) if k in ("business_date", "expected", "actual", "diff") and v is not None else v)
             for k, v in brk.items() if k in ("business_date", "break_type", "severity", "entity", "book", "metric",
                                              "expected", "actual", "diff", "detail")}
    facts["hints"] = [h for h in brk["hints"].split(",") if h]
    rb = "\n".join(f'<runbook id="{c["chunk_id"]}" types="{",".join(c["break_types"])}" hints="{",".join(c["hints"])}">'
                   f'{_esc(c["title"])} — {_esc(c["section"])}\n{_esc(c["text"])}</runbook>' for c in runbooks)
    inc = "\n".join(f'<incident id="{i["chunk_id"]}" type="{",".join(i["break_types"])}" hints="{",".join(i["hints"])}">'
                    f'{_esc(i["text"])}</incident>' for i in incidents)
    return f"<break>{json.dumps(facts)}</break>\n<runbooks>\n{rb}\n</runbooks>\n<incidents>\n{inc}\n</incidents>"


def check(settings: Settings, brk: dict, exp: Explanation, runbooks: list[dict], incidents: list[dict]) -> tuple[str, list[str], Explanation]:
    """Deterministic policy after the model. Returns (status, flags, possibly-redacted explanation)."""
    p, flags = settings["policy"], []
    rb_ids = {c["chunk_id"]: c for c in runbooks}
    cited = [r for r in exp.runbook_refs if r in rb_ids]
    if len(cited) < len(exp.runbook_refs) or any(i not in {x["chunk_id"] for x in incidents} for i in exp.incident_refs):
        flags.append("citation_not_in_context")
    exp = exp.model_copy(update={"runbook_refs": cited,
                                 "incident_refs": [i for i in exp.incident_refs if i in {x["chunk_id"] for x in incidents}]})
    if len(cited) < p["min_runbook_citations"]:
        flags.append("no_runbook_citation")
    step_text = " ".join(rb_ids[r]["text"] for r in cited)
    st = set(tokens(exp.next_step))
    if exp.next_step and len(st & set(tokens(step_text))) / max(len(st), 1) < 0.6:
        flags.append("step_not_in_runbook")
    bad = [pat for pat in p["unsafe_action_patterns"] if re.search(pat, f"{exp.next_step} {exp.likely_cause}", re.I)]
    if bad:
        flags.append("unsafe_action")
        exp = exp.model_copy(update={"next_step": "Blocked by policy: the suggested step was unsafe "
                                                  f"({', '.join(bad)}). Follow the cited runbook manually and escalate "
                                                  "to the ops lead."})
    if brk["severity"] in p["human_required_severities"]:
        flags.append("critical_needs_human")
    needs_human = bool(flags) or exp.needs_human
    return ("needs_human" if needs_human else "explained"), flags, exp.model_copy(update={"needs_human": needs_human})


def _cached(con, brk: dict, model_name: str, prompt_sha: str, kb_version: str) -> dict | None:
    """COST-03: a break already explained with the same model, prompt and knowledge base isn't sent again."""
    r = con.execute("""select * from audit.explanations where break_id = %s and model_name = %s and prompt_sha = %s
                       and kb_version = %s and status in ('explained', 'needs_human') and run_id not like 'eval-%%'
                       order by ts desc limit 1""", (brk["break_id"], model_name, prompt_sha, kb_version)).fetchone()
    return dict(r) if r else None


def explain_break(settings: Settings, con, registry: Registry, client: LLMClient, brk: dict, alias: str,
                  run_id: str, kb_version: str, use_cache: bool = True) -> dict:
    t0 = time.perf_counter()
    runbooks, incidents = kb.retrieve(con, settings, registry, brk)
    system, prompt_sha = prompt(settings)
    hit = _cached(con, brk, registry.resolve(alias).name, prompt_sha, kb_version) if use_cache and not client.unavailable else None
    if hit:
        return {**{k: hit[k] for k in ("explanation_id", "status", "model_name", "model_id", "likely_cause", "next_step",
                                       "runbook_refs", "incident_refs", "needs_human", "used_fallback")},
                "run_id": run_id, "business_date": brk["business_date"], "break_id": brk["break_id"],
                "break_type": brk["break_type"], "severity": brk["severity"], "entity": brk["entity"],
                "prompt_sha": prompt_sha, "kb_version": kb_version, "confidence": float(hit["confidence"] or 0),
                "flags": list(hit["flags"] or []) + ["cached"], "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "context": {"runbooks": runbooks, "incidents": incidents}}
    row = {"explanation_id": uuid.uuid4().hex[:12], "run_id": run_id, "business_date": brk["business_date"],
           "break_id": brk["break_id"], "break_type": brk["break_type"], "severity": brk["severity"],
           "entity": brk["entity"], "model_name": "", "model_id": "", "prompt_sha": prompt_sha, "kb_version": kb_version,
           "likely_cause": "", "next_step": "", "runbook_refs": [], "incident_refs": [], "confidence": 0.0,
           "needs_human": True, "flags": [], "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
           "used_fallback": False, "status": "needs_human"}
    try:
        out = client.complete(alias, system, build_user_prompt(brk, runbooks, incidents),
                              settings["llm"]["max_output_tokens"], settings["llm"]["fallback_alias"])
        row.update(model_name=out.model.name, model_id=out.model.model_id, input_tokens=out.input_tokens,
                   output_tokens=out.output_tokens, cost_usd=out.cost_usd, used_fallback=out.used_fallback)
        try:
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", out.text.strip())
            exp = Explanation.model_validate(json.loads(raw[raw.find("{"): raw.rfind("}") + 1]))
            status, flags, exp = check(settings, brk, exp, runbooks, incidents)
            row.update(status=status, flags=flags + (["fallback_model"] if out.used_fallback else []),
                       **exp.model_dump())
        except Exception as e:  # SEC-04: off-contract output is never shown as an explanation
            row.update(flags=["invalid_output"], likely_cause=f"Model output failed validation ({type(e).__name__})")
    except (BudgetExceeded, RegistryError) as e:
        row.update(status="degraded", flags=["blocked"], likely_cause=f"Not explained: {e}")
    except Exception as e:  # primary and fallback both failed: degraded mode, still alert with the runbooks
        row.update(status="degraded", flags=["models_unavailable"],
                   likely_cause=f"No explanation: models unavailable ({type(e).__name__}). Retrieved runbook sections attached.")
    if row["status"] == "degraded":
        row["runbook_refs"] = [c["chunk_id"] for c in runbooks if c["section"] == "Steps"][:2]
    row["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    row["context"] = {"runbooks": runbooks, "incidents": incidents}
    con.execute("""insert into audit.explanations (explanation_id, run_id, business_date, break_id, break_type, severity,
                   entity, status, model_name, model_id, prompt_sha, kb_version, likely_cause, next_step, runbook_refs,
                   incident_refs, confidence, needs_human, flags, input_tokens, output_tokens, cost_usd, latency_ms,
                   used_fallback) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (row["explanation_id"], run_id, brk["business_date"], brk["break_id"], brk["break_type"],
                 brk["severity"], brk["entity"], row["status"], row["model_name"], row["model_id"], prompt_sha,
                 kb_version, row["likely_cause"], row["next_step"], json.dumps(row["runbook_refs"]),
                 json.dumps(row["incident_refs"]), row["confidence"], row["needs_human"], json.dumps(row["flags"]),
                 row["input_tokens"], row["output_tokens"], row["cost_usd"], row["latency_ms"], row["used_fallback"]))
    return row


# ---------------------------------------------------------------- alerts (FR-4)
def post_alert(settings: Settings, con, brk: dict, exp: dict) -> bool:
    """One alert per break (dedup by break_id). Written to the outbox; sending is separate (send_pending)."""
    aid = hashlib.sha256(f"{brk['break_id']}".encode()).hexdigest()[:16]
    if con.execute("select 1 from audit.alerts where alert_id = %s", (aid,)).fetchone():
        return False
    who = "ops lead + on-call" if exp["needs_human"] else "on-call"
    title = f"[{brk['severity'].upper()}] {brk['break_type'].replace('_', ' ')} · {brk['entity']} · {brk['business_date']}"
    body = (f"{brk['detail']}\nLikely cause: {exp['likely_cause'] or '—'}\nNext step: {exp['next_step'] or '—'}\n"
            f"Runbooks: {', '.join(exp['runbook_refs']) or '—'} · Incidents: {', '.join(exp['incident_refs']) or '—'}\n"
            f"For: {who}. Explanation {exp['explanation_id']} ({exp['status']}).")
    con.execute("""insert into audit.alerts (alert_id, business_date, break_id, channel, severity, title, body)
                   values (%s,%s,%s,%s,%s,%s,%s)""",
                (aid, brk["business_date"], brk["break_id"], settings["alerts"]["channel"], brk["severity"], title, body))
    return True


def send_pending(settings: Settings) -> int:
    """Send outbox alerts to Slack if SLACK_WEBHOOK_URL is set (never in the demo). Returns how many were sent."""
    url = os.getenv(settings["alerts"]["slack_webhook_env"])
    if settings["alerts"]["channel"] != "slack" or not url:
        return 0
    n = 0
    with connect(settings) as con:
        for a in con.execute("select alert_id, title, body from audit.alerts where not sent order by ts").fetchall():
            req = urllib.request.Request(url, data=json.dumps({"text": f"*{a['title']}*\n{a['body']}"}).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            con.execute("update audit.alerts set sent = true, sent_at = now() where alert_id = %s", (a["alert_id"],))
            n += 1
        con.commit()
    return n


# ---------------------------------------------------------------- the whole check
def breaks_for(con, business_date: str) -> list[dict]:
    return [dict(r) for r in con.execute(
        """select break_id, business_date::text as business_date, break_type, severity, entity, book, metric,
                  expected, actual, diff, hints, detail from marts.breaks where business_date = %s
           order by case severity when 'critical' then 0 when 'high' then 1 else 2 end, break_type, entity""",
        (business_date,)).fetchall()]


def run_eod(settings: Settings, business_date: str, as_of_time: str = "21:00", actor: str = "cli",
            trigger: str = "cli", alias: str | None = None, unavailable: set[str] | None = None,
            reload: bool = True, explain: bool = True, run_id: str | None = None, dbt_result: dict | None = None,
            use_cache: bool = True) -> dict:
    """load → dbt build (gate) → breaks for the date → explain each → alerts → audit + governance event."""
    telemetry.require_enabled("eod-check", actor)
    t0 = time.perf_counter()
    run_id = run_id or f"{trigger}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:4]}"
    alias = alias or settings["llm"]["primary_alias"]
    as_of = f"{business_date} {as_of_time}"
    if reload:
        load(settings)
    dbt = dbt_result or run_dbt(settings, as_of)   # evals build once for all dates and pass the result in
    result = {"run_id": run_id, "business_date": business_date, "as_of": as_of, "dbt": dbt, "breaks": [],
              "explanations": {}, "alerts": 0, "cost_usd": 0.0, "status": "ok"}
    with connect(settings) as con:
        con.execute(SCHEMA)
        if not dbt["ok"]:   # DATA-02: no explanations from data that failed its tests
            result["status"] = "blocked_dq"
        else:
            result["breaks"] = breaks_for(con, business_date)
            ver = kb.active_version(con)
            if explain and result["breaks"]:
                if not ver:
                    raise RuntimeError("Knowledge base not indexed: run `eodhb kb-index`")
                reg = Registry(ROOT / "config" / "models.yaml")
                c = settings["cost"]
                client = LLMClient(reg, Budget(c["max_usd_per_run"], c["max_input_tokens_per_call"],
                                               c["allow_unpriced_models"]), settings["llm"]["retries"], unavailable)
                for b in result["breaks"]:
                    e = explain_break(settings, con, reg, client, b, alias, run_id, ver["kb_version"], use_cache)
                    result["explanations"][b["break_id"]] = e
                    result["alerts"] += post_alert(settings, con, b, e)
                result["cost_usd"] = round(client.budget.spent, 6)
        exps = list(result["explanations"].values())
        result["summary"] = {
            "breaks": len(result["breaks"]),
            "critical": sum(b["severity"] == "critical" for b in result["breaks"]),
            "explained": sum(e["status"] == "explained" for e in exps),
            "needs_human": sum(e["status"] == "needs_human" for e in exps),
            "degraded": sum(e["status"] == "degraded" for e in exps),
            "nav_signoff": nav_status(con, business_date, as_of_time, settings) if dbt["ok"] else "blocked: data tests failed",
        }
        con.execute("""insert into audit.runs (run_id, business_date, as_of, actor, trigger, status, dbt_status, breaks,
                       explained, needs_human, alerts, cost_usd, detail) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (run_id, business_date, as_of, actor, trigger, result["status"], dbt["summary"],
                     len(result["breaks"]), result["summary"]["explained"], result["summary"]["needs_human"],
                     result["alerts"], result["cost_usd"], json.dumps(result["summary"])))
        con.commit()
    result["seconds"] = round(time.perf_counter() - t0, 1)
    flags = sorted({f for e in exps for f in e["flags"]} | ({"critical_break"} if result["summary"]["critical"] else set()))
    tokens_in = sum(e["input_tokens"] for e in exps)
    tokens_out = sum(e["output_tokens"] for e in exps)
    telemetry.record("eod-check", actor=actor, run_id=run_id, status=result["status"],
                     model=next((e["model_name"] for e in exps if e["model_name"]), ""),
                     input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=result["cost_usd"],
                     latency_ms=int(result["seconds"] * 1000), items=len(result["breaks"]),
                     rows_in=_rows_landed(settings, business_date), flags=flags,
                     detail={"business_date": business_date, "as_of": as_of, "trigger": trigger, **result["summary"]})
    return result


def _rows_landed(settings: Settings, business_date: str) -> int:
    p = settings.landing_dir / business_date / "arrivals.csv"
    if not p.exists():
        return 0
    return sum(int(r.split(",")[3]) for r in p.read_text().splitlines()[1:] if r.count(",") >= 3)


def nav_status(con, business_date: str, as_of_time: str, settings: Settings) -> str:
    crit = con.execute("""select count(*) as n from marts.breaks where business_date = %s and severity = 'critical'""",
                       (business_date,)).fetchone()["n"]
    pending = con.execute("""select count(*) as n from marts.file_sla where business_date = %s and critical
                             and status = 'pending'""", (business_date,)).fetchone()["n"]
    high = con.execute("""select count(*) as n from marts.breaks where business_date = %s and severity = 'high'""",
                       (business_date,)).fetchone()["n"]
    if crit:
        return f"blocked: {crit} critical break(s)"
    if pending:
        return f"waiting: {pending} critical feed(s) not due yet"
    return (f"at risk: {high} high break(s) open (sign-off target {settings['nav_signoff_time']} ET)" if high
            else "ready for sign-off")


def record_feedback(settings: Settings, explanation_id: str, rating: str, actor: str, note: str = "") -> None:
    """HITL-03: on-call marks an explanation useful / wrong; 'wrong' ones become golden-set candidates."""
    with connect(settings) as con:
        b = con.execute("select break_id from audit.explanations where explanation_id = %s", (explanation_id,)).fetchone()
        con.execute("insert into audit.feedback (explanation_id, break_id, rating, actor, note) values (%s,%s,%s,%s,%s)",
                    (explanation_id, b["break_id"] if b else None, rating, actor, note))
        con.commit()
    telemetry.record("feedback", event_type="feedback", actor=actor, status=rating, detail={"explanation_id": explanation_id})
