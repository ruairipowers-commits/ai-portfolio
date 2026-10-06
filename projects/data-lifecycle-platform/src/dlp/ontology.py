"""LAYER 1 — the ontology: what things mean.

Three files, none of which hold data about the world:
  ontology/dlp.ttl         classes and properties (OWL)
  ontology/vocabulary.ttl  the controlled vocabulary: concepts, categories, use cases, licences, sectors, factors
  ontology/shapes.ttl      SHACL rules instance data must satisfy before it enters the graph
This module loads them, resolves words to concepts (search, question parsing, field mapping all go through
`resolve()`), and diffs versions. It never reads the catalog, the graph or the warehouse.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, Namespace, URIRef
from rdflib.namespace import SKOS

from .config import ROOT

DLP = Namespace("https://w3id.org/dlp/ontology#")
V = Namespace("https://w3id.org/dlp/vocab/")
ID = Namespace("https://w3id.org/dlp/id/")

VOCAB_TYPES = {DLP.Identifier, DLP.Measure, DLP.Concept, DLP.DataCategory, DLP.UseCase, DLP.Licence, DLP.Sector,
               DLP.EconomicFactor}
SCHEMA_TYPES = {OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.Ontology}


def _path(name: str) -> Path:
    return ROOT / "ontology" / name


@functools.lru_cache(maxsize=1)
def schema() -> Graph:
    g = Graph()
    g.parse(_path("dlp.ttl"))
    return g


@functools.lru_cache(maxsize=1)
def vocabulary() -> Graph:
    g = Graph()
    g.parse(_path("vocabulary.ttl"))
    return g


@functools.lru_cache(maxsize=1)
def shapes() -> Graph:
    g = Graph()
    g.parse(_path("shapes.ttl"))
    return g


def version() -> str:
    return str(schema().value(URIRef("https://w3id.org/dlp/ontology"), OWL.versionInfo))


def expand(curie: str) -> URIRef:
    """'v:Ticker' → full IRI; full IRIs pass through."""
    if curie.startswith("v:"):
        return V[curie[2:]]
    if curie.startswith("dlp:"):
        return DLP[curie[4:]]
    return URIRef(curie)


def curie(iri) -> str:
    s = str(iri)
    for prefix, ns in (("v:", str(V)), ("dlp:", str(DLP))):
        if s.startswith(ns):
            return prefix + s[len(ns):]
    return s


# ---------------------------------------------------------------- vocabulary lookup
@dataclass(frozen=True)
class Term:
    iri: str
    kind: str          # local name of the vocab class: Measure, Identifier, Sector, …
    label: str
    labels: tuple[str, ...]


def _norm(text: str) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower()
    text = re.sub(r"(?<=[a-z])(?=\d)", " ", text)            # hv20 → hv 20
    return " ".join(re.sub(r"[^a-z0-9&+]+", " ", text).split())


@functools.lru_cache(maxsize=1)
def terms() -> tuple[Term, ...]:
    g = vocabulary()
    out = []
    for s, _, t in g.triples((None, RDF.type, None)):
        if t not in VOCAB_TYPES:
            continue
        pref = str(g.value(s, SKOS.prefLabel) or s.split("/")[-1])
        alts = [str(o) for o in g.objects(s, SKOS.altLabel)]
        labels = tuple(sorted({_norm(x) for x in [pref, *alts] if x}, key=len, reverse=True))
        out.append(Term(str(s), t.split("#")[-1], pref, labels))
    return tuple(out)


def term(iri_or_curie: str) -> Term | None:
    iri = str(expand(iri_or_curie))
    return next((t for t in terms() if t.iri == iri), None)


def resolve(text: str, kinds: set[str] | None = None, whole: bool = False) -> list[Term]:
    """Concepts mentioned in `text`, longest label first, no overlaps. `whole=True` matches a field name, where every
    label word must be in the name (so 'calls_contracts_traded' → options contracts traded)."""
    norm = f" {_norm(text)} "
    found: list[tuple[int, Term]] = []
    words = set(norm.split())
    for t in terms():
        if kinds and t.kind not in kinds:
            continue
        for lab in t.labels:
            hit = set(lab.split()) <= words if whole else f" {lab} " in norm
            if hit:
                found.append((len(lab.split()) * 100 + len(lab), t))
                break
    found.sort(key=lambda x: -x[0])
    if whole:
        return [found[0][1]] if found else []
    out, used = [], set()
    for _, t in found:
        if t.iri not in used:
            out.append(t)
            used.add(t.iri)
    return out


def map_field(name: str, description: str = "") -> Term | None:
    """Best concept for a dictionary field (code, not a model): name first, then description."""
    hits = resolve(name, {"Identifier", "Measure", "Concept"}, whole=True)
    if hits:
        return hits[0]
    hits = resolve(description, {"Identifier", "Measure", "Concept"})
    return hits[0] if hits else None


# ---------------------------------------------------------------- checks and versioning
def check() -> list[str]:
    """Layer-boundary checks: the ontology holds meaning only."""
    problems = []
    for s, _, o in schema().triples((None, RDF.type, None)):
        if o not in SCHEMA_TYPES:
            problems.append(f"dlp.ttl declares an instance {curie(s)} of {curie(o)} — instances belong in the graph")
    for s, _, o in vocabulary().triples((None, RDF.type, None)):
        if o not in VOCAB_TYPES:
            problems.append(f"vocabulary.ttl declares {curie(s)} as {curie(o)} — only vocabulary terms belong here")
    classes = set(schema().subjects(RDF.type, OWL.Class))
    for t in VOCAB_TYPES:
        if t not in classes:
            problems.append(f"vocabulary type {curie(t)} is not a class in dlp.ttl")
    return problems


def summary() -> dict:
    g = schema()
    return {"version": version(), "classes": len(set(g.subjects(RDF.type, OWL.Class))),
            "object_properties": len(set(g.subjects(RDF.type, OWL.ObjectProperty))),
            "datatype_properties": len(set(g.subjects(RDF.type, OWL.DatatypeProperty))),
            "vocabulary_terms": len(terms()), "shapes": len(set(shapes().subjects(RDF.type, URIRef(
                "http://www.w3.org/ns/shacl#NodeShape"))))}


def diff(old_ttl: str, new_ttl: str | None = None) -> dict:
    """What changed between two versions of dlp.ttl (+ vocabulary): added/removed triples, readable (NFR-5)."""
    a, b = Graph(), Graph()
    a.parse(data=old_ttl, format="turtle")
    if new_ttl is None:
        b = schema() + vocabulary()
    else:
        b.parse(data=new_ttl, format="turtle")
    fmt = lambda t: " ".join(curie(x) if isinstance(x, URIRef) else repr(str(x)) for x in t)
    added = sorted(fmt(t) for t in set(b) - set(a))
    removed = sorted(fmt(t) for t in set(a) - set(b))
    return {"added": added, "removed": removed}


def labels_for(iri: str) -> str:
    t = term(iri)
    return t.label if t else curie(iri)


def class_label(iri) -> str:
    return str(schema().value(URIRef(str(iri)), RDFS.label) or curie(iri))
