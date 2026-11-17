# Architecture — lob-matching-engine

## Flow

<!-- --8<-- [start:flow] -->
```mermaid
flowchart LR
    subgraph In["Order flow"]
        S[Session<br/>synthetic or uploaded order log]
        M[Order memos<br/>free text, untrusted]
    end
    subgraph Engine["Rust engine (pyo3)"]
        G{{Data gate<br/>DATA-02}}
        B[(Price ladder +<br/>FIFO slab)]
        E[(Event log<br/>accepted · trade · cancel · STP)]
    end
    subgraph Rules["Code decides"]
        D[Detectors<br/>layering · wash · stuffing · ignition]
        Q[Market quality<br/>spread · depth · λ]
    end
    subgraph AI["Governed narrative (Python)"]
        P[Payload builder<br/>pseudonyms + redaction<br/>DATA-03 · SEC-02]
        L[Model via alias<br/>budget + fallback<br/>MODEL-01 · COST-01]
        V[Schema + citation check<br/>SEC-04 · OBS-02]
        R[Policy<br/>no CLOSE on high severity]
    end
    H[Analyst decision<br/>HITL-02]
    A[(SQLite audit<br/>OBS-01)]
    S --> G --> B --> E --> D --> P
    M --> P
    E --> Q
    P --> L --> V --> R --> H
    L -.-> A
    R -.-> A
    H -.-> A
```
<!-- --8<-- [end:flow] -->

## One alert, end to end

<!-- --8<-- [start:sequence] -->
```mermaid
sequenceDiagram
    participant U as Analyst (app)
    participant W as Workflow
    participant E as Rust engine
    participant D as Detectors
    participant M as Model (alias)
    participant A as Audit (SQLite)
    U->>W: Run surveillance
    W->>W: data gate (columns, band, time, refs)
    W->>E: replay commands
    E-->>W: event log (ids, trades, STP cancels)
    W->>D: orders + events
    D-->>W: alerts (pattern, severity, event ids, facts)
    loop each alert
        W->>W: pseudonymise trader, redact + delimit memos
        W->>M: facts + untrusted memos (schema in prompt)
        M-->>W: JSON narrative
        W->>W: validate schema, check citations, apply policy
        W->>A: call log + narrative + overrides
    end
    U->>W: close / escalate (+ reason)
    W->>A: disposition (agrees with AI?)
```
<!-- --8<-- [end:sequence] -->

## Design decisions

<!-- --8<-- [start:decisions] -->
| Decision | Chosen | Why | Alternatives |
|---|---|---|---|
| Engine language | Rust, exposed to Python with pyo3/maturin | Predictable latency (no GC), memory safety, one wheel for every Python ≥ 3.9 (abi3) | C++ (pybind11), Java/LMAX-style, pure Python (≈100× slower) |
| Book layout | Dense price ladder + intrusive FIFO lists in a slab | O(1) add / cancel / fill and no allocation in steady state; best price is a cached index | `BTreeMap` of levels (simpler, O(log n), worse tails); skip lists |
| What decides an alert | Rules in code over the engine's event log | Deterministic, testable, explainable to a regulator; the model can't invent or suppress alerts | Model classifies raw events (unauditable); ML anomaly score (needs labels) |
| Model's job | Draft a cited narrative inside a schema | Saves the reconstruction time; every figure and event id is checked against the log | No model (slower reviews); agent with query tools (more risk for little gain) |
| Pattern | Workflow, not an agent | Fixed steps, no tools, nothing for a prompt injection to call | LangGraph agent with read-only SQL tools |
| Who decides | A named analyst; high-severity closes need a reason | Surveillance outcomes are compliance decisions | Auto-close low severity (left as a config option, off) |
| Store | SQLite | Zero infrastructure, one file per visitor in the demo, queryable audit | DuckDB, Postgres; DynamoDB + S3 Object Lock on AWS |
| Benchmark method | Untimed replay for throughput; per-command timer for latency | The timer would deflate throughput; tails need per-command samples | Sampling profiler; hardware timestamps (needs NIC support) |
<!-- --8<-- [end:decisions] -->

## Code map

```
rust/src/book.rs      order book, matching, stops, STP, invariants
rust/src/flow.rs      synthetic flow, benchmark harness, simulator
rust/src/python.rs    pyo3 bindings → lob_matching_engine._engine
src/lob_matching_engine/
  sessions.py         session generator, data gate, replay, market quality
  detectors.py        layering, wash (STP-blocked), stuffing, ignition
  workflow.py         payload → model → validate → cite-check → policy → audit; dispose()
  guardrails.py       injection scan, PII redaction, pseudonyms, schema parse, citation check, policy
  llm.py / mock_model.py   registry, budgets, fallback; deterministic gullible mock
  evals.py            golden set + gate;  store.py  SQLite audit;  telemetry.py  governance console client
  ui.py               Streamlit: Surveillance workflow + Engine lab pages (lab/)
```
