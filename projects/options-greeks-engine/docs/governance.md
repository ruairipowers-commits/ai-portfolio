# Governance mapping — options-greeks-engine

Maps every control in the portfolio's [AI governance standard]({{SITE_URL}}/blog/governance/) (copy in [`governance/controls.md`](../governance/controls.md) when published)
to this project. **Status**: ✅ implemented · 🟡 partial / manual · ⚪ not applicable · 🔷 option documented, not built.

**Risk tier: High** (HITL-01). A ticket feeds a trading decision with leverage and potentially unlimited loss.
So the model only proposes legs and explains numbers; code validates every leg, prices, and checks permissions
and limits; a blocked ticket can't be approved; every approval needs a named approver and a reason; and nothing is
ever sent to a broker. Accounts, the underlying and the chain are fictional.

| Control | Status | How this project does it | Configure it | Other options (not built here) |
|---|---|---|---|---|
| DATA-01 Source inventory & lineage | ✅ | Reference data is versioned in git: `config/market.yaml` (chain, vol surface, `version`, owner: risk desk) and `config/accounts.yaml`. Each ticket stores the request hash, legs, risk, checks, cross-check and decision. | `market_file`, `accounts_file` | Live chain from a market-data vendor with a snapshot id per ticket |
| DATA-02 Quality gates before AI | 🟡 | Reference data is static and reviewed in git; the code checks every leg against it before pricing. No automated tests on the vol surface itself (e.g. calendar arbitrage). | `config/market.yaml` | Arbitrage-free surface checks (no calendar / butterfly arbitrage) before each session |
| DATA-03 Minimization & sensitive data | ✅ | The parse call sees the chain summary and the redacted request; the explain call sees only computed numbers. Account names and limits never reach the model. | `request.redact_pii`, `request.max_chars` | Presidio; dropping free text for structured order entry |
| DATA-04 Usage rights | ⚪ | Fictional reference data. With vendor data, licence terms would gate model use. | — | Licence flag per data source |
| DATA-05 Retrieval corpus hygiene | ⚪ | No retrieval corpus. | — | — |
| SEC-01 Secrets management | ✅ | Keys only from the environment; Bedrock via IAM. | `.env.example` | Secrets Manager |
| SEC-02 Prompt-injection defense | ✅ | The request is screened ("pre-approved", "skip the limit check", "note to assistant"…), escaped and delimited. A hit still lets the limits run but blocks approval until the request is resubmitted clean. | `guardrails.INJECTION_PATTERNS`, `policy.block_on_injection` | Bedrock Guardrails; structured order entry instead of text |
| SEC-03 Least-privilege tools | ⚪ | No tools. The only write is the approver's decision; there is no route to a broker. AWS: the task can propose tickets; approval is another principal. | `infra/aws/main.tf` | Step Functions approval with a task token (documented in the AWS guide) |
| SEC-04 Output handling | ✅ | Both outputs are Pydantic schemas with `extra="forbid"`; a model that adds an `approved` field, invents a strike, adds a leg or changes a quantity produces no ticket. | `schemas.py`, `guardrails.validate_legs` | Provider structured outputs |
| SEC-05 Provider & residency terms | ✅ | Registry `approved:` flag; only approved, priced models with a key are offered. | `config/models.yaml` | Zero-retention agreements |
| SEC-06 Supply chain | 🟡 | Version-bounded deps; `pip-audit` in CI (report-only); ECR scan on push. | `pyproject.toml`, CI | Hash-pinned lockfile; SBOM |
| COST-01 Hard budgets | ✅ | Per-call token cap and per-run cap checked before each call; unpriced models refused. | `cost.*` | Gateway budgets |
| COST-02 Cost attribution | ✅ | `ai_calls` per ticket, purpose (parse / explain) and model; `cost-report`. | — | Langfuse |
| COST-03 Efficiency levers | 🟡 | Two short calls per ticket (≈1k tokens each); separate aliases let the parse use a smaller model than the explanation. | `aliases.parse-*`, `aliases.explain-*` | Prompt caching of the static chain summary |
| COST-04 Alerts & review | ✅ | Monthly threshold in `cost-report`; AWS Budgets in the AWS path. | `cost.monthly_alert_usd` | Slack alert |
| MODEL-01 Registry & aliases | ✅ | `parse-*` and `explain-*` aliases; registry holds provider, ID, pricing, deprecation. | `config/models.yaml` | LiteLLM router |
| MODEL-02 Eval-gated changes | ✅ | `eval --alias parse-candidate --baseline parse-primary`; `promote` needs a passing eval on the current prompt hash. | `eval.*` | Shadow parsing on live requests |
| MODEL-03 Deprecation monitoring | 🟡 | `models-check` warns inside the window; runbook below. | `governance.deprecation_warning_days` | Provider-page scraper |
| MODEL-04 Prompt versioning | ✅ | `prompts/parse_request.v1.md`, `prompts/risk_explanation.v1.md`; version + SHA per call. | `llm.parse_prompt`, `llm.explain_prompt` | Prompt registry |
| MODEL-05 Fallback & resilience | ✅ | Retries then the fallback alias; a failed explanation blocks approval (degraded mode is explicit); a failed parse gives no ticket. | `llm.fallback_alias`, `llm.retries` | Cross-provider fallback |
| EVAL-01 Golden dataset | ✅ | 8 cases: exact parse, clarification, injection, two permission cases, unlisted strike, limit breach, explanation grounding. | `evals/golden_set.yaml` | Real (anonymised) request logs |
| EVAL-02 Metrics & thresholds | ✅ | Case pass rate, exact-parse rate, schema-valid rate, citation accuracy, injection recall, block recall, cost. | `eval.*` | Per-structure parse accuracy |
| EVAL-03 Regression in CI | ✅ | CI builds the engine, runs pricing-accuracy and determinism tests, the end-to-end run and the eval gate. | `.github/workflows/ci.yml` | Scheduled live-model eval (job included) |
| OBS-01 Run log | ✅ | Per call: purpose, model, prompt version + SHA, input hash, tokens, latency, cost, status. Per ticket: status, legs, risk, checks, cross-check, flags, decision. | `store.py` | OpenTelemetry GenAI spans |
| OBS-02 Traceability | ✅ | Every explanation figure must equal the engine's number; every leg must trace to the chain and to the request text. | `guardrails.check_citations`, `guardrails.validate_legs` | Highlight the request span each leg came from |
| OBS-03 Retention | 🟡 | `log_retention_days` documented; local SQLite has no expiry. AWS: S3 Object Lock for approved tickets. | `governance.log_retention_days` | Books-and-records archive |
| HITL-01 Risk tiering | ✅ | High: leverage and unlimited-loss structures. The tier is why limits block rather than warn and why approval needs a reason. | `risk_tier` | Tier per account or structure |
| HITL-02 Human approval | ✅ | A named approver with a reason (≥ 10 characters); blocked, invalid or unclarified tickets can't be approved; decisions are final. | `policy.min_approval_reason_chars` | Four-eyes above a premium threshold |
| HITL-03 Feedback loop | 🟡 | Decisions and blocked tickets are stored; turning a mis-parse into a golden case is manual. | `decisions` table | Approver "mis-parsed" button that drafts a golden case |
| HITL-04 Use-case card | ✅ | In the README. | `README.md` | — |

## Model migration runbook (MODEL-02/03)

1. Add the new model to `config/models.yaml` with pricing and `approved: true` (after provider review).
2. Point `parse-candidate` (and/or `explain-candidate`) at it.
3. `options-greeks-engine eval --alias parse-candidate --baseline parse-primary` — must PASS with no regression.
4. Review the eval JSON in `output/evals/`.
5. `options-greeks-engine promote parse-primary <model>`; commit `models.yaml` with the eval report ID.
6. Keep the old model as `parse-fallback` for one cycle, then retire it.
