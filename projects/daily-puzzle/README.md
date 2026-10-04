# daily-puzzle

**One puzzle a day across logic, words, numbers, coding and AI. A generator model writes it; a second model that
never sees the answer has to reach the same one — for coding and AI puzzles by writing and running its own code —
before it's published. Code grades every attempt, keeps a cumulative leaderboard, and reveals the answer only after
submissions close. The whole day runs on a schedule; a human sees only the failures.**

> Part of the [AI Workflow Portfolio]({{SITE_URL}}) by Ruairi Powers · a personal project ·
> Write-up: [{{SITE_URL}}/personal/daily-puzzle/]({{SITE_URL}}/personal/daily-puzzle/) ·
> Governance: [this project's mapping](docs/governance.md)

## What it does

- **Subscribe** with an email, a public handle and the tracks you want (logic, words, numbers, coding, AI/ML).
  Double opt-in, magic-link sign-in (no passwords), one-click unsubscribe, delete your account any time.
- **Every morning** (07:00 ET) subscribers of that day's track get the puzzle by email. Accept it on the site and
  answer; each submission says at once whether you solved it and how many attempts you have left (6 by default).
- **Scoring:** 100 × 0.7^(attempts − 1) → 100 / 70 / 49 / 34 / 24 / 17 points, 0 if unsolved, added up across
  puzzles. The leaderboard (all time, this week, per track) shows handle, puzzles accepted, attempted, solved and
  score; ties go to fewer total attempts, then the earlier solve.
- **Integrity:** the answer is stored only as salted hashes plus an encrypted key until submissions close (23:59 ET);
  then it's revealed with a worked solution and, for code puzzles, the reference code. Before that, the API
  returns 403 and the answer is in no page, email, log or telemetry event (tested).
- **Coding and AI puzzles teach something.** Each states a learning objective and skill tags and gives starter code;
  examples: what a Python snippet prints and why, filtering a CSV, summing a layer's weights in a saved model,
  fine-tuning a model's last layer with a fixed seed and reporting the loss, nearest neighbours in word vectors.
  They run on allow-listed public data (Hugging Face models and datasets, licence-checked, safetensors only) or
  the bundled stand-ins in `fixtures/`.
- **Puzzle packs:** a one-off set of new, verified puzzles as a questions PDF and a separate answer-key PDF.
- **Everything is configuration** (`config/puzzles.yaml`): which tracks, which kinds, the weekday rotation,
  difficulty, attempts, scoring, the data allow-list, sandbox limits, the window and time zone, who can make packs.

## How a puzzle gets published

```
choose track/kind/difficulty → generator writes a draft
  → schema → content policy → learning fields → data allow-list & licence → not a repeat
  → proof by code: exhaustive search finds exactly one answer (logic, words, numbers)
    or the reference code, run twice in the sandbox, reproduces the key (coding, AI)
  → blind solver (a different model) reaches the same answer and finds no other
  → PUBLISH            … or the reasons go back to the generator (3 rounds), then the draft is escalated to the
                         operator and a pre-verified reserve puzzle is published instead
```

See [docs/architecture.md](docs/architecture.md) for the diagrams and decisions.

## Quickstart (offline, no keys)

```bash
pip install -e ".[dev]"            # WeasyPrint needs Pango: apt install libpango-1.0-0 libpangoft2-1.0-0 (macOS: brew install pango)
pytest -q                          # 112 tests, ~30 s
puzzle all                         # reserve → a simulated week with 25 players → a 5-puzzle pack → eval gate (~10 s)
puzzle serve                       # player site + scheduler: http://localhost:8800 (emails land in output/outbox/)
puzzle ui                          # operator app: simulate, try to break it, review escalations, make packs
puzzle pack --count 5 --tracks coding,ai_ml --seed 7   # → output/packs/<id>-questions.pdf and -answers.pdf
```

Results from `puzzle all` on the offline mock models (this repo, October 2026): 10 reserve puzzles, 8 daily puzzles
all verified on the first round, 25 simulated players making 291 graded attempts, a 5-puzzle pack, and the eval gate
passing — verifier accuracy 1.00 on 19 golden drafts, must-reject recall 1.00 (9 deliberately broken drafts), grading
accuracy 1.00. Mock models carry simulated prices ($1 / $5 per million tokens) so the cost path is exercised: one day
of generation plus verification logged about 1,500 tokens. **These are mock numbers: real models write longer drafts,
and their first-round pass rate hasn't been measured yet.**

### Real models

The mock generator writes procedural puzzles of the same JSON shape a real model must return
([`prompts/generator.v1.md`](prompts/generator.v1.md)); the mock solver brute-forces formal kinds and, for code kinds,
runs an independent implementation that ships with each template. To use real models, keep the two different:

```bash
export PUZZLE_GENERATOR_MODEL=local-qwen PUZZLE_SOLVER_MODEL=local-gemma OLLAMA_URL=http://localhost:11434
# or claude-sonnet / claude-haiku with ANTHROPIC_API_KEY (fill pricing in config/models.yaml first)
puzzle eval --role generator --alias puzzle-candidate   # after pointing puzzle-candidate at the model
```

## Configuration

| What | Where |
|---|---|
| Tracks, kinds, rotation, difficulty, attempts, scoring, window, packs | `config/puzzles.yaml` (`puzzle config-check` validates it) |
| Data a puzzle may use (licences, file types, size, assets) | `config/puzzles.yaml` → `data_sources` |
| Sandbox limits | `config/puzzles.yaml` → `sandbox` |
| Models | `config/models.yaml` aliases; env `PUZZLE_GENERATOR_MODEL`, `PUZZLE_SOLVER_MODEL` |
| Budgets, rate limits, retention, eval thresholds | `config/settings.yaml` |
| Secrets, email, public URL | `.env` (see `.env.example`) |

## Use-case card (HITL-04)

| | |
|---|---|
| **Intended use** | A daily learning game for a small public audience; one-off puzzle packs for teaching |
| **Users** | Subscribers (players); one operator who reviews escalations |
| **Not for** | Assessment that matters (hiring tests, grades): puzzles are AI-written and checked by code and a second model, not by a person |
| **Owner** | Ruairi Powers |
| **Decisions by AI** | What the puzzle is. Not: whether an answer is right (code), scores (code), what gets published without passing verification (never) |
| **Known failure modes** | A puzzle whose wording and machine-readable spec disagree (caught only by a real solver model — the mock solver reads the spec); the word list behind cipher and anagram checks is small, so an obscure second answer outside it isn't caught; difficulty labels are the generator's estimate; the sandbox's audit hooks stop model mistakes, not a determined attacker |
| **Data** | Player emails (private), handles (public), attempts; synthetic fixtures; allow-listed public models and datasets |
| **Human in the loop** | Every draft that fails verification after 3 rounds is reviewed by a named operator; reserve puzzles keep the day running meanwhile |

## Layout

```
config/            settings.yaml · puzzles.yaml · models.yaml · blocked_terms.txt
prompts/           generator.v1.md · solver.v1.md
src/daily_puzzle/  puzzles.py (kinds, mock generator, proofs) · verify.py · generate.py · sandbox.py · assets.py
                   grading.py · game.py · cycle.py · mailer.py · packs.py · web.py · ui.py · simulate.py · evals.py · cli.py
fixtures/          tiny safetensors model, flowers.csv, word vectors (synthetic, seeded)
evals/             golden_set.yaml
docs/              architecture.md · governance.md · aws-native.md
infra/aws/         Terraform starter (KMS split for the answer key, Fargate sandbox network, scheduler, budget)
```

MIT licence. Puzzles, players and data in the demo are synthetic.
