#!/usr/bin/env bash
# Restore files backed up by install.sh from one run.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Resolve the state directory with the exact same rule as install.sh: an
# explicit INTEGRATED_STATE_DIR (used by the sandbox installer) wins over the
# default. This keeps "--latest" able to find backups that install.sh wrote
# outside $HOME.
STATE="${INTEGRATED_STATE_DIR:-$HOME/.local/state/integrated-niri-m3}"
BACKUP=""
APPLY=0
usage(){
    cat <<'USAGE'
Usage: ./scripts/restore.sh [OPTIONS]

  --backup DIR   Restore from one specific backup directory (must contain
                 restore.tsv as written by install.sh).
  --latest       Use the newest backup directory under
                 ${INTEGRATED_STATE_DIR:-~/.local/state/integrated-niri-m3}/backups
  --apply        Actually copy the files back (default is a dry-run plan).
  -h, --help     Show this help.

  restore.tsv lines are "<destination>\t<backup>\t<type>"; each destination is
  copied back with "cp -a", so a dry run only prints the plan.
USAGE
}
while (($#)); do
    case "$1" in
        --backup) BACKUP="${2:?}"; shift ;;
        --latest)
            if [[ ! -d "$STATE/backups" ]]; then
                printf '[ERROR] no backup directory: %s\n' "$STATE/backups" >&2
                exit 1
            fi
            BACKUP="$(find "$STATE/backups" -mindepth 1 -maxdepth 1 -type d | sort | tail -n1)"
            if [[ -z "$BACKUP" ]]; then
                printf '[ERROR] no backups in: %s\n' "$STATE/backups" >&2
                exit 1
            fi
            ;;
        --apply) APPLY=1 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'unknown option %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done
[[ -n "$BACKUP" && -f "$BACKUP/restore.tsv" ]] || { echo "valid --backup DIR required" >&2; exit 2; }
info(){ printf '[INFO] %s\n' "$*"; }
info "Restore plan from $BACKUP"
while IFS=$'\t' read -r dest backup typ; do
    printf '  %s <- %s\n' "$dest" "$backup"
    if (( APPLY )); then
        mkdir -p "$(dirname "$dest")"
        rm -rf -- "$dest"
        cp -a -- "$backup" "$dest"
    fi
done < "$BACKUP/restore.tsv"
(( APPLY )) && info "Restored." || info "Dry run; re-run with --apply."
