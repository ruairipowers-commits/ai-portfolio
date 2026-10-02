# Governance mapping — research-qa-rag

Maps every control in the portfolio's [AI governance standard]({{SITE_URL}}/blog/governance/) (copy in [`governance/controls.md`](../governance/controls.md) when published)
to this project. **Status**: ✅ implemented · 🟡 partial / manual · ⚪ not applicable · 🔷 option documented, not built.

**Risk tier: Medium** (HITL-01). Answers inform research; nothing trades, sends or changes data. The risks are
wrong numbers presented as fact, licensed research reaching people without a licence, and licence terms that
forbid AI processing — so grounding, entitlements and licences are enforced in code, not in the prompt.

| Control | Status | How this project does it | Configure it | Other options (not built here) |
|---|---|---|---|---|
| DATA-01 Source inventory & lineage | ✅ | `data/corpus/manifest.yaml` lists every document with source, company, date, entitlement and licence; `documents` stores the file hash; every chunk carries document, page and section. | `corpus_dir`, manifest | Document management system as source of truth; OpenLineage events per ingest |
| DATA-02 Quality gates before AI | ✅ | Ingest refuses documents it can't parse, drops empty and tiny chunks, and `ask` refuses to run without an index or on an index built with a different embedding model. | `ingest.min_chunk_words` | Parse-quality checks (OCR confidence, table extraction) with a human review queue |
| DATA-03 Minimization & sensitive data | ✅ | Emails and phone numbers are redacted before indexing (8 in the sample broker notes). The model sees only the top-k excerpts. Governance telemetry carries a hash of the question, never its text. | `ingest.redact_pii`, `retrieval.top_k` | Presidio / Comprehend PII; MNPI watch-list screening at ingest |
| DATA-04 Usage rights | ✅ | Each document has a licence and an `ai_processing` flag. Barred documents are keyword-indexed (the analyst may read them) but never embedded and never sent to a model; refusals explain this. The Kestrel note is the test case. | manifest `ai_processing` | Licence terms pulled from the research-entitlement system (e.g. a vendor-management database) |
| DATA-05 Retrieval corpus hygiene | ✅ | Chunking config (90 words, 20 overlap, page-bounded), boilerplate dedup within an entitlement, quarantine, incremental re-index by file hash, `index_runs` history, and the index version on every answer. | `ingest.*` | Blue/green index with rollback; scheduled freshness checks per source |
| SEC-01 Secrets management | ✅ | Keys only from the environment; `.env` git-ignored; Bedrock via IAM role. The hosted demo has no keys at all. | `.env.example` | AWS Secrets Manager; OIDC in CI |
| SEC-02 Prompt-injection defense | ✅ | Two screens: paragraphs with instruction-like text are quarantined at ingest, and retrieved chunks are screened again before the prompt. Excerpts are escaped and wrapped in `<excerpt>` tags; the prompt says they are data. The Aldgate note's hidden white text is the live case. | `ingest.quarantine_suspicious`, `guardrails.INJECTION_PATTERNS` | LLM-based classifier (Llama Guard, Bedrock Guardrails prompt-attack filter); rendering PDFs and comparing visible vs extracted text |
| SEC-03 Least-privilege tools | ✅ | The model has no tools; retrieval is code. The API takes identity from a header limited to known personas; entitlements are looked up server-side, never taken from the request. | `config/users.yaml` | SSO (IAM Identity Center / Entra ID) groups → entitlements; row-level security in the store |
| SEC-04 Output handling | ✅ | Pydantic schema; off-contract output becomes a refusal (`invalid_output`); answers are rendered as text. | `guardrails.Answer` | Provider structured outputs; repair prompt |
| SEC-05 Provider & residency terms | ✅ | Registry `approved:` flag for answer and embedding models (OpenAI entries ship disabled). Bedrock keeps traffic in-region. | `config/models.yaml` | Zero-retention agreements; VPC endpoints |
| SEC-06 Supply chain | 🟡 | Version-bounded deps; `pip-audit` in CI (report-only); embedding model IDs recorded per index. | `pyproject.toml`, CI | Hash-pinned lockfile; SBOM; Dependabot |
| COST-01 Hard budgets | ✅ | Pre-flight per question: token cap, worst-case cost vs `max_usd_per_question`, refusal of unpriced models (test: an unpriced Claude alias is blocked). | `cost.*` | Gateway budgets per team (LiteLLM proxy) |
| COST-02 Cost attribution | ✅ | `answers` stores tokens and $ per question, user, model, prod vs eval; `cost-report`; governance events per question. | — | Langfuse / Helicone dashboards |
| COST-03 Efficiency levers | 🟡 | top-k trims context; refusals before any model call when nothing is retrieved; model tiering by alias. Embeddings are computed once per document version (incremental re-index). | `retrieval.top_k`, aliases | Prompt caching of the system prompt; semantic answer cache; batch re-embedding |
| COST-04 Alerts & review | ✅ | `cost-report` flags months over the alert; the governance hub charts daily and cumulative spend against the monthly budget. | `cost.monthly_alert_usd` | AWS Budgets alerts; FinOps review |
| MODEL-01 Registry & aliases | ✅ | `answer-primary/fallback/candidate` and `embed-primary` aliases; code never names a model. | `config/models.yaml` | MLflow registry; LiteLLM router |
| MODEL-02 Eval-gated changes | ✅ | `eval --alias answer-candidate --baseline answer-primary` fails on thresholds or regression; `promote` refuses without a passing eval on the current prompt hash **and index version**. | `eval.*` | Shadow traffic; analyst blind comparison |
| MODEL-03 Deprecation monitoring | 🟡 | `models-check` warns inside the window. Embedding deprecations force a full re-index — runbook below. | `governance.deprecation_warning_days` | Provider deprecation feed alerts |
| MODEL-04 Prompt versioning | ✅ | `prompts/answer.v1.md`; prompt hash on every answer and eval report. | `llm.prompt_file` | Prompt registry |
| MODEL-05 Fallback & resilience | ✅ | Retries then `answer-fallback`; `used_fallback` logged. An index/embedding mismatch fails closed with a clear message. | `llm.fallback_alias`, `llm.retries` | Cross-provider fallback; keyword-only degraded mode |
| EVAL-01 Golden dataset | ✅ | 21 questions: filings, transcripts, entitled broker notes, a not-entitled case, a licence-barred case, hidden instructions, two no-answer cases. | `evals/golden_set.yaml` | Synthetic question generation per new document |
| EVAL-02 Metrics & thresholds | ✅ | Answer and refusal accuracy, citation accuracy, faithfulness, context recall, entitlement leaks (must be 0), injection resisted, p95 latency, cost; plus recall@k / MRR per retrieval mode. | `eval.*` | LLM-judged faithfulness and answer relevance (RAGAS) on a sample |
| EVAL-03 Regression in CI | ✅ | Tests + ingest + eval gate on every push (mock, $0). | `.github/workflows/ci.yml` | Scheduled live eval with a real model |
| OBS-01 Run log | ✅ | `answers` (who, question, outcome, model, prompt hash, index version, filters, tokens, latency, cost, flags) and `index_runs`. | — | OpenTelemetry GenAI spans → Langfuse / Datadog |
| OBS-02 Traceability | ✅ | Every answer cites document + page; each quote must match the retrieved text word for word and the answer must be ≥ 90% supported, or it is refused. The retrieval trace shows why each chunk was chosen. | `answer.min_supported_ratio` | Highlighting the quote on the rendered PDF page |
| OBS-03 Retention | 🟡 | Local SQLite (no expiry); AWS path sets S3 versioning + log retention. | `governance.log_retention_days` | S3 Object Lock (WORM) for research records |
| HITL-01 Risk tiering | ✅ | `risk_tier: medium` with rationale above. | `risk_tier` | — |
| HITL-02 Human approval | 🟡 | Advisory only: no action is taken on an answer; analysts verify the cited page. Adding a document is logged with who added it. | — | Librarian approval before new sources go live |
| HITL-03 Feedback loop | ✅ | 👍/👎 per answer stored in `feedback`; "wrong" answers are golden-set candidates. | — | Auto-open a PR adding the case to `golden_set.yaml` |
| HITL-04 Use-case card | ✅ | See README → *Use-case card*. | `README.md` | — |

## Model migration runbook (MODEL-02/03)

**Answer model**

1. Add the model to `config/models.yaml` with pricing and `approved: true`; point `answer-candidate` at it.
2. `rqa eval --alias answer-candidate --baseline answer-primary` — must pass with no regression.
3. `rqa promote answer-primary <model>`; keep the old one as `answer-fallback` for a cycle.

**Embedding model** (every vector changes)

1. Add the model (`kind: embedding`, `dimensions`), approve it, point `embed-primary` at it.
2. `rqa ingest --full` builds a new index version with the new embeddings. Until then, `ask` refuses: the index
   and the embedding alias disagree.
3. `rqa compare-retrieval` and `rqa eval` on the new index; compare recall@k / MRR with the previous report.
4. If it regresses, point `embed-primary` back and re-index.
