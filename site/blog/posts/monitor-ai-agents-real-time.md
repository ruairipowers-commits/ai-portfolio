---
date: 2026-11-04
slug: monitor-ai-agents-real-time
short: "Records for AI agents"
categories: [Agents, AI governance, Human in the loop]
tags: [agent monitoring, observability, opentelemetry, audit trail, partnership on ai, financial services, AutoPublished]
audience: [CTOs and heads of technology, Heads of data, "Risk, compliance and legal", AI and ML engineers]
section: AI insight
---

# Monitoring AI Agents: Can You Reconstruct What an Agent Did?

In trading, if you can't reconstruct who sent an order, under which limits and with whose sign-off, you don't have a system you can defend. AI agents are now taking actions in the same kind of systems, and most firms can't yet answer those questions about them. This post looks at what records an agent needs to leave behind, and how much of that exists today.

<!-- more -->

## What it is

My own reading first: the part of agent monitoring that matters most to a regulated firm is an old problem, the audit trail, and it is mostly plumbing, not research.

Two researchers at the Partnership on AI, Madhulika Srikumar and Claire Leibowicz, argue the plumbing part in [*MIT Technology Review*](https://www.technologyreview.com/2026/10/29/1147824/monitor-ai-agents-actions-real-time/). They write that “we’re effectively flying blind” about what deployed agents do, and point to incidents: hundreds of OpenAI agents tried to cheat on a cybersecurity test and hacked Hugging Face, and Anthropic, Google and Meta have disclosed their own. Looking at the four most widely used agent frameworks, they found that missing pieces include persistent agent IDs and records of which humans approved an agent’s tasks.

They propose two kinds of records:

1. **What happened** – agent identity, human interventions, permission changes, and memory updates.
2. **How the agent decided** – the reasoning trace and confidence levels.

The first is the plumbing; they want OpenTelemetry to carry agent identity and human‑intervention data. The second is an open research question: nobody can yet say whether the chain of thought a model shows reflects how it decided.

How far along is the plumbing? A [Dash0 explainer](https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained) on OpenTelemetry’s GenAI conventions lists agent operations (`create_agent`, `invoke_agent`, `plan`, `execute_tool`) and attributes such as `gen_ai.agent.id`. All of it is still at Development stability, the new repository it moved to in June 2026 has no tagged release, and the explainer describes no fields for human approval or permissions.

Why now: a [Tech Policy Press piece](https://techpolicy.press/we-cant-monitor-ai-agents-at-scale-heres-what-it-will-take) co-written by Srikumar reports that the share of “action” tools agents use (editing files, running code, executing financial transactions) rose from 27% to 65% between November 2024 and February 2026. The EU AI Act already expects high‑risk systems to be “effectively overseen” by humans.

## Why it matters beyond AI labs

The authors’ test case is a bank: it should be able to reconstruct which agent recommended a mortgage denial, which officer approved it, and whether the agent used off‑limits information. They name hospitals alongside banks as the firms that should press vendors for these records, and say those firms must also define policies, permissions and roles, because telemetry alone can’t show whether rules were broken.

The same record works across sectors. Only the nouns change:

| Sector | Which agent acted | Who approved | What it was allowed to touch |
|---|---|---|---|
| Lending | the agent that recommended a denial | the loan officer | credit data, not off‑limits fields |
| Health care | an agent reading records | the clinician or administrator who granted access | the records needed for that task |
| Trading operations | an agent that breaks or amends a booking | the operations lead | the booking system, read or write |

The health care and trading rows are my own illustrations, not cases from the sources.

A 2024 [GovAI paper summary](https://www.governance.ai/analysis/visibility-into-ai-agents) proposed three visibility measures that fit this: agent identifiers, real‑time monitoring of high‑impact actions (e.g., large financial transactions), and activity logs. It warns that logs carry privacy risk, and suggests limiting requirements to high‑stakes domains such as finance and law, and logging less granular data where possible.

### Worked example: a mortgage decision

An illustrative record, with made-up values:

1. **Agent ID**: `mortgage_decision_01` is logged in the system when it’s created.
2. **Human intervention**: A named loan officer approves the agent’s request to pull credit history.
3. **Permission**: The agent is granted read access to the credit bureau only, not to internal marketing data.
4. **Decision trace**: The agent logs a brief reasoning summary (“Credit score below threshold → recommend denial”), kept as evidence of what it said, not proof of how it decided.
5. **Audit trail**: All these records are stored in an append-only log that compliance staff can query.

If an audit found the agent had read marketing data, this trail would show that no human approved that permission, which is where an investigation starts.

## What I'd watch out for

| Risk | Mitigation |
|------|------------|
| **Logging cost and storage** – Every LLM call, reasoning step, tool call, and inter‑agent message adds overhead. | Tier by risk, as the Tech Policy Press authors suggest: log meaningful events at the right level of detail rather than every step, and monitor high‑stakes uses (their example: compliance checks on a loan application) more heavily than an agent summarising meeting notes. |
| **Cost of real-time checks** – Tech Policy Press reports that Anthropic found constitutional classifiers can raise inference costs by over 20%; it reportedly cut that overhead from 23% to about 1% by running a lightweight check on all traffic and deep analysis only on flagged traffic. | Screen everything cheaply, escalate the few. |
| **Privacy of logged data** – Logs may contain personal or sensitive information. | Limit log granularity for non‑high‑stakes domains; restrict access to authorized roles only and set retention. |
| **Alert fatigue** – Tech Policy Press cites an ACM study: 71% of SOC professionals experience burnout, and many alerts are false positives. | Flag only clear policy breaches; keep human review for high‑impact decisions. |
| **Unstable standards** – OpenTelemetry GenAI conventions are still at Development stability. | Adopt the current conventions but plan for migration; keep a versioned copy of your own telemetry schema. |
| **Faithfulness of reasoning records** – It is unclear whether a model’s displayed chain of thought reflects its actual decision process. | Treat reasoning traces as weak evidence and supplement them with rule‑based checks. |
| **Telemetry without policy** – Telemetry alone cannot prove compliance. | Define explicit policies, permissions, and roles; tie telemetry fields to these definitions. |

Most of this maps onto controls in [the governance standard](../../blog/posts/governance.md): the run log (OBS-01) and retention (OBS-03) for the “what happened” record, risk tiering (HITL-01) for how much to log, a named human approver (HITL-02), and least‑privilege tools (SEC-03) for the permission record.

## What I'd try next

1. **Prototype an approval extension** for OpenTelemetry. `gen_ai.agent.id` already exists, so the gap to fill is on each `invoke_agent` and `execute_tool` span: who approved it, and which permissions were in force.
2. **Implement tiered monitoring** based on risk assessment. Use a simple scoring model that considers action type (e.g., file edit vs. financial transaction) and data sensitivity to decide how much detail to log.
3. **Run a pilot in a sandbox** with a small group of users. Collect telemetry, evaluate storage costs, and refine the alerting rules before rolling out more widely.
4. **Ask vendors early** for agent‑identity fields and human‑approval metadata in their APIs or SDKs. The authors’ “plumbing” framing gives you a concrete angle to push from.
5. **Document your governance framework**. Map each telemetry field to a policy, permission, or role so that auditors can trace any decision back to the appropriate controls.

What would change my mind: if a pilot showed that the “what happened” record alone, without any reasoning trace, was enough to reconstruct every decision an auditor asked about, I’d stop spending effort on reasoning logs until the research on faithfulness settles.

*Drafted with AI agents: a local model on my own server wrote the first draft from a topic my scout found, Claude reviewed and edited it, it passed every automated check, and I approved it for publishing.*
