# Editorial agents

A **scout** keeps a ranked, varied queue of AI topics from open sources, scored for engagement, novelty against
what's already published, and how many market sectors could use each one. Readers **vote** on the queue from the blog;
the owner picks or dismisses from a daily email. Each day (`.claude/skills/daily-post`, a scheduled Claude task) a
**local model** on the owner's server drafts a post from the top topic, Claude reviews and edits it, an independent
**editor** scores it, and **code decides** the label (`editorial gate`): every check passes and every editor score
is ≥ 4 → `ready-to-publish`; anything else → `needs-work`. Either way it's a pull request, tagged **AutoPublished**,
and **nothing publishes until the owner merges it**. Every run
is logged to compare local drafting against Claude writing (`metrics/routing-runs.jsonl`). Readers can subscribe and
get an email when a post goes live.

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
| **Intended use** | Suggest blog topics and draft posts for the owner's own site, for the owner to approve |
| **Not for** | Publishing without the owner's review; anything presented as client or employer work; copying sources |
| **Decides** | Nothing on its own. Code labels each post ready or needs-work (`editorial gate`); the owner picks or dismisses topics and merges (or withholds) every post |
| **Data** | Public titles, summaries and links from official APIs and feeds; subscriber email addresses (double opt-in) |
| **Owner** | Ruairi Powers |
| **Risk tier** | Medium: publishes under the owner's name; emails real people |
| **Known limits** | TF-IDF novelty misses paraphrases; the offline classifier is keyword-based; source signals measure attention, not quality; the editor is a model and can be wrong, votes are anonymous and per-browser, so a determined person can inflate them |

## How it fits together

- **Scout** (`src/editorial/scout.py`): collect → injection screen → classify (local model, or the deterministic
  mock) → score (engagement percentile within each source + interest + recency; novelty vs. published posts; sector
  breadth) → MMR re-rank → the queue holds `queue.size` topics (default 10). Picks are pinned; dismissals refill.
- **Readers' votes** (`app.py`, `POST /api/queue/{id}/vote`): one per anonymous visitor per topic per day, from the
  blog's origin only (CORS); votes order the queue after the owner's picks.
- **Owner's email** (`digest.py`, daily): the queue in the order it'll be written, readers' votes (total and new), and
  signed, expiring, single-use Pick / Dismiss links that open a confirmation page (a GET never changes anything).
- **Daily post**: `.claude/skills/daily-post/SKILL.md`, a scheduled Claude task. Claude researches and writes a
  brief; the local model (`prompts/local-writer.v1.md`, on the EVO-X1) drafts; Claude reviews and edits; a separate
  editor subagent scores it against `prompts/editor.v1.md`; `editorial gate` labels the PR `ready-to-publish` or
  `needs-work` (with `draft-post`); the owner merges. `editorial routing` logs each run.
- **Weekly post** (`.claude/skills/weekly-post/SKILL.md`): the earlier, review-only path; its scheduled task is paused.
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
