#!/usr/bin/env bash
# Tests for backup.sh, restore.sh and maintenance.sh.
#   deploy/selfhost/tests/test_scripts.sh
# 1. bash -n on every script, shellcheck when it is installed (SHELLCHECK=/path/to/shellcheck to pick one).
# 2. Pure logic, no Docker: JSON building, retention selection, integrity summary, compose/Dockerfile image
#    parsing, backup-age and digest comparison (with a fake `docker` on PATH), and — when python3 is on the
#    test machine — the Python that runs inside the backup/restore containers, against a live WAL database.
# 3. End to end when Docker works and a Python image is available locally (E2E_PY_IMAGE, default
#    python:3.11-slim): a throwaway compose project "ai-portfolio-demos-test" with labelled volumes and a
#    writer container, backup -> damage -> restore, the integrity-failure path, retention and a fake rclone.
#    Skipped (not failed) without Docker. E2E=0 skips it explicitly.
# Exit status: number of failed checks (0 = all passed).
# shellcheck disable=SC1091,SC2016,SC2329
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
PASS=0; FAIL=0; SKIP=0
pass() { PASS=$((PASS + 1)); echo "  ok   $*"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $*"; }
skip() { SKIP=$((SKIP + 1)); echo "  skip $*"; }
check() { local name="$1"; shift; if "$@"; then pass "$name"; else fail "$name"; fi; }
eq() { [ "$1" = "$2" ] || { echo "       expected: $2"; echo "       got:      $1"; return 1; }; }
valid_json() {
  if command -v python3 >/dev/null; then python3 -c 'import json,sys; json.load(sys.stdin)' <<< "$1"
  elif command -v jq >/dev/null; then jq -e . >/dev/null <<< "$1"
  else return 0; fi
}
have_py() { command -v python3 >/dev/null; }

E2E_PROJECT=ai-portfolio-demos-test
cleanup() {
  if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    docker rm -f "$E2E_PROJECT-writer" >/dev/null 2>&1 || true
    docker volume ls -q --filter "label=com.docker.compose.project=$E2E_PROJECT" | xargs -r docker volume rm -f >/dev/null 2>&1 || true
    docker image rm -f ai-portfolio-test/fake-rclone >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "== syntax"
for s in backup.sh restore.sh maintenance.sh tests/test_scripts.sh; do
  check "bash -n $s" bash -n "$HERE/$s"
done
SC="${SHELLCHECK:-$(command -v shellcheck || true)}"
if [ -n "$SC" ]; then
  for s in backup.sh restore.sh maintenance.sh tests/test_scripts.sh; do
    check "shellcheck $s" "$SC" -x "$HERE/$s"
  done
else skip "shellcheck not installed"; fi

echo "== backup.sh helpers"
(
  # shellcheck source=../backup.sh
  . "$HERE/backup.sh"
  set +e
  check "json_str escapes" eq "$(json_str $'a"b\\c\nd\te')" '"a\"b\\c\nd\te"'
  files="$(printf 'volumes/x/a.sqlite\t4096\tabc\nenv.enc\t32\tdef\n' | files_json)"
  check "files_json" eq "$files" '[{"name": "volumes/x/a.sqlite", "bytes": 4096, "sha256": "abc"}, {"name": "env.enc", "bytes": 32, "sha256": "def"}]'
  check "files_json empty" eq "$(printf '' | files_json)" '[]'
  st="$(status_json 2026-10-03T03:20:00Z true /b/2026-10-03 "$files" ok skipped false "")"
  check "status_json is valid JSON" valid_json "$st"
  check "status_json exact" eq "$st" '{"ts": "2026-10-03T03:20:00Z", "ok": true, "dir": "/b/2026-10-03", "files": [{"name": "volumes/x/a.sqlite", "bytes": 4096, "sha256": "abc"}, {"name": "env.enc", "bytes": 32, "sha256": "def"}], "integrity": "ok", "offsite": "skipped", "encrypted_env": false, "error": ""}'
  if have_py; then
    keys="$(python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)))' <<< "$st")"
    check "status_json keys" eq "$keys" "ts,ok,dir,files,integrity,offsite,encrypted_env,error"
  fi
  check "integrity_summary ok" eq "$(printf 'a/x.sqlite\tok\nb/y.sqlite\tok\n' | integrity_summary)" ok
  check "integrity_summary none" eq "$(printf '' | integrity_summary)" ok
  check "integrity_summary failed" eq "$(printf 'a/x.sqlite\tok\nb/y.sqlite\terror: file is not a database\n' | integrity_summary)" \
    "failed: b/y.sqlite: error: file is not a database"

  # retention: 60 consecutive days ending Sat 2026-10-03 (Sundays: 09-27, 09-20, …)
  days="$(for i in $(seq 0 59); do date -u -d "2026-10-03 -$i days" +%F; done)"
  pruned="$(printf '%s\nnot-a-date\n2026-10-03.failed-031500\n' "$days" | retention_prune_list 14 8)"
  kept="$(comm -23 <(sort <<< "$days") <(sort <<< "$pruned") | sort -r)"
  daily="$(head -14 <<< "$days")"
  sundays="$(while read -r d; do [ "$(date -u -d "$d" +%u)" = 7 ] && echo "$d"; done <<< "$days" | head -8)"
  expect="$(printf '%s\n%s\n' "$daily" "$sundays" | sort -u -r)"
  check "retention keeps 14 daily + 8 Sundays" eq "$kept" "$expect"
  check "retention count (14 + 6 older Sundays = 20)" eq "$(grep -c . <<< "$kept")" 20
  check "retention ignores non-date names" eq "$(grep -c -E 'not-a-date|failed' <<< "$pruned" || true)" 0
  check "retention keeps all when few" eq "$(printf '2026-10-01\n2026-10-02\n' | retention_prune_list 14 8)" ""
  check "retention daily=1 weekly=0" eq "$(printf '2026-10-01\n2026-10-03\n2026-10-02\n' | retention_prune_list 1 0 | paste -sd,)" "2026-10-02,2026-10-01"
)

echo "== maintenance.sh helpers"
(
  # shellcheck source=../maintenance.sh
  . "$HERE/maintenance.sh"
  set +e
  cat > "$TMP/compose.yml" <<'YML'
name: x
services:
  app:
    build:
      context: .
    image: ai-portfolio/app:latest
  ollama:
    image: ${OLLAMA_IMAGE:-ollama/ollama:latest}
    volumes:
    - m:/root/.ollama
  caddy:
    image: caddy:2-alpine
  cloudflared:
    image: "cloudflare/cloudflared:latest"
volumes:
  m: {}
YML
  check "compose_images" eq "$(compose_images "$TMP/compose.yml" | tr '\t' ' ' | paste -sd,)" \
    'ollama ${OLLAMA_IMAGE:-ollama/ollama:latest},caddy caddy:2-alpine,cloudflared cloudflare/cloudflared:latest'
  check "resolve_ref default" eq "$(unset OLLAMA_IMAGE; resolve_ref '${OLLAMA_IMAGE:-ollama/ollama:latest}')" ollama/ollama:latest
  check "resolve_ref env" eq "$(OLLAMA_IMAGE=ollama/ollama:rocm resolve_ref '${OLLAMA_IMAGE:-ollama/ollama:latest}')" ollama/ollama:rocm
  check "resolve_ref plain" eq "$(resolve_ref caddy:2-alpine)" caddy:2-alpine
  printf 'FROM node:22-slim AS server\nRUN x\nFROM python:3.11-slim\nCOPY --from=server /a /b\n' > "$TMP/Dockerfile.a"
  printf 'FROM --platform=linux/amd64 python:3.11-slim\nFROM server\n' > "$TMP/Dockerfile.b"
  check "dockerfile_bases" eq "$(dockerfile_bases "$TMP/Dockerfile.a" "$TMP/Dockerfile.b" | paste -sd,)" "node:22-slim,python:3.11-slim"
  check "hours_since" eq "$(hours_since 2026-10-03T03:00:00Z "$(date -u -d 2026-10-04T15:30:00Z +%s)")" 36.5
  check "hours_since bad ts" eq "$(hours_since garbage)" ""
  mkdir -p "$TMP/st1" "$TMP/st2" "$TMP/st3"
  printf '{"ts": "2026-10-03T03:20:00Z", "ok": true, "dir": "/x", "files": [], "error": ""}\n' > "$TMP/st1/backup.json"
  printf '{"ts": "2026-10-04T03:20:00Z", "ok": false, "dir": "", "files": [], "error": "x"}\n' > "$TMP/st2/backup.json"
  printf '2026-10-02T03:21:00Z\n' > "$TMP/st2/backup_last_ok"
  check "json_field ok" eq "$(json_field "$TMP/st1/backup.json" ok)" true
  check "last good backup (ok run)" eq "$(last_good_backup_ts "$TMP/st1")" 2026-10-03T03:20:00Z
  check "last good backup (failed run -> backup_last_ok)" eq "$(last_good_backup_ts "$TMP/st2")" 2026-10-02T03:21:00Z
  check "last good backup (none)" eq "$(last_good_backup_ts "$TMP/st3")" ""

  # digest comparison with a fake docker
  mkdir -p "$TMP/bin"
  cat > "$TMP/bin/docker" <<'SH'
#!/usr/bin/env bash
case "$1 $2" in
  "image inspect") case "${*: -1}" in
      caddy:2-alpine) printf 'caddy@sha256:aaa\n' ;;
      old:1)          printf 'old@sha256:bbb\n' ;;
      *) exit 1 ;; esac ;;
  "buildx imagetools") case "$4" in
      caddy:2-alpine|old:1) printf '"sha256:aaa"\n' ;;
      *) exit 1 ;; esac ;;
  *) exit 1 ;;
esac
SH
  chmod +x "$TMP/bin/docker"
  PATH="$TMP/bin:$PATH"
  check "update_available false (same digest)" eq "$(update_available caddy:2-alpine)" false
  check "update_available true (newer at registry)" eq "$(update_available old:1)" true
  check "update_available unknown (not pulled)" eq "$(update_available missing:1)" ""
)

echo "== container Python (run with the local python3)"
if have_py; then
  (
    # shellcheck source=../backup.sh
    . "$HERE/backup.sh"
    # shellcheck source=../restore.sh
    . "$HERE/restore.sh"
    set +e
    src="$TMP/vol"; mkdir -p "$src/sub"; echo hello > "$src/notes.txt"; echo x > "$src/sub/cache.json"
    python3 - "$src/app.sqlite" <<'PY' &
import sqlite3, sys, time
c = sqlite3.connect(sys.argv[1]); c.execute("pragma journal_mode=wal"); c.execute("create table t(i)")
for i in range(300):
    c.execute("insert into t values(?)", (i,)); c.commit(); time.sleep(0.005)
time.sleep(5)
PY
    writer=$!
    sleep 1
    out="$(python3 -c "$VOLUME_BACKUP_PY" "$src" "$TMP/bk/volumes/v" "$TMP/bk/volumes/v.files.tar.gz" "$(id -u)" "$(id -g)")"
    check "backup py: sqlite copied with integrity ok" eq "$(grep '^sqlite' <<< "$out" | tr '\t' ' ')" "sqlite app.sqlite ok"
    check "backup py: other files tarred (wal/shm excluded)" eq "$(grep '^tar' <<< "$out" | tr '\t' ' ')" "tar v.files.tar.gz 2"
    check "backup py: no -wal/-shm next to the copy" eq "$(find "$TMP/bk" -name '*-wal' -o -name '*-shm' | wc -l)" 0
    rows="$(python3 -c 'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("select count(*) from t").fetchone()[0])' "$TMP/bk/volumes/v/app.sqlite")"
    check "backup py: copy has committed rows ($rows)" test "$rows" -gt 0
    kill "$writer" 2>/dev/null; wait "$writer" 2>/dev/null
    printf 'SQLite format 3\000garbage-garbage-garbage' > "$src/broken.sqlite"
    out="$(python3 -c "$VOLUME_BACKUP_PY" "$src" "$TMP/bk2/volumes/v" "$TMP/bk2/volumes/v.files.tar.gz" "$(id -u)" "$(id -g)")"
    check "backup py: corrupt db reported" grep -q $'^sqlite\tbroken.sqlite\terror' <<< "$out"

    # restore into a volume that has a newer db plus a stale -wal that must not survive
    dst="$TMP/dst"; mkdir -p "$dst"
    python3 -c 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute("create table t(i)"); c.execute("insert into t values(-1)"); c.commit()' "$dst/app.sqlite"
    echo stale > "$dst/app.sqlite-wal"; echo changed > "$dst/notes.txt"
    out="$(python3 -c "$RESTORE_PY" "$TMP/bk/volumes/v" "$TMP/bk/volumes/v.files.tar.gz" "$dst" "$TMP/pre/v" 1 "$(id -u)" "$(id -g)")"
    check "restore py: reports restored db" grep -q $'^restored\tapp.sqlite' <<< "$out"
    check "restore py: stale -wal moved aside" test ! -e "$dst/app.sqlite-wal" -a -f "$TMP/pre/v/app.sqlite-wal"
    check "restore py: old db kept in pre-restore" test -f "$TMP/pre/v/app.sqlite"
    rows2="$(python3 -c 'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("select count(*) from t").fetchone()[0])' "$dst/app.sqlite")"
    check "restore py: restored rows match backup" eq "$rows2" "$rows"
    check "restore py: other files restored" eq "$(cat "$dst/notes.txt")" hello
  )
else skip "python3 not on this machine"; fi

echo "== end to end (Docker)"
PY_IMAGE="${E2E_PY_IMAGE:-python:3.11-slim}"
if [ "${E2E:-1}" = 0 ]; then skip "E2E=0"
elif ! command -v docker >/dev/null || ! docker info >/dev/null 2>&1; then skip "Docker not available"
elif ! docker image inspect "$PY_IMAGE" >/dev/null 2>&1; then skip "image $PY_IMAGE not present locally (docker pull it or set E2E_PY_IMAGE)"
else
  P="$E2E_PROJECT"
  cleanup_e2e() { docker rm -f "$P-writer" >/dev/null 2>&1 || true
                  docker volume ls -q --filter "label=com.docker.compose.project=$P" | xargs -r docker volume rm -f >/dev/null 2>&1 || true; }
  cleanup_e2e
  for v in console-data ollama-models; do
    docker volume create --label "com.docker.compose.project=$P" --label "com.docker.compose.volume=$v" "${P}_$v" >/dev/null
  done
  docker run --rm -v "${P}_ollama-models:/m" "$PY_IMAGE" python -c "open('/m/blob','w').write('x'*1000)"
  # a "service" holding the db open and writing to it while the backup runs
  docker run -d --name "$P-writer" --label "com.docker.compose.project=$P" --label "com.docker.compose.service=governance-console" \
    -v "${P}_console-data:/app/warehouse" "$PY_IMAGE" python -c "
import sqlite3, time, os
c = sqlite3.connect('/app/warehouse/console.sqlite', timeout=30); c.execute('pragma journal_mode=wal')
c.execute('create table if not exists t(i)')
os.path.exists('/app/warehouse/settings.json') or open('/app/warehouse/settings.json', 'w').write('{\"a\": 1}')
i = c.execute('select count(*) from t').fetchone()[0]
while True:
    if i < 500:
        c.execute('insert into t values(?)', (i,)); c.commit(); i += 1
    time.sleep(0.01)
" >/dev/null
  sleep 3
  # fake rclone: checks its arguments and the mounted config, fails for remotes starting with "fail:"
  mkdir -p "$TMP/rclone-img" "$TMP/rclone-conf"
  echo "[fake]" > "$TMP/rclone-conf/rclone.conf"
  cat > "$TMP/rclone-img/fake_rclone.py" <<'PY'
import os, sys
cmd, args = sys.argv[1], sys.argv[2:]
assert os.path.isfile("/config/rclone/rclone.conf"), "no config"
if any(a.startswith("fail:") for a in args):
    print("ERROR : fake failure"); sys.exit(1)
if cmd == "copy":
    assert os.path.isfile(os.path.join(args[0], "manifest.json")), "nothing to copy"
print(cmd, *args)
PY
  printf 'FROM %s\nCOPY fake_rclone.py /fake_rclone.py\nENTRYPOINT ["python", "/fake_rclone.py"]\n' "$PY_IMAGE" > "$TMP/rclone-img/Dockerfile"
  docker build -q -t ai-portfolio-test/fake-rclone "$TMP/rclone-img" >/dev/null 2>&1 || DOCKER_BUILDKIT=0 docker build -q -t ai-portfolio-test/fake-rclone "$TMP/rclone-img" >/dev/null

  B="$TMP/backups"; S="$TMP/state"; mkdir -p "$B"
  printf "GOVERNANCE_ADMIN_TOKEN=secret-token\nBACKUP_PASSPHRASE='correct horse battery staple'\n" > "$TMP/env"
  # old backups for retention: 10 days before today, plus a Sunday long ago
  for i in $(seq 1 10); do mkdir -p "$B/$(date -d "-$i days" +%F)"; done
  mkdir -p "$B/2026-01-04"   # a Sunday
  run_backup() {
    env PROJECT="$P" ENV_FILE="$TMP/env" STATE_DIR="$S" BACKUP_DIR="$B" PY_IMAGE="$PY_IMAGE" \
        BACKUP_KEEP_DAILY=3 BACKUP_KEEP_WEEKLY=1 RCLONE_IMAGE=ai-portfolio-test/fake-rclone \
        RCLONE_CONFIG_DIR="$TMP/rclone-conf" "$@" "$HERE/backup.sh" > "$TMP/backup.log" 2>&1
  }
  rc=0; run_backup BACKUP_RCLONE_REMOTE=fake:bucket || rc=$?
  today="$(date +%F)"; st="$(cat "$S/backup.json")"
  check "e2e backup exit 0" eq "$rc" 0 || cat "$TMP/backup.log"
  check "e2e backup.json valid" valid_json "$st"
  check "e2e ok true" grep -q '"ok": true' <<< "$st"
  check "e2e integrity ok" grep -q '"integrity": "ok"' <<< "$st"
  check "e2e offsite ok" grep -q '"offsite": "ok"' <<< "$st"
  check "e2e encrypted_env true" grep -q '"encrypted_env": true' <<< "$st"
  check "e2e sqlite copied" test -s "$B/$today/volumes/console-data/console.sqlite"
  check "e2e other files tarred" test -s "$B/$today/volumes/console-data.files.tar.gz"
  check "e2e ollama-models excluded" test ! -e "$B/$today/volumes/ollama-models" -a ! -e "$B/$today/volumes/ollama-models.files.tar.gz"
  check "e2e no clear-text secret in backup" bash -c "! grep -rq secret-token '$B/$today'"
  check "e2e SHA256SUMS verifies" bash -c "cd '$B/$today' && sha256sum -c --quiet SHA256SUMS"
  check "e2e manifest valid" valid_json "$(cat "$B/$today/manifest.json")"
  check "e2e env.enc decrypts" eq "$(BACKUP_PASSPHRASE='correct horse battery staple' openssl enc -d -aes-256-cbc -pbkdf2 -salt \
        -pass env:BACKUP_PASSPHRASE -in "$B/$today/env.enc" | head -1)" "GOVERNANCE_ADMIN_TOKEN=secret-token"
  remaining="$(find "$B" -mindepth 1 -maxdepth 1 -type d -name '????-??-??' -printf '%f\n' | sort -r | paste -sd' ')"
  expected_keep="$(printf '%s\n' "$today" "$(date -d '-1 days' +%F)" "$(date -d '-2 days' +%F)" \
                    "$(for i in $(seq 0 10); do d="$(date -d "-$i days" +%F)"; [ "$(date -d "$d" +%u)" = 7 ] && echo "$d"; done | head -1)" |
                    grep . | sort -u -r | paste -sd' ')"
  check "e2e retention (3 daily + newest Sunday)" eq "$remaining" "$expected_keep"

  rc=0; run_backup BACKUP_RCLONE_REMOTE=fail:bucket || rc=$?
  st="$(cat "$S/backup.json")"
  check "e2e offsite failure -> exit nonzero" test "$rc" -ne 0
  check "e2e offsite failure recorded" grep -q '"offsite": "failed: ' <<< "$st"
  check "e2e offsite failure keeps local backup" grep -q "\"dir\": \"$B/$today\"" <<< "$st"

  printf 'GOVERNANCE_ADMIN_TOKEN=secret-token\n' > "$TMP/env-nopass"
  rc=0; run_backup ENV_FILE="$TMP/env-nopass" || rc=$?
  st="$(cat "$S/backup.json")"
  check "e2e no passphrase: still ok" eq "$rc" 0
  check "e2e no passphrase: env skipped" test ! -e "$B/$today/env.enc"
  check "e2e no passphrase: encrypted_env false" grep -q '"encrypted_env": false' <<< "$st"

  # damage the data, then restore
  rows_backup="$(docker run --rm -v "$B/$today/volumes:/b:ro" "$PY_IMAGE" python -c \
    "import sqlite3; print(sqlite3.connect('file:/b/console-data/console.sqlite?mode=ro&immutable=1', uri=True).execute('select count(*) from t').fetchone()[0])")"
  docker exec "$P-writer" python -c "import sqlite3; c=sqlite3.connect('/app/warehouse/console.sqlite'); c.execute('delete from t'); c.commit()"
  docker exec "$P-writer" python -c "open('/app/warehouse/settings.json','w').write('damaged')"
  out="$(env PROJECT="$P" ENV_FILE="$TMP/env" BACKUP_DIR="$B" PY_IMAGE="$PY_IMAGE" "$HERE/restore.sh" "$today" --dry-run 2>&1)"
  check "e2e restore --dry-run lists the service" grep -q "docker stop" <<< "$out"
  check "e2e restore --dry-run verifies checksums" grep -q "checksums ok" <<< "$out"
  check "e2e restore --dry-run changes nothing" eq "$(docker inspect -f '{{.State.Running}}' "$P-writer")" true
  rc=0; out="$(env PROJECT="$P" ENV_FILE="$TMP/env" BACKUP_DIR="$B" PY_IMAGE="$PY_IMAGE" "$HERE/restore.sh" "$today" console-data -y 2>&1)" || rc=$?
  check "e2e restore exit 0" eq "$rc" 0 || echo "$out"
  check "e2e restore restarted the service" eq "$(docker inspect -f '{{.State.Running}}' "$P-writer")" true
  sleep 1
  rows_now="$(docker run --rm -v "${P}_console-data:/w:ro" "$PY_IMAGE" python -c \
    "import sqlite3; print(sqlite3.connect('file:/w/console.sqlite?mode=ro&immutable=1', uri=True).execute('select count(*) from t').fetchone()[0])")"
  check "e2e restored rows ($rows_now >= $rows_backup)" test "$rows_now" -ge "$rows_backup" -a "$rows_backup" -gt 0
  check "e2e restored other files" eq "$(docker exec "$P-writer" cat /app/warehouse/settings.json)" '{"a": 1}'
  check "e2e pre-restore copy kept" bash -c "ls '$B'/pre-restore-*/console-data/console.sqlite >/dev/null"
  # tamper with the backup -> restore refuses
  echo tamper >> "$B/$today/volumes/console-data/console.sqlite"
  rc=0; env PROJECT="$P" ENV_FILE="$TMP/env" BACKUP_DIR="$B" PY_IMAGE="$PY_IMAGE" "$HERE/restore.sh" "$today" -y >/dev/null 2>&1 || rc=$?
  check "e2e restore refuses a bad checksum" test "$rc" -ne 0
  # env restore goes next to ENV_FILE, never over it (run before the tampered day is overwritten)
  rc=0; env PROJECT="$P" ENV_FILE="$TMP/env" BACKUP_DIR="$B" BACKUP_PASSPHRASE='correct horse battery staple' \
      "$HERE/restore.sh" "$(find "$B" -mindepth 1 -maxdepth 1 -name '????-??-??' -printf '%f\n' | sort -r | head -1)" --env-only -y >/dev/null 2>&1 || rc=$?
  # (today's dir no longer has env.enc after the no-passphrase run, so this is expected to fail cleanly)
  check "e2e --env-only without env.enc fails cleanly" test "$rc" -ne 0 -a ! -e "$TMP/.env.restored"
  run_backup || true
  rc=0; env PROJECT="$P" ENV_FILE="$TMP/env" BACKUP_DIR="$B" "$HERE/restore.sh" "$today" --env-only -y >/dev/null 2>&1 || rc=$?
  check "e2e --env-only writes .env.restored" test "$rc" -eq 0 -a -f "$TMP/.env.restored"
  check "e2e .env.restored content" eq "$(head -1 "$TMP/.env.restored")" "GOVERNANCE_ADMIN_TOKEN=secret-token"
  check "e2e .env untouched" eq "$(head -1 "$TMP/env")" "GOVERNANCE_ADMIN_TOKEN=secret-token"

  # integrity failure: a corrupt db -> nonzero exit, JSON still written, good backup of the day kept
  docker run --rm -v "${P}_console-data:/w" "$PY_IMAGE" python -c \
    "open('/w/broken.sqlite','wb').write(b'SQLite format 3\x00' + b'x' * 200)"
  rc=0; run_backup || rc=$?
  st="$(cat "$S/backup.json")"
  check "e2e corrupt db -> exit nonzero" test "$rc" -ne 0
  check "e2e corrupt db -> ok false" grep -q '"ok": false' <<< "$st"
  check "e2e corrupt db -> integrity failed" grep -q '"integrity": "failed: console-data/broken.sqlite' <<< "$st"
  check "e2e corrupt db -> good backup kept" test -s "$B/$today/volumes/console-data/console.sqlite"
  check "e2e corrupt db -> failed copy kept aside" bash -c "ls -d '$B/$today'.failed-* >/dev/null"
  check "e2e corrupt db -> backup_last_ok kept" test -s "$S/backup_last_ok"

  # an unparsable .env still yields a status JSON, without echoing the offending (secret) line
  printf 'BACKUP_PASSPHRASE=hunter2 hunter3\n' > "$TMP/badenv"
  rc=0; env PROJECT="$P" ENV_FILE="$TMP/badenv" STATE_DIR="$TMP/state-bad" BACKUP_DIR="$B" PY_IMAGE="$PY_IMAGE" \
    "$HERE/backup.sh" >/dev/null 2>&1 || rc=$?
  check "e2e bad .env -> exit nonzero" test "$rc" -ne 0
  check "e2e bad .env -> JSON written" grep -q '"error": "could not read' "$TMP/state-bad/backup.json"
  check "e2e bad .env -> no secret in JSON" bash -c "! grep -q hunter '$TMP/state-bad/backup.json'"

  # maintenance against the test state: valid JSON with the exact keys
  rc=0; ENV_FILE="$TMP/env" STATE_DIR="$S" COMPOSE_FILE="$TMP/none.yml" PROJECTS_DIR="$TMP/none" "$HERE/maintenance.sh" > "$TMP/m.log" 2>&1 || rc=$?
  check "e2e maintenance exit 0" eq "$rc" 0
  m="$(cat "$S/maintenance.json")"
  check "e2e maintenance.json valid" valid_json "$m"
  if have_py; then
    check "e2e maintenance.json keys" eq "$(python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)))' <<< "$m")" \
      "ts,apt_upgradable,apt_security,reboot_required,reboot_pkgs,images,ollama_version,docker_version,disk_free_gb,backup_age_hours,actions,ok"
  fi
  check "e2e maintenance sees a recent backup" grep -qE '"backup_age_hours": 0\.[0-9]' <<< "$m"
  cleanup_e2e
fi

echo
echo "passed $PASS, failed $FAIL, skipped $SKIP"
exit "$FAIL"
