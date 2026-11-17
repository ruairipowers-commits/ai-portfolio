# Governance mapping — lob-matching-engine

Maps every control in the portfolio's [AI governance standard]({{SITE_URL}}/blog/governance/) (copy in [`governance/controls.md`](../governance/controls.md) when published)
to this project. **Status**: ✅ implemented · 🟡 partial / manual · ⚪ not applicable · 🔷 option documented, not built.

**Risk tier: Medium** (HITL-01). The model's narratives inform a compliance decision about a (fictional) trader, so
a named analyst disposes of every alert and high-severity alerts can't be closed without a written reason. The model
never decides what is an alert and never sees a trader's id. No real orders, venues or people.

| Control | Status | How this project does it | Configure it | Other options (not built here) |
|---|---|---|---|---|
| DATA-01 Source inventory & lineage | ✅ | One input: the order log (synthetic generator or uploaded CSV, schema in `sessions.COLUMNS`). Every run stores its source, command count and the full engine event log keyed by run id, so each alert traces command → engine event → alert → narrative. | `store_path`, `session.*` | OpenLineage events from the replay job; venue drop-copy as a second source to reconcile |
| DATA-02 Quality gates before AI | ✅ | `sessions.validate` checks columns, actions, order types, sides, positive quantities, the price band, monotonic time, orphan cancels and duplicate refs. A failure stops the run before replay and before any model call. | `gate.*`, `engine.price_band` | Great Expectations / pandera schemas; sequence-gap checks against exchange sequence numbers |
| DATA-03 Minimization & sensitive data | ✅ | The model gets only the alert's computed facts, up to 40 event ids and up to 8 sanitized memos. Trader ids become `TRADER-n` (mapping stays local). Emails, phones and SSN-like strings are redacted. | `data.pseudonymise_traders`, `data.redact_pii`, `data.max_memos_per_alert` | Presidio / Comprehend PII; keyed-hash pseudonyms shared with the case-management system |
| DATA-04 Usage rights | ⚪ | All data is synthetic and generated here. With real order data, the venue's / client's terms and surveillance-record rules would gate any third-party model use; the Bedrock path keeps data in-account. | — | Contract flag per data source checked before the model step (see *altdata-triage*) |
| DATA-05 Retrieval corpus hygiene | ⚪ | No retrieval corpus: the model sees only the alert's own events. | — | — |
| SEC-01 Secrets management | ✅ | Keys only from the environment; `.env` git-ignored; Bedrock uses IAM roles. | `.env.example` | AWS Secrets Manager; OIDC in CI |
| SEC-02 Prompt-injection defense | ✅ | Memos are scanned for instruction patterns, `<`/`>` escaped, truncated and placed in `<untrusted_order_memos>`. A hit flags the alert and forces the suggestion to ESCALATE. The mock model is deliberately gullible, so tests prove the guard, not the model. | `guardrails.INJECTION_PATTERNS`, `policy.escalate_on_injection`, `data.max_memo_chars` | Bedrock Guardrails prompt-attack filter; a classifier model; dropping memos entirely |
| SEC-03 Least-privilege tools | ⚪ | No agent tools. The workflow reads the event log in code; the only write (a disposition) is made by a person in the app. AWS task role can't update dispositions. | `infra/aws/main.tf` | Read-only MCP query tools for analysts (see *trade-ops-exceptions*) |
| SEC-04 Output handling | ✅ | Pydantic schema with `extra="forbid"`, enums and bounds; parse failure yields an ESCALATE fallback narrative, never a guess. Output is rendered as text. | `schemas.py` | Provider structured outputs; one repair prompt |
| SEC-05 Provider & residency terms | ✅ | Registry `approved:` flag; unapproved models can't be resolved (OpenAI ships disabled). The app lists only approved, priced models with a key present. | `config/models.yaml` | Zero-retention agreements; private endpoints |
| SEC-06 Supply chain | 🟡 | Version-bounded Python deps; `Cargo.lock` committed; `pip-audit` in CI (report-only); ECR scan on push in the AWS path. | `pyproject.toml`, `rust/Cargo.lock`, CI | `cargo audit` / `cargo deny`; hash-pinned Python lockfile; SBOM |
| COST-01 Hard budgets | ✅ | Pre-flight per call: token cap, worst-case cost vs remaining run budget, unpriced models refused. A blocked call stops the run and is logged. | `cost.*` | Gateway budgets per key (LiteLLM proxy) |
| COST-02 Cost attribution | ✅ | `ai_calls` stores tokens and $ per call, alert, run and model; `cost-report` splits prod vs eval. | — | Langfuse / Helicone |
| COST-03 Efficiency levers | 🟡 | Small payloads (facts + ≤8 memos, ≈1.5k tokens); one call per alert, none for a clean session; tiering is one alias change. | `aliases`, `data.max_memos_per_alert` | Prompt caching of the static system prompt; batch API for overnight runs |
| COST-04 Alerts & review | ✅ | Monthly total vs threshold in `cost-report`; AWS Budgets forecast alert in the AWS path. | `cost.monthly_alert_usd` | Slack/Teams alert; FinOps review |
| MODEL-01 Registry & aliases | ✅ | Code uses `narrative-primary` / `-fallback` / `-candidate`; the registry holds provider, ID, pricing, deprecation date. | `config/models.yaml` | MLflow registry; LiteLLM router |
| MODEL-02 Eval-gated changes | ✅ | `eval --alias narrative-candidate --baseline narrative-primary` fails on any threshold or regression; `promote` refuses without a passing eval on the current prompt hash. | `eval.*` | Shadow runs on live alerts; blind analyst grading |
| MODEL-03 Deprecation monitoring | 🟡 | `models-check` warns inside the window; runbook below. Dates are entered by hand. | `governance.deprecation_warning_days` | Scrape provider deprecation pages |
| MODEL-04 Prompt versioning | ✅ | `prompts/alert_narrative.v1.md`; version + SHA logged per call; promotion invalidated by a prompt change. | `llm.prompt_file` | Prompt registry |
| MODEL-05 Fallback & resilience | ✅ | Retries with backoff, then the fallback alias; a failed call yields an explicit ESCALATE fallback narrative (degraded mode is visible). | `llm.fallback_alias`, `llm.retries` | Cross-provider fallback (Bedrock ↔ Anthropic API) |
| EVAL-01 Golden dataset | ✅ | 7 cases: each behaviour detected, grounding, injection, PII, a CLOSE-on-high compliance case and a clean session with zero alerts. | `evals/golden_set.yaml` | Replay of labelled historical alerts |
| EVAL-02 Metrics & thresholds | ✅ | Detection recall, false-positive alerts, schema-valid rate, citation accuracy, injection recall, PII leaks, total cost, each with a threshold. | `eval.*` | Narrative quality graded by analysts (1–5) |
| EVAL-03 Regression in CI | ✅ | CI builds the Rust engine, runs Rust and Python tests, the offline end-to-end run and the eval gate on every push. | `.github/workflows/ci.yml` | Scheduled live-model eval (job included, runs on schedule only) |
| OBS-01 Run log | ✅ | Each call logs model, prompt version + SHA, input hash, tokens, latency, cost, fallback, status; each run logs its source, gate result, stats and spend. | `store.py` | OpenTelemetry GenAI spans |
| OBS-02 Traceability | ✅ | Every cited event id must belong to the alert; every figure must equal the computed fact; numbers in the summary must appear in the facts. Errors force ESCALATE and show in the app. | `guardrails.check_citations` | Highlight cited events on a replay timeline (partly in the app) |
| OBS-03 Retention | 🟡 | `log_retention_days` (~7 years) documented; local SQLite has no automatic expiry. AWS path: S3 Object Lock (compliance mode) for dispositions and narratives. | `governance.log_retention_days` | WORM archive per your surveillance-record rules (e.g. SEC 17a-4 / MiFID II) |
| HITL-01 Risk tiering | ✅ | Medium, with rationale above and in `config/settings.yaml`; the tier is reported to the governance console. | `risk_tier` | Tier-driven approval matrix |
| HITL-02 Human approval | ✅ | Only a named analyst closes or escalates; closing a high-severity alert needs a written reason (enforced in code); the model's CLOSE suggestion is overridden on high severity. | `policy.min_close_reason_chars`, `policy.no_close_suggestion_on` | Four-eyes on closes; case-management integration |
| HITL-03 Feedback loop | 🟡 | Every disposition is stored with `agrees_with_ai`; the eval report shows human agreement. Turning overrides into new golden cases is manual. | `dispositions` table | Auto-draft golden cases from overrides for review |
| HITL-04 Use-case card | ✅ | In the README: intended use, limits, owners and known failure modes. | `README.md` | — |

## Model migration runbook (MODEL-02/03)

1. Add the new model to `config/models.yaml` with pricing and `approved: true` (after provider review).
2. Point `narrative-candidate` at it.
3. `lob-matching-engine eval --alias narrative-candidate --baseline narrative-primary` — must PASS with no regression.
4. Review the eval JSON in `output/evals/` (per-case results, cost delta).
5. `lob-matching-engine promote narrative-primary <model>`; commit `models.yaml` with the eval report ID in the message.
6. Keep the old model as `narrative-fallback` for one cycle, then retire it.
