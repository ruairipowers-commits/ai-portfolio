# Governance mapping — trade-ops-exceptions

Maps every control in the portfolio's [AI governance standard]({{SITE_URL}}/blog/governance/) (copy in [`governance/controls.md`](../governance/controls.md) when published)
to this project. **Status**: ✅ implemented · 🟡 partial / manual · ⚪ not applicable · 🔷 option documented, not built.

**Risk tier: High** (HITL-01). The agent proposes changes to settlement records and drafts external emails.
So every write needs a named human, is enforced in two places, and emails are queued, never sent.

| Control | Status | How this project does it | Configure it | Other options (not built here) |
|---|---|---|---|---|
| DATA-01 Source inventory & lineage | 🟡 | Seven source tables documented in `schema/schema.sql` (OMS trades, allocations, broker confirms, custodian, SSIs, exceptions, history); every tool result hash is logged per step. | `schema/schema.sql` | Data catalog (DataHub/Unity), OpenLineage events from the MCP server |
| DATA-02 Quality gates before AI | 🟡 | Malformed or missing source data surfaces as a tool error and forces escalation instead of a guess (case EX-0039). No upstream test suite — sources are operational systems. | `policy.escalate_on_tool_error` | dbt/Great Expectations tests on the nightly feeds; freshness checks on custodian files |
| DATA-03 Minimization & sensitive data | ✅ | The model sees only what a tool returns for one trade; no bulk tables. SSI account refs are internal references, not bank account numbers. | `agent.read_tools` | Field-level masking in the MCP server (e.g. show last 4 of account refs) |
| DATA-04 Usage rights | ⚪ | Internal operational data processed for its own purpose; no third-party licences involved. Provider terms are covered by SEC-05. | — | — |
| DATA-05 Retrieval corpus hygiene | ⚪ | No retrieval corpus; similar cases come from a SQL lookup tool. | — | — |
| SEC-01 Secrets management | ✅ | Model keys and `APPROVAL_SIGNING_KEY` from environment; `.env` git-ignored; the signing key is passed only to the write-scoped server process; Bedrock uses IAM. | `.env.example` | Secrets Manager / Vault; KMS-backed signing (asymmetric, so the server only holds the public key) |
| SEC-02 Prompt-injection defense | ✅ | Every tool result is screened for instruction-like text and bank-detail-change requests; broker `free_text` is labelled untrusted by the server; any hit escalates. The model has no write capability to abuse. Cases EX-0037 and EX-0038. | `policy.escalate_on_injection`, `policy.escalate_on_ssi_change_request`, `policy.INJECTION` patterns | Classifier model (Llama Guard / Bedrock Guardrails) on tool results; spotlighting / data-marking of untrusted fields |
| SEC-03 Least-privilege tools | ✅ | Model gets 7 read tools on a **read-only DB handle**; the write tool is registered only in a separate server process started after approval; tools outside the allow-list are refused and flagged. | `agent.read_tools`, `MCP_TOOL_SCOPE` | Per-tool OAuth scopes via MCP authorization; row-level security in Postgres |
| SEC-04 Output handling | ✅ | `submit_proposal` is a Pydantic schema (enums for category and fix); invalid output → escalation, never parsed free text. Proposal is data; only the execute node acts. | `policy.py: Proposal` | Provider strict tool schemas |
| SEC-05 Provider & residency terms | ✅ | Registry `approved:` flag blocks unreviewed models (OpenAI ships disabled); Bedrock keeps traffic in-region under IAM. | `config/models.yaml` | Zero-data-retention agreements; VPC endpoints |
| SEC-06 Supply chain | 🟡 | Version-bounded Python deps, `package-lock.json` for Node, `npm audit` + `pip-audit` in CI (report-only), ECR scan in AWS path. | CI | Hash-pinned `uv.lock`; SBOM; Dependabot; signed MCP server images |
| COST-01 Hard budgets | ✅ | Per-exception ($0.25) and per-run ($5) caps checked before each LLM call; tool-call cap (8) and LLM-turn cap (10); unpriced models refused. Exceeding any cap escalates. | `cost.*`, `agent.max_tool_calls`, `agent.max_llm_turns` | Gateway budgets (LiteLLM proxy) per team |
| COST-02 Cost attribution | ✅ | Tokens and $ per LLM step (`agent_steps`) and per exception (`agent_runs`); `cost-report` by month/model/prod-vs-eval. | — | Langfuse/Datadog LLM observability |
| COST-03 Efficiency levers | 🟡 | Cheap model tier is one alias change; prompt is short; playbook limits lookups. | `aliases` | Prompt caching of system prompt + tool schemas; parallel tool calls; small model for triage, large for hard cases |
| COST-04 Alerts & review | ✅ | Monthly total vs threshold in `cost-report`; AWS Budgets alert in the AWS path. | `cost.monthly_alert_usd` | Slack alert webhook |
| MODEL-01 Registry & aliases | ✅ | Code references `investigator-*` aliases; registry holds provider, ID, pricing, approval, deprecation date. | `config/models.yaml` | LiteLLM router |
| MODEL-02 Eval-gated changes | ✅ | `eval --alias investigator-candidate --baseline investigator-primary` gates outcome **and** trajectory metrics; `promote` refuses without a passing eval on the current prompt hash. | `eval.*` | Shadow mode on live queue before promotion |
| MODEL-03 Deprecation monitoring | 🟡 | `models-check` warns within the window; dates entered manually. | `governance.deprecation_warning_days` | Automated provider-deprecation feed |
| MODEL-04 Prompt versioning | ✅ | `prompts/investigator.v1.md`; prompt SHA on every run; promotion invalidated by prompt edits. | `llm.prompt_file` | Prompt registry |
| MODEL-05 Fallback & resilience | ✅ | Provider errors fall back to `investigator-fallback`; LangGraph checkpoints let a paused or crashed thread resume. | `llm.fallback_alias`, `checkpoint_db` | Cross-provider fallback; durable execution (Temporal) |
| EVAL-01 Golden dataset | ✅ | 16 cases: 2 per break type (both "who's wrong" variants) + injection, SSI-change fraud, malformed data, ambiguous/loop. | `evals/golden_set.yaml` | Sample of real historical breaks with outcomes |
| EVAL-02 Metrics & thresholds | ✅ | Category and fix accuracy, **escalation recall**, **trajectory compliance** (required tools, step cap), **unapproved writes = 0**, cost. | `eval.*` | LLM-as-judge on root-cause quality; analyst edit-distance on emails |
| EVAL-03 Regression in CI | ✅ | CI builds the server, runs Node + Python tests, the offline agent over all 40 exceptions and the eval gate. | `.github/workflows/ci.yml` | Scheduled live-model eval |
| OBS-01 Run log | ✅ | `agent_steps`: every LLM turn and tool call with args, result hash/preview, tokens, cost, flags; `agent_runs` per exception. | — | OpenTelemetry GenAI spans |
| OBS-02 Traceability | ✅ | Each evidence item `{tool, field, value}` is verified against the actual tool results; mismatches escalate. `tradeops replay` prints the full trajectory. | `policy.require_evidence_match` | Link evidence to source-system record URLs in the UI |
| OBS-03 Retention | 🟡 | Local SQLite; AWS path sets CloudWatch/S3 retention ≈ 7 years. | `governance.log_retention_days` | S3 Object Lock (WORM) for books-and-records |
| HITL-01 Risk tiering | ✅ | `risk_tier: high` with rationale; drives two-layer write control and outbox-only email. | `risk_tier` | — |
| HITL-02 Human approval | ✅ | LangGraph `interrupt()` pauses every clean proposal; approve/edit/reject via Streamlit or CLI with a named approver; HMAC token binds the approval to the exact content written; optional approver allow-list. | `approval.*` | Four-eyes (two approvers) for SSI or large-value cases; SSO identity instead of typed name |
| HITL-03 Feedback loop | 🟡 | `approvals` records AI fix vs final fix and whether edited; overrides are candidates for new golden cases (manual step). | — | Auto-open a PR adding overridden cases to the golden set |
| HITL-04 Use-case card | ✅ | See README → *Use-case card*. | `README.md` | — |

## Model migration runbook (MODEL-02/03)

1. Add the model to `config/models.yaml` with pricing and `approved: true` after provider review.
2. Point `investigator-candidate` at it.
3. `tradeops eval --alias investigator-candidate --baseline investigator-primary`. It must pass: category/fix accuracy,
   100% escalation recall, trajectory compliance, zero unapproved writes, and no regression.
4. Read the per-case diffs in `output/evals/`; pay special attention to the adversarial cases and tool-call counts.
5. `tradeops promote investigator-primary <model>`; commit with the eval run ID.
6. Keep the previous model as `investigator-fallback` for one cycle.
