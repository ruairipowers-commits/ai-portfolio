---
title: pgvector
category: Search & retrieval
vendor: pgvector open-source project (Andrew Kane and contributors)
docs: https://github.com/pgvector/pgvector
aliases: [pgvector]
summary: PostgreSQL extension that adds a vector type and similarity search to Postgres.
---

# pgvector

pgvector is a PostgreSQL extension that stores embeddings in a `vector` column and searches them by similarity with ordinary SQL.

## What it is

pgvector is an open-source extension for PostgreSQL. It adds a `vector` data type, distance operators (`<->` for L2 distance, `<=>` for cosine distance, `<#>` for negative inner product) and approximate-nearest-neighbor indexes (HNSW and IVFFlat). Without an index it does exact search; with one it trades a little recall for speed.

Because it lives inside Postgres, vectors sit in the same rows as the metadata that describes them. A query can filter on entity, date or permission columns, join to other tables and order by similarity, all in one statement and one transaction. Backups, roles and replication are the ones you already run for Postgres.

It is available on the major managed Postgres services, including Amazon RDS and Aurora PostgreSQL.

## Typical use cases

- Retrieval-augmented generation over internal documents.
- Semantic search over tickets, runbooks or research notes.
- "Find similar" over past incidents, trades or filings.
- Deduplication and clustering of text by embedding.
- Adding vector search to an existing Postgres app without a new system.

## In AI work

pgvector is the retrieval step of RAG when the team already runs Postgres. Embeddings for document chunks are stored next to their source, section and metadata; at question time the app embeds the query, filters by metadata in `WHERE`, ranks by distance and passes the top chunks to the model with their IDs so the answer can cite them. Logging which embedding model produced each vector matters, because vectors from different models aren't comparable.

## In this portfolio

- [EOD heartbeat](../blog/posts/eod-heartbeat.md): [PostgreSQL](postgres.md) + pgvector retrieves runbook sections and past incidents, filtered by break type, so the LLM can explain each break with citations. Locally it runs on embedded Postgres via pgserver; on AWS, RDS.

## Pros and cons

| Pros | Cons |
|---|---|
| One fewer system: vectors live in the database you run | Index build and memory needs grow with large collections |
| Metadata filters, joins and vectors in one SQL query | Filtered approximate search needs care to keep recall |
| Postgres roles, backups and transactions apply | Fewer search features than a dedicated search engine (no built-in BM25) |
| Available on managed Postgres services | Tuning HNSW/IVFFlat parameters is on you |

## Basic usage

Enable the extension, store vectors and find the nearest ones:

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE runbook_chunks (
    id        bigserial PRIMARY KEY,
    section   text,
    embedding vector(3)
);

INSERT INTO runbook_chunks (section, embedding) VALUES
    ('Cash breaks',     '[0.9, 0.1, 0.0]'),
    ('Position breaks', '[0.1, 0.9, 0.0]');

SELECT section, embedding <=> '[0.8, 0.2, 0.0]' AS cosine_distance
FROM runbook_chunks
ORDER BY embedding <=> '[0.8, 0.2, 0.0]'
LIMIT 5;
```

## Documentation

[pgvector documentation](https://github.com/pgvector/pgvector) — official README and source, from the pgvector project.
