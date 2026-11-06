---
date: 2026-11-06
slug: eon-mcp-gateway
short: "One MCP gateway for people and agents"
categories: [Agents, Security, AI governance]
tags: [mcp, amazon bedrock agentcore, cedar, least privilege, sso, multi-cloud, sre agent, AutoPublished]
audience: [CTOs and heads of technology, AI and ML engineers, "Risk, compliance and legal"]
section: AI insight
---

# One MCP Gateway for Every Engineer and Agent: A Practical Access Model on Amazon Bedrock AgentCore

Once engineers and agents both use AI tools against production systems, someone has to decide who can call which tool, and where that decision is written down. One company's answer was to put every investigation tool behind a single gateway, with one policy file covering people and its incident agent. The access model is worth studying even if you never touch the product.

<!-- more -->

## What it is

Eon, a cloud backup and data company, needed its engineers and an autonomous SRE agent to pull logs, metrics, pull requests and cloud health data from AWS, Azure and GCP. Each developer ran several MCP servers on their own machine, each new tool added another credential to manage and rotate, and onboarding took about two days per developer. Instead of building a custom reverse proxy with authentication logic, Eon chose Amazon Bedrock AgentCore's MCP Gateway, as described in a [case study on the AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/how-eon-built-multi-cloud-investigation-with-an-mcp-gateway-on-amazon-bedrock-agentcore) co-written with Eon.

The gateway sits behind a single URL. Developers using Claude Code, Cursor or Codex sign in once with corporate SSO, federated through Amazon Cognito. The agent, which runs Claude on Amazon Bedrock, gets its own machine identity. Behind the URL, dozens of MCP servers expose hundreds of tools, hosted in AgentCore Runtimes across several AWS accounts. The runtimes use service credentials kept in a vault, so no developer carries a per‑tool token. Each account trusts the gateway's execution role through one IAM trust policy rather than VPC peering or PrivateLink.

The part I care about is the rulebook. Every tool call is checked against Cedar policies before the gateway forwards it. People in approved SSO groups, mapped to job roles, can read. The agent can write only where a policy names its identity, and only for small things like commenting on a pull request or ticket. Production is read‑only, granted just in time after approval, and audited. Changes to the policies go through reviewed pull requests, like any other code.

[AWS's documentation for AgentCore Policy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-getting-started.html) fills in the semantics. In ENFORCE mode nothing is allowed unless a policy permits it, and a matching forbid always wins. A rule can look at a tool's inputs too; the docs' example allows a refund tool only when the amount is under 1000. Each decision is logged to CloudWatch.

Why put this at the gateway rather than in the prompt? Joris Conijn [makes the case well for Xebia](https://xebia.com/blog/cedar-policies-for-amazon-bedrock-agentcore-gateway/): instructions in a prompt only nudge a model, and prompt injection can talk an agent into a tool it shouldn't use, whereas a gateway policy stops the call before any tool code runs. He still keeps checks inside the tools, because the gateway only governs calls that actually pass through it.

Eon's reported results: no per‑system credentials for developers (one SSO login), local MCP processes per machine down from 10 to 0, onboarding down from two days to two minutes, and one Cedar policy covering humans and agents, across more than 100 developers and about 10,000 sessions over several months. These are Eon's own numbers in a post co‑written with AWS; nobody has checked them independently, and cost, latency and error rates aren't reported.

It wasn't frictionless. The policy grew towards its size quota as tool schemas were indexed, so large tool catalogues moved to a DYNAMIC listing mode that gives up semantic tool search. The coding tools expected an OAuth parameter the gateway didn't use, so Eon built a shim. And it trims the tool list per developer to cut noise and accidental calls.

## Why it matters beyond AI labs

The pattern isn't limited to software engineering teams. I'd expect it to suit any regulated firm that lets engineers or analysts point AI coding tools and agents at production systems:

- **Financial services**: Picture a hypothetical asset manager whose data team is investigating a broken overnight NAV feed. Humans get read‑only access to logs, data‑quality metrics and the pipeline's code repo through one gateway; an incident agent can read the same tools and may only post a comment on the ticket. Production access requires just‑in‑time approval and is logged. The policy file is reviewed like code, so an auditor can see who could do what on any date.

- **Insurance**: My expectation is that a claims team would use the same split: analysts read claim data through the gateway by role, and an agent can annotate a claim but never change the record.

- **Healthcare**: The same idea could limit who reads patient‑related systems by role, with an agent restricted to adding notes. That's speculation on my part; the sources only cover an engineering team.

What carries over isn't the product. It's having one place where "who can call what" is written down, reviewed and logged, for people and agents alike.

## What I'd watch out for

| Risk | Mitigation |
|------|------------|
| **Single point of failure** – one gateway handles all calls. | It's a managed service, so I'd ask AWS what availability and regional set-up it offers, and rehearse what an investigation looks like when the gateway is down. |
| **Policy correctness** – a broad permit can expose many tools unintentionally. | Adopt default‑deny, keep permits narrow, and review policy changes via pull requests. Test policies against sample inputs before merging. |
| **Calls that bypass the gateway** – tool code could be invoked directly. | Keep defensive checks inside each tool; enforce that all production calls route through the gateway. |
| **Vendor lock‑in** – reliance on Amazon Bedrock AgentCore and Cedar. | I'd keep the role-to-tool mapping in a plain, reviewed file of my own, so it could be regenerated for another policy engine. |
| **Unverified metrics** – cost, latency, error rates not reported. | Measure these in your own environment before scaling. |

Against [the governance standard](../../blog/posts/governance.md), this design puts several controls in one place: read‑only by default with explicit permits for any write (SEC-03), and no secrets on developer machines (SEC-01). It only partly meets two others. Production access needs an approval, but the source doesn't say a named person gives it, which HITL-02 asks for; and policy decisions go to CloudWatch, which is a start on a run log but not the per‑call model, token and cost record OBS-01 asks for. It also helps with prompt injection (SEC-02): an injected instruction can't widen what the agent is allowed to call.

## What I'd try next

1. **Plan for policy size early** – Eon's policy approached its size quota, and the fix cost semantic tool search on large catalogues. With hundreds of tools, I'd decide up front which targets stay fully indexed and which go dynamic, rather than finding the limit in production.

2. **Test the agent's limits, not just the humans'** – The agent can only comment, but that only holds for tools reached through the gateway. I'd list every tool the agent could reach by any other route, and attack the comment‑only rule with injected instructions to see whether anything slips past.

3. **Cost and latency profiling** – The case study does not report these metrics. I'd put three tools behind a gateway and measure the time each tool call adds and the cost per 1,000 calls, against calling the same tools directly.

4. **Keep the trust policies in view** – The gateway centralises who can call what, but the IAM trust policies still live in each account. I'd generate them from the same reviewed repository as the Cedar policies, so the two can't drift apart.

What would change my mind: published latency and cost figures showing the gateway becomes a bottleneck at scale, or evidence that teams route around it to get work done. Either would make the single front door less attractive than it looks here.

*Drafted with AI agents: a local model on my own server wrote the first draft from a topic my scout found, Claude reviewed and edited it, it passed every automated check, and I approved it for publishing.*
