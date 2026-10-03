#!/usr/bin/env bash
# Weekly "what needs updating" check for the demo host. READ-ONLY: it never upgrades, pulls or restarts anything;
# it lists the exact commands for you to run.
#   - OS: upgradable apt packages (and how many from -security), /var/run/reboot-required (+ .pkgs)
#     (counts come from the last `apt update`; Ubuntu refreshes the lists daily by itself)
#   - Docker images the stack runs (ollama, caddy, cloudflared from generated/docker-compose.yml) and the base
#     images of the app builds (FROM lines of projects/*/Dockerfile.space): local digest vs. the registry's
#     current digest for the same tag (docker buildx imagetools inspect; null when the registry can't be asked)
#   - Ollama server version and the configured OLLAMA_MODEL; Docker engine version
#   - free disk on / and on Docker's data root (the smaller is reported); hours since the last good backup
# Result: deploy/selfhost/.state/maintenance.json
#   {"ts", "apt_upgradable", "apt_security", "reboot_required", "reboot_pkgs", "images": [{"image",
#    "update_available"}], "ollama_version", "docker_version", "disk_free_gb", "backup_age_hours",
#    "actions": ["command to run", …], "ok": true when there is nothing to do}
#
#   deploy/selfhost/maintenance.sh          # check, print a summary, write the JSON
#   deploy/selfhost/maintenance.sh --json   # same, and print the JSON
# Thresholds: MAINT_MIN_FREE_GB (default 10), MAINT_BACKUP_MAX_HOURS (default 36).
# Overrides for testing: ENV_FILE, STATE_DIR, COMPOSE_FILE, PROJECTS_DIR.
# Needs: Docker (buildx plugin for digests), GNU coreutils. No Python on the host.
#
# systemd (Linux) — /etc/systemd/system/ai-portfolio-maintenance.service  (replace USER and the path):
# ---------------------------------------------------------------------------------------------
# [Unit]
# Description=Weekly update check for the AI portfolio demo host (read-only)
# After=docker.service network-online.target
# Wants=network-online.target
#
# [Service]
# Type=oneshot
# User=USER
# ExecStart=/home/USER/ai-portfolio/deploy/selfhost/maintenance.sh
# TimeoutStartSec=15min
# ---------------------------------------------------------------------------------------------
# /etc/systemd/system/ai-portfolio-maintenance.timer:
# ---------------------------------------------------------------------------------------------
# [Unit]
# Description=Weekly update check for the AI portfolio demo host (Sunday 06:00)
#
# [Timer]
# OnCalendar=Sun *-*-* 06:00:00
# Persistent=true
#
# [Install]
# WantedBy=timers.target
# ---------------------------------------------------------------------------------------------
# Enable: sudo systemctl daemon-reload && sudo systemctl enable --now ai-portfolio-maintenance.timer
# Logs:   journalctl -u ai-portfolio-maintenance
set -euo pipefail

# Installed copies (/usr/local/lib/ai-portfolio, root-owned) are told where the deploy clone is.
if [ -n "${AI_PORTFOLIO_REPO:-}" ]; then HERE="$AI_PORTFOLIO_REPO/deploy/selfhost"; else HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; fi

# ---------------------------------------------------------------- pure helpers (sourced by tests) ----

json_str() {
  local s="${1-}"
  s="${s//\\/\\\\}"; s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"; s="${s//$'\r'/\\r}"; s="${s//$'\t'/\\t}"
  s="$(printf '%s' "$s" | tr -d '\000-\010\013\014\016-\037')"
  printf '"%s"' "$s"
}
json_or_null() { if [ -n "${1-}" ]; then json_str "$1"; else printf null; fi; }   # string or null
num_or_null() { if [ -n "${1-}" ]; then printf '%s' "$1"; else printf null; fi; }   # number/bool or null
json_array() { local x sep="" out="["; for x in "$@"; do out+="$sep$(json_str "$x")"; sep=", "; done; printf '%s]' "$out"; }

# compose_images FILE -> "service<TAB>image" for every service with an image: line that isn't built here
compose_images() {
  awk '
    /^services:/ { in_s = 1; next }
    /^[^ #]/     { in_s = 0 }
    in_s && /^  [A-Za-z0-9_.-]+:[[:space:]]*$/ { svc = $1; sub(/:$/, "", svc) }
    in_s && /^    image:/ { img = $0; sub(/^    image:[[:space:]]*/, "", img); gsub(/["'\'']/, "", img)
                            if (img !~ /^ai-portfolio\//) print svc "\t" img }
  ' "$1"
}

# resolve_ref '${OLLAMA_IMAGE:-ollama/ollama:latest}' -> value of OLLAMA_IMAGE or the default
resolve_ref() {
  local r="$1" var def
  if [[ "$r" =~ ^\$\{([A-Za-z_][A-Za-z0-9_]*):?-(.*)\}$ ]]; then
    var="${BASH_REMATCH[1]}"; def="${BASH_REMATCH[2]}"; r="${!var:-$def}"
  fi
  printf '%s' "$r"
}

# dockerfile_bases FILE… -> distinct external base images (skips build-stage names and scratch)
dockerfile_bases() {
  awk 'toupper($1) == "FROM" {
         img = $2; if (img ~ /^--/) img = $3
         for (i = 1; i <= NF; i++) if (toupper($i) == "AS") stages[$(i + 1)] = 1
         if (!(img in stages) && img != "scratch") print img
       }' "$@" | sort -u
}

# hours_since ISO8601Z [now_epoch] -> hours with one decimal (empty when the timestamp is unparsable)
hours_since() {
  local t0 now; t0="$(date -u -d "$1" +%s 2>/dev/null)" || return 0
  now="${2:-$(date -u +%s)}"
  awk -v a="$t0" -v b="$now" 'BEGIN { printf "%.1f", (b - a) / 3600 }'
}

# json_field FILE KEY -> raw value of a top-level scalar ("ts" -> 2026-…, "ok" -> true)
json_field() {
  grep -o "\"$2\": *\\(\"[^\"]*\"\\|true\\|false\\|null\\|[0-9.]*\\)" "$1" 2>/dev/null | head -1 |
    sed -E "s/^\"$2\": *//; s/^\"(.*)\"$/\\1/"
}

# last_good_backup_ts STATE_DIR -> ts of the newest successful backup (empty if none)
last_good_backup_ts() {
  local st="$1"
  if [ -f "$st/backup.json" ] && [ "$(json_field "$st/backup.json" ok)" = true ]; then
    json_field "$st/backup.json" ts
  elif [ -f "$st/backup_last_ok" ]; then
    head -1 "$st/backup_last_ok"
  fi
}

# registry_digest REF -> current digest for the tag at the registry (empty on failure)
registry_digest() {
  local d
  d="$(timeout 60 docker buildx imagetools inspect "$1" --format '{{json .Manifest.Digest}}' 2>/dev/null | tr -d '"[:space:]')" || d=""
  if [[ "$d" != sha256:* ]]; then   # fallback: single-arch manifests only (lists carry no index digest)
    d="$(timeout 60 docker manifest inspect -v "$1" 2>/dev/null | head -c 4096 |
          awk 'NR==1 && !/^\{/ { exit } { print }' | grep -o '"digest": *"sha256:[0-9a-f]*"' | head -1 |
          grep -o 'sha256:[0-9a-f]*')" || d=""
  fi
  printf '%s' "$d"
}

# update_available REF -> true | false | "" (unknown: not pulled locally, or registry unreachable)
update_available() {
  local ref="$1" local_digests remote
  local_digests="$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$ref" 2>/dev/null |
                   sed -n 's/.*@//p')" || local_digests=""
  [ -n "$local_digests" ] || return 0
  remote="$(registry_digest "$ref")"
  [ -n "$remote" ] || return 0
  if grep -qxF "$remote" <<< "$local_digests"; then printf false; else printf true; fi
}

# ----------------------------------------------------------------------------------------- main ----

maintenance_main() {
  local print_json=0
  case "${1:-}" in
    "") ;; --json) print_json=1 ;;
    -h|--help) sed -n '2,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; return 2 ;;
  esac
  ENV_FILE="${ENV_FILE:-$HERE/.env}"
  # shellcheck disable=SC1090
  if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; fi
  local STATE="${STATE_DIR:-$HERE/.state}" compose_file="${COMPOSE_FILE:-$HERE/generated/docker-compose.yml}"
  local projects="${PROJECTS_DIR:-$HERE/../../projects}"
  local min_free="${MAINT_MIN_FREE_GB:-10}" max_age="${MAINT_BACKUP_MAX_HOURS:-36}"
  mkdir -p "$STATE"
  local -a actions=() images_json=() notes=()

  # compose command, written the way you'd type it from deploy/selfhost
  local cc="docker compose -f generated/docker-compose.yml --env-file .env"
  local -a COMPOSE=(docker compose -f "$compose_file" --env-file "$ENV_FILE")
  if [ -f "$HERE/docker-compose.override.yml" ]; then
    cc+=" -f docker-compose.override.yml"; COMPOSE+=(-f "$HERE/docker-compose.override.yml")
  fi
  if [ -n "${TUNNEL_TOKEN:-}" ]; then cc+=" --profile tunnel"; COMPOSE+=(--profile tunnel); fi

  # OS
  local apt_up="" apt_sec="" reboot=false
  local -a reboot_pkgs=()
  if command -v apt >/dev/null; then
    local up; up="$(apt list --upgradable 2>/dev/null | grep 'upgradable from' || true)"
    apt_up="$(grep -c . <<< "$up" || true)"
    apt_sec="$(grep -c -- '-security' <<< "$up" || true)"
  fi
  if [ -f /var/run/reboot-required ]; then
    reboot=true
    [ -f /var/run/reboot-required.pkgs ] && mapfile -t reboot_pkgs < <(sort -u /var/run/reboot-required.pkgs | grep . || true)
  fi
  if [ -n "$apt_up" ] && [ "$apt_up" -gt 0 ]; then
    if [ "$reboot" = true ] || [ "$apt_sec" -gt 0 ]; then actions+=("sudo apt update && sudo apt upgrade -y && sudo reboot")
    else actions+=("sudo apt update && sudo apt upgrade -y"); fi
  elif [ "$reboot" = true ]; then
    actions+=("sudo reboot   # needed by: ${reboot_pkgs[*]:-pending updates}")
  fi

  # Docker
  local docker_version="" have_docker=0
  if docker_version="$(docker version --format '{{.Server.Version}}' 2>/dev/null)"; then have_docker=1; else docker_version=""; fi

  # images
  local svc ref upd
  local -a stale_svcs=() stale_bases=()
  if [ "$have_docker" = 1 ] && [ -f "$compose_file" ]; then
    while IFS=$'\t' read -r svc ref; do
      [ -n "$ref" ] || continue
      ref="$(resolve_ref "$ref")"
      upd="$(update_available "$ref")"
      images_json+=("{\"image\": $(json_str "$ref"), \"update_available\": $(num_or_null "$upd")}")
      [ "$upd" = true ] && stale_svcs+=("$svc")
      echo "image $ref ($svc): update_available=${upd:-unknown}"
    done < <(compose_images "$compose_file")
  elif [ ! -f "$compose_file" ]; then notes+=("no $compose_file yet (run update.sh)"); fi
  local -a dockerfiles=()
  mapfile -t dockerfiles < <(find "$projects" -mindepth 2 -maxdepth 2 -name Dockerfile.space 2>/dev/null | sort)
  if [ "$have_docker" = 1 ] && [ "${#dockerfiles[@]}" -gt 0 ]; then
    while IFS= read -r ref; do
      [ -n "$ref" ] || continue
      upd="$(update_available "$ref")"
      images_json+=("{\"image\": $(json_str "$ref"), \"update_available\": $(num_or_null "$upd")}")
      [ "$upd" = true ] && stale_bases+=("$ref")
      echo "base image $ref: update_available=${upd:-unknown}"
    done < <(dockerfile_bases "${dockerfiles[@]}")
  fi
  if [ "${#stale_svcs[@]}" -gt 0 ]; then
    actions+=("cd $HERE && $cc pull ${stale_svcs[*]} && $cc up -d ${stale_svcs[*]}")
  fi
  if [ "${#stale_bases[@]}" -gt 0 ]; then
    local pulls="" b
    for b in "${stale_bases[@]}"; do pulls+="docker pull $b && "; done
    actions+=("${pulls}$HERE/update.sh --force   # rebuilds the apps on the new base images")
  fi

  # Ollama
  local ollama_version=""
  if [ "$have_docker" = 1 ] && [ -f "$compose_file" ]; then
    ollama_version="$(timeout 60 "${COMPOSE[@]}" exec -T ollama ollama --version 2>/dev/null |
                      grep -oE '[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9.+-]*' | tail -1 || true)"
  fi
  echo "ollama ${ollama_version:-not running}, model ${OLLAMA_MODEL:-unset}; docker ${docker_version:-unavailable}"

  # disk
  local free_root="" free_docker="" disk_free="" droot
  free_root="$(df -P -B1 / 2>/dev/null | awk 'NR==2 { printf "%.1f", $4 / 1e9 }')" || free_root=""
  if [ "$have_docker" = 1 ]; then
    droot="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)"
    [ -n "$droot" ] && free_docker="$(df -P -B1 "$droot" 2>/dev/null | awk 'NR==2 { printf "%.1f", $4 / 1e9 }' || true)"
  fi
  disk_free="$(printf '%s\n' "$free_root" "$free_docker" | grep . | sort -g | head -1 || true)"
  echo "disk free: / ${free_root:-?} GB, docker root ${droot:-?} ${free_docker:-?} GB"
  if [ -n "$disk_free" ] && awk -v f="$disk_free" -v m="$min_free" 'BEGIN { exit !(f < m) }'; then
    actions+=("docker image prune -f && docker builder prune -f   # only ${disk_free} GB free; volumes are not touched")
  fi

  # backups
  local last_ts age=""
  last_ts="$(last_good_backup_ts "$STATE")"
  [ -n "$last_ts" ] && age="$(hours_since "$last_ts")"
  if [ -z "$age" ]; then
    actions+=("$HERE/backup.sh   # no successful backup recorded; also enable ai-portfolio-backup.timer (see backup.sh header)")
  elif awk -v a="$age" -v m="$max_age" 'BEGIN { exit !(a > m) }'; then
    actions+=("$HERE/backup.sh   # last good backup ${age} h ago — check: journalctl -u ai-portfolio-backup; cat $STATE/backup.json")
  fi
  if [ -n "$age" ]; then echo "last good backup: $age h ago"; else echo "last good backup: none recorded"; fi

  # host scripts: the timers run root-owned copies in /usr/local/lib/ai-portfolio, so a push can't change what
  # runs on this machine. When the repo's copies change, the owner reviews them and re-installs.
  local lib=/usr/local/lib/ai-portfolio f drift=()
  if [ -d "$lib" ]; then
    for f in update.sh hostmon.sh backup.sh restore.sh maintenance.sh deploy-guard.py; do
      [ -f "$HERE/$f" ] && ! cmp -s "$HERE/$f" "$lib/$f" && drift+=("$f")
    done
    [ -f "$HERE/../../security/pentest.py" ] && ! cmp -s "$HERE/../../security/pentest.py" "$lib/pentest.py" && drift+=("pentest.py")
    [ "${#drift[@]}" -gt 0 ] && actions+=("git -C $HERE/../.. log -p -5 -- deploy/selfhost security/pentest.py   # review the change to ${drift[*]}, then: sudo $HERE/install.sh")
  else
    actions+=("sudo $HERE/install.sh   # installs the root-owned host scripts, deploy guard and timers")
  fi

  local ok=true; [ "${#actions[@]}" -eq 0 ] || ok=false
  local imgs="" sep="" j
  for j in "${images_json[@]}"; do imgs+="$sep$j"; sep=", "; done
  local json
  json="$(printf '{"ts": %s, "apt_upgradable": %s, "apt_security": %s, "reboot_required": %s, "reboot_pkgs": %s, "images": [%s], "ollama_version": %s, "docker_version": %s, "disk_free_gb": %s, "backup_age_hours": %s, "actions": %s, "ok": %s}' \
    "$(json_str "$(date -u +%Y-%m-%dT%H:%M:%SZ)")" "$(num_or_null "$apt_up")" "$(num_or_null "$apt_sec")" "$reboot" \
    "$(json_array "${reboot_pkgs[@]}")" "$imgs" "$(json_or_null "$ollama_version")" "$(json_or_null "$docker_version")" \
    "$(num_or_null "$disk_free")" "$(num_or_null "$age")" "$(json_array "${actions[@]}")" "$ok")"
  printf '%s\n' "$json" > "$STATE/maintenance.json.tmp" && mv "$STATE/maintenance.json.tmp" "$STATE/maintenance.json"

  local n
  for n in "${notes[@]}"; do echo "note: $n"; done
  if [ "$ok" = true ]; then echo "Nothing to do."; else
    echo "To do (run these yourself):"; for n in "${actions[@]}"; do echo "  $n"; done
  fi
  echo "wrote $STATE/maintenance.json"
  [ "$print_json" = 1 ] && printf '%s\n' "$json"
  return 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then maintenance_main "$@"; fi
