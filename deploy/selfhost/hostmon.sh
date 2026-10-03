#!/usr/bin/env bash
# Host monitor for the self-host box (EVO-X1). Runs ON THE HOST every minute from a systemd timer and posts one JSON
# sample to the governance console's Host tab, through the local Caddy:
#   POST http://127.0.0.1:${DEMOS_PORT:-8088}/governance-console/api/host
#   Authorization: Bearer $GOVERNANCE_INGEST_TOKEN          (both read from deploy/selfhost/.env, like update.sh)
#
# What it collects (no Python on the host: /proc, df, the docker CLI and awk; jq is used only if it's installed):
#   host        cpu_pct (two /proc/stat samples 1 s apart), load1/5/15, cpu_count, mem_total_gb, mem_used_pct,
#               swap_used_pct, disks [{mount, used_pct, free_gb}] for / and Docker's data root, temp_c (hottest
#               thermal_zone / hwmon sensor, null if none), uptime_s, hostname
#   containers  compose project ai-portfolio-demos: name, service, state, health, restarts, cpu_pct, mem_mb, mem_limit_mb
#   backup · maintenance · pentest    .state/backup.json, .state/maintenance.json, .state/pentest.json passed
#               through as-is when present (pentest may carry a long "report_md")
#   deploy      the contents of .state/deployed and .state/failed (written by update.sh)
#
# Cheap (well under 1 s of CPU; ~2 s wall clock, mostly `docker stats` and the 1 s CPU sample) and quiet: it always
# exits 0 and logs problems to stderr (the journal). Try it by hand:  deploy/selfhost/hostmon.sh --print
#
# Install (as root; replace YOU with the user that runs update.sh — it needs to be in the docker group):
#
# /etc/systemd/system/ai-portfolio-hostmon.service
#   [Unit]
#   Description=AI portfolio host monitor (one sample to the governance console)
#   After=docker.service network-online.target
#   [Service]
#   Type=oneshot
#   User=YOU
#   ExecStart=/path/to/ai-portfolio/deploy/selfhost/hostmon.sh
#   Nice=10
#
# /etc/systemd/system/ai-portfolio-hostmon.timer
#   [Unit]
#   Description=Run the AI portfolio host monitor every minute
#   [Timer]
#   OnBootSec=1min
#   OnUnitActiveSec=1min
#   AccuracySec=5s
#   [Install]
#   WantedBy=timers.target
#
#   sudo systemctl daemon-reload && sudo systemctl enable --now ai-portfolio-hostmon.timer
#   journalctl -u ai-portfolio-hostmon -n 20        # what it logged
set -u
# Installed copies (/usr/local/lib/ai-portfolio, root-owned) are told where the deploy clone is.
if [ -n "${AI_PORTFOLIO_REPO:-}" ]; then HERE="$AI_PORTFOLIO_REPO/deploy/selfhost"; else HERE="$(cd "$(dirname "$0")" && pwd)"; fi
STATE="$HERE/.state"
PROJECT="ai-portfolio-demos"
MAX_BYTES=390000                     # the console accepts up to 400 KB per sample
log() { echo "hostmon: $*" >&2; }
TMP="$(mktemp)" || exit 0
trap 'rm -f "$TMP" "$TMP.out"; exit 0' EXIT          # whatever happens: clean up, exit 0
[ -f "$HERE/.env" ] && { set -a; . "$HERE/.env" 2>/dev/null; set +a; }
URL="http://127.0.0.1:${DEMOS_PORT:-8088}/governance-console/api/host"
HAVE_JQ=0; command -v jq >/dev/null 2>&1 && HAVE_JQ=1
HAVE_DOCKER=0; command -v docker >/dev/null 2>&1 && HAVE_DOCKER=1

# ---------------------------------------------------------------- JSON helpers
jstr() {   # a JSON string literal (quotes, backslashes and control characters escaped)
  local s="${1-}"
  s="${s//\\/\\\\}"; s="${s//\"/\\\"}"; s="${s//$'\n'/\\n}"; s="${s//$'\r'/\\r}"; s="${s//$'\t'/\\t}"
  s="$(printf '%s' "$s" | tr -d '\000-\010\013\014\016-\037')"
  printf '"%s"' "$s"
}
jnum() {   # a JSON number, or null
  if [[ "${1-}" =~ ^-?[0-9]+(\.[0-9]+)?$ ]]; then printf '%s' "$1"; else printf 'null'; fi
}
jdoc() {   # a status file's JSON passed through, or null (validated with jq when available)
  local f="$1"
  [ -s "$f" ] || { printf 'null'; return; }
  if [ "$HAVE_JQ" = 1 ]; then
    jq -c . "$f" 2>/dev/null || { log "ignoring invalid JSON in $f"; printf 'null'; }
  else
    local first; first="$(head -c 200 "$f" | tr -d ' \t\r\n' | head -c 1)"
    if [ "$first" = "{" ]; then cat "$f"; else log "ignoring $f (not a JSON object)"; printf 'null'; fi
  fi
}

# ---------------------------------------------------------------- host
read -r _ u1 n1 s1 i1 w1 x1 y1 z1 _ < /proc/stat
sleep 1
read -r _ u2 n2 s2 i2 w2 x2 y2 z2 _ < /proc/stat
CPU_PCT="$(awk -v a="$((u1+n1+s1+i1+w1+x1+y1+z1))" -v b="$((u2+n2+s2+i2+w2+x2+y2+z2))" -v ia="$((i1+w1))" -v ib="$((i2+w2))" \
  'BEGIN { t = b - a; if (t <= 0) print "null"; else printf "%.1f", 100 * (t - (ib - ia)) / t }')"
read -r L1 L5 L15 _ < /proc/loadavg
CPUS="$(nproc 2>/dev/null || grep -c ^processor /proc/cpuinfo)"
MEM="$(awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} /^SwapTotal:/{st=$2} /^SwapFree:/{sf=$2}
  END { printf "%.1f %.1f %s", t/1048576, (t>0 ? 100*(t-a)/t : 0), (st>0 ? sprintf("%.1f", 100*(st-sf)/st) : "0") }' /proc/meminfo)"
read -r MEM_TOTAL MEM_USED SWAP_USED <<< "$MEM"
UPTIME="$(awk '{printf "%d", $1}' /proc/uptime)"
HOSTNAME_="$(cat /proc/sys/kernel/hostname 2>/dev/null || hostname)"

TEMP="$(cat /sys/class/thermal/thermal_zone*/temp /sys/class/hwmon/hwmon*/temp*_input 2>/dev/null |
  awk '$1 ~ /^-?[0-9]+$/ { c = $1 / 1000; if (c > 0 && c < 150 && (m == "" || c > m)) m = c } END { if (m == "") print "null"; else printf "%.1f", m }')"

disk() {   # {"mount","used_pct","free_gb"} for the filesystem holding $1 (used% as df computes it: used / (used + avail))
  local nums
  nums="$(df -P -k "$1" 2>/dev/null | awk 'NR == 2 { u = $3; a = $4; t = u + a; printf "%.1f %.1f", (t > 0 ? 100 * u / t : 0), a / 1048576 }')"
  [ -n "$nums" ] || return 0
  printf '{"mount":%s,"used_pct":%s,"free_gb":%s}' "$(jstr "$1")" "$(jnum "${nums% *}")" "$(jnum "${nums#* }")"
}
DISKS="$(disk /)"
DOCKER_ROOT=""
[ "$HAVE_DOCKER" = 1 ] && DOCKER_ROOT="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)"
if [ -n "$DOCKER_ROOT" ] && [ -d "$DOCKER_ROOT" ]; then
  d="$(disk "$DOCKER_ROOT")"; [ -n "$d" ] && DISKS="$DISKS${DISKS:+,}$d"
fi

# ---------------------------------------------------------------- containers
to_mb() {  # "312.4MiB" / "2GiB" / "1.5GB" / "900kB" → MB
  awk -v v="$1" 'BEGIN { n = v + 0; u = v; sub(/^[0-9.]+/, "", u);
    f["B"]=1/1048576; f["KiB"]=1/1024; f["MiB"]=1; f["GiB"]=1024; f["TiB"]=1048576;
    f["kB"]=1000/1048576; f["KB"]=1000/1048576; f["MB"]=1e6/1048576; f["GB"]=1e9/1048576; f["TB"]=1e12/1048576;
    if (u in f) printf "%.1f", n * f[u]; else print "null" }'
}
CONTAINERS=""
if [ "$HAVE_DOCKER" = 1 ]; then
  IDS="$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null || true)"
  if [ -n "$IDS" ]; then
    declare -A CPU MEMU MEML
    RUNNING="$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null || true)"
    if [ -n "$RUNNING" ]; then
      # same fields as `docker stats --format '{{json .}}'` (.Name, .CPUPerc, .MemUsage), as a delimited line: no jq needed
      while IFS='|' read -r name cpu mem; do
        CPU["$name"]="${cpu%\%}"
        MEMU["$name"]="$(to_mb "$(echo "${mem%%/*}" | tr -d ' ')")"
        MEML["$name"]="$(to_mb "$(echo "${mem##*/}" | tr -d ' ')")"
      done < <(docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}' $RUNNING 2>/dev/null)
    fi
    while IFS='|' read -r name service state health restarts; do
      name="${name#/}"
      CONTAINERS="$CONTAINERS${CONTAINERS:+,}{\"name\":$(jstr "$name"),\"service\":$(jstr "$service"),\"state\":$(jstr "$state"),\"health\":$(jstr "$health"),\"restarts\":$(jnum "$restarts"),\"cpu_pct\":$(jnum "${CPU[$name]:-}"),\"mem_mb\":$(jnum "${MEMU[$name]:-}"),\"mem_limit_mb\":$(jnum "${MEML[$name]:-}")}"
    done < <(docker inspect --format '{{.Name}}|{{index .Config.Labels "com.docker.compose.service"}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.RestartCount}}' $IDS 2>/dev/null)
  fi
else
  log "docker not found — sending host metrics only"
fi

# ---------------------------------------------------------------- status files + deploy
DEPLOYED="$(head -c 80 "$STATE/deployed" 2>/dev/null | tr -d '\n' || true)"
FAILED="$(head -c 80 "$STATE/failed" 2>/dev/null | tr -d '\n' || true)"
PENTEST_FILE="$STATE/pentest.json"

build() {  # $1: pentest JSON (or null)
  printf '{"v":1,"ts":%s,' "$(jstr "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
  printf '"host":{"hostname":%s,"cpu_pct":%s,"load1":%s,"load5":%s,"load15":%s,"cpu_count":%s,' \
    "$(jstr "$HOSTNAME_")" "$(jnum "$CPU_PCT")" "$(jnum "$L1")" "$(jnum "$L5")" "$(jnum "$L15")" "$(jnum "$CPUS")"
  printf '"mem_total_gb":%s,"mem_used_pct":%s,"swap_used_pct":%s,"uptime_s":%s,"temp_c":%s,"disks":[%s]},' \
    "$(jnum "$MEM_TOTAL")" "$(jnum "$MEM_USED")" "$(jnum "$SWAP_USED")" "$(jnum "$UPTIME")" "$(jnum "$TEMP")" "$DISKS"
  printf '"containers":[%s],"deploy":{"deployed":%s,"failed":%s},' "$CONTAINERS" "$(jstr "$DEPLOYED")" "$(jstr "$FAILED")"
  printf '"backup":%s,"maintenance":%s,"pentest":%s}' "$(jdoc "$STATE/backup.json")" "$(jdoc "$STATE/maintenance.json")" "$1"
}

build "$(jdoc "$PENTEST_FILE")" > "$TMP"
if [ "$(wc -c < "$TMP")" -gt "$MAX_BYTES" ]; then          # the pentest report is the only thing that can be big
  if [ "$HAVE_JQ" = 1 ]; then
    log "sample too large — truncating pentest.report_md"
    build "$(jq -c '.report_md |= (if type == "string" then .[0:200000] + "\n\n…(truncated by hostmon.sh)" else . end)' "$PENTEST_FILE" 2>/dev/null || echo null)" > "$TMP"
  fi
  if [ "$(wc -c < "$TMP")" -gt "$MAX_BYTES" ]; then
    log "sample too large — sending without the pentest result"
    build null > "$TMP"
  fi
fi

if [ "${1:-}" = "--print" ]; then
  if [ "$HAVE_JQ" = 1 ]; then jq . "$TMP" || cat "$TMP"; else cat "$TMP"; echo; fi
  exit 0
fi
[ -n "${GOVERNANCE_INGEST_TOKEN:-}" ] || log "GOVERNANCE_INGEST_TOKEN is not set in $HERE/.env — the console will refuse the sample if it requires one"
CODE="$(curl -sS -m 15 -o "$TMP.out" -w '%{http_code}' -X POST "$URL" -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${GOVERNANCE_INGEST_TOKEN:-}" --data-binary @"$TMP" 2>/dev/null)" || { log "console unreachable at $URL"; exit 0; }
[ "$CODE" = "202" ] || log "console answered HTTP $CODE: $(head -c 300 "$TMP.out" 2>/dev/null)"
exit 0
