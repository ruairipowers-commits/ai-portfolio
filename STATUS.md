# Status — open items

What's in flight, so a new chat can pick up without the old one's history. Newest context first; tick items off
(or delete them) as they're done. Last updated 4 October 2026.

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
- [ ] Optional, offered and not requested: a `hidden` list in `portfolio.yaml` to hide a project from the site.
