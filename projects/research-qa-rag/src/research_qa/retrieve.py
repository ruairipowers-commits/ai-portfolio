"""Hybrid retrieval: FTS5 BM25 + sqlite-vec cosine, fused with reciprocal rank fusion (RRF).

The entitlement and licence filters are part of the SQL WHERE clause of *both* retrievers, so a chunk the
user may not see is never ranked, never fused and never reaches the model (FR-4, NFR-3). The trace records
how many matching chunks each filter removed, for the audit log and the admin view in the app.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlite_vec

from . import guardrails as G
from .llm import Registry, embed, tokens

SELECT = """select c.rowid, c.chunk_id, c.doc_id, c.page, c.section, c.text, c.entitlement, c.ai_processing,
                   d.title, d.company, d.ticker, d.source, d.doc_type, d.published"""


@dataclass
class Retrieved:
    chunks: list[dict]
    trace: list[dict]                      # every candidate with its BM25 / vector rank and fused score
    excluded_entitlement: int = 0          # matching chunks hidden by the entitlement filter
    excluded_licence: int = 0              # matching chunks whose licence forbids AI processing
    dropped_runtime: list[str] = field(default_factory=list)   # SEC-02 second screen at query time
    embed_tokens: int = 0


def fts_query(question: str) -> str:
    terms = sorted({re.sub(r"[^a-z0-9]", "", t) for t in tokens(question)} - {""})
    return " OR ".join(f'"{t}"' for t in terms)


def _bm25(con, q: str, where: str, params: list, n: int) -> list[dict]:
    if not q:
        return []
    rows = con.execute(f"""{SELECT}, bm25(chunks_fts) as score from chunks_fts
                           join chunks c on c.rowid = chunks_fts.rowid join documents d using (doc_id)
                           where chunks_fts match ? and {where} order by score limit ?""", [q, *params, n]).fetchall()
    return [dict(r) for r in rows]


def _vector(con, qvec: bytes, where: str, params: list, n: int) -> list[dict]:
    rows = con.execute(f"""{SELECT}, vec_distance_cosine(c.embedding, ?) as score from chunks c
                           join documents d using (doc_id)
                           where c.embedding is not null and {where} order by score limit ?""",
                       [qvec, *params, n]).fetchall()
    return [dict(r) for r in rows]


def retrieve(con, question: str, entitlements: list[str], settings, registry: Registry, mode: str | None = None,
             top_k: int | None = None) -> Retrieved:
    r = settings["retrieval"]
    mode, top_k, n = mode or r["mode"], top_k or r["top_k"], r["candidates"]
    marks = ",".join("?" * len(entitlements))
    allowed = f"c.entitlement in ({marks}) and c.ai_processing = 1 and c.quarantined = 0"
    q = fts_query(question)

    lists: dict[str, list[dict]] = {}
    tok = 0
    if mode in ("hybrid", "bm25"):
        lists["bm25"] = _bm25(con, q, allowed, entitlements, n)
    if mode in ("hybrid", "vector"):
        vecs, tok, _ = embed(registry, settings["llm"]["embedding_alias"], [question])
        lists["vector"] = _vector(con, sqlite_vec.serialize_float32(vecs[0]), allowed, entitlements, n)

    # What the filters removed (counted with the keyword retriever, which also covers keyword-only documents).
    excl_ent = excl_lic = 0
    if q:
        excl_ent = con.execute(f"""select count(*) from chunks_fts join chunks c on c.rowid = chunks_fts.rowid
                                   where chunks_fts match ? and c.entitlement not in ({marks})""",
                               [q, *entitlements]).fetchone()[0]
        excl_lic = con.execute(f"""select count(*) from chunks_fts join chunks c on c.rowid = chunks_fts.rowid
                                   where chunks_fts match ? and c.entitlement in ({marks}) and c.ai_processing = 0""",
                               [q, *entitlements]).fetchone()[0]

    fused: dict[str, dict] = {}
    for name, rows in lists.items():
        for rank, row in enumerate(rows, start=1):
            f = fused.setdefault(row["chunk_id"], {**row, "bm25_rank": None, "vector_rank": None, "rrf": 0.0})
            f[f"{name}_rank"] = rank
            f["rrf"] += 1.0 / (r["rrf_k"] + rank)
    ranked = sorted(fused.values(), key=lambda x: (-x["rrf"], x["chunk_id"]))

    chunks, dropped = [], []
    for c in ranked:
        if len(chunks) >= top_k:
            break
        if G.scan_injection(c["text"]):          # quarantine was off or missed it: never send it to the model
            dropped.append(c["chunk_id"])
            continue
        chunks.append(c)
    trace = [{"chunk_id": c["chunk_id"], "doc": c["title"], "page": c["page"], "bm25_rank": c["bm25_rank"],
              "vector_rank": c["vector_rank"], "rrf": round(c["rrf"], 4),
              "used": c in chunks, "runtime_dropped": c["chunk_id"] in dropped} for c in ranked[: max(top_k * 2, 10)]]
    return Retrieved(chunks, trace, excl_ent, excl_lic, dropped, tok)
