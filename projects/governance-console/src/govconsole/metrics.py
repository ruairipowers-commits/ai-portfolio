"""Aggregations behind the dashboards: KPIs, daily series, budgets, anomalies, actors and control evidence.

All numbers come from SQL over the events table; this module only shapes them. Definitions:
  run              any event that isn't a visit, a human decision or a blocked attempt (an AI or system execution)
  human decision   review / approve / reject / feedback
  active user      distinct named people and anonymous demo visitors (services excluded)
  budget use       trailing-30-day spend ÷ monthly budget (stable early in a month, unlike month-to-date)
  anomaly          a day whose cost > anomaly_factor × the trailing 14-day median for that workflow
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
VISIT = ("visit",)
HUMAN = ("review", "approve", "reject", "feedback")
NOT_RUN = VISIT + HUMAN + ("register",)
ESCALATED = ("escalated", "refused", "needs_human")   # handed to a person instead of completed by the AI
BLOCKED = ("blocked", "blocked_dq")                    # stopped by a control before any model call
ERRORS = ("error", "write_failed")

# Which events evidence which control (shown next to the static mapping from docs/governance.md).
EVIDENCE = {
    "DATA-02": ("flag", ["dq_gate_failed"], "runs blocked by the data-quality gate"),
    "DATA-03": ("flag", ["pii_redacted"], "runs where PII was redacted"),
    "DATA-04": ("flag", ["licence_excluded"], "answers that excluded licence-restricted documents"),
    "DATA-05": ("event", ["ingest"], "index builds recorded"),
    "SEC-02": ("flag", ["injection_detected", "quarantined_content", "bank_change_request"],
               "injection / fraud attempts caught"),
    "SEC-03": ("flag", ["entitlement_filtered"], "retrievals narrowed by entitlement"),
    "COST-01": ("flag", ["budget_blocked", "step_or_budget_cap"], "runs stopped by a budget or step cap"),
    "COST-02": ("cost", [], "AI spend attributed to a workflow, model and person"),
    "COST-04": ("budget", [], "trailing-30-day spend vs monthly budget"),
    "MODEL-02": ("eval", [], "latest eval gate"),
    "EVAL-03": ("eval", [], "latest eval gate"),
    "OBS-01": ("count", [], "events in the run log"),
    "OBS-02": ("flag", ["citation_error", "evidence_mismatch"], "outputs whose citations failed verification"),
    "HITL-02": ("event", ["approve", "reject", "review"], "named human decisions"),
    "HITL-03": ("flag", ["human_override", "marked_wrong", "edited_by_human"], "human overrides / corrections captured"),
}


def load_settings() -> dict:
    return yaml.safe_load((PKG_ROOT / "config" / "settings.yaml").read_text())


def load_workflow_config() -> dict:
    return yaml.safe_load((PKG_ROOT / "config" / "workflows.yaml").read_text())


def wf_config(slug: str, cfg: dict | None = None) -> dict:
    cfg = cfg or load_workflow_config()
    return {**cfg["defaults"], **(cfg.get("workflows") or {}).get(slug, {})}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _where(start: str, end: str, workflow: str | None, include_simulated: bool, environment: str | None):
    sql, p = ["day >= ?", "day <= ?"], [start, end]
    if workflow:
        sql.append("workflow = ?"), p.append(workflow)
    if not include_simulated:
        sql.append("source = 'live'")
    if environment:
        sql.append("environment = ?"), p.append(environment)
    return " and ".join(sql), p


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    values = sorted(values)
    return int(values[min(len(values) - 1, int(round(0.95 * (len(values) - 1))))])


def _kpis(store, where: str, p: list) -> dict:
    r = store.query(f"""
        select coalesce(sum(cost_usd), 0) as cost,
               sum(case when event_type not in {NOT_RUN} and status not in {BLOCKED} then 1 else 0 end) as runs,
               sum(case when event_type in {HUMAN} then 1 else 0 end) as decisions,
               sum(case when event_type = 'visit' then 1 else 0 end) as visits,
               sum(case when status in {BLOCKED} then 1 else 0 end) as blocked,
               sum(case when status in {ERRORS} then 1 else 0 end) as errors,
               sum(case when status in {ESCALATED} then 1 else 0 end) as escalated,
               coalesce(sum(input_tokens + output_tokens), 0) as tokens,
               coalesce(sum(records_in), 0) as records_in, coalesce(sum(records_out), 0) as records_out,
               count(distinct case when actor_type in ('named', 'visitor') then actor end) as users,
               count(*) as events
        from events where {where}""", p)[0]
    lat = [x["latency_ms"] for x in store.query(
        f"select latency_ms from events where {where} and latency_ms > 0 and event_type not in {NOT_RUN}", p)]
    runs = r["runs"] or 0
    return {**{k: (v or 0) for k, v in r.items()}, "cost": round(r["cost"] or 0, 4), "p95_latency_ms": _p95(lat),
            "error_rate": round((r["errors"] or 0) / runs, 4) if runs else 0.0,
            "escalation_rate": round((r["escalated"] or 0) / runs, 4) if runs else 0.0}


def summary(store, catalog: dict, days: int = 30, workflow: str | None = None, include_simulated: bool = True,
            environment: str | None = None, end: date | None = None) -> dict:
    end = end or _today()
    start = end - timedelta(days=days - 1)
    where, p = _where(start.isoformat(), end.isoformat(), workflow, include_simulated, environment)
    prev_where, prev_p = _where((start - timedelta(days=days)).isoformat(), (start - timedelta(days=1)).isoformat(),
                                workflow, include_simulated, environment)
    kpi, prev = _kpis(store, where, p), _kpis(store, prev_where, prev_p)

    known = [w["slug"] for w in catalog["workflows"]]
    seen = [r["workflow"] for r in store.query(f"select distinct workflow from events where {where}", p)]
    order = known + sorted(w for w in seen if w not in known)
    daily = store.query(f"""
        select day, workflow, sum(cost_usd) as cost,
               sum(case when event_type not in {NOT_RUN} and status not in {BLOCKED} then 1 else 0 end) as runs,
               sum(records_in) as records_in, sum(records_out) as records_out,
               sum(case when status in {ESCALATED} then 1 else 0 end) as escalated,
               sum(case when status in {ERRORS} then 1 else 0 end) as errors
        from events where {where} group by day, workflow""", p)
    days_list = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    by = {(r["day"], r["workflow"]): r for r in daily}
    series = {}
    for metric in ("cost", "runs", "records_in", "escalated", "errors"):
        series[metric] = {w: [round(float((by.get((d, w)) or {}).get(metric) or 0), 6) for d in days_list]
                          for w in order if any((d, w) in by for d in days_list)}
    total_by_day = [sum(series["cost"][w][i] for w in series["cost"]) for i in range(days)]
    cumulative, acc = [], 0.0
    for v in total_by_day:
        acc += v
        cumulative.append(round(acc, 4))

    flags = Counter()
    for r in store.query(f"select flags, count(*) as n from events where {where} and flags not in ('', '[]') group by flags", p):
        for f in json.loads(r["flags"] or "[]"):
            flags[f] += r["n"]
    by_model = store.query(f"""select model, sum(cost_usd) as cost, count(*) as calls,
                                      sum(input_tokens) as input_tokens, sum(output_tokens) as output_tokens
                               from events where {where} and model <> '' group by model order by cost desc""", p)
    return {"start": start.isoformat(), "end": end.isoformat(), "days": days_list, "kpi": kpi, "prev": prev,
            "series": series, "cumulative_cost": cumulative, "workflow_order": order, "flags": dict(flags.most_common()),
            "by_model": by_model, "unregistered": [w for w in seen if w not in known]}


def workflow_table(store, catalog: dict, include_simulated: bool = True, end: date | None = None) -> list[dict]:
    end = end or _today()
    s = load_settings()
    cfg = load_workflow_config()
    state = store.effective_state()
    meta = store.workflow_meta()
    att = store.latest_attestations(include_simulated)
    stale_before = (end - timedelta(days=s["attestation"]["stale_after_days"])).isoformat()
    src = "" if include_simulated else "and source = 'live'"
    start30 = (end - timedelta(days=29)).isoformat()
    agg = {r["workflow"]: r for r in store.query(f"""
        select workflow, sum(cost_usd) as cost30, count(distinct case when actor_type in ('named','visitor') then actor end) as users,
               sum(case when event_type not in {NOT_RUN} and status not in {BLOCKED} then 1 else 0 end) as runs,
               sum(case when status in {ERRORS} then 1 else 0 end) as errors,
               sum(case when status in {ESCALATED} then 1 else 0 end) as escalated,
               sum(records_in) as records_in,
               max(case when event_type not in {NOT_RUN} then ts end) as last_run
        from events where day >= ? and day <= ? {src} group by workflow""", (start30, end.isoformat()))}
    anomalies = detect_anomalies(store, end=end, include_simulated=include_simulated)
    rows = []
    known = {w["slug"] for w in catalog["workflows"]}
    for w in catalog["workflows"] + [{"slug": u, "name": u, "emoji": "❓", "status": "unregistered", "built": False,
                                      "risk_tier": (meta.get(u, {}).get("risk_tier") or "unrated") + (" (self-declared)" if u in meta else ""),
                                      "controls": {}}
                                     for u in agg if u not in known]:
        a = agg.get(w["slug"], {})
        c = wf_config(w["slug"], cfg)
        st = state.get(w["slug"])
        statuses = Counter(v["status"] for v in w.get("controls", {}).values())
        runs = a.get("runs") or 0
        budget = float(c["monthly_budget_usd"])
        cost30 = round(float(a.get("cost30") or 0), 2)
        rows.append({
            "slug": w["slug"], "name": w.get("name", w["slug"]), "emoji": w.get("emoji", "🤖"),
            "registered": w["slug"] in known, "lifecycle": w.get("status", ""), "built": w.get("built", False),
            "risk_tier": w.get("risk_tier", ""), "owner": c["owner"], "technical_owner": c["technical_owner"],
            "enabled": bool(st["enabled"]) if st else s["kill_switch"]["default_enabled"],
            "state_reason": (st or {}).get("reason") or "", "state_by": (st or {}).get("changed_by") or "",
            "state_at": (st or {}).get("changed_at") or "", "state_expires": (st or {}).get("expires_at") or "",
            "attested": sum(1 for cid in w.get("controls", {}) if (w["slug"], cid) in att
                            and att[(w["slug"], cid)]["verdict"] == "confirmed" and att[(w["slug"], cid)]["ts"][:10] >= stale_before),
            "attest_stale": sum(1 for cid in w.get("controls", {}) if (w["slug"], cid) in att
                                and att[(w["slug"], cid)]["ts"][:10] < stale_before),
            "attest_exceptions": sum(1 for cid in w.get("controls", {}) if (w["slug"], cid) in att
                                     and att[(w["slug"], cid)]["verdict"] == "exception"),
            "declared": meta.get(w["slug"], {}),
            "runs_30d": runs, "users_30d": a.get("users") or 0, "cost_30d": cost30, "budget": budget,
            "budget_pct": round(100 * cost30 / budget, 1) if budget else 0.0,
            "budget_warn": bool(budget) and 100 * cost30 / budget >= s["alerts"]["budget_warn_pct"],
            "error_rate": round((a.get("errors") or 0) / runs, 4) if runs else 0.0,
            "escalation_rate": round((a.get("escalated") or 0) / runs, 4) if runs else 0.0,
            "records_in_30d": a.get("records_in") or 0, "last_run": a.get("last_run") or "",
            "controls_total": len(w.get("controls", {})),
            "controls_implemented": statuses.get("implemented", 0), "controls_partial": statuses.get("partial", 0),
            "controls_na": statuses.get("not_applicable", 0), "controls_option": statuses.get("documented_option", 0),
            "anomalies": [x for x in anomalies if x["workflow"] == w["slug"]],
        })
    return rows


def detect_anomalies(store, days: int = 30, end: date | None = None, include_simulated: bool = True) -> list[dict]:
    s = load_settings()["alerts"]
    end = end or _today()
    start = end - timedelta(days=days + 14)
    src = "" if include_simulated else "and source = 'live'"
    rows = store.query(f"select workflow, day, sum(cost_usd) as cost from events where day >= ? and day <= ? {src} "
                       "group by workflow, day", (start.isoformat(), end.isoformat()))
    per = defaultdict(dict)
    for r in rows:
        per[r["workflow"]][r["day"]] = float(r["cost"] or 0)
    out = []
    for wf, by_day in per.items():
        for i in range(days):
            d = end - timedelta(days=days - 1 - i)
            hist = [by_day.get((d - timedelta(days=k)).isoformat(), 0.0) for k in range(1, 15)]
            hist = [h for h in hist if h > 0]
            cost = by_day.get(d.isoformat(), 0.0)
            if len(hist) >= 5 and cost >= s["anomaly_min_usd"]:
                med = statistics.median(hist)
                if cost > s["anomaly_factor"] * med:
                    out.append({"workflow": wf, "day": d.isoformat(), "cost": round(cost, 2), "median": round(med, 2),
                                "factor": round(cost / med, 1)})
    return out


def actors(store, workflow: str | None, days: int = 30, include_simulated: bool = True, limit: int = 50) -> list[dict]:
    end = _today()
    where, p = _where((end - timedelta(days=days - 1)).isoformat(), end.isoformat(), workflow, include_simulated, None)
    return store.query(f"""
        select actor, actor_type, count(*) as events,
               sum(case when event_type not in {NOT_RUN} and status not in {BLOCKED} then 1 else 0 end) as runs,
               sum(case when event_type in {HUMAN} then 1 else 0 end) as decisions,
               round(sum(cost_usd), 4) as cost, max(ts) as last_seen, count(distinct workflow) as workflows
        from events where {where} group by actor, actor_type order by events desc limit {int(limit)}""", p)


def recent_events(store, workflow: str | None = None, limit: int = 100, include_simulated: bool = True,
                  actor: str | None = None, status: str | None = None, event_type: str | None = None) -> list[dict]:
    sql, p = ["1=1"], []
    for col, val in (("workflow", workflow), ("actor", actor), ("status", status), ("event_type", event_type)):
        if val:
            sql.append(f"{col} = ?"), p.append(val)
    if not include_simulated:
        sql.append("source = 'live'")
    rows = store.query(f"select * from events where {' and '.join(sql)} order by ts desc limit {int(limit)}", p)
    for r in rows:
        r["flags"] = json.loads(r["flags"] or "[]")
        r["detail"] = json.loads(r["detail"] or "{}")
    return rows


def control_evidence(store, slug: str, days: int = 30, include_simulated: bool = True) -> dict[str, str]:
    """Live evidence per control for one workflow, e.g. 'SEC-02': '14 injection / fraud attempts caught (30d)'."""
    end = _today()
    where, p = _where((end - timedelta(days=days - 1)).isoformat(), end.isoformat(), slug, include_simulated, None)
    flag_counts = Counter()
    for r in store.query(f"select flags, count(*) as n from events where {where} and flags not in ('', '[]') group by flags", p):
        for f in json.loads(r["flags"] or "[]"):
            flag_counts[f] += r["n"]
    types = {r["event_type"]: r["n"] for r in store.query(
        f"select event_type, count(*) as n from events where {where} group by event_type", p)}
    total = sum(types.values())
    cost = store.query(f"select coalesce(sum(cost_usd),0) as c, count(*) as n from events where {where} and cost_usd > 0", p)[0]
    last_eval = store.query("select ts, status, model from events where workflow = ? and event_type = 'eval' "
                            + ("" if include_simulated else "and source = 'live' ") + "order by ts desc limit 1", (slug,))
    budget = wf_config(slug)["monthly_budget_usd"]
    out = {}
    for cid, (kind, keys, label) in EVIDENCE.items():
        if kind == "flag":
            n = sum(flag_counts[k] for k in keys)
            out[cid] = f"{n:,} {label} ({days}d)"
        elif kind == "event":
            out[cid] = f"{sum(types.get(k, 0) for k in keys):,} {label} ({days}d)"
        elif kind == "cost":
            out[cid] = f"${cost['c']:,.2f} across {cost['n']:,} costed events ({days}d)"
        elif kind == "budget":
            out[cid] = f"${cost['c']:,.2f} of ${float(budget):,.0f}/month budget ({days}d)"
        elif kind == "eval":
            out[cid] = (f"{'PASS' if last_eval[0]['status'] == 'ok' else 'FAIL'} on {last_eval[0]['ts'][:10]}"
                        f" ({last_eval[0]['model'] or 'model n/a'})") if last_eval else "no eval recorded"
        elif kind == "count":
            out[cid] = f"{total:,} events logged ({days}d)"
    return out
