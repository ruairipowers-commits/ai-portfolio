# Architecture — daily-puzzle

## Flow

<!-- --8<-- [start:flow] -->
```mermaid
flowchart TB
    CFG[config/puzzles.yaml<br/>tracks · rotation · difficulty<br/>data allow-list · scoring] --> CH
    subgraph Daily["Scheduler (APScheduler, every minute) · tick()"]
      CH[03:00 choose track,<br/>kind, difficulty] --> GEN[Generator agent<br/>alias puzzle-generator · MODEL-01]
      GEN --> V{Verifier}
      V -->|reasons fed back,<br/>≤ 3 rounds| GEN
      V -->|still failing| ESC[Escalate · HITL-02<br/>operator review queue]
      ESC --> RES[(Reserve:<br/>pre-verified puzzles)]
      V -->|PUBLISH| SEAL[Seal key · SEC-04<br/>HMAC hashes + encrypted key]
      RES --> SEAL
      SEAL --> OPEN[07:00 open +<br/>email subscribers]
      OPEN --> CLOSE[23:59 close]
      CLOSE --> REV[+5 min reveal:<br/>answer, solution, code]
    end
    subgraph Verify["Verifier (verify.py)"]
      direction LR
      S1[schema · SEC-04] --> S2[content · learning fields]
      S2 --> S3[data allow-list,<br/>licence, no pickle · DATA-04]
      S3 --> S4[repeat check]
      S4 --> S5[proof by code:<br/>exactly 1 solution]
      S5 --> S6[reference code ×2<br/>in sandbox · SEC-03]
      S6 --> S7[blind solver agent<br/>alias puzzle-solver,<br/>own code in sandbox]
    end
    V -.- Verify
    OPEN --> SITE[Player site<br/>FastAPI + HTMX]
    SITE -->|answer typed| GRADE[Grade by code<br/>HMAC compare · SEC-02]
    GRADE --> LB[(Leaderboard<br/>fewer attempts, more points)]
    REV --> SITE
    GEN & S7 -->|tokens, cost,<br/>kill switch| G[Governance console]
    PK[Operator: puzzle pack] --> GEN
    PK --> PDF[questions.pdf +<br/>answer-key.pdf]
```
<!-- --8<-- [end:flow] -->

## A player's day

<!-- --8<-- [start:sequence] -->
```mermaid
sequenceDiagram
    participant Sch as Scheduler
    participant Gen as Generator model
    participant Ver as Verifier (code + sandbox)
    participant Sol as Solver model (blind)
    participant P as Player
    participant Site as Player site
    Sch->>Gen: track, kind, difficulty, seed
    Gen-->>Ver: draft JSON (statement, key, spec / reference code)
    Ver->>Ver: schema · content · data · repeat · proof · reference ×2
    Ver->>Sol: public puzzle only (no key, solution or code)
    Sol-->>Ver: answer, or code → run in sandbox
    Ver-->>Sch: PUBLISH (or reasons → next round / escalate)
    Sch->>P: 07:00 email (no answer)
    P->>Site: Accept
    loop up to 6 attempts
      P->>Site: answer
      Site->>Site: normalize → HMAC compare (no model)
      Site-->>P: solved +points / not yet (n left)
    end
    Sch->>Site: 23:59 close · 00:04 reveal answer + worked solution
```
<!-- --8<-- [end:sequence] -->

## Why this shape

<!-- --8<-- [start:decisions] -->
| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Pattern | Two agents (generator, blind solver) inside a plain scheduled workflow | One agent that writes and self-checks; a full agent framework | A model checking its own puzzle shares its own blind spots. Everything else (schedule, grading, scoring, email) is deterministic, so it stays plain code |
| Proving one answer | Code first: exhaustive search over a machine-readable `spec` (logic, words, numbers) or the reference code run twice (coding, AI); then the solver | Ask the model "is this unique?" | A brute-force count is a proof; a model's yes is an opinion. The solver catches what code can't — wording that doesn't match the spec |
| Grading | Normalize, then compare salted HMACs | An LLM judging free-text answers | Instant, free, deterministic and immune to "mark this correct" in the answer box. The answer needn't be decrypted to grade |
| Answer integrity | Key encrypted until the reveal step; `reveal_*` columns empty before close; 403 from the API | Hide the answer in the page and trust the front end | The server holds no plaintext answer to leak until close; tested on pages, API, email, logs and telemetry |
| Running model-written code | Isolated subprocess: empty environment, no network, audit-hook guard, rlimits, two runs | Docker per run; gVisor/Firecracker | Works inside the hardened demo container (which can't start Docker) and blocks the mistakes a model makes; stronger isolation is documented, not built |
| Public data | Allow-list with licence, file types and size; Hub licence re-checked; files staged by trusted code; safetensors only | Let the model pick any dataset | Licences and pickle are the two ways public data goes wrong; the sandbox never touches the network |
| Bad days | Escalate to a review queue and publish a pre-verified reserve puzzle | Retry until it works; skip the day | Players always get a puzzle, and a human sees every failure |
| Scheduler | APScheduler inside the service, `tick()` idempotent | Airflow, cron | One process on a home server; missed steps catch up in order |
| Front end | FastAPI + Jinja + HTMX for players; Streamlit for the operator | Streamlit for everything | Players need sign-in, cookies, forms and email links; the operator needs a simulation console |
<!-- --8<-- [end:decisions] -->

## Data model

| Table | Holds | Never holds |
|---|---|---|
| `puzzles` | statement, track, kind, window, HMACs of accepted answers, encrypted key, verification report | the plain answer before close |
| `players` | email (private), handle (public), tracks, opt-in and unsubscribe times | passwords (magic links only) |
| `acceptances`, `attempts` | who accepted what, each attempt, points | — |
| `suppression` | SHA-256 of unsubscribed or deleted addresses | the address |
| `ai_calls`, `sandbox_runs`, `jobs`, `outbox`, `reviews` | audit: model, prompt hash, input hash, tokens, cost; code and output hashes; scheduler steps; email kinds; named reviewers | prompts, answers, program output |

## Puzzle kinds

| Track | Kinds | Proved by |
|---|---|---|
| Logic | knights-knaves, ordering | exhaustive search over the spec |
| Words | cipher (Caesar), anagram | every shift / anagram checked against the word list |
| Numbers | sequence, combinatorics | every rule family fitted; brute-force count |
| Coding | python-output, data-wrangling | reference code ×2 in the sandbox; solver's own code |
| AI / ML | weights-inspection, tiny-finetune, embeddings | same, on a pinned safetensors model, dataset or vectors |
