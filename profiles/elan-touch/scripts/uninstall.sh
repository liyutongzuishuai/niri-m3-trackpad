#!/usr/bin/env bash
# Stop and remove the user-level service. Never modifies Niri/kernel/libinput
# config unless --restore-niri is passed and a backup exists.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(id -un)"
HOME_DIR="$(getent passwd "$USER_NAME" | cut -d: -f6)"
SERVICE="elan-gesture.service"
STATE_DIR="$HOME_DIR/.local/state/elan-gesture"
DBUS_ADDR="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"
PURGE=0
RESTORE_NIRI=0
for arg in "$@"; do
    case "$arg" in
        --purge) PURGE=1 ;;
        --restore-niri) RESTORE_NIRI=1 ;;
        -h|--help)
            cat <<'USAGE'
Usage: ./scripts/uninstall.sh [--purge] [--restore-niri]

  --purge         Also delete .venv, user config, captures, reports and logs.
  --restore-niri  Restore the newest ~/.config/niri/config.kdl backup made by
                  install.sh --niri-input (kept under
                  ~/.local/state/elan-gesture/niri-backup-*.kdl).
USAGE
            exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

say() { printf '\n==> %s\n' "$*"; }
warn() { printf '\n!!  %s\n' "$*" >&2; }
export DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDR"

say "Stopping and disabling user service"
systemctl --user disable --now "$SERVICE" 2>/dev/null || true
rm -f "$HOME_DIR/.config/systemd/user/$SERVICE"
rm -f "$HOME_DIR/.config/systemd/user/graphical-session.target.wants/$SERVICE"
systemctl --user daemon-reload 2>/dev/null || true

say "Removing fish helper and udev rule (if writable)"
rm -f "$HOME_DIR/.config/fish/conf.d/elan-gesture.fish"
if [[ -f /etc/udev/rules.d/72-elan-touchpad-gesture-uaccess.rules ]]; then
    if rm -f /etc/udev/rules.d/72-elan-touchpad-gesture-uaccess.rules 2>/dev/null; then
        udevadm control --reload 2>/dev/null || true
    else
        warn "Run once to remove the udev rule:"
        printf '    sudo rm -f /etc/udev/rules.d/72-elan-touchpad-gesture-uaccess.rules\n'
        printf '    sudo udevadm control --reload\n'
    fi
fi

if [[ "$RESTORE_NIRI" -eq 1 ]]; then
    say "Restoring the newest Niri config backup"
    NEWEST="$(ls -1t "$STATE_DIR"/niri-backup-*.kdl 2>/dev/null | head -n 1 || true)"
    if [[ -n "$NEWEST" ]]; then
        TARGET="$HOME_DIR/.config/niri/config.kdl"
        cp -a "$TARGET" "$TARGET.before-restore" 2>/dev/null || true
        cp -a "$NEWEST" "$TARGET"
        echo "Restored $TARGET from $NEWEST"
        if command -v niri >/dev/null 2>&1 && niri validate -c "$TARGET" >/dev/null 2>&1; then
            niri msg action load-config-file >/dev/null 2>&1 || true
            echo "Niri config valid and reloaded."
        else
            warn "Restored file did not validate; previous file kept at $TARGET.before-restore"
        fi
    else
        warn "No niri-backup-*.kdl found under $STATE_DIR; nothing restored."
    fi
else
    say "Niri input config untouched (pass --restore-niri to revert the click-method/drag patch)"
fi

if [[ "$PURGE" -eq 1 ]]; then
    say "Purging venv, user config, captures, reports and logs"
    rm -rf "$ROOT/.venv" "$ROOT/logs" "$ROOT/docs/captures"
    rm -rf "$HOME_DIR/.config/elan-gesture"
else
    say "Preserved user config, captures and test report"
fi
say "Uninstall complete"
printf 'Remaining project source: %s\n' "$ROOT"
