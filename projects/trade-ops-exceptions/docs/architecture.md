# Architecture — trade-ops-exceptions

## Flow

<!-- --8<-- [start:flow] -->
```mermaid
flowchart LR
    Q[(Open exceptions<br/>queue)] --> A
    subgraph Agent["LangGraph agent (Python)"]
        A[agent<br/>LLM via alias<br/>COST-01 budget] -->|tool calls| T[tools node<br/>allow-list · cap 8<br/>result screening SEC-02]
        T --> A
        A -->|submit_proposal| P[policy<br/>schema · evidence check<br/>deterministic rules]
        P -->|clean| H{{human_review<br/>interrupt HITL-02}}
        P -->|flags| X[escalated<br/>to ops lead]
        H -->|approve / edit| E[execute<br/>mint approval token]
        H -->|reject| R[rejected]
    end
    subgraph MCPR["MCP server — scope=read (TypeScript)"]
        RT[7 read-only tools<br/>read-only DB handle]
    end
    subgraph MCPW["MCP server — scope=write (started only on approval)"]
        WT[record_resolution<br/>verifies HMAC token]
    end
    T <--> RT
    E --> WT
    WT --> DB[(resolutions + outbox<br/>never auto-sent)]
    A -. every step .-> L[(agent_steps<br/>agent_runs · approvals)]
```
<!-- --8<-- [end:flow] -->

## Sequence: one exception, investigation to approval

```mermaid
sequenceDiagram
    participant Q as Queue
    participant G as LangGraph
    participant M as LLM (alias)
    participant R as MCP read server
    participant U as Analyst (UI/CLI)
    participant W as MCP write server
    Q->>G: EX-0002
    loop until submit_proposal or cap (8 tool calls)
        G->>M: system prompt + history + read tools
        M-->>G: tool call (e.g. get_broker_confirm)
        G->>R: call tool (allow-listed)
        R-->>G: JSON result → screened for injection / SSI-change text
    end
    M-->>G: submit_proposal {category, fix, evidence, email}
    G->>G: policy: schema, evidence vs results, rules
    G-->>U: interrupt — proposal awaits approval (checkpointed)
    U->>G: resume {approve, approver, edits}
    G->>W: record_resolution + HMAC token over the exact approved content
    W-->>G: recorded (email queued in outbox, not sent)
```

## Why this shape

<!-- --8<-- [start:decisions] -->
| Decision | Chosen | Why | Alternatives considered |
|---|---|---|---|
| Pattern | Agent (tool loop) | Which system to check next depends on what the last lookup showed; a fixed pipeline either over-fetches or misses cases. | Fixed workflow (see altdata-triage), multi-agent |
| Framework | LangGraph | Explicit state machine, first-class `interrupt()` + checkpoints for human approval, most widely used. | OpenAI Agents SDK, Claude Agent SDK, hand-rolled loop |
| Tools | MCP server (TypeScript) | Tools become reusable by any MCP client (Claude Desktop, IDEs, other agents); scopes are enforced by the server process, not by the prompt. | Native Python function tools |
| Write safety | Two layers: write tool absent from model's tools **and** server requires an HMAC token minted only after approval | A prompt-injected or buggy agent can't write even if it names the tool; a stolen tool call can't be replayed with different content. | Prompt instructions alone; approval flag in DB |
| Email | Outbox table, never sent | External comms are the highest-risk action; sending stays a separate, human step. | SES/Graph send after approval |
| Local DB | SQLite (Postgres optional) | Clone-and-run with no Docker; same SQL on Postgres. | Postgres only |
| Offline model | Scripted investigator | Deterministic CI and free demos; exercises the real graph, MCP server and policy. | Recorded real-model cassettes |
<!-- --8<-- [end:decisions] -->
