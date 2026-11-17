---
date: 2026-11-17
slug: scientists-chatgpt-workflows
short: "How 1,819 scientists use ChatGPT"
categories: [Research, Evaluation, Human in the loop]
tags: [ChatGPT, OpenAI, research workflows, productivity, adoption, AutoPublished]
audience: [CTOs and heads of technology, Heads of data, Executives and boards, Data scientists]
section: AI insight
---

# How 1,819 Scientists Use ChatGPT, and What It Says About AI Adoption Claims

In a new OpenAI study, 1,819 academic researchers sent over half a million messages to ChatGPT in about a month. Most of it was reading, writing, analysis and code; fully autonomous research was a sliver of use that some tried but few relied on. I read it as a yardstick for any team, or any company I might back, that claims AI has changed how it works.

<!-- more -->

## What it is

OpenAI published the study on 16 November 2026 ([OpenAI's write-up](https://openai.com/index/science-at-the-frontier/)). I couldn't load that page, so every figure here comes from two reports on it, by [Unite.ai](https://www.unite.ai/openai-study-finds-scientists-rarely-request-end-to-end-ai-research/) and [The Rundown](https://www.therundown.ai/news/openai-study-scientists-chatgpt-reading-writing-code).

It covers **580,186 messages** sent between 20 August and 22 September 2026 by scientists in OpenAI's free academic pilot, plus a survey of **251 participants**. Automated classifiers grouped the messages by task; nobody read them. The figures I care about:

* Reading, writing, analysis and code made up about **85%** of the average scientist's messages. Reading alone was **27.7%** and writing **26.9%**.
* End-to-end autonomous research was **0.4%** of messages, though **15.3%** of scientists tried it at least once. The study calls that experimentation.
* On the study's scientist-involvement score, about a third of requests (**31.8%**) were followed by clarification, checking or revision.
* Checking or correcting outputs was the most-cited difficulty, named by **45.4%** of those surveyed.
* Respondents estimated an hour with AI would take about **1.9 hours** without it, from 1.36× for administration to around 2.8× for code. Quality was assumed equal, not measured.

The limits are stated plainly: these are OpenAI's own pilot users, who applied for access and chose to answer, and the shares describe requests, not research value or time spent.

## Why it matters beyond AI labs

The pattern is supervised help, not delegation: lots of reading and drafting, a steady rate of checking, and very little "do it all for me". That gives me a baseline to compare claims against.

### Worked example: diligence on a deep-tech startup

Say I'm looking at a materials startup that says its AI platform speeds up discovery. As an outsider I won't see its ChatGPT logs, and I shouldn't expect to. What I can ask for:

* What share of your AI use is reading, writing, analysis, code, and end-to-end automation? Can you show a usage summary by task, under NDA?
* How often is an output revised or rejected before it's used, and who signs it off?
* How do you check AI-generated analysis before it reaches a result, a report or a regulator?

A profile like the study's, with checking happening at a steady rate, looks like real, supervised adoption. The warning sign is a team claiming large gains or "autonomous discovery" while it can't say how outputs are checked. My hypothesis, not a finding of the study, is that the gap between the claim and the usage pattern is where most of the risk sits.

The same questions work closer to home. In a finance or technology team, I'd want the split between drafting, analysis and code, and the revision rate, before believing any productivity number in an AI business case.

## What I'd watch out for

* **Self-reported productivity.** The 1.9× figure assumes equal quality. Nobody measured it, so I'd treat it as a ceiling, not an estimate.
* **Selection bias.** Volunteers in a free, vendor-run pilot are likely keener than average.
* **Verification cost.** Checking is the top difficulty. It is real work and it eats into the time saved.
* **Data handling.** Unpublished research goes into a third-party tool. Unite.ai reports that programme data were not used for training by default; a firm should confirm its own settings rather than rely on a default.

These map onto [the governance standard](../../blog/posts/governance.md):

* **DATA-03 and SEC-05** – only the fields a task needs reach the model, and no-training settings are confirmed with the provider.
* **HITL-02** – a named person approves AI-assisted output before it informs a decision.
* **OBS-02** – every claim an assistant makes traces back to a source someone can check.
* **OBS-01** – a run log of AI interactions, so usage by task can be reported at all.

## What I'd try next

1. **Classify my own use.** Tag a month of my assistant requests on my own projects by task, the way the study did, and count how often I revise or discard the output.
2. **Time it.** Measure a few tasks with and without the assistant instead of estimating, and score the quality blind.
3. **Track outcomes, not activity.** The study doesn't measure whether AI help leads to more or better research. That's the question that matters, and the one I'd want answered before trusting a speed-up.

One more finding keeps me cautious: the bottlenecks respondents named most were limited time or staffing (51.8%) and funding (43.8%). Faster drafting doesn't fix either.

What would change my mind? Evidence from outside a volunteer pilot showing much more end-to-end automation with checking that still holds up. Until then, I'll read high autonomy and low checking as a risk, not a sign of maturity.

*Drafted with AI agents: a local model on my own server wrote the first draft from a topic my scout found, Claude reviewed and edited it, it passed every automated check, and I approved it for publishing.*
