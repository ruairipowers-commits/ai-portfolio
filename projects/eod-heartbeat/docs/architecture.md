# Architecture — eod-heartbeat

## Flow

<!-- --8<-- [start:flow] -->
```mermaid
flowchart LR
    subgraph Feeds["EOD feeds (landing)"]
        F1[prices · FX · trades<br/>prime-broker positions<br/>corp actions · risk P&L]
        F2[arrival times]
    end
    subgraph DAG["Airflow DAG every 5 min 17:00-21:00 ET"]
        L[load raw.*] --> D[dbt build<br/>models + 28 tests<br/>DATA-02 gate]
        D --> B[(marts.breaks<br/>file SLAs · recon · P&L<br/>stale · outliers)]
        B --> R[retrieve<br/>runbook sections + incidents<br/>pgvector, by break type]
        R --> M[explainer via alias<br/>fallback MODEL-05<br/>budget COST-01]
        M --> P{policy<br/>cites a runbook?<br/>step from runbook?<br/>unsafe action?<br/>critical?}
        P -->|ok| E[explained]
        P -->|flag| H[needs a human]
        E & H --> A[alert outbox<br/>one per break]
    end
    subgraph KB["Knowledge base (DATA-05)"]
        K1[15 runbooks · 30 incidents] --> K2[redact client names / PII<br/>quarantine instructions SEC-02]
        K2 --> K3[(kb.chunks<br/>pgvector + kb_version)]
    end
    F1 & F2 --> L
    K3 --> R
    A --> O[on-call: Slack / SNS<br/>👍 / 👎 feedback HITL-03]
    M -. every explanation .-> AU[(audit.explanations<br/>model · prompt hash · kb version)]
```
<!-- --8<-- [end:flow] -->

## Sequence: one heartbeat

```mermaid
sequenceDiagram
    participant AF as Airflow (5-min tick)
    participant PG as Postgres
    participant DBT as dbt-postgres
    participant KB as kb.chunks (pgvector)
    participant M as Explainer (alias)
    participant OC as On-call
    AF->>PG: load landed feeds into raw.*
    AF->>DBT: build with as_of = tick time
    DBT-->>AF: 28 tests pass? (fail → stop, no explanations)
    AF->>PG: breaks for the business date
    loop each break not yet alerted
        AF->>KB: nearest runbook sections + incidents for this break type
        AF->>M: break facts (computed by SQL) + sources
        M-->>AF: {likely_cause, next_step, runbook_refs, incident_refs}
        AF->>AF: policy: cited? step in runbook? unsafe? critical?
        AF->>PG: audit.explanations + audit.alerts (outbox)
    end
    AF->>OC: send pending alerts (if configured)
    OC->>PG: useful / wrong
```

## Why this shape

<!-- --8<-- [start:decisions] -->
| Decision | Chosen | Why | Alternatives considered |
|---|---|---|---|
| Detection | Deterministic SQL in dbt (one `breaks` model) | Whether a break exists must be reproducible, testable and reviewable in a PR. The model never decides that. | Anomaly-detection model; LLM reading raw files |
| Pattern | RAG explainer per break, single call | The knowledge is in runbooks and incident history. One grounded call per break is cheap and auditable. | Agent that runs diagnostic queries (more power, much more risk on a NAV night) |
| Orchestration | Airflow DAG, 5-minute ticks 17:00–21:00 ET | The most common orchestrator in fund data teams; frequent idempotent ticks meet "alert within 5 minutes" without sensors. Alerts are de-duplicated per break. | Dagster, Prefect, Step Functions, cron |
| Store | Postgres for data, marts, audit **and** vectors (pgvector) | One system to run, back up and secure; the KB is small. | Separate vector DB (OpenSearch, Qdrant) |
| Local Postgres | Embedded via pgserver (Postgres 16 + pgvector) | Clone-and-run with no Docker; same SQL as RDS. docker compose for the full stack with Airflow. | Docker only; SQLite (no pgvector, different SQL) |
| Retrieval filter | Break type → runbook `break_types`, then the causes + steps sections of the top two runbooks are always included | Retrieval can't drift to an unrelated runbook, and the step the model cites is the real step. | Pure vector search |
| Guardrails | Policy after the model: must cite a retrieved runbook, the step must come from it, unsafe-action patterns are blocked, critical breaks always go to a human | A runbook can be wrong or tampered with; advice on NAV night must be checkable. | Prompt rules alone |
| Resilience | Fallback model, then degraded mode (alert with runbook steps, no explanation) | The alert matters more than the prose. A provider outage must not hide a break. | Fail the run |
<!-- --8<-- [end:decisions] -->

## Data model

```mermaid
erDiagram
    raw_file_arrivals ||--o{ file_sla : "vs feeds.sla_time"
    raw_trades ||--o{ stg_internal_positions : "cumulative + adjustments"
    stg_internal_positions ||--o{ recon_positions : "vs raw.pb_positions"
    stg_internal_positions ||--o{ pnl_explain : "prior qty x price change x FX"
    file_sla ||--o{ breaks : late_or_missing
    recon_positions ||--o{ breaks : position_break
    pnl_explain ||--o{ breaks : pnl_break
    breaks ||--o{ explanations : "explained in"
    kb_chunks ||--o{ explanations : "cited by"
    explanations ||--o| alerts : "one per break"
    explanations ||--o{ feedback : "rated by on-call"
    breaks {
        text break_id PK
        date business_date
        text break_type
        text severity
        text entity
        text hints
    }
    explanations {
        text explanation_id PK
        text break_id FK
        text status
        text model_name
        text prompt_sha
        text kb_version
        jsonb runbook_refs
    }
    kb_chunks {
        text chunk_id PK "RB-04#steps"
        text doc_sha
        vector embedding
    }
```
