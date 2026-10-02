#!/usr/bin/env bash
# One-time (Linux with systemd). Safe to re-run: it overwrites the units.
#  - Docker and containerd start at boot; every container has restart: unless-stopped, so the demos come back on reboot.
#  - ai-portfolio-demos.timer runs update.sh 30 s after boot (starts anything that isn't up) and every 2 minutes
#    after that (deploys new commits on main once their GitHub Actions checks pass).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="$(id -un)"
command -v flock >/dev/null || { echo "flock missing (package util-linux)"; exit 1; }
sudo systemctl enable --now docker.service containerd.service
sudo tee /etc/systemd/system/ai-portfolio-demos.service >/dev/null <<UNIT
[Unit]
Description=Deploy AI portfolio live demos from GitHub main (CI-gated)
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
User=$USER_NAME
ExecStart=$HERE/update.sh
TimeoutStartSec=45min
UNIT
sudo tee /etc/systemd/system/ai-portfolio-demos.timer >/dev/null <<UNIT
[Unit]
Description=Check GitHub main for a new CI-passed commit every 2 minutes

[Timer]
OnBootSec=30s
OnUnitInactiveSec=2min
Persistent=true

[Install]
WantedBy=timers.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now ai-portfolio-demos.timer
echo "Installed. A sleeping machine means the demos are down; to stop it ever sleeping:"
echo "  sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target"
echo "  Status:  $HERE/update.sh --status      Timer: systemctl list-timers ai-portfolio-demos"
echo "  Logs:    journalctl -u ai-portfolio-demos -f"
