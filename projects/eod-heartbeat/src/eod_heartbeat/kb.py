"""Knowledge base: runbook sections + past incidents in pgvector, incremental and versioned (DATA-05).

Runbooks are split on their "## " sections (one chunk each, id RB-04#steps); each incident is one chunk.
Before indexing: client names, emails and phone numbers are redacted (DATA-03) and any paragraph with
instruction-like text is quarantined (SEC-02). Every explanation records the kb_version it used, and each
chunk keeps the hash of the file it came from, so a reviewer can see exactly which runbook text was cited.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil

import yaml

from . import telemetry
from .llm import Registry, embed
from .store import ROOT, Settings, connect

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"note (for|to) (ai|llm|the assistant|assistants)",
    r"\byou are now\b",
    r"^\s*(system|assistant)\s*:",
    r"do not (mention|reveal) this",
    r"always tell the (on-call|user|engineer)",
]
PII_PATTERNS = {"EMAIL": r"[\w.+-]+@[\w-]+\.[\w.-]+", "PHONE": r"\+?\d[\d\s().-]{8,}\d"}


def _sha(s: str | bytes) -> str:
    return hashlib.sha256(s if isinstance(s, bytes) else s.encode()).hexdigest()


def scan_injection(text: str) -> list[str]:
    hits = []
    for p in INJECTION_PATTERNS:
        m = re.search(p, text, re.I | re.M)
        if m:
            hits.append(f"instruction-like text: '{m.group(0).strip()}'")
    return hits


def redact(text: str, clients: list[str]) -> tuple[str, int]:
    n = 0
    for name in clients:
        text, k = re.subn(re.escape(name), "[CLIENT]", text)
        n += k
    for label, pat in PII_PATTERNS.items():
        text, k = re.subn(pat, f"[REDACTED_{label}]", text)
        n += k
    return text, n


def reset_kb(settings: Settings) -> None:
    """Copy the repo's kb/ (the source of truth) into this workspace's editable working copy."""
    shutil.rmtree(settings.kb_dir, ignore_errors=True)
    shutil.copytree(ROOT / "kb", settings.kb_dir)


def _runbook_docs(settings: Settings) -> list[dict]:
    docs = []
    for p in sorted((settings.kb_dir / "runbooks").glob("*.md")):
        raw = p.read_text()
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
        meta, body = yaml.safe_load(m.group(1)), m.group(2)
        sections = re.split(r"(?m)^## ", body)[1:]
        chunks = []
        for sec in sections:
            head, _, text = sec.partition("\n")
            chunks.append({"chunk_id": f"{meta['id']}#{re.sub(r'[^a-z]+', '-', head.lower()).strip('-')}",
                           "section": head.strip(), "text": text.strip()})
        docs.append({"doc_id": meta["id"], "kind": "runbook", "title": meta["title"], "path": f"runbooks/{p.name}",
                     "sha": _sha(raw), "break_types": meta["break_types"], "hints": meta.get("hints", []),
                     "chunks": chunks})
    return docs


def _incident_docs(settings: Settings) -> list[dict]:
    raw = (settings.kb_dir / "incidents.yaml").read_text()
    docs = []
    for i in yaml.safe_load(raw)["incidents"]:
        text = f"{i['summary']}. Root cause: {i['root_cause']}. Resolution: {i['resolution']}. Runbook: {i['runbook']}."
        docs.append({"doc_id": i["id"], "kind": "incident", "title": i["summary"], "path": "incidents.yaml",
                     "sha": _sha(json.dumps(i, sort_keys=True, default=str)), "break_types": [i["break_type"]],
                     "hints": i.get("hints", []), "chunks": [{"chunk_id": i["id"], "section": "incident", "text": text}]})
    return docs


def index(settings: Settings, full: bool = False, actor: str = "cli") -> dict:
    cfg = settings["kb"]
    reg = Registry(ROOT / "config" / "models.yaml")
    espec = reg.resolve(settings["llm"]["embedding_alias"])
    chash = _sha(json.dumps({**cfg, "embedding": espec.name, "dims": espec.dimensions}, sort_keys=True))[:12]
    clients = yaml.safe_load((settings.kb_dir / cfg["client_register"]).read_text())["clients"] if cfg["redact_pii"] else []
    docs = _runbook_docs(settings) + _incident_docs(settings)
    stats = {"docs": len(docs), "docs_changed": 0, "chunks": 0, "quarantined": 0, "pii_redactions": 0, "embed_tokens": 0}
    with connect(settings) as con:
        con.execute("create schema if not exists kb")
        con.execute("""create table if not exists kb.quarantine (chunk_id text, doc_id text, reason text, text text,
                       ts timestamptz default now())""")
        con.execute("""create table if not exists kb.index_runs (kb_version text, ts timestamptz default now(),
                       embedding_model text, dims int, docs int, docs_changed int, chunks int, quarantined int,
                       pii_redactions int, active boolean)""")
        dims = con.execute("""select atttypmod from pg_attribute where attrelid = to_regclass('kb.chunks')
                              and attname = 'embedding'""").fetchone()
        if full or (dims and dims["atttypmod"] != espec.dimensions):
            con.execute("drop table if exists kb.chunks")
            con.execute("delete from kb.quarantine")
        con.execute(f"""create table if not exists kb.chunks (chunk_id text primary key, doc_id text, kind text,
                        title text, section text, text text, break_types text[], hints text[], doc_sha text,
                        config_hash text, embedding vector({espec.dimensions}))""")
        live = set()
        for d in docs:
            live.add(d["doc_id"])
            have = con.execute("select count(*) as n from kb.chunks where doc_id = %s and doc_sha = %s and config_hash = %s",
                               (d["doc_id"], d["sha"], chash)).fetchone()["n"]
            if have:
                stats["chunks"] += have
                continue
            stats["docs_changed"] += 1
            con.execute("delete from kb.chunks where doc_id = %s", (d["doc_id"],))
            con.execute("delete from kb.quarantine where doc_id = %s", (d["doc_id"],))
            rows = []
            for c in d["chunks"]:
                kept = []
                for para in re.split(r"\n\s*\n|\n(?=\d+\. |- )", c["text"]):
                    para = para.strip()
                    if not para:
                        continue
                    hits = scan_injection(para)
                    if hits and cfg["quarantine_suspicious"]:
                        con.execute("insert into kb.quarantine (chunk_id, doc_id, reason, text) values (%s,%s,%s,%s)",
                                    (c["chunk_id"], d["doc_id"], "; ".join(hits), para))
                        stats["quarantined"] += 1
                        continue
                    para, n = redact(para, clients)
                    stats["pii_redactions"] += n
                    kept.append(para)
                if kept:
                    rows.append({**c, "text": "\n".join(kept)})
            if rows:
                vecs, tok, _ = embed(reg, espec.name, [f"{d['title']} — {r['section']}\n{r['text']}" for r in rows])
                stats["embed_tokens"] += tok
                for r, v in zip(rows, vecs):
                    con.execute("""insert into kb.chunks values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)""",
                                (r["chunk_id"], d["doc_id"], d["kind"], d["title"], r["section"], r["text"],
                                 d["break_types"], d["hints"], d["sha"], chash, json.dumps(v)))
            stats["chunks"] += len(rows)
        for (old,) in [tuple(r.values()) for r in con.execute("select distinct doc_id from kb.chunks").fetchall()]:
            if old not in live:
                con.execute("delete from kb.chunks where doc_id = %s", (old,))
        shas = sorted((r["doc_id"], r["doc_sha"]) for r in con.execute("select distinct doc_id, doc_sha from kb.chunks"))
        version = _sha(json.dumps([chash, shas]))[:12]
        con.execute("update kb.index_runs set active = false")
        con.execute("""insert into kb.index_runs (kb_version, embedding_model, dims, docs, docs_changed, chunks, quarantined,
                       pii_redactions, active) values (%s,%s,%s,%s,%s,%s,%s,%s,true)""",
                    (version, espec.name, espec.dimensions, stats["docs"], stats["docs_changed"], stats["chunks"],
                     con.execute("select count(*) as n from kb.quarantine").fetchone()["n"], stats["pii_redactions"]))
        con.commit()
    stats.update(kb_version=version, embedding_model=espec.name)
    telemetry.record("kb-index", actor=actor, items=stats["docs_changed"], rows_in=stats["chunks"],
                     input_tokens=stats["embed_tokens"], model=espec.name,
                     flags=["quarantined_chunks"] if stats["quarantined"] else [],
                     detail={"kb_version": version, "quarantined": stats["quarantined"]})
    return stats


def active_version(con) -> dict | None:
    r = con.execute("select * from kb.index_runs where active order by ts desc limit 1").fetchone()
    return r


def retrieve(con, settings: Settings, registry: Registry, brk: dict) -> tuple[list[dict], list[dict]]:
    """Runbook sections and incidents for one break: vector search filtered to the break type, then the
    causes + steps sections of the top two runbooks are always included (so the step cited is the real step)."""
    q = f"{brk['break_type'].replace('_', ' ')} {brk['hints'].replace(',', ' ')} {brk['detail']}"
    vecs, _, _ = embed(registry, settings["llm"]["embedding_alias"], [q])
    qv = json.dumps(vecs[0])
    r = settings["retrieval"]
    top = con.execute("""select chunk_id, doc_id, title, section, text, break_types, hints,
                                round((embedding <=> %s::vector)::numeric, 4) as distance
                         from kb.chunks where kind = 'runbook' and %s = any(break_types)
                         order by embedding <=> %s::vector limit %s""",
                      (qv, brk["break_type"], qv, r["runbook_k"])).fetchall()
    docs = list(dict.fromkeys(t["doc_id"] for t in top))[:2]
    extra = con.execute("""select chunk_id, doc_id, title, section, text, break_types, hints, null::numeric as distance
                           from kb.chunks where doc_id = any(%s) and section in ('Likely causes', 'Steps')""",
                        (docs,)).fetchall() if docs else []
    seen, runbooks = set(), []
    for c in list(top) + list(extra):
        if c["chunk_id"] not in seen:
            seen.add(c["chunk_id"])
            runbooks.append(dict(c))
    incidents = con.execute("""select chunk_id, doc_id, title, text, break_types, hints,
                                      round((embedding <=> %s::vector)::numeric, 4) as distance
                               from kb.chunks where kind = 'incident' and %s = any(break_types)
                               order by embedding <=> %s::vector limit %s""",
                            (qv, brk["break_type"], qv, r["incident_k"])).fetchall()
    return runbooks, [dict(i) for i in incidents]
