---
date: 2026-11-03
slug: sea-ai-usage-gap
short: "AI adoption vs. AI usage"
categories: [Evaluation, Cost & FinOps, AI governance]
tags: [e-conomy sea, southeast asia, tokens, adoption metrics, agentic commerce, financial services, AutoPublished]
audience: [Executives and boards, CTOs and heads of technology, Heads of data, "Risk, compliance and legal"]
section: AI insight
---

# Measuring AI Impact in Southeast Asia: Tokens vs Adoption

Most AI rollouts I see reported are measured by how many people have access. The latest e-Conomy SEA report from Google, Temasek and Bain & Company adds a second number, how much AI is actually used, and finds the two far apart. That gap is the question I'd put to any firm that has bought AI seats for everyone: is the spend doing work yet?

<!-- more -->

## What it is

The report, summarised in [Google's announcement](https://blog.google/company-news/inside-google/around-the-globe/google-asia/e-conomy-sea-report-2026/) and [Bain's press release](https://www.bain.com/about/media-center/press-releases/sea/e-conomy-sea-2026/), projects Southeast Asia's digital economy will reach **$368 billion GMV** in 2026 and grow at **17% year-on-year**, surpassing $1 trillion by 2035.
It also introduces a new metric: **AI usage measured in tokens**, presented alongside the traditional GMV figure.

I've spent most of my career around trading and data platforms, where a new system's launch dashboard always shows logins. Logins tell you a tool was opened. They don't tell you whether a trade, a reconciliation or a credit decision went through it. That's why this framing caught my eye: it's the first time I've seen a big regional forecast make the same distinction.

The numbers behind the gap:

* Generative AI adoption hit **243 million people**, 58% of the working population, in under three years: four times faster than mobile internet uptake.
* Regional token usage is about **10% of U.S. levels**; Bain's Florian Hoppe says most users remain on free tiers ([CRN Asia](https://www.crnasia.com/news/2026/artificial-intelligence/e-conomy-sea-2026-southeast-asia-s-digital-economy-to-hit-us)).
* Across the region, consumers generate roughly **60%** of tokens. In Singapore and Malaysia alone, enterprise workloads drive 45–60%.
* Usage could grow up to **60-fold by 2030** as people shift from basic searches to delegating complex tasks to AI agents.

Bain's Florian Hoppe puts it as a shift from how many people use AI to how deeply. I'd add a third question: neither breadth nor depth measures value. Tokens are closer to a cost line than an outcome. The useful step for a firm is to put all three side by side.

## Why it matters beyond AI labs

### Sectors that can benefit

| Sector | What the report says | A ratio I'd track (my suggestion) |
|--------|------------------------------|-----------------|
| **Financial services** | Digital financial services GTV of $1.65 trillion, up 16%; digital lending up 22% to $116 billion; AI used in customer acquisition, credit assessment and real-time fraud detection | Model cost per fraud alert triaged, next to alert precision; cost per credit memo drafted, next to the reviewer's edit rate |
| **Retail & e-commerce** | $226 billion GMV, up 18%; 69% of shoppers use AI to compare complex purchases; Bain reports a 10% year-on-year conversion lift | Cost per AI-assisted order, next to conversion and return rates |
| **Enterprise IT** | Data centre capacity needs to roughly triple over five years; enterprises need falling inference costs and demonstrable ROI | Cost per completed task by workload, next to the task's success rate |

### Worked example (hypothetical): a bank rolling out an AI assistant

Say a regional bank launches an internal AI assistant for staff and reports an illustrative **80% adoption**, meaning 80% of employees opened it at least once a week. The report's framing suggests looking deeper:

1. **Work per user**: tokens and cost per completed task (a credit memo, a triaged alert), not tokens per head. A few short chats a week is opening the tool, not using it.
2. **Enterprise-managed vs free-tier usage**: tokens generated on personal, free-tier accounts could fall outside corporate data controls.
3. **Business outcome linkage**: track how many credit memos are drafted or fraud alerts triaged by the AI.

If adoption is high but token volume and business outcomes remain low, the bank can identify bottlenecks: perhaps the assistant needs better integration with core banking systems or clearer use cases for staff.

## What I'd watch out for

| Risk | Why it matters | Governance link |
|------|----------------|-----------------|
| **Users want to undo agent actions** | 30% of users name the ability to undo an agent's action as a condition of trust; my recommendation is audit trails and limits before any agent can transact. | [SEC-03, HITL-02](../../blog/posts/governance.md): agents' write actions need explicit approval and limits |
| **Staff data outside enterprise control** | My inference, not the report's: if work runs through personal free-tier accounts, sensitive information can leave the firm's privacy and residency controls. | [SEC-05, DATA-03](../../blog/posts/governance.md): approved providers only, and only the fields a task needs |
| **Tokens ≠ value** | High token counts do not guarantee ROI; enterprises need demonstrable productivity gains. | [COST-02, EVAL-02](../../blog/posts/governance.md): cost logged per use case, judged against task metrics |
| **Uncertain forecasts** | Projections to 2035 and a 60-fold growth come from firms with a commercial stake in the region's growth (Google, Temasek, Bain). | None: a judgement call, so treat them as scenarios |
| **Infrastructure and energy** | Data centre capacity must roughly triple over five years; the report cites Singapore's PUE efficiency rules and Malaysia's CRESS clean-energy scheme as the kind of measures that help. | [COST-03](../../blog/posts/governance.md): right-size models before buying capacity |

The common thread: track not just who uses AI, but how it is used and what it delivers.

I'd add one caution about the metric itself. I read the Google post, Bain's press release and CRN Asia's coverage, not the full report, and none of them says how tokens per person were estimated or how the US comparison was built. Until I've seen that method, I'd treat "10% of US levels" as a direction, not a number to put in a board pack.

## What I'd try next

* **Token-based dashboards**: build real-time metrics that show token volume per business unit, split by free vs enterprise tiers.
* **Outcome-linked usage**: tie token counts to specific KPIs (e.g., fraud alerts triaged, loan approvals processed) to validate ROI.
* **Bring staff use inside the controls**: give staff an enterprise-managed option good enough that work doesn't drift to personal free-tier accounts.
* **Scenario modelling**: treat the 60-fold projection as an upper-bound scenario, not a plan: if usage grew that much, which budgets and capacity limits would break first? That's speculative by design.

If token usage rises sharply without a corresponding lift in business outcomes, that would be a clear signal that the AI deployment needs redesign: perhaps by tightening integration points or redefining success metrics.

What would change my mind about tokens as the headline measure: evidence that token volume and business outcomes move apart in practice, for example a fraud team whose alert quality improves while its token count falls because prompts got shorter. Then I'd count completed tasks instead and keep tokens as a cost line.

*Drafted with AI agents: a local model on my own server wrote the first draft from a topic my scout found, Claude reviewed and edited it, it passed every automated check, and I approved it for publishing.*
