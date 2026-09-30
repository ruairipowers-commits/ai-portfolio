<!--
  SOURCE OF TRUTH for the AI governance control catalog.
  - Every project's docs/governance.md must map EVERY control ID below
    (scripts/check_governance.py enforces this).
  - To add/rename a control, edit this file; the blog post and all
    project checks pick it up automatically.
  - Row format must stay: | ID | Control | Requirement | Evidence expected |
-->

### Data preparation & quality

| ID | Control | Requirement | Evidence expected |
|---|---|---|---|
| DATA-01 | Source inventory & lineage | Every input source has an owner, refresh cadence and documented lineage from raw to AI input. | dbt sources + lineage graph; source table in README |
| DATA-02 | Quality gates before AI | Automated data tests (nulls, uniqueness, ranges, freshness) must pass before any model call; failures block the run. | Test suite + gate code that reads test results |
| DATA-03 | Minimization & sensitive data | Only fields needed for the task reach the model; PII / MNPI is classified and redacted or excluded. | Payload builder, redaction code, tests |
| DATA-04 | Usage rights | Data licenses / terms permit processing by third-party AI providers and derived use. | License flag checked in pipeline or policy |
| DATA-05 | Retrieval corpus hygiene | For RAG: chunking, de-duplication, provenance metadata and re-index policy are defined and versioned. | Indexing config + index version in run log |

### AI security

| ID | Control | Requirement | Evidence expected |
|---|---|---|---|
| SEC-01 | Secrets management | No keys in code or logs; secrets from env/secret manager; rotation path documented. | `.env.example`, secret-manager option |
| SEC-02 | Prompt-injection defense | Untrusted content is delimited, scanned and never allowed to change instructions or tool permissions. | Sanitizer + injection test cases |
| SEC-03 | Least-privilege tools | Agent tools are read-only by default; any write/side effect needs explicit approval. | Tool allow-list; approval step |
| SEC-04 | Output handling | Model output is schema-validated and treated as data — never executed or trusted blindly. | Pydantic/JSON-schema validation, repair/fallback path |
| SEC-05 | Provider & data residency terms | Only approved providers/regions; zero-retention / no-training settings where available. | Provider allow-list in model registry |
| SEC-06 | Supply chain | Dependencies pinned, scanned; model provenance recorded. | Lockfile, CI scan, model IDs in registry |

### Cost oversight

| ID | Control | Requirement | Evidence expected |
|---|---|---|---|
| COST-01 | Hard budgets | Per-call token caps and per-run spend caps that stop execution when exceeded. | Budget guard + test |
| COST-02 | Cost attribution | Tokens and cost logged per call, run, use case and model. | Call log table + cost report |
| COST-03 | Efficiency levers | Right-size models (tiering), cache, batch, and trim context before scaling spend. | Config options + measured effect |
| COST-04 | Alerts & review | Monthly thresholds with alerts and a named reviewer. | Threshold config + report command |

### Model lifecycle & migration

| ID | Control | Requirement | Evidence expected |
|---|---|---|---|
| MODEL-01 | Registry & aliases | Code references aliases, never raw model IDs; the registry holds provider, ID, pricing, deprecation date. | `models.yaml` |
| MODEL-02 | Eval-gated changes | Any model or prompt change must pass the eval suite (and not regress vs baseline) before promotion. | Eval gate + promote command |
| MODEL-03 | Deprecation monitoring | Provider deprecation dates tracked with warning window and a migration runbook. | Check command + runbook |
| MODEL-04 | Prompt versioning | Prompts live in versioned files; prompt hash recorded on every call. | `prompts/` + hash in log |
| MODEL-05 | Fallback & resilience | Retries plus a fallback model/provider for outages; degraded mode is explicit. | Fallback alias + retry code |

### Evaluation & quality

| ID | Control | Requirement | Evidence expected |
|---|---|---|---|
| EVAL-01 | Golden dataset | A labeled set of representative and adversarial cases with expected outcomes. | `evals/` folder |
| EVAL-02 | Metrics & thresholds | Task accuracy, format validity, grounding/citation accuracy and safety metrics with pass thresholds. | Threshold config + eval report |
| EVAL-03 | Regression in CI | Evals run automatically on every change (offline/mock in CI, live on schedule). | CI workflow |

### Observability & audit

| ID | Control | Requirement | Evidence expected |
|---|---|---|---|
| OBS-01 | Run log | Each call logs model, prompt version, input hash, tokens, latency, cost, outcome. | Audit tables |
| OBS-02 | Traceability | Every AI claim traces to source data (citations checked against the source). | Citation check |
| OBS-03 | Retention | Logs retained per books-and-records policy; access controlled. | Retention setting / storage option |

### Human oversight & accountability

| ID | Control | Requirement | Evidence expected |
|---|---|---|---|
| HITL-01 | Risk tiering | Each use case is tiered (low/medium/high); the tier sets required controls and approvals. | `risk_tier` in config + rationale |
| HITL-02 | Human approval | Consequential decisions/actions require a named human approver. | Review step / approval queue |
| HITL-03 | Feedback loop | Reviewer overrides are captured and fed back into evals. | Review log + eval ingestion |
| HITL-04 | Use-case card | Intended use, limits, owners and known failure modes are documented. | Use-case card in README |
