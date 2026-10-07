---
title: Oxigraph and SHACL
category: Data & storage
vendor: Oxigraph project (open source) · W3C (RDF, SPARQL, SHACL)
docs: https://pyoxigraph.readthedocs.io/
aliases: [Oxigraph, SHACL, pyshacl, rdflib, RDF, SPARQL, OWL]
summary: An embedded RDF graph store with SPARQL, plus SHACL — the W3C standard for validating graph data.
---

# Oxigraph and SHACL

Oxigraph is a small, embeddable graph database for RDF that answers SPARQL; SHACL is the W3C language for saying what
valid graph data looks like.

## What it is

RDF stores facts as triples (subject, predicate, object) with web-style identifiers, so data from different sources
joins on shared IRIs. OWL and SKOS describe the classes, properties and controlled vocabularies (the ontology).
SPARQL is the query language. Oxigraph is an open-source RDF store written in Rust with Python bindings
(`pyoxigraph`); like DuckDB, it runs in-process and stores to a folder. SHACL shapes (validated in Python with
`pyshacl`) state rules such as "every dataset has exactly one vendor" or "a contract ends after it starts".

## Typical use cases

- Knowledge graphs that link catalog entities, organisations and reference data.
- Data catalogs and lineage with typed relationships.
- Validating graph data before it's published (SHACL as a quality gate).

## In AI work

A graph gives a model facts with stable identifiers it can cite, and a place for relationships that tables model
badly (which dataset covers which companies, what depends on what). SHACL plays the role dbt tests play for tables:
nothing malformed reaches the layer the model reads from.

## In this portfolio

- [Data marketplace & lifecycle platform](../blog/posts/data-lifecycle-platform.md): an OWL/SKOS ontology and SHACL
  shapes define meaning; the graph is rebuilt from the catalog and warehouse on every build and loaded into Oxigraph
  only if SHACL passes. Search, impact analysis and the context layer read it with SPARQL. The AWS path uses Neptune.

## Pros and cons

| Pros | Cons |
|---|---|
| Standards-based; IRIs join data across sources | RDF tooling has a learning curve |
| Embedded, no server, fast enough for millions of triples | Single-node; large graphs need Neptune, GraphDB or similar |
| SHACL gives declarative, testable data rules | SHACL error reports are verbose |

## Basic usage

```python
import pyoxigraph as ox
from pyshacl import validate

conforms, _, report = validate(data_graph, shacl_graph=shapes, ont_graph=ontology, inference="rdfs")
store = ox.Store("warehouse/graph")
store.bulk_load(data_graph.serialize(format="nt").encode(), "application/n-triples")
for row in store.query("SELECT ?n WHERE { ?d a <https://w3id.org/dlp/ontology#Dataset> ; <https://w3id.org/dlp/ontology#name> ?n }"):
    print(row["n"].value)
```

## Documentation

[pyoxigraph](https://pyoxigraph.readthedocs.io/) · [SHACL (W3C)](https://www.w3.org/TR/shacl/) · [pySHACL](https://github.com/RDFLib/pySHACL)
