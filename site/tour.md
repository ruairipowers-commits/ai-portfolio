---
hide: [navigation]
description: Ruairi Powers in three minutes — who he is, three projects with measured results, and the evidence behind each skill.
---

# Ruairi Powers in three minutes

I'm a data and technology leader with 25 years in investment firms: Bridgewater, Two Sigma and Neudata, and now data
and analytics director at Silver Ridge Advisors. I build AI systems the way trading systems should be built:
measured before they're trusted, governed in code, and explainable to the people who rely on them.

**[Resume (PDF)](assets/Ruairi-Powers-Resume.pdf)** · [LinkedIn](https://www.linkedin.com/in/ruairi-powers) ·
[GitHub](https://github.com/{{GITHUB_OWNER}}) · [About me](about.md)

## Ask the portfolio

I built this assistant for hiring managers. Ask whether I fit your role, or what I've done with agents, data or
governance, and it answers from everything on this site, my resume and the project code, citing the page behind
each claim. **Search** lists the pages that match; **Ask** writes an answer. Expand the panel to keep the answers
beside the page while you click through the sources; your history stays as you move around the site.

Hiring for a specific role? Paste the job description under *Match me to a role* and download a fit read: where the
evidence matches, what the site doesn't show yet, and what to ask me.

<div data-sa-inline markdown>

The assistant runs on my own server and isn't reachable right now. The search box at the top of the page still
works, and my [resume](assets/Ruairi-Powers-Resume.pdf) has my contact details.

</div>

## Three projects

Each one runs offline with one command, has a live demo, and is mapped to the same
[30 governance controls](blog/posts/governance.md). All of them are my own work, built on synthetic data for learning
and as examples.

<!-- tour:projects -->

## What I can do, and where to see it

| Capability | Evidence on this site |
|---|---|
| **Production data pipelines** | [EOD heartbeat](blog/posts/eod-heartbeat.md): Airflow and dbt on Postgres, with 28 dbt tests gating every run. [Alt-data triage](blog/posts/altdata-triage.md): each vendor's sample data scored in dbt before a model drafts anything |
| **Agents with human approval** | [Trade-ops exception agent](blog/posts/trade-ops-exceptions.md): read-only tools over MCP; nothing is written until a named analyst approves. [Editorial agents](personal/posts/editorial-agents.md): a writer and an independent editor; only my merge publishes |
| **Retrieval (RAG)** | [Research Q&A](blog/posts/research-qa-rag.md): entitlements enforced inside retrieval, cited answers, a refusal when the evidence isn't there. The **Ask** button on this site |
| **Evaluation** | A golden set and an eval gate in CI for every project; [choosing the Ask model](personal/posts/choosing-the-ask-model.md) measured three local models before picking one |
| **AI governance** | [The standard](blog/posts/governance.md) every project maps to; the [governance console](blog/posts/governance-console.md) with a kill switch; [a leader's guide](blog/posts/questions-for-your-ai-team.md) to questioning an AI team |
| **Financial data** | Twenty years at Bridgewater in market data, transaction-cost analytics, clearing and trading QA; data catalog and lineage at Two Sigma; alternative data at Neudata ([About](about.md)) |
| **Leading teams** | A team of thirteen through a zero-to-one SaaS launch at Neudata; how I'd [build an AI team](blog/posts/building-an-ai-team.md) |

## How I work with AI

I directed Claude Code to build this site and every project on it: I wrote the standard, the specs and the rules, and
reviewed the results; Claude wrote most of the code. [How this site was built](index.md#how-this-site-was-built) explains
the method, and [how I govern it](blog/posts/how-i-govern-this-site.md) links each control to the code and tests behind it.

Questions? Press **Ask** in the header: it answers from everything on the site and cites its sources.
