# CLAUDE.md — ai-portfolio

This repo generates Ruairi Powers' AI-workflow portfolio: a blog site (MkDocs Material → GitHub Pages)
and one runnable public repo per project. To create or update a project, follow
`.claude/skills/portfolio-project/SKILL.md`.

## Where the truth lives

| What | File | Who edits |
|---|---|---|
| Author, URLs, project order | `portfolio.yaml` | Ruairi |
| Governance controls (IDs) | `governance/controls.md` | Ruairi — the governance post and every project check read it |
| Voice, structure, repo conventions | `factory/style-guide.md` | Ruairi |
| Default tools + diversity | `factory/stack-catalog.md` | both |
| Per-project intent | `specs/<slug>.yaml` | both (Claude drafts, Ruairi approves) |
| Code + docs | `projects/<slug>/` | both |
| Posts | `site/blog/posts/*.md` | both |
| Open items and work in flight | `STATUS.md` | both — read it at the start of a chat; update it before ending one |

## Rules

- **Human edits win.** Before changing any file, check `git log` for commits without a
  `Co-Authored-By: Claude` trailer; those are Ruairi's. Adopt the conventions they imply and don't
  overwrite hand-edited prose — suggest changes instead.
- Every project maps every control (`python scripts/check_governance.py` must pass).
- Everything runs offline with a mock model; never claim a result you didn't run.
- Don't push to GitHub or publish repos without explicit approval in the conversation.

## Commands

```bash
pip install -r requirements-site.txt && mkdocs serve        # preview site at localhost:8000
python scripts/check_governance.py                          # control coverage across projects
scripts/publish_project.sh <slug> [--push]                  # package / publish a project repo
cd projects/<slug> && pip install -e ".[dev]" && make all test
```
