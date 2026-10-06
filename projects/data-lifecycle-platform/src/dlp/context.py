"""LAYER 4 — the context layer: the minimal, entitled, cited packet a model may see for one question.

Steps, in order, all in code:
  1. screen the question (untrusted)                                     SEC-02
  2. resolve words to concepts, sectors, factors via the ontology        layer 1
  3. filter to datasets this firm may send to an AI model                DATA-04 (licensing.py)
  4. map concepts to governed metrics and run them                        layer 3 (semantic.py)
  5. add graph facts about the datasets and companies in scope           layer 2 (graph.py)
  6. add policy notes, trim to the token budget                          DATA-03, NFR-4
The packet is versioned (hash) and logged; the model sees nothing else. `answer()` then checks that every number
the model wrote is in the packet (OBS-02) and falls back to a plain rendering of the packet if not.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from sqlmodel import select

from . import graph, licensing, ontology, semantic, store
from .ai import Runner
from .config import Settings, sha
from .guardrails import numbers_in, sanitize_untrusted, ungrounded_numbers
from .llm import estimate_tokens
from .schemas import Answer

USE = "v:AIProcessing"
PACKET_VERSION = "ctx-1"


@dataclass
class Packet:
    question_sha: str
    customer_id: str
    status: str = "ANSWERED"
    status_reason: str = ""
    concepts: list[str] = field(default_factory=list)
    metrics: list[dict] = field(default_factory=list)
    graph: list[dict] = field(default_factory=list)
    policy: list[str] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    token_estimate: int = 0
    version: str = PACKET_VERSION

    def model_view(self) -> dict:
        """What the model sees: no customer id, no internal flags."""
        return {"status": self.status, "status_reason": self.status_reason,
                "metrics": [{k: v for k, v in m.items() if not k.startswith("_")} for m in self.metrics],
                "graph": self.graph, "policy": self.policy,
                "excluded": [{"dataset": e["title"], "reason": e["reason"]} for e in self.excluded]}

    def ids(self) -> set[str]:
        return {m["query_id"] for m in self.metrics} | {g["id"] for g in self.graph}

    def numbers(self) -> list[float]:
        return numbers_in(json.dumps(self.model_view()))

    def packet_sha(self) -> str:
        return sha(json.dumps(self.model_view(), sort_keys=True))


def _symbols(settings: Settings, text: str) -> list[str]:
    known = {r["s"] for r in graph.sparql(settings, "SELECT ?s WHERE { ?c dlp:symbol ?s }")}
    return [t for t in dict.fromkeys(re.findall(r"\b[A-Z]{1,5}(?:\.[A-Z])?\b", text)) if t in known]


def roi_window(settings: Settings) -> tuple[str, str]:
    from datetime import timedelta

    end = settings.as_of - timedelta(days=1)
    return (end - timedelta(days=settings["lifecycle"]["roi_window_days"] - 1)).isoformat(), end.isoformat()


def _customer_name(settings: Settings, customer_id: str) -> str:
    with store.session(settings) as s:
        c = s.get(store.Customer, customer_id)
        return c.name if c else customer_id


def build(settings: Settings, question: str, customer_id: str) -> Packet:
    clean, qflags = sanitize_untrusted(question, 2000)
    p = Packet(sha(question), customer_id)
    if qflags["injection_suspected"]:
        p.flags.append("injection_in_question")
    terms = ontology.resolve(question)
    measures = [t for t in terms if t.kind in ("Measure",)]
    sectors = [t for t in terms if t.kind == "Sector"]
    factors = [t for t in terms if t.kind == "EconomicFactor"]
    cats = [t for t in terms if t.kind == "DataCategory"]
    symbols = _symbols(settings, question)
    p.concepts = [ontology.curie(t.iri) for t in terms]

    with store.session(settings) as s:
        datasets = {d.id: d for d in s.exec(select(store.Dataset)).all()}
        allowed = {v.dataset_id: v for v in licensing.entitlements(s, settings, customer_id, USE)}
        verdict = lambda ds: licensing.assess(s, settings, ds, USE, customer_id)

        # ---- metrics bound to the concepts asked about
        by_concept: dict[str, list[semantic.MetricDef]] = {}
        for m in semantic.metrics().values():
            by_concept.setdefault(m.ontology_iri, []).append(m)
        undefined = [t for t in measures if t.iri not in by_concept]
        planned: list[semantic.MetricDef] = []
        for t in measures:
            for m in by_concept.get(t.iri, [])[:1] if t.iri.endswith("OptionVolume") else by_concept.get(t.iri, []):
                if m.dataset_id == "platform":
                    planned.append(m)
                elif m.dataset_id in allowed:
                    planned.append(m)
                else:
                    v = verdict(m.dataset_id)
                    if not any(e["dataset_id"] == m.dataset_id for e in p.excluded):
                        p.excluded.append({"dataset_id": m.dataset_id, "title": datasets[m.dataset_id].title,
                                           "reason": "; ".join(v.reasons) or v.verdict})
        queries = []
        data_metrics = [m.name for m in planned if m.dataset_id != "platform"]
        plat_metrics = [m.name for m in planned if m.dataset_id == "platform"]
        if data_metrics:
            gb, where = [], {}
            if symbols:
                gb, where = ["option_day__symbol"], {"option_day__symbol": symbols}
            elif sectors:
                gb, where = ["option_day__gics_sector"], {"option_day__gics_sector": [t.label for t in sectors]}
            elif re.search(r"\bby sector\b|\beach sector\b|\bsectors\b", question, re.I):
                gb = ["option_day__gics_sector"]
            queries.append((data_metrics, gb, where))
        if plat_metrics:                                   # the firm's own usage and spend, over the ROI window
            start, end = roi_window(settings)
            queries.append((plat_metrics, ["dataset__title"],
                            {"customer__customer_name": _customer_name(settings, customer_id)}, start, end))
        defs = semantic.metrics()
        for names, gb, where, *window in queries:
            r = semantic.query(settings, names, gb, where, *(window or [None, None]), limit=60)
            rows = [row for row in r.rows if any(row[n] is not None for n in names)]
            p.metrics.append({"query_id": r.query_id, "metrics": names, "group_by": gb, "rows": rows,
                              "window": window or None, "units": {n: defs[n].unit for n in names},
                              "sql_sha": sha(r.sql), "_sql": r.sql})

        # ---- graph facts for the datasets and companies in scope
        in_scope = set()
        for m in planned:
            if m.dataset_id != "platform":
                in_scope.add(m.dataset_id)
        for cat in cats:
            in_scope |= {d for d in graph.datasets_for_categories(settings, [cat.iri]) if d in allowed}
        for ds_id, ds in datasets.items():
            if ds.title.lower() in question.lower() or ds_id in question:
                (in_scope.add(ds_id) if ds_id in allowed else p.excluded.append(
                    {"dataset_id": ds_id, "title": ds.title, "reason": "; ".join(verdict(ds_id).reasons)}))
        for ds_id in sorted(in_scope):
            n = graph.dataset_neighbourhood(settings, ds_id)
            if not n:
                continue
            p.graph.append({"id": n["iri"], "text": (
                f"{n['name']} ({n['vendor']}, licence {n['licence']}) covers {n['companies_covered']} companies "
                f"in {len(n['sectors'])} sectors; metrics: {', '.join(n['metrics']) or 'none'}.")})
            for sec in sectors:
                covered = [r["s"] for r in graph.sparql(settings, f"""SELECT ?s WHERE {{
                    <{n['iri']}> dlp:covers ?c . ?c dlp:inSector <{sec.iri}> ; dlp:symbol ?s }} ORDER BY ?s""")]
                if covered:
                    p.graph.append({"id": f"{n['iri']}#{sec.iri.rsplit('/', 1)[-1]}",
                                    "text": f"{n['name']} covers {len(covered)} {sec.label} companies: {', '.join(covered)}."})
        for f in factors:
            fx = graph.factor_expansion(settings, f.iri)
            p.graph.append({"id": f.iri, "text": f"{f.label} moves " + ", ".join(
                f"{x['label']} ({x['sensitivity']:+.1f}, assumed)" for x in fx["sectors"]) +
                "; observed early by " + (", ".join(x["label"] for x in fx["categories"]) or "no category") + "."})
        for ds_id in sorted(in_scope):
            v = allowed.get(ds_id)
            if v and v.conditions:
                p.policy.extend(v.conditions)
            if v:
                p.policy.append(f"{datasets[ds_id].title}: {v.verdict.lower()} for AI processing ({v.source}).")

    # ---- status
    has_numbers = any(m["rows"] for m in p.metrics)
    if undefined and not has_numbers:
        p.status, p.status_reason = "NOT_DEFINED", (
            "Not defined in the semantic layer: " + ", ".join(t.label for t in undefined) +
            ". There is no governed metric for it, so I won't estimate one.")
    elif p.excluded and not has_numbers and not p.graph:
        p.status, p.status_reason = "NOT_ENTITLED", (
            "Your firm isn't entitled to use the data needed for this with an AI model: " +
            "; ".join(f"{e['title']} — {e['reason']}" for e in p.excluded))
    elif not has_numbers and not p.graph:
        p.status, p.status_reason = "NO_DATA", "Nothing in the catalog, graph or metrics matches this question."

    # ---- token budget (NFR-4): drop graph facts, then metric rows, until it fits
    cap = settings["layers"]["context_max_tokens"]
    while estimate_tokens(json.dumps(p.model_view())) > cap and (p.graph or any(len(m["rows"]) > 5 for m in p.metrics)):
        if p.graph:
            p.graph.pop()
        else:
            for m in p.metrics:
                m["rows"] = m["rows"][: max(5, len(m["rows"]) // 2)]
        p.flags.append("trimmed")
    p.token_estimate = estimate_tokens(json.dumps(p.model_view()))
    return p


def render(p: Packet) -> str:
    """A deterministic answer straight from the packet (fallback when the model's answer fails a check)."""
    if p.status != "ANSWERED":
        return p.status_reason
    parts = []
    for m in p.metrics:
        for row in m["rows"][:8]:
            label = ", ".join(str(row[g]) for g in m["group_by"]) or "All"
            parts.append(label + ": " + "; ".join(f"{k} {row[k]}" for k in row if k not in m["group_by"]))
    parts += [g["text"] for g in p.graph[:5]]
    return " ".join(x.rstrip(".") + "." for x in parts)


@dataclass
class AnswerResult:
    answer: str
    status: str
    packet: Packet
    citations: list[str]
    checks: dict
    model: str
    cost_usd: float
    run_id: str


def answer(settings: Settings, question: str, customer_id: str, actor: str = "", runner: Runner | None = None) -> AnswerResult:
    runner = runner or Runner(settings)
    p = build(settings, question, customer_id)
    view = json.dumps(p.model_view(), default=str)
    q, _ = sanitize_untrusted(question, 2000)
    r = runner.call("answer", "answer", {"packet": view, "question": q}, Answer, actor=actor,
                    customer_id=customer_id, subject=question[:80], flags=p.flags,
                    metric_queries=[m["_sql"] for m in p.metrics])
    checks = {"schema_valid": r.ok, "ungrounded_numbers": [], "unknown_citations": [], "status_matches": True,
              "fallback_used": False}
    if r.ok:
        out: Answer = r.output
        checks["ungrounded_numbers"] = ungrounded_numbers(out.answer, p.numbers())
        checks["unknown_citations"] = [c for c in out.citations if c not in p.ids()]
        checks["status_matches"] = (out.status == p.status) or (p.status == "ANSWERED" and out.status == "NO_DATA")
        text, status, cites = out.answer, out.status, out.citations
        if p.status != "ANSWERED" and out.status == "ANSWERED":
            checks["status_matches"] = False
    if not r.ok or checks["ungrounded_numbers"] or checks["unknown_citations"] or not checks["status_matches"]:
        text, status, cites = render(p), p.status, sorted(p.ids())
        checks["fallback_used"] = True
    return AnswerResult(text, status, p, cites, checks, r.model_name, r.cost_usd, r.run_id)
