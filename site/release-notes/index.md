---
icon: material/rocket-launch-outline
hide: [navigation]
---

# Release notes

The big changes to this portfolio, newest first. Each project's repository has the detail in its commit history.

## 5 October 2026

**Two governance posts.** [Is our AI behaving?](../blog/posts/questions-for-your-ai-team.md) is a plain-language
guide for leaders on what to ask their tech team, and what evidence to expect, using a credit model, a customer
assistant and a feedback-analysis AI. [How I govern the AI on this site](../blog/posts/how-i-govern-this-site.md)
walks through this site's own governance step by step, with a link to the code, test or run behind each step.

**A portfolio gallery on Home.** Every project now has a card on [Home](../index.md) with its headline
measured result, how it was measured, and one-click links to the live demo, the code and the write-up.

## 4 October 2026

**Private AI workbench.** A new [personal project](../personal/posts/private-local-ai.md) on the local AI setup
on my mini PC: local models on its integrated GPU, notebooks and creative tools, and exactly what stays home in
its fully local and hybrid modes.

**My current role.** [Home](../index.md), [About](../about.md) and the [resume](../assets/Ruairi-Powers-Resume.pdf)
now include my position since July 2026 as data and analytics director at Silver Ridge Advisors. The Ask button
picks it up from the same pages.

## 3 October 2026

**Safer, watched, backed up.** The demo machine runs code from a public repo, so now:

- **Deploy guard.** A root-owned guard refuses any deploy that could take over the machine (privileged containers,
  the Docker socket, host mounts, missing CPU and memory limits). Every container drops its Linux capabilities, and
  the demo apps have no route to the internet. The demos force HTTPS and send HSTS and the standard security headers.

- **Host tab.** The governance console shows the server's load and history, and emails alerts and a weekly health
  and security report.

- **Backups.** The databases are backed up nightly, integrity-checked, with `.env` encrypted.
- **Updates.** A daily check lists OS, image and model updates with the exact commands to run.
- **Security self-assessment.** It runs on every commit in CI and weekly on the machine, alongside a 30-minute uptime
  check from GitHub.

**Thumbs down and a Console button.** Posts now ask "Was this useful?" with 👍 or 👎. A 👎 can say what was missing;
that's private and goes into the daily email. The site header has a shield button that opens the live governance
console.

**Thumbs up, upvotes and a Content tab.**

- **Posts:** every post ends with "Was this useful?" and a thumbs up. The blog list shows the counts.
- **Suggestions:** project suggestions have their own page under Projects. Visitors upvote ideas, and new ones
  appear once I've approved them.

- **Daily email:** thumbs up by post, and the top ten suggestions with new ones marked. Each suggestion has links
  that start it in Claude as an industry or personal project.

- **Governance console:** a new **Content** tab shows the top-rated articles. It's also where I publish, hide or
  close suggestions.

**Blog filters in the side panel.** On wide screens, the topic, type and date filters sit in the left panel. The
newest post is always first.

**A faster Ask button.** After [measuring three local models](../personal/posts/choosing-the-ask-model.md) on the
server, the default is now `gemma4:e4b`. It's more than twice as fast as the runner-up and more accurate.

**A smarter Ask button.**

- **Every answer starts from a profile card** that the site builds from the posts on each publish: background, MIT
  coursework, evidence by topic, the technologies each project uses, and the newest work first. A new project shows
  up in answers as soon as it's published.

- **It reads more of what's public:** project READMEs and docs on GitHub, the governance controls, the capstone
  notebook's commentary and my resume.

- **Questions about me get cited evidence.** When I don't have something a visitor asks about, the answer says so
  honestly and turns it into a chance to grow. It's now on my plate to review, and the daily email lists those
  questions.

- **Faster:** the model stays loaded, the fixed start of every prompt is cached, and reasoning is switched off. A
  benchmark command compares models on the server, and the setup guide covers using the iGPU through Vulkan.

**How this site was built, and a suggestion box.** [About](../about.md) now explains the framework behind the site:
free, open source, repeatable, CI/CD and expandable, built in days with AI. A generated **Skills and evidence**
section maps every topic and technology to the work that shows it. Visitors can suggest projects for me to try, and
their ideas arrive in my daily email.

**A home page that explains the site.** [Home](../index.md) now says what this site is for: a record of my
journey learning to use and govern AI responsibly, open for others to learn from. It also covers what I bring, how
I directed Claude to build the site, and the two MIT courses, with a link to my resume.

**Projects tab.** The project tables moved from Home to [Projects](../projects/index.md), with sub-tabs for
industry projects and personal projects. The Governance tab is now **AI Governance**.

**Blog topics and filters.** The [Blog](../blog/index.md) now lists every write-up on the site: industry projects,
governance, personal projects and classes. Each post is tagged with topics and keywords, and the list filters by
topic, type and date.

**Classes.** A new [Classes](../classes/index.md) tab covers the two MIT Professional Education courses I took
this year: what each covered, why it matters for AI and agentic workflows, how I've applied it, and the work I
completed. The first explains how the models work. The second covers bringing AI into an organisation responsibly:
frameworks, governance and staged rollout.

**Loan default capstone.** My [capstone](../classes/posts/loan-default-capstone.md) for the first course is now a
project you can run. The notebook opens read-only in Google Colab and reruns end to end. The write-up walks through
the presentation deck, and the project is listed under Personal projects.

**Ask the portfolio.** Every page now has an **Ask** button.

- It searches the whole blog and answers questions with a local open model, citing the sections it used. That
  includes questions about my background and whether I'd fit a role.

- Searches, questions and page views are logged, without IP addresses or cookies.
- A daily email summarises engagement: blog views, searches, demo runs, Cloudflare traffic and GitHub views,
  clones and stars.

- It's governed like the other workflows: the console can switch it off.
- The [write-up](../personal/posts/site-assistant.md) is the first entry on the Personal projects page.

**Narrated walkthrough.** The governance escalation video now has a spoken voice-over: a neutral Piper voice
rendered on the demo server. Page loads, waits and pauses are cut, so the whole loop runs 1 min 23 s.

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
