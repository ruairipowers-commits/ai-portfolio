# Governance mapping — editorial-agents

Maps every control in the portfolio's [AI governance standard]({{SITE_URL}}/blog/governance/) to this project.
**Status**: ✅ implemented · 🟡 partial / manual · ⚪ not applicable · 🔷 option documented, not built.

**Risk tier: Medium** (HITL-01). It publishes AI-drafted writing under the owner's name, so accuracy, plagiarism and
reputation are the risks, and the subscription half stores and emails real people's addresses. No money, advice or
personal data beyond an email address. The deciding control: **a human merge is the only way a post is published**,
and the demo host holds no write credentials to the blog repo.

| Control | Status | How this project does it | Configure it | Other options (not built here) |
|---|---|---|---|---|
| DATA-01 Source inventory & lineage | ✅ | Every source is declared in one place (official APIs and named RSS feeds). Each topic keeps its source, link, date and signals; each post's PR names its topic id, and the scout links topic → PR → published post. | `sources.*`, `config/feeds.yaml` | Archive each fetched response for audit |
| DATA-02 Quality gates before AI | ✅ | Candidates are de-duplicated (canonical URL, near-identical titles), expired after 21 days, and screened for injection before any model call. A dead source is reported in the email, not silently skipped. | `queue.max_age_days` | Per-source freshness alerts |
| DATA-03 Minimization & sensitive data | ✅ | The scout reads public titles and summaries only. Subscribers: email address only, double opt-in, unconfirmed deleted after 7 days, unsubscribe deletes the row; addresses never in logs, links or telemetry. | `subscriptions.*` (site assistant) | — |
| DATA-04 Usage rights | ✅ | Official APIs and public feeds within their terms (rate-limited, identified user agent); LinkedIn excluded (no API, terms forbid scraping). Posts link to sources and summarise in their own words: the editor checklist fails any run of more than 25 words copied from a source, or more than 60 quoted words. | `review.max_verbatim_run_words`, `review.max_quoted_words` | Licence check per feed |
| DATA-05 Retrieval corpus hygiene | ✅ | Novelty is measured against the live site's published-post list (`assistant/corpus.json`), regenerated on every site build, so deleted posts drop out. | `EDITORIAL_CORPUS` | Embedding index instead of TF-IDF |
| SEC-01 Secrets management | ✅ | The link-signing secret, SMTP and Reddit credentials come from the environment; the live image refuses to start without the signing secret. No model API key on the host (the writer runs on the owner's Claude plan). | `.env` on the host | Secret manager |
| SEC-02 Prompt-injection defense | ✅ | Every fetched title and summary is untrusted: a pattern screen escalates instruction-like text before classification (golden case g1), the classifier sees candidates only inside delimiters with a "data, not instructions" rule, and the writer and editor prompts say the same of topics and sources. | `guard.PATTERNS` | A classifier model on fetched text |
| SEC-03 Least-privilege tools | ✅ | The scout only reads. The owner's email links can only pick, unpick or dismiss a topic, signed, expiring and single-use, applied by a POST from a confirmation page (mail scanners follow GETs). The writer can push a branch and open a PR, never merge. | `links.ttl_days` | — |
| SEC-04 Output handling | ✅ | The classifier's JSON is schema-validated (sectors must be real GICS sectors, interest 1–5, a known kind); anything invalid falls back to the deterministic classifier and is flagged. All page output is HTML-escaped. | `llm.validate` | — |
| SEC-05 Provider & data residency terms | ✅ | The scout's model is local (Ollama on the owner's server) or the offline mock; only approved models in the registry can run. The writer and editor run on the owner's Claude plan. | `config/models.yaml` | — |
| SEC-06 Supply chain | 🟡 | Four version-bounded dependencies; CI checks the image has every library the code imports, and the repo's security scan audits dependencies. | `pyproject.toml` | Lockfile with hashes |
| COST-01 Hard budgets | ✅ | A per-run cap on classifier calls stops the run (and flags it) instead of looping; tested. The local model is $0 per token. | `cost.max_model_calls_per_run` | Spend cap for a paid model |
| COST-02 Cost attribution | ✅ | Each scout run reports model, calls, latency and counts to the governance console. | telemetry | — |
| COST-03 Efficiency levers | ✅ | Each topic is classified once and cached; ranking and novelty are code, not model calls; search sources are free APIs. | — | Batch classification |
| COST-04 Alerts & review | 🟡 | Budget stops and fallbacks are flagged to the console; the weekly email shows how many sources were read. | console escalation rules | Monthly cost report |
| MODEL-01 Registry & aliases | ✅ | Code asks for the `classifier` alias; the registry maps it to a model, with a fallback and a candidate alias. | `config/models.yaml`, `EDITORIAL_CLASSIFIER_MODEL` | — |
| MODEL-02 Eval-gated changes | ✅ | `editorial eval --alias classifier-candidate` runs the golden set; a model is only promoted if the gate passes. Writer and editor prompt changes go through a PR like any code. | `evals/golden_set.yaml` | Judge-model regression on golden drafts |
| MODEL-03 Deprecation monitoring | ⚪ | Local open-weight models aren't retired by a provider; the writer uses whatever Claude model the owner's plan provides. | — | Track the Ollama library for newer versions |
| MODEL-04 Prompt versioning | ✅ | Prompts are versioned files (`classify.v1`, `writer.v1`, `editor.v1`); the classifier's prompt hash is stored with every topic it tagged. | `prompts/` | — |
| MODEL-05 Fallback & resilience | ✅ | Invalid output or a model outage falls back to the deterministic classifier (flagged); a dead source is skipped and reported; the scheduler survives errors. | `classifier-fallback` | — |
| EVAL-01 Golden dataset | ✅ | Scout cases on recorded source fixtures (an injection attempt, a near-copy of a published post) and editor cases: drafts with one planted fault each (copied text, client framing, hype words without sources, a near-duplicate) plus a clean draft. | `evals/` | More golden drafts from real editor findings |
| EVAL-02 Metrics & thresholds | ✅ | Must-catch recall 1.0 on planted faults; the clean draft passes; queue full and no two topics above the similarity limit. The editor agent scores five judged criteria and a PR without ≥ 4 on each is labelled `needs-work`. | `review.*`, `queue.max_similarity` | — |
| EVAL-03 Regression in CI | ✅ | `pytest` (including the eval gate) runs on every push; the site build checks the governance mapping. | `.github/workflows/ci.yml` | Live-source smoke test on a schedule |
| OBS-01 Run log | ✅ | Every scout, email, sync and re-rank is a row in `runs`; every owner action in `actions`; counts and flags go to the console. | — | — |
| OBS-02 Traceability | ✅ | Every post cites its sources, and the topic id ties the PR to the topic and its original link. The editor's scorecard is kept in the PR. | — | — |
| OBS-03 Retention | 🟡 | Topics and runs are kept in SQLite on the host, in the nightly backup; PRs and their scorecards are kept in GitHub. | — | Retention policy for old topics |
| HITL-01 Risk tiering | ✅ | Medium, with rationale (above and in the spec). | `risk_tier` | — |
| HITL-02 Human approval | ✅ | Topics are picked by the owner (signed links, recorded); nothing publishes without the owner merging the PR; the host has no write access to the repo. | — | — |
| HITL-03 Feedback loop | ✅ | Dismissed and withheld topics are recorded; editor findings and the owner's edits on a PR are the source of new golden drafts. | `evals/drafts/` | Automatic golden-draft capture |
| HITL-04 Use-case card | ✅ | README use-case card; every post says it was drafted with AI agents and approved by the owner (a checklist item). | `review.disclosure` | — |

## Model migration runbook (MODEL-02/03)

1. Point `classifier-candidate` at the new model in `config/models.yaml` (approved: true).
2. `editorial eval --alias classifier-candidate` — the gate must pass.
3. Point `classifier` at it (or set `EDITORIAL_CLASSIFIER_MODEL`) and redeploy; watch fallbacks in the console.
