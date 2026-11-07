#!/usr/bin/env bash
# Fedora 44's gtk4-layer-shell needs to precede libwayland-client in link order.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAYER_LIB="${TOUCHVIZ_LAYER_LIB:-/lib64/libgtk4-layer-shell.so.0}"
if [[ -r "$LAYER_LIB" ]] && [[ -z "${LD_PRELOAD:-}" ]]; then
    export LD_PRELOAD="$LAYER_LIB${LD_PRELOAD:+:$LD_PRELOAD}"
fi
exec "$ROOT/.venv/bin/python" "$ROOT/touchviz/touchviz.py" "$@"
