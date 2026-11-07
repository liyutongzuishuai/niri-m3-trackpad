# elan-gesture fish helpers. Sourced automatically by fish; does not modify config.fish.
set -gx ELAN_GESTURE_ROOT $HOME/.local/share/integrated-niri-m3/elan-touch
set -gx ELAN_GESTURE_PYTHON $ELAN_GESTURE_ROOT/.venv/bin/python
set -gx ELAN_GESTURE_SRC $ELAN_GESTURE_ROOT/src

function elan-gesture-monitor --description 'Read-only live gesture monitor (never runs actions)'
    env PYTHONPATH=$ELAN_GESTURE_SRC $ELAN_GESTURE_PYTHON -m elan_gesture monitor $argv
end

function elan-gesture-probe --description 'Print Elan touchpad capability report'
    env PYTHONPATH=$ELAN_GESTURE_SRC $ELAN_GESTURE_PYTHON -m elan_gesture probe $argv
end

function elan-gesture-replay --description 'Replay a JSONL capture through the detector'
    env PYTHONPATH=$ELAN_GESTURE_SRC $ELAN_GESTURE_PYTHON -m elan_gesture replay $argv
end

function elan-gesture-log --description 'Follow elan-gesture user service journal'
    journalctl --user -u elan-gesture.service -f -o cat $argv
end

function elan-gesture-status --description 'Show elan-gesture user service status'
    systemctl --user status elan-gesture.service $argv
end

function elan-gesture-restart --description 'Restart elan-gesture user service'
    systemctl --user restart elan-gesture.service $argv
end

function elan-gesture-gestures --description 'Print the effective gesture table (provider + action)'
    env PYTHONPATH=$ELAN_GESTURE_SRC $ELAN_GESTURE_PYTHON -m elan_gesture gestures $argv
end

function elan-gesture-lookup --description 'Look up the current selection (Apple three-finger tap action)'
    env PYTHONPATH=$ELAN_GESTURE_SRC $ELAN_GESTURE_PYTHON -m elan_gesture.lookup $argv
end

function elan-gesture-inject-test --description 'Diagnose the injection backend; --yes to actually inject'
    env PYTHONPATH=$ELAN_GESTURE_SRC $ELAN_GESTURE_PYTHON -m elan_gesture inject-test $argv
end
