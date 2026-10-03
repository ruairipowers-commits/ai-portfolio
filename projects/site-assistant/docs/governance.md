# Governance mapping — site-assistant

Maps every control in the portfolio's [AI governance standard]({{SITE_URL}}/blog/governance/) to this project.
**Status**: ✅ implemented · 🟡 partial / manual · ⚪ not applicable · 🔷 option documented, not built.

**Risk tier: Low** (HITL-01). It answers questions about public blog content, takes no actions and holds no
private data beyond what visitors type. Two risks remain. It could make a wrong statement about a real person
(including "is he a fit for this role"). And it is a public text box, open to prompt injection and abuse. So it
answers only from cited excerpts, it has budgets and rate limits, and the governance console can switch it off.

| Control | Status | How this project does it | Configure it | Other options (not built here) |
|---|---|---|---|---|
| DATA-01 Source inventory & lineage | ✅ | One source: the published blog's `search/search_index.json`. `index_runs` records each refresh (source, passages, pages, status), and every passage keeps its page URL and section. | `index.source`, `SITE_INDEX` | Sitemap crawl; per-page content hashes |
| DATA-02 Quality gates before AI | 🟡 | A refresh that yields no passages is rejected and the last good index keeps serving. Tiny sections, search and pagination pages are dropped. | `index.min_words` | Validate the index schema; alert on a sharp drop in pages |
| DATA-03 Minimization & sensitive data | ✅ | IP addresses and cookies are never stored. The visitor key is a hash of a daily-rotating salt, IP and browser. Searches and questions are kept as typed because the owner asked to see them. The console receives only lengths and hashes. | `privacy.*`, `ASSISTANT_SALT` | Redact emails/phone numbers typed into questions; opt-out banner |
| DATA-04 Usage rights | ⚪ | All content is the author's own published blog. | — | — |
| DATA-05 Retrieval corpus hygiene | ✅ | Rebuilt from the live site every hour, so deleted pages disappear. Sections are split into ≤ 180-word passages, with at most two passages per page in results. | `index.refresh_minutes` | Versioned index snapshots |
| SEC-01 Secrets management | ✅ | Tokens come only from the environment (SMTP, Cloudflare, GitHub, admin). The model is local, so there's no model API key. | `.env` on the host | Secrets Manager |
| SEC-02 Prompt-injection defense | ✅ | Excerpts are wrapped as delimited data, and the system prompt says to ignore instructions inside them. Questions with injection patterns are flagged (`injection_suspected`) and reported. The model has no tools, so it can only write text. The golden set includes an injection case. | `prompts/answer.md`, `llm.INJECTION` | An LLM classifier (Llama Guard) on questions and answers |
| SEC-03 Least-privilege tools | ✅ | No tools. The service reads the public index. The GitHub token needs read-only Administration, the Cloudflare token read-only Analytics. The service holds only an append-only ingest token for the console. | token scopes | — |
| SEC-04 Output handling | ✅ | The widget escapes all model text and allows only bold, quotes and citation links built from the server's own source list. No HTML from the model reaches the page. | `widget.js` | Answer-level PII scan |
| SEC-05 Provider & data residency terms | ✅ | Questions never leave the owner's server: the model runs locally in Ollama. | `OLLAMA_URL` | — |
| SEC-06 Supply chain | 🟡 | Four version-bounded Python dependencies, no front-end dependencies. Model weights are pulled by name from the Ollama library. | `pyproject.toml`, `OLLAMA_MODEL` | Pin the model by digest; `pip-audit` |
| COST-01 Hard budgets | ✅ | Per-visitor limits (searches and questions per hour), a daily cap on questions and a daily token budget. Past them, answering stops and search keeps working. | `limits.*`, `cost.daily_budget_tokens` | Per-country or ASN limits at Cloudflare |
| COST-02 Cost attribution | ✅ | Every answer logs its model and tokens, locally and to the console. Cost is $0 per token on the local model. | `cost.usd_per_1k_tokens` | Electricity estimate per token |
| COST-03 Efficiency levers | 🟡 | Search answers instantly with no model. The model sees six excerpts, not whole pages, and the answer length is capped. | `chat.top_k`, `chat.max_answer_tokens` | Cache answers to repeated questions |
| COST-04 Alerts & review | ✅ | The daily engagement email shows questions and searches against a 7-day average. The console's escalation rules cover budget stops and injection flags. | `digest.*`, console Settings | — |
| MODEL-01 Registry & aliases | ✅ | Code asks for the `chat` alias, and `config/models.yaml` maps it to a model. The extractive fallback is registered too. | `config/models.yaml`, `OLLAMA_MODEL` | — |
| MODEL-02 Eval-gated changes | 🟡 | `siteassist eval` runs the retrieval golden set with a hit-rate gate. Answer quality with a new model is reviewed by hand. | `evals/golden_set.yaml` | LLM-as-judge faithfulness eval on a fixed question set |
| MODEL-03 Deprecation monitoring | ⚪ | Open-weight local models don't get retired by a provider. | — | Track the Ollama library for newer versions |
| MODEL-04 Prompt versioning | ✅ | The prompt is a file in git (`prompts/answer.md`), so every change is a reviewed commit. | `prompts/` | Log the prompt hash per answer |
| MODEL-05 Fallback & resilience | ✅ | If the model is missing, still downloading or fails mid-answer, the service quotes the best passages instead (status `fallback`). Search doesn't depend on the model. | — | A second, smaller local model |
| EVAL-01 Golden dataset | ✅ | 16 retrieval cases covering projects, technologies, the About page, fit questions, release notes and an injection. | `evals/golden_set.yaml` | — |
| EVAL-02 Metrics & thresholds | ✅ | hit@6 ≥ 0.9 (measured 1.00 on the current blog). Tests check citations, the profile-first rule for fit questions, fallback, limits and the kill switch. | `gate.hit_rate` | Answer faithfulness and refusal accuracy |
| EVAL-03 Regression in CI | ✅ | The portfolio CI runs the tests (with a stand-in Ollama) on every push. | `.github/workflows/ci.yml` | Run `siteassist eval` against the built site in CI |
| OBS-01 Run log | ✅ | `activity` holds every page view, search and question, with model, tokens, latency and status. The console gets one event per search and question. | `privacy.retention_days` | — |
| OBS-02 Traceability | ✅ | Each answer streams its source list first, and citations link to the exact page section. The owner's `/stats` page shows every question. | — | Store the answer text alongside the question |
| OBS-03 Retention | ✅ | Activity older than `retention_days` (365) is deleted at every index refresh. Daily metrics are kept as aggregates. | `privacy.retention_days` | — |
| HITL-01 Risk tiering | ✅ | Low, with the rationale above. Fit questions get a balanced, cited answer that names what the blog doesn't show. | `risk_tier` | — |
| HITL-02 Human approval | ⚪ | Answers are informational and nothing is executed. Its own kill switch is in the governance console. | — | — |
| HITL-03 Feedback loop | 🟡 | The daily email lists searches with no results and the questions asked, which become new posts or golden cases. | `digest.top_n` | 👍/👎 on each answer |
| HITL-04 Use-case card | ✅ | See README → *Use-case card*. | `README.md` | — |
