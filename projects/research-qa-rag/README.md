# research-qa-rag

**Ask questions of filings, earnings calls and broker research, and get answers that cite the page they came from.**
If the documents you're entitled to don't support an answer, it refuses rather than guessing. Licensed broker notes
stay with the people who hold the licence, and notes whose licence forbids AI processing never reach a model.

> Part of the [AI Workflow Portfolio]({{SITE_URL}}) by Ruairi Powers ·
> Write-up: [{{BLOG_TITLE}}]({{SITE_URL}}/blog/research-qa-rag/) · Live demo: [Hugging Face Space](https://huggingface.co/spaces/{{HF_OWNER}}/research-qa-rag) ·
> Governance: [standard]({{SITE_URL}}/blog/governance/) / [this project's mapping](docs/governance.md)

![python](https://img.shields.io/badge/python-3.11-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-service-teal) ![hybrid search](https://img.shields.io/badge/search-BM25%20%2B%20vectors-purple) ![runs offline](https://img.shields.io/badge/runs-offline%20by%20default-green)

## What it does

Analysts spend hours re-reading 10-Ks, transcripts and broker notes to answer one question, and answers given from
memory have no source. Licensed broker research makes it worse: who may read a note, and whether its licence even
allows an AI to process it, differs by document.

For each question the service:

1. **Filters first.** Only chunks the analyst is entitled to, from documents whose licence allows AI processing,
   are candidates. The filter is in the SQL of both retrievers, so restricted text is never ranked, fused or sent.
2. **Retrieves hybrid.** BM25 keyword search (SQLite FTS5) and vector search (sqlite-vec), fused with reciprocal
   rank fusion. Exact financial terms and paraphrases both land.
3. **Drafts** an answer with a model chosen by alias, inside a per-question budget.
4. **Verifies in code.** Every citation must quote a retrieved excerpt word for word, and the answer's numbers and
   words must be supported by those quotes. Anything else becomes a refusal with the reason.

At ingest, PDFs and HTML are parsed page by page. Emails and phone numbers are redacted, repeated boilerplate is
stored once, and any paragraph containing instruction-like text is quarantined. The index is incremental and
versioned, and every answer records the index version it used.

On the 21-question golden set the offline run gets:

| Metric | Result | Gate |
|---|---|---|
| Answer accuracy (17 answerable) | 1.00 | ≥ 0.90 |
| Refusal accuracy (4: not entitled, licence-barred, 2 not in corpus) | 1.00 | 1.00 |
| Citation accuracy / faithfulness / context recall | 1.00 / 1.00 / 1.00 | ≥ 0.95 / 0.90 / 0.90 |
| Entitlement leaks | 0 | 0 |
| Hidden-instruction note: injected claims in the answer | none | none |
| p95 latency · total cost (simulated pricing) | 8 ms · $0.025 | ≤ 8 s · ≤ $0.50 |

| Retrieval mode | recall@5 | MRR |
|---|---|---|
| BM25 only | 1.000 | 0.931 |
| Vector only (offline hash embeddings) | 1.000 | 0.926 |
| **Hybrid (RRF)** | 1.000 | **0.961** |

These numbers come from a deterministic **extractive mock**, not an LLM. It quotes one sentence and never invents
text, so faithfulness is 1.0 by construction. They show the pipeline and controls work; they say nothing about
how a real model would score. Run the same gate with Claude or Bedrock to find out (below).

## Quickstart (5 minutes, no API keys)

```bash
git clone <this repo> && cd research-qa-rag
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ui,dev]"

rqa all                      # corpus → index → retrieval comparison → four sample questions
rqa ask "What is Northbridge's price target on Halvorsen Robotics?" --user equity-analyst
rqa ask "What is Northbridge's price target on Halvorsen Robotics?" --user public-analyst   # refused
rqa eval                     # golden-set gate
rqa ui                       # browser app (http://localhost:8501)
rqa serve                    # FastAPI on :8000, OpenAPI docs at /docs
pytest -q                    # 29 tests incl. the app (headless) and the API
```

### The app

![Ask tab: cited answer with the retrieval trace](docs/img/app.png)

`rqa ui` has five tabs (full guide: [docs/app-guide.md](docs/app-guide.md), also in the app):

- **💬 Ask** — pick an analyst (entitlements) and a question, or one of the 21 golden examples → **Ask** → a cited
  answer or a refusal. Below it are the retrieval trace (BM25 rank, vector rank, fused score), the exact excerpts
  sent to the model, the sentence-by-sentence verification, and 👍/👎 feedback.
- **🧨 Try to break it** — add a broker note with hidden white-text instructions, or one whose licence forbids AI,
  or upload a PDF; see what ingest quarantines, then ask about it.
- **📚 Corpus & index** — every document with entitlement, licence, chunks, quarantine and redactions; the rendered
  page next to the chunks retrieval sees; index versions; incremental or full re-index.
- **📏 Evals & audit** — the eval gate, the retrieval comparison, the answer log, cost by model, feedback.
- **📘 Guide** — what every control does.

![Try to break it: the hidden-instruction paragraph is quarantined](docs/img/break-it.png)

### Use a real model

```bash
pip install -e ".[anthropic]"            # or [aws] for Bedrock, [openai]
cp .env.example .env                     # ANTHROPIC_API_KEY=...
# config/models.yaml: add pricing for claude-sonnet; set answer-candidate: claude-sonnet
rqa eval --alias answer-candidate --baseline answer-primary
rqa promote answer-primary claude-sonnet
```

Switching embeddings (e.g. Titan v2) changes every vector: point `embed-primary` at the model, `rqa ingest --full`,
then `rqa compare-retrieval` and `rqa eval`. Until you re-index, questions are refused because the index and the
embedding alias disagree.

## Requirements

**Functional**

| ID | Requirement |
|---|---|
| FR-1 | Ingest PDFs/HTML with source, page, licence and entitlement metadata; incremental, versioned re-index |
| FR-2 | Answer with citations to document and page, each quote verified against the source |
| FR-3 | Refuse when the accessible evidence is insufficient |
| FR-4 | Filter retrieval by user entitlements before ranking |
| FR-5 | Exclude documents whose licence forbids AI processing; quarantine chunks with hidden instructions |
| FR-6 | Capture analyst feedback per answer |

**Non-functional**

| ID | Requirement | Target |
|---|---|---|
| NFR-1 | Latency | p95 < 8 s per answer |
| NFR-2 | Grounding | faithfulness ≥ 0.9, citation accuracy ≥ 0.95 |
| NFR-3 | Entitlement leakage | 0 restricted chunks ever reach the model |
| NFR-4 | Re-index | incremental by file hash; every answer records its index version |
| NFR-5 | Portability | offline in < 5 min with no keys; Anthropic / OpenAI / Bedrock by alias |

## Use-case card (HITL-04)

| | |
|---|---|
| **Intended use** | Find and quote what filings, transcripts and licensed research say, with the page to check. |
| **Not for** | Investment recommendations of its own, trading decisions, documents with MNPI, research the user isn't licensed for. |
| **Risk tier** | Medium. See the [governance mapping](docs/governance.md). |
| **Owner** | Head of research (business) · Research engineering (technical) |
| **Known limits** | Regex screening catches common injection phrasing, not all of it. Entitlements come from a persona list here, not SSO. The offline embeddings are lexical, not semantic. Tables and charts in PDFs aren't parsed. Page citations depend on page-bounded chunks. |

## Architecture

See [docs/architecture.md](docs/architecture.md) for the flow, the sequence diagram, the data model and the
design decisions; [docs/aws-native.md](docs/aws-native.md) for the Bedrock Knowledge Bases version.

```
config/      settings.yaml (chunking, retrieval, budgets, eval gates) · models.yaml (answer + embedding aliases) · users.yaml
prompts/     answer.v1.md
scripts/     generate_corpus.py (5 fictional companies: 5 annual reports, 3 transcripts, 4 broker notes)
src/research_qa/
  ingest.py     parse → redact → dedup → screen → chunk → embed → index (incremental, versioned)
  retrieve.py   BM25 + vector with the entitlement/licence filter in SQL, RRF fusion, runtime screen
  answer.py     prompt → model (budget, fallback) → verify citations + support → log
  guardrails.py injection patterns, PII redaction, output schema, verification
  evals.py      golden-set gate + retrieval comparison
  api.py        FastAPI: /ask /documents /feedback /health
  telemetry.py  governance-console events, self-registration, kill switch
  ui.py         Streamlit app
evals/       golden_set.yaml (21 cases)
infra/aws/   Terraform starter: S3, OpenSearch Serverless, Bedrock Knowledge Base, API role, Budgets
```

## Governance console

Every question, ingest and eval is reported to the portfolio's [governance console]({{SITE_URL}}/blog/governance-console/): who ran it, the model, tokens, cost, records in and out, the outcome and safety flags
(never prompts, questions or document text — only counts and hashes). The console can switch the workflow off; `ask` then refuses with the reason. Point `GOVERNANCE_URL` at the console (events are posted with `GOVERNANCE_INGEST_TOKEN`); without it, events go to a local spool file (`~/.ai-portfolio/governance/events.jsonl`) that a console on the same machine imports. `GOVERNANCE_TELEMETRY=off` disables telemetry; `GOVERNANCE_FAIL_CLOSED=1` blocks runs when the console can't be reached.

## Commands

| Command | Purpose |
|---|---|
| `rqa all` | corpus → full index → retrieval comparison → sample questions |
| `rqa data` / `rqa ingest [--full] [--embedding X]` | regenerate the corpus / index it |
| `rqa ask "…" --user U [--mode hybrid\|bm25\|vector] [--alias X]` | one question |
| `rqa eval [--alias X] [--baseline Y]` / `promote ALIAS MODEL` | eval gate and promotion |
| `rqa compare-retrieval` | recall@k and MRR per retrieval mode |
| `rqa serve` / `rqa ui` | FastAPI service / Streamlit app |
| `rqa models-check` / `cost-report` | model hygiene and spend |

## License

MIT. All companies, people, numbers and research are fictional.
