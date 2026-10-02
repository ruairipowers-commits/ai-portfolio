"""Ingest: parse → redact → de-duplicate → screen → chunk → embed → index. Incremental and versioned (DATA-05).

Parsing is cheap and deterministic, so every run re-parses every document; only documents whose file hash
or chunking/embedding config changed are re-written and re-embedded. Each run is logged in `index_runs`,
and every answer records the index version it used.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import pymupdf
import sqlite_vec
import yaml

from . import guardrails as G
from . import telemetry
from .llm import Registry, embed
from .store import ROOT, Settings, connect

SECTION_RE = re.compile(r"^(Item \d+[A-Z]?\..*|Research note|Prepared remarks.*|Q&A)$")


def _sha(b: bytes | str) -> str:
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- parsing
def parse_pdf(path: Path) -> list[tuple[int, str, list[str]]]:
    """[(page, section, paragraphs)]. PyMuPDF text blocks are paragraphs; page headers/footers are dropped."""
    out, section = [], ""
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            paras = []
            for b in page.get_text("blocks", sort=False):
                t = re.sub(r"\s+", " ", b[4]).strip()
                if not t or re.fullmatch(r"Page \d+", t) or (b[1] < 95 and len(t.split()) <= 20):   # running title
                    continue
                if SECTION_RE.match(t):
                    section = t
                    continue
                paras.append(t)
            out.append((i, section, paras))
    return out


class _Html(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections, self._tag, self._h = [], None, ""

    def handle_starttag(self, tag, attrs):
        self._tag = tag

    def handle_endtag(self, tag):
        self._tag = None

    def handle_data(self, data):
        t = data.strip()
        if not t:
            return
        if self._tag == "h2":
            self._h = t
            self.sections.append((t, []))
        elif self._tag == "p" and self.sections:
            self.sections[-1][1].append(re.sub(r"\s+", " ", t))


def parse_html(path: Path) -> list[tuple[int, str, list[str]]]:
    """Transcripts: each <section> is a citable unit, numbered like a page."""
    p = _Html()
    p.feed(path.read_text())
    return [(i, h, paras) for i, (h, paras) in enumerate(p.sections, start=1)]


def parse(path: Path) -> list[tuple[int, str, list[str]]]:
    return parse_pdf(path) if path.suffix.lower() == ".pdf" else parse_html(path)


# ---------------------------------------------------------------- chunking
def chunk_paragraphs(paras: list[str], chunk_words: int, overlap_words: int, min_words: int) -> list[str]:
    """Greedy paragraph packing within one page; long paragraphs split on sentences; word overlap between chunks."""
    units: list[str] = []
    for p in paras:
        if len(p.split()) <= chunk_words:
            units.append(p)
        else:
            units.extend(re.split(r"(?<=[.!?])\s+", p))
    chunks, cur = [], []
    for u in units:
        if cur and len(" ".join(cur).split()) + len(u.split()) > chunk_words:
            chunks.append(" ".join(cur))
            tail = " ".join(cur).split()[-overlap_words:] if overlap_words else []
            cur = [" ".join(tail)] if tail else []
        cur.append(u)
    if cur:
        chunks.append(" ".join(cur))
    return [c for c in chunks if len(c.split()) >= min_words]


# ---------------------------------------------------------------- ingest
def config_hash(settings: Settings, embed_name: str, dims: int) -> str:
    cfg = {**settings["ingest"], "embedding": embed_name, "dimensions": dims}
    return _sha(json.dumps(cfg, sort_keys=True))[:12]


def manifest(settings: Settings) -> list[dict]:
    return yaml.safe_load((settings.corpus_dir / "manifest.yaml").read_text())["documents"]


def ingest(settings: Settings, embedding_alias: str | None = None, full: bool = False, actor: str = "cli") -> dict:
    t0 = time.perf_counter()
    cfg = settings["ingest"]
    reg = Registry(ROOT / "config" / "models.yaml")
    espec = reg.resolve(embedding_alias or settings["llm"]["embedding_alias"])
    chash = config_hash(settings, espec.name, espec.dimensions or 0)
    con = connect(settings)
    docs = manifest(settings)
    stats = {"docs": len(docs), "docs_changed": 0, "docs_unchanged": 0, "chunks": 0, "quarantined": 0,
             "dedup_dropped": 0, "pii_redactions": 0, "embed_tokens": 0}
    seen: dict[str, set[str]] = {}          # entitlement -> normalised paragraph hashes (boilerplate dedup)
    live_ids = set()
    try:
        for d in docs:
            path = settings.corpus_dir / d["file"]
            doc_sha = _sha(path.read_bytes())
            live_ids.add(d["doc_id"])
            pages = parse(path)
            # Paragraph-level work happens for every document so dedup is the same whether or not it changed.
            scope = seen.setdefault(d["entitlement"], set())
            kept_pages, quarantine_rows, n_pii, n_dup = [], [], 0, 0
            for page, section, paras in pages:
                kept = []
                for para in paras:
                    text, k = G.redact_pii(para) if cfg["redact_pii"] else (para, 0)
                    n_pii += k
                    hits = G.scan_injection(text)
                    if hits and cfg["quarantine_suspicious"]:   # screen before dedup so every copy is recorded
                        quarantine_rows.append((page, "; ".join(hits), text))
                        continue
                    h = _sha(re.sub(r"\W+", " ", text.lower()))
                    if cfg["dedup"] and h in scope:
                        n_dup += 1
                        continue
                    scope.add(h)
                    kept.append(text)
                kept_pages.append((page, section, kept))
            stats["pii_redactions"] += n_pii
            stats["dedup_dropped"] += n_dup
            stats["quarantined"] += len(quarantine_rows)

            prev = con.execute("select sha256 from documents where doc_id = ?", (d["doc_id"],)).fetchone()
            same_cfg = con.execute("select count(*) from chunks where doc_id = ? and config_hash = ?",
                                   (d["doc_id"], chash)).fetchone()[0]
            if not full and prev and prev[0] == doc_sha and same_cfg:
                stats["docs_unchanged"] += 1
                stats["chunks"] += same_cfg
                continue
            stats["docs_changed"] += 1
            con.execute("delete from chunks where doc_id = ?", (d["doc_id"],))
            con.execute("delete from quarantine where doc_id = ?", (d["doc_id"],))
            rows = []
            for page, section, kept in kept_pages:
                for n, text in enumerate(chunk_paragraphs(kept, cfg["chunk_words"], cfg["overlap_words"],
                                                          cfg["min_chunk_words"]), start=1):
                    rows.append({"chunk_id": f"{d['doc_id']}:p{page}:c{n}", "page": page, "section": section,
                                 "text": text, "words": len(text.split()), "sha": _sha(text)[:16]})
            vectors = [None] * len(rows)
            if d.get("ai_processing", True) and rows:      # DATA-04: no embedding API call for restricted documents
                vecs, tok, _ = embed(reg, espec.name, [f"{d['company']} — {d['title']}\n{r['text']}" for r in rows])
                vectors = [sqlite_vec.serialize_float32(v) for v in vecs]
                stats["embed_tokens"] += tok
            con.executemany(
                """insert into chunks (chunk_id, doc_id, page, section, text, words, sha, entitlement, ai_processing,
                   quarantined, quarantine_reason, config_hash, doc_sha, embedding)
                   values (?,?,?,?,?,?,?,?,?,0,'',?,?,?)""",
                [(r["chunk_id"], d["doc_id"], r["page"], r["section"], r["text"], r["words"], r["sha"], d["entitlement"],
                  int(d.get("ai_processing", True)), chash, doc_sha, v) for r, v in zip(rows, vectors)])
            con.executemany("insert into quarantine values (?,?,?,?,?,?)",
                            [(f"{d['doc_id']}:p{p}:q{i}", d["doc_id"], p, reason, text, now())
                             for i, (p, reason, text) in enumerate(quarantine_rows, start=1)])
            con.execute("delete from documents where doc_id = ?", (d["doc_id"],))
            con.execute(
                """insert into documents (doc_id, file, title, company, ticker, doc_type, source, published, entitlement,
                   licence, ai_processing, sha256, pages, chunks, quarantined, pii_redactions, status, ingested_at)
                   values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (d["doc_id"], d["file"], d["title"], d["company"], d["ticker"], d["doc_type"], d["source"],
                 str(d["published"]), d["entitlement"], d["licence"], int(d.get("ai_processing", True)), doc_sha,
                 len(pages), len(rows), len(quarantine_rows), n_pii,
                 "indexed" if d.get("ai_processing", True) else "keyword-only: licence forbids AI processing", now()))
            stats["chunks"] += len(rows)
        # documents removed from the manifest leave the index
        for (old,) in con.execute("select doc_id from documents").fetchall():
            if old not in live_ids:
                for t in ("chunks", "quarantine", "documents"):
                    con.execute(f"delete from {t} where doc_id = ?", (old,))
        con.execute("insert into chunks_fts(chunks_fts) values('rebuild')")
        doc_shas = sorted((r[0], r[1]) for r in con.execute("select doc_id, sha256 from documents"))
        version = _sha(json.dumps([chash, doc_shas]))[:12]
        con.execute("update index_runs set active = 0")
        con.execute("""insert into index_runs values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                    (version, now(), espec.name, espec.dimensions, cfg["chunk_words"], cfg["overlap_words"],
                     stats["docs"], stats["docs_changed"], stats["docs_unchanged"], stats["chunks"], stats["quarantined"],
                     stats["dedup_dropped"], stats["pii_redactions"], stats["embed_tokens"]))
        con.commit()
    finally:
        con.close()
    stats.update(index_version=version, embedding_model=espec.name, seconds=round(time.perf_counter() - t0, 2))
    telemetry.record("ingest", actor=actor, items=stats["docs_changed"], rows_in=stats["chunks"],
                     input_tokens=stats["embed_tokens"], model=espec.name, latency_ms=int(stats["seconds"] * 1000),
                     flags=["quarantined_chunks"] if stats["quarantined"] else [],
                     detail={k: stats[k] for k in ("docs", "docs_unchanged", "quarantined", "dedup_dropped",
                                                   "index_version")})
    return stats


def active_index(con) -> dict | None:
    r = con.execute("select * from index_runs where active = 1 order by ts desc limit 1").fetchone()
    return dict(r) if r else None


# ---------------------------------------------------------------- adding documents ("try to break it", uploads)
def add_document(settings: Settings, *, title: str, company: str, ticker: str, entitlement: str, licence: str,
                 ai_processing: bool, text: str = "", hidden_text: str = "", pdf_bytes: bytes | None = None,
                 doc_type: str = "broker_note", source: str = "") -> str:
    """Write a new document into the corpus (PDF) and add it to the manifest. Run ingest() afterwards."""
    corpus = settings.corpus_dir
    slug = re.sub(r"[^a-z0-9]+", "-", f"{source or 'upload'}-{ticker}".lower()).strip("-")
    existing = {d["doc_id"] for d in manifest(settings)}
    doc_id = slug
    n = 2
    while doc_id in existing:
        doc_id, n = f"{slug}-{n}", n + 1
    path = corpus / f"{doc_id}.pdf"
    if pdf_bytes:
        path.write_bytes(pdf_bytes)
    else:
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_textbox(pymupdf.Rect(54, 54, 558, 90), title.replace("—", "-"), fontsize=13, fontname="helv")
        page.insert_textbox(pymupdf.Rect(54, 100, 558, 120), "Research note", fontsize=11, fontname="hebo")
        page.insert_textbox(pymupdf.Rect(54, 128, 558, 640), text, fontsize=10, fontname="helv", lineheight=1.35)
        if hidden_text:   # white 4pt text: invisible on the page, present in the extracted text
            page.insert_textbox(pymupdf.Rect(54, 650, 558, 740), hidden_text, fontsize=4, fontname="helv", color=(1, 1, 1))
        doc.save(path)
        doc.close()
    m = yaml.safe_load((corpus / "manifest.yaml").read_text())
    m["documents"].append({"doc_id": doc_id, "file": path.name, "doc_type": doc_type, "source": source or "Upload",
                           "title": title, "company": company, "ticker": ticker,
                           "published": datetime.now(timezone.utc).date().isoformat(), "entitlement": entitlement,
                           "licence": licence, "ai_processing": bool(ai_processing)})
    (corpus / "manifest.yaml").write_text(yaml.safe_dump(m, sort_keys=False, allow_unicode=True))
    return doc_id
