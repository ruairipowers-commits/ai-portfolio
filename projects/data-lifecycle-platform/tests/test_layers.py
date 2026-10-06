"""The four layers stay apart: a test at each boundary."""
import pytest
from rdflib import RDF, Graph, Literal, URIRef

from dlp import context, graph, ontology, semantic, store
from dlp.ontology import DLP, V


def test_ontology_holds_meaning_only():
    assert ontology.check() == []
    g = Graph() + ontology.schema()
    g.add((URIRef("https://w3id.org/dlp/id/vendor/x"), RDF.type, DLP.Vendor))       # an instance sneaks in
    assert any("instances belong in the graph" in p for p in ontology.check(schema_g=g))


def test_every_metric_is_bound_to_a_vocabulary_measure(built):
    s, _ = built
    with store.session(s) as ss:
        ids = {d.id for d in ss.exec(__import__("sqlmodel").select(store.Dataset)).all()}
    for m in semantic.metrics().values():
        t = ontology.term(m.ontology_iri)
        assert t is not None and t.kind == "Measure", m.name
        assert m.dataset_id in ids | {"platform"}, m.name


def test_graph_points_at_metrics_but_holds_no_metric_values(built):
    s, _ = built
    names = {r["n"] for r in graph.sparql(s, "SELECT ?n WHERE { ?m a dlp:Metric ; dlp:metricName ?n }")}
    assert names == set(semantic.metrics())
    numeric = graph.sparql(s, """SELECT ?p WHERE { ?s ?p ?o . FILTER(isLiteral(?o) &&
        DATATYPE(?o) IN (<http://www.w3.org/2001/XMLSchema#decimal>, <http://www.w3.org/2001/XMLSchema#double>)) }""")
    assert {r["p"] for r in numeric} <= {str(DLP.sensitivity)}


def test_shacl_refuses_bad_instances_and_loads_nothing(built):
    s, _ = built
    before = graph.info(s)["graph_version"]
    g = graph.instances(s)
    bad = graph.iri("contract", "c-001")
    g.remove((bad, DLP.endDate, None))
    g.add((bad, DLP.endDate, Literal("2025-01-01", datatype=URIRef("http://www.w3.org/2001/XMLSchema#date"))))
    g.remove((graph.iri("dataset", "ds-card-panel"), DLP.providedBy, None))
    ok, report, n = graph.shacl(g)
    assert not ok and n >= 2 and "Contract must end after it starts" in report
    assert graph.info(s)["graph_version"] == before


def test_semantic_layer_sql_reads_only_warehouse_tables(built):
    s, _ = built
    r = semantic.query(s, ["atm_iv", "put_call_ratio"], ["option_day__gics_sector"])
    assert "fct_options_daily" in r.sql and "catalog" not in r.sql.lower() and r.compiled_by == "metricflow"
    assert len(r.rows) >= 8


def test_context_packet_holds_only_entitled_data_and_metric_numbers(built):
    s, _ = built
    p = context.build(s, "What is the ATM implied volatility for JPM?", "cust-alder")
    assert p.metrics == [] and p.status == "NOT_ENTITLED"
    assert [e["dataset_id"] for e in p.excluded] == ["ds-options-iv"]
    p = context.build(s, "What is the ATM implied volatility for JPM?", "cust-harbor")
    assert p.status == "ANSWERED" and p.metrics[0]["rows"][0]["option_day__symbol"] == "JPM"
    view = p.model_view()
    assert "customer" not in str(view).lower() and "_sql" not in str(view)
    assert p.token_estimate <= s["layers"]["context_max_tokens"]


def test_undefined_concept_is_not_defined_not_guessed(built):
    s, _ = built
    p = context.build(s, "What is the dark pool volume ratio for AAPL?", "cust-harbor")
    assert p.status == "NOT_DEFINED" and p.metrics == []
