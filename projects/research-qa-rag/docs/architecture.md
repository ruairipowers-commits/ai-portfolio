# Architecture — research-qa-rag

## Flow

<!-- --8<-- [start:flow] -->
```mermaid
flowchart LR
    subgraph Ingest["Ingest (incremental, versioned · DATA-05)"]
        D[PDF filings + broker notes<br/>HTML transcripts<br/>manifest: entitlement, licence] --> P[parse pages<br/>PyMuPDF / HTML]
        P --> R[redact PII<br/>DATA-03]
        R --> U[dedup boilerplate]
        U --> S{screen for<br/>instructions<br/>SEC-02}
        S -->|hit| Q[(quarantine)]
        S -->|clean| C[chunk per page]
        C --> E[embed<br/>only if licence allows<br/>DATA-04]
    end
    E --> IX[(SQLite index<br/>FTS5 BM25 + sqlite-vec<br/>index_runs)]
    C -->|keyword only| IX
    subgraph Ask["Ask (FastAPI · Streamlit · CLI)"]
        A[question + analyst] --> F[entitlement + licence<br/>filter in SQL · FR-4]
        F --> B[BM25] & V[vector]
        B --> RRF[reciprocal rank fusion<br/>+ runtime screen]
        V --> RRF
        RRF --> M[LLM via alias<br/>budget COST-01]
        M --> VER{verify<br/>quotes verbatim<br/>support ≥ 90%<br/>OBS-02}
        VER -->|pass| OK[cited answer]
        VER -->|fail| NO[refusal + reason]
    end
    IX --> F
    OK & NO -. answers log .-> L[(answers · feedback<br/>governance hub)]
```
<!-- --8<-- [end:flow] -->

## Sequence: one question

```mermaid
sequenceDiagram
    participant U as Analyst
    participant API as FastAPI / app
    participant IX as SQLite index
    participant M as Model (alias)
    participant V as Verifier
    U->>API: question (identity → entitlements)
    API->>API: kill switch? embedding model == index's?
    API->>IX: BM25 + vector, WHERE entitlement IN (…) AND ai_processing AND NOT quarantined
    IX-->>API: candidates (+ counts removed by each filter)
    API->>API: RRF fuse → top-k → drop any instruction-like chunk
    API->>M: system prompt + <excerpt id=…> blocks
    M-->>API: JSON {answer, citations[{chunk_id, quote}], refused}
    API->>V: parse (Pydantic) → quotes verbatim? numbers + words supported?
    V-->>API: answered | refused (unverified / unsupported / invalid)
    API-->>U: answer with document + page, or refusal
    API->>API: log answer (index version, model, prompt hash, cost) + governance event
```

## Why this shape

<!-- --8<-- [start:decisions] -->
| Decision | Chosen | Why | Alternatives considered |
|---|---|---|---|
| Pattern | RAG, single model call | The question needs documents, not tools or multi-step planning. One call is cheaper, faster and easier to audit. | Agentic retrieval (query rewriting, multi-hop), fine-tuning |
| Retrieval | Hybrid: BM25 + vectors fused with RRF | Financial questions are full of exact terms (tickers, "net revenue retention", "$3.9 billion") that keyword search nails and embeddings blur; vectors catch paraphrase. RRF needs no score calibration. Measured: hybrid has the best MRR on the golden set. | Vector only; learned reranker (Cohere / bge-reranker); Bedrock KB hybrid |
| Store | One SQLite file: FTS5 + sqlite-vec | Zero infrastructure, exact search, filters in plain SQL, and a per-visitor copy in the hosted demo. Exact (brute-force) vector search is fine for tens of thousands of chunks; beyond that, use an ANN index. | Postgres + pgvector (see eod-heartbeat), OpenSearch, Qdrant, Bedrock Knowledge Bases |
| Access control | Entitlement filter inside both retrievers' WHERE clauses | A chunk the user can't see is never scored, fused or sent — not filtered afterwards. Refusals don't reveal restricted documents. | Post-filtering results; one index per entitlement group |
| Licences | `ai_processing` per document; barred documents are keyword-indexed but never embedded or sent to a model | The analyst may read the note; the licence forbids third-party AI. Embedding APIs are third-party AI too. | Excluding the document entirely; legal review per question |
| Injection | Screen paragraphs at ingest (quarantine) and retrieved chunks at query time | Hidden text in PDFs is the classic indirect injection. Removing it before the model sees it beats asking the model to ignore it. | LLM classifier (Llama Guard, Bedrock Guardrails prompt-attack filter) |
| Grounding | Verbatim quote check + support ratio on every answer | A citation that doesn't match the source is worse than no answer. Deterministic, free, runs on every call. | LLM-as-judge faithfulness (RAGAS) on a sample |
| Service | FastAPI + the same `ask()` in Streamlit and CLI | One code path; OpenAPI docs for integration. | Lambda handlers; LangServe |
| Offline models | Extractive mock + feature-hash embeddings | Deterministic CI and a free hosted demo that exercises every control. | Recorded real-model responses |
<!-- --8<-- [end:decisions] -->

## Data model

```mermaid
erDiagram
    documents ||--o{ chunks : "split into"
    documents ||--o{ quarantine : "paragraphs removed"
    index_runs ||--o{ answers : "answered from"
    answers ||--o{ feedback : "rated by analyst"
    documents {
        text doc_id PK
        text entitlement "who may see it"
        text licence
        int ai_processing "may an AI process it"
        text sha256 "change detection"
    }
    chunks {
        text chunk_id PK "doc:page:n"
        text doc_id FK
        int page
        text section
        text config_hash "chunking + embedding config"
        blob embedding "null when licence forbids AI"
    }
    index_runs {
        text index_version
        text embedding_model
        int docs_changed
        int quarantined
    }
    answers {
        text answer_id PK
        text index_version
        text model_name
        text prompt_sha
        int excluded_entitlement
        real cost_usd
    }
```
