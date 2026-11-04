---
name: course-news
description: Daily "What's new" scan for the crash course — for each technology with a course, find official releases, features, deprecations and retirements since the last scan, write dated items in our own words with source links, flag changes that may make a course level out of date, publish the items to the course-news branch (they show on the catalog, the What's new tab and the site's Technologies pages), and open a pull request for any proposed status badge (deprecated / replaced / less used / retired). Used by the daily scheduled task when news.scanner is claude.
---

# Daily course news: research → validated items → course-news branch → status PR for Ruairi

Ruairi's decisions (4 November 2026): the scan runs daily; news items show without approval (factual, each links its
official source); a status badge on a course or a Technologies page needs his merge; changes that may make a level
out of date are listed on the course owner page for him to review. Course content stays stable — this scan **never
edits course levels**. You never merge.

Read first: `CLAUDE.md`, `STATUS.md`, `projects/crash-course/src/crash_course/news.py` (the item schema and rules).

## 0. Is this scan on?

`news.scanner` in `projects/crash-course/config/settings.yaml` must be `claude`. If it is `feeds`, the GitHub workflow
`course-news.yml` does the scan: stop and say so.

## 1. Setup

```bash
pip install -q -e projects/crash-course
python scripts/course_news.py pull          # every earlier item, from the course-news branch
cd projects/crash-course && course news-review | head -1 && cd ../..
```

Newest item per course (start each course's search after this date; for a course with none, go back
`news.lookback_days`):

```bash
cd projects/crash-course && python -c "
from crash_course import catalog, news
latest = news.latest_by_course(news.load())
for slug, c in sorted(catalog.bundled().items()):
    print(slug, '|', c.title, '|', latest.get(slug, {}).get('date', '-'), '|', c.docs, '|', c.status)"
```

## 2. Research each technology

For every course, look for **official** news since its newest item: the project's release notes or changelog, its
GitHub releases, the vendor's blog or announcements, deprecation and end-of-life pages. Prefer the vendor's own page
as the link; a reputable news report only when there is no official page. Keep it lean: skip a course quickly when
there's nothing new, and stop at `news.max_items_per_course` (5) per course — the most significant first.

What counts: new major or minor releases, notable features, deprecations, removals, end-of-life or retirement,
security advisories, pricing or licence changes. Not: patch releases with only bug fixes, blog marketing, rumours.

Material (could make a level wrong or out of date) — check, don't guess: grep the course's levels
(`projects/crash-course/courses/<slug>/*.yaml`) for the changed API, command or name. Mark `material: true` only when
a level teaches something the change removes, renames or contradicts, and list those levels in `affects` with a
one-sentence `reason` naming what changed. New features alone are not material.

Status (a badge on the course): propose `status` only from an official announcement — `deprecated`, `replaced` (with
`replaced_by`), `retired`. `declining` ("less used") needs strong public evidence of a shift (the vendor steering
users elsewhere, the project archived or unmaintained); never infer it from opinion.

## 3. Write the items

One JSON list in `drafts/news/<YYYY-MM-DD>.json` (git-ignored). Each item:

```json
{"course": "langgraph", "date": "2026-10-30", "title": "LangGraph 1.2.19", "summary": "One or two sentences in our own words: what changed and why it matters to a learner.", "url": "https://…official source…", "kind": "release", "material": false, "affects": [], "reason": "", "status": null, "replaced_by": "", "source": "claude"}
```

`date` is when it happened (release date), not today. `kind`: release, feature, deprecation, retirement, security,
pricing, other. Summaries are plain text, at most 400 characters, no HTML, no copied paragraphs, no invented numbers.

```bash
cd projects/crash-course && course news-add ../../drafts/news/<date>.json && cd ../..
```

It validates every item and exits 1 if any was rejected: fix or drop those items and run it again (items already
added are skipped, so rerunning is safe).

## 4. Publish the items

```bash
python scripts/course_news.py publish        # course-news branch only; never main
```

## 5. Proposed statuses → one pull request

Only if an item proposes a status the tech page doesn't already have. On a branch
`agent/claude-course-status-<date>` from `main`, add to `site/tech/<slug>.md`'s front matter:

```yaml
status: replaced            # deprecated | replaced | declining | retired
replaced_by: <slug or name>
status_note: One sentence, with the date.
status_source: https://…official announcement…
```

Then `cd projects/crash-course && course sources` (copies the page into `sources/tech/`), check
`PYTHONPATH=src python3 -m crash_course.cli check --course <slug>` still passes, commit, push, and open one PR titled
"Course status: <slug> → <status>" (several slugs: list them) with the evidence for each. Human edits win: if Ruairi
has edited that page's front matter, change only the status keys. Never merge.

## 6. Report

Short: items added per course, material items (course, levels, reason), the status PR link if any, and anything you
couldn't check. Update `STATUS.md` only for something Ruairi must act on.
