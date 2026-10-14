# AGENT.md — ai-portfolio

This repo generates Ruairi Powers' AI-workflow portfolio: a blog site (MkDocs Material → GitHub Pages)
and one runnable public repo per project. To create or update a project, follow
`.agents/skills/portfolio-project/SKILL.md` (or `.claude/skills/portfolio-project/SKILL.md`).

This file governs all AI agents acting as developers on this repository (Claude, Gemini, GPT, Perplexity, and local Evo-X1 LLaMA).

---

## Where the truth lives

| What | File | Who edits |
|---|---|---|
| Author, URLs, project order | `portfolio.yaml` | Ruairi |
| Who can see and reuse each project (open → hidden) | `portfolio.yaml` `access` → `scripts/apply_access.py` | Ruairi |
| Governance controls (IDs) | `governance/controls.md` | Ruairi — the governance post and every project check read it |
| Voice, structure, repo conventions | `factory/style-guide.md` | Ruairi |
| Default tools + diversity | `factory/stack-catalog.md` | both |
| Per-project intent | `specs/<slug>.yaml` | both (Agent drafts, Ruairi approves) |
| Code + docs | `projects/<slug>/` | both |
| Posts | `site/blog/posts/*.md` | both |
| Open items and work in flight | `STATUS.md` | both — read it at the start of a chat/task; update it before ending one |

---

## Non-Negotiable Rules

- **Human edits win.** Before changing any file, check `git log` for commits without a co-authored trailer (`Co-Authored-By: Claude`, `Co-Authored-By: Gemini`, etc.); those are Ruairi's. Adopt the conventions they imply and do not overwrite hand-edited prose — suggest changes instead.
- **Strict governance compliance:** Every project must map every control (`python scripts/check_governance.py` must pass).
- **Offline & reproducible:** Everything must run offline with a mock model; never claim an execution result you did not run.
- **Safety barrier:** Do not push to GitHub, merge to `main`, or publish repos without explicit approval in the conversation.
  This includes posts: the `daily-post` skill opens a pull request with the gate's verdict and never merges it.
  Ruairi merges every post (his decision, 14 October 2026).

---

## Multi-Agent Git & Branching Protocol

When working across multiple AI agents, isolate changes on dedicated feature branches:

| Agent | Branch Format | Co-Authored-By Trailer |
|---|---|---|
| Claude | `agent/claude-<slug-or-task>` | `Co-Authored-By: Claude <noreply@anthropic.com>` |
| Gemini | `agent/gemini-<slug-or-task>` | `Co-Authored-By: Gemini <noreply@google.com>` |
| Evo-X1 (LLaMA) | `agent/llama-<slug-or-task>` | `Co-Authored-By: Evo-X1 <llama@local>` |
| GPT | `agent/gpt-<slug-or-task>` | `Co-Authored-By: ChatGPT <noreply@openai.com>` |

---

## Commands

```bash
pip install -r requirements-site.txt && mkdocs serve        # preview site at localhost:8000
python scripts/check_governance.py                          # control coverage across projects
scripts/publish_project.sh <slug> [--push]                  # package / publish a project repo
cd projects/<slug> && pip install -e ".[dev]" && make all test