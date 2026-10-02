---
title: sqlite-vec
category: Search & retrieval
vendor: Alex Garcia (open-source project)
docs: https://alexgarcia.xyz/sqlite-vec/
aliases: [sqlite-vec]
summary: SQLite extension for storing and searching vectors inside a SQLite file.
---

# sqlite-vec

sqlite-vec is a small SQLite extension that adds vector storage and nearest-neighbor search to an ordinary SQLite database.

## What it is

sqlite-vec is an open-source extension written in C with no dependencies, created by Alex Garcia. It provides a `vec0` virtual table for storing embeddings and SQL functions for vector math. You load it into a SQLite connection (the Python package wraps this as `sqlite_vec.load()`), create a `vec0` table with a fixed dimension, and query it with `MATCH` plus a `k` limit to get the nearest rows by distance.

Vectors sit in the same file as everything else, keyed by `rowid`, so they join naturally to document and metadata tables. Search is brute-force over the stored vectors, which is simple and exact and comfortably fast at the scale of a team's document set; it is not designed for very large collections in the way a dedicated vector database is.

The project is pre-1.0, so pin the version and expect the API to change between minor releases.

## Typical use cases

- Local or embedded RAG without a vector database service.
- Semantic search in desktop, mobile or edge apps.
- Prototypes and evals that need a reproducible, single-file index.
- Vector half of a hybrid search next to SQLite FTS5.
- "Find similar" over a modest set of notes or records.

## In AI work

sqlite-vec makes a whole retrieval stack portable: documents, embeddings, keyword index and entitlements in one file that runs offline in CI with a mock model. Pair it with FTS5 and fuse the two rankings; apply permission filters in SQL before results reach the prompt; record which embedding model produced the vectors so they can be rebuilt consistently.

## In this portfolio

- [Research Q&A](../blog/posts/research-qa-rag.md): one [SQLite](sqlite.md) file holds [FTS5](sqlite-fts5.md) BM25 keyword search and sqlite-vec vector search, fused with reciprocal rank fusion, with an entitlement filter in SQL. The AWS path replaces it with Bedrock Knowledge Bases on OpenSearch Serverless.

## Pros and cons

| Pros | Cons |
|---|---|
| No extra service; vectors live in the SQLite file | Pre-1.0; API may change |
| Exact search, simple to reason about | Brute-force search; not meant for very large collections |
| Joins to metadata and entitlement tables in SQL | Requires a SQLite build that allows loading extensions |
| Runs anywhere SQLite runs, including CI | Smaller community than pgvector or dedicated vector DBs |

## Basic usage

Load the extension, store vectors and query the nearest neighbors:

```python
import sqlite3
import sqlite_vec

con = sqlite3.connect(":memory:")
con.enable_load_extension(True)
sqlite_vec.load(con)
con.enable_load_extension(False)

con.execute("create virtual table chunks using vec0(embedding float[3])")
for rowid, vec in [(1, [0.9, 0.1, 0.0]), (2, [0.1, 0.9, 0.0])]:
    con.execute("insert into chunks(rowid, embedding) values (?, ?)",
                (rowid, sqlite_vec.serialize_float32(vec)))

rows = con.execute(
    "select rowid, distance from chunks where embedding match ? and k = 2 order by distance",
    (sqlite_vec.serialize_float32([0.8, 0.2, 0.0]),),
).fetchall()
print(rows)
```

## Documentation

[sqlite-vec documentation](https://alexgarcia.xyz/sqlite-vec/) — official, from the sqlite-vec project. Source: [asg017/sqlite-vec on GitHub](https://github.com/asg017/sqlite-vec).
