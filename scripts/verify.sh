#!/usr/bin/env bash
# One-shot validation of the integrated project. Safe: no ~/.config writes.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${INTEGRATED_PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
    python3 -m venv --system-site-packages "$ROOT/.venv"
    "$PY" -m pip install --no-cache-dir --require-hashes -r "$ROOT/profiles/elan-touch/requirements.lock"
fi
OUT="$ROOT/docs/validation-report.md"
CHECK_LOG="$ROOT/.sandbox/validation-check.log"
mkdir -p "$ROOT/docs" "$ROOT/.sandbox"
PASS=0; FAIL=0
check(){ local name="$1"; shift; if "$@" >"$CHECK_LOG" 2>&1; then printf 'PASS  %s\n' "$name"; PASS=$((PASS+1)); else printf 'FAIL  %s\n' "$name"; sed -n '1,20p' "$CHECK_LOG"; FAIL=$((FAIL+1)); fi; }
info(){ printf '\n==> %s\n' "$*"; }

info "Manifest / configs"
check "manifest.toml parses" "$PY" -c "import tomllib;tomllib.load(open('$ROOT/manifest.toml','rb'))"
check "waybar config JSONC parses" "$PY" "$ROOT/tools/validate.py" --jsonc "$ROOT/profiles/m3-waybar/config.jsonc"
check "elan default TOML parses" "$PY" -c "import tomllib;tomllib.load(open('$ROOT/profiles/elan-touch/config/default.toml','rb'))"
check "elan example TOML parses" "$PY" -c "import tomllib;tomllib.load(open('$ROOT/profiles/elan-touch/config/examples/four-directions.toml','rb'))"
check "matugen config TOML parses" "$PY" -c "import tomllib;tomllib.load(open('$ROOT/profiles/niri-dotfiles/dotfiles/.config/matugen/config.toml','rb'))"

info "Shell / fish / Python syntax"
while IFS= read -r f; do
    [[ "$f" == *.sh || ( "$f" != *.* && -x "$f" ) ]] || continue
    check "bash -n ${f#$ROOT/}" bash -n "$f"
done < <(find "$ROOT/scripts" "$ROOT/modules" -maxdepth 1 -type f -print | sort)
while IFS= read -r f; do check "fish -n ${f#$ROOT/}" fish -n "$f"; done < <(find "$ROOT/profiles/elan-touch/fish" -type f -name '*.fish' -print | sort)
check "python compileall (elan + touchviz)" "$PY" -m compileall -q "$ROOT/profiles/elan-touch/src" "$ROOT/profiles/elan-touch/touchviz" "$ROOT/tools"
check "upstream waybar scripts bash -n" bash -c 'for f in "$0"/profiles/m3-waybar/scripts/*.sh; do bash -n "$f" || exit 1; done' "$ROOT"
check "upstream waybar python compile" "$PY" -m py_compile "$ROOT/profiles/m3-waybar/scripts/controlcenter.py"

info "Profile consistency"
check "integrated profile validator" "$PY" "$ROOT/tools/validate.py" --all "$ROOT"
check "hard-coded home audit" "$PY" "$ROOT/tools/validate.py" --no-hardcoded-home "$ROOT"
check "waybar CSS role references" "$PY" "$ROOT/tools/validate.py" --css-roles "$ROOT/profiles/m3-waybar/style.css" "$ROOT/profiles/m3-waybar/colors.css"
check "Niri startup snippet present" grep -q 'integrated-waybar' "$ROOT/modules/niri-startup.kdl"
check "manifest profile sources exist" "$PY" "$ROOT/tools/validate.py" --sources "$ROOT"

info "Elan offline unit tests"
check "elan unittest" env PYTHONPATH="$ROOT/profiles/elan-touch/src" "$PY" -m unittest discover -s "$ROOT/profiles/elan-touch/tests" -p 'test_*.py'
check "touchviz unittest" "$PY" "$ROOT/profiles/elan-touch/touchviz/test_touchviz.py"

info "Runtime environment (non-fatal if tool missing)"
for c in niri waybar fuzzel mako matugen fcitx5 swaybg brightnessctl pactl nmcli jq python3 fish; do
    if command -v "$c" >/dev/null 2>&1; then printf 'OK    command %s -> %s\n' "$c" "$(command -v "$c")"; else printf 'WARN  missing optional command %s\n' "$c"; fi
done
if command -v niri >/dev/null 2>&1 && [[ -n "${NIRI_SOCKET:-}" ]]; then
    check "Niri IPC version" niri msg --json version
fi

{
  echo "# Integrated Niri M3 validation report"
  echo
  echo "- Generated: $(date --iso-8601=seconds)"
  echo "- Root: $ROOT"
  echo "- PASS: $PASS"
  echo "- FAIL: $FAIL"
  echo
  echo "See terminal output and $ROOT/docs/validation.log for details."
} > "$OUT"
printf '\nSummary: PASS=%d FAIL=%d report=%s\n' "$PASS" "$FAIL" "$OUT"
(( FAIL == 0 ))
