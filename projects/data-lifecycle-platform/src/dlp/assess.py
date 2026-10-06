"""Assess and compare datasets (FR-4).

Facts are computed by code — coverage of the S&P 500 universe, history, freshness, null rates, dictionary concepts,
licence verdict, price, overlap with what the firm already holds. The model writes the narrative and alpha-use
hypotheses from those facts only (each hypothesis is labelled untested, with a way to test it). One analysis is
actually run: the IV–HV spread check on the options data, so at least one alpha claim has numbers behind it.
"""
from __future__ import annotations

import json
from datetime import date

from sqlmodel import select

from . import graph, licensing, ontology, semantic, store
from .ai import Runner
from .config import Settings
from .schemas import Assessment


def facts(settings: Settings, dataset_id: str, customer_id: str | None = None) -> dict:
    with store.session(settings) as s:
        d = s.get(store.Dataset, dataset_id)
        if d is None:
            raise KeyError(dataset_id)
        v = licensing.assess(s, settings, dataset_id, "v:InternalResearch", customer_id)
        vai = licensing.assess(s, settings, dataset_id, "v:AIProcessing", customer_id)
        held = graph.held_by(settings, customer_id) if customer_id else []
    n = graph.dataset_neighbourhood(settings, dataset_id)
    f = {"dataset_id": dataset_id, "title": d.title, "vendor": n.get("vendor"),
         "category": n.get("category"), "licence": d.licence, "licence_verdict": v.verdict,
         "ai_processing_verdict": vai.verdict, "price": d.list_price_usd or 0, "price_model": d.price_model,
         "delivery": d.delivery, "frequency": d.frequency, "fields": len(d.dictionary or []),
         "mapped_concepts": sorted({x["concept"] for x in (d.dictionary or []) if x.get("concept")}),
         "sectors_covered": len(n.get("sectors", [])), "point_in_time": (d.custom or {}).get("point_in_time"),
         "source": "declared by vendor"}
    cov = semantic.table(settings, f"select * from fct_dataset_coverage where dataset_id = '{dataset_id}'") \
        if dataset_id == "ds-options-iv" else []
    if cov:
        c = cov[0]
        last = c["last_date"]
        f |= {"source": "measured on ingested data", "coverage_pct": round(c["coverage_pct"], 4),
              "symbols_covered": c["symbols_covered"], "universe_size": c["universe_size"],
              "history_days": c["history_days"], "first_date": str(c["first_date"]), "last_date": str(last),
              "freshness_lag_days": (settings.as_of - last).days if hasattr(last, "year") else None,
              "rows": c["row_count"], "null_rate_key_measure": round(c["null_rate_key_measure"], 4)}
    elif (d.coverage or {}).get("history_start"):
        f["history_days"] = (settings.as_of - date.fromisoformat(d.coverage["history_start"])).days
    if held:
        mine = {c for h in held if h != dataset_id for c in _concepts(settings, h)}
        theirs = set(_concepts(settings, dataset_id))
        f["overlap_with_holdings"] = round(len(mine & theirs) / len(theirs), 2) if theirs else 0.0
        f["new_concepts"] = sorted(ontology.labels_for(x) for x in theirs - mine)
    return f


def _concepts(settings: Settings, dataset_id: str) -> list[str]:
    rows = graph.sparql(settings, f"""SELECT DISTINCT ?c WHERE {{ <{graph.iri('dataset', dataset_id)}> dlp:hasField ?f .
        ?f dlp:means ?c }}""")
    return [r["c"] for r in rows]


def assess(settings: Settings, dataset_id: str, customer_id: str | None = None, runner: Runner | None = None,
           actor: str = "") -> dict:
    f = facts(settings, dataset_id, customer_id)
    runner = runner or Runner(settings)
    r = runner.call("assess", "assess", {"facts": json.dumps(f, default=str)}, Assessment, actor=actor,
                    customer_id=customer_id, subject=dataset_id)
    out = r.output.model_dump() if r.ok else {"summary": "Assessment unavailable; facts below are computed.",
                                              "strengths": [], "risks": [], "alpha_ideas": [],
                                              "recommendation": "TRIAL", "citations": []}
    # Policy no model output can override.
    if f["licence_verdict"] == licensing.LEGAL_REVIEW:
        out["recommendation"] = "LEGAL_REVIEW"
    elif f["licence_verdict"] == licensing.BLOCKED and f["price_model"] == "free":
        out["recommendation"] = "PASS"
    out["unknown_citations"] = [c for c in out.get("citations", []) if c not in f]
    return {"facts": f, "assessment": out, "model": r.model_name, "cost_usd": r.cost_usd}


def compare(settings: Settings, dataset_ids: list[str], customer_id: str | None = None) -> list[dict]:
    """Like-for-like table: the same computed facts for each dataset."""
    keys = ["title", "vendor", "category", "licence", "licence_verdict", "ai_processing_verdict", "price",
            "delivery", "frequency", "fields", "sectors_covered", "history_days", "coverage_pct", "freshness_lag_days",
            "point_in_time", "overlap_with_holdings", "source"]
    rows = []
    for d in dataset_ids[:4]:
        f = facts(settings, d, customer_id)
        rows.append({"dataset_id": d, **{k: f.get(k) for k in keys}})
    return rows


def iv_hv_check(settings: Settings, horizon: int = 10) -> dict:
    """One alpha idea actually tested: does today's IV–HV spread predict the change in 20-day realised vol over the
    next `horizon` trading days? (Cross-sectional quintiles.) Reports what data it ran on."""
    src = (settings.path("landing") / "SOURCE")
    sql = f"""
    with x as (
      select symbol, obs_date, iv_hv_spread,
             lead(hv_20, {horizon}) over (partition by symbol order by obs_date) - hv_20 as fwd_hv_change
      from fct_options_daily),
    q as (select *, ntile(5) over (partition by obs_date order by iv_hv_spread) as quintile
          from x where fwd_hv_change is not null)
    select quintile, count(*) as n, round(avg(iv_hv_spread), 3) as avg_spread,
           round(avg(fwd_hv_change), 3) as avg_fwd_hv_change
    from q group by quintile order by quintile"""
    rows = semantic.table(settings, sql)
    corr = semantic.table(settings, f"""select round(corr(iv_hv_spread, fwd_hv_change), 4) as c, count(*) as n from (
        select iv_hv_spread, lead(hv_20, {horizon}) over (partition by symbol order by obs_date) - hv_20 as fwd_hv_change
        from fct_options_daily) where fwd_hv_change is not null""")[0]
    return {"horizon_days": horizon, "quintiles": rows, "correlation": corr["c"], "observations": corr["n"],
            "data": src.read_text().strip() if src.exists() else "unknown",
            "caveat": ("Offline fixture: generated values, so this result says nothing about markets. Run `dlp fetch` "
                       "and rebuild to test it on the real Hub slice.")
            if src.exists() and src.read_text().strip() == "fixture" else
            "Real Hub slice; in-sample, no costs, no multiple-testing correction — a first look, not a backtest."}
