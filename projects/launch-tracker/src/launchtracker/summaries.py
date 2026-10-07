"""Cited AI summaries (FR-6): a mission in plain English, a weekly digest, and what changed since the last refresh.

The same path for all three: governance kill switch → facts from SQL → untrusted text screened and delimited →
budgeted model call (aliases only) → strict parse → every citation and number checked against the facts → accepted, or
replaced by a plain template built from the same facts and labelled as such. Everything is logged (OBS-01).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import analytics, guardrails, telemetry
from .config import ROOT, Settings, sha, utcnow
from .db import rows, scalar
from .llm import Budget, BudgetExceeded, LLMClient, Registry


@dataclass
class Result:
    purpose: str
    subject: str
    text: str
    accepted: bool
    source: str                      # "model" or "template"
    problems: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    model: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    facts: dict = field(default_factory=dict)


def new_run_id() -> str:
    return utcnow().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]


def client(settings: Settings, budget_usd: float | None = None) -> LLMClient:
    c = settings["cost"]
    return LLMClient(Registry(ROOT / "config" / "models.yaml"),
                     Budget(budget_usd or c["max_usd_per_run"], c["max_input_tokens_per_call"], c["allow_unpriced_models"]),
                     settings["llm"]["retries"])


def _prompt(settings: Settings, key: str) -> tuple[str, str, str]:
    path = settings["llm"]["prompts"][key]
    text = (ROOT / path).read_text()
    return text, path.rsplit("/", 1)[-1].replace(".md", ""), sha(text)


def _daily_spend(con) -> float:
    return scalar(con, "select coalesce(sum(cost_usd), 0) from audit.ai_calls where call_ts > ?",
                  [utcnow() - timedelta(days=1)]) or 0.0


def _run(con, settings: Settings, purpose: str, prompt_key: str, subject: str, facts: dict, template: str,
         description: str | None = None, alias: str | None = None, llm: LLMClient | None = None,
         run_id: str | None = None, actor: str = "") -> Result:
    run_id = run_id or new_run_id()
    alias = alias or settings["llm"]["summary_alias"]
    flags: list[str] = []
    telemetry.require_enabled(purpose, actor=actor)          # the kill switch, in the code path
    if _daily_spend(con) >= settings["cost"]["daily_budget_usd"]:
        raise BudgetExceeded(f"daily AI budget ${settings['cost']['daily_budget_usd']:.2f} reached (COST-01)")
    system, pver, psha = _prompt(settings, prompt_key)
    desc_block = ""
    if description is not None:
        clean, f = guardrails.sanitize(description, settings["guard"]["max_description_chars"])
        if f["injection_suspected"]:
            flags.append("injection_suspected")
            if settings["guard"]["drop_description_on_injection"]:
                clean = "[withheld: the description contained instruction-like text]"
        desc_block = f"\n<description>\n{clean}\n</description>"
    facts_json = json.dumps(facts, default=str, sort_keys=True)
    user = f"<facts>\n{facts_json}\n</facts>{desc_block}"
    llm = llm or client(settings)
    res = Result(purpose, subject, template, False, "template", flags=flags, facts=facts)
    status, err = "ok", None
    try:
        out = llm.complete(alias, system, user, settings["llm"]["max_output_tokens"],
                           fallback_alias=settings["llm"]["fallback_alias"])
        res.model, res.cost_usd = out.model.name, out.cost_usd
        res.input_tokens, res.output_tokens = out.input_tokens, out.output_tokens
        if out.used_fallback:
            flags.append("fallback_model")
        try:
            draft = guardrails.parse(out.text)
            problems = guardrails.check(draft, facts)
        except Exception as e:                               # SEC-04: off-contract output is rejected
            draft, problems = None, [f"output not in the schema: {e}"]
        if draft and not problems:
            res.text, res.accepted, res.source = draft.text, True, "model"
            res.citations = [c.model_dump() for c in draft.citations]
        else:
            res.problems = problems
            flags.append("draft_rejected")
            status = "rejected"
        log_call(con, run_id=run_id, purpose=purpose, subject=subject, alias=alias, spec=out.model,
                 prompt_version=pver, prompt_sha=psha, input_sha=sha(user), tin=out.input_tokens,
                 tout=out.output_tokens, cost=out.cost_usd, latency=out.latency_ms, fallback=out.used_fallback,
                 status=status, flags=flags)
    except BudgetExceeded:
        raise
    except Exception as e:
        status, err = "error", str(e)
        res.problems = [f"model unavailable: {e}"]
        flags.append("model_error")
        log_call(con, run_id=run_id, purpose=purpose, subject=subject, alias=alias, spec=None, prompt_version=pver,
                 prompt_sha=psha, input_sha=sha(user), status="error", flags=flags, error=err)
    res.flags = flags
    con.execute("insert into audit.summaries values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [run_id, utcnow(), purpose, subject, res.text, json.dumps(res.citations), res.accepted,
                 json.dumps(res.problems), res.model])
    telemetry.record(purpose, actor=actor, status="ok" if res.accepted else "fallback", run_id=run_id,
                     model=res.model, input_tokens=res.input_tokens, output_tokens=res.output_tokens,
                     cost_usd=res.cost_usd, items=1, rows_in=len(facts), flags=flags)
    return res


def log_call(con, *, run_id, purpose, subject, alias, spec, prompt_version, prompt_sha, input_sha, tin=0, tout=0,
             cost=0.0, latency=0, fallback=False, status="ok", flags=None, error=None) -> None:
    con.execute("insert into audit.ai_calls values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [run_id, utcnow(), purpose, subject, alias, getattr(spec, "name", None), getattr(spec, "provider", None),
                 getattr(spec, "model_id", None), prompt_version, prompt_sha, input_sha, tin, tout, cost, latency,
                 fallback, status, json.dumps(flags or []), error])


# ---------------------------------------------------------------- the three summaries
def mission_facts(detail: dict) -> dict:
    """Only the fields a summary needs (DATA-03 minimisation), with dates as plain strings."""
    L = detail["launch"]
    facts = {"launch": {k: L.get(k) for k in ("launch_id", "name", "mission_name", "rocket", "provider", "location",
                                               "mission_type", "orbit", "outcome", "destination", "program")}}
    facts["launch"]["net_date"] = L["net"].date().isoformat() if L.get("net") else None
    b = next((s for s in detail["stages"] if s.get("serial")), None)
    if b:
        facts["booster"] = {"serial": b["serial"], "flight_number": b["flight_number"],
                            "landing_success": b["landing_success"]}
    if detail["crew"]:
        facts["crew_count"] = len(detail["crew"])
        facts["commander"] = next((c["name"] for c in detail["crew"] if "ommander" in (c["role"] or "")), None)
    sd = next((c for c in detail["spacecraft"] if c.get("splashdown") and c.get("landing_success")), None)
    if sd:
        facts["splashdown"] = sd["landing_location"]
    if detail["cost"]["status"] == "PUBLIC":
        e = detail["cost"]["entry"]
        facts["cost"] = {"amount_usd": e["amount_usd"], "unit": e["unit"], "source": e["source"]}
    return {k: v for k, v in facts.items() if v is not None}


def mission_template(f: dict) -> str:
    L = f["launch"]
    verb = {"success": "launched successfully", "failure": "failed", "partial": "was a partial failure",
            "pending": "is scheduled to launch"}.get(L["outcome"], "launched")
    return f"{L.get('mission_name') or L['name']} {verb} on a {L['rocket']} from {L['location']} on {L['net_date']}."


def mission(con, settings: Settings, launch_id: str, **kw) -> Result:
    d = analytics.launch(con, settings, launch_id)
    if not d:
        raise KeyError(launch_id)
    f = mission_facts(d)
    return _run(con, settings, "mission_summary", "mission", launch_id, f, mission_template(f),
                description=d["launch"].get("mission_description"), **kw)


def digest_facts(con, week_start: date) -> dict:
    end = week_start + timedelta(days=7)
    r = rows(con, """select count(*) as launches, count(*) filter (where outcome = 'success') as successes,
                     count(*) filter (where outcome in ('failure', 'partial')) as failures,
                     count(*) filter (where crewed) as crewed from launches
                     where net >= ? and net < ? and outcome <> 'pending'""", [week_start, end])[0]
    r["landings"] = scalar(con, """select count(*) from stages s join launches l using (launch_id)
                                   where s.landing_success and l.net >= ? and l.net < ?""", [week_start, end])
    top = rows(con, """select provider, count(*) n from launches where net >= ? and net < ? and outcome <> 'pending'
                       group by 1 order by 2 desc, 1 limit 1""", [week_start, end])
    if top:
        r["top_provider"], r["top_provider_launches"] = top[0]["provider"], top[0]["n"]
    r.update({"week_start": week_start.isoformat(), "week_end": (end - timedelta(days=1)).isoformat()})
    return r


def digest(con, settings: Settings, week_start: date | None = None, **kw) -> Result:
    now = settings.now()
    week_start = week_start or (now.date() - timedelta(days=now.weekday() + 7))   # last full week, Monday start
    f = digest_facts(con, week_start)
    t = (f"{f['launches']} launches in the week from {f['week_start']} to {f['week_end']}: "
         f"{f['successes']} succeeded, {f['failures']} did not.")
    return _run(con, settings, "weekly_digest", "digest", f"week:{f['week_start']}", f, t, **kw)


def changes_facts(con) -> dict:
    """Launches whose target time differs between their last two snapshots."""
    r = rows(con, """with s as (select launch_id, seen_at, net, row_number() over (partition by launch_id order by seen_at desc) rn
                                from net_snapshots)
                     select l.name, b.net as from_net, a.net as to_net,
                            round(epoch(a.net - b.net) / 86400, 1) as days
                     from s a join s b on a.launch_id = b.launch_id and a.rn = 1 and b.rn = 2
                     join launches l on l.launch_id = a.launch_id
                     where a.net <> b.net order by abs(epoch(a.net - b.net)) desc""")
    return {"count": len(r), "changes": [{"name": x["name"], "from_date": x["from_net"].date().isoformat(),
                                          "to_date": x["to_net"].date().isoformat(), "days": x["days"]} for x in r]}


def what_changed(con, settings: Settings, **kw) -> Result:
    f = changes_facts(con)
    t = f"{f['count']} launches changed target time since the previous refresh."
    return _run(con, settings, "what_changed", "changes", "changes", f, t, **kw)
