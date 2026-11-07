#!/usr/bin/env bash
# Run a full --apply install into the project-local sandbox HOME.
# It never touches the real ~/.config.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX="$ROOT/.sandbox/home"
STATE="$ROOT/.sandbox/state"
LOG="$ROOT/docs/sandbox-install.log"
mkdir -p "$ROOT/.sandbox" "$ROOT/docs"
rm -rf -- "$SANDBOX" "$STATE"
mkdir -p -- "$SANDBOX" "$STATE"
HOME="$SANDBOX" INTEGRATED_STATE_DIR="$STATE" \
    "$ROOT/scripts/install.sh" --apply --profile m3-waybar \
    --profile niri-core --profile niri-theme --profile elan-gesture \
    >"$LOG" 2>&1
printf 'sandbox install OK\n'
printf '  HOME:    %s\n' "$SANDBOX"
printf '  state:   %s\n' "$STATE"
printf '  log:     %s\n' "$LOG"
printf '  restore: %s\n' "$(find "$STATE/backups" -name restore.tsv | sort | tail -n1)"
