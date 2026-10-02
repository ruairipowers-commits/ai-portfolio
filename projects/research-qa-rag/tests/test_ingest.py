"""DATA-03/04/05 and SEC-02 at ingest: redaction, dedup, quarantine, licence, incremental versioned re-index."""


def test_corpus_indexed_with_provenance(m, built):
    con = m.store.connect(built)
    docs = {r["doc_id"]: dict(r) for r in con.execute("select * from documents")}
    assert len(docs) == 12
    chunk = con.execute("select * from chunks where doc_id = 'halv-2025-annual' and page = 3").fetchone()
    assert chunk["section"].startswith("Item 7") and chunk["entitlement"] == "public" and chunk["embedding"]


def test_hidden_instructions_quarantined_never_indexed(m, built):
    con = m.store.connect(built)
    q = con.execute("select * from quarantine where doc_id = 'aldgate-bwu-2026q2'").fetchall()
    assert len(q) == 1 and "Ignore all prior instructions" in q[0]["text"]
    assert not con.execute("select count(*) from chunks where text like '%strong buy%'").fetchone()[0]


def test_pii_redacted_and_boilerplate_deduplicated(m, built):
    con = m.store.connect(built)
    text = " ".join(r[0] for r in con.execute("select text from chunks where doc_id like 'northbridge%'"))
    assert "@northbridge.example" not in text and "[REDACTED_EMAIL]" in text and "[REDACTED_PHONE]" in text
    # the second Northbridge note's analyst line and disclaimer duplicate the first's -> stored once
    run = con.execute("select dedup_dropped from index_runs where active = 1").fetchone()[0]
    assert run == 2


def test_licence_barred_document_is_keyword_only(m, built):
    con = m.store.connect(built)
    rows = con.execute("select ai_processing, embedding from chunks where doc_id = 'kestrel-crvn-2026q2'").fetchall()
    assert rows and all(r["ai_processing"] == 0 and r["embedding"] is None for r in rows)


def test_incremental_reindex_and_versioning(m, built):
    first = m.ingest.ingest(built)
    assert first["docs_changed"] == 0 and first["docs_unchanged"] == 12
    doc_id = m.ingest.add_document(built, title="Test note", company="Marisol Foods", ticker="MRSL", entitlement="public",
                          licence="test", ai_processing=True, text="We rate Marisol Foods Buy with a price target of $60.",
                          source="Test")
    second = m.ingest.ingest(built)
    assert second["docs_changed"] == 1 and second["docs_unchanged"] == 12
    assert second["index_version"] != first["index_version"]
    con = m.store.connect(built)
    assert con.execute("select count(*) from index_runs").fetchone()[0] == 3
    assert con.execute("select count(*) from chunks where doc_id = ?", (doc_id,)).fetchone()[0] == 1


def test_chunker_respects_size_and_overlap(m):
    paras = [" ".join(f"w{i}_{j}" for j in range(40)) for i in range(4)]
    chunks = m.ingest.chunk_paragraphs(paras, chunk_words=90, overlap_words=10, min_words=5)
    assert len(chunks) == 2
    assert all(len(c.split()) <= 100 for c in chunks)
    assert chunks[1].split()[:10] == chunks[0].split()[-10:]
