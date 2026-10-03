#!/usr/bin/env bash
# Continuous deployment of the live demos on this machine. Run by a systemd timer every 2 minutes (install.sh) and
# once at boot. Each run:
#   1. fetches main; if the newest commit is already deployed, just makes sure the containers are up;
#   2. otherwise waits until that commit's GitHub Actions checks have finished and passed (CI gate);
#   3. renders the stack from the repo, rebuilds what changed, and records the commit as deployed.
# A failed build leaves the previous containers running, and isn't retried until there's a newer commit.
#
#   deploy/selfhost/update.sh            # the above
#   deploy/selfhost/update.sh --force    # deploy the newest commit now: skip the CI gate, rebuild regardless
#   deploy/selfhost/update.sh --status   # what's deployed, what's on main, and the CI state
# Needs: git, curl, Docker with the compose plugin. Python runs inside a container; nothing else on the host.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
STATE="$HERE/.state"; mkdir -p "$STATE"
MODE="${1:-}"
cd "$REPO"
[ -f "$HERE/.env" ] || { echo "Missing $HERE/.env — copy .env.example and fill it in"; exit 1; }
set -a; . "$HERE/.env"; set +a

# one run at a time (a build can outlast the timer interval)
exec 9>"$STATE/lock"
flock -n 9 || { echo "another deploy is running"; exit 0; }

COMPOSE=(docker compose -f "$HERE/generated/docker-compose.yml" --env-file "$HERE/.env")
[ -f "$HERE/docker-compose.override.yml" ] && COMPOSE+=(-f "$HERE/docker-compose.override.yml")   # local tweaks (GPU)
[ -n "${TUNNEL_TOKEN:-}" ] && COMPOSE+=(--profile tunnel)
log() { echo "$(date -Is) $*"; }
running() { [ -f "$HERE/generated/docker-compose.yml" ] && "${COMPOSE[@]}" ps -q 2>/dev/null | grep -q .; }
py() { if command -v python3 >/dev/null; then python3 "$@"; else docker run --rm -i python:3.11-slim python "$@"; fi; }

# owner/repo from the clone's remote (https or ssh form)
SLUG="$(git config --get remote.origin.url | sed -E 's#(\.git)?$##; s#^.*github\.com[:/]##')"

ci_state() {   # success | pending | failure for one commit, from GitHub's check runs
  local sha="$1" auth=()
  [ -n "${GITHUB_TOKEN:-}" ] && auth=(-H "Authorization: Bearer $GITHUB_TOKEN")
  curl -fsS "${auth[@]}" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$SLUG/commits/$sha/check-runs?per_page=100" 2>/dev/null |
  py -c '
import json, sys, time, datetime as dt
try:
    runs = json.load(sys.stdin)["check_runs"]
except Exception:
    print("pending"); sys.exit()          # GitHub unreachable or rate-limited: try again next tick
bad = {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}
if any(r["status"] == "completed" and r["conclusion"] in bad for r in runs):
    print("failure")
elif not runs or any(r["status"] != "completed" for r in runs):
    print("pending")                       # not started yet, or still running
else:
    print("success")
' || echo pending
}

git fetch --quiet origin main
target="$(git rev-parse origin/main)"
deployed="$(cat "$STATE/deployed" 2>/dev/null || true)"
failed="$(cat "$STATE/failed" 2>/dev/null || true)"

if [ "$MODE" = "--status" ]; then
  echo "deployed: ${deployed:-none}"; echo "main:     $target ($(git log -1 --format=%s "$target"))"
  echo "CI:       $(ci_state "$target")"; [ -n "$failed" ] && echo "last failed: $failed"
  running && echo "containers: up" || echo "containers: down"; exit 0
fi

if [ "$MODE" != "--force" ]; then
  if [ "$target" = "$deployed" ]; then
    running || { log "containers down — starting $(git rev-parse --short HEAD)"; "${COMPOSE[@]}" up -d; }
    exit 0
  fi
  [ "$target" = "$failed" ] && { running || "${COMPOSE[@]}" up -d 2>/dev/null || true; exit 0; }
  if [ "${DEPLOY_SKIP_CI:-0}" != "1" ]; then
    ci="$(ci_state "$target")"
    case "$ci" in
      pending) log "waiting for CI on ${target:0:7}"; running || { [ -n "$deployed" ] && "${COMPOSE[@]}" up -d; } || true; exit 0 ;;
      failure) log "CI failed on ${target:0:7} — not deploying it; keeping ${deployed:0:7}"; echo "$target" > "$STATE/failed"
               running || { [ -n "$deployed" ] && "${COMPOSE[@]}" up -d; } || true; exit 0 ;;
    esac
  fi
fi

git merge --ff-only --quiet "$target" || { log "local changes block a fast-forward; this clone should be deploy-only"; exit 1; }
log "deploying $(git rev-parse --short HEAD): $(git log -1 --format=%s)"

docker run --rm -v "$REPO:/repo" -w /repo -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -e PORTFOLIO_DEMOS_TARGET=selfhost -e PORTFOLIO_DEMOS_URL="$DEMOS_URL" \
  -e PORTFOLIO_SITE_URL="$SITE_URL" -e PORTFOLIO_GITHUB_OWNER="$GITHUB_OWNER" \
  python:3.11-slim sh -c "pip install -q --user --disable-pip-version-check pyyaml 2>/dev/null && python scripts/demos.py render selfhost"

if "${COMPOSE[@]}" up -d --build --remove-orphans; then
  echo "$target" > "$STATE/deployed"; rm -f "$STATE/failed"
  docker image prune -f >/dev/null
  log "done: $DEMOS_URL"
else
  echo "$target" > "$STATE/failed"
  log "build failed for ${target:0:7}; the previous containers are still serving. Fix and push, or run update.sh --force."
  exit 1
fi
