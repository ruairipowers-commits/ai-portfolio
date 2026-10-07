# Governance mapping — data-lifecycle-platform

Maps every control in the portfolio's [AI governance standard]({{SITE_URL}}/blog/governance/) to this project.
**Status**: ✅ implemented · 🟡 partial / manual · ⚪ not applicable · 🔷 option documented, not built.

**Risk tier: Medium** (HITL-01). The AI reads vendor pages, drafts catalog records and memos, plans searches and
answers questions about the data estate. Its output steers licensing, spend and listing decisions, and it reads
untrusted vendor text, so every write (catalog publication, contracts, licence decisions, listings, retirements)
waits for a named person, and usage rights are decided by code, never by the model.

| Control | Status | How this project does it | Configure it | Other options (not built here) |
|---|---|---|---|---|
| DATA-01 Source inventory & lineage | ✅ | Every landing source is declared in dbt `sources.yml` with owner, licence and the catalog `dataset_id`; dbt's lineage (the same graph the Dagster assets are built from) is written into the knowledge graph as `DataAsset → readsFrom → Dataset`, so `impact()` can answer "what breaks if this goes". Extracted catalog fields keep their source URL (`provenance`). | `semantic/models/sources.yml`, `graph._lineage` | OpenLineage events from Dagster; DataHub / Unity Catalog lineage |
| DATA-02 Quality gates before AI | ✅ | 22 dbt tests (unique, not-null, accepted GICS sectors, IV/HV/VIX ranges, one row per symbol-day) plus SHACL validation of the graph. A failed test closes the gate file; `semantic.query()` and therefore every answer refuses to run; a SHACL violation stops the graph load. | `data.require_dbt_tests_pass`, `data.require_shacl_conforms` | Great Expectations / Soda; dbt source freshness as a hard gate |
| DATA-03 Minimization & sensitive data | ✅ | The model only ever sees the context packet: metric results and short graph facts for datasets in scope, capped at 4,000 tokens, with no customer ids. Vendor text is PII-redacted before extraction. A data owner's sample with personal-data columns is blocked before any model call. | `layers.context_max_tokens`, `data.redact_pii`, `data.pii_columns`, `monetize.block_on_pii` | Presidio / Comprehend PII detection; column-level masking in the warehouse |
| DATA-04 Usage rights | ✅ | `licensing.py` decides PERMITTED / CONDITIONAL / LEGAL_REVIEW / BLOCKED per dataset, use case and firm from licence tags and active contracts. No licence → legal review; vendor text that contradicts the tag → legal review; a contract that excludes AI processing keeps the data out of every packet. Extraction can never set a licence tag. | `licensing.*`, `contracts.*` | Contract-management system integration; clause extraction from signed PDFs (with legal review) |
| DATA-05 Retrieval corpus hygiene | ⚪ | No text retrieval corpus: retrieval is SPARQL over the graph plus governed metric queries. The equivalent hygiene is the ontology version, SHACL and the graph version recorded per build. | — | — |
| SEC-01 Secrets management | ✅ | Keys only from the environment (`.env` git-ignored). API tokens are HMACs of the principal with `DLP_TOKEN_SECRET`; the hosted demo refuses to start the API without it. Bedrock uses IAM. | `.env.example` | Secrets Manager / Vault; OIDC for CI |
| SEC-02 Prompt-injection defense | ✅ | Vendor pages, cards, owner descriptions, search needs and questions are scanned, escaped and delimited. Extracted values whose quote comes from injected text are dropped and flagged; the Larkspur page is a live test. Injection in a question is flagged and changes nothing (the packet is built by code). | `guardrails.INJECTION_PATTERNS`, `data.max_untrusted_chars` | Classifier-based screening (Llama Guard / Bedrock Guardrails) |
| SEC-03 Least-privilege tools | ✅ | The model has no tools. The MCP server exposes six read-only tools, runs as one firm's entitlements and caps calls per session. Every write goes through the approval queue. | `DLP_MCP_CUSTOMER`, `DLP_MCP_MAX_CALLS` | Per-tool OAuth scopes |
| SEC-04 Output handling | ✅ | Every response is parsed into a Pydantic schema; anything off-contract is rejected and the answer falls back to a plain rendering of the packet. Search plans keep only vocabulary ids; proposed field concepts are re-checked. | `schemas.py` | Provider structured outputs |
| SEC-05 Provider & residency terms | ✅ | Registry `approved:` flag; unapproved models can't be resolved (OpenAI ships disabled). | `config/models.yaml` | Zero-retention agreements; private endpoints |
| SEC-06 Supply chain | 🟡 | Version-bounded deps, `pip-audit` in CI (report-only), MCP SDK pinned to 2.x. | `pyproject.toml`, CI | Hash-pinned lockfile; SBOM |
| COST-01 Hard budgets | ✅ | Per-call token cap, per-action cap ($0.05) and per-run cap ($0.50) checked before every call; the eval run has its own budget. Blocked calls are logged as `budget_exceeded`. | `cost.*`, `eval.max_total_cost_usd` | Gateway budgets per key |
| COST-02 Cost attribution | ✅ | `AICall` rows hold tokens and $ per call, purpose, firm, actor and model; `cost-report` splits prod and eval. Data spend is attributed per firm and dataset in the semantic layer (`spend_usd`, `cost_per_query`). | — | Langfuse; cost-allocation tags |
| COST-03 Efficiency levers | 🟡 | Structured sources are parsed by code, not a model; the context packet is small by design; model tiering is one alias change. | `models.yaml` aliases | Prompt caching; batch extraction overnight |
| COST-04 Alerts & review | ✅ | Monthly AI spend vs alert with a named reviewer in `cost-report`; firm budgets vs annualised commitments and renewal deadlines in the app and `dlp roi`. | `cost.monthly_alert_usd`, `cost.reviewer`, `contracts.renewal_alert_days` | Slack alerts; AWS Budgets |
| MODEL-01 Registry & aliases | ✅ | Code only uses `dlp-primary` / `dlp-fallback` / `dlp-candidate`. | `config/models.yaml` | LiteLLM router |
| MODEL-02 Eval-gated changes | ✅ | `dlp eval --alias dlp-candidate --baseline dlp-primary` fails on thresholds or regression; `promote` refuses without a passing eval on the current prompt hashes. | `eval.*` | Shadow traffic |
| MODEL-03 Deprecation monitoring | 🟡 | `dlp models-check` warns inside the window; runbook below. Dates entered by hand. | `governance.deprecation_warning_days` | Scrape provider deprecation pages |
| MODEL-04 Prompt versioning | ✅ | Five prompts in `prompts/*.v1.md`; version and SHA logged per call; a prompt change invalidates promotion. | `llm.prompts` | Prompt registry |
| MODEL-05 Fallback & resilience | ✅ | Retries then `dlp-fallback`; `used_fallback` logged; a failed or ungrounded answer falls back to the packet itself. | `llm.fallback_alias`, `llm.retries` | Cross-provider fallback |
| EVAL-01 Golden dataset | ✅ | 19 cases: search (incl. economic factors), answers (grounded, undefined metric, not entitled, injection, contract excludes AI), extraction (concept mapping, injection), licences, monetization (PII), retirement. | `evals/golden_set.yaml` | Larger set from reviewer corrections |
| EVAL-02 Metrics & thresholds | ✅ | Accuracy, schema-valid rate, citation/grounding accuracy, must-escalate recall, total cost, fallback count. | `eval.*` | LLM-as-judge for memo quality |
| EVAL-03 Regression in CI | ✅ | CI runs the tests, `dlp all` and the eval gate on every push (mock, $0). | `.github/workflows/ci.yml` | Scheduled live eval |
| OBS-01 Run log | ✅ | `AICall`: model, prompt version + SHA, input and context hashes, tokens, latency, cost, status, flags and the SQL of every metric query behind an answer. Questions and sources are stored only as hashes. | — | OpenTelemetry GenAI spans |
| OBS-02 Traceability | ✅ | Every number in an answer must appear in the packet and every citation must be a packet id (metric query id or graph IRI); otherwise the packet is rendered instead. Extracted values must quote their source. | `guardrails.ungrounded_numbers`, `guardrails.quotes_missing` | Span-level attribution |
| OBS-03 Retention | 🟡 | Local SQLite with no expiry; retirements leave an archive record; the AWS path sets ~7-year retention. | `governance.log_retention_days` | S3 Object Lock (WORM) |
| HITL-01 Risk tiering | ✅ | Medium, rationale above. | `risk_tier` | Tier-driven checklist in CI |
| HITL-02 Human approval | ✅ | One approval queue for extractions, contracts, licence decisions, listings and retirements; a decision needs a named reviewer and is recorded with time and note. Contracts give no entitlement until approved. | `catalog.decide` | Four-eyes approval for contracts above a price |
| HITL-03 Feedback loop | ✅ | Reviewer edits to an extraction are stored as `Feedback` and counted in every eval report. | — | Auto-add corrections as golden cases |
| HITL-04 Use-case card | ✅ | README → *Use-case card*. | `README.md` | Model cards per model version |

## Model migration runbook (MODEL-02/03)

1. Add the model to `config/models.yaml` with pricing and `approved: true` after provider review.
2. Point `dlp-candidate` at it.
3. `dlp eval --alias dlp-candidate --baseline dlp-primary` must pass with no regression.
4. Read the per-case report in `output/evals/latest_<model>.json` (watch extraction quotes and grounding).
5. `dlp promote dlp-primary <model>`; commit `models.yaml` with the eval timestamp in the message.
6. Keep the previous model as `dlp-fallback` for one cycle, then retire it.
