---
date: 2026-11-17
slug: hyperscale-data-center-emissions
short: "What 403 data centers emit"
categories: [Operations, Cost & FinOps, AI governance]
tags: [data centers, energy, emissions, cloud regions, ESG, AutoPublished]
audience: [CTOs and heads of technology, Executives and boards, "Risk, compliance and legal", Heads of data]
section: AI insight
---

# The Carbon Footprint of US Hyperscale Data Centers, and Why Region Choice Matters

If I run AI workloads in the cloud, or hold the companies that build the data centers, the grid behind each region is part of the cost. A new Harvard-led study estimates that 403 US hyperscale data centers used about 1.8% of US electricity in a year and emitted about 25.7 million metric tonnes of CO₂, which Reuters compared to Denmark's annual output. Here is what I take from it.

<!-- more -->

## What it is

The study was published in *Nature Sustainability* in mid-November 2026 by researchers led by the Harvard T.H. Chan School of Public Health ([Harvard's summary](https://hsph.harvard.edu/news/hyperscale-data-centers-energy-consumption-carbon-emissions-newly-estimated-by-researchers/); [The Verge](https://www.theverge.com/ai-artificial-intelligence/1034668/data-centers-electricity-climate-pollution-study-harvard) also covered it). It covers May 2024 to April 2025. The 403 sites are the ones with enough data: the earlier [preprint](https://arxiv.org/html/2606.05420) started from 675 identified.

The method, as the preprint describes it: capacity × hours × a load factor, under four scenarios, then attributed to the power plants in each grid balancing area using EPA eGRID data. The preprint's emissions numbers differ from the published ones, so I use the published figures from Harvard and [The Next Web](https://thenextweb.com/news/us-data-centres-emissions-denmark-harvard-study):

* **Electricity**: 68–99 TWh; about 82 TWh in the central case, roughly 1.8% of US use.
* **CO₂**: about 25.7 million tonnes in the central case, 21–31 million across scenarios.
* **Mix**: about 54% fossil, of which natural gas 38% and coal 15%.
* **Where**: Virginia, Oregon, Ohio and Iowa hold more than half the load. Oregon is second for power but sixth for emissions, because of its hydropower.

To put the electricity in context, the top of the range approaches what Indiana, Michigan or Tennessee each use in a year. The preprint's state split shows how lopsided it is: about 21 TWh in Virginia, 11 in Oregon, 9 in Ohio and 7 in Iowa. For a utility in one of those states, this isn't a national average; it's a local load-planning problem.

The numbers are modelled, not metered, because operators don't disclose power use. On-site generation and clean-energy contracts are left out, and the study can't separate AI from general computing. The lead author says the 2026 figures could already be substantially larger.

## Why it matters beyond AI labs

### Worked example: one inference workload, two grids

Take a hypothetical model-screening job that uses 100 MWh a year. The preprint puts the hyperscale fleet's electricity-weighted carbon intensity at about 545 gCO₂/kWh, against a 2023 US average of about 370 (both preprint figures, before revision):

| Grid intensity | Annual CO₂ for 100 MWh |
|---|---|
| ~545 g/kWh (hyperscale average, preprint) | ~54.5 tonnes |
| ~370 g/kWh (US average, preprint) | ~37 tonnes |

Same work, roughly 17 tonnes apart, purely from where the electricity comes from. The Oregon ranking makes the same point from the other side. For location-based reporting, region choice is a lever I can actually pull; the 100 MWh is my assumption, the intensities are the study's.

### What each group should do with it

* **Firms buying cloud compute**: add grid mix to the criteria for choosing a region, and ask providers for metered, location-based figures per region.
* **Investors in hyperscalers and utilities**: treat the four-state concentration as a planning and transition-risk question for the utilities serving Virginia, Oregon, Ohio and Iowa, and ask hyperscalers how they'll disclose.
* **Risk and reporting teams**: keep modelled figures labelled as ranges with their source, not as facts about any one provider.

On prices, the evidence so far points the other way from the headlines. The separate Harvard and Penn study puts data centers behind about 4% of residential rate rises over five years, but about 15% of the industrial price increase from 2020 to 2025. If I ran an energy-heavy business in one of those grid areas, the second number is the one I'd watch.

## What I'd watch out for

| Issue | What the sources say | What I'd do |
|-------|----------------|--------------------------|
| **Modelled, not metered** | Operators don't disclose power use; the figures are estimates. | Report ranges with sources ([the governance standard](../../blog/posts/governance.md), OBS-02). |
| **Exclusions** | On-site generation and clean-energy contracts are excluded. | My speculation: this could cut either way for a given operator, so ask each provider for its own numbers. |
| **Region choice** | The grid behind a region drives the footprint. | Approved providers and regions (SEC-05), with grid mix as a criterion. |
| **Household prices** | A [separate Harvard and Penn study](https://tech.slashdot.org/story/26/11/07/0412226/) puts about 4% of residential rate rises over five years down to data centers; some grid areas have seen costs pushed onto residents. | Watch the concentrated regions, not the national average. |

## What I'd try next

1. **AI share of the load.** The study can't split AI from general computing. That split is the number I'd most like to see.
2. **Disclosure.** The same day the study came out, COP31 negotiators launched a voluntary pledge asking data centers to use clean power and disclose energy, water and emissions data. Whether operators sign up and publish is the real test.
3. **My own projects.** Pick regions with grid mix as one of the criteria, and record the assumption next to the cost.

What would change my mind is metered data. If providers published metered, location-based consumption per region, I'd use it instead of the model and expect the ranges to narrow, possibly in their favour.

*Drafted with AI agents: a local model on my own server wrote the first draft from a topic my scout found, Claude reviewed and edited it, it passed every automated check, and I approved it for publishing.*
