# speaking-coach

**Bring your own filler words, a transcript, or both. It finds every "um", "like" and "so" you said, tells real
fillers from normal English, scores you against your own target, shows where the streaks are, and rewrites your
worst sentences without them.**

> Part of the [AI Workflow Portfolio]({{SITE_URL}}) by Ruairi Powers · a personal project ·
> Write-up: [{{SITE_URL}}/personal/speaking-coach/]({{SITE_URL}}/personal/speaking-coach/) ·
> Governance: [this project's mapping](docs/governance.md)

## What it does

- **Your list, not ours.** Start from presets (*starter* is the author's own list: um, uh, like, you know, kind of,
  "So" to open a sentence, "I guess" to close one, plus repeated words), add your own words and phrases with a
  weight and a rule, and list words never to flag. Paste the list, upload it, or export it to reuse.
- **Any transcript.** Paste text, or upload .txt, .md, .docx, .srt or .vtt. Meeting exports with several people
  ("Name: …" lines or WebVTT voice tags) are split by speaker so only your turns are scored. Captions with
  timestamps add pace (words a minute) and pauses.
- **Code counts, a model only judges context.** Every match is found by code. "So" counts only at the start of a
  sentence, "I guess" only at the end, "like" only when it isn't a verb or comparison. The unclear ones go to a
  model with a few words of context. Same transcript, same score, every time.
- **Coaching you can use.** The biggest patterns with where they happen, tips from a practice plan, and your three
  worst sentences rewritten cleanly. Code checks every rewrite: no flagged word left, every number and name kept.
- **Your call.** Mark anything disputed or wrong; the numbers update instantly. Save corrections as test cases so a
  future model change can't undo them.
- **Private by default.** Nothing is saved unless you turn history on. Names, emails and phone numbers become
  placeholders before any model sees text. `local_only` keeps everything on your machine.

## Quickstart

```bash
pip install -e ".[ui,dev]"
coach all                     # 8 fictional samples → output/*.report.md|html, offline mock model
coach eval                    # golden-set gate: precision, recall, guard, checks
coach ui                      # Streamlit app: input → run → output
pytest -q
```

Your own transcript and list:

```bash
coach analyze --words my-list.txt                              # preview how your list will match
coach analyze meeting.vtt --words my-list.txt --speaker "Sam Ortiz" --target 1.5 --history
coach history
```

A word list is plain text, one entry per line: `phrase | category | weight | rule`. Only the phrase is required.
Rules: `always`, `opener` (start of a sentence), `closer` (end of a thought), `context` (neighbour rules, then a
model). `!word` adds to the ignore list. See `samples/word-lists/`.

To use a real model, add it to `config/models.yaml` and point the aliases at it (a local Ollama model needs
`pip install -e ".[local]"` and `OLLAMA_URL`). Run `coach eval --alias coach-candidate` before promoting it.

## Results (offline run, mock model)

| Measure | Result |
|---|---|
| Precision / recall, all labelled transcripts | 0.986 / 0.986 (71 of 72 fillers found, 1 false alarm) |
| Words that need context (like, so, you know, kind of, right…) | 0.975 / 0.975 |
| Held-out transcript (written after the rules, never tuned against) | 0.857 / 0.857 (6 of 7) |
| Rewrite guard decisions | 7 of 7 correct |
| Case checks (counts, grade, pace, flags, nothing private sent) | 15 of 15 |
| Model calls for the whole eval | 15, simulated cost $0.018 |

The labelled transcripts and the rules were written together, so the first two rows flatter it; the held-out row
is the honest number for the rules, and the mock is not a real model. Live numbers on a local model are next.

## Configuration

| What | Where |
|---|---|
| Presets, your words, ignore list, repetition | `config/settings.yaml` `lexicon.*`; presets in `config/lexicons/*.yaml` |
| Target, grade bands, streak window, pace band | `thresholds.*` |
| Model confidence needed, context words sent | `disambiguation.*` |
| Number of rewrites, tone, audience, practice plan | `coaching.*` |
| History, pseudonymization, local-only | `privacy.*` |
| Models | `config/models.yaml` (aliases `coach-disambiguator`, `coach-writer`, `coach-fallback`, `coach-candidate`) |
| Budgets and eval thresholds | `cost.*`, `eval.*` |

## Use-case card (HITL-04)

| | |
|---|---|
| **Intended use** | Personal practice: see your filler habits in a transcript of your own speech and get cleaner wording. |
| **Not for** | Judging or scoring other people (meeting exports are filtered to one speaker for that reason); assessing anyone's ability; non-English transcripts (v1). |
| **Risk tier** | Low. Content treated as sensitive: not stored, pseudonymized before any model. |
| **Owner** | Ruairi Powers |
| **Known limits** | Needs a transcript that keeps fillers (many auto-captions drop "um"); no audio in v1. Rules rely on punctuation, so an unpunctuated transcript gives less reliable opener/closer calls (the report says so). Name detection is heuristic: a name only ever seen at the start of a sentence can slip through (list it under names). The mock model is a stand-in. |

## Architecture

See [docs/architecture.md](docs/architecture.md) and [docs/aws-native.md](docs/aws-native.md).
