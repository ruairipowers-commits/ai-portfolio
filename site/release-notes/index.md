---
icon: material/rocket-launch-outline
hide: [navigation]
---

# Release notes

The big changes to this portfolio, newest first. Each project's repository has the detail in its commit history.

## 2 October 2026

**Technology pages.** Every technology named in a post's stack line, or in a project table, now links to its own page.
Each page has a description, typical use cases, how it shows up in AI work, where this portfolio uses it, pros and
cons, a minimal example and a link to the vendor's documentation. They're all listed on
[Technologies](../tech/index.md).

**Featured and personal projects.** Featured projects stay on the home page and in the main blog. Smaller personal
ones get their own [Personal projects](../personal/index.md) page and blog. Which is which is one list in
`portfolio.yaml`.

**Governance escalation.** The [governance console](../blog/posts/governance-console.md) now acts on what it sees.
- When a workflow reports a governance issue, the console opens an incident. Examples are an AI-proposed step
  outside the runbook, restricted content reaching someone, a bank-detail change request, an injection, a failed
  eval or data gate, a budget or spend anomaly, or an unregistered AI tool.
- Serious issues switch the workflow off automatically.
- It emails the workflow's escalation list with the details and a link straight to the incident. There, someone
  records the root cause, the fix and where it's documented, then switches the workflow back on.
- The recipients and the severity levels for emails and switch-offs are set per workflow on a Settings page.
- PagerDuty and ServiceNow ticketing is designed, with payloads shown on each incident, but not built yet.
- There's a walkthrough video in the post.

**Live demos on my own hardware.**
- Every demo runs at `demos.agentls.com/<app>` on a small home server, behind a Cloudflare Tunnel, at no cost.
- The server deploys each change automatically once its tests pass on GitHub. It keeps serving the last good
  version if a build fails, and comes back on its own after a reboot.
- The deployment target is one setting: self-hosted, Hugging Face Spaces, Cloudflare Containers or Google Cloud Run.
- Every project's tests run on every push.

**The demos look like the blog.** The Streamlit apps carry the blog's header, with links to the write-up, the
source and the governance console.

**The governance console.** It's one place to see every AI workflow: usage, spend (daily and cumulative), data
throughput, safety signals, control coverage with live evidence and attestations, a models inventory, and a kill
switch the workflows enforce. Every project reports to it through the same small telemetry client. New projects
appear automatically, and unregistered ones are flagged as shadow AI.

**Two new projects.**
- [Research Q&A](../blog/posts/research-qa-rag.md): cited answers over filings and broker research, with
  entitlement filtering inside retrieval and a refusal when the evidence isn't there.
- [EOD heartbeat](../blog/posts/eod-heartbeat.md): finds end-of-day breaks with SQL and explains them from the
  firm's own runbooks.

## 1 October 2026

**A browser app for every project.** Each project got a Streamlit app built the same way: a default input, a Run
button and the results, plus a *Try to break it* panel.
- **Trade-ops app:** a data explorer, a row-driven exception queue and a single-trade walkthrough where you play
  each role.
- **Alt-data app:** view, edit, download and reset each vendor's sample data.

## 30 September 2026

**The portfolio factory.**
- [The governance standard](../blog/posts/governance.md): 30 controls that every project maps itself against.
- A spec-driven template for new projects: a runnable repo, an offline mock model, a governance mapping, an
  AWS path and a write-up.
- The first project: [Alt-data vendor triage](../blog/posts/altdata-triage.md).
- Personal details are resolved at build time rather than committed.

**[Trade-ops exception agent](../blog/posts/trade-ops-exceptions.md).** A LangGraph agent investigates settlement
breaks using read-only tools from a TypeScript MCP server. It proposes a fix and waits: nothing is written until
a named analyst approves.
