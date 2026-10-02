# Governance mapping — eod-heartbeat

Maps every control in the portfolio's [AI governance standard]({{SITE_URL}}/blog/governance/) (copy in [`governance/controls.md`](../governance/controls.md) when published)
to this project. **Status**: ✅ implemented · 🟡 partial / manual · ⚪ not applicable · 🔷 option documented, not built.

**Risk tier: Medium** (HITL-01). The workflow explains; it never reruns, edits or publishes anything. The risk is bad
advice on NAV night — a wrong cause that wastes the on-call engineer's time, or a dangerous step (a forced full
rerun) taken from a tampered runbook. So detection is SQL, every explanation must cite the runbook it came from,
unsafe steps are blocked in code, and critical breaks always go to a person.

| Control | Status | How this project does it | Configure it | Other options (not built here) |
|---|---|---|---|---|
| DATA-01 Source inventory & lineage | ✅ | dbt `sources.yml` declares every feed with owner, source system and SLA; `dbt docs` renders raw → staging → marts → breaks. | `dbt/models/staging/sources.yml`, `config/feeds` | OpenLineage from Airflow + dbt into Marquez / DataHub |
| DATA-02 Quality gates before AI | ✅ | 28 dbt tests run every heartbeat; if any fails, the DAG task fails and nothing is explained (`blocked_dq`). Duplicate trade ids are *detected as breaks*, not test failures, so they get explained. | `dbt/models/**/schema.yml` | Source freshness as a hard gate; Great Expectations / Soda |
| DATA-03 Minimization & sensitive data | ✅ | Client names (from a client register), emails and phone numbers are redacted before runbooks and incidents are indexed; the model sees only break facts and retrieved sections, never positions or P&L tables. Governance telemetry carries counts, not content. | `kb.redact_pii`, `kb/client_register.yaml` | Presidio / Comprehend PII; MNPI watch-list |
| DATA-04 Usage rights | ⚪ | Internal operational data and internally written runbooks; no third-party licence restricts AI processing. Vendor price/FX data never reaches the model. | — | Licence flag per feed if vendor data were ever sent (see research-qa-rag) |
| DATA-05 Retrieval corpus hygiene | ✅ | Runbooks chunked by section (`RB-04#steps`), one chunk per incident; incremental re-index by file hash; `kb.index_runs` history; every explanation stores the `kb_version` and each chunk the hash of the file it came from, so a reviewer can see exactly which runbook text was cited. | `kb.*` | Runbook approval workflow (PR review) before re-index; blue/green KB versions |
| SEC-01 Secrets management | ✅ | Keys only from the environment; the embedded Postgres has no network listener; RDS credentials via Secrets Manager in the AWS path. | `.env.example` | Vault / 1Password; IAM database auth |
| SEC-02 Prompt-injection defense | ✅ | Runbook and incident paragraphs with instruction-like text are quarantined at index time (RB-10 ships with one); sources are escaped and tagged as reference material in the prompt. | `kb.quarantine_suspicious`, `kb.INJECTION_PATTERNS` | LLM classifier on runbook changes; signed runbooks |
| SEC-03 Least-privilege tools | ✅ | The model has no tools and no database access; code retrieves. Nothing the model returns is executed. The DAG's DB role needs no write access to raw feeds. | — | Separate read-only role for retrieval |
| SEC-04 Output handling | ✅ | Pydantic schema; invalid output → `needs_human` with `invalid_output`; **unsafe-action policy** blocks forced/full reruns, skipping reconciliation, deletes and publishing NAV, even when the text came from a runbook. | `policy.unsafe_action_patterns` | Allow-list of runbook step ids instead of patterns |
| SEC-05 Provider & residency terms | ✅ | Registry `approved:` flag (OpenAI entry ships disabled); Bedrock keeps traffic in-region. | `config/models.yaml` | Zero-retention agreements; VPC endpoints |
| SEC-06 Supply chain | 🟡 | Version-bounded deps; `pip-audit` (report-only); Airflow pinned with its constraints file in CI. | `pyproject.toml`, CI | Lockfile with hashes; SBOM |
| COST-01 Hard budgets | ✅ | Per-run budget across all explanations, per-call token cap, unpriced models refused. | `cost.*` | Gateway budgets per team |
| COST-02 Cost attribution | ✅ | `audit.explanations` (tokens, $ per break, model, prod vs eval); `cost-report`; governance events per run. | — | Langfuse dashboards |
| COST-03 Efficiency levers | 🟡 | A break already explained with the same model, prompt and knowledge-base version is not sent to the model again on the next 5-minute tick (`cached`); alerts are de-duplicated; the lite fallback is priced ~4× lower; the context is a handful of sections. | `retrieval.*`, aliases | Cache explanations by break signature; prompt caching |
| COST-04 Alerts & review | ✅ | `cost-report` vs monthly alert; the governance console charts spend per workflow against budget; AWS Budgets in the Terraform. | `cost.monthly_alert_usd` | FinOps review |
| MODEL-01 Registry & aliases | ✅ | `explain-primary/fallback/candidate`, `embed-primary`; code never names a model. | `config/models.yaml` | — |
| MODEL-02 Eval-gated changes | ✅ | `eval --alias explain-candidate --baseline explain-primary`; `promote` refuses without a passing eval on the current prompt. | `eval.*` | Shadow explanations alongside production for a week |
| MODEL-03 Deprecation monitoring | 🟡 | `models-check` with a warning window. Embedding changes force a full KB re-index (`kb-index --full`). | `governance.deprecation_warning_days` | Provider deprecation feed |
| MODEL-04 Prompt versioning | ✅ | `prompts/explain.v1.md`; hash on every explanation and eval report. | `llm.prompt_file` | Prompt registry |
| MODEL-05 Fallback & resilience | ✅ | Retries → `explain-fallback` (a cheaper model; flagged `fallback_model`) → **degraded mode**: the break is still detected and alerted with its runbook steps, status `degraded`. The eval gate fails on `explained_rate` when all models are down, while detection still passes. Try it in the app's outage switch. | `llm.fallback_alias`, `llm.retries` | Cross-provider fallback (Bedrock ↔ Anthropic API); circuit breaker |
| EVAL-01 Golden dataset | ✅ | All 10 business days with the exact breaks SQL must find and, per break, acceptable runbooks and whether a human is required. | `evals/golden_set.yaml` | Replay of real historical evenings |
| EVAL-02 Metrics & thresholds | ✅ | Detection recall/precision (SQL), runbook accuracy, citation rate, explained rate, human routing, unsafe actions shown (0), cost. | `eval.*` | LLM-judged usefulness calibrated against on-call ratings |
| EVAL-03 Regression in CI | ✅ | Tests + end-to-end + eval gate on the embedded Postgres; a CI job installs Airflow 3.1 and imports the DAG. | `.github/workflows/ci.yml` | Nightly live-model eval |
| OBS-01 Run log | ✅ | `audit.runs` (who/what triggered, as-of time, dbt result, counts, cost) and `audit.explanations`. | — | OpenTelemetry spans from Airflow tasks |
| OBS-02 Traceability | ✅ | Every explanation cites runbook chunk ids (and incident ids) that were in the context — checked in code; the app shows the cited text; `kb_version` + chunk `doc_sha` pin the exact text. | `policy.min_runbook_citations` | Link alerts to the runbook page at that git commit |
| OBS-03 Retention | ✅ | `eodhb retention` archives audit rows past the retention period to JSON Lines with a SHA-256 manifest, then deletes (dry run by default). The AWS path writes the archive to S3 with Object Lock. | `governance.log_retention_days`, `governance.archive_dir` | Partitioned audit tables with automatic expiry |
| HITL-01 Risk tiering | ✅ | `risk_tier: medium` with rationale above. | `risk_tier` | — |
| HITL-02 Human approval | ✅ | Nothing is executed. Critical breaks and any policy flag set `needs_human`; alerts say who must act (on-call vs ops lead). Publishing NAV is always the ops lead's decision (RB-12). | `policy.human_required_severities` | Acknowledge/assign workflow in PagerDuty / Opsgenie |
| HITL-03 Feedback loop | ✅ | 👍/👎 per explanation in `audit.feedback`; "wrong" explanations are reviewed and become golden-set cases or runbook fixes. | — | Weekly review of wrong explanations with the runbook owner |
| HITL-04 Use-case card | ✅ | See README → *Use-case card*. | `README.md` | — |

## Model migration runbook (MODEL-02/03)

1. Add the model to `config/models.yaml` with pricing and `approved: true`; point `explain-candidate` at it.
2. `eodhb eval --alias explain-candidate --baseline explain-primary` — must pass with no regression.
3. `eodhb promote explain-primary <model>`; keep the previous model as `explain-fallback` for a cycle.
4. For an embedding change: point `embed-primary` at it, `eodhb kb-index --full`, then `eodhb eval`.
