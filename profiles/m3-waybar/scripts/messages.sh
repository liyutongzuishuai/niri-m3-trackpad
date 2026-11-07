#!/usr/bin/env bash
# waybar-m3 · scripts/messages.sh
# 消息来源。按顺序尝试，第一个「真的有内容」的胜出
#（不是第一个“能用”的 —— 否则 mako 装着但缓冲为空时会永远挡住后面的来源）。
#
#   mako   makoctl list -j     当前还挂在屏幕上的通知（真正的未读）
#          makoctl history -j  历史缓冲（最新的在前）—— 通知超时后仍能在这里找到
#   dunst  dunstctl history
#   swaync 没有命令行列表接口，交给 panel.sh 直接用它的面板
#   消息池 $XDG_RUNTIME_DIR/waybar-m3/messages.jsonl（用 message-add.sh 写入）
#
# 环境变量：
#   WAYBAR_M3_MESSAGE_SOURCE=auto|list|history|dunst|spool  强制只用某一个来源
#   WAYBAR_M3_SPOOL=<路径>                                  自定义消息池位置
#
# 输出：每行一条 TSV   应用名 \t 标题 \t 正文      （最新的在最前）
#
# 用法：
#   messages.sh list | count | latest | clear | source

set -u
. "$(dirname "$(readlink -f "$0")")/lib.sh"

SPOOL="${WAYBAR_M3_SPOOL:-${XDG_RUNTIME_DIR:-/tmp}/waybar-m3/messages.jsonl}"
SOURCE="${WAYBAR_M3_MESSAGE_SOURCE:-auto}"

# ── mako ──────────────────────────────────────────────────────
mako_available() { has makoctl && makoctl list -j >/dev/null 2>&1; }

# makoctl 的 JSON 字段是 app_name / desktop_entry / summary / body，且最新在前。
# 顺手过滤掉 waybar-m3 自己发的通知，否则“展示全部”会把内容又写回列表。
mako_list() {
    makoctl "${1:-history}" -j 2>/dev/null | jq -r '
        [ .[]
          | select((.app_name // "") != "waybar-m3")
          | select((.desktop_entry // "") != "waybar-m3") ]
        | .[]
        | [ (.app_name // .desktop_entry // "未知"),
            (.summary // ""),
            (.body // "") ]
        | @tsv' 2>/dev/null
}

# ── dunst ─────────────────────────────────────────────────────
dunst_available() { has dunstctl && dunstctl history >/dev/null 2>&1; }

dunst_list() {
    dunstctl history 2>/dev/null | jq -r '
        [ .data[][]? | select((.appname // "") != "waybar-m3") ]
        | reverse
        | .[]
        | [ (.appname // "未知"), (.summary // ""), (.body // "") ]
        | @tsv' 2>/dev/null
}

# ── 消息池 ────────────────────────────────────────────────────
spool_list() {
    [ -s "$SPOOL" ] || return 0
    jq -r 'select((.app // "") != "waybar-m3")
           | [ (.app // "未知"), (.summary // ""), (.body // "") ] | @tsv' "$SPOOL" 2>/dev/null | tac
}

list_messages() {
    local out=""
    case "$SOURCE" in
        list)    mako_available && mako_list list ;;
        history) mako_available && mako_list history ;;
        dunst)   dunst_available && dunst_list ;;
        spool)   spool_list ;;
        *)
            if mako_available; then
                out=$(mako_list list)
                [ -n "$out" ] && { printf '%s\n' "$out"; return 0; }
                out=$(mako_list history)
                [ -n "$out" ] && { printf '%s\n' "$out"; return 0; }
            fi
            if dunst_available; then
                out=$(dunst_list)
                [ -n "$out" ] && { printf '%s\n' "$out"; return 0; }
            fi
            spool_list ;;
    esac
}

count_messages() { list_messages | grep -c . || true; }

# 当前实际生效的来源（调试用）
source_of() {
    if mako_available; then
        [ -n "$(mako_list list)" ] && { printf 'mako(list)'; return 0; }
        [ -n "$(mako_list history)" ] && { printf 'mako(history)'; return 0; }
    fi
    if dunst_available && [ -n "$(dunst_list)" ]; then printf 'dunst'; return 0; fi
    if [ -n "$(spool_list)" ]; then printf 'spool'; return 0; fi
    printf 'none'
}

# 注意：makoctl dismiss --all 只关掉当前挂着的通知，历史缓冲里仍然留着。
# 想只认“未读”，用 WAYBAR_M3_MESSAGE_SOURCE=list。
clear_messages() {
    mako_available && makoctl dismiss --all >/dev/null 2>&1
    dunst_available && dunstctl close-all >/dev/null 2>&1
    : >"$SPOOL" 2>/dev/null || true
}

case "${1:-list}" in
    list)   list_messages ;;
    count)  count_messages ;;
    latest) list_messages | head -n 1 ;;
    clear)  clear_messages ;;
    source) source_of ;;
    *) printf 'messages.sh: 未知参数 %s\n' "$1" >&2; exit 2 ;;
esac
