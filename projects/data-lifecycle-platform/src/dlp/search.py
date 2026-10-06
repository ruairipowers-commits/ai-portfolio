"""Find data (FR-3): natural language → a search plan over the vocabulary → ranked datasets.

The model turns the need into vocabulary terms (it may only choose from the list it's given; code drops anything
else and adds what the ontology resolves directly, so a model miss can't hide an obvious match). Economic factors
expand through the graph into the sectors they move and the data categories that observe them. Scoring is code:
concept matches (fields and metrics), category, sector coverage weighted by sensitivity, a little text match.
Each result says what this firm can do with it today (held / available / needs a contract / legal review) and what
it overlaps with. Marketplace listings not yet in the catalog come back as discoveries.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from sqlmodel import select

from . import graph, licensing, marketplaces, ontology, store
from .ai import Runner
from .config import Settings
from .guardrails import sanitize_untrusted
from .schemas import SearchPlan

STOP = {"that", "this", "with", "data", "which", "would", "help", "from", "about", "need", "want", "free", "stocks",
        "position", "into", "have", "some", "like"}
KIND_FIELDS = {"concepts": {"Measure", "Identifier", "Concept"}, "categories": {"DataCategory"},
               "sectors": {"Sector"}, "factors": {"EconomicFactor"}}


@dataclass
class Result:
    dataset_id: str
    title: str
    vendor: str
    score: float
    why: list[str] = field(default_factory=list)
    access: str = ""
    licence: str = ""
    price: str = ""
    overlaps_with: list[str] = field(default_factory=list)
    in_catalog: bool = True
    url: str = ""


def vocabulary_for_prompt() -> list[dict]:
    return [{"iri": t.iri, "kind": t.kind, "labels": list(t.labels)} for t in ontology.terms()
            if t.kind in {"Measure", "Identifier", "DataCategory", "Sector", "EconomicFactor"}]


def plan(settings: Settings, need: str, runner: Runner | None = None, actor: str = "") -> tuple[SearchPlan, dict]:
    clean, flags = sanitize_untrusted(need, 2000)
    runner = runner or Runner(settings)
    r = runner.call("search", "search", {"need": clean, "vocabulary": json.dumps(vocabulary_for_prompt())}, SearchPlan,
                    actor=actor, subject=need[:80], flags=["injection_in_need"] if flags["injection_suspected"] else [])
    p = r.output if r.ok else SearchPlan()
    valid = {t.iri: t for t in ontology.terms()}
    dropped = []
    for key, kinds in KIND_FIELDS.items():
        keep = []
        for iri in getattr(p, key):
            iri = str(ontology.expand(iri))
            if iri in valid and valid[iri].kind in kinds:
                keep.append(iri)
            else:
                dropped.append(iri)
        setattr(p, key, keep)
    added = []
    for t in ontology.resolve(need):                   # deterministic floor
        for key, kinds in KIND_FIELDS.items():
            if t.kind in kinds and t.iri not in getattr(p, key):
                getattr(p, key).append(t.iri)
                added.append(t.iri)
    p.free_only = p.free_only or bool(re.search(r"\bfree\b|open licen", need, re.I))
    return p, {"model_ok": r.ok, "dropped": dropped, "added_by_code": added, "model": r.model_name,
               "cost_usd": r.cost_usd, "flags": r.flags}


def run(settings: Settings, need: str, customer_id: str | None = None, runner: Runner | None = None,
        actor: str = "", limit: int = 10, include_marketplaces: bool = True) -> dict:
    p, meta = plan(settings, need, runner, actor)
    sectors: dict[str, float] = {s: 1.0 for s in p.sectors}
    cats = set(p.categories)
    factor_notes = []
    for f in p.factors:
        fx = graph.factor_expansion(settings, f)
        for x in fx["sectors"]:
            sectors[x["iri"]] = max(sectors.get(x["iri"], 0), abs(x["sensitivity"]))
        cats |= {c["iri"] for c in fx["categories"]}
        factor_notes.append(f"{ontology.labels_for(f)} → " + ", ".join(
            f"{x['label']} ({x['sensitivity']:+.1f})" for x in fx["sectors"]) +
            (" · watched by " + ", ".join(c["label"] for c in fx["categories"]) if fx["categories"] else ""))
    by_concept = graph.datasets_for_concepts(settings, p.concepts)
    by_cat = set(graph.datasets_for_categories(settings, sorted(cats)))
    by_sector = graph.datasets_for_sectors(settings, sorted(sectors))
    words = {w for w in re.findall(r"[a-z0-9&]{3,}", need.lower())} - {"the", "and", "for", "with", "data", "that", "which"}

    with store.session(settings) as s:
        datasets = s.exec(select(store.Dataset).where(store.Dataset.status != "retired")).all()
        vendors = {v.id: v for v in s.exec(select(store.Vendor)).all()}
        held = set(graph.held_by(settings, customer_id)) if customer_id else set()
        results = []
        for d in datasets:
            score, why = 0.0, []
            if d.id in by_concept:
                score += 3 * len(by_concept[d.id])
                why.append("has " + ", ".join(ontology.labels_for(c) for c in by_concept[d.id]))
            cat_iri = str(ontology.expand(d.category))
            if cat_iri in by_cat or d.id in by_cat:
                score += 2
                why.append(f"category {ontology.labels_for(d.category)}")
            if d.id in by_sector:
                w = sum(sectors[sx] for sx in _covered_sectors(settings, d.id) if sx in sectors)
                score += w
                why.append(f"covers {by_sector[d.id]} of the target sectors")
            text = f"{d.title} {d.description}".lower()
            tw = sum(1 for w_ in words if w_ in text)
            if tw:
                score += 0.5 * tw
            if score <= 0.5 * tw and not why:
                continue
            if p.free_only and d.price_model != "free":
                continue
            access = _access(s, settings, d, customer_id, held)
            if p.needs_ai_processing and customer_id:
                v = licensing.assess(s, settings, d.id, "v:AIProcessing", customer_id)
                if not v.allowed:
                    why.append(f"AI processing: {v.verdict.lower().replace('_', ' ')}")
            results.append(Result(d.id, d.title, vendors[d.vendor_id].name, round(score, 2), why, access, d.licence,
                                  "free" if d.price_model == "free" else f"${d.list_price_usd:,.0f}/yr" if d.list_price_usd else d.price_model,
                                  sorted(x for x in held if x != d.id and _same_category(s, x, d.category)),
                                  True, vendors[d.vendor_id].website or ""))
        results.sort(key=lambda r: (-r.score, r.title))
        catalogued = {d.hub_id for d in datasets if d.hub_id} | {d.title.lower() for d in datasets}
    discoveries = []
    if include_marketplaces:
        keys = {w for w in re.findall(r"[a-z]{4,}", (need + " " + " ".join(
            ontology.labels_for(c) for c in p.concepts + p.categories)).lower())} - STOP
        scored = []
        for name in marketplaces.ADAPTERS:
            try:
                listings = marketplaces.get(name)._all()
            except Exception:
                continue
            for l in listings:
                if l.listing_id in catalogued or l.title.lower() in catalogued:
                    continue
                hit = sum(1 for k in keys if k in f"{l.title} {l.description} {l.listing_id}".lower())
                if hit:
                    scored.append((hit, l))
        for hit, l in sorted(scored, key=lambda x: (-x[0], x[1].title))[:5]:
            discoveries.append(Result(f"{l.marketplace}:{l.listing_id}", l.title, l.publisher, float(hit),
                                      [f"listed on {l.marketplace}, not yet in the catalog"], "not catalogued",
                                      l.licence or "none declared", "free" if l.free else "paid", [], False, l.url))
    return {"plan": {k: [ontology.curie(x) for x in getattr(p, k)] for k in KIND_FIELDS} |
            {"free_only": p.free_only, "needs_ai_processing": p.needs_ai_processing, "rationale": p.rationale},
            "plan_meta": meta, "factor_expansion": factor_notes,
            "results": [r.__dict__ for r in results[:limit]], "discoveries": [r.__dict__ for r in discoveries[:5]]}


def _covered_sectors(settings: Settings, dataset_id: str) -> set[str]:
    return {r["s"] for r in graph.sparql(settings, f"SELECT ?s WHERE {{ <{graph.iri('dataset', dataset_id)}> dlp:coversSector ?s }}")}


def _same_category(s, dataset_id: str, category: str) -> bool:
    d = s.get(store.Dataset, dataset_id)
    return bool(d and d.category == category)


def _access(s, settings: Settings, d: store.Dataset, customer_id: str | None, held: set[str]) -> str:
    if not customer_id:
        return "—"
    if d.id in held:
        return "held"
    v = licensing.assess(s, settings, d.id, "v:InternalResearch", customer_id)
    if v.verdict == licensing.LEGAL_REVIEW:
        return "legal review"
    if d.price_model != "free":
        return "needs contract"
    lic = licensing.assess(s, settings, d.id, "v:InternalResearch")
    return "available (register)" if lic.allowed else "legal review"
