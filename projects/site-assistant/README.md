# site-assistant

**Search and chat for the portfolio blog. It runs a local open model, answers only from the blog with links to
the pages it used, logs every search, and sends the owner a daily engagement email.**

> Part of the [AI Workflow Portfolio]({{SITE_URL}}) by Ruairi Powers · a personal project ·
> Write-up: [{{SITE_URL}}/personal/site-assistant/]({{SITE_URL}}/personal/site-assistant/) ·
> Governance: [this project's mapping](docs/governance.md)

## What it does

- **Ask button on every blog page.** It opens a panel with suggested questions. Answers stream from a local model
  (Ollama) and cite the blog sections they used. A list of matching pages appears alongside. Questions about
  Ruairi, such as "would he be a good fit for an AI product role?", always get the About page in context. The answer
  is balanced: evidence with citations, plus what the blog doesn't show.
- **Search** over every post, technology page, the release notes and the About page. It reads the blog's own
  MkDocs search index, so a new page is searchable within an hour with no deploy.
- **Logging.** Page views, the blog's built-in search box, assistant searches and questions. Text is stored as
  typed, but no IP addresses and no cookies. The visitor key is a hash that rotates daily.
- **Daily engagement email** with yesterday's numbers against a 7-day average:
  - blog views and visitors, top pages and referrers;
  - top searches, searches with no results (content gaps) and the questions asked;
  - demo visits and runs (from the governance console);
  - Cloudflare requests, page views and visitors;
  - GitHub repo views, clones (≈ downloads), stars and forks.
- **Governed like every workflow.** Each search and question is reported to the governance console, which can
  switch answering off; search keeps working. Rate limits and a daily token budget apply.

## Quickstart

```bash
pip install -e ".[dev]"
pytest -q                                              # 14 tests, with a stand-in Ollama
mkdocs build -f ../../mkdocs.yml -d /tmp/site          # or point at the live blog
export SITE_INDEX=/tmp/site/search/search_index.json PORTFOLIO_SITE_URL=http://localhost:8000
siteassist index && siteassist ask "Which projects use RAG?"
siteassist eval                                        # retrieval golden set, hit@6 gate
siteassist serve                                       # http://localhost:8700
```

With no model it answers by quoting the best passages. For real answers, run Ollama
(`ollama pull llama3.1:8b`) and set `OLLAMA_URL=http://localhost:11434`. In the self-hosted demo stack, Ollama runs
as its own container, and the assistant pulls the model the first time it starts.

## Configuration

| What | Where |
|---|---|
| Blog index source, refresh interval | `config/settings.yaml` `index.*`; env `SITE_INDEX`, `PORTFOLIO_SITE_URL` |
| Model | `config/models.yaml` (alias `chat`); env `OLLAMA_URL`, `OLLAMA_MODEL` |
| Limits, token budget, retention | `config/settings.yaml` `limits.*`, `cost.*`, `privacy.*` |
| Daily email | `digest.hour`, `digest.timezone`; env `DIGEST_EMAIL` (else `GOVERNANCE_ALERT_EMAIL`), `SMTP_*` |
| Cloudflare | env `CF_API_TOKEN` (Analytics: Read), `CF_ZONE_ID` |
| GitHub | env `GITHUB_TRAFFIC_TOKEN` (fine-grained, repository *Administration: read*), `GITHUB_REPOS` (`owner/repo,…`) |
| Owner pages (`/stats`, send the email now) | env `ASSISTANT_ADMIN_TOKEN` (else `GOVERNANCE_ADMIN_TOKEN`) |

## Use-case card (HITL-04)

| | |
|---|---|
| **Intended use** | Help blog visitors find and understand what's published; give the owner a daily view of engagement. |
| **Not for** | Statements about Ruairi beyond what's published; advice of any kind; private data. |
| **Risk tier** | Low — public content, no actions. Kill switch in the governance console. |
| **Owner** | Ruairi Powers |
| **Known limits** | A small local model can phrase things clumsily or miss nuance. Answers are only as current as the blog. Retrieval is keyword-based (BM25), so unusual wording can miss a page. GitHub keeps only 14 days of traffic, so the daily email stores each day as it comes. |

## Architecture

See [docs/architecture.md](docs/architecture.md).
