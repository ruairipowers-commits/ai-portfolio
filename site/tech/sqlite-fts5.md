---
title: SQLite FTS5
category: Search & retrieval
vendor: SQLite project (D. Richard Hipp and the SQLite developers)
docs: https://sqlite.org/fts5.html
aliases: [FTS5]
summary: SQLite's built-in full-text search extension with BM25 ranking.
---

# SQLite FTS5

FTS5 is SQLite's full-text search extension: an inverted index you create as a virtual table and query with `MATCH`.

## What it is

FTS5 ships with the SQLite source and is compiled into most builds, including the one bundled with most Python distributions. You declare a virtual table with the columns to index; FTS5 tokenizes the text and maintains an inverted index. Queries use `MATCH` with a small query language — terms, phrases in quotes, `AND`/`OR`/`NOT`, prefix matches (`liquid*`) and `NEAR`.

Results can be ranked with the built-in `bm25()` function (lower is better; `ORDER BY rank` uses it by default), and helper functions `highlight()` and `snippet()` return the matching text with markers. Tokenizers control how text is split; `porter` adds English stemming and `trigram` supports substring search.

It is keyword search, not semantic search: it finds the words you typed (or their stems), not paraphrases.

## Typical use cases

- Search boxes in internal tools and desktop apps.
- Searching logs, tickets or notes stored in SQLite.
- Exact matching of identifiers, tickers and codes.
- Keyword half of a hybrid search alongside vector search.
- Generating highlighted snippets for search results.

## In AI work

Keyword search catches what embeddings miss: exact tickers, ISINs, fund names, error codes and rare terms. In a RAG system, running BM25 next to vector search and fusing the two ranked lists (for example with reciprocal rank fusion) usually retrieves better context than either alone, and the BM25 side is cheap, deterministic and easy to explain when someone asks why a passage was retrieved.

## In this portfolio

- [Research Q&A](../blog/posts/research-qa-rag.md): one [SQLite](sqlite.md) file holds FTS5 BM25 keyword search and [sqlite-vec](sqlite-vec.md) vector search, fused with reciprocal rank fusion, with an entitlement filter in SQL.

## Pros and cons

| Pros | Cons |
|---|---|
| Built into SQLite; no extra service | Keyword only — no synonyms or semantic matching |
| BM25 ranking, snippets and highlighting included | Query syntax errors on raw user input unless escaped |
| Deterministic and explainable results | Tokenizer choice matters and is fixed per table |
| Lives in the same file and transaction as the data | Single-writer limits of SQLite apply |

## Basic usage

Index some text and search it with BM25 ranking:

```python
import sqlite3

con = sqlite3.connect(":memory:")
con.execute("create virtual table pages using fts5(doc, body)")
con.executemany("insert into pages values (?, ?)", [
    ("note-1", "Liquidity in credit markets tightened in September."),
    ("note-2", "Equity volatility fell after the rate decision."),
])

query = "select doc, bm25(pages) from pages where pages match ? order by rank"
for row in con.execute(query, ("liquidity",)):
    print(row)
```

## Documentation

[SQLite FTS5 documentation](https://sqlite.org/fts5.html) — official, from the SQLite project.
