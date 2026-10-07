# Status — open items

What's in flight, so a new chat can pick up without the old one's history. Newest context first; tick items off
(or delete them) as they're done. Last updated 7 October 2026.

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
- [ ] Options documented, not built: push notifications (needs the EAS project id), Google Calendar API push,
      two-adult approval above a spend threshold, automated retention pruning.
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
