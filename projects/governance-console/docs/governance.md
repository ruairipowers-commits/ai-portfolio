# Governance mapping — governance-console

Maps every control in the portfolio's [AI governance standard]({{SITE_URL}}/blog/governance/) (copy in [`governance/controls.md`](../governance/controls.md) when published)
to this project. **Status**: ✅ implemented · 🟡 partial / manual · ⚪ not applicable · 🔷 option documented, not built.

The console makes **no model calls**, so most controls apply to it in a second sense: it is where the evidence for
the *other* workflows' controls is collected and reviewed. Each row says both — how the console itself meets the
control (or why it doesn't apply) and what it contributes for the governed workflows.

**Risk tier: Low** (HITL-01). It observes and can switch off the workflows that call models. The one consequential
action — the kill switch — is admin-only, needs a reason and is audited; in the public demo a visitor can switch a
workflow off for ten minutes at most.

| Control | Status | How this project does it | Configure it | Other options (not built here) |
|---|---|---|---|---|
| DATA-01 Source inventory & lineage | ✅ | The catalog is built from `portfolio.yaml`, each spec and each project's governance mapping; every event names its workflow, client version and environment. | `catalog/workflows.json`, `PORTFOLIO_ROOT` | ServiceNow / Collibra AI inventory as the system of record |
| DATA-02 Quality gates before AI | ⚪ | No model calls. Ingest validates every event against a schema (types, ranges, bounded sizes) and rejects the batch otherwise. For the workflows it counts `dq_gate_failed` events. | `ingest.*` | — |
| DATA-03 Minimization & sensitive data | ✅ | The event schema has no field for prompts, questions, documents or answers — only counts, hashes and flags; `detail` is capped. Visitors are pseudonymous ids. | `app.Event` | Field-level allow-list per workflow; PII scan on `detail` |
| DATA-04 Usage rights | ⚪ | Holds no licensed content. Shows each workflow's `licence_excluded` / `entitlement_filtered` counts as evidence. | — | — |
| DATA-05 Retrieval corpus hygiene | ⚪ | No retrieval. Shows index builds (`ingest`, `kb-index` events) for the RAG workflows. | — | — |
| SEC-01 Secrets management | ✅ | Ingest and admin tokens and `DATABASE_URL` come from the environment (Space secrets in the hosted demo); `.env` is git-ignored; tokens are compared in constant time. | `.env.example` | AWS Secrets Manager; rotate tokens per workflow |
| SEC-02 Prompt-injection defense | ⚪ | No model. All event fields are rendered escaped (Jinja autoescape, `textContent` in charts), so a hostile workflow name or flag can't inject script. | — | Content-Security-Policy header |
| SEC-03 Least-privilege tools | ✅ | Workflows get an append-only ingest token and a read-only status endpoint; only an admin can change a switch or attest; demo visitors get time-boxed switch-offs only. Ingest is rate-limited per client. | `GOVERNANCE_INGEST_TOKEN`, `GOVERNANCE_ADMIN_TOKEN`, `ingest.rate_limit_per_minute` | Per-workflow tokens; SSO with a governance role; mTLS between apps and console |
| SEC-04 Output handling | ✅ | Events are parsed with Pydantic (bounded strings, non-negative numbers, workflow-name pattern) before storage; bad batches get 422. | `app.Event` | JSON Schema published for other languages |
| SEC-05 Provider & data residency terms | 🟡 | No provider of its own. The **Models** page lists every workflow's registered models with approval and pricing status — the inventory a provider review starts from. | — | Block events that report an unapproved model |
| SEC-06 Supply chain | 🟡 | Few dependencies, version-bounded; Chart.js vendored with its licence (no CDN at runtime); `pip-audit` in CI (report-only). | `pyproject.toml`, CI | Hash-pinned lockfile; SBOM |
| COST-01 Hard budgets | ⚪ | Budgets are enforced inside each workflow before every call. The console shows the runs those caps stopped (`budget_blocked`, `step_or_budget_cap`). | — | Central spend gateway that refuses calls over budget |
| COST-02 Cost attribution | ✅ | Every event carries model, tokens and cost per workflow, person and run; the dashboards break spend down by workflow, model and person, daily and cumulative. | — | AWS cost-allocation tags reconciled against the invoice |
| COST-03 Efficiency levers | 🟡 | Spend by model per workflow makes tiering decisions visible (the simulated trade-ops promotion to a larger model is the obvious example). | — | Recommendations (e.g. cache hit rate) per workflow |
| COST-04 Alerts & review | ✅ | Trailing-30-day spend vs each workflow's monthly budget with a warning at 80%; spend anomalies (day > 2.5 × trailing 14-day median) on the overview and audit pages. | `config/workflows.yaml`, `alerts.*` | Email / Slack alerts; monthly FinOps sign-off recorded in the console |
| MODEL-01 Registry & aliases | ✅ | Reads each workflow's `config/models.yaml` and shows which aliases point at which model. | — | — |
| MODEL-02 Eval-gated changes | 🟡 | Shows each workflow's latest eval-gate result as evidence; doesn't block promotions itself. | — | Refuse a `register` event whose primary model has no passing eval |
| MODEL-03 Deprecation monitoring | ✅ | The Models page flags models within 90 days of, or past, their deprecation date across all workflows. | `models.yaml` `deprecation_date` | Scrape provider deprecation pages |
| MODEL-04 Prompt versioning | ⚪ | No prompts. Workflows log prompt hashes in their own audit tables. | — | Include prompt hash in events |
| MODEL-05 Fallback & resilience | ✅ | For the console itself: telemetry is sent in the background and spooled locally if the console is down; the kill switch fails open unless a workflow sets `GOVERNANCE_FAIL_CLOSED=1`. | `GOVERNANCE_FAIL_CLOSED` | Replicated console; queue (SQS / Kinesis) in front of ingest |
| EVAL-01 Golden dataset | ⚪ | No model to evaluate. The simulated history is a fixed, seeded scenario the tests assert against (shadow AI, kill-switch day, cost anomaly). | `simulation.*` | — |
| EVAL-02 Metrics & thresholds | ⚪ | No model. Metric definitions (run, escalation, budget use, anomaly) are fixed in `metrics.py` and tested. | — | — |
| EVAL-03 Regression in CI | ✅ | CI runs the tests, including a round trip with the real telemetry client over HTTP, and the portfolio CI checks every workflow's client copy is identical. | `.github/workflows/ci.yml` | — |
| OBS-01 Run log | ✅ | The events table *is* the cross-workflow run log: who, what, model, tokens, cost, latency, records, outcome, flags. | — | OpenTelemetry export to Datadog / Grafana |
| OBS-02 Traceability | 🟡 | Events carry `run_id`, so a console row links to the workflow's own audit trail (memo, trajectory, answer log). | — | Deep links into each app's audit view |
| OBS-03 Retention | 🟡 | Live events kept indefinitely in Postgres; the hosted demo's SQLite is wiped when the Space sleeps unless `DATABASE_URL` is set. AWS path: S3 with Object Lock. | `retention.live_events_days`, `DATABASE_URL` | WORM storage; scheduled purge job |
| HITL-01 Risk tiering | ✅ | Every workflow's tier comes from its spec and is shown on every page; self-declared tiers from unregistered sources are labelled as such. | `specs/<slug>.yaml` | Tier-driven required-control checks |
| HITL-02 Human approval | ✅ | Switching a workflow off or on needs an admin and a reason; every change is in the audit log. Demo visitors' switch-offs lapse after 10 minutes. | `kill_switch.*` | Two-person rule for switching a high-risk workflow back on |
| HITL-03 Feedback loop | ✅ | Reviewer overrides, edits and "wrong" ratings from every workflow are counted per workflow; attestations record a reviewer's confirmation or exception per control. | `attestation.stale_after_days` | Auto-open an issue for each exception |
| HITL-04 Use-case card | ✅ | See README → *Use-case card*. Each governed workflow's card is in its own README. | `README.md` | — |
