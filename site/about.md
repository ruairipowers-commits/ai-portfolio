# About

Ruairi Powers — technical product and data engineering leader in financial services, Westport, CT.

- **Bridgewater Associates** (2000–2020): software engineer → trading analytics tech manager → investment engine solution architect → trading QA manager
- **Principles LLC** (2020–2022): product manager, people analytics
- **Two Sigma** (2022–2024): VP, product manager, data engineering
- **Neudata** (2024–2025): SVP, product manager
- BS Computer Science, Rensselaer Polytechnic Institute · Series 3
- MIT Professional Education (2026): [*Applied AI and Data Science*](classes/posts/applied-ai-data-science.md) (16 CEUs);
  [*Applied Agentic AI for Organizational Transformation*](classes/posts/applied-agentic-ai.md) (7 CEUs) — see [Classes](classes/index.md)

Contact: [LinkedIn](https://www.linkedin.com/in/ruairi-powers) · [Resume (PDF)](assets/Ruairi-Powers-Resume.pdf) · [GitHub](https://github.com/{{GITHUB_OWNER}})

## How I built this site with AI

I built this whole site, and every project on it, by working with AI: Claude Code as an agentic engineering partner,
inside a framework I set up so the result would be free, open, reusable and able to keep growing.

<!-- build:stats -->

| Goal | How the framework delivers it |
|---|---|
| **Free to run** | The site is on GitHub Pages. The live demos run on my own mini PC behind a Cloudflare Tunnel. The [Ask](personal/posts/site-assistant.md) assistant uses a local open model. No paid hosting and no per-question API bills. |
| **Open source** | Everything is in a public GitHub repo, and each project is MIT-licensed. |
| **Usable by others** | Every project runs offline in about five minutes with a mock model and no API keys. Every demo gives each visitor a private copy of the data. The [capstone](classes/posts/loan-default-capstone.md) notebook opens in Colab. |
| **Repeatable** | Each project starts as a short spec. A reusable skill turns the spec into a repo, tests, a demo, a governance mapping and a write-up, following a style guide and an instructions file the AI reads every time. |
| **CI/CD** | GitHub Actions runs the tests, evals and governance checks on every change and publishes the site. My server deploys a commit only after its checks pass. |
| **Expandable** | A new project is one line in a config file plus a spec. The project tables, [technology pages](tech/index.md), [blog](blog/index.md) filters, the evidence below and the assistant's knowledge all update from it. |
| **Evolves over time** | [Release notes](release-notes/index.md) record every step. My own edits always win over generated ones. A daily email shows what visitors read, like, search for and ask about, and the [suggestion box](projects/suggestions.md) collects ideas that visitors upvote. |

**AI and agentic workflows, in practice.**

- **Claude Code did the engineering.** It planned, wrote the code, ran the tests, built and checked the site,
  recorded and narrated the demo video, and fixed what failed.
- **Subagents handled side work in parallel**, such as researching course material and drafting technology pages.
  I set the direction, approved the specs and reviewed the results.
- **The projects themselves are agentic and governed:**
  - a [LangGraph agent](blog/posts/trade-ops-exceptions.md) behind an MCP server, where humans approve every write;
  - retrieval with citations in [research Q&A](blog/posts/research-qa-rag.md) and [EOD heartbeat](blog/posts/eod-heartbeat.md);
  - a [governance console](blog/posts/governance-console.md) with telemetry, incidents and a kill switch;
  - this site's own local-model assistant.

**Industry practice, built in.**

- A 30-control [AI governance standard](blog/posts/governance.md) that every project maps, enforced in CI.
- Golden-set evals that gate changes.
- Least-privilege tools with human approval.
- Prompt-injection tests.
- Secrets kept out of code.
- Containers, and Terraform for an AWS path.
- Logging that keeps no IP addresses.

The tools are listed on [Technologies](tech/index.md).

## Suggest a project

What should I try next? [Suggest a project](projects/suggestions.md), or upvote the ideas others have shared. The
top ten arrive in my email every day.

## Skills and evidence

<!-- evidence -->
