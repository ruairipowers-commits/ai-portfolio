---
date: 2026-11-18
slug: openai-10b-quarter
short: "OpenAI's $10B quarter, for buyers"
categories: [Operations, Cost & FinOps, AI governance]
tags: [openai, anthropic, vendor risk, unit economics, ai pricing, AutoPublished]
audience: [CTOs and heads of technology, Executives and boards, Heads of data, "Risk, compliance and legal"]
section: AI insight
---

# OpenAI’s Reported $10B Quarter: Read It as a Supplier Risk

I’ve spent 25 years in financial data and trading technology, and the first question I ask about any critical supplier is whether its economics are stable. OpenAI’s third quarter reportedly brought in about $10 billion while it still lost more than a dollar for every dollar of revenue. If you build on its APIs, that combination is worth ten minutes: it tells you what kind of pressure sits behind the prices you pay.

<!-- more -->

## What it is

[TechCrunch](https://techcrunch.com/2026/11/11/openais-quarterly-revenue-reportedly-crosses-10b-for-the-first-time/) summarises the reports. Bloomberg cited people familiar with figures OpenAI shared with investors, and the Wall Street Journal reviewed the documents; OpenAI declined to comment, and nothing here is audited. [Yahoo Finance](https://finance.yahoo.com/technology/ai/articles/openai-hits-10-billion-quarterly-190211001.html), [The Next Web](https://thenextweb.com/news/openai-revenue-q3-10bn-operating-loss) and [Forbes](https://www.forbes.com/sites/gabrielalinzainescu/2026/11/11/openai-revenue-hits-10-billion-as-losses-reach-109-billion/) add the loss figures.

The reported numbers:

- Revenue of about **$10 billion** in Q3, up roughly 50% on Q2’s $6.7 billion and nearly three times the same quarter of 2025.
- An adjusted operating loss of about **$10.9 billion**, up from $10.1 billion.
- An adjusted operating margin of about –109%, up from –150%.

My reading: the loss per dollar of revenue is falling, but the loss in dollars is still rising. A supplier in that position has to keep finding margin somewhere, and the reported drivers point at where: tighter pricing and targeted discounts, alongside better models and a push into enterprise products and AI agents. None of those drivers has been independently confirmed. Forbes cites Greg Brockman saying enterprise sales became OpenAI’s largest revenue source in Q3, and Sarah Friar saying enterprise revenue doubled on the quarter while consumer sales rose 20%.

The Next Web, citing Bloomberg, says OpenAI is completing a funding round at a $1.25 trillion valuation, and reports that it has delayed its own listing until next year.

The obvious comparison is Anthropic. Its amended IPO filing, [summarised by StockAnalysis.com](https://stockanalysis.com/news/anthropic-third-quarter-revenue-17-billion-ipo-filing/), shows Q3 revenue of $16.96 billion, an operating loss of $567 million and adjusted operating income of $2.5 billion. Note the mismatch: that $567 million is a reported operating loss, while OpenAI’s $10.9 billion is an adjusted figure, so the two loss numbers don’t line up. TechCrunch also warns that the two firms compute annualized revenue on different bases, because one includes cloud-partner sales and the other books only its share of some of them. League tables built from these numbers will mislead.

## Why it matters beyond AI labs

### The supplier‑risk angle

If your firm builds on an external model provider’s API – whether for finance, healthcare, retail or media – the vendor’s financial health becomes part of your own risk profile. A company losing $1.09 per dollar of revenue has strong incentives to change pricing, discount structures, and contractual terms. Those changes can ripple through any downstream product that depends on that model.

### Example: Document summarisation workflow

Consider a hypothetical hedge‑fund analytics platform that uses an AI API to summarise research reports. Each month you track the cost per document, store the prompts and evaluation set so you can switch vendors if needed, and embed a clause in your contract that triggers a price review or a model deprecation notice.

Set the trigger before you need it. Agree a budget band for cost per document when the contract starts. If a monthly figure lands outside that band, or the vendor announces a deprecation, you rerun the same evaluation set on a second provider that week and compare quality and cost side by side. When OpenAI tightens pricing or offers a new discount tier, you already have a plan to reassess costs without scrambling.

### Other sectors

- **Financial services**: Before building trading or risk tools on a third‑party model, add the provider to the third‑party risk register with a named owner and a tested fallback provider.
- **Healthcare & insurance**: For long‑term contracts on regulated workloads, require written notice of model changes, with time to re‑validate before the old model is retired.
- **Retail & media**: For high‑volume, price‑sensitive inference, set a spend alert per use case so a repricing shows up in days, not at quarter end.

The takeaway is that any organization using AI APIs should treat the provider like any other critical third‑party feed: monitor unit economics, maintain portability of prompts and evaluation data, and negotiate clear terms for pricing changes or model deprecations.

## What I'd watch out for

| Risk | Why it matters | What I'd do |
|------|----------------|---------------------|
| **Unverified numbers** | The revenue figures are not audited; they may be inflated or understated. | Treat them as directional; base decisions on your own measured costs. |
| **Differing revenue definitions** | The two leading labs compute annualized revenue on different bases. | Standardise the definition of “vendor revenue” in risk assessments. |
| **Price volatility** | My inference, not a reported plan: losses on this scale give the vendor reason to keep adjusting prices and discounts. | Include price‑change clauses and automated monitoring dashboards. |
| **Vendor concentration** | Heavy reliance on one vendor exposes you to single‑point failure if the vendor restructures. | Diversify across multiple model providers; maintain cross‑vendor portability. |
| **Structural changes** | Yahoo Finance suggests sustained losses may force a structural response; what that would be is speculation. | Conduct scenario analysis and contingency planning for sudden vendor shifts. |

Several controls in [the governance standard](../../blog/posts/governance.md) apply directly: cost logged per call and use case with monthly alerts and a named reviewer (COST-02, COST-04), deprecation dates tracked with a migration runbook (MODEL-03), a fallback provider (MODEL-05), and an eval gate before any model switch (MODEL-02).

## What I'd try next

1. **Read vendor numbers critically** – The figures are unverified, so track the reported trend (revenue growth, operating margins, discounting) each quarter rather than relying on any single headline.
2. **Measure your own unit cost** – Run one workload’s evaluation set through two or three providers and record cost per task and quality on the same cases. Your own number is the one that matters, because the vendors’ headline figures don’t line up.
3. **Model portability testing** – Build a small pilot that swaps between providers for the same workload; measure performance, cost, and integration effort.
4. **Scenario planning** – Run stress tests where OpenAI raises prices or discontinues a popular model; evaluate impact on your margins and operational timelines.
5. **Contractual safeguards** – Negotiate notice periods for price changes and a grace period before a model deprecation takes effect.

What would change my mind is audited accounts showing the dollar loss shrinking, not just the margin. Until then, if any of these steps reveal that your cost structure is too sensitive to one vendor’s pricing, I would consider shifting to a more diversified set of providers or investing in an internal model‑hosting capability.

*Drafted with AI agents: a local model on my own server wrote the first draft from a topic my scout found, Claude reviewed and edited it, it passed every automated check, and I approved it for publishing.*
