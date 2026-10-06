"""Budget & ROI (FR-7) and migration & retirement (FR-8).

ROI numbers come from the semantic layer (spend, queries, cost per query over one window). Retirement is
impact-checked against the graph: what reads from the dataset, which metrics and reports depend on it, who is
entitled to it. Anything with dependants needs a mapped substitute; every retirement needs a named approver, and
leaves an archive record.
"""
from __future__ import annotations

import json
from datetime import timedelta

from sqlmodel import Session, select

from . import graph, licensing, semantic, store, telemetry
from .config import Settings, now
from .context import roi_window


def roi(settings: Settings, customer_id: str | None = None) -> list[dict]:
    start, end = roi_window(settings)
    where = {}
    if customer_id:
        with store.session(settings) as s:
            where = {"customer__customer_name": s.get(store.Customer, customer_id).name}
    r = semantic.query(settings, ["spend_usd", "queries", "cost_per_query"], ["dataset__title"], where, start, end)
    thr = settings["lifecycle"]["retire_if_cost_per_query_above"]
    with store.session(settings) as s:
        titles = {d.title: d for d in s.exec(select(store.Dataset)).all()}
    out = []
    for row in r.rows:
        d = titles.get(row["dataset__title"])
        cpq = row.get("cost_per_query")
        flag = []
        if cpq is not None and cpq > thr:
            flag.append(f"cost per query above ${thr:,.0f}")
        if (row.get("queries") or 0) == 0 and (row.get("spend_usd") or 0) > 0:
            flag.append("paid for, not used")
        out.append({"dataset_id": d.id if d else None, "title": row["dataset__title"], "spend_usd": row.get("spend_usd"),
                    "queries": row.get("queries"), "cost_per_query": cpq, "flags": flag,
                    "window": f"{start} to {end}", "query_id": r.query_id})
    return sorted(out, key=lambda x: -(x["cost_per_query"] or 0))


def budget(settings: Settings, customer_id: str) -> dict:
    with store.session(settings) as s:
        c = s.get(store.Customer, customer_id)
        contracts = [k for k in store.tenant(s, store.Contract, customer_id) if k.status == "active"]
        renewals = licensing.renewals(s, settings, customer_id)
    annual = sum(k.price_usd * 365 / ((k.end - k.start).days + 1) for k in contracts)
    return {"customer": c.name, "budget_usd": c.budget_usd, "annualised_commitments_usd": round(annual, 2),
            "headroom_usd": round(c.budget_usd - annual, 2), "over_budget": annual > c.budget_usd,
            "alert": annual > c.budget_usd * 0.9, "renewals": renewals}


def candidates(settings: Settings, customer_id: str) -> list[dict]:
    """Retirement and migration candidates: expensive per use, or overlapping a cheaper dataset already held."""
    out = []
    held = set(graph.held_by(settings, customer_id))
    for r in roi(settings, customer_id):
        if not r["dataset_id"]:
            continue
        subs = [x for x in graph.substitutes(settings, r["dataset_id"]) if x["dataset_id"] in held] \
            if (r["spend_usd"] or 0) > 0 else []          # only suggest moving off something we pay for
        if r["flags"] or subs:
            out.append({**r, "substitutes_held": [x["dataset_id"] for x in subs],
                        "suggestion": "migrate to " + subs[0]["dataset_id"] if subs else "retire at term end"})
    return out


def blockers(settings: Settings, dataset_id: str, customer_id: str | None) -> dict:
    imp = graph.impact(settings, dataset_id)
    if customer_id is None:
        hard = {"metrics": imp["metrics"], "reports": imp["reports"],
                "contracts": imp["active_contracts"], "assets": imp["assets"]}
    else:
        reports = [r["n"] for r in graph.sparql(settings, f"""SELECT ?n WHERE {{ ?r dlp:dependsOn <{graph.iri('dataset', dataset_id)}> ;
            dlp:name ?n ; dlp:ownedBy ?t . ?t dlp:memberOf <{graph.iri('customer', customer_id)}> }}""")]
        hard = {"reports": reports}
    return {"impact": imp, "blocking": {k: v for k, v in hard.items() if v}}


def request_retirement(settings: Settings, dataset_id: str, actor: str, customer_id: str | None = None,
                       substitute: str | None = None) -> dict:
    b = blockers(settings, dataset_id, customer_id)
    if substitute:
        valid = {x["dataset_id"] for x in graph.substitutes(settings, dataset_id)}
        if substitute not in valid:
            return {"status": "BLOCKED", "reason": f"{substitute} is not a known substitute for {dataset_id}", **b}
        if customer_id:
            with store.session(settings) as s:
                v = licensing.assess(s, settings, substitute, "v:InternalResearch", customer_id)
            if not v.allowed:
                return {"status": "BLOCKED", "reason": f"Substitute not usable: {'; '.join(v.reasons)}", **b}
    elif b["blocking"]:
        return {"status": "BLOCKED", "reason": "Has dependants and no substitute is mapped: " +
                "; ".join(f"{k}: {', '.join(map(str, v))}" for k, v in b["blocking"].items()), **b}
    with store.session(settings) as s:
        a = store.Approval(id=store.new_id("ap"), kind="retirement", subject_id=dataset_id, customer_id=customer_id,
                           payload={"substitute": substitute, "impact": b["impact"], "blocking": b["blocking"]},
                           requested_by=actor)
        s.add(a)
        s.commit()
    telemetry.record("retire_request", actor=actor, items=1)
    return {"status": "PENDING_APPROVAL", "approval_id": a.id, **b}


def apply_retirement(s: Session, a: store.Approval, reviewer: str) -> None:
    from .config import workspace

    ds_id, cust, sub = a.subject_id, a.customer_id, a.payload.get("substitute")
    if cust:                                           # the firm stops using it: no renewal, consumers move
        for c in store.tenant(s, store.Contract, cust):
            if ds_id in c.datasets and c.status == "active":
                c.auto_renew = False
                c.notes = f"Retire at term end ({c.end}); approved by {reviewer}" + (f"; replaced by {sub}" if sub else "")
                s.add(c)
        for r in store.tenant(s, store.Registration, cust):
            if r.dataset_id == ds_id:
                r.status = "retired"
                s.add(r)
        dep = s.get(store.Dependency, ds_id)
        if dep and sub:
            teams = {t.id for t in store.tenant(s, store.Team, cust)}
            moved = [t for t in dep.consumers if t in teams]
            dep.consumers = [t for t in dep.consumers if t not in teams]
            s.add(dep)
            target = s.get(store.Dependency, sub) or store.Dependency(dataset_id=sub)
            target.consumers = sorted(set(target.consumers) | set(moved))
            target.reports = sorted(set(target.reports) | set(dep.reports))
            dep.reports = []
            s.add(target)
    else:                                              # delisted from the marketplace
        d = s.get(store.Dataset, ds_id)
        d.status = "retired"
        s.add(d)
    archive = workspace() / "output" / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    d = s.get(store.Dataset, ds_id)
    (archive / f"{ds_id}_{cust or 'platform'}_{now():%Y%m%d%H%M%S}.json").write_text(json.dumps({
        "dataset": json.loads(d.model_dump_json()), "customer_id": cust, "substitute": sub, "approved_by": reviewer,
        "approval_id": a.id, "impact_at_retirement": a.payload.get("impact"), "retired_at": now().isoformat()},
        indent=2, default=str))
