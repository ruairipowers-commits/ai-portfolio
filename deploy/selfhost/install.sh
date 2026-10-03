#!/usr/bin/env bash
# One-time setup on the demo host (Linux with systemd), and again whenever you've reviewed a change to the host
# scripts (the weekly maintenance email says when). Safe to re-run.
#
#   sudo deploy/selfhost/install.sh            # as root, from the deploy clone; the deploy user is the clone's owner
#
# What it does:
#  1. Copies the host scripts to /usr/local/lib/ai-portfolio, owned by root and read-only for everyone else. The
#     timers run those copies, so a push to GitHub can't change what runs on this machine — including the deploy
#     guard that update.sh asks before every deploy (deploy-guard.py: no privileged containers, no Docker socket,
#     no host mounts, CPU/memory limits, ports on loopback only).
#  2. Installs systemd timers (all run as the deploy user, at low priority except the deploy itself):
#       ai-portfolio-demos        every 2 min and at boot   deploy new CI-passed commits; restart anything down
#       ai-portfolio-hostmon      every minute              load, containers, backup/maintenance/scan status → console
#       ai-portfolio-backup       nightly 03:15             SQLite volumes (integrity-checked) + encrypted .env
#       ai-portfolio-maintenance  daily 06:10               OS/image/Ollama updates, reboot needed, disk, backup age
#       ai-portfolio-pentest      Sundays 05:30             security self-assessment (repo, external, host)
#     The console turns their results into alerts and a weekly health & security email.
#  3. Tightens deploy/selfhost/.env to mode 600.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
LIB=/usr/local/lib/ai-portfolio
[ "$(id -u)" = 0 ] || { echo "Run with sudo: sudo $0"; exit 1; }
USER_NAME="${SUDO_USER:-$(stat -c %U "$REPO")}"
[ "$USER_NAME" != root ] || { echo "Run it with sudo as the deploy user, not from a root shell"; exit 1; }
command -v flock >/dev/null || { echo "flock missing (package util-linux)"; exit 1; }
command -v python3 >/dev/null || echo "note: python3 not found — the deploy guard runs in a container instead and the weekly security scan is skipped"

# 1. root-owned copies of everything a timer runs
install -d -o root -g root -m 755 "$LIB"
for f in update.sh hostmon.sh backup.sh restore.sh maintenance.sh deploy-guard.py; do
  install -o root -g root -m 755 "$HERE/$f" "$LIB/$f"
done
install -o root -g root -m 755 "$REPO/security/pentest.py" "$LIB/pentest.py"
git -C "$REPO" rev-parse HEAD > "$LIB/INSTALLED_FROM" 2>/dev/null || true
chmod 644 "$LIB/INSTALLED_FROM" 2>/dev/null || true
[ -f "$HERE/.env" ] && { chown "$USER_NAME" "$HERE/.env"; chmod 600 "$HERE/.env"; }

# 2. systemd units
unit() {   # name, description, ExecStart, extra [Service] lines
  cat > "/etc/systemd/system/$1.service" <<UNIT
[Unit]
Description=$2
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
User=$USER_NAME
Environment=AI_PORTFOLIO_REPO=$REPO
ExecStart=$3
$4
UNIT
}
timer() {  # name, description, [Timer] lines
  cat > "/etc/systemd/system/$1.timer" <<UNIT
[Unit]
Description=$2

[Timer]
$3
Persistent=true

[Install]
WantedBy=timers.target
UNIT
}
systemctl enable --now docker.service containerd.service

unit ai-portfolio-demos "Deploy AI portfolio live demos from GitHub main (CI-gated, deploy guard)" \
  "$LIB/update.sh" "TimeoutStartSec=45min"
timer ai-portfolio-demos "Check GitHub main for a new CI-passed commit every 2 minutes" \
  "OnBootSec=30s
OnUnitInactiveSec=2min"

unit ai-portfolio-hostmon "AI portfolio host monitor (one sample to the governance console)" \
  "$LIB/hostmon.sh" "Nice=10
TimeoutStartSec=2min"
timer ai-portfolio-hostmon "Host monitor every minute" "OnBootSec=1min
OnUnitActiveSec=1min
AccuracySec=5s"

unit ai-portfolio-backup "Back up AI portfolio demo data (Docker volumes, encrypted .env)" \
  "$LIB/backup.sh" "Nice=15
IOSchedulingClass=idle
TimeoutStartSec=2h"
timer ai-portfolio-backup "Nightly backup of the demo data" "OnCalendar=*-*-* 03:15
RandomizedDelaySec=10min"

unit ai-portfolio-maintenance "Update and health check for the AI portfolio host (read-only)" \
  "$LIB/maintenance.sh" "Nice=10
TimeoutStartSec=15min"
timer ai-portfolio-maintenance "Daily update check" "OnCalendar=*-*-* 06:10
RandomizedDelaySec=10min"

unit ai-portfolio-pentest "Weekly security self-assessment of the AI portfolio" \
  "/usr/bin/env python3 $LIB/pentest.py --all --state $HERE/.state/pentest.json --out $REPO/security/reports/pentest-latest.md" \
  "Nice=15
TimeoutStartSec=30min
EnvironmentFile=-$HERE/.env"
timer ai-portfolio-pentest "Weekly security self-assessment (Sunday 05:30)" "OnCalendar=Sun *-*-* 05:30"

systemctl daemon-reload
for t in demos hostmon backup maintenance pentest; do systemctl enable --now "ai-portfolio-$t.timer"; done

echo "Installed to $LIB (from $(cut -c1-7 "$LIB/INSTALLED_FROM" 2>/dev/null || echo '?')) for user $USER_NAME."
echo "Timers:  systemctl list-timers 'ai-portfolio-*'"
echo "Logs:    journalctl -u ai-portfolio-demos -f      (also -hostmon, -backup, -maintenance, -pentest)"
echo "Status:  $HERE/update.sh --status"
echo "A sleeping machine means the demos are down; to stop it ever sleeping:"
echo "  sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target"
