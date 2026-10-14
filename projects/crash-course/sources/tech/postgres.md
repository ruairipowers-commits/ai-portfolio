---
title: PostgreSQL
category: Data & storage
vendor: PostgreSQL Global Development Group
docs: https://www.postgresql.org/docs/
aliases: [PostgreSQL, Postgres]
summary: Open-source relational database; transactional workhorse with a deep extension ecosystem.
---

# PostgreSQL

PostgreSQL is a mature, open-source relational database that handles transactional workloads, moderate analytics and, through extensions, vector search.

## What it is

PostgreSQL (Postgres) is developed by the PostgreSQL Global Development Group under a permissive license. It is a client-server database with full ACID transactions, rich SQL (window functions, CTEs, JSONB, partial and expression indexes), row-level security, and roles and grants for access control.

Its extension system is what keeps it relevant for new workloads: pgvector adds vector similarity search, and other extensions add time series, geospatial and more, all inside the same database and transaction model. Every major cloud offers it as a managed service (on AWS, RDS for PostgreSQL and Aurora PostgreSQL).

The cost relative to an embedded engine is operations: a server to run, connections to manage, backups, upgrades and vacuuming to plan for.

## Typical use cases

- Application databases for internal tools and services.
- Operational data stores for trade, position and reference data.
- Audit and event tables that need transactional guarantees.
- Moderate-scale reporting and dbt transformations.
- Vector search next to relational data, via pgvector.

## In AI work

Postgres lets one database hold the relational facts, the documents an LLM retrieves from and the audit trail of what the model was asked and answered. With pgvector, retrieval can filter on ordinary columns (entity, date, entitlement) and rank by similarity in a single SQL query, so access control and retrieval use the same mechanism. Row-level security and grants apply to that retrieval path like any other query.

## In this portfolio

- [EOD heartbeat](../blog/posts/eod-heartbeat.md): [dbt](dbt.md)-postgres models find end-of-day breaks, and Postgres with [pgvector](pgvector.md) retrieves runbook sections and past incidents; locally it runs as embedded Postgres via pgserver, on AWS as RDS.
- [Trade-ops exception agent](../blog/posts/trade-ops-exceptions.md) and [governance console](../blog/posts/governance-console.md): [SQLite](sqlite.md) by default, with Postgres as the option (RDS / Aurora Serverless v2 on the AWS path).

## Pros and cons

| Pros | Cons |
|---|---|
| Proven transactional engine with strong SQL | A server to operate: backups, upgrades, vacuum, connections |
| Extensions (pgvector and others) avoid extra systems | Large analytical scans are slower than a columnar engine |
| Managed everywhere, including RDS and Aurora | Connection limits need pooling under many clients |
| Roles, grants and row-level security for access control | Tuning (indexes, memory settings) needs expertise at scale |

## Basic usage

Create a table and query it with `psql`:

```sql
CREATE TABLE breaks (
    id          bigserial PRIMARY KEY,
    account     text        NOT NULL,
    as_of_date  date        NOT NULL,
    difference  numeric     NOT NULL
);

INSERT INTO breaks (account, as_of_date, difference)
VALUES ('FUND-01', '2026-09-30', -15.00);

SELECT account, sum(difference) AS total
FROM breaks
GROUP BY account;
```

## Documentation

[PostgreSQL documentation](https://www.postgresql.org/docs/) — official, from the PostgreSQL Global Development Group.
