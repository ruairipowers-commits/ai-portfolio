---
hide: [navigation]
---

# Learning to use AI responsibly, in the open

This site is my working record of learning to build, use and govern AI in the kind of setting I've spent my career
in: investment firms, where data has to be right and every decision has to be explainable to someone.

I built it for two reasons. The first is to **catalogue my own journey**: the projects, what went wrong, what I'd do
differently, and the controls I now hold every AI workflow to. The second is so **others can learn from it**. Each
project shows how to use AI responsibly and govern it, with the code and the reasoning. The site keeps changing as I
learn; the [release notes](release-notes/index.md) record each step.

## Portfolio gallery

Every project, what it measured, and where to try it. The industry projects' numbers come from offline runs on
synthetic data and golden-set evaluations (the demos need no API keys). The Ask button's and the capstone's are
measured on my own server and on a public loan dataset.

<!-- projects:gallery -->

## Latest posts

<!-- posts:carousel -->

[All posts, with filters →](blog/index.md)

## What's here

<div class="grid cards" markdown>

- :material-shield-check-outline: **[AI Governance](blog/posts/governance.md)**

    The 30 controls every project is held to: data preparation, security, cost, model changes, evals, audit and
    human oversight. Start here if you only read one thing.

- :material-briefcase-outline: **[Projects](projects/index.md)**

    Industry projects for real fund problems (vendor data, end-of-day breaks, trade exceptions, research Q&A), each
    with a live demo and a runnable repo. Plus the console that governs them, and some personal projects.

- :material-post-outline: **[Blog](blog/index.md)**

    The write-up behind each project: the business problem, the design, the trade-offs. Filter by topic or date.

- :material-school-outline: **[Classes](classes/index.md)**

    Two MIT courses: one on how the models work, one on bringing AI into an organisation responsibly.

- :material-toolbox-outline: **[Technologies](tech/index.md)**

    Every tool used here: what it's for, where it fits in AI work, its trade-offs and a minimal example.

- :material-chat-question-outline: **Ask**

    The button in the header answers questions about anything on the site, citing its sources. It runs on a local
    open model on my own server.

</div>

## My Background

I've spent 25 years building and running investment technology.

- **Bridgewater.** Twenty years: transaction-cost analytics and market data, then architecture for a dual back
  office that independently cleared every transaction each day, then leading trading QA.

- **Two Sigma.** A data catalog and lineage product for researchers and the engineers who keep production pipelines
  running.

- **Neudata.** Leading a team of thirteen through a zero-to-one SaaS launch.
- **Silver Ridge Advisors.** Now: data and analytics director at a consulting firm, leading strategic assessments
  and modernization for clients, from a retailer's inventory platform to a charity's fundraising and financial
  systems.

That background shapes how I approach AI. In trading and clearing, a wrong number costs money, so you design for
verification, audit and rollback from the start. I think AI should be held to the same standard. What interests me
is the work between a promising demo and a system a firm can rely on: choosing the right problem, getting the data
right, measuring the model honestly, and governing it so people can trust it.

**What I'd bring to a team:**

- **I sit between the business and the engineering.** I can write the requirements, review the architecture and
  test the result.

- **A habit of measuring before trusting.** Golden sets, eval gates, staged rollouts.
- **Fluency in financial data.** Market data, trading, settlement and alternative data.
- **Hands-on technical depth** in Python and SQL, data platforms and cloud, now extended into retrieval, agents and
  model evaluation.

## How this site was built

I built this site with Claude Code as my engineering partner. I directed and reviewed the work; Claude wrote most of
the code. How I directed it is as much the point as what it built:

- **Standards first.** I wrote the [governance standard](blog/posts/governance.md), a style guide and a short
  instructions file before any project. Every project must map every control, and CI fails if one is missing.

- **A spec for each project.** Each starts as a short spec of the use case, data and success criteria. Claude drafts
  it, I approve it, and a reusable skill turns it into a repo, tests, a demo and a write-up.

- **Rules that keep it honest.** Everything runs offline with a mock model. Numbers come from code, never from the
  model. Nothing is claimed that wasn't run, and my own edits always win over generated ones.

- **The same discipline in delivery.** Tests and evals gate every change, and only commits that pass CI deploy to
  the [live demos](projects/index.md) on my own server.

Directing AI well turned out to need the skills I already had: product management to say what good looks like, data
engineering to know where it breaks, and QA to insist on proof. That is the most useful thing this project has
taught me.

## Deepening the academic side

Alongside the practical work, I took two MIT Professional Education courses in 2026 to ground it.

- **[Applied AI and Data Science](classes/posts/applied-ai-data-science.md)** taught how the models work:
  statistics, regression and classification, trees and forests, deep learning, recommenders and generative AI. My
  capstone was an explainable [loan-default model](classes/posts/loan-default-capstone.md) that you can run in Colab.

- **[Applied Agentic AI for Organizational Transformation](classes/posts/applied-agentic-ai.md)** taught how to bring
  agents into an organisation and scale them responsibly: frameworks, governance plans and staged rollout.

The [Classes](classes/index.md) page shows how the two fit together.

---

**[Resume (PDF)](assets/Ruairi-Powers-Resume.pdf)** · [LinkedIn](https://www.linkedin.com/in/ruairi-powers) ·
[About me](about.md) · [GitHub](https://github.com/{{GITHUB_OWNER}})
