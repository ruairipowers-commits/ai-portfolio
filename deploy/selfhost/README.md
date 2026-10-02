# Self-hosting the live demos (free)

Runs every demo on one machine with Docker, behind a free **Cloudflare Tunnel** on your own domain:
`https://demos.<your-domain>/<app>/`. Nothing is opened on your router — the tunnel connects outbound.
Everything comes back on its own after a reboot, and a push to `main` is live a few minutes after its GitHub
Actions checks pass (CI-gated continuous deployment — no inbound access from GitHub needed).

```
visitor ── https://demos.example.com/<app>/ ── Cloudflare ══ tunnel ══ cloudflared ── Caddy :80 ─┬─ altdata-triage
                                                                                                    ├─ eod-heartbeat
                                                     (all in one docker compose network)           ├─ trade-ops-exceptions
                                                                                                    ├─ research-qa-rag
                                                                                                    └─ governance-console
```

Everything below is generated from the repo (`python scripts/demos.py render selfhost`), so a new project with a
`Dockerfile.space` is deployed with no change here.

## What you need

- A machine that stays on, with **Docker** (Linux: Docker Engine + compose plugin; Windows: Docker Desktop with WSL2 —
  run these steps inside the WSL shell) and **git**. Roughly 8–12 GB RAM free for all five apps, ~15 GB disk.
- Your domain on Cloudflare (free plan is fine).
- Tailscale is optional: handy for reaching the machine and for `DEMOS_BIND=<tailscale IP>` private previews,
  but the public site goes through the Cloudflare Tunnel.

## One-time setup

**1. Create the tunnel (Cloudflare dashboard, ~3 minutes)**
1. *Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared*. Name it `ai-portfolio-demos`.
2. On the *Install connector* page, copy the **token** (the long string after `--token`). Don't run their install
   command — the token goes in `.env` and the tunnel runs as a container.
3. *Public hostname*: subdomain `demos`, domain `<your-domain>`, path empty, **service `HTTP` → `caddy:80`**. Save.

**2. On the machine**

```bash
git clone https://github.com/<you>/ai-portfolio.git ~/ai-portfolio     # a deploy-only clone
cd ~/ai-portfolio/deploy/selfhost
cp .env.example .env && nano .env      # DEMOS_URL, SITE_URL, GITHUB_OWNER, TUNNEL_TOKEN, two governance tokens
sudo usermod -aG docker "$USER"        # once, then log out and back in
./update.sh --force                    # first build: 10–20 minutes (it builds all five images)
./install.sh                           # Linux: start at boot + deploy every CI-passed commit on main
```

Open `https://demos.<your-domain>/` — a landing page lists the apps; each app is at `/<app>/`.

**3. In GitHub** (*Settings → Secrets and variables → Actions → Variables*), so the site and READMEs link to it:
`DEMOS_URL = https://demos.<your-domain>` (and `DEMOS_TARGET = selfhost` if you ever change portfolio.yaml).
Then re-run the **site** workflow.

## Reboots and continuous deployment

`install.sh` sets up two things:

- **Start at boot.** Docker and containerd are enabled, and every container has `restart: unless-stopped`, so the
  stack comes back with Docker. 30 seconds after boot the deploy timer also runs once and starts anything that
  isn't up (for example after a `docker compose down`).
- **Deploy on push, after CI.** Every 2 minutes `update.sh` fetches `main`. When there's a new commit it asks
  GitHub for that commit's check runs (the `ci` workflow tests every project; the `site` workflow checks
  governance coverage and builds the blog) and waits until they finish:

```
push to main ─▶ GitHub Actions: ci (every project's tests) + site (governance, blog)
                         │ all passed?
EVO-X1 timer (2 min) ────┴─ yes ─▶ git pull ─▶ render ─▶ docker compose up --build ─▶ live
                         └─ failed ─▶ keep serving the last good commit; skip this one
```

A build that fails on the machine also leaves the previous containers serving, and that commit isn't retried
until a newer one lands. `update.sh --status` shows what's deployed, what's on `main` and the CI state.
`update.sh --force` deploys the newest commit immediately without waiting for CI. Set `DEPLOY_SKIP_CI=1` in
`.env` to turn the gate off, and `GITHUB_TOKEN` (read-only) if the repo is private or you hit GitHub's
60-requests-an-hour anonymous limit.

## Day to day

| Task | Command |
|---|---|
| What's deployed / waiting for CI | `deploy/selfhost/update.sh --status` |
| Deploy now, skipping the CI gate | `deploy/selfhost/update.sh --force` |
| Logs | `docker compose -f deploy/selfhost/generated/docker-compose.yml logs -f trade-ops-exceptions` |
| Timer status / logs | `systemctl list-timers ai-portfolio-demos` · `journalctl -u ai-portfolio-demos -f` |
| Stop everything | `docker compose -f deploy/selfhost/generated/docker-compose.yml --profile tunnel down` |
| Private preview over Tailscale | set `DEMOS_BIND=<tailscale IP>` in `.env`, `update.sh --force`, open `http://<tailscale IP>:8088/` |

Windows without systemd: run `update.sh` from Task Scheduler every 2 minutes and at log-on
(`wsl -d <distro> -- /home/<you>/ai-portfolio/deploy/selfhost/update.sh`).

## What's isolated and what isn't

- Each app runs as a non-root user in its own container with a memory cap; visitors each get a private copy of
  the data inside the app, and **Reset** only affects their copy.
- The governance console keeps its history in a Docker volume on this machine (it survives rebuilds), or in
  Postgres if you set `GOVERNANCE_DATABASE_URL`.
- Only Caddy is reachable, and only from this machine (or the address in `DEMOS_BIND`); the public path is the tunnel.
- Cloudflare's free plan adds DDoS protection; add a rate-limiting rule on `demos.<your-domain>` if you expect traffic.
- When the machine is off or asleep, the demos are down — set it never to sleep.
