---
name: portfolio-project
description: Create, update or publish an AI-workflow portfolio project (spec, runnable repo, governance mapping, AWS path, blog post) in Ruairi's ai-portfolio repo from a use case and domain.
---

# Portfolio project generator

Turns "use case + domain" into a published portfolio project that matches the existing
ones. The repo is the source of truth; Ruairi edits it directly, so **always read before
you write** and treat human edits as authoritative.

## 0. Load context (every time)

Read, in this order:

1. `CLAUDE.md` (repo rules) and `portfolio.yaml`
2. `factory/style-guide.md`, `factory/stack-catalog.md` (incl. diversity matrix)
3. `governance/controls.md` — the control IDs every project must map
4. `factory/project-spec.template.yaml`, `factory/templates/blog-post.md`
5. The reference implementation `projects/altdata-triage/` (structure, `llm.py`, `guardrails.py`,
   `evals.py`, `store.py`, `config/`, `docs/`) and its post `site/blog/posts/altdata-triage.md`
6. What changed since Claude last worked here:
   `git log --since="30 days ago" --format='%h %an %s' -- factory governance specs site projects`
   then `git show` any commit **without** a `Co-Authored-By: Claude` trailer. Those are Ruairi's
   edits: follow any new conventions they imply, and never overwrite hand-edited prose — propose
   changes to those passages instead.

If the request is an update (e.g. "I changed the governance standard", "refresh the trade-ops
post"), skip to the matching step below.

## 1. Spec (checkpoint)

- Create `specs/<slug>.yaml` from the template using the user's use case and domain.
- Choose the pattern (workflow / rag / agent / multi-agent): the **simplest** that solves it.
- Choose the stack from `stack-catalog.md`: most-common defaults, but vary at least two layers
  versus existing projects (check the diversity matrix) and list what the project uniquely `showcases`.
- 3–6 FRs, 4–6 NFRs with targets, risk tier with rationale, 3–5 `governance.deep_dive` controls,
  `not_applicable` with reasons, synthetic data including ≥1 adversarial and ≥1 compliance case.
- **Show the spec to the user and wait for approval** before building (it's the expensive step).
  Set `status: spec-approved` once they agree.

## 2. Build the repo — `projects/<slug>/`

Mirror the reference layout:

```
README.md  LICENSE  pyproject.toml (or package.json)  Makefile  Dockerfile  .env.example  .gitignore
config/settings.yaml   config/models.yaml        # same keys as reference; add domain keys
prompts/<name>.v1.md
src/<package>/  (workflow/agent, guardrails, llm registry adapter, evals, store/audit, cli)
evals/golden_set.yaml
src/<package>/ui.py  + tests/test_ui.py         # Streamlit app: Input → Run → Output (see style guide)
src/<package>/demo.py                           # copy from a sibling: per-visitor sandbox + links back (blog, source, console)
src/<package>/telemetry.py                      # written by scripts/sync_telemetry_client.py — never hand-edit
Dockerfile.space                                # hosted demo (port 7860, PORTFOLIO_DEMO=1, baseline built with GOVERNANCE_TELEMETRY=off)
.streamlit/config.toml                          # gatherUsageStats = false
scripts/generate_sample_data.py                 # deterministic, seeded, fictional names
tests/                                          # unit tests per control + one offline end-to-end
docs/architecture.md  docs/governance.md  docs/aws-native.md
infra/aws/  (main.tf, variables.tf, outputs.tf, terraform.tfvars.example)
.github/workflows/ci.yml
```

Rules:
- Runs offline with the mock provider in < 5 minutes; switching to Anthropic/OpenAI/Bedrock is an alias change.
- Reuse the reference `llm.py` registry/budget/fallback code (copy, then adapt). Keep code short and readable.
- Numbers come from code/SQL. The model drafts, classifies or explains within schema + policy.
- Agents: read-only tools by default; every write tool behind a human-approval step; cap tool calls and cost.
- RAG: record chunking config, embedding model and index version per answer; include a no-answer case.
- `docs/architecture.md`: Mermaid flow (+ sequence if interactive) wrapped in snippet markers
  `<!-- --8<-- [start:flow] -->` … `[end:flow]`, and a decisions table in `[start:decisions]` … `[end:decisions]`.
- `docs/governance.md`: a row for **every** control ID with status ✅/🟡/⚪/🔷, how, config key, and options not built;
  plus a model-migration runbook.
- Use `{{SITE_URL}}`, `{{GITHUB_OWNER}}`, `{{HF_OWNER}}`, `{{BLOG_TITLE}}` placeholders for cross-links.
- Governance telemetry: `telemetry.register(ROOT)` + one `visit` per session in the app; `telemetry.require_enabled(action)`
  before every model call or write; one `telemetry.record(...)`/`emit(...)` per run with model, tokens, cost, latency,
  records in/out and flags. Counts, hashes and flags only — never prompts, questions or documents. Tests set
  `GOVERNANCE_SPOOL` to a temp file (see a sibling's `tests/conftest.py`, which also has a stand-in console).
- Add a `demo:` block (title, emoji, short_description) to the spec for the Hugging Face Space.

## 3. Verify (don't skip)

Run and fix until all pass:
```
pip install -e ".[dev]" && <cli> all && <cli> eval && pytest -q
python scripts/check_governance.py <slug>
python scripts/sync_telemetry_client.py && python scripts/build_catalog.py   # new project → console catalog
```
Then open the app in a real browser (Playwright + the preinstalled Chromium, or `<cli> ui` locally): load the
default, run it, try the break-it input, do the human step, and look at screenshots. Headless tests passing is
not the same as the page looking right.
Record real numbers from the run (results table, cost, token counts) for the README and post.
Never claim something runs, or quote a figure, you didn't observe.

## 4. Blog post — `site/blog/posts/<slug>.md`

Follow `factory/templates/blog-post.md` and the voice in the style guide (first person, 1,200–1,800 words).
Pull diagrams and the decisions table in with snippets:
`--8<-- "projects/<slug>/docs/architecture.md:flow"`. Governance section covers the spec's
`deep_dive` controls: risk → how handled → config knob → option not built. Be explicit about
what's mocked or not yet built.

Then update `site/index.md` (projects table, with the live-demo link), the diversity matrix in
`factory/stack-catalog.md`, and run `mkdocs build --strict`. Open the governance console locally with the new
project's events (`GOVERNANCE_URL=http://localhost:8600`) and check it appears with its controls.

## 5. Package and publish

- `scripts/publish_project.sh <slug>` → `dist/<slug>/` + zip (runs the governance check, substitutes placeholders).
- Only with the user's explicit go-ahead: `scripts/publish_project.sh <slug> --push` (creates/updates the public repo).
- Hosted demo: any project with a `Dockerfile.space` is deployed by the **demos** workflow to the configured target
  (`demos.target` in portfolio.yaml: selfhost | huggingface | cloudflare | cloudrun). `python scripts/demos.py list`
  shows it; the image must serve at a root or under `/<slug>/` (Streamlit reads `STREAMLIT_SERVER_BASE_URL_PATH`;
  FastAPI apps need a `ROOT_PATH` like the console). Never deploy from a session without the user's go-ahead.
- Set spec `status: built` (or `published` — the script does this on push). Commit with a clear message.

## Update flows

- **Governance standard changed** → `python scripts/check_governance.py`; add/rename rows in every
  project's `docs/governance.md`; implement or mark 🔷 with an option; mention new controls in posts only
  where they're a deep-dive.
- **Template/style changed** → regenerate the affected sections of each post, preserving hand-edited passages.
- **Existing external project (e.g. eod-heartbeat)** → don't regenerate: add the missing standard pieces
  (governance mapping, evals, registry aliases, AWS doc, CI) to the existing code and write the post.
