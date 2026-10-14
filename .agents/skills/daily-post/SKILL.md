---
name: daily-post
description: Daily blog post from the top of the editorial queue — a local model on the EVO-X1 drafts it, Claude reviews and edits it, code gates it, and it auto-publishes tagged AutoPublished (or waits as a draft PR). Logs the local-vs-Claude comparison. Used by the daily scheduled task.
---

# Daily post: local draft → Claude review → code gate → publish or hold

You are the **reviewer**, not the writer. A local model on Ruairi's EVO-X1 writes the first draft; you research,
brief it, review and edit its draft, and a separate **editor** subagent scores the result. **Code decides** whether it
publishes (`editorial gate`). Ruairi asked for this to publish without his review when every check passes; when
anything fails, it waits for him as a draft pull request.

Read first: `CLAUDE.md`, `factory/style-guide.md`, `projects/editorial-agents/prompts/local-writer.v1.md` (the local
model's brief), `projects/editorial-agents/prompts/editor.v1.md` (the editor's rubric). Standing rule: never say or
imply client or employer work; this site is Ruairi's own work, for learning and as examples.

Setup: `pip install -q -e projects/editorial-agents`. Work in `drafts/<slug>/` (git-ignored, never committed).

## 1. Take the topic

- Fetch the queue (`EDITORIAL_QUEUE_URL` from the task prompt, a `queue.md`; never write that URL into any file) with
  WebFetch, verbatim. The first topic is next: Ruairi's picks first, then readers' votes, then rank. Note its `id`,
  title, link, summary, angle, sectors and votes.
- Skip a topic that already has a PR: `gh api "repos/{owner}/ai-portfolio/pulls?state=all&per_page=50"` and look
  for `Topic: <id>` in any body. Take the next one.
- Queue unreachable or empty: **stop** and report why. Never invent a topic.
- Slug: short, lowercase, hyphenated, not already used under `site/`. Date: today (UTC).

## 2. Research and brief (you)

- Read the topic's own link plus two to four reputable sources (WebSearch, WebFetch). Save each source's main text to
  `drafts/<slug>/sources/<n>-<site>.txt`.
- Write `drafts/<slug>/brief.md`, **at most 900 words**: the topic in two lines; the sources (title + URL, the topic's
  own link first); 8–15 numbered facts, each tagged with its source number, with any figure stated exactly as the
  source gives it; the cross-industry angle (sectors and one worked example); risks to cover; what's unknown or
  speculative. Only facts you read. The brief is the local model's only knowledge, so it must be complete and right.

## 3. Local draft (the EVO-X1)

- Prompt = `local-writer.v1.md` with `{brief}` replaced by the brief's text. Keep it under ~2,500 words in total:
  the server's context window is 8,192 tokens and the answer needs room.
- Time it: `date +%s.%N > drafts/<slug>/t0`, then call `mcp__remote-devices__evo-x1__ollama_generate` with
  `model: gpt-oss:20b`, `temperature: 0.4`, the prompt; then `date +%s.%N > drafts/<slug>/t1`.
  If gpt-oss:20b fails or returns nothing, retry once with `qwen3-coder:30b` and note it.
- Save the response **exactly as returned** to `drafts/<slug>/local.md`. Never touch it up: the comparison measures
  what you change.
- If the EVO-X1 tools are missing or the call fails twice: the computer is off or unreachable. Stop, open nothing,
  and report it. Don't write the draft yourself in its place.

## 4. Review and edit (you)

- Write `drafts/<slug>/review.md`: a numbered list of every defect you find in `local.md`: unsupported or wrong
  claims (check each against the brief and sources), invented figures, copied runs, missing sections, style-guide
  breaches, client framing, broken links. One line each. The count of items is the run's **defects**.
- Make the post: `site/blog/posts/<slug>.md` = front matter + `local.md` with **only the edits your review calls
  for**. Keep the local model's wording wherever it's right; don't rewrite for taste. If the draft is unusable
  (wrong topic, mostly invented), write it yourself and record `--rewritten`.
- Front matter: `date`, `slug`, `short` (≤ 40 chars), `categories` (existing site topics), `tags` (must include
  `AutoPublished`), `audience` (two to five roles from `portfolio.yaml` `audiences`, quoting any with a comma),
  `section: AI insight`.
- Last line, in italics, exactly: *Drafted with AI agents: a local model on my own server wrote the first draft from
  a topic my scout found, Claude reviewed and edited it, and it was published automatically after passing every
  check, without my review.*

## 5. Check, edit once, gate

1. `editorial review site/blog/posts/<slug>.md --sources drafts/<slug>/sources --corpus <site URL>/assistant/corpus.json`
   Whether every code check passed on this first run is the run's **checks first pass**.
2. Start the **editor** as a separate subagent (Agent tool, general-purpose). Give it ONLY: `editor.v1.md`, the post,
   the source texts and the code-check table. Save its JSON to `drafts/<slug>/editor.json`.
3. One revision round: fix every failed check and every criterion scored 3 or below; append what you changed to
   `review.md` (it counts as Claude's writing). Re-run the code checks and the editor.
4. `editorial gate site/blog/posts/<slug>.md --editor drafts/<slug>/editor.json --sources drafts/<slug>/sources --corpus …`
   Exit 0 = publish; exit 1 = hold. Never override it.

## 6. Comparison arm (only while fewer than 10 topics are paired)

If `editorial routing paired` prints a number below 10, also run the **claude-only** arm on the same topic, for the
metrics post's baseline: write your own complete post from the same brief and sources to `drafts/<slug>/claude.md`
(same shape, same front matter, same last line), without looking at `local.md` or `review.md`. Run the code checks and
a separate editor subagent on it (`drafts/<slug>/editor-claude.json`). It is **never published**; only measured.

## 7. Log the run

After the gate decision, so `--published` is true only if it really publishes. From the repo root:

```bash
T=$(python3 -c "print(float(open('drafts/<slug>/t1').read())-float(open('drafts/<slug>/t0').read()))")
editorial routing log --arm local-review --topic <id> --slug <slug> --final site/blog/posts/<slug>.md \
  --local-draft drafts/<slug>/local.md --review drafts/<slug>/brief.md drafts/<slug>/review.md \
  --read drafts/<slug>/sources/*.txt drafts/<slug>/local.md --local-model <model used> --local-seconds "$T" \
  --defects <n> --editor-min <lowest final editor score> [--checks-first-pass] [--rewritten] [--published]
```

If the comparison arm ran:

```bash
editorial routing log --arm claude-only --topic <id> --slug <slug> --final drafts/<slug>/claude.md \
  --review drafts/<slug>/brief.md --read drafts/<slug>/sources/*.txt \
  --editor-min <its lowest editor score> [--checks-first-pass]
```

Both arms count the brief as Claude's writing, so the comparison is like for like.

## 8. Publish or hold

Branch `auto/<slug>` from `main`. Commit `site/blog/posts/<slug>.md` and
`projects/editorial-agents/metrics/routing-runs.jsonl`, with the usual `Co-Authored-By` trailer. Push. Open the PR with
`gh api repos/{owner}/ai-portfolio/pulls` (title = the post title, base `main`). Body:

```
Topic: `<topic id>`
Source: <topic link> · votes: <n> · picked by Ruairi: yes|no
Local model: <model> · <seconds> s · defects found in review: <n> · rewritten: yes|no

<!-- scorecard -->
<final code-check table, plus one row per editor criterion>
<!-- /scorecard -->

Gate: PUBLISH | HOLD — <reasons if held>
```

- **Gate said PUBLISH:** label `auto-published` (create it if missing), then merge it yourself:
  `gh api -X PUT repos/{owner}/ai-portfolio/pulls/<n>/merge -f merge_method=squash`. The site deploys from `main`.
- **Gate said HOLD:** change the post's last line to *Drafted with AI agents from a topic my scout found, then edited
  and approved by me.*, remove `AutoPublished` from its tags, commit that, label the PR `draft-post` **and**
  `needs-work`, and leave it open. Never merge it. The `draft-post` workflow emails Ruairi.

Never push to `main` directly, never merge a held PR, never change files other than the post and the run log.

## 9. Finish

Final message: the topic and its votes, the PR link, PUBLISHED or HELD (and why), the local model's time and the
review's defect count, whether the comparison arm ran, and anything left out for lack of a source.
