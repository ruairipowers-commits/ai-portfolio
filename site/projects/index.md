---
icon: material/briefcase-outline
---

# Projects

<nav class="subtabs" markdown>
[Industry projects](index.md){ .active }
[Personal projects](../personal/index.md)
</nav>

AI workflows for the problems an investment firm actually has: vendor data triage, end-of-day breaks, trade
exceptions and research questions. Each one starts from a business problem, runs on a laptop in five minutes, and
is held to the same [AI governance standard](../blog/posts/governance.md).

<!-- projects:featured -->

## Governing them

<!-- projects:platform -->

Every workflow above reports each visit and action to the console (usage, cost, data throughput, safety signals)
and obeys its kill switch. Use any demo, then find yourself in the console with *Include simulated history* unticked.

## What every project includes

- A write-up: business problem, functional and non-functional requirements, architecture diagrams and the *why*
- A browser app (Streamlit): a default input, a Run button and the results, plus a "try to break it" input,
  hosted as a live demo where every visitor gets a private copy of the data
- A public repo that runs offline with a mock model (no API keys) and switches to Claude, OpenAI or Bedrock by config
- A control-by-control governance mapping, with configuration and the options I didn't build
- An AWS-native path: Terraform starter and a local-vs-AWS comparison
- Tests, a golden-set eval gate, and CI
- Telemetry to the [governance console](../blog/posts/governance-console.md) and a kill switch it controls

Smaller things I've built for myself are under [Personal projects](../personal/index.md).
