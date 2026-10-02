---
title: dbt
category: Data & storage
vendor: dbt Labs
docs: https://docs.getdbt.com/
aliases: [dbt-postgres, dbt]
summary: SQL transformation framework with tests, lineage and docs; runs on most warehouses.
---

# dbt

dbt turns a folder of SQL `select` statements into a tested, versioned, dependency-ordered set of tables and views in your warehouse.

## What it is

dbt (data build tool) is maintained by dbt Labs. You write each model as a `select` statement, reference upstream models with `{{ ref('...') }}`, and dbt works out the build order, materializes the results as tables or views, and records lineage. Configuration and tests live alongside the SQL in YAML files, so transformation logic goes through the same code review and Git history as application code.

dbt itself doesn't store or compute anything; an adapter connects it to a database. The same project can run on DuckDB on a laptop and on Postgres, Snowflake, Athena or another warehouse in production by switching the target in `profiles.yml` — `dbt-duckdb` and `dbt-postgres` are two such adapters.

Tests are the part that matters most for a data team: generic tests (`not_null`, `unique`, `accepted_values`, `relationships`) and custom SQL tests fail the build when data breaks an assumption.

## Typical use cases

- Building staging, intermediate and reporting layers in a warehouse.
- Data-quality checks that block bad data from reaching consumers.
- Documenting columns and lineage for analysts and auditors.
- Porting the same transformations between a local engine and a cloud warehouse.
- Incremental models for large, append-heavy tables.

## In AI work

dbt is useful before the model is called. Compute scores, breaks and aggregates in SQL, test them, and only then hand the results to an LLM to explain or draft from. A failed dbt test becomes a hard stop: the model never sees data that didn't pass the gate, and the numbers in any AI output trace back to a tested SQL model rather than to the model's arithmetic.

## In this portfolio

- [Alt-data vendor triage](../blog/posts/altdata-triage.md): dbt on [DuckDB](duckdb.md) scores vendor data samples, with 14 dbt tests as a quality gate before any LLM call.
- [EOD heartbeat](../blog/posts/eod-heartbeat.md): dbt-postgres models on [PostgreSQL](postgres.md) find end-of-day breaks, backed by 28 tests, and run from an [Airflow](airflow.md) DAG.

## Pros and cons

| Pros | Cons |
|---|---|
| Transformations are plain SQL under version control | Jinja templating can make SQL hard to read |
| Built-in tests act as a data-quality gate | Not an orchestrator; scheduling lives elsewhere |
| Same project runs on many warehouses via adapters | Adapters differ in SQL dialect and feature support |
| Lineage and docs generated from the project | Large projects need conventions or they sprawl |

## Basic usage

A model that references another model, plus a test, then a build:

```sql
-- models/daily_positions.sql
select account_id, as_of_date, sum(quantity) as quantity
from {{ ref('stg_positions') }}
group by account_id, as_of_date
```

```yaml
# models/schema.yml
version: 2
models:
  - name: daily_positions
    columns:
      - name: account_id
        tests: [not_null]
```

```bash
dbt build   # runs models and their tests in dependency order
```

## Documentation

[dbt documentation](https://docs.getdbt.com/) — official, from dbt Labs. Adapter setup for Postgres: [dbt-postgres setup](https://docs.getdbt.com/docs/core/connect-data-platform/postgres-setup).
