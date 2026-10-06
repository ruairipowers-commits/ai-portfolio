"""Help a company that owns data decide whether, how and to whom to sell it (FR-9).

Code profiles the sample (rows, history, columns, personal data), maps columns to concepts, places the data in the
vocabulary (category → economic factors it observes → sectors they move), measures uniqueness against the catalog,
and computes a price band from comparable listings. If the sample holds personal data, it stops there: nothing is
sent to a model and the gap list says what to remove. Otherwise the model writes the advice from those facts.
Listing on the marketplace needs an operator's approval.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

import pandas as pd
from sqlmodel import select

from . import graph, ontology, store, telemetry
from .ai import Runner
from .config import ROOT, Settings
from .guardrails import pii_columns, sanitize_untrusted
from .schemas import MonetizationAdvice


def submit(settings: Settings, company: str, description: str, sample_file: str) -> store.OwnerSubmission:
    with store.session(settings) as s:
        o = store.OwnerSubmission(id=store.new_id("own"), company=company, description=description, sample_file=sample_file)
        s.add(o)
        s.commit()
        return o


def profile(settings: Settings, sample_file: str) -> dict:
    p = Path(sample_file)
    p = p if p.is_absolute() else ROOT / p
    df = pd.read_csv(p) if p.suffix == ".csv" else pd.read_parquet(p)
    date_cols = [c for c in df.columns if "date" in c.lower()]
    months = None
    if date_cols:
        dt = pd.to_datetime(df[date_cols[0]], errors="coerce")
        months = round((dt.max() - dt.min()).days / 30.44, 1)
    cols = [{"name": c, "concept": (lambda t: ontology.curie(t.iri) if t else None)(ontology.map_field(c))} for c in df.columns]
    return {"rows": int(len(df)), "columns": cols, "history_months": months,
            "pii_columns": pii_columns(list(df.columns), settings["data"]["pii_columns"]),
            "null_rate": round(float(df.isna().mean().mean()), 4)}


def assess(settings: Settings, submission_id: str, runner: Runner | None = None, actor: str = "") -> dict:
    with store.session(settings) as s:
        o = s.get(store.OwnerSubmission, submission_id)
    prof = profile(settings, o.sample_file)
    cfg = settings["monetize"]
    gaps = []
    if prof["pii_columns"]:
        gaps.append("Remove personal data before anything else: " + ", ".join(prof["pii_columns"]))
    if (prof["history_months"] or 0) < cfg["min_history_months"]:
        gaps.append(f"History is {prof['history_months']} months; buyers usually want {cfg['min_history_months']}+ to backtest")
    gaps.append("Confirm the history is point-in-time (no restatements) and document it")
    gaps.append("Map lanes or shippers to listed companies (tickers) so funds can join it to positions")

    desc, flags = sanitize_untrusted(o.description, 4000)
    cats = ontology.resolve(o.description, {"DataCategory"})
    cat_iris = [c.iri for c in cats]
    factors, sectors = [], {}
    for f in ontology.terms():
        if f.kind != "EconomicFactor":
            continue
        fx = graph.factor_expansion(settings, f.iri)
        if any(c["iri"] in cat_iris for c in fx["categories"]):
            factors.append(f.label)
            for x in fx["sectors"]:
                sectors[x["label"]] = x["sensitivity"]
    with store.session(settings) as s:
        same = [d for d in s.exec(select(store.Dataset)).all()
                if str(ontology.expand(d.category)) in cat_iris and d.status != "retired"]
    comps = [d.list_price_usd for d in same if d.list_price_usd]
    uniqueness = round(1 - len(same) / (len(same) + 2), 2)
    band = None
    if comps:
        mid = statistics.median(comps)
        adj = (0.6 if (prof["history_months"] or 0) < 24 else 1.0) * (0.8 + 0.4 * uniqueness)
        band = [round(mid * 0.5 * adj, -3), round(mid * adj, -3)]
    facts = {"company": o.company, "rows": prof["rows"], "history_months": prof["history_months"],
             "columns": [c["name"] for c in prof["columns"]], "categories": [c.label for c in cats],
             "factors": factors, "sectors": sorted(sectors), "uniqueness": uniqueness,
             "comparables": [{"title": d.title, "price_usd": d.list_price_usd} for d in same],
             "price_band_usd": band, "gaps": gaps}
    result = {"facts": facts, "profile": prof, "status": "assessed", "advice": None, "model": "", "cost_usd": 0.0}
    if prof["pii_columns"] and cfg["block_on_pii"]:
        result["status"] = "blocked"
        result["reason"] = "The sample contains personal data; nothing was sent to a model. Remove it and resubmit."
    else:
        runner = runner or Runner(settings)
        r = runner.call("monetize", "monetize", {"facts": json.dumps(facts, default=str), "description": desc},
                        MonetizationAdvice, actor=actor, subject=submission_id,
                        flags=["injection_suspected"] if flags["injection_suspected"] else [])
        result |= {"advice": r.output.model_dump() if r.ok else None, "model": r.model_name, "cost_usd": r.cost_usd}
    with store.session(settings) as s:
        o = s.get(store.OwnerSubmission, submission_id)
        o.status, o.assessment = result["status"], json.loads(json.dumps(result, default=str))
        s.add(o)
        s.commit()
    telemetry.record("monetize", actor=actor, status="blocked" if result["status"] == "blocked" else "ok",
                     flags=["pii"] if prof["pii_columns"] else [])
    return result


def request_listing(settings: Settings, submission_id: str, actor: str) -> store.Approval:
    with store.session(settings) as s:
        o = s.get(store.OwnerSubmission, submission_id)
        if o.status != "assessed":
            raise ValueError(f"Submission is {o.status}; only an assessed submission can be listed")
        a = store.Approval(id=store.new_id("ap"), kind="listing", subject_id=submission_id, payload=o.assessment,
                           requested_by=actor)
        s.add(a)
        s.commit()
        return a


def apply_listing(s, a: store.Approval, reviewer: str) -> None:
    from .catalog import upsert_dataset, upsert_vendor

    o = s.get(store.OwnerSubmission, a.subject_id)
    f = o.assessment["facts"]
    v = upsert_vendor(s, {"name": o.company, "status": "prospect", "source": "owner-submission", "notes": "Data owner"},
                      actor=reviewer)
    cat = ontology.resolve(o.description, {"DataCategory"})
    band = f.get("price_band_usd")
    d = upsert_dataset(s, {"vendor_id": v.id, "title": f"{o.company} data (draft listing)", "description": o.description[:400],
                           "category": ontology.curie(cat[0].iri) if cat else "v:ReferenceData",
                           "price_model": "subscription", "list_price_usd": band[1] if band else None,
                           "status": "listed", "dictionary": [{"name": c} for c in f["columns"]]}, actor=reviewer)
    d.licence = "proprietary"
    s.add(d)
    o.status = "listed"
    s.add(o)
