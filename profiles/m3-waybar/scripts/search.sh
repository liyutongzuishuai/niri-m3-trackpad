#!/usr/bin/env bash
# waybar-m3 · scripts/search.sh
# 搜索栏（提示词里「类似于 rofi」的那条）：左端 search 图标 + 占位文字「搜索」。
#
#   --bar      搜索栏内容（图标 + 占位文字）      ← 由 waybar 定时执行
#   --apps     应用搜索                          ← 左键
#   --windows  窗口切换                          ← 右键
#   --run      执行命令（相当于 rofi -show run）  ← 中键
#
# 启动器按 fuzzel → rofi → wofi → anyrun 的顺序找第一个能用的。

set -u
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "$SCRIPT_DIR/lib.sh"

ICON_SEARCH=$'\uEF7A' # Material Symbols Rounded: search（注意不是老 Material Icons 的 e8b6）

# 从标准输入挑选一项，回显所选内容
pick_from_stdin() {
    local prompt="$1"
    if has fuzzel; then
        local -a flags
        mapfile -t flags < <(fuzzel_theme_flags 48 8 top-left)
        fuzzel "${flags[@]}" --dmenu --prompt="$prompt " --placeholder="输入以筛选" --minimal-lines
    elif has rofi; then
        rofi -dmenu -i -p "$prompt"
    elif has wofi; then
        wofi --dmenu --prompt "$prompt"
    elif has anyrun; then
        anyrun
    else
        notify "没有启动器" "请安装 fuzzel（推荐）或 rofi / wofi。"
        return 1
    fi
}

do_bar() {
    printf "<span foreground='%s' size='18pt'>%s</span>  <span foreground='%s'>%s</span>" \
        "$(m3 on_surface_variant)" "$ICON_SEARCH" "$(m3 on_surface_variant)" "搜索"
}

do_apps() {
    if has fuzzel; then
        local -a flags
        mapfile -t flags < <(fuzzel_theme_flags 48 8 top-left)
        fuzzel "${flags[@]}" --prompt="应用 " --placeholder="搜索应用"
    elif has rofi; then
        rofi -show drun
    elif has wofi; then
        wofi --show drun
    else
        notify "没有启动器" "请安装 fuzzel（推荐）或 rofi / wofi。"
    fi
}

do_windows() {
    has niri || { notify "窗口切换" "需要 niri 才能列出窗口。"; return 0; }
    local tmp sel idx id
    m3_mktempdir
    tmp="$M3_TMPDIR"
    niri msg --json windows 2>/dev/null \
        | jq -r '.[] | [.id, (.title // "(无标题)")] | @tsv' >"$tmp/win"
    [ -s "$tmp/win" ] || { notify "窗口切换" "当前没有窗口。"; return 0; }
    cut -f2 "$tmp/win" >"$tmp/titles"
    sel=$(pick_from_stdin "窗口" <"$tmp/titles") || return 0
    [ -n "$sel" ] || return 0
    idx=$(grep -n -F -x -m1 -- "$sel" "$tmp/titles" | cut -d: -f1)
    [ -n "$idx" ] || return 0
    id=$(sed -n "${idx}p" "$tmp/win" | cut -f1)
    niri msg action focus-window --id "$id" >/dev/null 2>&1
}

do_run() {
    local sel
    sel=$(printf '' | pick_from_stdin "执行") || return 0
    [ -n "$sel" ] || return 0
    setsid sh -c "$sel" >/dev/null 2>&1 &
}

case "${1:---bar}" in
    --bar)     do_bar ;;
    --apps)    do_apps ;;
    --windows) do_windows ;;
    --run)     do_run ;;
    *) printf 'search.sh: 未知参数 %s\n' "$1" >&2; exit 2 ;;
esac
