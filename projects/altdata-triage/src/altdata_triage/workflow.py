"""The triage workflow: fetch facts -> sanitize -> LLM -> validate -> cite-check -> policy -> log.

Design note: this is a *workflow* (fixed, auditable steps) rather than an open-ended
agent. The model only drafts the memo; data access is done by code with read-only
queries (SEC-03), and every decision passes deterministic policy afterwards.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from pydantic import ValidationError

from . import guardrails as g
from .llm import BudgetExceeded, LLMClient, RegistryError
from .schemas import TriageResult, memo_json_schema
from .store import ROOT, Settings, log_call, log_result, sha

# The only columns the model may see (DATA-03 minimization). Raw panel rows never leave the warehouse.
FACT_COLUMNS = [
    "vendor_id", "vendor_name", "category", "history_years", "n_tickers", "pct_tickers_mapped",
    "core_universe_coverage", "null_rate", "gap_rate", "days_stale", "rule_score",
    "pii_present", "point_in_time", "license_derived_use", "delivery", "annual_price_usd",
]


class DataQualityGateError(RuntimeError):
    pass


def assert_dbt_tests_passed(root: Path = ROOT) -> None:
    """DATA-02: refuse to call any model unless the last dbt build fully passed."""
    rr = root / "dbt" / "target" / "run_results.json"
    if not rr.exists():
        raise DataQualityGateError("No dbt results found; run `altdata-triage transform` first.")
    results = json.loads(rr.read_text())["results"]
    bad = [r["unique_id"] for r in results if r["status"] not in ("success", "pass")]
    if bad:
        raise DataQualityGateError(f"dbt build has failing nodes, AI step blocked: {bad}")


def get_vendor_facts(con, vendor_id: str) -> dict:
    """Read-only 'tool' #1."""
    cur = con.execute(f"select {', '.join(FACT_COLUMNS)} from marts.vendor_scorecard where vendor_id = ?", [vendor_id])
    row = cur.fetchone()
    if row is None:
        raise KeyError(f"vendor {vendor_id} not in scorecard")
    return {k: (float(v) if hasattr(v, "as_integer_ratio") and not isinstance(v, (bool, int)) else v)
            for k, v in zip(FACT_COLUMNS, row)}


def get_vendor_notes(con, vendor_id: str) -> str:
    """Read-only 'tool' #2 (returns UNTRUSTED text)."""
    row = con.execute("select notes from staging.stg_vendor_questionnaires where vendor_id = ?", [vendor_id]).fetchone()
    return row[0] if row else ""


def list_vendors(con) -> list[str]:
    return [r[0] for r in con.execute("select vendor_id from marts.vendor_scorecard order by 1").fetchall()]


def build_prompt(settings: Settings) -> tuple[str, str, str]:
    path = ROOT / settings["llm"]["prompt_file"]
    template = path.read_text()
    system = template.replace("{schema}", memo_json_schema())
    return system, path.stem, sha(template)


def triage_vendor(con, vendor_id: str, settings: Settings, client: LLMClient, run_id: str,
                  alias: str | None = None) -> TriageResult:
    llm_cfg, data_cfg = settings["llm"], settings["data"]
    alias = alias or llm_cfg["primary_alias"]
    facts = get_vendor_facts(con, vendor_id)
    notes, flags = g.sanitize_untrusted(get_vendor_notes(con, vendor_id), data_cfg["max_notes_chars"],
                                        data_cfg["redact_pii"])
    system, prompt_version, prompt_sha = build_prompt(settings)
    user = (f"<vendor_facts>\n{json.dumps(facts, default=str)}\n</vendor_facts>\n"
            f"<untrusted_vendor_notes>\n{notes}\n</untrusted_vendor_notes>")

    base_log = dict(run_id=run_id, purpose="triage_memo", vendor_id=vendor_id, alias=alias,
                    prompt_version=prompt_version, prompt_sha=prompt_sha, input_sha=sha(user))
    schema_valid, cost, model_name = True, 0.0, ""
    try:
        res = client.complete(alias, system, user, llm_cfg["max_output_tokens"], llm_cfg.get("fallback_alias"))
        cost, model_name = res.cost_usd, res.model.name
        log_call(con, **base_log, model_name=res.model.name, provider=res.model.provider, model_id=res.model.model_id,
                 input_tokens=res.input_tokens, output_tokens=res.output_tokens, cost_usd=res.cost_usd,
                 latency_ms=res.latency_ms, used_fallback=res.used_fallback, status="ok")
        try:
            memo = g.parse_memo(res.text)
        except (ValueError, ValidationError) as e:
            schema_valid = False
            memo = g.fallback_memo(vendor_id, f"model output failed schema validation: {str(e)[:200]}")
    except (BudgetExceeded, RegistryError) as e:
        status = "budget_blocked" if isinstance(e, BudgetExceeded) else "not_approved"
        log_call(con, **base_log, status=status, error=str(e))
        raise
    except Exception as e:
        log_call(con, **base_log, status="error", error=str(e)[:500])
        schema_valid = False
        memo = g.fallback_memo(vendor_id, f"model call failed: {str(e)[:200]}")

    citation_errors = g.check_citations(memo, facts) if schema_valid else []
    if citation_errors:
        memo.risks.append("Memo cited values that do not match source data; treat narrative with caution")
    final, overrides = g.apply_policy(memo.recommendation, facts, flags, settings["policy"])
    if citation_errors and final == "PURSUE":
        final, overrides = "ESCALATE", overrides + ["Citation errors on a PURSUE recommendation"]

    result = TriageResult(
        memo=memo, llm_recommendation=memo.recommendation, final_recommendation=final,
        policy_overrides=overrides, citation_errors=citation_errors, schema_valid=schema_valid,
        injection_suspected=flags["injection_suspected"], pii_redactions=flags["pii_redactions"],
        model_name=model_name, cost_usd=cost,
    )
    log_result(con, run_id, result, facts["rule_score"])
    return result


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def render_memo_md(r: TriageResult, facts: dict) -> str:
    m = r.memo
    lines = [f"# Triage memo — {facts['vendor_name']} ({m.vendor_id})", "",
             f"**Final recommendation: {r.final_recommendation}**  ",
             f"Model draft: {r.llm_recommendation} (confidence {m.confidence:.2f}, model `{r.model_name}`)", ""]
    if r.policy_overrides:
        lines += ["> **Policy overrides applied:** " + "; ".join(r.policy_overrides), ""]
    lines += [m.summary, "", "## Strengths", *[f"- {s}" for s in m.strengths or ["—"]],
              "", "## Risks", *[f"- {s}" for s in m.risks or ["—"]],
              "", "## Evidence (checked against scorecard)", "| Metric | Value |", "|---|---|",
              *[f"| {e.metric} | {e.value} |" for e in m.evidence]]
    if r.citation_errors:
        lines += ["", "**Citation errors:** " + "; ".join(r.citation_errors)]
    lines += ["", "## Next steps", *[f"- {s}" for s in m.next_steps or ["—"]], "",
              "_AI-drafted, advisory only. A named reviewer must record a decision (`altdata-triage review`)._"]
    return "\n".join(lines) + "\n"
