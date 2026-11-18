---
date: 2026-11-13
slug: metr-anthropic-rd-acceleration
short: "Anthropic's AI R&D at ~2x pace"
categories: [AI governance, Evaluation, Research]
tags: [anthropic, metr, ai r&d, model risk, vendor risk, third-party assessment, AutoPublished]
audience: [CTOs and heads of technology, "Risk, compliance and legal", Heads of data, Executives and boards]
section: AI insight
---

# Anthropic’s AI-Assisted R&D at About 2x: What It Means for Model-Risk Teams

I’ve spent two and a half decades building trading systems that rely on high-quality data and reliable model outputs. When an independent group like METR reports that a leading lab is now improving its models at about twice its earlier pace, largely because it uses AI in its own research, it’s a signal I can’t ignore. For CTOs and heads of data who must decide how often to re-evaluate vendor models, the more useful part of the report is how little of the evidence an outsider can check.

<!-- more -->

## What it is

[METR published its assessment](https://metr.org/blog/2026-11-05-anthropic-ai-rd-acceleration-assessment) on 5 November 2026 after working with Anthropic from 12 August to 29 October 2026, with about two and a half full-time staff. The engagement was first planned for four weeks and was extended to eleven. [Resultsense](https://www.resultsense.com/news/2026-11-06-metr-anthropic-ai-rd-acceleration/) and [Let's Data Science](https://letsdatascience.com/news/metr-estimates-anthropics-ai-capability-progress-has-roughly-e64b77bb) summarise it, and [The Verge covered it too](https://www.theverge.com/ai-artificial-intelligence/1029126/anthropic-metr-report-accelerating-ai-development), though I couldn't open that piece, so nothing below comes from it.

The core finding is that most METR staff believe Anthropic’s model-capability progress on well-specified tasks has accelerated to about twice the rate observed between March 2024 and October 2025. They would not be surprised if the true figure lay nearer 1.3× or 3×. On a benchmark index called AECI (Anthropic’s version of the Epoch Capabilities Index), scores since October 2025 grew at 1.9× the earlier rate, with a 95% confidence interval of 1.5× to 2.8×; alternative analyses give 1.1× to 2.9×. METR reads that as roughly two years’ worth of historical progress in one year.

Anthropic’s own Haiku 5.5 system card reported 1.7×, and METR attributes the difference mainly to including unreleased internal models in its calculations.

METR’s guess is that about 80% of the October 2026 acceleration is due to AI, with substantial uncertainty. Separately, it is confident the speed-up did not come from faster growth in training compute. It was told the current gains come mainly from AI assistance to researchers rather than fully autonomous work, but sees signs that autonomous contributions may grow soon.

The evidence has gaps, and METR says so. Anthropic redacted most of the evidence METR found most informative, describing the aim as removing “confidential information that could accelerate other AI developers.” METR never had direct access to Anthropic’s systems, only datasets and documents, and Anthropic cancelled a compute-allocation verification step midway through. METR took no payment; Anthropic supplied laptops and token credits.

## Why it matters beyond AI labs

Any organisation that buys model capacity from a frontier lab is exposed to that lab’s release cadence. If capability improves twice as fast, model versions, behaviour and pricing may change faster than a yearly review cycle assumes. That lands on the teams that validate and approve models before they enter production, in financial services and in any IT function running a model on a vendor’s API. That consequence is my reading, not something METR measured.

**Worked example: an investment firm’s model-risk team.** Consider a firm that uses Anthropic’s Claude models to summarise research documents for analysts. The internal risk team must decide whether to adopt each new version. The report says nothing about release dates or prices, so how often new versions will arrive is unknown. What it does suggest is that the gap between one version and the next may be larger than the team is used to, and that the best outside evidence about the supplier comes with redactions.

The practical response is to:

1. **Test each new version** against the firm’s own tasks (e.g., summaries checked against the source documents) as soon as it is available.
2. **Pin a stable version** for production until the next round of testing confirms no regressions.
3. **Record the evidence** that was available and what was redacted, so a later review can trace the decision.

This mirrors the situation described in METR’s report: the firm must rely on an evaluator whose access was limited and whose findings are partly hidden. A rigorous test-and-pin cycle reduces how much the risk team depends on outside judgement alone.

**Analysts covering AI companies.** The METR assessment is one data point from a single lab with significant redactions. Treat it as a range (1.3× to 3×) rather than an exact figure. The report also says gains may be confined to well-specified tasks; real-world, messy problems might not see the same pace of improvement.

## What I'd watch out for

Several of these map to controls in [the governance standard](../../blog/posts/governance.md): eval-gated model changes (MODEL-02), a registry that pins which model version is in use (MODEL-01), recorded model provenance (SEC-06) and keeping the evidence for later review (OBS-03).

| Risk | What I'd do about it |
|------|----------------------|
| Verification gap: redactions, no direct system access, a cancelled compute check | Record what the assessment could and couldn't see; don't treat it as a full audit |
| Trust concentrated in a single evaluator | Look for a second, independent assessment before leaning on the numbers |
| Conflicts: METR’s checklist includes a disclosure about staff equity in the provider | Read the disclosure; weigh it as you would any assessor's conflict |
| Capability change outpacing internal review cycles | Automated regression tests on your own tasks, and version pinning |
| Reading benchmark gains on well-specified tasks as gains on messy real work | Judge on production-like workloads, not on the index |

METR itself warns of “a significant risk that further capabilities progress could lead to even faster acceleration,” and says it may be missing important bottlenecks. If the trend continues, internal review processes may lag behind the pace of model change.

## What I'd try next

These are my suggestions, not METR’s.

1. **Broader independent assessments**: METR’s study covers only Anthropic. The same exercise across several frontier labs would show whether this is a general pattern or one lab’s experience.
2. **Transparent evidence sharing**: if labs could provide anonymised records of AI-assisted experiments, external reviewers could check the acceleration claim without exposing proprietary detail.
3. **Contract terms that expect change**: vendor agreements that allow for more frequent model updates would align pricing and risk management with a faster cycle.
4. **Benchmark diversification**: including real-world, ill-specified tasks would give a clearer picture of how acceleration translates to production workloads.

What would change my mind: a second assessment, at another lab or with fewer redactions, that lands near 1.3×. Until then I’d treat METR’s 2× as a central estimate inside a wide range, not a precise number and not a ceiling, and design model-risk processes for the faster end of it.

*Drafted with AI agents: a local model on my own server wrote the first draft from a topic my scout found, Claude reviewed and edited it, it passed every automated check, and I approved it for publishing.*
