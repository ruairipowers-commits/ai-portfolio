"""LAYER 2 — the knowledge graph: what exists and how it connects.

Built, never hand-edited: `build()` reads the operational store (vendors, datasets, contracts…), the warehouse
(companies, which symbols a dataset covers, who used what), the semantic layer's metric list and dbt lineage, turns
them into instances of the ontology, validates them against the SHACL shapes (NFR-5, refuses to load on failure),
and loads them into Oxigraph. Everything above reads it with SPARQL through the functions at the bottom.
It holds no metric values (those stay in the semantic layer) and no free text beyond names and descriptions.
"""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pyoxigraph as ox
from pyshacl import validate
from rdflib import RDF, XSD, Graph, Literal, URIRef
from sqlmodel import select

from . import licensing, ontology, semantic, store
from .config import ROOT, Settings, now, sha
from .ontology import DLP, ID, V, expand

PREFIXES = f"PREFIX dlp: <{DLP}>\nPREFIX v: <{V}>\nPREFIX id: <{ID}>\n" \
           "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"


class GraphValidationError(RuntimeError):
    def __init__(self, report: str, n: int):
        super().__init__(f"SHACL validation failed ({n} violations); nothing was loaded.\n{report[:2500]}")
        self.report, self.violations = report, n


def iri(kind: str, key: str) -> URIRef:
    return ID[f"{kind}/{key}"]


def sector_iri(name: str) -> URIRef | None:
    hits = ontology.resolve(name or "", {"Sector"})
    return URIRef(hits[0].iri) if hits else None


# ---------------------------------------------------------------- build
def instances(settings: Settings) -> Graph:
    """Turn the catalog + warehouse facts into ontology instances (no validation yet)."""
    g = Graph()
    g.bind("dlp", DLP), g.bind("v", V), g.bind("id", ID)
    lit = lambda x: Literal(str(x))
    with store.session(settings) as s:
        vendors = s.exec(select(store.Vendor)).all()
        datasets = s.exec(select(store.Dataset)).all()
        customers = s.exec(select(store.Customer)).all()
        teams = s.exec(select(store.Team)).all()
        contracts = s.exec(select(store.Contract)).all()
        deps = s.exec(select(store.Dependency)).all()
        ents = {c.id: licensing.entitlements(s, settings, c.id) for c in customers}

    for v in vendors:
        n = iri("vendor", v.id)
        g.add((n, RDF.type, DLP.Vendor))
        g.add((n, DLP.name, lit(v.name)))
        if v.website:
            g.add((n, DLP.website, lit(v.website)))
    marketplaces = set()
    for d in datasets:
        n = iri("dataset", d.id)
        g.add((n, RDF.type, DLP.Dataset))
        g.add((n, DLP.name, lit(d.title)))
        g.add((n, DLP.status, lit(d.status)))
        g.add((n, DLP.providedBy, iri("vendor", d.vendor_id)))
        g.add((n, DLP.inCategory, expand(d.category)))
        lic = V[f"licence-{(d.licence or 'none').lower()}"]
        g.add((n, DLP.hasLicence, lic if (lic, RDF.type, DLP.Licence) in ontology.vocabulary() else V["licence-none"]))
        for m in d.listed_on:
            mk = iri("marketplace", m)
            marketplaces.add(m)
            g.add((n, DLP.listedOn, mk))
        for sub in d.substitute_for:
            g.add((n, DLP.substituteFor, iri("dataset", sub)))
        for sec in (d.coverage or {}).get("sectors", []) if isinstance((d.coverage or {}).get("sectors"), list) else []:
            si = sector_iri(sec)
            if si:
                g.add((n, DLP.coversSector, si))
        if (d.coverage or {}).get("sectors") == "all":
            for t in ontology.terms():
                if t.kind == "Sector":
                    g.add((n, DLP.coversSector, URIRef(t.iri)))
        for i, f in enumerate(d.dictionary or []):
            fn = iri("field", f"{d.id}/{f['name']}")
            g.add((n, DLP.hasField, fn))
            g.add((fn, RDF.type, DLP.Field))
            g.add((fn, DLP.name, lit(f["name"])))
            g.add((fn, DLP.dataType, lit(f.get("type") or "string")))
            if f.get("concept"):
                g.add((fn, DLP.means, expand(f["concept"])))
        for ident in d.identifiers or []:      # declared identifiers count as fields that mean them
            fn = iri("field", f"{d.id}/{ontology.curie(expand(ident)).split(':')[1].lower()}")
            if (n, DLP.hasField, fn) not in g:
                g.add((n, DLP.hasField, fn))
                g.add((fn, RDF.type, DLP.Field))
                g.add((fn, DLP.name, lit(ontology.labels_for(ident))))
                g.add((fn, DLP.dataType, lit("string")))
                g.add((fn, DLP.means, expand(ident)))
    for m in marketplaces:
        g.add((iri("marketplace", m), RDF.type, DLP.Marketplace))
        g.add((iri("marketplace", m), DLP.name, lit(m)))

    for c in customers:
        g.add((iri("customer", c.id), RDF.type, DLP.Customer))
        g.add((iri("customer", c.id), DLP.name, lit(c.name)))
    for t in teams:
        g.add((iri("team", t.id), RDF.type, DLP.Team))
        g.add((iri("team", t.id), DLP.name, lit(t.name)))
        g.add((iri("team", t.id), DLP.memberOf, iri("customer", t.customer_id)))
    for c in contracts:
        n = iri("contract", c.id)
        g.add((n, RDF.type, DLP.Contract))
        g.add((n, DLP.holder, iri("customer", c.customer_id)))
        for d in c.datasets:
            g.add((n, DLP.coversDataset, iri("dataset", d)))
        g.add((n, DLP.startDate, Literal(c.start, datatype=XSD.date)))
        g.add((n, DLP.endDate, Literal(c.end, datatype=XSD.date)))
        g.add((n, DLP.status, lit(c.status)))
        for u in c.permitted_use:
            g.add((n, DLP.permitsUse, expand(u)))
    for cid, vs in ents.items():
        for v in vs:
            n = iri("entitlement", f"{cid}/{v.dataset_id}/{v.use.split(':')[1]}")
            g.add((n, RDF.type, DLP.Entitlement))
            g.add((n, DLP.entitles, iri("customer", cid)))
            g.add((n, DLP.toDataset, iri("dataset", v.dataset_id)))
            g.add((n, DLP.forUse, expand(v.use)))
            g.add((n, DLP.status, lit(v.verdict)))
    for dep in deps:
        for team in dep.consumers:
            g.add((iri("team", team), DLP.consumes, iri("dataset", dep.dataset_id)))
        for r in dep.reports:
            rn = iri("report", sha(r))
            g.add((rn, RDF.type, DLP.Report))
            g.add((rn, DLP.name, lit(r)))
            g.add((rn, DLP.dependsOn, iri("dataset", dep.dataset_id)))
            for team in dep.consumers:
                g.add((rn, DLP.ownedBy, iri("team", team)))

    # warehouse facts: companies, coverage, who used what
    try:
        companies = semantic.table(settings, "select symbol, company_name, gics_sector, gics_sub_industry, cik from dim_company")
        covered = semantic.table(settings, "select distinct symbol from stg_options")
        used = semantic.table(settings, "select distinct team_id, dataset_id from fct_dataset_usage")
    except Exception:
        companies, covered, used = [], [], []
    for c in companies:
        n = iri("company", c["symbol"])
        g.add((n, RDF.type, DLP.Company))
        g.add((n, DLP.symbol, lit(c["symbol"])))
        g.add((n, DLP.name, lit(c["company_name"])))
        if c.get("cik"):
            g.add((n, DLP.cik, lit(c["cik"])))
        si = sector_iri(c["gics_sector"])
        if si:
            g.add((n, DLP.inSector, si))
        ind = iri("industry", sha(c["gics_sub_industry"] or "unknown"))
        g.add((ind, RDF.type, DLP.Industry))
        g.add((ind, DLP.name, lit(c["gics_sub_industry"])))
        g.add((n, DLP.inIndustry, ind))
        if si:
            g.add((ind, DLP.industryOf, si))
    known = {c["symbol"] for c in companies}
    opt = iri("dataset", "ds-options-iv")
    for r in covered:
        if r["symbol"] in known:
            g.add((opt, DLP.covers, iri("company", r["symbol"])))
            for sec in g.objects(iri("company", r["symbol"]), DLP.inSector):
                g.add((opt, DLP.coversSector, sec))
    cons = iri("dataset", "ds-constituents")
    for c in companies:
        g.add((cons, DLP.covers, iri("company", c["symbol"])))
    for r in used:
        g.add((iri("team", r["team_id"]), DLP.consumes, iri("dataset", r["dataset_id"])))

    # semantic layer: metrics point at their concept and the dataset/asset they're computed from
    for name, m in semantic.metrics().items():
        n = iri("metric", name)
        g.add((n, RDF.type, DLP.Metric))
        g.add((n, DLP.metricName, lit(name)))
        g.add((n, DLP.name, lit(m.label)))
        g.add((n, DLP.measures, URIRef(m.ontology_iri)))
        if m.dataset_id and m.dataset_id != "platform":
            g.add((n, DLP.computedFrom, iri("dataset", m.dataset_id)))
    _lineage(g, settings)

    # factor knowledge (synthetic assumptions, labelled in the seed)
    extras = store.seed_extras()
    for i, fs in enumerate(extras["factor_sensitivities"]):
        n = iri("sensitivity", f"{fs['factor'][2:]}-{fs['sector'][2:]}")
        g.add((n, RDF.type, DLP.Sensitivity))
        g.add((n, DLP.factor, expand(fs["factor"])))
        g.add((n, DLP.sector, expand(fs["sector"])))
        g.add((n, DLP.sensitivity, Literal(fs["sensitivity"], datatype=XSD.decimal)))
        g.add((expand(fs["factor"]), DLP.moves, expand(fs["sector"])))
    for fp in extras["factor_proxies"]:
        g.add((expand(fp["factor"]), DLP.proxiedBy, expand(fp["category"])))
    return g


def _lineage(g: Graph, settings: Settings) -> None:
    """dbt's lineage (the same graph Dagster's assets are built from) as DataAssets."""
    from .config import workspace

    manifest = workspace() / "semantic" / "target" / "manifest.json"
    if not manifest.exists():
        manifest = ROOT / "semantic" / "target" / "manifest.json"
    if not manifest.exists():
        return
    m = json.loads(manifest.read_text())
    src_ds = {uid: n.get("meta", {}).get("dataset_id") for uid, n in m["sources"].items()}
    for uid, n in m["sources"].items():          # platform-owned inputs (catalog export, usage log) are assets too
        if not src_ds[uid]:
            a = iri("asset", f"source.{n['name']}")
            g.add((a, RDF.type, DLP.DataAsset))
            g.add((a, DLP.name, Literal(f"landing.{n['name']}")))
    for uid, node in m["nodes"].items():
        if node["resource_type"] != "model":
            continue
        a = iri("asset", node["name"])
        g.add((a, RDF.type, DLP.DataAsset))
        g.add((a, DLP.name, Literal(node["name"])))
        for p in node["depends_on"]["nodes"]:
            if p.startswith("source."):
                g.add((a, DLP.readsFrom, iri("dataset", src_ds[p]) if src_ds.get(p) else
                       iri("asset", f"source.{m['sources'][p]['name']}")))
            elif p.startswith("model."):
                g.add((a, DLP.readsFrom, iri("asset", p.split(".")[-1])))
    for sm in semantic.semantic_models().values():
        import re
        table = re.search(r"ref\('(\w+)'\)", sm["model"]).group(1)
        for name, md in semantic.metrics().items():
            measures = {ms["name"] for ms in sm.get("measures", [])}
            if md.measure in measures and (iri("asset", table), RDF.type, DLP.DataAsset) in g:
                g.add((iri("metric", name), DLP.fromAsset, iri("asset", table)))


def shacl(data: Graph) -> tuple[bool, str, int]:
    full = data + ontology.vocabulary()
    conforms, _, text = validate(full, shacl_graph=ontology.shapes(), ont_graph=ontology.schema(), inference="rdfs",
                                 advanced=True, allow_warnings=True)
    n = text.count("Constraint Violation")
    return bool(conforms), text, n


def store_path(settings: Settings) -> Path:
    return settings.path("graph_store")


def build(settings: Settings) -> dict:
    """Build → SHACL → load. Refuses to load anything that fails validation (NFR-5)."""
    g = instances(settings)
    ok, report, n = shacl(g)
    if not ok and settings["data"]["require_shacl_conforms"]:
        raise GraphValidationError(report, n)
    p = store_path(settings)
    tmp = p.with_name(p.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    st = ox.Store(str(tmp))
    full = g + ontology.schema() + ontology.vocabulary()
    st.bulk_load(full.serialize(format="nt").encode(), "application/n-triples")
    st.flush()
    del st
    shutil.rmtree(p, ignore_errors=True)
    tmp.rename(p)
    _cache.clear()
    info = {"triples": len(full), "instance_triples": len(g), "conforms": ok, "violations": n,
            "ontology_version": ontology.version(), "built_at": now().isoformat(), "graph_version": sha(
                g.serialize(format="nt"))}
    (p.parent / "graph_info.json").write_text(json.dumps(info, indent=2))
    return info


def info(settings: Settings) -> dict:
    p = store_path(settings).parent / "graph_info.json"
    return json.loads(p.read_text()) if p.exists() else {}


# ---------------------------------------------------------------- reading
_cache: dict[str, ox.Store] = {}


def _store(settings: Settings) -> ox.Store:
    p = str(store_path(settings))
    if p not in _cache:
        if not Path(p).exists():
            raise FileNotFoundError("Knowledge graph not built; run `dlp build`")
        _cache[p] = ox.Store.read_only(p)
    return _cache[p]


def sparql(settings: Settings, q: str) -> list[dict]:
    res = _store(settings).query(PREFIXES + q)
    vars_ = [v.value for v in res.variables]
    out = []
    for sol in res:
        row = {}
        for v in vars_:
            t = sol[v]
            row[v] = None if t is None else t.value
        out.append(row)
    return out


def _local(iri_value: str) -> str:
    return iri_value.rsplit("/", 1)[-1]


def dataset_neighbourhood(settings: Settings, dataset_id: str) -> dict:
    d = f"id:dataset\\/{dataset_id}"
    d = f"<{iri('dataset', dataset_id)}>"
    base = sparql(settings, f"""SELECT ?name ?vendor ?vname ?cat ?catlabel ?lic WHERE {{
        {d} dlp:name ?name ; dlp:providedBy ?vendor ; dlp:inCategory ?cat ; dlp:hasLicence ?l .
        ?vendor dlp:name ?vname . ?l dlp:spdxId ?lic . OPTIONAL {{ ?cat skos:prefLabel ?catlabel }} }}""")
    if not base:
        return {}
    b = base[0]
    fields = sparql(settings, f"""SELECT ?fname ?concept ?clabel WHERE {{ {d} dlp:hasField ?f . ?f dlp:name ?fname .
        OPTIONAL {{ ?f dlp:means ?concept . ?concept skos:prefLabel ?clabel }} }} ORDER BY ?fname""")
    sectors = [r["l"] for r in sparql(settings, f"SELECT DISTINCT ?l WHERE {{ {d} dlp:coversSector ?s . ?s skos:prefLabel ?l }} ORDER BY ?l")]
    n_cov = sparql(settings, f"SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE {{ {d} dlp:covers ?c }}")[0]["n"]
    metrics = [r["m"] for r in sparql(settings, f"SELECT ?m WHERE {{ ?x dlp:computedFrom {d} ; dlp:metricName ?m }} ORDER BY ?m")]
    subs = [_local(r["s"]) for r in sparql(settings, f"SELECT ?s WHERE {{ {{ {d} dlp:substituteFor ?s }} UNION {{ ?s dlp:substituteFor {d} }} }}")]
    markets = [r["n"] for r in sparql(settings, f"SELECT ?n WHERE {{ {d} dlp:listedOn ?m . ?m dlp:name ?n }}")]
    return {"dataset_id": dataset_id, "name": b["name"], "vendor": b["vname"], "vendor_id": _local(b["vendor"]),
            "category": b["catlabel"] or ontology.curie(b["cat"]), "licence": b["lic"], "sectors": sectors,
            "companies_covered": int(n_cov), "fields": [{"name": f["fname"], "concept": f["clabel"]} for f in fields],
            "metrics": metrics, "substitutes": subs, "marketplaces": markets, "iri": str(iri("dataset", dataset_id))}


def datasets_for_concepts(settings: Settings, concept_iris: list[str]) -> dict[str, list[str]]:
    """dataset_id → concepts it has a field (or metric) for."""
    if not concept_iris:
        return {}
    vals = " ".join(f"<{c}>" for c in concept_iris)
    rows = sparql(settings, f"""SELECT DISTINCT ?d ?c WHERE {{ VALUES ?c {{ {vals} }}
        {{ ?d dlp:hasField ?f . ?f dlp:means ?c }} UNION {{ ?m dlp:measures ?c ; dlp:computedFrom ?d }} }}""")
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(_local(r["d"]), []).append(r["c"])
    return out


def datasets_for_categories(settings: Settings, cat_iris: list[str]) -> list[str]:
    if not cat_iris:
        return []
    vals = " ".join(f"<{c}>" for c in cat_iris)
    return [_local(r["d"]) for r in sparql(settings, f"SELECT DISTINCT ?d WHERE {{ VALUES ?c {{ {vals} }} ?d dlp:inCategory ?c }}")]


def datasets_for_sectors(settings: Settings, sector_iris: list[str]) -> dict[str, int]:
    if not sector_iris:
        return {}
    vals = " ".join(f"<{s}>" for s in sector_iris)
    rows = sparql(settings, f"SELECT ?d (COUNT(DISTINCT ?s) AS ?n) WHERE {{ VALUES ?s {{ {vals} }} ?d dlp:coversSector ?s }} GROUP BY ?d")
    return {_local(r["d"]): int(r["n"]) for r in rows}


def factor_expansion(settings: Settings, factor_iri: str) -> dict:
    """An economic factor → the sectors it moves (with sensitivity) and the data categories that observe it."""
    f = f"<{factor_iri}>"
    sectors = sparql(settings, f"""SELECT ?s ?l ?w WHERE {{ ?x dlp:factor {f} ; dlp:sector ?s ; dlp:sensitivity ?w .
        ?s skos:prefLabel ?l }} ORDER BY DESC(?w)""")
    cats = sparql(settings, f"SELECT ?c ?l WHERE {{ {f} dlp:proxiedBy ?c . ?c skos:prefLabel ?l }}")
    return {"sectors": [{"iri": r["s"], "label": r["l"], "sensitivity": float(r["w"])} for r in sectors],
            "categories": [{"iri": r["c"], "label": r["l"]} for r in cats]}


def held_by(settings: Settings, customer_id: str) -> list[str]:
    c = f"<{iri('customer', customer_id)}>"
    return sorted({_local(r["d"]) for r in sparql(settings, f"SELECT ?d WHERE {{ ?e dlp:entitles {c} ; dlp:toDataset ?d }}")})


def impact(settings: Settings, dataset_id: str) -> dict:
    """What depends on a dataset: assets, metrics, reports, teams, contracts and customers entitled to it (FR-8)."""
    d = f"<{iri('dataset', dataset_id)}>"
    assets = [r["n"] for r in sparql(settings, f"SELECT DISTINCT ?n WHERE {{ ?a dlp:readsFrom+ {d} ; dlp:name ?n }} ORDER BY ?n")]
    metrics = [r["n"] for r in sparql(settings, f"""SELECT DISTINCT ?n WHERE {{ ?m dlp:metricName ?n .
        {{ ?m dlp:computedFrom {d} }} UNION {{ ?m dlp:fromAsset ?a . ?a dlp:readsFrom+ {d} }} }} ORDER BY ?n""")]
    reports = [r["n"] for r in sparql(settings, f"SELECT ?n WHERE {{ ?r dlp:dependsOn {d} ; dlp:name ?n }}")]
    teams = [r["n"] for r in sparql(settings, f"SELECT DISTINCT ?n WHERE {{ ?t dlp:consumes {d} ; dlp:name ?n }} ORDER BY ?n")]
    contracts = [_local(r["c"]) for r in sparql(settings, f"SELECT ?c WHERE {{ ?c dlp:coversDataset {d} ; dlp:status 'active' }}")]
    customers = [r["n"] for r in sparql(settings, f"SELECT DISTINCT ?n WHERE {{ ?e dlp:toDataset {d} ; dlp:entitles ?c . ?c dlp:name ?n }} ORDER BY ?n")]
    return {"dataset_id": dataset_id, "assets": assets, "metrics": metrics, "reports": reports, "teams": teams,
            "active_contracts": contracts, "entitled_customers": customers}


def substitutes(settings: Settings, dataset_id: str) -> list[dict]:
    """Declared substitutes first, then same-category datasets ranked by shared concepts (FR-8)."""
    d = f"<{iri('dataset', dataset_id)}>"
    declared = {_local(r["s"]) for r in sparql(settings, f"SELECT ?s WHERE {{ {{ {d} dlp:substituteFor ?s }} UNION {{ ?s dlp:substituteFor {d} }} }}")}
    rows = sparql(settings, f"""SELECT ?o (COUNT(DISTINCT ?c) AS ?shared) WHERE {{
        {d} dlp:inCategory ?cat . ?o dlp:inCategory ?cat . FILTER(?o != {d})
        OPTIONAL {{ {d} dlp:hasField ?f1 . ?f1 dlp:means ?c . ?o dlp:hasField ?f2 . ?f2 dlp:means ?c }}
        OPTIONAL {{ ?m dlp:computedFrom {d} ; dlp:measures ?c . ?o dlp:hasField ?f3 . ?f3 dlp:means ?c }}
        }} GROUP BY ?o""")
    out = {r["o"].rsplit("/", 1)[-1]: int(r["shared"]) for r in rows}
    for x in declared:
        out.setdefault(x, 0)
    ranked = sorted(out.items(), key=lambda kv: (kv[0] not in declared, -kv[1], kv[0]))
    return [{"dataset_id": k, "shared_concepts": v, "declared": k in declared} for k, v in ranked]


def companies_in(settings: Settings, sector_iri_: str) -> list[str]:
    return [r["s"] for r in sparql(settings, f"SELECT ?s WHERE {{ ?c dlp:inSector <{sector_iri_}> ; dlp:symbol ?s }} ORDER BY ?s")]


def counts(settings: Settings) -> dict:
    rows = sparql(settings, "SELECT ?t (COUNT(?s) AS ?n) WHERE { ?s a ?t . FILTER(STRSTARTS(STR(?s), 'https://w3id.org/dlp/id/')) } GROUP BY ?t ORDER BY DESC(?n)")
    return {ontology.curie(r["t"]): int(r["n"]) for r in rows}
