#!/usr/bin/env bash
# Install elan-gesture for the current user. Never converts the daemon to root.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(id -un)"
HOME_DIR="$(getent passwd "$USER_NAME" | cut -d: -f6)"
CONFIG_DIR="$HOME_DIR/.config/elan-gesture"
SYSTEMD_DIR="$HOME_DIR/.config/systemd/user"
FISH_DIR="$HOME_DIR/.config/fish/conf.d"
STATE_DIR="$HOME_DIR/.local/state/elan-gesture"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
SERVICE="elan-gesture.service"
NIRI_CONFIG="$HOME_DIR/.config/niri/config.kdl"
NIRI_INPUT=0
DBUS_ADDR="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

for arg in "$@"; do
    case "$arg" in
        --niri-input) NIRI_INPUT=1 ;;
        -h|--help)
            cat <<'USAGE'
Usage: ./scripts/install.sh [--niri-input]

  --niri-input   Also patch ~/.config/niri/config.kdl touchpad{} with
                 click-method "clickfinger" (two-finger right click), drag and
                 drag-lock (tap-and-drag). The file is backed up first and the
                 patch is reverted automatically if `niri validate` fails.
USAGE
            exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

say() { printf '\n==> %s\n' "$*"; }
warn() { printf '\n!!  %s\n' "$*" >&2; }

if [[ "$EUID" -eq 0 ]]; then
    echo "Run install.sh as your ordinary desktop user, not root." >&2
    exit 2
fi

say "Creating Python virtual environment and installing pinned dependency"
if [[ ! -x "$PY" ]]; then
    python3 -m venv --system-site-packages "$VENV"
fi
REPO_ROOT="$(cd "$ROOT/../.." && pwd)"
WHEEL="$(ls "$REPO_ROOT"/vendor/wheels/*.whl 2>/dev/null | head -1 || true)"
if [[ -n "$WHEEL" && -f "$WHEEL" ]]; then
    "$PY" -m pip install --no-cache-dir --no-index "$WHEEL" || \
        "$PY" -m pip install --no-cache-dir --require-hashes -r "$ROOT/requirements.lock"
else
    "$PY" -m pip install --no-cache-dir --require-hashes -r "$ROOT/requirements.lock"
fi

say "Installing user configuration (existing config is preserved)"
mkdir -p "$CONFIG_DIR" "$SYSTEMD_DIR" "$FISH_DIR" "$STATE_DIR" "$ROOT/docs/captures" "$ROOT/logs"
if [[ ! -f "$CONFIG_DIR/config.toml" ]]; then
    cp "$ROOT/config/examples/apple-trackpad.toml" "$CONFIG_DIR/config.toml"
    echo "Wrote $CONFIG_DIR/config.toml (Apple trackpad mapping)"
else
    echo "Preserved $CONFIG_DIR/config.toml"
fi

say "Installing fish helpers and systemd user unit"
install -m 0644 "$ROOT/fish/conf.d/elan-gesture.fish" "$FISH_DIR/elan-gesture.fish"
sed -e "s|/home/lancetfish/code/ThinkPad|$ROOT|g" \
    -e "s|/home/lancetfish/.config/elan-gesture/config.toml|$CONFIG_DIR/config.toml|g" \
    "$ROOT/systemd/$SERVICE" > "$SYSTEMD_DIR/$SERVICE"
export DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDR"
systemctl --user daemon-reload
systemd-analyze --user verify "$SYSTEMD_DIR/$SERVICE"

say "Checking the optional injection backend"
INJECT_OK=0
if "$PY" - "$ROOT" <<'PY'
import json, os, subprocess, sys
root = sys.argv[1]
env = dict(os.environ, PYTHONPATH=os.path.join(root, "src"))
out = subprocess.run([os.path.join(root, ".venv/bin/python"), "-m", "elan_gesture",
                      "inject-test"], env=env, capture_output=True, text=True)
try:
    report = json.loads(out.stdout)
except json.JSONDecodeError:
    print("inject backend: unknown (" + (out.stderr.strip().splitlines() or [""])[-1] + ")")
    raise SystemExit(1)
print(f"ydotool={report['ydotool']} socket_present={report['available']} "
      f"wheel={report['wheel_available']}")
raise SystemExit(0 if (report["available"] or report["wheel_available"]) else 1)
PY
then
    INJECT_OK=1
    echo "Injection backend available (keys via ydotool, wheel via UInput)."
else
    warn "No injection backend. Gestures that need it will fail at runtime:"
    warn "  three_finger_tap with type=\"command\" is unaffected; type=\"inject\" is not."
    warn "  Start it once per session with: niri config -> spawn-at-startup \"ydotoold\""
fi

say "Checking the M3 notification centre"
if "$PY" - <<'PY'
import sys
from elan_gesture.niri_dynamic import control_center_command
argv = control_center_command()
print("control centre:" + (" ".join(argv) if argv else "not found"))
raise SystemExit(0 if argv else 1)
PY
then
    echo "Gesture will reuse the same command as waybar's tune button."
else
    warn "control.sh not found in any waybar config; two_finger_edge_left will"
    warn "fall back to swaync, then to a plain notification."
fi

if [[ "$NIRI_INPUT" -eq 1 ]]; then
    say "Patching Niri touchpad input (click-method / drag / drag-lock)"
    if [[ ! -f "$NIRI_CONFIG" ]]; then
        warn "$NIRI_CONFIG not found; skipping Niri input patch"
    else
        BACKUP="$STATE_DIR/niri-backup-$(date +%Y%m%d_%H%M%S).kdl"
        cp -a "$NIRI_CONFIG" "$BACKUP"
        echo "Backup: $BACKUP"
        if "$PY" - "$NIRI_CONFIG" <<'PY'
import re, sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
wanted = ['click-method "clickfinger"', "drag true", "drag-lock"]
match = re.search(r"^(\s*)touchpad\s*\{", text, re.MULTILINE)
if not match:
    print("no touchpad{} block; nothing to do")
    raise SystemExit(0)
indent = match.group(1) + "    "
start = match.end()
depth = 1
index = start
while index < len(text) and depth:
    if text[index] == "{":
        depth += 1
    elif text[index] == "}":
        depth -= 1
    index += 1
block = text[start:index]
missing = [line for line in wanted
           if not re.search(r"^\s*" + re.escape(line.split()[0]) + r"\b",
                            block, re.MULTILINE)]
if not missing:
    print("touchpad{} already has click-method/drag/drag-lock")
    raise SystemExit(0)
addition = "".join(f"{indent}{line}\n" for line in missing)
stripped = block.rstrip()
close = stripped.rfind("}")
if close < 0:
    print("touchpad{} block has no closing brace")
    raise SystemExit(1)
body = stripped[:close].rstrip()
new_block = body + "\n" + addition + match.group(1) + "}" + stripped[close + 1:]
path.write_text(text[:start] + new_block + text[index:])
print("added: " + ", ".join(missing))
PY
        then
            if niri validate -c "$NIRI_CONFIG" >/dev/null 2>&1; then
                niri msg action load-config-file >/dev/null 2>&1 || true
                echo "Niri config valid and reloaded."
            else
                cp -a "$BACKUP" "$NIRI_CONFIG"
                warn "niri validate failed; restored $BACKUP"
            fi
        else
            cp -a "$BACKUP" "$NIRI_CONFIG"
            warn "patching failed; restored $BACKUP"
        fi
    fi
fi

say "Checking touchpad read access for $USER_NAME"
ACCESS_OK=0
if "$PY" - <<'PY'
import os
p = "/dev/input/event11"
fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
os.close(fd)
print("read-only open OK")
PY
then
    ACCESS_OK=1
    echo "Touchpad is already readable by the ordinary user."
else
    warn "Touchpad is not readable yet. Attempting one-time uaccess authorization."
    PRIV=""
    if command -v pkexec >/dev/null 2>&1; then
        PRIV="pkexec"
    elif command -v sudo >/dev/null 2>&1; then
        PRIV="sudo"
    fi
    if [[ -n "$PRIV" ]] && "$PRIV" "$ROOT/scripts/bootstrap-permissions.sh" --root-stage; then
        if "$PY" - <<'PY'
import os
fd = os.open("/dev/input/event11", os.O_RDONLY | os.O_NONBLOCK)
os.close(fd)
print("read-only open OK after uaccess")
PY
        then
            ACCESS_OK=1
        fi
    else
        warn "Privileged authorization did not complete in this non-interactive shell."
        warn "Run this once from a graphical terminal, then re-run install.sh:"
        printf '    sudo %s/scripts/bootstrap-permissions.sh --root-stage\n' "$ROOT"
        printf '    # or: pkexec %s/scripts/bootstrap-permissions.sh --root-stage\n' "$ROOT"
    fi
fi

say "Enabling graphical-session user service"
systemctl --user enable --now "$SERVICE" || {
    warn "Service could not start (usually because the touchpad ACL is still missing)."
    warn "After completing the authorization command above: systemctl --user restart $SERVICE"
}

say "Effective gesture table"
PYTHONPATH="$ROOT/src" "$PY" -m elan_gesture --config "$CONFIG_DIR/config.toml" gestures || true

say "Post-install checks"
systemctl --user --no-pager status "$SERVICE" || true
journalctl --user -u "$SERVICE" -n 12 --no-pager -o cat || true
printf '\nAccess status: %s\n' "$([[ "$ACCESS_OK" -eq 1 ]] && echo READY || echo NEEDS_ONE_TIME_AUTHORIZATION)"
printf 'Injection backend: %s\n' "$([[ "$INJECT_OK" -eq 1 ]] && echo READY || echo DEGRADED)"
printf 'Read-only monitor: %s -m elan_gesture monitor\n' "$PY"
printf 'Hardware probe:    %s -m elan_gesture probe\n' "$PY"
printf 'Gesture table:     %s -m elan_gesture gestures\n' "$PY"
printf 'Service logs:      journalctl --user -u %s -f -o cat\n' "$SERVICE"
