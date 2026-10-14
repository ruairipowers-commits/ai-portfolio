# Crash course

Learn any tool on this site at three depths: **Familiar** (15 minutes), **Beginner** (1 hour, with a guided project) and
**Intermediate** (4 hours, deep dives with a scored check on each core piece). A learner registers with an email,
signs up for a course and works through the levels on a tracker. Passing a level's quiz and finishing its project
unlocks the next one.

- **Quizzes:** scored on the server, with unlimited retries.
- **Projects:** self-attested.
- **Feedback:** learners leave it on any level, and it turns into proposed edits.
- **New topics:** a learner can suggest one. An agent reviews it first, and nothing is created until the owner approves.

> Part of the [AI Workflow Portfolio]({{SITE_URL}}) by Ruairi Powers · a personal project ·
> Write-up (with the link to sign up): [{{SITE_URL}}/personal/crash-course/]({{SITE_URL}}/personal/crash-course/) ·
> Governance: [this project's mapping](docs/governance.md)

## What it does

| Who | What they do | What code does | What a model does |
|---|---|---|---|
| Learner | registers, signs up, reads, takes quizzes, marks projects done, gives feedback, suggests topics | magic-link sign-in; draws and shuffles questions; scores them on the server; applies the unlock rule; stores everything | nothing — no model on any learner path |
| Owner | approves topics, publishes levels, accepts or rejects edits | signed approval links, the `/owner` page, content checks before every publish, an audit row for every decision | — |
| Worker | — | queues drafts when a learner unlocks a level that doesn't exist yet | the **writer** drafts a level in a strict schema; the **moderator** assesses suggested topics; the **reviser** proposes edits from feedback |

The 38 courses are seeded from the site's technology pages (`sources/tech/`). Every Familiar level was written at build
time from its page and passes every check. Beginner and Intermediate are drafted when the first learner unlocks
them, and published only after the owner reviews them.

### The three levels

| Level | Time | What's in it | Quiz |
|---|---|---|---|
| Familiar | 15 min | The concept; history and use today; how it fits business users; key use cases; pros and cons; resources (official docs first); a hello-world project; how to discuss it in an interview | 10 questions from a bank of 13, pass mark 70% |
| Beginner | 1 hour | Recap; 10 core terms; a setup checklist; a 30-minute guided project with checkpoints and "done when"; common mistakes; a cheat sheet; interview questions | 15 questions, pass mark 70% |
| Intermediate | 4 hours | 4–5 deep-dive modules, each with an exercise and a 5-question check (pass mark 80%); production concerns; alternatives; how this portfolio uses it; a capstone with a rubric; scenario interview questions | 25-question final test, pass mark 75% |

## Quickstart

```bash
pip install -e ".[dev]"
course all          # offline end to end in ~25 s: checks, 12 learners, builds, suggestions, feedback, eval gate
course serve        # learner site + owner page on http://localhost:8810 (COURSE_SHOW_LINKS=1 shows sign-in links on screen)
course ui           # the owner's operator app (Streamlit)
pytest -q           # 67 tests
```

Owner commands: `course queue`, `course publish --all --reviewer "Your Name"`, `course decide <id> --approve --reviewer
…`, `course revise --decide <id> --accept 0,1 --reviewer …`, `course report`, `course eval`.

## Results (offline, mock models, fictional learners)

From `course all` on 14 October 2026 (`output/run_summary.json`):

| What | Result |
|---|---|
| Familiar levels passing every content check | **38 of 38** (estimated 10.0–12.7 minutes each; 494 questions in the banks) |
| Quiz answers grounded in the tech page itself | **453 of 494**; the other 41 (mostly history) in the level's own text, checked by the owner |
| Hello-world projects run and checked by hand | **22 of 38** (the rest need an account, a server or Docker: Bedrock, AWS, Airflow, Postgres…) |
| Simulated learners | 12 learners, 24 attempts (19 passed), 18 Familiar levels completed, 6 Beginner drafts queued |
| Beginner drafts (mock writer) | 6 written, 6 passed the checks; the owner published one and a learner scored 15/15 |
| Suggestions | Kubernetes recommended and approved; a duplicate, a dual-use tool, an injection and a stalking request flagged and rejected |
| Feedback round | 3 edits proposed and accepted into a new draft; the edit an injected comment asked for (change an answer key) was held |
| Eval gate | **passed**: moderation accuracy 1.0, must-reject recall 1.0, false rejects 0.0, duplicates 1.0, content, tracker and feedback all 1.0 |
| Model calls | 11 calls, 25,870 in / 33,122 out tokens, $0.19 simulated cost |

The mock writer builds Beginner and Intermediate levels from the source page's own sentences (fill-the-gap questions).
That's enough to exercise every check and approval, but it is not the content a real model writes. Running on the
local model is the next step (see *What's next* in the write-up).

## Configuration

Everything is in `config/settings.yaml`:

- **Levels:** durations, required sections, quiz sizes and pass marks.
- **Completion rule:** a quiz passed AND the project done.
- **Quizzes:** bank size and shuffling.
- **Content checks:** evidence length, options, blocked terms.
- **Moderation:** categories, rate limits, duplicate threshold.
- **Approvals:** link expiry.
- **Registration:** open, or invite-only.
- **Privacy and retention.**
- **Cost caps.**

Models are aliases in `config/models.yaml`; `COURSE_MODERATOR_MODEL` and `COURSE_WRITER_MODEL` override them.
Secrets go in `.env` (see `.env.example`).

## Use-case card (HITL-04)

| | |
|---|---|
| **Intended use** | Self-paced learning about software tools, at three depths, for anyone with an email address. The owner curates every course. |
| **Not for** | Certification or assessment that anyone relies on (projects are self-attested; quizzes are open-book); security-offensive or harmful topics; medical, legal or financial advice. |
| **Risk tier** | Medium: public free-text input, published teaching content people rely on, and learners' email addresses. |
| **Owner** | Ruairi Powers |
| **Known limits** | The grounding check proves a quiz matches its material, not that the material is true; the 41 history questions not on the tech pages rest on the owner's review. Tool versions and details change, so `course sources` flags levels built from an older page. The mock writer is a stand-in. A determined learner can pass a quiz by trial and error, which is acceptable for a self-paced course. |

## Architecture

See [docs/architecture.md](docs/architecture.md) (flow, sequence and decisions), [docs/governance.md](docs/governance.md)
(every control) and [docs/aws-native.md](docs/aws-native.md) (the AWS path; Terraform starter in `infra/aws/`).

## License

Code: Apache 2.0. Docs and course content: CC BY 4.0. See NOTICE: if you reuse this, credit Ruairi Powers' AI Workflow
Portfolio, built with Claude.

## License

Apache-2.0, by Ruairi Powers, built with Claude: keep the NOTICE file and credit the project if you reuse it (see [NOTICE](NOTICE)).
