#!/usr/bin/env bash
# Restore demo data from a backup made by backup.sh.
#
#   deploy/selfhost/restore.sh --list                               # backups on this machine
#   deploy/selfhost/restore.sh 2026-10-03 --dry-run                 # show what would happen, verify checksums
#   deploy/selfhost/restore.sh 2026-10-03                           # restore every volume in that backup
#   deploy/selfhost/restore.sh 2026-10-03 site-assistant-data       # just one volume (short or full name)
#   deploy/selfhost/restore.sh 2026-10-03 --with-env                # also decrypt .env -> .env.restored
#   deploy/selfhost/restore.sh 2026-10-03 --env-only                # only decrypt .env (no volumes touched)
#   deploy/selfhost/restore.sh /mnt/usb/2026-10-03 -y               # a backup copied from elsewhere, no prompt
#
# For each volume it: verifies the backup's sha256 (SHA256SUMS), stops the services using the volume
# (docker compose … stop <service>), moves the current SQLite files (+ -wal/-shm) aside to
# $BACKUP_DIR/pre-restore-<timestamp>/<volume>/, copies the backed-up files in (keeping the owner/mode the app
# expects), unpacks <volume>.files.tar.gz unless --db-only, and starts the services again — also if a step fails.
# A volume that no longer exists is created (with the compose labels), so this also rebuilds a new machine:
#   clone the repo, restore .env (--env-only, then review and rename .env.restored), ./update.sh --force,
#   then run this script for the volumes.
# .env is only ever decrypted to .env.restored (and the override to docker-compose.override.yml.restored);
# it never overwrites .env. The passphrase comes from BACKUP_PASSPHRASE (env or .env) or is asked for.
#
# Options: --dry-run  --with-env  --env-only  --db-only  -y|--yes  --list  -h|--help
# Overrides for testing: PROJECT (default ai-portfolio-demos), ENV_FILE, BACKUP_DIR, PY_IMAGE.
# Needs: Docker, sha256sum, openssl (for --with-env). No Python on the host.
#
# No timer: restores are manual. The nightly backup timer is documented at the top of backup.sh.
set -euo pipefail

# Installed copies (/usr/local/lib/ai-portfolio, root-owned) are told where the deploy clone is.
if [ -n "${AI_PORTFOLIO_REPO:-}" ]; then HERE="$AI_PORTFOLIO_REPO/deploy/selfhost"; else HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; fi

# Runs inside the python container. argv: backup_dir_for_volume tarpath volume_mount pre_dir with_files uid gid
RESTORE_PY='
import os, sys, shutil, sqlite3, tarfile
from urllib.parse import quote
bsrc, tarp, vol, pre, with_files, uid, gid = sys.argv[1:8]
uid, gid = int(uid), int(gid)
root = os.stat(vol)
def mkdirs(d, owner):
    if not os.path.isdir(d):
        mkdirs(os.path.dirname(d), owner); os.mkdir(d); os.chown(d, *owner)
def chown_tree(d):
    for r, ds, fs in os.walk(d):
        for n in ds + fs:
            os.lchown(os.path.join(r, n), uid, gid)
    if os.path.isdir(d):
        os.lchown(d, uid, gid)
if os.path.isdir(bsrc):
    for r, ds, fs in os.walk(bsrc):
        ds.sort()
        for n in sorted(fs):
            src = os.path.join(r, n); rel = os.path.relpath(src, bsrc); dst = os.path.join(vol, rel)
            if os.path.exists(dst):
                st = os.stat(dst); owner, mode = (st.st_uid, st.st_gid), st.st_mode & 0o7777
            else:
                owner, mode = (root.st_uid, root.st_gid), 0o644
            c = sqlite3.connect("file:" + quote(src) + "?mode=ro&immutable=1", uri=True)
            rows = [x[0] for x in c.execute("pragma integrity_check").fetchall()]; c.close()
            if rows != ["ok"]:
                print("failed\t%s\tintegrity: %s" % (rel, " ".join("; ".join(rows[:3]).split())), flush=True)
                sys.exit(3)
            mkdirs(os.path.dirname(dst), (root.st_uid, root.st_gid))
            for s in ("", "-wal", "-shm", "-journal"):
                if os.path.lexists(dst + s):   # never leave a stale WAL next to the restored db
                    keep = os.path.join(pre, rel + s); os.makedirs(os.path.dirname(keep), exist_ok=True)
                    shutil.move(dst + s, keep)
            tmp = dst + ".restoring"
            shutil.copyfile(src, tmp); os.chown(tmp, *owner); os.chmod(tmp, mode); os.replace(tmp, dst)
            print("restored\t%s\t%d bytes" % (rel, os.path.getsize(dst)), flush=True)
if with_files == "1" and tarp and os.path.isfile(tarp):
    with tarfile.open(tarp, "r:gz") as t:
        members = [m for m in t.getmembers()
                   if not (m.name.startswith("/") or ".." in m.name.split("/") or m.isdev())]
        kw = {"filter": "fully_trusted"} if hasattr(tarfile, "fully_trusted_filter") else {}
        t.extractall(vol, members=members, numeric_owner=True, **kw)
    print("files\t%s\t%d files" % (os.path.basename(tarp), len(members)), flush=True)
chown_tree(pre)
'

usage() { sed -n '2,27p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }
log() { echo "$(date -Is) $*"; }
die() { echo "restore: $*" >&2; exit 1; }

restore_main() {
  local dry=0 with_env=0 env_only=0 db_only=0 yes=0 list=0
  local -a pos=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) dry=1 ;; --with-env) with_env=1 ;; --env-only) env_only=1; with_env=1 ;;
      --db-only) db_only=1 ;; -y|--yes) yes=1 ;; --list) list=1 ;;
      -h|--help) usage; return 0 ;;
      -*) die "unknown option $1 (see --help)" ;;
      *) pos+=("$1") ;;
    esac
    shift
  done

  ENV_FILE="${ENV_FILE:-$HERE/.env}"
  # shellcheck disable=SC1090
  if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; fi
  PROJECT="${PROJECT:-ai-portfolio-demos}"
  BACKUP_DIR="${BACKUP_DIR:-$HOME/ai-portfolio-backups}"
  PY_IMAGE="${PY_IMAGE:-python:3.11-slim}"

  if [ "$list" = 1 ] || [ "${#pos[@]}" -eq 0 ]; then
    echo "Backups in $BACKUP_DIR:"
    find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '????-??-??*' -printf '  %f\n' 2>/dev/null | sort -r || true
    [ "$list" = 1 ] && return 0
    echo; echo "Usage: $0 <YYYY-MM-DD | path> [volume…] [--dry-run] [--with-env] [--db-only] [-y]   (--help for more)"
    return 2
  fi

  local src="${pos[0]}"; local -a want=("${pos[@]:1}")
  if [ -d "$src" ]; then src="$(cd "$src" && pwd)"
  elif [ -d "$BACKUP_DIR/$src" ]; then src="$(cd "$BACKUP_DIR/$src" && pwd)"
  else die "no backup '$src' (looked in . and $BACKUP_DIR; try --list)"; fi
  BACKUP_DIR="$(mkdir -p "$BACKUP_DIR" && cd "$BACKUP_DIR" && pwd)"   # docker -v needs absolute paths
  [ "$env_only" = 1 ] || [ -f "$src/SHA256SUMS" ] || die "$src has no SHA256SUMS — not a backup.sh backup"

  # volumes available in the backup
  local -a avail=() vols=()
  local p v
  if [ -d "$src/volumes" ]; then
    mapfile -t avail < <(cd "$src/volumes" && { find . -mindepth 1 -maxdepth 1 -type d -printf '%P\n'
                                                 find . -mindepth 1 -maxdepth 1 -name '*.files.tar.gz' -printf '%P\n' |
                                                   sed 's/\.files\.tar\.gz$//'; } | sort -u)
  fi
  if [ "$env_only" = 0 ]; then
    if [ "${#want[@]}" -eq 0 ]; then vols=("${avail[@]}"); else
      for v in "${want[@]}"; do
        v="${v#"${PROJECT}"_}"
        [[ " ${avail[*]} " == *" $v "* ]] || die "volume '$v' is not in $src (has: ${avail[*]:-none})"
        vols+=("$v")
      done
    fi
    [ "${#vols[@]}" -gt 0 ] || die "nothing to restore in $src"
  fi

  # services per volume (only running ones are stopped and started again)
  local compose_ok=0
  local -a COMPOSE=(docker compose -f "$HERE/generated/docker-compose.yml" --env-file "$ENV_FILE")
  [ -f "$HERE/docker-compose.override.yml" ] && COMPOSE+=(-f "$HERE/docker-compose.override.yml")
  [ -n "${TUNNEL_TOKEN:-}" ] && COMPOSE+=(--profile tunnel)
  [ "$PROJECT" = ai-portfolio-demos ] && [ -f "$HERE/generated/docker-compose.yml" ] && [ -f "$ENV_FILE" ] && compose_ok=1
  local -a services=() containers=()
  local full s
  for v in "${vols[@]}"; do
    full="${PROJECT}_$v"
    while IFS=$'\t' read -r p s; do
      [ -n "$p" ] || continue
      containers+=("$p"); services+=("$s")
    done < <(docker ps --filter "volume=$full" --filter "label=com.docker.compose.project=$PROJECT" \
               --format '{{.ID}}\t{{.Label "com.docker.compose.service"}}')
  done
  mapfile -t services < <(printf '%s\n' "${services[@]}" | grep . | sort -u || true)
  mapfile -t containers < <(printf '%s\n' "${containers[@]}" | grep . | sort -u || true)

  local ts; ts="$(date +%Y%m%d-%H%M%S)"
  local pre="$BACKUP_DIR/pre-restore-$ts"
  echo "Restore from: $src"
  [ -f "$src/manifest.json" ] && echo "  taken:      $(grep -o '"ts": *"[^"]*"' "$src/manifest.json" | head -1 | cut -d'"' -f4)"
  if [ "$env_only" = 0 ]; then
    for v in "${vols[@]}"; do
      echo "  volume:     ${PROJECT}_$v  <- $(cd "$src/volumes" && { find "$v" -type f 2>/dev/null; [ "$db_only" = 0 ] && ls "$v.files.tar.gz" 2>/dev/null; } | paste -sd' ' -)"
    done
    echo "  stop/start: ${services[*]:-(no running services use these volumes)}"
    echo "  current db files will be moved to: $pre/"
  fi
  [ "$with_env" = 1 ] && echo "  decrypt:    $src/env.enc -> $(dirname "$ENV_FILE")/.env.restored (your .env is not touched)"

  if [ "$env_only" = 0 ]; then
    local pat; pat="$(printf '%s|' "${vols[@]}")"; pat="${pat%|}"
    echo "Verifying sha256…"
    (cd "$src" && grep -E "  volumes/($pat)(/|\.files\.tar\.gz$)" SHA256SUMS | sha256sum -c --quiet -) ||
      die "checksum mismatch in $src — not restoring from it (try another day)"
    echo "  checksums ok"
  fi

  if [ "$dry" = 1 ]; then
    echo; echo "Dry run — would run:"
    if [ "$env_only" = 0 ]; then
      if [ "${#services[@]}" -gt 0 ]; then
        if [ "$compose_ok" = 1 ]; then echo "  ${COMPOSE[*]} stop ${services[*]}"; else echo "  docker stop ${containers[*]}"; fi
      fi
      for v in "${vols[@]}"; do echo "  restore ${PROJECT}_$v (files above) via a $PY_IMAGE container"; done
      if [ "${#services[@]}" -gt 0 ]; then
        if [ "$compose_ok" = 1 ]; then echo "  ${COMPOSE[*]} start ${services[*]}"; else echo "  docker start ${containers[*]}"; fi
      fi
    fi
    [ "$with_env" = 1 ] && echo "  openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in $src/env.enc -out $(dirname "$ENV_FILE")/.env.restored"
    return 0
  fi

  if [ "$yes" = 0 ]; then
    [ -t 0 ] || die "not a terminal: re-run with -y to confirm"
    local answer; read -r -p "Proceed? [y/N] " answer
    [[ "$answer" =~ ^[Yy] ]] || die "cancelled"
  fi

  if [ "$with_env" = 1 ]; then restore_env "$src"; fi
  [ "$env_only" = 1 ] && return 0

  # stop, restore, and always start again
  STARTED=0
  start_again() {
    [ "$STARTED" = 1 ] && return; STARTED=1
    [ "${#services[@]}" -gt 0 ] || return 0
    log "starting ${services[*]}"
    if [ "$compose_ok" = 1 ]; then "${COMPOSE[@]}" start "${services[@]}"; else docker start "${containers[@]}" >/dev/null; fi
  }
  trap start_again EXIT
  if [ "${#services[@]}" -gt 0 ]; then
    log "stopping ${services[*]}"
    if [ "$compose_ok" = 1 ]; then "${COMPOSE[@]}" stop "${services[@]}"; else docker stop "${containers[@]}" >/dev/null; fi
  fi
  mkdir -p "$pre"
  for v in "${vols[@]}"; do
    full="${PROJECT}_$v"
    if ! docker volume inspect "$full" >/dev/null 2>&1; then
      log "creating volume $full"
      docker volume create --label "com.docker.compose.project=$PROJECT" --label "com.docker.compose.volume=$v" "$full" >/dev/null
    fi
    log "restoring $full"
    docker run --rm --network none -v "$full:/vol" -v "$src/volumes:/backup:ro" -v "$pre:/pre" "$PY_IMAGE" \
      python -c "$RESTORE_PY" "/backup/$v" "/backup/$v.files.tar.gz" /vol "/pre/$v" \
      "$((1 - db_only))" "$(id -u)" "$(id -g)" | sed 's/^/    /' ||
      die "restoring $full failed — the services will be started again; previous files are in $pre/$v"
  done
  start_again
  rmdir "$pre" 2>/dev/null || true
  echo
  echo "Restored ${vols[*]} from $src."
  [ -d "$pre" ] && echo "The files that were replaced are in $pre/ (delete it once you're happy)."
  echo "Check: docker compose -f $HERE/generated/docker-compose.yml ps   and each app's /api/health page."
}

restore_env() {
  local src="$1" f out envdir
  envdir="$(dirname "$ENV_FILE")"   # deploy/selfhost unless ENV_FILE is overridden
  [ -f "$src/env.enc" ] || die "$src has no env.enc (BACKUP_PASSPHRASE was not set when it was taken)"
  command -v openssl >/dev/null || die "openssl is needed to decrypt (sudo apt install openssl)"
  if [ -z "${BACKUP_PASSPHRASE:-}" ]; then
    [ -t 0 ] || die "set BACKUP_PASSPHRASE (not a terminal, can't ask)"
    read -r -s -p "Backup passphrase: " BACKUP_PASSPHRASE; echo
  fi
  export BACKUP_PASSPHRASE
  umask 077
  for f in env.enc docker-compose.override.yml.enc; do
    [ -f "$src/$f" ] || continue
    if [ "$f" = env.enc ]; then out="$envdir/.env.restored"; else out="$envdir/docker-compose.override.yml.restored"; fi
    [ -e "$out" ] && die "$out already exists — move it away first"
    openssl enc -d -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE -in "$src/$f" -out "$out" ||
      { rm -f "$out"; die "could not decrypt $f (wrong passphrase?)"; }
    echo "  wrote $out"
  done
  echo "  Compare and adopt it yourself:  diff $envdir/.env $envdir/.env.restored   then   mv $envdir/.env.restored $envdir/.env"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then restore_main "$@"; fi
