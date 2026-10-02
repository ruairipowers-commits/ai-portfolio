#!/usr/bin/env bash
# One-time: run update.sh every 5 minutes with systemd (Linux). Re-run safely; it overwrites the units.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="$(id -un)"
sudo tee /etc/systemd/system/ai-portfolio-demos.service >/dev/null <<UNIT
[Unit]
Description=Deploy AI portfolio live demos from GitHub main
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
User=$USER_NAME
ExecStart=$HERE/update.sh
UNIT
sudo tee /etc/systemd/system/ai-portfolio-demos.timer >/dev/null <<UNIT
[Unit]
Description=Check GitHub for new commits every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now ai-portfolio-demos.timer
echo "Installed. Logs: journalctl -u ai-portfolio-demos -f    Status: systemctl list-timers ai-portfolio-demos"
