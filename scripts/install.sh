#!/usr/bin/env bash
# Non-destructive installer for niri-m3-trackpad.
#
# Default is dry-run. Pass --apply to write files; every overwritten destination
# is copied ONCE into a timestamped state directory and recorded in restore.tsv.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="${INTEGRATED_STATE_DIR:-$HOME/.local/state/integrated-niri-m3}"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
BACKUP="$STATE/backups/$RUN_ID"
RESTORE="$BACKUP/restore.tsv"
LOG="$STATE/install-$RUN_ID.log"
APPLY=0
PROFILES=()
WITH_ELDAN=1
WITH_ASSETS=1
ACTIVATE=1
NIRI_INPUT=1
BOOTSTRAP=1
PYTHON_BIN="$(command -v python3 || true)"

info(){ printf '[INFO] %s\n' "$*"; }
warn(){ printf '[WARN] %s\n' "$*" >&2; }
die(){ printf '[ERROR] %s\n' "$*" >&2; exit 1; }
usage(){
    cat <<'USAGE'
Usage: ./scripts/install.sh [OPTIONS]

  Default is DRY-RUN (prints the plan, writes nothing).
  --apply               Write files, patch Niri input, install the udev rule
                        and enable the gesture service.
  --dry-run             Explicit dry-run (default).
  --all                 All five profiles (adds niri-supporting).
  --profile NAME        Install one profile; repeatable. Names:
                        m3-waybar niri-core niri-theme niri-supporting
                        elan-gesture
  --no-elan             Skip the gesture daemon.
  --assets              Copy wallpapers (default ON).
  --no-assets           Skip wallpapers.
  --activate            Enable services after install (default ON with --apply).
  --no-activate         Do not touch systemd or restart waybar.
  --no-niri-input       Do not patch touchpad{} with clickfinger/drag/drag-lock.
  --no-bootstrap        Do not install the udev uaccess rule.

  Every destination is backed up ONCE to
  ~/.local/state/integrated-niri-m3/backups/<timestamp>/restore.tsv
  (override with INTEGRATED_STATE_DIR). Restore with scripts/restore.sh.

  Run as the ordinary desktop user, never as root.
USAGE
}

while (($#)); do
    case "$1" in
        --apply) APPLY=1 ;;
        --dry-run) APPLY=0 ;;
        --profile) PROFILES+=("${2:?}"); shift ;;
        --all) PROFILES=(m3-waybar niri-core niri-theme niri-supporting elan-gesture) ;;
        --no-elan) WITH_ELDAN=0 ;;
        --assets) WITH_ASSETS=1 ;;
        --no-assets) WITH_ASSETS=0 ;;
        --activate) ACTIVATE=1 ;;
        --no-activate) ACTIVATE=0 ;;
        --no-niri-input) NIRI_INPUT=0 ;;
        --no-bootstrap) BOOTSTRAP=0 ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
    shift
done
((${#PROFILES[@]})) || PROFILES=(m3-waybar niri-core niri-theme elan-gesture)
(( EUID != 0 )) || die "Run as the ordinary desktop user, not root."
[[ -n "$PYTHON_BIN" ]] || die "python3 missing"
command -v rsync >/dev/null || die "rsync missing"

mkdir -p "$STATE"
if (( APPLY )); then
    mkdir -p "$BACKUP"
    : > "$RESTORE"
    exec > >(tee -a "$LOG") 2>&1
fi

# ---------------------------------------------------------------------------
# Backup: record each destination exactly ONCE, before anything overwrites it.
# A set keyed by the destination prevents a later in-place edit (KDL patch,
# matugen append) from replacing the original backup with the new file.
# ---------------------------------------------------------------------------
declare -A BACKED_UP=()
backup_dest(){
    local dest="$1"
    [[ -n "${BACKED_UP[$dest]:-}" ]] && return 0
    local rel="${dest#"$HOME"/}"
    local backup="$BACKUP/$rel"
    if [[ -e "$dest" || -L "$dest" ]]; then
        mkdir -p "$(dirname "$backup")"
        cp -a -- "$dest" "$backup"
        printf '%s\t%s\t%s\n' "$dest" "$backup" "$(stat -c '%F' "$dest")" >> "$RESTORE"
    fi
    BACKED_UP[$dest]=1
}

install_tree(){
    local src="$1" dest="$2" label="$3"
    info "[$label] $src -> $dest"
    (( APPLY )) || return 0
    backup_dest "$dest"
    mkdir -p "$(dirname "$dest")"
    rm -rf -- "$dest"
    cp -a -- "$src" "$dest"
    # Replace literal upstream home paths with this machine's real HOME.
    # Double quotes are intentional: the shell expands $HOME, so config files
    # receive an absolute path rather than a literal "$HOME" that KDL/CSS would
    # never expand.
    if grep -RIl '/home/lancetfish' "$dest" >/dev/null 2>&1; then
        while IFS= read -r f; do
            sed -i "s|/home/lancetfish|$HOME|g" "$f"
        done < <(grep -RIl '/home/lancetfish' "$dest" 2>/dev/null || true)
    fi
}

install_selective(){
    local src="$1" dest="$2" label="$3"
    shift 3
    local name
    info "[$label] selected config directories from $src"
    (( APPLY )) || return 0
    for name in "$@"; do
        [[ -d "$src/$name" || -f "$src/$name" ]] || { warn "missing $src/$name"; continue; }
        install_tree "$src/$name" "$dest/$name" "$label:$name"
    done
}

install_m3(){
    local src="$ROOT/profiles/m3-waybar" dest="$HOME/.config/waybar-m3"
    install_tree "$src" "$dest" m3-waybar
    (( APPLY )) || return 0
    mkdir -p "$HOME/.local/share/fonts/waybar-m3"
    cp -a "$src/fonts/." "$HOME/.local/share/fonts/waybar-m3/"
    command -v fc-cache >/dev/null && fc-cache -f "$HOME/.local/share/fonts/waybar-m3" >/dev/null 2>&1 || true
}

install_niri_core(){
    install_tree "$ROOT/profiles/niri-dotfiles/dotfiles/.config/niri" "$HOME/.config/niri" niri-core
    (( APPLY )) || return 0
    mkdir -p "$HOME/.local/bin"
    install -m 0755 "$ROOT/modules/integrated-waybar" "$HOME/.local/bin/integrated-waybar"
    local kdl="$HOME/.config/niri/config.kdl"

    # Niri does not expand $HOME inside spawn-at-startup argv. Replace the
    # literal with the real path so swaybg finds the wallpaper.
    if grep -qF '"$HOME/Pictures/Wallpapers/' "$kdl"; then
        sed -i "s|\"\$HOME/Pictures/Wallpapers/|\"$HOME/Pictures/Wallpapers/|g" "$kdl"
    fi
    if grep -qF 'spawn-at-startup "waybar"' "$kdl"; then
        sed -i 's|spawn-at-startup "waybar"|spawn-at-startup "integrated-waybar"|' "$kdl"
    fi
}

# Add the libinput settings that back Apple's two-finger right click and
# three-finger drag. Idempotent, validated, and rolled back on failure.
patch_niri_input(){
    local kdl="$1"
    [[ -f "$kdl" ]] || { warn "$kdl missing; skipping touchpad input patch"; return 0; }
    local snapshot="$STATE/niri-input-backup-$RUN_ID.kdl"
    cp -a "$kdl" "$snapshot"
    if ! "$PYTHON_BIN" - "$kdl" <<'PY'
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
        cp -a "$snapshot" "$kdl"
        warn "touchpad patch failed; restored $snapshot"
        return 0
    fi
    if command -v niri >/dev/null 2>&1 && niri validate -c "$kdl" >/dev/null 2>&1; then
        niri msg action load-config-file >/dev/null 2>&1 || true
        info "Niri touchpad config valid and reloaded."
    else
        cp -a "$snapshot" "$kdl"
        warn "niri validate failed; restored $snapshot"
    fi
}

install_niri_theme(){
    install_tree "$ROOT/profiles/niri-dotfiles/dotfiles/.config/matugen" "$HOME/.config/matugen" niri-theme
    (( APPLY )) || return 0
    local cfg="$HOME/.config/matugen/config.toml"
    if ! grep -q '\[templates.waybar_m3\]' "$cfg"; then
        cat "$ROOT/modules/matugen-waybar-m3.toml" >> "$cfg"
    fi
}

install_niri_supporting(){
    install_selective "$ROOT/profiles/niri-dotfiles/dotfiles/.config" "$HOME/.config" niri-supporting \
        fish foot fuzzel mako kitty waypaper swayosd yazi fastfetch btop cava fcitx5 \
        xdg-desktop-portal mpv satty scripts starship.toml mimeapps.list xdg-terminals.list
}

# ---------------------------------------------------------------------------
# Elan gesture profile
# ---------------------------------------------------------------------------
find_wheel(){
    local f
    for f in "$ROOT"/vendor/wheels/*.whl; do
        [[ -f "$f" ]] && { printf '%s' "$f"; return 0; }
    done
    return 1
}

install_elan(){
    local src="$ROOT/profiles/elan-touch" dest="$HOME/.local/share/integrated-niri-m3/elan-touch"
    info "[elan-gesture] $src -> $dest"
    (( APPLY )) || return 0
    install_tree "$src" "$dest" elan-gesture
    mkdir -p "$HOME/.config/elan-gesture" "$HOME/.config/systemd/user" "$HOME/.config/fish/conf.d"
    if [[ ! -f "$HOME/.config/elan-gesture/config.toml" ]]; then
        cp -a "$src/config/examples/apple-trackpad.toml" "$HOME/.config/elan-gesture/config.toml"
    fi
    install -m 0755 "$src/fish/conf.d/elan-gesture.fish" "$HOME/.config/fish/conf.d/elan-gesture.fish"
    # Generate the unit from the pristine template for this exact HOME.
    sed -e "s|/home/lancetfish/code/ThinkPad|$dest|g" \
        -e "s|/home/lancetfish/.config/elan-gesture/config.toml|$HOME/.config/elan-gesture/config.toml|g" \
        "$src/systemd/elan-gesture.service" > "$HOME/.config/systemd/user/elan-gesture.service"

    if [[ ! -x "$dest/.venv/bin/python" ]]; then
        "$PYTHON_BIN" -m venv --system-site-packages "$dest/.venv"
    fi
    local vpy="$dest/.venv/bin/python"
    if ! "$vpy" -c 'import evdev, evdev.ecodes' >/dev/null 2>&1; then
        # Prefer the wheel shipped in this repository (works offline, any
        # Python 3.14 x86_64). Fall back to the pinned download only when the
        # vendored wheel is missing or incompatible.
        local wheel
        if wheel=$(find_wheel); then
            info "Installing bundled wheel: $wheel"
            "$vpy" -m pip install --no-cache-dir --no-index "$wheel" || \
                "$vpy" -m pip install --no-cache-dir --require-hashes -r "$dest/requirements.lock"
        else
            "$vpy" -m pip install --no-cache-dir --require-hashes -r "$dest/requirements.lock"
        fi
        "$vpy" -c 'import evdev, evdev.ecodes' || \
            die "evdev import failed after install; check Python version (needs 3.14 x86_64)"
    fi
}

# One-time privileged stage: give the seat user read access to the Elan pad.
bootstrap_permissions(){
    (( WITH_ELDAN )) || return 0
    local helper="$ROOT/profiles/elan-touch/scripts/bootstrap-permissions.sh"
    local readable=0
    if "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import glob, os
for path in glob.glob("/dev/input/event*"):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        os.close(fd)
        raise SystemExit(0)
    except OSError:
        pass
raise SystemExit(1)
PY
    then
        readable=1
    fi
    if (( readable )); then
        info "An input event node is already readable; skipping udev bootstrap."
        return 0
    fi
    local priv=""
    if command -v pkexec >/dev/null 2>&1; then priv="pkexec"
    elif command -v sudo >/dev/null 2>&1; then priv="sudo"; fi
    if [[ -n "$priv" ]] && "$priv" "$helper" --root-stage; then
        info "uaccess rule installed."
    else
        warn "Could not install the udev rule automatically (no polkit agent / sudo)."
        warn "Run once from a graphical terminal, then restart the service:"
        printf '    sudo %s --root-stage\n' "$helper"
    fi
}

case_profile(){
    case "$1" in
        m3-waybar) install_m3 ;;
        niri-core) install_niri_core ;;
        niri-theme) install_niri_theme ;;
        niri-supporting) install_niri_supporting ;;
        elan-gesture) (( WITH_ELDAN )) && install_elan ;;
        *) die "unknown profile: $1" ;;
    esac
}

info "Mode: $( (( APPLY )) && echo APPLY || echo DRY-RUN )"
info "Profiles: ${PROFILES[*]}"
for profile in "${PROFILES[@]}"; do case_profile "$profile"; done

if (( WITH_ASSETS )); then
    info "[assets] wallpapers and preview pictures"
    if (( APPLY )); then
        mkdir -p "$HOME/Pictures/Wallpapers"
        cp -an "$ROOT/profiles/niri-dotfiles/assets-wallpapers/." "$HOME/Pictures/Wallpapers/" 2>/dev/null || true
    fi
fi

if (( APPLY )) && (( NIRI_INPUT )) && [[ " ${PROFILES[*]} " == *" niri-core "* ]]; then
    patch_niri_input "$HOME/.config/niri/config.kdl"
fi

if (( APPLY )) && (( BOOTSTRAP )); then
    bootstrap_permissions
fi

if (( APPLY )) && (( ACTIVATE )); then
    info "Activating services"
    systemctl --user daemon-reload
    if (( WITH_ELDAN )) && [[ " ${PROFILES[*]} " == *" elan-gesture "* ]]; then
        systemctl --user enable --now elan-gesture.service 2>/dev/null || \
            warn "elan-gesture.service could not start; run: systemctl --user restart elan-gesture.service"
    fi
    if [[ " ${PROFILES[*]} " == *" m3-waybar "* ]] && command -v waybar >/dev/null 2>&1; then
        # Only restart an already-running bar; a fresh session will start it
        # through spawn-at-startup "integrated-waybar".
        if pgrep -x waybar >/dev/null 2>&1; then
            pkill -x waybar 2>/dev/null || true
            nohup "$HOME/.local/bin/integrated-waybar" >/dev/null 2>&1 &
        fi
    fi
fi

if (( APPLY )); then
    info "Backup: $BACKUP"
    info "Restore with: $ROOT/scripts/restore.sh --backup $BACKUP"
    info "Service log: journalctl --user -u elan-gesture.service -f -o cat"
else
    info "Dry run complete. Re-run with --apply to write."
fi
