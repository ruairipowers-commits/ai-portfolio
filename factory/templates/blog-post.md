---
date: YYYY-MM-DD
slug: <slug>
categories: [<pattern>, <domain tag>]
tags: [<tech>, <tech>]
---

# <Title: the business outcome, not the tech>

<2–3 sentence hook: the problem in the reader's world, and what this project shows.>

<!-- more -->

**Repo:** [github.com/<owner>/<slug>](https://github.com/<owner>/<slug>) · runs offline in 5 minutes ·
**Stack:** <comma list>

## The business problem

<Who, what they do today, cost/time/risk. Why it matters to a fund. 2–3 paragraphs.>

## What the workflow does

<Plain-language walkthrough; include the results table from a demo run.>

## Requirements

**Functional** — table FR-n (3–6 rows)

**Non-functional** — table NFR-n with targets

## Architecture

<Mermaid flow diagram (include via snippet from the repo's docs/architecture.md where possible).>

### Why this architecture

<Decision table: decision · chosen · why · alternatives. Then 1–2 paragraphs on the most
interesting trade-off (e.g. workflow vs agent).>

## Governance in practice

<Pick the spec's `governance.deep_dive` controls. For each: what could go wrong, how the
project handles it, the config knob, and an option not built. Link to the full mapping.>

### Configuring it

<Table: what to change · file · key.>

## Taking it to AWS

<3–5 sentences + the local→AWS mapping table; link docs/aws-native.md.>

## What I'd do next / limits

<Honest list: what's mocked, what's missing, what production would add.>

---

*Part of my [AI workflow portfolio](../../index.md). Governance controls referenced here are
defined in [How I govern AI workflows](governance.md).*
