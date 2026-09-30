# Stack catalog

Pick the **most common** tool for each layer unless the project's `showcases` calls for
something else. Across the portfolio, aim for each row's default to appear at least once
and for no two projects to have identical stacks.

| Layer | Default (most common) | Common alternatives | Notes |
|---|---|---|---|
| Language | Python 3.11+ | TypeScript (MCP servers, UIs) | Python for data/AI; TS where the ecosystem expects it |
| Transform / modelling | dbt (duckdb locally) | SQLMesh, plain SQL, pandas/Polars | dbt tests double as the AI data-quality gate |
| Local warehouse | DuckDB | Postgres | DuckDB = zero infra; Postgres when pgvector or concurrency needed |
| Cloud warehouse (docs) | Snowflake / Athena | BigQuery, Databricks, Fabric | Same dbt models, different target |
| Orchestration | Airflow | Dagster, Prefect, Step Functions, cron + CLI | Use CLI for single-step workflows; Airflow when schedules/SLAs matter |
| Agent framework | LangGraph | OpenAI Agents SDK, Claude Agent SDK, CrewAI, plain loop | Only for true agents; workflows stay plain Python |
| LLM access | Registry adapter (this repo) | LiteLLM, LangChain chat models | Always aliases, never raw model IDs in code |
| Structured output | Pydantic | JSON Schema, Instructor | Validate every response |
| Tools | MCP server | Native function calling | MCP makes tools reusable across agents/clients |
| Vector store | pgvector | OpenSearch, Pinecone, Qdrant, Bedrock KB | pgvector = one fewer system |
| Embeddings | provider embeddings via registry | sentence-transformers local | Log embedding model version (DATA-05) |
| Evals | pytest + golden YAML | promptfoo, DeepEval, RAGAS, Langfuse evals | Mock provider in CI, live on schedule |
| Observability | audit tables (SQL) | Langfuse, OpenTelemetry GenAI, Datadog LLM | SQL tables keep it runnable offline |
| API | FastAPI | Flask, Lambda handlers | |
| UI | Streamlit | Next.js, Retool, Slack app | Approval queues and chat |
| IaC | Terraform | CDK, Bicep, Pulumi | AWS starter in every project |
| CI | GitHub Actions | GitLab CI | tests + offline e2e + eval gate |
| Containers | Docker / compose | Podman | |

## AWS-native equivalents

| Local | AWS |
|---|---|
| folder landing | S3 (encrypted, versioned, private) |
| DuckDB + dbt | Glue Catalog + Athena (dbt-athena) or Redshift |
| Postgres + pgvector | RDS Postgres + pgvector / OpenSearch Serverless / Bedrock Knowledge Bases |
| Airflow | MWAA or Step Functions |
| LLM provider | Bedrock (IAM-scoped, no keys) |
| CLI container | ECS Fargate / Lambda |
| audit tables | CloudWatch Logs + S3 (Object Lock for WORM) |
| budgets in config | AWS Budgets + cost-allocation tags |
| .env | Secrets Manager / IAM roles |

## Diversity matrix (update as projects are added)

| Project | Pattern | Data | Orchestration | Retrieval | Tools/UI | AWS focus |
|---|---|---|---|---|---|---|
| altdata-triage | workflow | dbt + DuckDB | CLI | — | markdown memos | Athena, Bedrock, ECS |
| eod-heartbeat | RAG + monitor | dbt + Postgres | Airflow | pgvector | alerts | MWAA, RDS |
| trade-ops-exceptions | agent | Postgres | LangGraph | — | MCP (TS) + Streamlit | Step Functions, AgentCore |
| research-qa-rag | RAG | doc parsing | FastAPI | hybrid pgvector | Streamlit chat | Bedrock KB, OpenSearch |
