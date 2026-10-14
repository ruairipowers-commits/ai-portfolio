---
title: MetricFlow
category: Data & storage
vendor: dbt Labs
docs: https://docs.getdbt.com/docs/build/about-metricflow
aliases: [MetricFlow, dbt MetricFlow]
summary: The dbt semantic layer's engine — define metrics once in YAML, compile any query for them to SQL.
---

# MetricFlow

MetricFlow turns metric definitions written next to your dbt models into correct SQL for whatever slice someone asks for.

## What it is

MetricFlow is the open-source engine behind the dbt Semantic Layer, maintained by dbt Labs. You describe *semantic
models* — which table, its entities (keys), dimensions and measures — and *metrics* built from them: simple
aggregates, ratios, derived expressions. At query time you ask for metrics and group-bys
(`atm_iv by option_day__gics_sector`); MetricFlow plans the joins through entities and emits SQL for your warehouse.

It is a definitions-and-compiler layer, not a database. The SQL runs on DuckDB, Snowflake, BigQuery, Databricks,
Redshift, Postgres and others through the dbt adapter.

## Typical use cases

- One definition of "revenue" or "active users" shared by dashboards, notebooks and APIs.
- Ratios across tables (spend per query) without hand-writing the join each time.
- Letting non-SQL users query governed metrics safely.

## In AI work

A semantic layer is the cleanest way to stop a model inventing numbers: the model (or the code around it) asks for a
named metric and gets back rows plus the exact SQL, which can be logged and audited. Binding each metric to a concept
in an ontology lets natural-language questions resolve to metrics without a prompt doing the mapping.

## In this portfolio

- [Data marketplace & lifecycle platform](../blog/posts/data-lifecycle-platform.md): 12 metrics over options data
  and platform usage and spend, each tagged with the ontology concept it measures. The context layer calls MetricFlow
  to compile, runs the SQL read-only on [DuckDB](duckdb.md), and logs the SQL behind every number in an answer.

## Pros and cons

| Pros | Cons |
|---|---|
| Metrics defined once, in Git, next to the models | Another YAML vocabulary to learn |
| Correct joins across tables via entities | Python API is less documented than the CLI |
| Same definitions across warehouses | Hosted Semantic Layer APIs need dbt Cloud |

## Basic usage

```bash
pip install "dbt-metricflow[dbt-duckdb]"
mf validate-configs
mf query --metrics atm_iv,put_call_ratio --group-by option_day__gics_sector --explain   # show the SQL
```

## Documentation

[About MetricFlow](https://docs.getdbt.com/docs/build/about-metricflow) — official, from dbt Labs.
