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
| [Alt-data vendor triage](blog/posts/altdata-triage.md) | Analysts spend days profiling vendor samples | Workflow | dbt, DuckDB, Pydantic, Bedrock | ✅ Live |
| EOD heartbeat | End-of-day pipeline breaks found late, fixed from tribal knowledge | RAG + monitor | Airflow, Postgres/pgvector, dbt | In progress |
| Trade-ops exception agent | Settlement breaks need lookups across 4 systems | Agent + human approval | LangGraph, MCP (TypeScript), Streamlit | Planned |
| Research Q&A | Analysts re-read filings to answer questions | RAG | FastAPI, hybrid pgvector search, RAGAS-style evals | Planned |

## What every project includes

- A write-up: business problem, functional and non-functional requirements, architecture diagrams and the *why*
- A public repo that runs offline with a mock model — no API keys — and switches to Claude, OpenAI or Bedrock by config
- A control-by-control governance mapping, with configuration and the options I didn't build
- An AWS-native path: Terraform starter and a local-vs-AWS comparison
- Tests, a golden-set eval gate, and CI

## Start here

**[How I govern AI workflows →](blog/posts/governance.md)** — the 30 controls behind every project:
data preparation, AI security, cost oversight, model migration, evals, audit and human oversight.
