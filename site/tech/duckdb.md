---
title: DuckDB
category: Data & storage
vendor: DuckDB Foundation
docs: https://duckdb.org/docs/current/
aliases: [DuckDB]
summary: In-process analytical SQL database — "SQLite for analytics".
---

# DuckDB

DuckDB is an in-process analytical SQL database: a library you import, not a server you run.

## What it is

DuckDB is an open-source, columnar SQL engine designed for analytical queries — scans, joins and aggregations over many rows. It runs inside the host process (Python, R, the command line, Node.js and others), stores a database in a single file or in memory, and needs no server, users or network setup. The project is stewarded by the non-profit DuckDB Foundation, with development led by DuckDB Labs.

It reads CSV, Parquet and JSON directly, so a lot of work happens with no load step at all: `select ... from 'file.parquet'`. In Python it exchanges data with pandas, Polars and Arrow without copying everything through Python objects.

It is not a multi-user transactional database. One process writes at a time; for concurrent writers, row-level updates under load, or extensions like pgvector, PostgreSQL is the better fit.

## Typical use cases

- Local analytics on files without standing up a warehouse.
- A dev and CI target for dbt projects that run on a cloud warehouse in production.
- Ad-hoc data profiling and quality checks on vendor files.
- Embedding analytical SQL inside an application or notebook.
- Converting between CSV, JSON and Parquet.

## In AI work

DuckDB is a practical way to prepare and check data before it reaches a model: profile a sample, compute scores and aggregates in SQL, and pass the model a small, tested result instead of raw rows. Because it is a single file with no server, a whole pipeline — data, transformations and audit tables — can run offline in CI with a mock model, which keeps evals reproducible.

## In this portfolio

- [Alt-data vendor triage](../blog/posts/altdata-triage.md): [dbt](dbt.md) on DuckDB scores vendor data samples, with 14 dbt tests as the quality gate before an LLM drafts each vendor memo. The AWS path swaps DuckDB for Glue and Athena.

## Pros and cons

| Pros | Cons |
|---|---|
| Zero infrastructure: a pip install and a file | Single writer; not built for concurrent transactional workloads |
| Fast columnar execution for analytical queries | Not a shared, networked database for many users |
| Queries CSV/Parquet/JSON in place | Some SQL and extension behavior differs from Postgres |
| Works well as a dbt dev/CI target | Datasets larger than one machine need a different engine |

## Basic usage

Query a CSV file directly from Python:

```python
import duckdb

con = duckdb.connect("warehouse.duckdb")
rows = con.sql("""
    select vendor, count(*) as n_rows, avg(price) as avg_price
    from read_csv_auto('sample.csv')
    group by vendor
    order by n_rows desc
""").fetchall()
print(rows)
```

## Documentation

[DuckDB documentation](https://duckdb.org/docs/current/) — official, from the DuckDB Foundation.
