# Architecture — governance-console

## Flow

<!-- --8<-- [start:flow] -->
```mermaid
flowchart LR
    subgraph WF["AI workflows (each ships the same telemetry.py)"]
        A[altdata-triage]
        B[eod-heartbeat]
        C[trade-ops-exceptions]
        D[research-qa-rag]
        X[new project<br/>added to portfolio.yaml]
    end
    subgraph Console["Governance console (FastAPI)"]
        I[POST /api/events<br/>ingest token · schema · rate limit<br/>SEC-03]
        S[GET /api/workflows/slug/status<br/>kill switch]
        DB[(events · workflow_state<br/>control_changes · attestations<br/>SQLite or Postgres · OBS-01/03)]
        M[metrics: spend · runs · users<br/>throughput · flags · budgets<br/>anomalies · COST-02/04]
        UI[Dashboards: overview · workflow<br/>controls matrix · models · events · audit]
        K[Catalog: portfolio.yaml + specs +<br/>docs/governance.md · HITL-01]
    end
    A & B & C & D & X -->|one event per visit / action<br/>background thread, spool fallback| I
    A & B & C & D & X -->|before every run, cached 15 s| S
    I --> DB
    S --> DB
    K --> M
    DB --> M --> UI
    ADM[Admin · reviewer] -->|switch off / on · reason required| S
    ADM -->|attest a control| DB
```
<!-- --8<-- [end:flow] -->

## Sequence: a workflow is switched off

```mermaid
sequenceDiagram
    participant U as Admin (console)
    participant C as Console
    participant W as Workflow app
    participant P as Person using the app
    U->>C: POST /workflows/trade-ops-exceptions/toggle {enabled: 0, reason}
    C->>C: workflow_state + control_changes (who, when, why)
    P->>W: Investigate EX-0042
    W->>C: GET /api/workflows/trade-ops-exceptions/status (≤ 15 s cache)
    C-->>W: {enabled: false, reason, changed_by}
    W->>C: POST /api/events {investigate, status: blocked, flags: [kill_switch]}
    W-->>P: ⛔ Switched off by governance: reason (by cro) — no model call made
```

## Sequence: a violation is escalated

```mermaid
sequenceDiagram
    participant App as Workflow (e.g. eod-heartbeat)
    participant C as Console
    participant M as Email (SMTP)
    actor O as Owner
    App->>C: POST /api/events (flags: unsafe_action)
    C->>C: rule unsafe-action (high) → open INC-0004
    C->>C: high ≥ auto-shutdown level → kill switch off
    C->>M: email: details + link to /incidents/INC-0004
    App->>C: next run: GET status → disabled (Automatic: INC-0004)
    App-->>App: refuses the run, logs "blocked"
    M->>O: [HIGH] INC-0004 EOD heartbeat: AI proposed an action outside the approved runbook
    O->>C: opens the link: evidence, guidance, timeline
    O->>C: notes, then resolve: root cause + fix + documentation, re-confirm SEC-04, re-enable
    App->>C: next run: GET status → enabled
```

Rules live in `config/escalation.yaml` (flag rules fire on ingest; budget, anomaly and shadow-AI rules every five
minutes). Per-workflow recipients and levels are on the Settings page. Ticketing is designed in
[integrations.md](integrations.md).

## Telemetry contract

One JSON event per visit or action. No prompts, questions, documents or answers — counts, hashes and flags only.

| Field | Meaning |
|---|---|
| `event_id` | idempotency key (re-sending an event never double-counts) |
| `ts`, `workflow`, `event_type`, `status` | when, which workflow, what happened (`triage`, `investigate`, `ask`, `eod-check`, `approve`, `visit`, `register` …), outcome (`ok`, `escalated`, `refused`, `blocked`, `error` …) |
| `actor`, `actor_type`, `session_id` | a named person, an anonymous demo visitor, or a service (scheduler, agent) |
| `model`, `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms` | what the run consumed — the workflow's own budget code computes cost |
| `records_in`, `records_out` | throughput: rows / documents / tool results read, outputs produced |
| `flags` | safety and control signals: `injection_detected`, `escalated`, `budget_blocked`, `entitlement_filtered`, `kill_switch`, `human_override` … |
| `environment`, `app_version` | `demo`, `local`, `ci`, `prod`; client version |

## Why this shape

<!-- --8<-- [start:decisions] -->
| Decision | Chosen | Why | Alternatives considered |
|---|---|---|---|
| Transport | HTTP push to an ingest API, with a local spool file as fallback | Apps hold an append-only token, never database credentials, so a compromised app can't rewrite history or flip a switch. Works across separately hosted demos with no shared database. | Apps write to a shared Postgres (simpler, but every app can write every table); OpenTelemetry collector → vendor backend |
| Telemetry client | One small file copied into every workflow, kept identical by a CI check | No shared package to version and publish; each project repo stays standalone. | Shared PyPI package; OpenTelemetry GenAI semantic conventions (a good next step) |
| Kill switch | Polled by the app before every run, enforced in the code path, fail-open by default | The switch has to stop the model call, not just grey out a button. Fail-open keeps a console outage from stopping the business; `GOVERNANCE_FAIL_CLOSED=1` for high-risk workflows. | Feature-flag service (AWS AppConfig, LaunchDarkly); push via webhook |
| Catalog | Read from the portfolio repo (portfolio.yaml, specs, each `docs/governance.md`) | A new project is governed the moment it's added — owner, risk tier and control mapping come from files the project already has. Unknown event sources are flagged as shadow AI. | Hand-maintained registry; ServiceNow / Collibra AI inventory |
| UI | Server-rendered HTML + Chart.js (vendored) | Fast, dependency-light, no build step; a contrast with the Streamlit apps it governs. | Grafana / Datadog dashboards over the same events; Streamlit; React |
| Store | SQLite, Postgres via `DATABASE_URL` | Zero-infra locally; durable and shared when hosted. Same SQL on both. | ClickHouse / DuckDB for high event volumes; S3 + Athena (see AWS) |
| Demo history | 90 days of labelled simulated events, hideable with one toggle | The dashboards mean something on day one; live events are always distinguishable. | Empty dashboards until people use the demos |
<!-- --8<-- [end:decisions] -->
