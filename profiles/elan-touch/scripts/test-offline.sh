#!/usr/bin/env bash
# Run every offline verification against the production Python code.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${INTEGRATED_PYTHON:-$ROOT/.venv/bin/python}"
# A profile checked out standalone has no .venv; prefer the repository-root venv
# (created by scripts/verify.sh) which already contains the pinned evdev module.
if [[ ! -x "$PY" ]]; then
    REPO_ROOT="$(cd "$ROOT/../.." && pwd)"
    if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
        PY="$REPO_ROOT/.venv/bin/python"
    else
        PY="$(command -v python3)"
    fi
fi
export PYTHONPATH="$ROOT/src"

printf '\n==> compileall\n'
"$PY" -m compileall -q "$ROOT/src" "$ROOT/tests"

printf '\n==> shell / fish / systemd syntax\n'
bash -n "$ROOT/scripts/install.sh" "$ROOT/scripts/uninstall.sh" \
    "$ROOT/scripts/bootstrap-permissions.sh" "$ROOT/scripts/test-offline.sh"
fish -n "$ROOT/fish/conf.d/elan-gesture.fish"
systemd-analyze --user verify "$ROOT/systemd/elan-gesture.service"

printf '\n==> configs\n'
"$PY" - "$ROOT" <<'PY'
import sys
from elan_gesture.config import load_config
root = sys.argv[1]
for p in ("config/default.toml", "config/examples/four-directions.toml",
          "config/examples/apple-trackpad.toml"):
    c = load_config(root + "/" + p)
    enabled = sorted(n for n, g in c.gestures.items() if g.enabled)
    print("config OK", p, "trigger_on=" + c.gesture.trigger_on,
          "gestures=" + (",".join(enabled) or "-"))
PY

printf '\n==> regenerate fixtures\n'
"$PY" "$ROOT/tests/synthetic.py"

printf '\n==> unittest\n'
"$PY" -m unittest discover -s "$ROOT/tests" -p 'test_*.py' -v

printf '\n==> touchviz decoder tests\n'
"$PY" "$ROOT/touchviz/test_touchviz.py" -v

printf '\n==> gesture expectations (apple profile)\n'
"$PY" - "$ROOT" <<'PY'
import sys
root = sys.argv[1]
sys.path.insert(0, root + "/src")
sys.path.insert(0, root + "/tests")
from helpers import apple_config, fired_gestures, run_fixture

EXPECT = {
    "gesture_three_finger_tap": ["three_finger_tap"],
    "false_three_finger_tap_moved": [],
    "false_three_finger_hold": [],
    "false_two_finger_tap": [],
    "gesture_four_swipe_left": ["four_finger_left"],
    "gesture_four_swipe_right": ["four_finger_right"],
    "gesture_four_swipe_down": ["four_finger_down"],
    "gesture_four_swipe_up": [],
    "false_four_swipe_short": [],
    "gesture_thumb_spread_open": ["thumb_spread_open"],
    "gesture_thumb_pinch": ["thumb_spread_pinch"],
    "false_four_translate_not_spread": [],
    "gesture_edge_swipe_right": ["two_finger_edge_left"],
    "false_edge_swipe_middle": [],
    "false_two_finger_scroll": [],
}
config = apple_config()
failures = []
for name, expected in EXPECT.items():
    summary, _ = run_fixture(name, config)
    actual = fired_gestures(summary)
    ok = actual == expected
    print(f"{'PASS' if ok else 'FAIL'} {name:34s} expected={expected or '[]'} actual={actual or '[]'}")
    if not ok:
        failures.append(name)
raise SystemExit(1 if failures else 0)
PY

printf '\n==> legacy asymmetric matrix (default profile)\n'
"$PY" - "$ROOT" <<'PY'
import sys
root = sys.argv[1]
sys.path.insert(0, root + "/src")
sys.path.insert(0, root + "/tests")
from helpers import fired_gestures, run_fixture

EXPECT = {
    "gesture_up": ["up"], "gesture_down": ["down"],
    "gesture_left": ["left"], "gesture_right": ["right"],
    "gesture_fast_up": ["up"],
    "gesture_continuous": ["up", "down", "left", "right"],
    "repeat_gestures": ["up", "up"],
    "false_two_finger_scroll": [],
    "false_three_finger_swipe": [],
    "false_four_finger": [],
    "false_static_drift": [],
    "false_short_move": [],
    "false_diagonal": [],
    "false_tracking_id_change": [],
    "false_syn_dropped": [],
}
failures = []
for name, expected in EXPECT.items():
    summary, _ = run_fixture(name)
    actual = fired_gestures(summary)
    ok = actual == expected
    print(f"{'PASS' if ok else 'FAIL'} {name:34s} expected={expected or '[]'} actual={actual or '[]'}")
    if not ok:
        failures.append(name)
raise SystemExit(1 if failures else 0)
PY

printf '\n==> CLI smoke\n'
APPLE_CONFIG="$ROOT/config/examples/apple-trackpad.toml"
"$PY" -m elan_gesture --config "$APPLE_CONFIG" gestures >/dev/null
echo "gestures OK"
"$PY" -m elan_gesture --config "$APPLE_CONFIG" replay \
    --in "$ROOT/tests/fixtures/gesture_three_finger_tap.jsonl" --format json >/dev/null 2>&1
echo "replay OK"
"$PY" -m elan_gesture inject-test --keys ctrl c >/dev/null
echo "inject-test (dry) OK"
"$PY" -m elan_gesture.lookup --print-only --no-inject >/dev/null
echo "lookup (print-only) OK"

printf '\n==> read-only hardware probe\n'
"$PY" -m elan_gesture probe > "$ROOT/docs/probe.json"
"$PY" - "$ROOT" <<'PY'
import json, sys
r = json.load(open(sys.argv[1] + "/docs/probe.json"))
b = r.get("borrowed_ioctl_probe") or r
print("probe OK", b.get("name"), "type_b_mt=", b.get("type_b_mt"))
print("direct_open_error=", r.get("direct_open_error", "none"))
print("inject=", r.get("inject"))
PY

printf '\n==> Niri IPC read-only handshake\n'
niri msg --json version
printf '\nAll offline checks passed.\n'
