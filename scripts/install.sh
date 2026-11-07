#!/usr/bin/env bash
# Non-destructive installer for integrated-niri-m3.
#
# Default is dry-run. Pass --apply to write files; every overwritten destination
# is copied into a timestamped state directory and recorded in a restore manifest.
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
WITH_ASSETS=0
ACTIVATE=0

info(){ printf '[INFO] %s\n' "$*"; }
warn(){ printf '[WARN] %s\n' "$*" >&2; }
die(){ printf '[ERROR] %s\n' "$*" >&2; exit 1; }
usage(){ sed -n '2,26p' "$0"; }

while (($#)); do
    case "$1" in
        --apply) APPLY=1 ;;
        --dry-run) APPLY=0 ;;
        --profile) PROFILES+=("${2:?}"); shift ;;
        --all) PROFILES=(m3-waybar niri-core niri-theme niri-supporting elan-gesture) ;;
        --no-elan) WITH_ELDAN=0 ;;
        --assets) WITH_ASSETS=1 ;;
        --activate) ACTIVATE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
    shift
done
((${#PROFILES[@]})) || PROFILES=(m3-waybar niri-core niri-theme elan-gesture)
(( EUID != 0 )) || die "Run as the ordinary desktop user, not root."
command -v python3 >/dev/null || die "python3 missing"
command -v rsync >/dev/null || die "rsync missing"

mkdir -p "$STATE"
if (( APPLY )); then
    mkdir -p "$BACKUP"
    : > "$RESTORE"
    exec > >(tee -a "$LOG") 2>&1
fi

backup_dest(){
    local dest="$1"
    local rel="${dest#"$HOME"/}"
    local backup="$BACKUP/$rel"
    [[ -e "$dest" || -L "$dest" ]] || return 0
    mkdir -p "$(dirname "$backup")"
    cp -a -- "$dest" "$backup"
    printf '%s\t%s\t%s\n' "$dest" "$backup" "$(stat -c '%F' "$dest")" >> "$RESTORE"
}

install_tree(){
    local src="$1" dest="$2" label="$3"
    info "[$label] $src -> $dest"
    (( APPLY )) || return 0
    backup_dest "$dest"
    mkdir -p "$(dirname "$dest")"
    rm -rf -- "$dest"
    cp -a -- "$src" "$dest"
    # Normalize upstream hard-coded home path to this machine's HOME.
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
        [[ -d "$src/$name" ]] || { warn "missing $src/$name"; continue; }
        install_tree "$src/$name" "$dest/$name" "$label:$name"
    done
}

install_m3(){
    local src="$ROOT/profiles/m3-waybar" dest="$HOME/.config/waybar-m3"
    install_tree "$src" "$dest" m3-waybar
    (( APPLY )) || return 0
    # Local fonts are installed user-only, never system-wide.
    mkdir -p "$HOME/.local/share/fonts/waybar-m3"
    cp -a "$src/fonts/." "$HOME/.local/share/fonts/waybar-m3/"
    command -v fc-cache >/dev/null && fc-cache -f "$HOME/.local/share/fonts/waybar-m3" >/dev/null 2>&1 || true
}

install_niri_core(){
    install_tree "$ROOT/profiles/niri-dotfiles/dotfiles/.config/niri" "$HOME/.config/niri" niri-core
    (( APPLY )) || return 0
    # Install the Waybar launcher and patch only the exact old startup line.
    mkdir -p "$HOME/.local/bin"
    install -m 0755 "$ROOT/modules/integrated-waybar" "$HOME/.local/bin/integrated-waybar"
    local kdl="$HOME/.config/niri/config.kdl"
    if grep -qF 'spawn-at-startup "waybar"' "$kdl"; then
        backup_dest "$kdl"
        sed -i 's|spawn-at-startup "waybar"|spawn-at-startup "integrated-waybar"|' "$kdl"
    fi
}

install_niri_theme(){
    install_tree "$ROOT/profiles/niri-dotfiles/dotfiles/.config/matugen" "$HOME/.config/matugen" niri-theme
    (( APPLY )) || return 0
    local cfg="$HOME/.config/matugen/config.toml"
    if ! grep -q '\[templates.waybar_m3\]' "$cfg"; then
        backup_dest "$cfg"
        cat "$ROOT/modules/matugen-waybar-m3.toml" >> "$cfg"
    fi
}

install_niri_supporting(){
    install_selective "$ROOT/profiles/niri-dotfiles/dotfiles/.config" "$HOME/.config" niri-supporting \
        fish foot fuzzel mako kitty waypaper swayosd yazi fastfetch btop cava fcitx5 \
        xdg-desktop-portal mpv satty scripts starship.toml mimeapps.list xdg-terminals.list
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
    # Do not sed the snapshot itself: repeated installs would otherwise compound paths.
    sed -e "s|/home/lancetfish/code/ThinkPad|$dest|g" \
        -e "s|/home/lancetfish/.config/elan-gesture/config.toml|$HOME/.config/elan-gesture/config.toml|g" \
        "$src/systemd/elan-gesture.service" > "$HOME/.config/systemd/user/elan-gesture.service"
    if [[ ! -x "$dest/.venv/bin/python" ]]; then
        python3 -m venv --system-site-packages "$dest/.venv"
        # Prefer an offline copy of the already-verified evdev module; fall back
        # to the pinned wheel only when the local copy is unavailable.
        local donor="$ROOT/.venv/lib/python3.14/site-packages/evdev"
        local donor_dist="$ROOT/.venv/lib/python3.14/site-packages/evdev_binary-2.0.0.dist-info"
        local target_site
        target_site="$("$dest/.venv/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
        if [[ -d "$donor" && -d "$donor_dist" ]]; then
            mkdir -p "$target_site"
            cp -a "$donor" "$target_site/"
            cp -a "$donor_dist" "$target_site/"
        else
            "$dest/.venv/bin/python" -m pip install --no-cache-dir --require-hashes -r "$dest/requirements.lock"
        fi
        "$dest/.venv/bin/python" -c 'import evdev, evdev.ecodes' || \
            "$dest/.venv/bin/python" -m pip install --no-cache-dir --require-hashes -r "$dest/requirements.lock"
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

if (( ACTIVATE )); then
    if (( APPLY )); then
        "$ROOT/scripts/activate.sh" --apply
    else
        info "[dry-run] would call scripts/activate.sh --apply"
    fi
fi

if (( APPLY )); then
    info "Backup: $BACKUP"
    info "Restore with: $ROOT/scripts/restore.sh --backup $BACKUP"
else
    info "Dry run complete. Re-run with --apply to write."
fi
