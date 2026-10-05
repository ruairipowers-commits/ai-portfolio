---
date: 2026-10-05
slug: building-an-ai-team
short: "Building an AI team"
categories: [Teams & hiring, AI governance, Human in the loop]
tags: [ai team, hiring, interviewing, ai engineer, ml engineer, data engineer, structured interviews, work samples, ai literacy, eu ai act, nyc local law 144, org design]
audience: [Executives and boards, CTOs and heads of technology, Heads of data, Hiring managers, Product managers]
section: AI insight
---

# Building a modern AI team: who to hire, how to interview, and what goes wrong

Most AI projects that stall don't stall on the model. They stall on people: nobody owns the problem, nobody owns the
data, and nobody owns the thing once it's live. This is how I'd staff an AI team today, what each role is
accountable for, how I'd interview for it, and the mistakes I'd try hardest to avoid.

<!-- more -->

## Start with why projects fail

In 2024 RAND interviewed 65 experienced AI practitioners, most of them in industry, about why AI projects fail. Their
[five root causes](https://www.rand.org/pubs/research_reports/RRA2680-1.html) are worth reading before you write a
single job description:

1. Leaders don't say clearly which problem to solve, or how success will be measured.
2. The organisation lacks the data needed to train or ground the model.
3. The team chases the newest technique instead of the simplest thing that solves the problem.
4. Too little investment in the infrastructure to manage data and run models in production.
5. The problem is beyond what the technology can do today.

Only the last one is about AI itself. The other four are about who is on the team, who they report to and what they
are asked to do. So the team design is the first control, not an afterthought.

## The roles

"AI team" now covers two kinds of work. One is building products on top of foundation models: prompts, retrieval,
tools, agents, evaluation. That's the job the industry has started calling the
[AI engineer](https://redmonk.com/blog/2025/07/23/shawn-swyx-wang-ai-engineer/), closer to product engineering than
to research. The other is training and validating models on your own data, which is still how credit scoring,
forecasting and fraud detection work. Most firms need both, plus the people who make either one safe to run.

| Role | Owns | Core skills | When you need it |
|---|---|---|---|
| **Business owner** | The problem, the success measure, and the decision to ship or stop | Can state the outcome in numbers; has authority over the process being changed | Day one. No owner, no project |
| **AI product manager** | Use cases, scope, the use-case card, what "good enough" means | Turns a business goal into testable acceptance criteria; comfortable with probabilistic results | Day one, often the same person as the owner at first |
| **AI engineer** | Building on foundation models: prompts, retrieval, tools, guardrails, evals | Software engineering first; evaluation design; prompt-injection awareness; cost sense | Day one |
| **Data engineer** | Getting the right data to the model, tested and traceable | Pipelines, data tests, lineage, access control | Day one. Usually the most underhired role |
| **ML engineer / data scientist** | Models trained on your data, and their validation | Statistics, feature work, validation, explainability | When the problem is prediction on your own data, not language |
| **Platform / MLOps engineer** | Deployment, monitoring, model registry, spend | Infrastructure, observability, CI/CD, security basics | Once two or more use cases are live |
| **Risk, compliance and security partner** | Risk tiering, privacy, regulatory fit, sign-off | Model risk, privacy law, threat modelling | Day one as a partner; part-time is fine early on |
| **Domain experts** | Ground truth: labelling, reviewing outputs, catching nonsense | Deep knowledge of the process | Throughout. They're the reviewers your evals depend on |

Two notes on the table. First, the business owner and the domain experts are not "the business side" waiting for a
delivery. They're team members with time allocated, or the project has no ground truth. Second, evaluation is a skill,
not a phase. Early on the AI engineer owns it; once you have several systems live, a dedicated evaluation and quality
owner pays for itself.

## Who is accountable for what

Every control in my [governance standard](governance.md) needs a name next to it. This is how I'd assign the ones
that matter most:

| What must be true | Control | Accountable |
|---|---|---|
| Data passes quality tests before any model call | DATA-02 | Data engineer |
| Only the fields the task needs reach the model; personal data handled lawfully | DATA-03 | Data engineer, with the privacy partner |
| No model or prompt change ships without passing the evals | MODEL-02, EVAL-03 | AI engineer (or ML engineer) |
| Untrusted content can't change the agent's instructions | SEC-02 | AI engineer, reviewed by security |
| Each use case is risk-tiered and has a use-case card | HITL-01, HITL-04 | Product manager, approved by risk |
| A named person approves consequential actions | HITL-02 | Business owner |
| Spend has budgets, alerts and a reviewer | COST-01, COST-04 | Platform lead |

If a row has no name, that's the first gap to fix, and it costs nothing but a meeting.

## Shape the team for its stage

These are my rules of thumb, not benchmarks:

| Stage | Team | What it should produce |
|---|---|---|
| **First use case** | Business owner, an AI engineer, a data engineer, a part-time risk partner, two or three domain reviewers | One workflow in production with evals, a use-case card and a measured result |
| **Several use cases** | Add a product manager, a platform engineer and a second AI engineer; ML engineers if prediction problems appear | Shared tooling: one place for logs, costs, evals and approvals |
| **Many teams** | Small product teams embedded in the business, plus a central platform and governance team | Teams ship on their own; the centre sets standards and runs the shared platform |

The common mistake at stage three is a central "centre of excellence" that builds everything. It becomes a queue.
The centre should own the platform and the standard, and the business teams should own their products.

## Build, borrow or buy the people

Domain knowledge is the scarce ingredient, and you already employ it. Before hiring, I'd look at who inside the firm
is already automating their own work. A strong analyst who knows the process and learns to build with AI tools
often beats an outside hire who knows the tools and has to learn the business.

Training isn't optional for the rest of the firm either. The EU AI Act asks providers and deployers to support a
sufficient level of AI literacy among their staff. The [July 2026 amendments](https://www.whitecase.com/insight-alert/eu-ai-omnibus-enters-force-amending-ai-act)
softened that duty from "ensure" to "take measures to support", but the practical point stands: the people who use
and oversee these systems need to understand their limits.

Borrow specialists for spikes (a security review, a data migration) and buy what isn't your edge. Hire permanently
for the roles that hold knowledge you can't afford to lose: the data engineer who knows your sources, and the AI
engineer who knows why each eval exists.

## How to interview

The research on hiring is clearer than most interview loops suggest. A 2022 re-analysis of decades of selection
studies by Sackett and colleagues found
[structured interviews were the strongest predictor of job performance](https://www.siop.org/tip-article/is-cognitive-ability-the-best-predictor-of-job-performance-new-research-says-its-time-to-think-again/),
ahead of job-knowledge tests and work samples, with general cognitive tests further down than long believed. So the
loop I'd run is built around structure:

1. **Write the scorecard first.** Four or five things the person must be able to do in the first six months, each
   with what "strong" and "weak" look like. Every interviewer scores against it.
2. **Ask everyone the same questions,** in the same order, rated on the same anchored scale, scored before the debrief
   so the loudest voice doesn't set the grade.
3. **Use a short work sample that looks like the job.** Two hours, not a weekend. Then talk it through.
4. **Test judgement, not trivia.** Nobody needs to recite attention maths. They do need to know when not to use a
   model.

Work samples I'd use, by role:

| Role | Exercise | What I'm looking for |
|---|---|---|
| AI engineer | A small retrieval app with a failing eval set and one planted prompt injection. Improve the scores and explain the trade-offs | Do they measure before changing things? Do they find the injection? Do they consider cost? |
| Data engineer | A messy extract with duplicates, late records and a schema change. Write the tests that should stop the pipeline | Which failures they choose to block, and which they only warn on |
| ML engineer / data scientist | A dataset with a leakage trap. Build a baseline and say whether to ship it | Do they spot the leak? Do they start simple? Can they explain the model to a risk reviewer? |
| Product manager | A vague request ("use AI for client onboarding"). Write the use-case card and acceptance criteria | Measurable success, named limits, a human step where it matters |
| Risk partner | A short use-case card with gaps. Tier it and list what evidence they'd need | Proportion: neither rubber-stamping nor blocking everything |

Questions I'd ask every candidate, whatever the role:

- Tell me about an AI system you worked on that didn't work. How did you find out, and what did you change?
- How would you know this system had got worse three months after launch?
- Here's a task. Would you use an LLM, a classic model or a rule? Why?
- What would you never let a model do without a human signing off?

I'd let candidates use AI tools in the work sample, because they will on the job. What I'd watch is whether they
check the output. Someone who pastes a confident answer without testing it is showing me how they'll work.

Red flags: every answer is about a model and none about data; no examples of measuring anything; "accuracy" with no
idea what it was measured on; dismissing governance as paperwork.

## If you use AI to hire, it's regulated

Screening candidates with AI is one of the most regulated uses there is. In New York City, Local Law 144 has been
enforced since July 2023: an
[automated employment decision tool](https://www.nyc.gov/site/dca/about/automated-employment-decision-tools.page)
needs a bias audit within the year before use, the results published, and notice given to candidates. The EU AI Act
lists employment and recruitment uses as high-risk, with those obligations now applying from 2 December 2027 under the
[same amendments](https://www.whitecase.com/insight-alert/eu-ai-omnibus-enters-force-amending-ai-act). Whatever the
jurisdiction, I'd keep a named person making every hiring decision ([HITL-02](governance.md)) and treat any scoring
tool as advice, not a filter. Ask your counsel which rules apply where you hire.

## The pitfalls

- **Hiring researchers for an engineering problem.** Most firms need to apply models well, not invent new ones. Hire
  builders who measure.
- **Data last.** RAND's interviewees put data engineering at the heart of the work. If the first three hires include no
  data engineer, the fourth will be one, after a missed deadline.
- **The unicorn job ad.** One person who does research, engineering, product, data and compliance doesn't exist. Hire
  for two strengths and cover the rest with the team.
- **A team cut off from the business.** If the domain experts have no time allocated, the evals have no ground truth
  and the product solves the wrong problem, which is RAND's first root cause.
- **Pilot purgatory.** Demos are easy. If nobody owns monitoring, cost and support after launch, the pilot never becomes
  a product. Name that owner before the pilot starts.
- **Governance as a final gate.** A risk partner who sees the system for the first time a week before launch can only
  say no. Involved from the start, they shape something they can approve.
- **Measuring activity.** Count use cases live, decisions improved and hours saved, not models trained or prompts
  written.
- **Ignoring the people whose work changes.** The operations team using the tool decides whether it gets used. Bring
  them in as reviewers early, and they'll own it.

## What I'd do in the first month

1. Name a business owner and one measurable outcome for the first use case.
2. Fill the accountability table above, even with names that are temporary.
3. Hire or second an AI engineer and a data engineer before anyone else.
4. Write the scorecards and work samples before posting the job ads.
5. Book weekly time with two or three domain experts, and treat it as part of the project budget.

The rest of this site applies the same idea at small scale: every project has an owner, a use-case card, evals and a
human approval step, mapped to the [governance standard](governance.md). For the questions a leader should ask once
the team is running, see [Is our AI behaving?](questions-for-your-ai-team.md).
