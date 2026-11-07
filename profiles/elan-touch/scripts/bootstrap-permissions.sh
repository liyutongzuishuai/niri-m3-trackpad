#!/usr/bin/env bash
# One-time privileged stage: install one uaccess rule for the Elan Touchpad.
# This script itself must run as root; install.sh invokes it via pkexec/sudo.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RULE_SRC="$ROOT/72-elan-touchpad-gesture-uaccess.rules"
RULE_DST="/etc/udev/rules.d/72-elan-touchpad-gesture-uaccess.rules"
OLD_RULE="/etc/udev/rules.d/99-elan-touchpad-gesture-uaccess.rules"
DEVPATH="/sys/devices/pci0000:00/0000:00:1f.4/i2c-7/7-0015/input/input17/event11"

if [[ "${1:-}" != "--root-stage" ]]; then
    echo "This helper is only called by install.sh --root-stage" >&2
    exit 2
fi
if [[ "$EUID" -ne 0 ]]; then
    echo "Root privileges are required for this stage" >&2
    exit 1
fi

# Remove the earlier 99- filename: it sorted after 73-seat-late.rules, so the
# uaccess builtin had already run and no ACL was applied.
rm -f "$OLD_RULE"
install -m 0644 "$RULE_SRC" "$RULE_DST"
udevadm control --reload

# This systemd-udev version uses a positional DEVPATH; also fall back to a
# device-name match for portability.
if [[ -e "$DEVPATH" ]]; then
    udevadm trigger --action=change "$DEVPATH"
else
    udevadm trigger --action=change --name-match=input/event11
fi

# Wait briefly for the uaccess ACL to materialize.
TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || echo lancetfish)}"
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if getfacl -p /dev/input/event11 2>/dev/null | grep -q "user:${TARGET_USER}:rw-"; then
        break
    fi
    sleep 0.2
done
echo "Installed $RULE_DST"
getfacl -p /dev/input/event11 2>/dev/null || true
if ! getfacl -p /dev/input/event11 2>/dev/null | grep -q "user:${TARGET_USER}:rw-"; then
    echo "WARNING: uaccess ACL not visible yet. Re-login, replug the touchpad, or reboot once." >&2
    echo "Check: udevadm test --action=change $DEVPATH" >&2
fi
