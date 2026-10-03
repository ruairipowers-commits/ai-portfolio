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

## The site assistant and its model

The stack includes `site-assistant` (the blog's **Ask** button) and an `ollama` container for its local model.
On first start the assistant asks Ollama to download `OLLAMA_MODEL`. Until that finishes, it answers by quoting
passages. Check progress with `docker compose … logs -f ollama`, or look for `model_ready` in
`https://demos.<your-domain>/site-assistant/api/health`.

### Faster answers

Most of the wait on a CPU is the model *reading* the prompt, not writing the answer. What's already done for you:

- **The model stays loaded** (`keep_alive` 24 h) and is **warmed up** at start-up, so nobody waits for a cold load.
- **The prompt starts the same way every time.** The rules and the profile card come first and don't change between
  questions, so Ollama reuses its cached reading of them and only reads the question and the search results.
  One model and one request at a time (`OLLAMA_NUM_PARALLEL=1`) keeps that cache warm.
- **A context window sized to the prompt** (`num_ctx` 8192 in `config/settings.yaml`), so nothing is cut off and
  memory isn't wasted.
- **Reasoning switched off** for reasoning models (`OLLAMA_THINK=false`): they answer directly instead of thinking
  first.

**Pick the model on this machine.** Compare candidates with the same questions, then set `OLLAMA_MODEL` in `.env`:

```bash
docker compose -f generated/docker-compose.yml --env-file .env exec site-assistant \
  siteassist bench gemma4:e4b qwen3.5:9b --out /tmp/answers.md
docker compose -f generated/docker-compose.yml --env-file .env exec site-assistant cat /tmp/answers.md
```

It pulls any missing model, then prints the load time, time to the first word, reading and writing speed for a fit
question, a gap question and a technical one, run twice (the second run uses the cached prefix). The answers file
lets you judge quality side by side. A good choice answers in a few seconds, cites its sources, and turns the gap
question into "on Ruairi's plate to review" without inventing anything.

| Model | Download | Measured on the EVO-X1 (CPU, 3 October 2026) |
|---|---|---|
| `gemma4:e4b` | 6.6–9.5 GB | **The default.** First word in 6–10 s, answers in 10–18 s, writes about 28 tokens/s. Accurate, cites sources, and uses the "on Ruairi's plate to review" wording for gaps |
| `qwen3.5:9b` | 6.6 GB | First word in 12–27 s, answers in 25–55 s, about 12.5 tokens/s. Fuller answers, but misspelt the name and stretched some claims |
| `llama3.1:8b` | 4.9 GB | The previous default; slower to load, fewer citations |
| `qwen3.5:4b` | 3.4 GB | Not measured; the smallest option if memory is tight |

Most of the time to the first word is the model reading the prompt (about 450 tokens/s on the CPU). The iGPU is the
biggest remaining lever for that:

**Use the iGPU (Vulkan).** The Radeon iGPU reads prompts much faster than the CPU. Recent Ollama builds can use it
through Vulkan (still marked experimental). Create `deploy/selfhost/docker-compose.override.yml` (git-ignored):

```yaml
services:
  ollama:
    devices: ["/dev/dri:/dev/dri"]
    group_add: ["video", "render"]
    environment:
      OLLAMA_VULKAN: "1"
```

Then `docker compose … up -d ollama` and check `docker compose … logs ollama | grep -i vulkan`: it should list the
GPU. If it doesn't, delete the override and stay on CPU. The iGPU shares system memory: the amount it may use is set
in the BIOS (UMA frame buffer) and by the kernel. Run `siteassist bench` before and after to see the difference.

**Owner pages.** `https://demos.<your-domain>/site-assistant/stats?token=<ASSISTANT_ADMIN_TOKEN>` shows the last
14 days, every search and question, and a button that sends the daily engagement email now. The email also goes
out by itself every day at 07:00 New York time. Add `CF_*` and `GITHUB_TRAFFIC_TOKEN` to `.env` to include
Cloudflare and GitHub numbers; without them the email says what's missing.

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
