---
name: weekly-post
description: Draft the weekly AI-insight blog post from the top of the editorial topic queue, run two independent editor reviews, and open a draft-post pull request for Ruairi to approve. Used by the weekly scheduled task; never publishes on its own.
---

# Weekly post: writer → editor ×2 → draft pull request

You are the **writer**. A separate **editor** (a subagent that never sees your notes) reviews your draft twice.
The only way a post goes live is Ruairi merging the pull request you open. **Never merge, never push to `main`.**

Read first: `CLAUDE.md`, `factory/style-guide.md`, `projects/editorial-agents/prompts/writer.v1.md` (your brief) and
`projects/editorial-agents/prompts/editor.v1.md` (the editor's rubric). Standing rule: never say or imply client or
employer work; this site is Ruairi's own work, for learning and as examples.

## 1. Choose the topic

- The queue URL comes from the task prompt (`EDITORIAL_QUEUE_URL`, ending in `/editorial-agents/queue.md`). It is
  kept out of git on purpose; don't write it into any file.
- Fetch it with WebFetch and ask for the Markdown verbatim. Take the **first** topic: picked topics come first, then
  by rank. Note its `id`, title, link, summary, angle and sectors, and whether its status is `picked`.
- If the queue can't be fetched or is empty: **stop**. Don't invent a topic. Report why in your final message.
- Skip a topic that already has an open `draft-post` pull request (check `gh api repos/{owner}/ai-portfolio/pulls`
  for `Topic: <id>` in a body); take the next one.

## 2. Research

- Read the topic's own link, plus two to four more reputable sources on the same subject (WebSearch, WebFetch).
- Save each source's main text to `drafts/<slug>/sources/<n>-<site>.txt` (git-ignored, never committed): the
  originality check compares your draft against these.
- Note which claims each source supports. Anything you can't support, leave out.

## 3. Write

- Write `site/blog/posts/<slug>.md` following `writer.v1.md` exactly: front matter including `section: AI insight`,
  900–1,800 words, the topic's link first among at least two cited sources, the cross-industry angle with a worked
  example, risks linked to the governance standard, and the italic disclosure line at the end.
- Date: the coming Monday. Slug: short, lowercase, hyphenated, not already used under `site/`.

## 4. Edit: two rounds

For each round (two in total):

1. Run the code checks:
   `pip install -q -e projects/editorial-agents && editorial review site/blog/posts/<slug>.md --sources drafts/<slug>/sources --corpus <site URL>/assistant/corpus.json`
   (the site URL is in `portfolio.yaml`, or ask the build: `https://<owner>.github.io/ai-portfolio`).
2. Start the **editor** as a separate subagent (Agent tool, general-purpose). Give it ONLY: the contents of
   `editor.v1.md`, the draft, the source texts, and the code-check table. Not your notes, not this skill.
   It returns JSON scores.
3. Revise: fix every failed code check and every criterion scored 3 or below, starting with its top three changes.

After round two, run the code checks once more. Then:

- Every code check passes and every editor score is ≥ 4: open the PR labelled `draft-post`.
- Otherwise: still open it, labelled `draft-post` **and** `needs-work`, with the reasons at the top.

## 5. Open the draft pull request

- Branch `draft/<slug>` from `main`. Commit only `site/blog/posts/<slug>.md` (and an image if you made one), with
  the usual `Co-Authored-By` trailer. Push the branch.
- Open the PR with `gh api repos/{owner}/ai-portfolio/pulls` (title: the post title; base `main`). The body must have:

  ```
  Topic: `<topic id>`        ← exactly this line; the scout uses it to mark the topic drafted / published
  Source: <topic link> · picked by Ruairi: yes|no (top-ranked)

  <!-- scorecard -->
  <the final code-check table, plus one row per editor criterion: "| Accuracy (editor) | 4/5 | note |">
  <!-- /scorecard -->

  Editor rounds: 2. Main changes after review: <two or three bullets>.
  To publish: merge. To withhold: leave this open (it stays a draft) or close it to drop the topic.
  ```

- Add the label(s): `gh api repos/{owner}/ai-portfolio/issues/<n>/labels -f "labels[]=draft-post"`. Create the
  label first if it doesn't exist.
- The `draft-post` workflow emails Ruairi the intro, the scorecard and the links. You don't send email.

## 6. Finish

Your final message: the topic, the PR link, the scorecard summary, and anything you left out for lack of a source.
