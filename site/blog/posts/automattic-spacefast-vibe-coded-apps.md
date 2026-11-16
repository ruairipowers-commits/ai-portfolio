---
date: 2026-11-15
slug: automattic-spacefast-vibe-coded-apps
short: "Hosting for agent-built apps"
categories: [AI governance, Security, Operations]
tags: [spacefast, automattic, vibe coding, app hosting, shadow it, ai agents, AutoPublished]
audience: [CTOs and heads of technology, "Risk, compliance and legal", Operations leads, Executives and boards]
section: AI insight
---

# Spacefast: Hosting for AI‑Built Apps, and Who Controls Them

When teams outside IT build small apps with agents, the decision I care about is no longer how the code gets written; it’s where the result runs and who controls it. Automattic’s new service, Spacefast, hosts websites and apps built by AI coding agents, and its pitch is aimed squarely at that decision. Here is what it does, where I think it fits, and what I’d check before letting a team use it.

<!-- more -->

## What it is

[TechCrunch reported the launch](https://techcrunch.com/2026/11/09/automattic-debuts-a-platform-to-deploy-vibe-coding-apps-amid-a-changing-internet/) on 9 November 2026. Spacefast is a hosting platform from the owner of WordPress.com, launched publicly after a soft launch in September. It started as a hackathon project called Stattic, focused on static hosting, and grew when users asked for databases and backend features.

The service accepts deployments from the AI coding agent you already use (ChatGPT, Claude, Cursor and others) or from a Git repository. According to [Lapaas Voice’s launch write-up](https://lapaasvoice.com/automattic-launches-spacefast-to-deploy-ai-built-apps-taking-on-lovable-and-emergent/), Spacefast provides:

* Hosting and custom domains
* An SQL database
* File upload storage
* Analytics
* Version history and comments on published projects
* Rollback
* An API, CLI, and MCP server for integration

Spaces are private by default. Sharing is controlled through invitations, passwords or scoped links; sensitive actions such as DNS changes and rollbacks can require approval. TechCrunch lists authentication and email among the backend pieces, but the launch write-up and the pricing page as NxCode read it say built-in app authentication is “coming soon” (sign-in is labelled Beta), and transactional email is also still to come. I go with the more cautious reading.

The platform does not charge for AI model credits – those are paid separately to the agent provider – but it charges for infrastructure. As [NxCode read the pricing page on 10 November](https://www.nxcode.io/resources/news/spacefast-hosting-pricing-ai-built-apps-2026), Personal is free with $1 of monthly usage, Go is $5 a month with $5 of usage, and Pro is $15 a month with $15 of usage. Every plan allows commercial use.

Spacefast’s [skill file for agents (SKILL.md)](https://cdn.jsdelivr.net/npm/spacefast@0.4.1/SKILL.md) lets an agent publish with a plain HTTP call and no account. It instructs agents not to print, commit or log any space keys and tokens, and to keep environment files out of publishes. Each publish returns an immutable version URL and a live URL; anonymous publishes generate a claim link that expires.

## Why it matters beyond AI labs

### The bet behind it

Spacefast competes with Lovable and Emergent, and Figma, Canva and Notion have launched products in the same space. Its difference is that it doesn’t write the code. It assumes the agent is something you bring, and charges for the hosting underneath.

That is the investment question as I see it: if code-generating agents keep getting cheaper and more interchangeable, the durable business may sit in running the output, not generating it. My view, not a sourced one, is that this is a reasonable bet but an unproven one. The founder, Batuhan İçöz, admitted to TechCrunch that users may churn after trying it, and none of the coverage I read gives user or revenue numbers.

### Market sectors that can benefit

1. **Information Technology** – Early users have built internal mockups, slideshows and offer pages: the throwaway prototypes that used to sit on someone’s laptop.
2. **Communication Services** – Event pages and microsites are where marketing teams reach for agents first, and the “IT sprawl” İçöz describes is mostly theirs.
3. **Financial services** – In my view, this is where the access and data questions below matter more than the features, because even a small event page can collect personal details.

### Worked example: a marketing team at an asset manager

Take a hypothetical: a marketing team at an asset manager wants a sign‑up page for a fund event, and uses an AI coding agent to generate it. Today that page might be hosted on one of several vibe‑coding services (e.g., Lovable or Emergent), each with its own billing and access controls.

With one host for these apps:

* **Fewer places to look** – IT has one service to review instead of several.
* **Private default** – The page is not publicly accessible until the team shares it.
* **Approval workflow** – DNS changes and rollbacks can require approval, so pointing a domain at the page or reverting it isn’t one person’s call.
* **Immutable versions** – If a bug is discovered after launch, the team can roll back to a previous version without rebuilding from scratch.

This is the “IT sprawl” pitch İçöz made to enterprises: marketing teams spread across several vibe-coding services. Consolidating hosting gives the firm visibility and a single set of controls. Whether it also saves money is unknown.

Before the page collects a single sign-up, a head of data would want to know a few details from the docs NxCode read:

* **Links prove access, not identity.** A share link or password can be forwarded, and link and password roles stop at viewing or commenting.
* **Grants add up.** Removing one route doesn’t remove another that matches, so revoking access means checking every grant.
* **The database isn’t automatic.** The built-in MySQL database comes with a space running Zero or a Functions worker; a plain static space has no data layer.
* **Billing stays with people.** Plan changes and cancellation happen in the dashboard, not through an agent, and after a failed payment there is a seven-day grace period in which the site keeps serving but writes are blocked. For a sign-up form, blocked writes mean lost registrations.

## What I'd watch out for

| Risk | Why it matters | What I’d do |
|---|---|---|
| **Shadow IT** – Anyone can publish without an account; share links and passwords prove access but not identity. | Uncontrolled deployments may bypass security checks or expose sensitive data. | Tier each app by risk and name an owner (HITL-01, HITL-04); claim anonymous spaces into a managed account. |
| **Missing authentication** – Built‑in app auth is “coming soon”; transactional email is also upcoming. | Personal data should not sit behind a forwarded link. | Keep personal data out of these apps until sign-in ships and has been tested (DATA-03). |
| **Database rollback gaps** – Version history covers files and config but not database state. | A bad release can damage data that a rollback won’t restore. | Use a separate export and backup routine for the database. |
| **Churn and lock‑in** – Switching between agents is easy; portability of apps is uncertain. | Teams may move on quickly, leading to fragmented hosting again. | Keep the source in your own Git repository so the app can move. |
| **Secrets hygiene** – Agents must not log or expose space keys. | A misconfigured agent could leak credentials. | Treat space keys like any other secret (SEC-01) and give agents the least access they need (SEC-03). |

The control IDs come from [the governance standard](../../blog/posts/governance.md) every project on this site is built against.

## What I'd try next

1. **Performance benchmarking** – Run a small app with database queries on Spacefast and compare latency with other hosting options. Spacefast runs on the infrastructure behind WordPress.com and Tumblr, which Automattic says serves more than 15 billion page views a month, but that does not guarantee the same performance for Spacefast apps, and none of the coverage I read includes independent measurements.
2. **Security hardening** – Test the authentication workflow once it’s available, ensuring that only authorized users can see the app or change DNS records.
3. **A rollback drill** – Publish two versions that change the database schema, roll back, and see exactly what is and isn’t restored.
4. **A personal pilot** – Publish one of my own small demo apps through an agent, then check what a reviewer can see: who published it, which version is live, and who has access.

If these experiments show that Spacefast can deliver reliable performance, sound security, and easy integration with existing Git workflows, I would take it seriously as a home for agent-built apps. What would change my mind is evidence of high churn or authentication slipping well past “coming soon”. Until then, I’d use it for prototypes and keep anything that collects personal data elsewhere.

*Drafted with AI agents: a local model on my own server wrote the first draft from a topic my scout found, Claude reviewed and edited it, it passed every automated check, and I approved it for publishing.*
