#!/usr/bin/env bash
# Nightly backup of everything Git doesn't hold for the self-hosted demos:
#   - every named Docker volume of the compose project (except ollama-models, which re-downloads):
#       SQLite files -> online-safe copy (sqlite3 backup API, volume mounted read-only in a throwaway python
#                       container), then PRAGMA integrity_check on the copy;
#       other files  -> volumes/<volume>.files.tar.gz
#   - deploy/selfhost/.env and docker-compose.override.yml, encrypted with BACKUP_PASSPHRASE
#     (openssl aes-256-cbc + pbkdf2). Without a passphrase they are skipped: secrets never land in clear.
#   - optional off-site copy with rclone (rclone/rclone image) when BACKUP_RCLONE_REMOTE is set.
# Layout: ${BACKUP_DIR:-$HOME/ai-portfolio-backups}/YYYY-MM-DD/
#           volumes/<volume>/<path>.sqlite   volumes/<volume>.files.tar.gz   env.enc
#           docker-compose.override.yml.enc   SHA256SUMS   manifest.json
# A rerun on the same day replaces that day's backup (only if the new one passes its integrity checks).
# Retention: the newest BACKUP_KEEP_DAILY (14) backups plus the newest BACKUP_KEEP_WEEKLY (8) Sunday backups.
# Status for the console/maintenance check: deploy/selfhost/.state/backup.json (always written, even on failure).
#
#   deploy/selfhost/backup.sh            # run a backup now
#   deploy/selfhost/backup.sh --status   # print the last status JSON
#   deploy/selfhost/restore.sh --help    # getting data back
#
# Settings (in deploy/selfhost/.env, sourced like update.sh does, or in the environment):
#   BACKUP_DIR=~/ai-portfolio-backups   BACKUP_KEEP_DAILY=14   BACKUP_KEEP_WEEKLY=8
#   BACKUP_PASSPHRASE=<long random string; keep a copy OUTSIDE this machine, e.g. a password manager>
#   BACKUP_RCLONE_REMOTE=r2:ai-portfolio-backups   (remote configured once with:
#     docker run --rm -it -v ~/.config/rclone:/config/rclone rclone/rclone config)
# Overrides for testing: PROJECT (compose project, default ai-portfolio-demos), ENV_FILE, STATE_DIR, PY_IMAGE,
#   RCLONE_IMAGE, RCLONE_CONFIG_DIR, BACKUP_EXCLUDE_VOLUMES (space-separated, default "ollama-models").
# Needs: Docker, openssl (only with BACKUP_PASSPHRASE), sha256sum, GNU date. No Python on the host.
#
# systemd (Linux) — /etc/systemd/system/ai-portfolio-backup.service  (replace USER and the path):
# ---------------------------------------------------------------------------------------------
# [Unit]
# Description=Back up AI portfolio demo data (Docker volumes, encrypted .env)
# After=docker.service network-online.target
# Wants=network-online.target
# Requires=docker.service
#
# [Service]
# Type=oneshot
# User=USER
# ExecStart=/home/USER/ai-portfolio/deploy/selfhost/backup.sh
# Nice=10
# IOSchedulingClass=idle
# TimeoutStartSec=2h
# ---------------------------------------------------------------------------------------------
# /etc/systemd/system/ai-portfolio-backup.timer:
# ---------------------------------------------------------------------------------------------
# [Unit]
# Description=Nightly backup of AI portfolio demo data (03:15 + up to 15 min)
#
# [Timer]
# OnCalendar=*-*-* 03:15:00
# RandomizedDelaySec=15min
# Persistent=true
#
# [Install]
# WantedBy=timers.target
# ---------------------------------------------------------------------------------------------
# Enable: sudo systemctl daemon-reload && sudo systemctl enable --now ai-portfolio-backup.timer
# Logs:   journalctl -u ai-portfolio-backup     Next run: systemctl list-timers ai-portfolio-backup
set -euo pipefail

# Installed copies (/usr/local/lib/ai-portfolio, root-owned) are told where the deploy clone is.
if [ -n "${AI_PORTFOLIO_REPO:-}" ]; then HERE="$AI_PORTFOLIO_REPO/deploy/selfhost"; else HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; fi

# ---------------------------------------------------------------- pure helpers (sourced by tests) ----

# JSON string literal (escapes backslash, quote and control characters).
json_str() {
  local s="${1-}"
  s="${s//\\/\\\\}"; s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"; s="${s//$'\r'/\\r}"; s="${s//$'\t'/\\t}"
  s="$(printf '%s' "$s" | tr -d '\000-\010\013\014\016-\037')"
  printf '"%s"' "$s"
}

json_bool() { if [ "${1:-}" = true ]; then printf true; else printf false; fi; }

# files_json: stdin lines "name<TAB>bytes<TAB>sha256" -> [{"name":…,"bytes":…,"sha256":…}, …]
files_json() {
  local name bytes sha sep="" out="["
  while IFS=$'\t' read -r name bytes sha; do
    [ -n "$name" ] || continue
    out+="$sep{\"name\": $(json_str "$name"), \"bytes\": ${bytes:-0}, \"sha256\": $(json_str "$sha")}"
    sep=", "
  done
  printf '%s]' "$out"
}

# status_json ts ok dir files_json integrity offsite encrypted_env error  -> the .state/backup.json document
status_json() {
  printf '{"ts": %s, "ok": %s, "dir": %s, "files": %s, "integrity": %s, "offsite": %s, "encrypted_env": %s, "error": %s}\n' \
    "$(json_str "$1")" "$(json_bool "$2")" "$(json_str "$3")" "${4:-[]}" "$(json_str "$5")" \
    "$(json_str "$6")" "$(json_bool "$7")" "$(json_str "$8")"
}

# retention_prune_list KEEP_DAILY KEEP_WEEKLY < dates  -> prints the dates (YYYY-MM-DD) to delete.
# Keeps the newest KEEP_DAILY backups and the newest KEEP_WEEKLY backups taken on a Sunday.
retention_prune_list() {
  local keep_daily="$1" keep_weekly="$2" d dow i=0 w=0 keep
  local -a dates=()
  mapfile -t dates < <(grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' | sort -r -u || true)
  for d in "${dates[@]}"; do
    keep=0
    [ "$i" -lt "$keep_daily" ] && keep=1
    dow="$(date -u -d "$d" +%u 2>/dev/null || echo 0)"
    if [ "$dow" = 7 ] && [ "$w" -lt "$keep_weekly" ]; then keep=1; w=$((w + 1)); fi
    i=$((i + 1))
    [ "$keep" = 1 ] || printf '%s\n' "$d"
  done
}

# integrity_summary: stdin lines "label<TAB>result" -> "ok" or "failed: label: result; …"
integrity_summary() {
  local label res bad=""
  while IFS=$'\t' read -r label res; do
    [ -n "$label" ] || continue
    [ "$res" = ok ] || bad+="${bad:+; }$label: $res"
  done
  if [ -z "$bad" ]; then printf ok; else printf 'failed: %s' "$bad"; fi
}

# Runs inside the python container. argv: src dst tarpath uid gid. Prints TSV:
#   sqlite<TAB>relpath<TAB>integrity     tar<TAB>tarname<TAB>member-count
VOLUME_BACKUP_PY='
import os, sys, sqlite3, tarfile
from urllib.parse import quote
src, dst, tarpath, uid, gid = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
def is_sqlite(p):
    try:
        with open(p, "rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False
dbs, other = [], []
for root, dirs, files in os.walk(src):
    dirs.sort()
    for n in sorted(files):
        p = os.path.join(root, n); rel = os.path.relpath(p, src)
        (dbs if (not os.path.islink(p) and os.path.isfile(p) and is_sqlite(p)) else other).append(rel)
side = {d + s for d in dbs for s in ("-wal", "-shm", "-journal")}
other = [r for r in other if r not in side]
def clean(s):
    return " ".join(str(s).split())
for rel in dbs:
    out = os.path.join(dst, rel); os.makedirs(os.path.dirname(out), exist_ok=True)
    path = os.path.join(src, rel)
    try:
        try:   # online-safe: shares the live app lock/WAL index (works on a read-only mount)
            s = sqlite3.connect("file:" + quote(path) + "?mode=ro", uri=True, timeout=60)
            s.execute("select count(*) from sqlite_master").fetchone()
        except sqlite3.OperationalError:
            # a cleanly closed WAL db on a read-only mount cannot be opened normally; with no -wal file
            # there is no live writer and nothing pending, so reading it as immutable is exact
            wal = path + "-wal"
            if os.path.exists(wal) and os.path.getsize(wal) > 0:
                raise
            s = sqlite3.connect("file:" + quote(path) + "?mode=ro&immutable=1", uri=True)
        d = sqlite3.connect(out)
        with d:
            s.backup(d)
        d.close(); s.close()
        c = sqlite3.connect(out)
        rows = [r[0] for r in c.execute("pragma integrity_check").fetchall()]
        c.close()
        res = "ok" if rows == ["ok"] else clean("; ".join(rows[:5]))
    except Exception as e:
        res = clean("error: %s" % e)
    for s in ("-wal", "-shm"):
        if os.path.exists(out + s):
            os.remove(out + s)
    print("sqlite\t%s\t%s" % (rel, res), flush=True)
if other:
    os.makedirs(os.path.dirname(tarpath), exist_ok=True)
    with tarfile.open(tarpath, "w:gz") as t:
        for rel in other:
            t.add(os.path.join(src, rel), arcname=rel, recursive=False)
    print("tar\t%s\t%d" % (os.path.basename(tarpath), len(other)), flush=True)
for root, dirs, files in os.walk(os.path.dirname(tarpath)):
    for n in dirs + files:
        os.lchown(os.path.join(root, n), uid, gid)
os.lchown(os.path.dirname(tarpath), uid, gid)
'

# ----------------------------------------------------------------------------------------- main ----

log() { echo "$(date -Is) $*"; }

backup_main() {
  if [ "${1:-}" = "--status" ]; then cat "${STATE_DIR:-$HERE/.state}/backup.json"; return; fi
  case "${1:-}" in
    "") ;;
    -h|--help) sed -n '2,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; return 2 ;;
  esac

  ENV_FILE="${ENV_FILE:-$HERE/.env}"
  STATE="${STATE_DIR:-$HERE/.state}"
  mkdir -p "$STATE"

  # status, filled in as we go and written on any exit (also when .env itself can't be read)
  TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; DAY="$(date +%F)"
  FINAL_DIR=""; FILES_JSON="[]"; INTEGRITY="not run"; OFFSITE="skipped"; ENCRYPTED_ENV=false; ERROR=""
  WORK=""; ERR_AT=""; SOURCING=0
  trap 'ERR_AT="line $LINENO: $BASH_COMMAND"' ERR
  trap 'backup_finish $?' EXIT

  if [ -f "$ENV_FILE" ]; then
    SOURCING=1; set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a; SOURCING=0
  fi
  PROJECT="${PROJECT:-ai-portfolio-demos}"
  BACKUP_DIR="${BACKUP_DIR:-$HOME/ai-portfolio-backups}"
  KEEP_DAILY="${BACKUP_KEEP_DAILY:-14}"; KEEP_WEEKLY="${BACKUP_KEEP_WEEKLY:-8}"
  [ "$KEEP_DAILY" -ge 1 ] 2>/dev/null || KEEP_DAILY=1
  [ "$KEEP_WEEKLY" -ge 0 ] 2>/dev/null || KEEP_WEEKLY=0
  PY_IMAGE="${PY_IMAGE:-python:3.11-slim}"
  RCLONE_IMAGE="${RCLONE_IMAGE:-rclone/rclone:latest}"
  RCLONE_CONFIG_DIR="${RCLONE_CONFIG_DIR:-$HOME/.config/rclone}"
  EXCLUDE="${BACKUP_EXCLUDE_VOLUMES:-ollama-models}"
  umask 077
  mkdir -p "$BACKUP_DIR"

  exec 8>"$STATE/backup.lock"
  if command -v flock >/dev/null && ! flock -n 8; then ERROR="another backup is running"; exit 1; fi

  rm -rf "$BACKUP_DIR"/.tmp-* 2>/dev/null || true
  WORK="$BACKUP_DIR/.tmp-$DAY-$$"; mkdir -p "$WORK/volumes"
  local notes=() vol short svc_list integ_lines="" volumes_json="" sep=""

  # 1. volumes
  local -a vols=()
  mapfile -t vols < <(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT" | sort)
  if [ "${#vols[@]}" -eq 0 ]; then
    ERROR="no Docker volumes found for compose project $PROJECT (is the stack up? docker volume ls)"; exit 1
  fi
  for vol in "${vols[@]}"; do
    short="$(docker volume inspect -f '{{index .Labels "com.docker.compose.volume"}}' "$vol")"
    [ -n "$short" ] || short="${vol#"${PROJECT}"_}"
    if [[ " $EXCLUDE " == *" $short "* ]]; then log "skip $vol (excluded)"; continue; fi
    svc_list="$(docker ps -a --filter "volume=$vol" --filter "label=com.docker.compose.project=$PROJECT" \
                --format '{{.Label "com.docker.compose.service"}}' | sort -u | paste -sd, -)"
    log "backing up volume $vol${svc_list:+ (used by $svc_list)}"
    local out kind name res dbs_json="" dsep="" tar_json=null
    out="$(docker run --rm --network none -v "$vol:/src:ro" -v "$WORK/volumes:/dst" "$PY_IMAGE" \
             python -c "$VOLUME_BACKUP_PY" /src "/dst/$short" "/dst/$short.files.tar.gz" "$(id -u)" "$(id -g)")" \
      || { ERROR="backup container failed for volume $vol"; exit 1; }
    while IFS=$'\t' read -r kind name res; do
      case "$kind" in
        sqlite) integ_lines+="$short/$name"$'\t'"$res"$'\n'
                dbs_json+="$dsep{\"name\": $(json_str "volumes/$short/$name"), \"integrity\": $(json_str "$res")}"; dsep=", " ;;
        tar)    tar_json="$(json_str "volumes/$name")" ;;
      esac
    done <<< "$out"
    volumes_json+="$sep{\"volume\": $(json_str "$vol"), \"name\": $(json_str "$short"), \"services\": $(json_str "$svc_list"), \"sqlite\": [${dbs_json}], \"tar\": $tar_json}"
    sep=", "
  done
  INTEGRITY="$(printf '%s' "$integ_lines" | integrity_summary)"

  # 2. secrets, encrypted or not at all
  if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
    export BACKUP_PASSPHRASE
    command -v openssl >/dev/null || { ERROR="BACKUP_PASSPHRASE is set but openssl is missing (sudo apt install openssl)"; exit 1; }
    local f
    for f in "$ENV_FILE" "$HERE/docker-compose.override.yml"; do
      [ -f "$f" ] || continue
      local enc="env.enc"; [ "$f" = "$ENV_FILE" ] || enc="$(basename "$f").enc"
      openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE -in "$f" -out "$WORK/$enc"
      [ "$enc" = env.enc ] && ENCRYPTED_ENV=true
    done
    [ "$ENCRYPTED_ENV" = true ] || notes+=("no .env at $ENV_FILE to back up")
  else
    notes+=("BACKUP_PASSPHRASE not set: .env and docker-compose.override.yml NOT backed up (never stored in clear)")
    log "note: ${notes[-1]}"
  fi

  # 3. checksums + manifest
  local list
  list="$(cd "$WORK" && find . -type f ! -name manifest.json ! -name SHA256SUMS -printf '%P\n' | LC_ALL=C sort |
          while IFS= read -r f; do printf '%s\t%s\t%s\n' "$f" "$(stat -c %s "$f")" "$(sha256sum "$f" | cut -d' ' -f1)"; done)"
  printf '%s\n' "$list" | awk -F'\t' 'NF==3{print $3"  "$1}' > "$WORK/SHA256SUMS"
  FILES_JSON="$(printf '%s\n' "$list" | files_json)"
  local notes_json="" n nsep=""
  for n in "${notes[@]}"; do notes_json+="$nsep$(json_str "$n")"; nsep=", "; done
  printf '{"ts": %s, "project": %s, "host": %s, "files": %s, "volumes": [%s], "integrity": %s, "encrypted_env": %s, "notes": [%s]}\n' \
    "$(json_str "$TS")" "$(json_str "$PROJECT")" "$(json_str "$(hostname)")" "$FILES_JSON" "$volumes_json" \
    "$(json_str "$INTEGRITY")" "$(json_bool "$ENCRYPTED_ENV")" "$notes_json" > "$WORK/manifest.json"

  # 4. publish the day's directory (a bad copy never replaces a good one from the same day)
  if [ "$INTEGRITY" = ok ]; then
    FINAL_DIR="$BACKUP_DIR/$DAY"
    rm -rf "$FINAL_DIR.old"; [ -d "$FINAL_DIR" ] && mv "$FINAL_DIR" "$FINAL_DIR.old"
    mv "$WORK" "$FINAL_DIR"; rm -rf "$FINAL_DIR.old"; WORK=""
  else
    FINAL_DIR="$BACKUP_DIR/$DAY.failed-$(date +%H%M%S)"; mv "$WORK" "$FINAL_DIR"; WORK=""
    ERROR="integrity check failed; kept for inspection in $FINAL_DIR, older backups not pruned"
    exit 1
  fi
  log "wrote $FINAL_DIR ($(du -sh "$FINAL_DIR" | cut -f1))"

  # 5. retention
  local -a pruned=()
  mapfile -t pruned < <(find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' |
                         retention_prune_list "$KEEP_DAILY" "$KEEP_WEEKLY")
  local d
  for d in "${pruned[@]}"; do
    if [ -n "$d" ]; then log "prune $d"; rm -rf "${BACKUP_DIR:?}/$d"; fi
  done
  local cutoff; cutoff="$(date -d "-$KEEP_DAILY days" +%F)"
  find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '????-??-??.failed-*' -printf '%f\n' |
    while IFS= read -r d; do
      if [[ "${d%%.*}" < "$cutoff" ]]; then rm -rf "${BACKUP_DIR:?}/$d"; fi
    done

  # 6. off-site
  if [ -n "${BACKUP_RCLONE_REMOTE:-}" ]; then
    local remote="${BACKUP_RCLONE_REMOTE%/}"
    if [ ! -d "$RCLONE_CONFIG_DIR" ]; then
      OFFSITE="failed: no rclone config in $RCLONE_CONFIG_DIR"
    elif docker run --rm -v "$RCLONE_CONFIG_DIR:/config/rclone:ro" -v "$BACKUP_DIR:/data:ro" "$RCLONE_IMAGE" \
           copy "/data/$DAY" "$remote/$DAY" --retries 3 >"$STATE/backup-rclone.log" 2>&1; then
      OFFSITE=ok
      for d in "${pruned[@]}"; do
        if [ -n "$d" ]; then
          docker run --rm -v "$RCLONE_CONFIG_DIR:/config/rclone:ro" "$RCLONE_IMAGE" \
            purge "$remote/$d" >>"$STATE/backup-rclone.log" 2>&1 || log "warning: could not prune $remote/$d"
        fi
      done
    else
      OFFSITE="failed: rclone copy to $remote (see $STATE/backup-rclone.log): $(tail -n 1 "$STATE/backup-rclone.log" | cut -c1-200)"
    fi
    if [ "$OFFSITE" != ok ]; then ERROR="off-site copy failed; the local backup in $FINAL_DIR is fine"; exit 1; fi
    log "off-site copy: $remote/$DAY"
  fi
}

backup_finish() {
  local rc="$1" ok=false
  trap - ERR EXIT
  [ -n "$WORK" ] && rm -rf "$WORK"
  if [ "$SOURCING" = 1 ]; then   # never echo the failing line: it may hold a secret
    ERROR="could not read $ENV_FILE as shell variables (quote values with spaces, like update.sh expects)"
  elif [ "$rc" -ne 0 ] && [ -z "$ERROR" ]; then
    ERROR="backup.sh failed (exit $rc)${ERR_AT:+ at ${ERR_AT:0:200}}"
  fi
  [ "$rc" -eq 0 ] && [ -z "$ERROR" ] && [ "$INTEGRITY" = ok ] && ok=true
  status_json "$TS" "$ok" "$FINAL_DIR" "$FILES_JSON" "$INTEGRITY" "$OFFSITE" "$ENCRYPTED_ENV" "$ERROR" > "$STATE/backup.json.tmp"
  mv "$STATE/backup.json.tmp" "$STATE/backup.json"
  if [ "$ok" = true ]; then
    printf '%s\n' "$TS" > "$STATE/backup_last_ok"
    log "backup ok: $FINAL_DIR (integrity $INTEGRITY, off-site $OFFSITE)"
    exit 0
  fi
  log "BACKUP FAILED: $ERROR"
  exit "$([ "$rc" -ne 0 ] && echo "$rc" || echo 1)"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then backup_main "$@"; fi
