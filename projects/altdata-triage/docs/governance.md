# Governance mapping — altdata-triage

Maps every control in the portfolio's [AI governance standard]({{SITE_URL}}/blog/governance/) (copy in [`governance/controls.md`](../governance/controls.md) when published)
to this project. **Status**: ✅ implemented · 🟡 partial / manual · ⚪ not applicable · 🔷 option documented, not built.

**Risk tier: Medium** (HITL-01). Output is advisory — it prioritises a human's diligence queue and
never spends money, signs contracts or touches trading. It *does* handle vendor data with licensing
and PII implications, so compliance-relevant cases are forced to a human.

| Control | Status | How this project does it | Configure it | Other options (not built here) |
|---|---|---|---|---|
| DATA-01 Source inventory & lineage | ✅ | dbt `sources.yml` declares raw tables with owner/refresh `meta`; `make docs` renders the lineage graph raw → staging → marts. | `dbt/models/staging/sources.yml` | OpenLineage/Marquez, DataHub, Unity Catalog, AWS Glue lineage |
| DATA-02 Quality gates before AI | ✅ | 14 dbt tests (not-null, unique, range, look-ahead guard). `triage` reads `run_results.json` and refuses to call any model unless every node passed. | `data.require_dbt_tests_pass` | Great Expectations / Soda checks; dbt `source freshness` as a hard gate |
| DATA-03 Minimization & sensitive data | ✅ | Model sees only 16 scorecard fields (`FACT_COLUMNS`) + sanitized notes. Raw rows never leave the warehouse. Emails/phones/SSN-like strings redacted. | `workflow.FACT_COLUMNS`, `data.redact_pii` | Microsoft Presidio or AWS Comprehend PII detection; MNPI keyword lists |
| DATA-04 Usage rights | ✅ | `license_derived_use` captured from the questionnaire; policy blocks PURSUE when PII is present without a derived-use license. | `policy.pii_without_license_allowed` | Contract-management system lookup; legal sign-off workflow |
| DATA-05 Retrieval corpus hygiene | ⚪ | No RAG in this project (see *Research Q&A* project). | — | — |
| SEC-01 Secrets management | ✅ | Keys only from environment; `.env` git-ignored; Bedrock uses IAM roles (no key at all). | `.env.example` | AWS Secrets Manager / Azure Key Vault / 1Password CLI; OIDC in CI |
| SEC-02 Prompt-injection defense | ✅ | Vendor notes are scanned for instruction patterns, `<`/`>` escaped so delimiters can't be closed, truncated, and placed in `<untrusted_vendor_notes>`. Any hit forces ESCALATE. Vendor v04 is a live test case. | `data.max_notes_chars`, `policy.escalate_on_injection`, `guardrails.INJECTION_PATTERNS` | LLM-based classifier (e.g. Llama Guard / Bedrock Guardrails prompt-attack filter); dual-LLM pattern |
| SEC-03 Least-privilege tools | ✅ | The model has no tools; code performs two read-only queries. No write paths exist. AWS role can read landing, write results, invoke only approved model ARNs. | `infra/aws/main.tf` | Tool allow-lists with MCP scopes (see *Trade-ops* project) |
| SEC-04 Output handling | ✅ | Pydantic schema with enum + bounds; parse failure yields an ESCALATE fallback memo, never a guess. Output is rendered as text, never executed. | `schemas.py` | Provider-native structured outputs / JSON mode; one-shot repair prompt |
| SEC-05 Provider & residency terms | ✅ | Registry `approved:` flag; unapproved models cannot be resolved (OpenAI entry ships disabled). Bedrock keeps traffic in your AWS region. | `config/models.yaml` | Enterprise zero-data-retention agreements; private endpoints/VPC |
| SEC-06 Supply chain | 🟡 | Version-bounded deps, `pip-audit` in CI (report-only), ECR scan-on-push in AWS path. | `pyproject.toml`, CI | `uv lock` / hash-pinned lockfile; SBOM via Syft; Dependabot |
| COST-01 Hard budgets | ✅ | Pre-flight check per call: token cap, worst-case cost vs remaining run budget, refusal of unpriced models. Blocked calls are logged. | `cost.*` | Provider-side spend limits; API gateway (LiteLLM proxy) budgets per key |
| COST-02 Cost attribution | ✅ | `audit.ai_calls` stores tokens and $ per call, vendor, run, model; `cost-report` splits prod vs eval. | — | Langfuse / Helicone dashboards; AWS cost allocation tags |
| COST-03 Efficiency levers | 🟡 | Minimized context (~1k tokens/vendor); model tiering is one alias change (e.g. Haiku for triage). | `aliases` in `models.yaml` | Prompt caching of the static system prompt; Batch APIs for overnight runs (~50% cheaper at most providers) |
| COST-04 Alerts & review | ✅ | Monthly total vs alert threshold in `cost-report`; AWS Budgets forecast alert in the AWS path. | `cost.monthly_alert_usd` | Slack/Teams alert webhook; FinOps monthly review |
| MODEL-01 Registry & aliases | ✅ | Code never names a model; aliases → registry with provider, ID, pricing, deprecation date. | `config/models.yaml` | MLflow model registry; LiteLLM router config |
| MODEL-02 Eval-gated changes | ✅ | `eval --alias triage-candidate --baseline triage-primary` fails on threshold or regression; `promote` refuses without a passing eval on the current prompt hash. | `eval.*` | Shadow traffic / canary % rollout; A/B with reviewer blind grading |
| MODEL-03 Deprecation monitoring | 🟡 | `models-check` warns inside the window; runbook below. Dates are entered manually. | `governance.deprecation_warning_days` | Scrape provider deprecation pages; calendar alerts |
| MODEL-04 Prompt versioning | ✅ | Prompt in `prompts/triage_memo.v1.md`; version + SHA logged per call; promotion invalidated by prompt change. | `llm.prompt_file` | Prompt registry (Langfuse, PromptLayer) |
| MODEL-05 Fallback & resilience | ✅ | Retries with backoff, then `triage-fallback` alias; `used_fallback` logged. Budget errors are never retried. | `llm.fallback_alias`, `llm.retries` | Cross-provider fallback (Anthropic ↔ Bedrock); circuit breaker |
| EVAL-01 Golden dataset | ✅ | 5 labelled vendors covering happy path, stale, PII/licensing, injection, look-ahead bias. | `evals/golden_set.yaml` | Synthetic case generation; larger historical sample |
| EVAL-02 Metrics & thresholds | ✅ | Accuracy, schema-valid rate, citation accuracy, escalation recall (safety), total cost. | `eval.*` | LLM-as-judge rubric for memo quality (calibrated vs humans) |
| EVAL-03 Regression in CI | ✅ | GitHub Actions runs tests + full pipeline + eval gate on every push (mock, $0); optional scheduled live eval. | `.github/workflows/ci.yml` | promptfoo / DeepEval suites |
| OBS-01 Run log | ✅ | `audit.ai_calls` (model, prompt SHA, input SHA, tokens, latency, cost, status) and `audit.triage_results`. | — | OpenTelemetry GenAI spans → Langfuse/Datadog/CloudWatch |
| OBS-02 Traceability | ✅ | Every evidence item is checked against the scorecard; mismatches are recorded and a PURSUE with bad citations is escalated. | `guardrails.check_citations` | Span-level source attribution |
| OBS-03 Retention | 🟡 | Local DuckDB (no expiry); AWS path sets S3 lifecycle + CloudWatch retention to ~7 years. | `governance.log_retention_days`, Terraform vars | WORM storage (S3 Object Lock) for SEC 17a-4 style records |
| HITL-01 Risk tiering | ✅ | `risk_tier: medium` with rationale above. | `risk_tier` | Tier-driven control checklist enforced in CI |
| HITL-02 Human approval | ✅ | Memos are advisory; `review` records a named reviewer's decision. Nothing downstream happens automatically. | — | Approval queue UI (Streamlit / Retool / Airtable) |
| HITL-03 Feedback loop | ✅ | Reviews stored in `audit.reviews`; eval reports `human_review_agreement`; overrides are candidates for new golden cases. | — | Auto-open a PR adding the case to `golden_set.yaml` |
| HITL-04 Use-case card | ✅ | See README → *Use-case card*. | `README.md` | Model cards per model version |

## Model migration runbook (MODEL-02/03)

1. Add the new model to `config/models.yaml` with pricing and `approved: true` (after provider review).
2. Point `triage-candidate` at it.
3. `altdata-triage eval --alias triage-candidate --baseline triage-primary` — must PASS with no regression.
4. Review the eval JSON in `output/evals/` (per-case diffs, cost delta).
5. `altdata-triage promote triage-primary <model>`; commit `models.yaml` with the eval report ID in the message.
6. Keep the old model as `triage-fallback` for one cycle, then retire it.
