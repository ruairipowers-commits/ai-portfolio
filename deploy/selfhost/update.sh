#!/usr/bin/env bash
# Pull main and (re)deploy the live demos on this machine. Safe to run on a timer: does nothing if main hasn't moved.
#   deploy/selfhost/update.sh            # deploy if there are new commits
#   deploy/selfhost/update.sh --force    # re-render and rebuild regardless
# Needs: git, Docker with the compose plugin. Python runs inside a container, so nothing else is installed on the host.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
cd "$REPO"
[ -f "$HERE/.env" ] || { echo "Missing $HERE/.env — copy .env.example and fill it in"; exit 1; }

before="$(git rev-parse HEAD)"
git fetch --quiet origin main
git merge --ff-only --quiet origin/main || { echo "Local changes block a fast-forward; this clone should be deploy-only"; exit 1; }
after="$(git rev-parse HEAD)"
if [ "$before" = "$after" ] && [ "${1:-}" != "--force" ] && docker compose -f "$HERE/generated/docker-compose.yml" --env-file "$HERE/.env" ps -q 2>/dev/null | grep -q .; then
  exit 0
fi
echo "$(date -Is) deploying $(git rev-parse --short HEAD)"

set -a; . "$HERE/.env"; set +a
docker run --rm -v "$REPO:/repo" -w /repo -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -e PORTFOLIO_DEMOS_TARGET=selfhost -e PORTFOLIO_DEMOS_URL="$DEMOS_URL" \
  -e PORTFOLIO_SITE_URL="$SITE_URL" -e PORTFOLIO_GITHUB_OWNER="$GITHUB_OWNER" \
  python:3.11-slim sh -c "pip install -q --user --disable-pip-version-check pyyaml 2>/dev/null && python scripts/demos.py render selfhost"

profile=""; [ -n "${TUNNEL_TOKEN:-}" ] && profile="--profile tunnel"
docker compose -f "$HERE/generated/docker-compose.yml" --env-file "$HERE/.env" $profile up -d --build --remove-orphans
docker image prune -f >/dev/null
echo "$(date -Is) done: $DEMOS_URL"
