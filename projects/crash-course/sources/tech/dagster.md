---
title: Dagster
category: Orchestration & agents
vendor: Dagster Labs
docs: https://docs.dagster.io/
aliases: [Dagster]
summary: Data orchestrator built around software-defined assets — the tables and files a pipeline produces.
---

# Dagster

Dagster schedules and runs data pipelines described as the assets they produce, rather than as tasks.

## What it is

Dagster is an open-source orchestrator from Dagster Labs. You declare *assets* (a table, a file, a model) with the
Python function that materialises them and the assets they depend on; Dagster derives the graph, runs it, records
metadata and lineage, and runs *asset checks* (tests) against the results. Jobs and schedules select assets to
refresh. A local UI (`dagster dev`) shows the asset graph and run history.

## Typical use cases

- Daily data builds where lineage between tables matters.
- dbt projects orchestrated alongside Python steps.
- Data quality checks attached to the asset they test.

## In AI work

Asset lineage answers "what feeds what the model reads", and asset checks make quality a precondition for the AI
step rather than a report after it.

## In this portfolio

- [Data marketplace & lifecycle platform](../blog/posts/data-lifecycle-platform.md): landing files → semantic layer
  (dbt build, with a check that every test passed) → knowledge graph (with a SHACL check), plus a weekday
  renewal-alert job. The same functions back the CLI, so CI doesn't need Dagster running. [Airflow](airflow.md) is used
  in EOD heartbeat for comparison.

## Pros and cons

| Pros | Cons |
|---|---|
| Asset-first model matches how data teams think | Heavier install than a cron job |
| Lineage and checks built in | Concepts (assets, ops, jobs, resources) take time to learn |
| Good local developer experience | Hosted features need Dagster+ |

## Basic usage

```python
from dagster import Definitions, asset

@asset
def semantic_layer():
    ...  # dbt build

@asset(deps=[semantic_layer])
def knowledge_graph():
    ...  # build, SHACL, load

defs = Definitions(assets=[semantic_layer, knowledge_graph])
```

```bash
dagster dev -m dlp.orchestration
```

## Documentation

[Dagster documentation](https://docs.dagster.io/) — official, from Dagster Labs.
