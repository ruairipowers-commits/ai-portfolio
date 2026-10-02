---
hide: [navigation]
---

# AI workflows for investment firms — built, governed, runnable

I'm Ruairi Powers. I've spent 25 years building data, trading and research platforms at
Bridgewater, Two Sigma and Neudata. This portfolio shows how I design AI workflows for a fund:
each project starts from a business problem, runs on a laptop in five minutes, and is held to the
same [governance standard](blog/posts/governance.md).

## Projects

<!-- projects:featured -->

### Governing them

<!-- projects:platform -->

Every workflow above reports each visit and action to the console — usage, cost, data throughput, safety signals —
and obeys its kill switch. Use any demo, then find yourself in the console with *Include simulated history* unticked.

Smaller things I've built for myself are on [Personal projects](personal/index.md); what's changed is in the
[release notes](release-notes/index.md).

## What every project includes

- A write-up: business problem, functional and non-functional requirements, architecture diagrams and the *why*
- A browser app (Streamlit): a default input, a Run button and the results — plus a "try to break it" input —
  hosted as a live demo where every visitor gets a private copy of the data
- A public repo that runs offline with a mock model — no API keys — and switches to Claude, OpenAI or Bedrock by config
- A control-by-control governance mapping, with configuration and the options I didn't build
- An AWS-native path: Terraform starter and a local-vs-AWS comparison
- Tests, a golden-set eval gate, and CI
- Telemetry to the [governance console](blog/posts/governance-console.md) and a kill switch it controls

## Start here

**[How I govern AI workflows →](blog/posts/governance.md)** — the 30 controls behind every project:
data preparation, AI security, cost oversight, model migration, evals, audit and human oversight.
