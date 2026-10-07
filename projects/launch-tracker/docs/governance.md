# Governance mapping — launch-tracker

Maps every control in the portfolio's [AI governance standard]({{SITE_URL}}/blog/governance/) (copy in [`governance/controls.md`](../governance/controls.md) when published)
to this project. **Status**: ✅ implemented · 🟡 partial / manual · ⚪ not applicable · 🔷 option documented, not built.

**Risk tier: Low** (HITL-01). Public data about launches; no decisions about people, no money moved. The real risks
are wrong facts (stale or mis-merged records, invented numbers or costs in a summary) and untrusted text from the
sources reaching the model, so numbers come only from SQL and every summary is checked against its rows.

| Control | Status | How this project does it | Configure it | Other options (not built here) |
|---|---|---|---|---|
| DATA-01 Source inventory & lineage | ✅ | Three sources, each with URL, refresh cadence and licence in config. Every row keeps `source` and `fetched_at`; matched launches keep both ids (LL2 id, GCAT tag); every load is a `source_runs` row with request count. Disagreements between sources are kept in `discrepancies` and shown on the launch page. | `sources.*` | OpenLineage events per refresh |
| DATA-02 Quality gates before AI | ✅ | Parsers read columns by name and stop with the real header if a source changes format (tested). Reconciliation checks every detailed past launch matched the history (tested). A summary is built only from a launch that exists, with dates parsed. | `sources.*` | dbt tests on the tables; freshness alerts per source |
| DATA-03 Minimization & sensitive data | ✅ | A summary's facts are a whitelist of fields (no description, no image URLs, tested); the description is passed only after screening, and withheld if flagged. Crew names are public mission data; telemetry carries counts and flags only. | `guard.*` | — |
| DATA-04 Usage rights | ✅ | Licences recorded per source (GCAT CC-BY-4.0, credited in the app). Images are displayed only with a recorded licence on the allowed list; "Unknown" becomes a link to the source (tested, golden `s06`). SATCAT downloaded at most daily per CelesTrak's usage policy; LL2 within its free-tier limit. | `images.allowed_licences`, `sources.*.refresh_hours` | Licence lookup for Wikimedia images per file |
| DATA-05 Retrieval corpus hygiene | ⚪ | No text retrieval corpus; summaries are built from SQL rows. | — | — |
| SEC-01 Secrets management | ✅ | Optional keys (LL2, model providers) only from the environment; `.env` git-ignored; the hosted demo reads none. | `.env.example` | Secrets Manager |
| SEC-02 Prompt-injection defense | ✅ | Two layers. Descriptions are scanned, escaped and delimited; if flagged they are withheld from the model. If that layer is off, the guard still rejects a draft that repeats an injected claim ("this launch failed") because it contradicts the row (golden `s02`, `s02b`; UI break-it test). | `guard.drop_description_on_injection`, `guard.flag_on_injection` | Llama Guard / Bedrock Guardrails classifier |
| SEC-03 Least-privilege tools | ✅ | The model has no tools. Writes are the app's own: loads, snapshots, reviews by a named person, audit rows. | — | — |
| SEC-04 Output handling | ✅ | Strict Pydantic schema; anything else is rejected and replaced by a plain template from the same facts. Summary text is rendered with dollar signs escaped and never executed. Filters are parameterised SQL (injection test). | `guardrails.Summary` | Provider-native structured outputs |
| SEC-05 Provider & data residency terms | ✅ | Only `approved: true` models resolve; a local Ollama model keeps everything on the machine. | `config/models.yaml` | — |
| SEC-06 Supply chain | 🟡 | Six runtime dependencies (duckdb, httpx, numpy, pandas, pydantic, PyYAML), version-bounded; repo CI runs `pip-audit`, the image check and the security self-assessment. | `pyproject.toml` | Lockfile with hashes |
| COST-01 Hard budgets | ✅ | Per-call token cap, per-run spend cap and a daily AI budget; unpriced models refused (tested). The LL2 request budget is enforced the same way for the data side. | `cost.*`, `sources.ll2.max_requests_per_hour` | Per-visitor quotas |
| COST-02 Cost attribution | ✅ | Tokens, cost and latency per call, purpose and model in `audit.ai_calls`; `launches cost-report` by month, purpose and model. | — | — |
| COST-03 Efficiency levers | ✅ | Summaries are short (500-token cap) from a small fact set; a small model is enough; local model option at $0. Summaries are only written on request. | `llm.max_output_tokens` | Cache summaries per (launch, prompt hash) |
| COST-04 Alerts & review | ✅ | `launches cost-report` compares 30-day spend with the alert threshold and names the reviewer. | `cost.monthly_alert_usd` | Email from the governance console |
| MODEL-01 Registry & aliases | ✅ | Code names aliases only (`summary-primary`, `summary-fallback`, `summary-candidate`). | `config/models.yaml` | LiteLLM router |
| MODEL-02 Eval-gated changes | ✅ | `launches eval --alias summary-candidate --baseline summary-primary` gates on thresholds and no regression; `promote` refuses without a passing eval. | `eval.*` | Shadow runs on live summaries |
| MODEL-03 Deprecation monitoring | 🟡 | `launches check-models` warns inside the window; dates entered by hand. | `governance.deprecation_warning_days` | Scrape provider deprecation pages |
| MODEL-04 Prompt versioning | ✅ | Three prompt files (`mission_summary.v1`, `weekly_digest.v1`, `what_changed.v1`); version and hash logged per call (tested). | `llm.prompts` | Prompt registry |
| MODEL-05 Fallback & resilience | ✅ | Retries, then the fallback alias; if a draft fails the guard or the model is down, a plain template from the same facts is shown and labelled. A failed data refresh keeps serving the last good database. | `llm.fallback_alias` | Cross-provider fallback |
| EVAL-01 Golden dataset | ✅ | Nine cases on the sample, found by query: grounded summary, injection (both layers), cost not public, digest numbers vs SQL, measured slip, unlicensed image, source disagreement, retirement. | `evals/golden_set.yaml` | Cases from live data, frozen weekly |
| EVAL-02 Metrics & thresholds | ✅ | Case accuracy, citation accuracy (re-checked independently), injection flag recall, cost. | `eval.min_*` | LLM-as-judge for readability |
| EVAL-03 Regression in CI | ✅ | Repo and project CI run the tests and `launches all`; project CI runs the eval gate (mock, $0). | `.github/workflows/ci.yml` | Weekly live eval on the local model |
| OBS-01 Run log | ✅ | `audit.ai_calls` (model, prompt hash, input hash, tokens, cost, latency, status, flags), `audit.summaries`, `source_runs`, `ll2_requests`. | — | OpenTelemetry spans |
| OBS-02 Traceability | ✅ | Every accepted summary's citations match the row, every number in it appears in its facts, and outcome and cost claims must agree with the data (tested, golden `s01`, `s04`). Every cost and projection on screen shows its source and date. | `guardrails.check` | Per-sentence source links in the UI |
| OBS-03 Retention | 🟡 | Audit and source-run rows kept in the database file; a personal project, so a one-year window is configured but not yet enforced by a prune job. | `governance.log_retention_days` | Nightly prune |
| HITL-01 Risk tiering | ✅ | `risk_tier: low` with the rationale above. | `risk_tier` | — |
| HITL-02 Human approval | ✅ | Every cost row is used only after a named person approves it against its source (UI and `launches approve`); rejections are recorded too. | `costs.require_approval` | Approval for reference and market rows as well |
| HITL-03 Feedback loop | 🟡 | Reviews are kept and override the file's status; a rejected cost never reappears. Summaries aren't rated yet. | `reference_reviews` | 👍/👎 on summaries feeding the golden set |
| HITL-04 Use-case card | ✅ | See README → *Use-case card*. | `README.md` | — |

## Model migration runbook (MODEL-02/03)

1. Add the model to `config/models.yaml` with pricing (0.0 for a local Ollama model) and `approved: true`.
2. Point `summary-candidate` at it.
3. `launches eval --alias summary-candidate --baseline summary-primary` — must PASS with no regression; read the
   rejected drafts in `output/evals/latest_<model>.json`.
4. `launches promote summary-primary <model>`; commit `models.yaml`.
5. Keep the old model as `summary-fallback` for one cycle, then retire it.
