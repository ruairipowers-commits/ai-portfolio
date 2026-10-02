---
title: SQLite
category: Data & storage
vendor: SQLite project (D. Richard Hipp and the SQLite developers)
docs: https://sqlite.org/docs.html
aliases: [SQLite]
summary: Embedded, serverless SQL database in a single file; ships with Python.
---

# SQLite

SQLite is a small, embedded SQL database engine that keeps an entire database in one ordinary file.

## What it is

SQLite is a C library, in the public domain, that implements a transactional SQL database without a server. The application opens a file and runs SQL against it in-process; there is no install, no network port and no user management. Python includes it in the standard library as `sqlite3`.

It supports transactions, indexes, views, triggers, JSON functions and virtual tables, which is how extensions such as FTS5 (full-text search) and sqlite-vec (vector search) plug in. With write-ahead logging (WAL) it handles many readers alongside one writer well.

The limits follow from the design: one writer at a time, no built-in access control beyond file permissions, and no network access for remote clients. When several services need to write concurrently, PostgreSQL is the usual next step.

## Typical use cases

- Application storage for single-node tools and services.
- Local caches and offline-first apps.
- Test fixtures and CI databases.
- File formats for shipping a dataset with its indexes.
- Audit and event logs for small deployments.

## In AI work

SQLite keeps a small AI system to one file: documents, chunk metadata, a keyword index (FTS5), a vector index (sqlite-vec), the agent's state and the audit log of model calls. That makes demos and evals reproducible — copy the file and you have the exact state — and lets permission filters run as SQL `WHERE` clauses in the same query as retrieval.

## In this portfolio

- [Research Q&A](../blog/posts/research-qa-rag.md): one SQLite file holds [FTS5](sqlite-fts5.md) BM25 keyword search and [sqlite-vec](sqlite-vec.md) vector search, fused with reciprocal rank fusion, with the entitlement filter in SQL.
- [Trade-ops exception agent](../blog/posts/trade-ops-exceptions.md): SQLite by default, with a [PostgreSQL](postgres.md) option.
- [Governance console](../blog/posts/governance-console.md): SQLite or Postgres event store.

## Pros and cons

| Pros | Cons |
|---|---|
| No server; the database is one file | One writer at a time |
| In Python's standard library | No users, roles or network access built in |
| Extensions add full-text and vector search | Fewer data types and ALTER TABLE options than Postgres |
| Easy to copy, back up and ship with tests | Not suited to many concurrent writers across hosts |

## Basic usage

Create a table and query it with Python's built-in `sqlite3`:

```python
import sqlite3

con = sqlite3.connect("app.db")
con.execute("create table if not exists events (ts text, kind text, detail text)")
con.execute("insert into events values (datetime('now'), 'model_call', 'memo drafted')")
con.commit()

for row in con.execute("select kind, count(*) from events group by kind"):
    print(row)
con.close()
```

## Documentation

[SQLite documentation](https://sqlite.org/docs.html) — official, from the SQLite project.
