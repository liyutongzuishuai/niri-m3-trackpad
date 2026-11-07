#!/usr/bin/env bash
# Restore files backed up by install.sh from one run.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP=""
APPLY=0
while (($#)); do
    case "$1" in
        --backup) BACKUP="${2:?}"; shift ;;
        --latest) BACKUP="$(find "$HOME/.local/state/integrated-niri-m3/backups" -mindepth 1 -maxdepth 1 -type d | sort | tail -n1)" ;;
        --apply) APPLY=1 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
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
