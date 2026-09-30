# Architecture — altdata-triage

## Flow

<!-- --8<-- [start:flow] -->
```mermaid
flowchart LR
    subgraph Vendor["Vendor delivery"]
        CSV[sample.csv<br/>weekly panel]
        Q[questionnaire.md<br/>flags + free text]
    end
    subgraph Warehouse["DuckDB + dbt"]
        RAW[(raw.*)]
        STG[staging<br/>typed + cleaned]
        INT[int_panel_mapped<br/>join security master]
        SC[(marts.vendor_scorecard<br/>metrics + rule score)]
        T{{14 dbt tests}}
    end
    subgraph AI["Governed AI step (Python)"]
        G1[DQ gate<br/>DATA-02]
        S[Sanitize notes<br/>injection scan + PII redact]
        L[LLM via alias<br/>budget + fallback]
        V[Schema validate<br/>+ citation check]
        P[Deterministic policy]
    end
    H[Human reviewer<br/>review command]
    A[(audit.*<br/>calls, results, reviews)]

    CSV --> RAW
    Q --> RAW
    RAW --> STG --> INT --> SC
    SC --- T
    T --> G1 --> S --> L --> V --> P --> H
    L -. log .-> A
    P -. log .-> A
    H -. log .-> A
```
<!-- --8<-- [end:flow] -->

## Sequence for one vendor

```mermaid
sequenceDiagram
    participant CLI as triage
    participant DB as DuckDB
    participant GR as guardrails
    participant LLM as LLM (alias)
    CLI->>DB: dbt run_results all passed?
    CLI->>DB: read scorecard row (16 fields)
    CLI->>DB: read vendor notes (untrusted)
    CLI->>GR: sanitize(notes)
    GR-->>CLI: clean text + flags (injection, PII count)
    CLI->>LLM: system prompt v1 + <vendor_facts> + <untrusted_vendor_notes>
    Note over CLI,LLM: pre-flight budget check, retries, fallback alias
    LLM-->>CLI: JSON memo
    CLI->>GR: parse (Pydantic) → cite-check → policy
    GR-->>CLI: final recommendation + overrides
    CLI->>DB: audit.ai_calls, audit.triage_results
```

## Why this shape

<!-- --8<-- [start:decisions] -->
| Decision | Chosen | Why | Alternatives considered |
|---|---|---|---|
| Numbers | dbt SQL, not the LLM | Metrics must be reproducible, testable and reviewable in a PR. LLMs are unreliable calculators. | Pandas notebooks; LLM code-interpreter |
| Orchestration | Fixed workflow | Triage steps are known in advance; a free-roaming agent adds cost and audit surface with no benefit. | LangGraph agent; Step Functions |
| Warehouse | DuckDB local | Zero-infra clone-and-run; identical dbt models run on Athena/Snowflake by switching target. | Postgres, Snowflake, Athena |
| LLM access | Thin provider adapter + registry | Provider-agnostic, auditable in ~200 lines; aliases make migrations a config change. | LiteLLM, LangChain model wrappers |
| Safety | Deterministic policy after the model | Compliance rules must hold even if the model is wrong or manipulated. | Relying on prompt instructions alone |
| Output | Pydantic schema + fallback | Downstream code never parses free text. | Provider JSON mode only |
<!-- --8<-- [end:decisions] -->
