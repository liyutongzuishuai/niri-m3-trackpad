#!/usr/bin/env bash
# Activate the integrated session without reinstalling files.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPLY=0
RESTART_WAYBAR=1
RESTART_ELAN=1
for arg in "$@"; do
    case "$arg" in
        --apply) APPLY=1 ;;
        --dry-run) APPLY=0 ;;
        --no-waybar) RESTART_WAYBAR=0 ;;
        --no-elan) RESTART_ELAN=0 ;;
        -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
        *) printf 'unknown option %s\n' "$arg" >&2; exit 2 ;;
    esac
done
info(){ printf '[INFO] %s\n' "$*"; }
warn(){ printf '[WARN] %s\n' "$*" >&2; }
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

info "Mode: $( (( APPLY )) && echo APPLY || echo DRY-RUN )"
if (( RESTART_WAYBAR )); then
    info "Waybar: integrated-waybar -> ~/.config/waybar-m3/config.jsonc"
    if (( APPLY )); then
        pkill -x waybar 2>/dev/null || true
        nohup "$HOME/.local/bin/integrated-waybar" >/dev/null 2>&1 &
    fi
fi
if (( RESTART_ELAN )); then
    info "Elan gesture: systemctl --user restart elan-gesture.service"
    if (( APPLY )); then
        systemctl --user daemon-reload
        systemctl --user enable --now elan-gesture.service
        systemctl --user restart elan-gesture.service
    fi
fi
if (( APPLY )); then
    if command -v niri >/dev/null && [[ -n "${NIRI_SOCKET:-}" ]]; then
        info "Niri IPC version: $(niri msg --json version)"
    else
        warn "NIRI_SOCKET not present; start this from inside the Niri session."
    fi
    info "Waybar log: journalctl --user -u niri.service -f | grep -i waybar"
    info "Elan log:   journalctl --user -u elan-gesture.service -f -o cat"
else
    info "No process was restarted. Re-run with --apply."
fi
