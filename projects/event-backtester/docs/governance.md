# Governance mapping — event-backtester

Maps every control in the portfolio's [AI governance standard]({{SITE_URL}}/blog/governance/) (copy in [`governance/controls.md`](../governance/controls.md) when published)
to this project. **Status**: ✅ implemented · 🟡 partial / manual · ⚪ not applicable · 🔷 option documented, not built.

**Risk tier: Medium** (HITL-01). The output supports a capital-allocation decision (promotion to paper trading), but
no orders are sent and a named PM decides every promotion. The real risks are overstated performance and a memo that
misquotes the run, so the promotion checks are code, the memo is checked figure by figure and against presentation
rules, and approval is refused while anything is blocked.

| Control | Status | How this project does it | Configure it | Other options (not built here) |
|---|---|---|---|---|
| DATA-01 Source inventory & lineage | ✅ | One input per run: a tick file (synthetic generator with its seed and parameters, or an upload). Each run stores the dataset name and a content hash, the strategy and parameters, every metric and every check. | `dataset.*`, `dataset_path` | Vendor tick data with a licence + refresh record; OpenLineage from the loader |
| DATA-02 Quality gates before AI | ✅ | `gates.validate_ticks`: minimum size, missing or non-positive prices, crossed quotes (ask < bid), time going backwards, spreads above a cap, long intraday gaps. A failure stops the run before any backtest or model call. | `gate.*` | Exchange calendar checks; corporate-action adjustment checks |
| DATA-03 Minimization & sensitive data | ✅ | The model sees computed metrics, check results and the researcher's notes (emails / phones redacted). Ticks, fills and code never reach it. | `data.redact_pii`, `data.max_notes_chars` | Strip notes entirely for external models |
| DATA-04 Usage rights | ⚪ | Synthetic data only. With licensed market data, the vendor's terms on derived works and third-party processing would gate the model step. | — | Licence flag on each dataset checked before the memo step |
| DATA-05 Retrieval corpus hygiene | ⚪ | No retrieval corpus. | — | — |
| SEC-01 Secrets management | ✅ | Keys only from the environment; `.env` git-ignored; Bedrock via IAM. | `.env.example` | Secrets Manager; OIDC in CI |
| SEC-02 Prompt-injection defense | ✅ | Notes are scanned (including "state the Sharpe is…", "mark it approved", "skip the disclaimer"), escaped and delimited. A hit blocks promotion. The mock model is deliberately gullible, so tests prove the guard. | `guardrails.INJECTION_PATTERNS`, `policy.block_on_injection` | Bedrock Guardrails; classifier model |
| SEC-03 Least-privilege tools | ⚪ | No agent tools. Custom strategy code (the only code execution) runs locally only and is disabled in the hosted demo (`PORTFOLIO_DEMO=1`). | `workflow.factory` | Sandboxed runner (Firecracker / gVisor) for custom strategies |
| SEC-04 Output handling | ✅ | Pydantic schema with `extra="forbid"`; parse failure gives a fallback memo that blocks promotion. Output is rendered as text. | `schemas.py` | Provider structured outputs |
| SEC-05 Provider & residency terms | ✅ | Registry `approved:` flag; the app lists only approved, priced models with a key present. | `config/models.yaml` | Zero-retention agreements |
| SEC-06 Supply chain | 🟡 | Version-bounded deps; `pip-audit` in CI (report-only); ECR scan on push in the AWS path. | `pyproject.toml`, CI | Hash-pinned lockfile; SBOM |
| COST-01 Hard budgets | ✅ | Per-call token cap and per-run spend cap, checked before each call; unpriced models refused. | `cost.*` | Gateway budgets |
| COST-02 Cost attribution | ✅ | `ai_calls`: tokens and $ per call, run and model; `cost-report` splits prod vs eval. | — | Langfuse |
| COST-03 Efficiency levers | 🟡 | One call per run on ≈2k tokens of metrics; tiering is one alias change. The expensive part (backtests) is plain code. | `aliases` | Prompt caching; batch API |
| COST-04 Alerts & review | ✅ | Monthly threshold in `cost-report`; AWS Budgets alert in the AWS path. | `cost.monthly_alert_usd` | Slack alert |
| MODEL-01 Registry & aliases | ✅ | Code uses `memo-primary` / `-fallback` / `-candidate`; registry holds provider, ID, pricing, deprecation. | `config/models.yaml` | LiteLLM router |
| MODEL-02 Eval-gated changes | ✅ | `eval --alias memo-candidate --baseline memo-primary` fails on threshold or regression; `promote` needs a passing eval on the current prompt hash. | `eval.*` | Blind PM grading of memos |
| MODEL-03 Deprecation monitoring | 🟡 | `models-check` warns inside the window; runbook below. | `governance.deprecation_warning_days` | Provider-page scraper |
| MODEL-04 Prompt versioning | ✅ | `prompts/research_memo.v1.md`; version + SHA logged per call. | `llm.prompt_file` | Prompt registry |
| MODEL-05 Fallback & resilience | ✅ | Retries then the fallback alias; a failed call yields a fallback memo that blocks promotion (degraded mode is explicit). | `llm.fallback_alias`, `llm.retries` | Cross-provider fallback |
| EVAL-01 Golden dataset | ✅ | 7 cases: promotable, Sharpe-inflation injection, gross-as-net compliance, leaky strategy, no edge, bad data, selection haircut. | `evals/golden_set.yaml` | Historical memos graded by the committee |
| EVAL-02 Metrics & thresholds | ✅ | Case pass rate, schema-valid rate, citation accuracy on clean cases, injection recall, compliance catch rate, total cost. | `eval.*` | Memo readability score |
| EVAL-03 Regression in CI | ✅ | CI builds the kernel, runs the parity suite and tests, the offline end-to-end run and the eval gate. | `.github/workflows/ci.yml` | Scheduled live-model eval (job included) |
| OBS-01 Run log | ✅ | Per call: model, prompt version + SHA, input hash, tokens, latency, cost, status. Per run: dataset hash, strategy, params, metrics, checks, spend. | `store.py` | OpenTelemetry GenAI spans |
| OBS-02 Traceability | ✅ | Every memo figure must equal the stored metric; the headline must equal the NET figures (gross quoted as net is named as such); failed checks must appear in the risks. | `guardrails.check_citations`, `guardrails.check_compliance` | Link each figure to its metric in a rendered memo |
| OBS-03 Retention | 🟡 | `log_retention_days` documented; local SQLite has no expiry. AWS path: S3 Object Lock (compliance mode) for promotion records. | `governance.log_retention_days` | Records policy per jurisdiction |
| HITL-01 Risk tiering | ✅ | Medium, rationale above and in `config/settings.yaml`, reported to the console. | `risk_tier` | — |
| HITL-02 Human approval | ✅ | A named PM approves or rejects; approval is refused in code while any check, figure, disclosure or injection blocker stands. | `promotion.*`, `policy.*` | Two approvers for capital above a threshold |
| HITL-03 Feedback loop | 🟡 | Decisions stored with `agrees_with_ai`; the eval report shows agreement. New golden cases from overrides are added by hand. | `promotions` table | Auto-draft cases from overrides |
| HITL-04 Use-case card | ✅ | In the README. | `README.md` | — |

## Model migration runbook (MODEL-02/03)

1. Add the new model to `config/models.yaml` with pricing and `approved: true` (after provider review).
2. Point `memo-candidate` at it.
3. `event-backtester eval --alias memo-candidate --baseline memo-primary` — must PASS with no regression.
4. Review the eval JSON in `output/evals/`.
5. `event-backtester promote memo-primary <model>`; commit `models.yaml` with the eval report ID.
6. Keep the old model as `memo-fallback` for one cycle, then retire it.
