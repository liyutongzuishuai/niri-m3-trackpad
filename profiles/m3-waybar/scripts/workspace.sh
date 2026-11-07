#!/usr/bin/env bash
# waybar-m3 · scripts/workspace.sh
# 图标按钮的点击行为。按钮上的「public 图标 + 工作区编号」由 niri/workspaces 模块显示，
# 这里补上点击后该做的事（否则点一下什么都不会发生）：
#
#   workspace.sh pick   工作区选择器（fuzzel）   ← 左键
#   workspace.sh next   切到下一个工作区          ← 右键

set -u
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "$SCRIPT_DIR/lib.sh"

pick() {
    has niri || { notify "工作区" "需要 niri。"; return 0; }
    local tmp sel idx
    m3_mktempdir
    tmp="$M3_TMPDIR"
    niri msg --json workspaces 2>/dev/null \
        | jq -r '.[] | "\(.idx)\t\(if (.name // "") == "" then "工作区 \(.idx)" else .name end)"' >"$tmp/ws"
    [ -s "$tmp/ws" ] || { notify "工作区" "读不到工作区列表。"; return 0; }
    cut -f2 "$tmp/ws" >"$tmp/names"

    local -a flags
    mapfile -t flags < <(fuzzel_theme_flags 32 6 top-left)
    sel=$(fuzzel "${flags[@]}" --dmenu --prompt="工作区 " --minimal-lines <"$tmp/names") || return 0
    [ -n "$sel" ] || return 0
    idx=$(grep -n -F -x -m1 -- "$sel" "$tmp/names" | cut -d: -f1)
    [ -n "$idx" ] || return 0
    niri msg action focus-workspace "$(sed -n "${idx}p" "$tmp/ws" | cut -f1)" >/dev/null 2>&1
}

next() { niri msg action focus-workspace-down >/dev/null 2>&1; }

case "${1:-pick}" in
    pick) pick ;;
    next) next ;;
    *) printf 'workspace.sh: 未知参数 %s\n' "$1" >&2; exit 2 ;;
esac
