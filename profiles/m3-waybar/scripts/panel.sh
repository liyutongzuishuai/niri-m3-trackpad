#!/usr/bin/env bash
# waybar-m3 · scripts/panel.sh
# 「屏幕 1 副本」：从右侧滑入、展示全部音频/消息条目的面板。
#
#   toggle / open / close
#
# 优先 swaync：它的控制中心本身就是从右侧滑入的，最贴近提示词的动画要求。
# 没装 swaync 就用 fuzzel 在右上角渲染一个 M3 面板（尺寸 16+5×36+16 = 212，
# 正好对上提示词里 412×212 的容器高度），配色同样取自 colors.css。
#
# 面板里的行为：选中音频条目 → 切到该窗口；选中消息 → 复制全文并提示（即“展示全部”）。

set -u
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "$SCRIPT_DIR/lib.sh"

swaync_toggle() {
    case "${1:-toggle}" in
        open)   swaync-client --open-panel ;;
        close)  swaync-client --close-panel ;;
        *)      swaync-client --toggle-panel ;;
    esac
}

fuzzel_panel() {
    local tmpdir sel idx action kind rest summary body
    m3_mktempdir
    tmpdir="$M3_TMPDIR"
    : >"$tmpdir/display"
    : >"$tmpdir/actions"

    # 1) 正在出声的进程排在最前
    local mtext
    if mtext=$("$SCRIPT_DIR/media.sh" --text 2>/dev/null) && [ -n "$mtext" ] \
       && ! printf '%s' "$mtext" | grep -q "无音频输出"; then
        printf '%s\n' "$mtext" >>"$tmpdir/display"
        printf 'media\n' >>"$tmpdir/actions"
    fi

    # 2) 然后是消息：每条一行「进程名：内容」
    local app sum bodytext
    while IFS=$'\t' read -r app sum bodytext; do
        [ -n "${app:-}" ] || continue
        printf '%s：%s\n' "$(friendly_name "" "$app")" "$(truncate_cols 56 "$sum")" >>"$tmpdir/display"
        printf 'msg\t%s\t%s\n' "$sum" "$bodytext" >>"$tmpdir/actions"
    done < <("$SCRIPT_DIR/messages.sh" list 2>/dev/null)

    if [ ! -s "$tmpdir/display" ]; then
        printf '%s\n' "没有正在出声的进程，也没有未读消息" >"$tmpdir/display"
        printf 'none\n' >"$tmpdir/actions"
    fi

    local -a flags
    mapfile -t flags < <(fuzzel_theme_flags 48 5 top-right)
    sel=$(fuzzel "${flags[@]}" --dmenu \
            --prompt="全部 " \
            --placeholder="搜索" \
            --minimal-lines \
            --mesg="音频 / 消息" \
            <"$tmpdir/display") || return 0
    [ -n "$sel" ] || return 0

    idx=$(grep -n -F -x -m1 -- "$sel" "$tmpdir/display" | cut -d: -f1)
    [ -n "$idx" ] || return 0
    action=$(sed -n "${idx}p" "$tmpdir/actions")
    kind=${action%%$'\t'*}

    case "$kind" in
        media)
            "$SCRIPT_DIR/media.sh" --focus
            ;;
        msg)
            rest=${action#*$'\t'}
            summary=${rest%%$'\t'*}
            body=${rest#*$'\t'}
            [ "$body" = "$rest" ] && body=""
            printf '%s\n%s\n' "$summary" "$body" | wl-copy 2>/dev/null \
                || notify "复制失败" "没有可用的剪贴板工具（wl-copy）。"
            notify "$summary" "${body:-（无正文）}"
            ;;
        none) : ;;
    esac
}

case "${1:-toggle}" in
    toggle|open|close)
        if has swaync-client; then
            swaync_toggle "${1:-toggle}"
        else
            fuzzel_panel
        fi ;;
    *) printf 'panel.sh: 未知参数 %s\n' "$1" >&2; exit 2 ;;
esac
