#!/usr/bin/env bash
# Narrate the escalation walkthrough with a neural voice (Piper), on a machine that can download it (e.g. the
# EVO-X1). Everything runs in a throwaway container; the only output is the finished video in ~/video-out/.
#
#   ~/ai-portfolio/scripts/video/narrate-on-host.sh                      # default voice en_US-lessac-high
#   VOICE=en_US-ryan-high ~/ai-portfolio/scripts/video/narrate-on-host.sh
#
# Voices: https://rhasspy.github.io/piper-samples/ — the voice model (~100 MB) is cached in ~/video-out/voices.
# Nothing is written inside the repo, so the deploy-only clone stays clean.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${OUT:-$HOME/video-out}"
VOICE="${VOICE:-en_US-lessac-high}"
mkdir -p "$OUT/voices"
docker run --rm -v "$REPO:/repo:ro" -v "$OUT:/out" -e HOME=/tmp python:3.11-slim bash -c "
  set -e
  apt-get update -qq && apt-get install -y -qq ffmpeg >/dev/null
  pip install -q --disable-pip-version-check piper-tts
  python /repo/scripts/video/narrate.py --tts piper --voice '$VOICE' --voices-dir /out/voices \
    --work /tmp/work --out /out/escalation.mp4
"
echo "Done: $OUT/escalation.mp4 — attach it in the chat (or copy it to the repo and push)."
