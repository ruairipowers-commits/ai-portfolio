---
hide: [navigation]
---

# AI workflows for investment firms — built, governed, runnable

I'm Ruairi Powers. I've spent 25 years building data, trading and research platforms at
Bridgewater, Two Sigma and Neudata. This portfolio shows how I design AI workflows for a fund:
each project starts from a business problem, runs on a laptop in five minutes, and is held to the
same [governance standard](blog/posts/governance.md).

## Projects

| Project | Problem | Pattern | Stack highlights | Status |
|---|---|---|---|---|
| [Alt-data vendor triage](blog/posts/altdata-triage.md) | Analysts spend days profiling vendor samples | Workflow | dbt, DuckDB, Streamlit, Bedrock | ✅ [Live demo]({{DEMOS_URL}}/altdata-triage/) |
| [EOD heartbeat](blog/posts/eod-heartbeat.md) | End-of-day pipeline breaks found late, fixed from tribal knowledge | RAG + monitor | Airflow, dbt-postgres, pgvector, Streamlit | ✅ [Live demo]({{DEMOS_URL}}/eod-heartbeat/) |
| [Trade-ops exception agent](blog/posts/trade-ops-exceptions.md) | Settlement breaks need lookups across 4 systems | Agent + human approval | LangGraph, MCP (TypeScript), Streamlit, Postgres | ✅ [Live demo]({{DEMOS_URL}}/trade-ops-exceptions/) |
| [Research Q&A](blog/posts/research-qa-rag.md) | Analysts re-read filings to answer questions | RAG | FastAPI, hybrid search (FTS5 + sqlite-vec), entitlements | ✅ [Live demo]({{DEMOS_URL}}/research-qa-rag/) |

### Governing them

| Project | Problem | Pattern | Stack highlights | Status |
|---|---|---|---|---|
| [AI governance console](blog/posts/governance-console.md) | Nobody can say what AI runs, who uses it, what it costs, or how to stop it | Platform | FastAPI, Chart.js, Postgres, kill switch | ✅ [Live demo]({{DEMOS_URL}}/governance-console/) |

Every workflow above reports each visit and action to the console — usage, cost, data throughput, safety signals —
and obeys its kill switch. Use any demo, then find yourself in the console with *Include simulated history* unticked.

## What every project includes

- A write-up: business problem, functional and non-functional requirements, architecture diagrams and the *why*
- A browser app (Streamlit): a default input, a Run button and the results — plus a "try to break it" input —
  hosted as a live demo where every visitor gets a private copy of the data
- A public repo that runs offline with a mock model — no API keys — and switches to Claude, OpenAI or Bedrock by config
- A control-by-control governance mapping, with configuration and the options I didn't build
- An AWS-native path: Terraform starter and a local-vs-AWS comparison
- Tests, a golden-set eval gate, and CI
- Telemetry to the [governance console](blog/posts/governance-console.md) and a kill switch it controls

## Start here

**[How I govern AI workflows →](blog/posts/governance.md)** — the 30 controls behind every project:
data preparation, AI security, cost oversight, model migration, evals, audit and human oversight.
