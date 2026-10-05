# Editorial agents

A **scout** keeps a ranked, varied queue of AI topics from open sources, scored for engagement, novelty against
what's already published, and how many market sectors could use each one. The owner picks from a weekly email. A
weekly **writer** (a scheduled Claude task) drafts a post from the top pick, an independent **editor** reviews it
twice, and the draft arrives as a pull request. **Nothing publishes until the owner merges it.** Readers can
subscribe and get an email when a post goes live.

Write-up: [{{SITE_URL}}/personal/editorial-agents/]({{SITE_URL}}/personal/editorial-agents/)

```bash
pip install -e ".[dev]"
make all     # offline: scout on recorded fixtures, topic email to warehouse/outbox, eval gate (< 1 s)
make test    # 15 tests
make serve   # queue page + pick / dismiss + scheduler on http://localhost:8810
```

## Use-case card (HITL-04)

| | |
|---|---|
| **Intended use** | Suggest blog topics and draft posts for the owner's own site, for the owner to edit and approve |
| **Not for** | Publishing without review; anything presented as client or employer work; copying sources |
| **Decides** | Nothing on its own. The owner picks topics and merges (or withholds) every post |
| **Data** | Public titles, summaries and links from official APIs and feeds; subscriber email addresses (double opt-in) |
| **Owner** | Ruairi Powers |
| **Risk tier** | Medium: publishes under the owner's name; emails real people |
| **Known limits** | TF-IDF novelty misses paraphrases; the offline classifier is keyword-based; source signals measure attention, not quality; the editor is a model and can be wrong |

## How it fits together

- **Scout** (`src/editorial/scout.py`): collect → injection screen → classify (local model, or the deterministic
  mock) → score (engagement percentile within each source + interest + recency; novelty vs. published posts; sector
  breadth) → MMR re-rank → the queue holds `queue.size` topics (default 10). Picks are pinned; dismissals refill.
- **Owner's email** (`digest.py`): the ranked list with signed, expiring, single-use Pick / Dismiss links that open a
  confirmation page (a GET never changes anything).
- **Writer + editor**: `.claude/skills/weekly-post/SKILL.md`, run weekly as a scheduled Claude task. The editor is a
  separate subagent given only the draft, the sources and the code checks (`editorial review`), scored against
  `prompts/editor.v1.md`. Two rounds, then a PR labelled `draft-post`.
- **Draft email**: `.github/workflows/draft-post.yml` → `scripts/draft_email.py`.
- **Publish**: merge. The scout marks the topic published from the PR (`github_sync.py`, public API, read-only).
- **Subscribers**: the site assistant (`projects/site-assistant/src/siteassistant/subscribers.py`).

## Configure

Everything is in `config/settings.yaml` (queue size, weights, schedule, sources, checklist thresholds) and
`.env` (see `.env.example`). Sources are official APIs and feeds only; Reddit needs a free API app; LinkedIn is not
used (no public API; its terms forbid scraping).

Docs: [architecture](docs/architecture.md) · [governance mapping](docs/governance.md) · [AWS path](docs/aws-native.md)

## License

Apache-2.0, by Ruairi Powers, built with Claude: keep the NOTICE file and credit the project if you reuse it (see [NOTICE](NOTICE)).
