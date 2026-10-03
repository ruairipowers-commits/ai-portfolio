# Security self-assessment

`security/pentest.py` is a repeatable, non-destructive security check of **the portfolio's own assets**: this repo,
the blog on GitHub Pages, the live demos at `https://demos.agentls.com/<app>/`, the EVO-X1 that serves them, and the
GitHub repository settings. It runs on Python 3.11 with the standard library plus `httpx`, and falls back to `urllib`
when `httpx` isn't installed.

Each check returns findings with a severity (`critical`, `high`, `medium`, `low`, `info`), the evidence, and a
concrete fix. Secrets are never printed. The report only says whether a secret is set, and its length.

## Modes

```bash
python3 security/pentest.py --repo        # default when no mode is given
python3 security/pentest.py --external    # HTTP probes against SITE_URL / DEMOS_URL
python3 security/pentest.py --host        # on the EVO-X1 itself (sudo gives more answers, but isn't required)
GITHUB_TOKEN=… python3 security/pentest.py --github
python3 security/pentest.py --all         # all four
```

| Option | Default |
|---|---|
| `--site-url` | `$PORTFOLIO_SITE_URL`, then `$SITE_URL`, then `SITE_URL` in the deploy `.env` |
| `--demos-url` | `$DEMOS_URL`, then `DEMOS_URL` in the deploy `.env` |
| `--env-file` / `--compose` | `deploy/selfhost/.env` / `deploy/selfhost/generated/docker-compose.yml` |
| `--out` | `security/reports/pentest-YYYY-MM-DD.md` (git-ignored) |
| `--state` | `deploy/selfhost/.state/pentest.json` (the summary the governance console reads) |
| `--llm` | off. Sends one prompt-injection question to the assistant's `/api/chat` |
| `--burst N` | off. Sends N (at most 40) quick searches to see whether the rate limit kicks in |
| `--strict` | off. Exits 1 when there's a critical or high finding (otherwise it always exits 0) |

The JSON state file has this shape: `{"ts", "ok" (no critical or high findings), "counts", "report", "report_md"
(truncated to 150k characters), "findings": [{id, severity, title, fix}, …]}`. `findings` holds the 40 most severe.

## What it checks

**Repo**
- **R1** Searches every line ever added in `git log -p --all` for GitHub, AWS, Slack and Resend tokens, private keys,
  and long random values assigned to `*TOKEN*`, `*KEY*`, `*SECRET*` or `*PASSWORD*`. It skips placeholders and test
  fixtures, and also flags secret files tracked by git (such as `deploy/selfhost/.env`).
- **R2** Runs `pip-audit` on each `projects/*/pyproject.toml` and `npm audit` on the trade-ops MCP server, when those
  tools are installed.
- **R3** Checks the GitHub Actions workflows for `pull_request_target`, a missing top-level `permissions:`,
  third-party actions not pinned to a commit SHA, and `${{ github.event… }}` used inside scripts.
- **R4** Checks each `Dockerfile.space` for a non-root `USER`, base images pinned by digest, and `curl | sh`.
- **R5** Checks the compose file for privileged containers, `docker.sock` mounts, host network/pid/ipc, bind mounts
  outside `deploy/selfhost`, missing memory and CPU limits (Ollama especially), missing `no-new-privileges` or
  `cap_drop`, ports published on all interfaces, and `:latest` images. When the generated file is missing or older
  than `scripts/demos.py`, the check renders a fresh one into a temporary directory and checks that instead.

**External** sends about 25 requests by default and never more than 40 (plus `--burst`). All of them go to the two
base URLs.
- **E1** Plain HTTP redirects to HTTPS.
- **E2** Security headers on the demos host: HSTS, `nosniff`, framing, Referrer-Policy, and whether the server
  version leaks. The headers GitHub Pages sends are fixed by GitHub, so the report notes them as info.
- **E3** Owner endpoints refuse anonymous requests: assistant `/stats`, `/admin/content`, `/digest/send`,
  `/admin/suggestions/1`, and the console's `/content/suggestions/1`. The console kill-switch probe only sends
  "switch ON", and only when the workflow is already on. If an owner has switched it off, the probe is skipped.
- **E4** The console's ingest endpoint (`POST /api/events` with an empty list, which writes nothing) needs a token.
- **E5** The site assistant's CORS policy doesn't echo a foreign origin.
- **E6** Whether the API docs and OpenAPI schema are public.
- **E7** Ollama can't be reached through the public host.
- **E8** `/.env`, `/.git/config` and similar paths aren't served.
- **E9** (`--llm` only) The assistant doesn't recite its system prompt when asked to.
- **E10** (`--burst N` only) Whether the search rate limit kicks in.

**Host** (on the EVO-X1). Anything it can't read without root is reported as unknown; the run doesn't fail.
- **H1** TCP ports listening on non-loopback addresses, other than SSH and Tailscale.
- **H2** sshd password authentication and root login.
- **H3** ufw or nftables default-deny.
- **H4** unattended-upgrades is enabled, and whether a reboot is pending.
- **H5** Running containers (`docker inspect`): privileged, host network, `docker.sock`, root user, no memory or CPU
  limit, added capabilities, no `no-new-privileges`, ports published on all interfaces. Also lists the members of the
  docker group.
- **H6** `deploy/selfhost/.env`: mode 600 and owned by the deploy user; the ingest and admin tokens are set and at
  least 24 characters; `DEPLOY_SKIP_CI=0`; the SMTP password is set.
- **H7** The deploy clone holds no push credentials: no credential helper `store`, no `~/.git-credentials`, and no
  token in the remote URL.
- **H8** `/usr/local/lib/ai-portfolio/deploy-guard.py` exists, is owned by root, and the deploy user can't write to it.
  The guard (`deploy/selfhost/deploy-guard.py`) checks the resolved compose stack before every deploy. Its tests
  are in `security/tests/test_deploy_guard.py`.

**GitHub** needs `GITHUB_TOKEN` with Administration read access. Without it, these checks are skipped and reported
as info.
- **G1** Branch protection or a ruleset on `main`: required status checks, no force pushes, no deletion.
- **G2** Dependabot alerts.
- **G3** Secret scanning and push protection.

## Where it runs

- **Every commit (CI).** The `security` job in `.github/workflows/ci.yml` runs `--repo --strict` with `pip-audit`
  installed. A critical or high finding fails CI, and the demo machine won't deploy the commit.
- **Every Sunday on the EVO-X1.** `sudo deploy/selfhost/install.sh` installs `ai-portfolio-pentest.timer`, which runs
  a root-owned copy of this script with `--all`. The summary goes to `deploy/selfhost/.state/pentest.json`;
  hostmon.sh passes it to the console, which emails it and shows the findings to admins on the Host tab. The full
  report stays on the machine (`security/reports/pentest-latest.md`, git-ignored). The script always exits 0 without
  `--strict`, so a finding never fails the timer unit.

## Safety

- **Own assets only.** Only point it at the portfolio's own URLs and machines.
- **Non-destructive.** Every write it attempts is one that must be refused, or one that changes nothing: an empty
  ingest batch, or "switch ON" for a workflow that's already on. A probe that gets through is reported as a finding.
  The probe doesn't retry it or go any further.
- **Rate-capped.** External probes stop at 40 requests by default. `--burst` is opt-in and capped at 40, and the
  default per-visitor limit (120 searches an hour) is well above that.
- **No secrets in output.** Values are reported only as "set / not set / length N". A secret found in git history is
  reported by commit, file and a short hash, never by its value.
- If the demos host can't be reached, the probes stop after the first request and the report says so.

## Tests

```bash
python3 -m pytest security/tests -q
```

The tests are offline. They use temporary git repositories, workflow, compose and Dockerfile fixtures, a local HTTP
stub standing in for the demos host, and a temporary `.env`.
