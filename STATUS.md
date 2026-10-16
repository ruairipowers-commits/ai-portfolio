# Status — open items

What's in flight, so a new chat can pick up without the old one's history. Newest context first; tick items off
(or delete them) as they're done. Last updated 16 October 2026.

## 000000000. Run log on its own branch; Python image bumps off (14 October 2026, night)

- **Every daily run counts**: the daily-post skill pushes its comparison rows to the `routing-log` branch
  (`scripts/routing_log.py publish`) whatever the gate says; the post PR carries only the post. The site build merges
  that branch in and now also rebuilds daily (15:40 UTC), so the metrics post's table moves without a merge.
- **Dependabot**: Python base-image minor/major bumps are ignored (CI tests 3.11). Close #35–#39 and #41 with
  `@dependabot ignore this minor version`.
- [ ] **Dependabot auto-merge (patch/minor pip + npm once checks pass)**: Ruairi asked for it; agents can't set up
      merges that skip his review, so it's his to add (workflow text in the chat of 14 Oct, or turn on "Allow
      auto-merge" in Settings → General and use Dependabot's own option).

## 00000000. Daily pipeline state (14 October 2026, evening)

- **Ruairi merges every post** (decision 14 Oct): the daily-post skill opens a PR labelled `ready-to-publish` or
  `needs-work` and never merges; CLAUDE.md, gate, skill, site copy updated (branch `agent/claude-owner-merges`).
- **Daily task paused** (trigger "Daily blog post"): the EVO-X1 `ollama_generate` tool goes through the Mac's
  Claude app, which times out at 60 s, and a ~1,200-word draft takes longer. Fix chosen: a start-job / fetch-result
  tool in the EVO-X1 MCP server (needs `evo-x1-mcp` from Ruairi). Re-enable the task after.
- **Weekly task paused**; replaced by the daily one.
- **Today's three posts** (AesCode, GreenWAM, supermarket fridge hack) were Claude-written after the local bridge timed
  out: draft PRs #29–#31 for Ruairi; logged as claude-only baseline runs (PR #28).
- Open dependency PRs: #6 (Actions; merge when watching a deploy), #9 and #11 (waiting on Dependabot rebase), #25.

## 0000000. Daily auto-published posts + votes + Blog/Learn tabs (14 October 2026, PR #24, `agent/claude-daily-post`)

Built: reader votes on the editorial queue (blog page), daily owner email with votes, `editorial gate` (code decides
auto-publish), `editorial routing` comparison log rendered into the metrics post, `.agents/skills/daily-post`, Blog
and Learn tabs. Ruairi chose: scheduled Claude task (not an API key), failures → draft PR, Learn = Crash course +
Classes + Technologies.

- [ ] **Merge PR #24**, then: pause the "Weekly blog post draft" scheduled task and create the daily one (needs the
      computer, for the EVO-X1 model). Not created yet: the skill must be on `main` first.
- [ ] **Three comparison posts** (top 3 queue topics, both arms, published if the gate passes): blocked on reading
      the queue — the fetch permission prompt timed out twice; Ruairi to paste the queue URL in the chat.
- [ ] After the first week: Ruairi reads a sample of AutoPublished posts (HITL-02 recommendation).

## 00000a. Every app has its own email sender (14 October 2026)

So mail from each project can be filtered on its own. Each app reads its own setting first; if that is empty it uses the
shared `SMTP_FROM` / `MAIL_FROM` address under its own name (e.g. `Daily puzzle <shared@…>`), so filtering by sender
name works even before any of these are set.

- [ ] **Deploy `.env` on the EVO-X1** (addresses on the Resend-verified domain; the name in front is free):
      `GOVERNANCE_MAIL_FROM`, `ASSISTANT_MAIL_FROM`, `EDITORIAL_MAIL_FROM`, `PUZZLE_MAIL_FROM`, `COURSE_MAIL_FROM`,
      `HELPER_MAIL_FROM` (Lil'Helper's own server `.env`), then `git pull && ./update.sh --force`.
- [ ] **GitHub repository variables** (Settings → Secrets and variables → Actions → Variables): `UPTIME_MAIL_FROM`,
      `DRAFT_MAIL_FROM`. Not secrets: a sender address isn't sensitive.

## 000000. Shared Ollama hardening + two posts (14 October 2026, branch `agent/claude-evo-ollama-openclaw`)

The EVO-X1 now runs one ROCm Ollama (host compose in the separate `infra-setups` repo, `evo-x1-server`), shared by
the demos (`OLLAMA_SHARED=1`) and OpenClaw. The `ollama-shared` proxy now passes model use only (chat, generate,
embeddings, tags, show, version, ps, pull, /v1 equivalents); delete/create/copy/push/blobs get 403 (tested against
a stand-in upstream with a real Caddy). Posts: `personal/posts/one-ollama-and-openclaw.md` (published on merge) and
`personal/posts/local-drafts-claude-reviews.md` (`draft: true`).

- [ ] **Publish the metrics post** once the results table has a month of real routed runs (local draft → Claude
      review), with the baseline logged the same way. Numbers today: one task (qwen3-coder:30b, 24.6 tok/s, 2,034
      tokens in 82.6 s; review found 3 lenient-input defects its own tests missed).
- [ ] **Build the routing:** weekly-post first draft on the local model; editor reviews + PR stay with Claude; log
      one row per run (fields in the post).
- [ ] **`private-local-ai.md` is now out of date** (it says the Ask button's Ollama is kept separate on purpose, and
      OpenClaw is "not yet part of the private path"). Suggested edit for Ruairi, not made: a short "Update, October
      2026" pointing to the new post.
- [ ] **infra-setups commit** (Ruairi, from the EVO-X1; the Claude GitHub app has no access to that repo).

## 00000. Crash course (new personal project, built 14 October 2026)

`projects/crash-course` + `site/personal/posts/crash-course.md` + a "Take the crash course" box on every tech page
(added by `scripts/mkdocs_hooks.py`, not by editing the pages). Courses at 15 min / 1 hour / 4 hours for all 38 tech
pages: learner site (FastAPI + Alpine.js, magic-link sign-in), tracker with unlocks (quiz passed AND project done),
server-scored retryable quizzes, feedback → proposed edits, topic suggestions reviewed by rules + a model, and an
owner page at `/owner`. Decisions (13 Oct): personal tier; Familiar written in the build session for all 38, Beginner
and Intermediate drafted on demand when a learner unlocks them; open registration. Work is on branch
`agent/claude-crash-course` (per AGENT.md); the earlier `crash-course` branch on GitHub holds only the spec and can be
deleted. Verified offline: 68 tests, `course all` ~25 s, eval gate passed, 38/38 levels pass every check, 22 of 38
hello-world projects run by hand, governance / image-deps / security checks, live site walked through in Chromium
(learner and owner, desktop and phone).

- [ ] **Review and publish the 38 Familiar levels.** They ship as drafts, so nothing is visible until you publish.
      Read a few in `/owner` → Review (the preview shows the answer key and each question's evidence). Then click
      "Publish all … drafts that pass the checks", or run on the host:
      `docker compose exec crash-course course publish --all --reviewer "Ruairi Powers"`.
- [ ] **Demo host:** `git pull && ./update.sh` builds `Dockerfile.space` (`/crash-course/`, 1g, `egress: true`, volume
      `/app/warehouse`). Set in the deploy `.env`: `COURSE_SECRET` (`openssl rand -hex 32`), `COURSE_OWNER_EMAIL`
      (your email; signing in with it opens `/owner`), `COURSE_PUBLIC_URL`, `RESEND_API_KEY` (shared), and
      `COURSE_MAIL_FROM` (e.g. `Crash course <courses@your-domain>`; falls back to the shared `MAIL_FROM`).
- [ ] **AWS Beginner (hand-written, v2):** review and publish it on `/owner` (it replaces the placeholder v1 draft the
      live site wrote on 14 Oct; reject that one). Then the AWS tracker shows Beginner "In progress".
- [ ] **Real writer model** (the live site now refuses the mock writer and says so on `/owner`; nothing is drafted
      until this is set): in the deploy `.env` set `COURSE_WRITER_MODEL=local-qwen` and `COURSE_OLLAMA_MODEL` to a
      model the shared Ollama has (`qwen3:14b` by default; the shared `OLLAMA_MODEL` is no longer used by this app),
      `ollama pull` it, `./update.sh --force`, then **Draft now** on `/owner` for each waiting level. Read each draft
      in the preview before publishing; a mid-size local model may need a second attempt or edits.
- [ ] Not run: the 16 hello-world projects that need an account, key, server or Docker (Airflow, Anthropic, AWS,
      Bedrock, Caddy, Chart.js, Cloudflare Tunnel, Docker, GitHub Actions, HF Spaces, MetricFlow (illustrative),
      Ollama, OpenAI, Postgres, pgvector, Terraform); Terraform `validate`; Resend in production.

## 00000. One Ollama on the EVO-X1 (14 October 2026, branch `agent/claude-shared-ollama`)

The demo stack ran its own CPU Ollama (`ai-portfolio-demos-ollama-1`, 7 GB loaded) next to the host's ROCm
`ollama-server`. `scripts/demos.py render selfhost` now also renders `ollama-shared`, a Caddy proxy that answers as
`ollama` on the internal network and forwards to the host's Ollama; `.env` picks one (`OLLAMA_BUNDLED` /
`OLLAMA_SHARED`, replica counts, so the installed `update.sh` is unchanged). Default unchanged (bundled).

- [ ] On the EVO-X1 after merge: set `OLLAMA_BUNDLED=0`, `OLLAMA_SHARED=1` in `deploy/selfhost/.env`, let
      `update.sh` deploy, run the README check, then `docker volume rm ai-portfolio-demos_ollama-models`.
- [ ] Not run here: a live stack (no Docker daemon in the sandbox). Checked: render, `docker compose config` in both
      modes, deploy guard (15 services OK both ways), `caddy validate` on the proxy config and a request through it
      to a stand-in upstream (Host rewritten), selfhost script tests, governance check.

## 0000. Launch tracker (new personal project, built 7 October 2026)

`projects/launch-tracker` + `site/personal/posts/launch-tracker.md` + tech pages (Prefect, Plotly). Every launch from
Launch Library 2 + GCAT + CelesTrak SATCAT, reconciled in DuckDB; countdowns, reuse, crews, measured slips, cited
costs (approval required), industry trend, orbit crowding; model summaries checked against the rows. Defaults taken
(Ruairi didn't answer): suborbital off by default (a setting), no 3D globe. Verified offline on a FICTIONAL sample:
30 tests, `launches all` 1.5 s, eval 9/9, governance / telemetry / image-deps / access / catalog checks,
`mkdocs build --strict`, app checked in Chromium (every tab).

- [ ] **Real data:** the sandbox can't reach the sources. On the EVO-X1: `pip install -e ".[ui]" && LAUNCHES_MODE=live
      launches fetch` (repeat hourly, or `launches refresh-loop`; the history backfill takes a few hours at 15
      requests/hour). Parsers follow field names checked against the live LL2 API and GCAT docs; the SATCAT header is
      the documented one but wasn't downloaded (robots.txt blocks automated fetches of records.php; the bulk
      `pub/satcat.csv` is used). A format change stops the load and prints the real header. Then replace the sample
      numbers in the README and post.
- [ ] **Demo host:** `git pull && ./update.sh` builds `Dockerfile.space` (`/launch-tracker/`, 1g). The spec sets
      `egress: true` (first demo after the console with outbound access) so the background refresher can fetch;
      optional `LL2_API_KEY` in `.env`. Without egress it serves the sample and says so.
- [ ] **Costs:** approve or reject the two real entries (NASA OIG SLS/Orion $4.1bn per launch; SpaceX rideshare
      $6,500/kg, Mar 2023) in the app or `launches approve <id> --reviewer "Ruairi Powers"`; add more with sources.
- [ ] Not run: Terraform (not installed), Prefect `serve` (flows import-checked only), real models.

## 000. Lil'Helper (new personal project, built 6 October 2026)

`projects/lil-helper` (Python engine + API + Streamlit demo, and `app/`, the Expo phone app) +
`site/personal/posts/lil-helper.md`. Decisions (5 Oct): personal tier; real iPhone app through TestFlight, Android
later; services Instacart+, Prime (Whole Foods), Costco; Google Calendar via .ics feed. Verified offline: 48 tests,
8-week simulation, eval gate 16/16 (must-reject recall 1.00), governance check, apply_access --check, demo and phone
app (web build at iPhone size) checked in a browser, app typecheck. Merged to `main` on 7 October with Ruairi's
go-ahead.

- [ ] **Household server on the EVO-X1:** `docker build -t lil-helper projects/lil-helper` and run with `.env`
      (`HELPER_SECRET` from `openssl rand -hex 32`, `RESEND_API_KEY`, `MAIL_FROM`) and the real
      `config/household.yaml` mounted read-only (never committed). Decide how the phone reaches it: a public
      hostname behind the magic-link sign-in, or Tailscale on her iPhone.
- [ ] **TestFlight:** Apple Developer account, then `app/README.md` steps (`eas init`, set `EXPO_PUBLIC_API_URL`,
      `eas build --platform ios`, `eas submit`, add her as an internal tester).
- [ ] **Instacart Developer Platform key** (`INSTACART_API_KEY`) for one-tap delivery links; development first.
- [ ] **Real data:** the family's recipes, store prices (`data/prices.yaml`, `verified` dates), then four real weeks
      and update the post's results table (all numbers today are simulated).
- [ ] **Real models:** `local-qwen` for ideas/notes and a local vision model for flyers; `helper eval --alias
      helper-candidate`, promote on a pass.
- [ ] **Public demo:** `git pull && ./update.sh` builds `Dockerfile.space` (`/lil-helper/`, mock only).
- [ ] Options documented, not built: two-adult approval above a spend threshold, automated retention pruning.
### Lil'Helper v2 (built 11–14 October 2026, merged to `main` 15 October)

Accounts and many households (admin/adult/kid roles, invites, welcome wizard, in-app settings), custom recipes,
specials by store and channel, shopping trips, dinner times and attendance, takeout/eat-out/leftovers/freezer
nights, kid chef, cards and partnerships, spending import (statements, receipts), budget and cost reports, cost per
serving range, fridge/freezer space and buy-ahead, cook from what I've got, ingredient forecast, per-person calendar
feeds with one-tap feedback, Expo push, a 15-minute scheduler tick per household. Verified offline: 71 tests, eval
gate 20/20, 8-week simulation, governance and access checks, mkdocs --strict, app typecheck, and the web build
walked through at iPhone size (wizard → first plan → approve → specials, recipe, forecast, money, calendar).

- [ ] **Server:** follow the new `docs/household-setup.md` (Cloudflare hostname `helper.agentls.com`, sign-up code,
      `HELPER_PUSH=expo`); import the v1 household file if you set one up.
- [ ] **TestFlight build** with push (say yes to push notifications in `eas build`); push and Apple/Google calendar
      subscribe are untested on a real phone.
- [ ] **Not done:** the Streamlit demo still shows v1 screens only; the App Store release work (AWS + RevenueCat +
      privacy) is planned in `docs/aws-native.md`, not built.

### Lil'Helper v3 (15 October 2026, merged to `main`)

Builds on `agent/claude-lil-helper-mail` (email fixes, Create household button). Change any planned meal (existing,
new, or from the web) with undo; meals move planned → today → what happened (eaten / leftovers / portions frozen /
skipped); freezer items editable, use-by-first planning; recipes: credit + link, add from the web (schema.org;
method stays at the source), export/import file, share with a household by code; cook-from ranks by what you typed
and writes a new recipe when nothing uses it all; calendar events link into the app and shopping events carry the
whole list. Verified offline: 88 tests, eval gate, governance, mkdocs, app typecheck, browser walk-through.

- [ ] New TestFlight build and server rebuild (both from `main`).
- [ ] Optional `BRAVE_API_KEY` on the server for in-app recipe search results (without it, search opens the browser).
- [ ] Not tested against live recipe sites from here (the sandbox can't reach them); parsing is tested on a fixture page.

### DinnerPeace: Lil'Helper renamed (16 October 2026, branch `agent/claude-dinnerpeace`)

Everything people see now says DinnerPeace: app name and permission prompts, screens, emails, calendar events, PDFs,
web pages, Alexa (invocation "dinner peace"), docs, post, wordmark (apple icon unchanged). App version 0.3.0. Kept on
purpose: repo folder and slug `lil-helper`, Python package `lilhelper`, the `helper` CLI, `HELPER_*` settings, bundle
id `com.agentls.lilhelper`, link scheme `lilhelper://`, EAS slug — so TestFlight, sign-ins, calendar links and data
carry over. Domain `dinnerpeace.app` reserved; moving the server to it is a documented option (household-setup.md).

- [ ] Ruairi: merge the PR; on the server `.env`, change `HELPER_MAIL_FROM`'s name to DinnerPeace (it wins over the
      code); App Store Connect → App Information → Name: DinnerPeace; then the TestFlight build.
- [ ] Optional: dinnerpeace.app on Cloudflare + `app.dinnerpeace.app` tunnel hostname + Resend domain.

### Lil'Helper v4 (15 October 2026, merged to `main`, PR #46)

Birthdays on profiles (child under 12 / teen / adult follows from them; teens adult portions, approve only if the
admin allows; no jobs on your birthday); special occasions (birthdays, US holidays on/off, anniversaries, own) feed
the plan; recipes suit breakfast/lunch/dinner with steps and calories for the whole book; own brand/store/price per
ingredient; book recipes on/off; meals with parts (cook / leftovers / ready-made); Today home tab; Make a plan (up to
12 weeks), Vibe cooking, Occasions, Weekly buffet, Surprise me; Reports (cost, time, calories, jobs); bulk Excel
import/export (admin, preview then confirm); voice (app mic via expo-speech-recognition / Web Speech, rules-based
`/api/voice`); Alexa skill backend (`alexa.py`, `docs/alexa.md`, `alexa/interaction-model.json`). Welcome screen
can cancel setup / sign out. Verified offline: 101 tests, eval gate, governance, mkdocs, app typecheck, browser
walk-through of every new screen.

- [ ] After merge: server rebuild and a **new TestFlight build** (speech recognition is a new native module).
- [ ] Alexa: create the skill in the Amazon developer console (`docs/alexa.md`), set `HELPER_ALEXA_SKILL_ID`. The
      certificate-chain check couldn't be run against Amazon's real certificate from the sandbox; the console's Test
      tab is the first live check.

## 000a. Data marketplace & lifecycle platform (featured, built 6 October 2026)

`projects/data-lifecycle-platform` + `site/blog/posts/data-lifecycle-platform.md` + tech pages (MetricFlow,
Oxigraph/SHACL, Dagster). Ontology, knowledge graph (Oxigraph, SHACL-gated), semantic layer (dbt + MetricFlow on
DuckDB) and context layer kept apart; vendor/dataset CRUD with custom fields, AI cataloguing, search with economic
factors, assess/compare, contracts and entitlements, ROI and retirement, monetization, marketplace adapters, REST API,
read-only MCP server (SDK 2.x), Dagster assets. Verified offline: 43 tests, `dlp all` (22 dbt tests, SHACL conforms,
19-case eval gate all 1.0), governance check, app checked in Chromium (every workflow).

- [ ] **Real data (Ruairi, on the EVO-X1):** `pip install -e ".[hub]" && dlp fetch && dlp build && dlp all`. The
      fixture's options column names come from the Hub viewer summary, not a download; `dlp fetch` stops with the real
      column list if they differ (then fix `semantic/models/staging/stg_options.sql`). Replace the fixture numbers in
      the README and post (results table, IV–HV test) with the real run.
- [ ] **Demo host:** `git pull && ./update.sh` builds `Dockerfile.space` (`/data-lifecycle-platform/`, 2g).
- [ ] **Real model:** point `dlp-candidate` at a priced model, run `dlp eval --alias dlp-candidate --baseline dlp-primary`.
- [ ] Not run against real services: Snowflake / ADX / Databricks adapters, S3/SFTP feeds, Terraform (`terraform` not
      installed in the build sandbox, so not even `validate`d).

## 00. Speaking coach (new personal project, built 5 October 2026)

`projects/speaking-coach` + `site/personal/posts/speaking-coach.md`, from Ruairi's own filler word list and
practice plan (the `starter` preset). Decisions: personal tier, no audio in v1, hosted demo text only. Verified
offline: 41 tests, `coach all`, eval gate (0.986 / 0.986; held-out 0.857), governance check, app checked in a
browser (default run, injection break-it, coaching tab), `mkdocs build --strict`. Merged to `main` on
5 October with Ruairi's go-ahead.

- [ ] **Demo host:** `git pull && ./update.sh` builds `Dockerfile.space` (`/speaking-coach/`, text only, 1g).
- [ ] **Real model:** point `coach-disambiguator` at a local model on the EVO-X1, run `coach eval`, and replace the
      mock numbers in the post's "What I'd do next".
- [ ] Options documented, not built: audio (faster-whisper, verbatim), a live buzzer (streaming the same rules),
      spaCy tagging for unclear words.

## 0a. Editorial agents + subscriptions (built 5 October 2026)

Pushed in `08e7707`, `6696723`, `86b9553`, `234a024`; CI green. The weekly scheduled task "Weekly blog post draft"
runs Thursdays 05:55 ET in the cloud and follows `.claude/skills/weekly-post`; its prompt holds the queue URL (never
commit it). A test run was fired on 5 October.

- [ ] **Demo host `.env`** (Ruairi, over SSH on the EVO-X1; replace the two `<…>` values):

      ```bash
      cd ~/ai-portfolio/deploy/selfhost && cp .env .env.bak.$(date +%F)
      setenv() { sed -i "/^$1=/d" .env; printf '%s=%s\n' "$1" "$2" >> .env; }
      for k in EDITORIAL_LINK_SECRET SUBSCRIBE_SECRET; do grep -q "^$k=." .env || setenv $k "$(openssl rand -hex 32)"; done
      setenv EDITORIAL_EMAIL '<your email>'
      setenv EDITORIAL_PUBLIC_URL 'https://demos.<your-domain>/editorial-agents'
      setenv ASSISTANT_PUBLIC_URL 'https://demos.<your-domain>/site-assistant'
      setenv EDITORIAL_CLASSIFIER_MODEL local-gemma        # optional: classify with the local model
      chmod 600 .env && grep -E '^(EDITORIAL|SUBSCRIBE|ASSISTANT_PUBLIC)' .env | sed 's/=.\{6\}.*/=<set>/'
      git -C ~/ai-portfolio pull && ./update.sh --force
      curl -s https://demos.<your-domain>/editorial-agents/api/health; echo
      curl -s https://demos.<your-domain>/editorial-agents/queue.md | head -20
      ```

      Optional Reddit source: create a "script" app at https://www.reddit.com/prefs/apps, then
      `setenv REDDIT_CLIENT_ID …; setenv REDDIT_CLIENT_SECRET …` and `./update.sh --force`.
- [ ] **GitHub** (Ruairi, on the Mac; `brew install gh && gh auth login` once):

      ```bash
      R=ruairipowers-commits/ai-portfolio
      gh label create draft-post --color 1d76db --description "AI-drafted post: merge to publish" -R $R
      gh label create needs-work --color d93f0b --description "Draft failed a check or scored below 4" -R $R
      gh secret set SMTP_HOST -b smtp.resend.com -R $R
      gh secret set SMTP_PORT -b 587 -R $R
      gh secret set SMTP_USER -b resend -R $R
      gh secret set SMTP_PASSWORD -R $R              # paste the Resend API key at the prompt (not echoed)
      gh secret set SMTP_FROM -b '<sender on your Resend-verified domain>' -R $R
      gh secret set ALERT_EMAIL -b '<your email>' -R $R
      gh label list -R $R | grep -E 'draft-post|needs-work' && gh secret list -R $R
      ```
- [ ] **First live scout run:** check the queue page and the Monday email, then update the post's measured table
      with live numbers (it only quotes the offline run).
- [ ] The 5 October test run of the weekly task finished in about 5 minutes without opening a PR, most likely a
      clean stop because the queue isn't served yet. Re-run it (or wait for Thursday) once the demo host is updated
      and its queue page loads.
- [ ] **Resume and LinkedIn:** point them at the 3-minute tour (`<site>/tour/`). Its three projects are
      `portfolio.yaml` `tour`; the audiences the blog filters by are `portfolio.yaml` `audiences`.

## 0. Daily puzzle (new personal project, built 4 October 2026)

`projects/daily-puzzle` + `site/personal/posts/daily-puzzle.md`. Built and verified offline (112 tests, `puzzle all`,
eval gate, player site and operator app checked in a browser). Pushed 5 October (`4dab046`); CI and the site
deploy passed, and the post is listed under Personal projects. The demo container isn't running yet:

- [ ] **Demo host:** `git pull && ./update.sh` on the EVO-X1 builds `Dockerfile.space` (`/daily-puzzle/`, 4g).
- [ ] **Deploy secrets** in the demo host's `.env` before it starts (the image refuses dev defaults):
      `PUZZLE_KEY_SECRET`, `PUZZLE_SALT`, `PUZZLE_ADMIN_TOKEN` (`openssl rand -hex 32`), `RESEND_API_KEY`,
      `MAIL_FROM`, `PUZZLE_OPERATOR_EMAIL`, `PUZZLE_PUBLIC_URL`.
- [ ] **Real models:** runs on the mock pair. Try `PUZZLE_GENERATOR_MODEL=local-qwen PUZZLE_SOLVER_MODEL=local-gemma`
      on the EVO-X1, run `puzzle eval --role generator`, and update the post's "What I'd do next" with real pass rates.
- [ ] Hugging Face live assets (`PUZZLE_LIVE_ASSETS=1`) not exercised yet: the Hub licence check and download path
      are untested against the live Hub.

## 1. Security fixes on the EVO-X1 (Ruairi's steps)

This repo is public, so the specifics live only in the private scan report on the machine
(`security/reports/pentest-*.md`, git-ignored) — ask Ruairi to paste it rather than writing details here.
The repo side is done; the remaining findings need commands on the machine:

- [ ] **H6:** replace the weak tokens in the deploy `.env` (`openssl rand -hex 32`), then `./update.sh --force`.
- [ ] **H5 / H1:** republish the personal (non-portfolio) Docker containers on `127.0.0.1`. Docker bypasses ufw;
      reach them from the Mac with `ssh -L`.
- [ ] **H2:** SSH key-only, after confirming key login from the Mac.
- [ ] **Mac access to the personal MCP server:** now firewalled from Wi-Fi; either allow the Mac's address or use
      Tailscale on the Mac. Not confirmed which was chosen.
- [ ] **Re-run the scan** (`git pull && sudo python3 security/pentest.py --all`) and confirm only accepted lows
      remain. E1/E2 (HTTPS redirect, HSTS) are fixed and verified with curl; a Cloudflare 403 to the scanner now
      reads as "not checked".

Done: firewall on, `install.sh` timers, deploy guard, hardened stack deployed, console crash fixed (`8bd1bb8`).

Accepted lows: Caddy and Ollama run as root inside their containers (all capabilities dropped,
no-new-privileges); base images not pinned by digest and Ollama/cloudflared on `:latest` (the daily maintenance
email reports new versions).

## 2. Blog posts waiting on a clean scan

Ruairi asked for these once the solutions are in place. Write them after section 1 is done, with the real
before/after scan results:

- [ ] Securing a self-hosted AI portfolio: deploy guard, root-owned host scripts, container hardening, firewall,
      the weekly self-assessment, and what the live scan found (including the honest mistakes: the Caddy
      capability and the console's missing dependency, both caught and fixed).
- [ ] Monitoring, updates and backups: the console's Host tab and alerts, the GitHub uptime check (which caught
      the console outage), the daily update check, nightly backups and restore.

## 3. Other open items

- [ ] **Private AI workbench post** (`site/personal/posts/private-local-ai.md`): its "What's next" promises a GPU
      benchmark of the local models (no speed figures are quoted yet) and OpenClaw on local models only. Update the
      post when either is done.
- [ ] **Faster Ask answers:** try Ollama on the iGPU through Vulkan (`deploy/selfhost/README.md`, "Faster
      answers"), then re-run `siteassist bench`.
- [ ] **Agentic course post:** the module table in `site/classes/posts/applied-agentic-ai.md` isn't verified
      against slide 11 of the orientation deck ("MPE Agentic AI Orientation English - 2026-2"); it needs the deck.
- [ ] **GitHub settings** (Ruairi): a ruleset on `main` (no force push or deletion, CI required), secret scanning
      with push protection, and Dependabot alerts.
