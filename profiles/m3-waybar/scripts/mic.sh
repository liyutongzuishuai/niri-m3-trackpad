#!/usr/bin/env bash
# waybar-m3 · scripts/mic.sh
# 搜索栏右端 mic 图标的点击行为：语音输入开关。
#
#   mic.sh toggle
#
# 依次尝试：WAYBAR_M3_VOICE_CMD → nerd-dictation → whisper-dictation。
# 一个都没有就明确提示（不假装能用），因为语音识别引擎必须由用户自己装。

set -u
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "$SCRIPT_DIR/lib.sh"

STATE="${XDG_RUNTIME_DIR:-/tmp}/waybar-m3/dictation.pid"

voice_cmd() {
    if [ -n "${WAYBAR_M3_VOICE_CMD:-}" ]; then
        printf '%s' "$WAYBAR_M3_VOICE_CMD"
        return 0
    fi
    if has nerd-dictation; then printf 'nerd-dictation'; return 0; fi
    if has whisper-dictation; then printf 'whisper-dictation'; return 0; fi
    return 1
}

start() {
    local cmd="$1"
    mkdir -p "$(dirname "$STATE")"
    case "$cmd" in
        nerd-dictation)
            nerd-dictation begin --timeout=2.0 >/dev/null 2>&1 &
            printf '%s' "$!" >"$STATE" ;;
        *)
            setsid sh -c "$cmd" >/dev/null 2>&1 &
            printf '%s' "$!" >"$STATE" ;;
    esac
    notify "语音输入" "已开始，说完停顿会自动断句"
}

stop() {
    local cmd="$1" pid=""
    [ -r "$STATE" ] && pid=$(cat "$STATE" 2>/dev/null)
    case "$cmd" in
        nerd-dictation) nerd-dictation end >/dev/null 2>&1 ;;
    esac
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
    rm -f "$STATE"
    notify "语音输入" "已停止"
}

case "${1:-toggle}" in
    toggle)
        if ! cmd=$(voice_cmd); then
            notify "语音输入不可用" "没有检测到 nerd-dictation 或 whisper-dictation。
安装其中一个，或用 WAYBAR_M3_VOICE_CMD 指定命令。"
            exit 0
        fi
        if [ -e "$STATE" ] && kill -0 "$(cat "$STATE" 2>/dev/null)" 2>/dev/null; then
            stop "$cmd"
        else
            rm -f "$STATE"
            start "$cmd"
        fi ;;
    status)
        if [ -e "$STATE" ]; then printf 'recording'; else printf 'idle'; fi ;;
    *) printf 'mic.sh: 未知参数 %s\n' "$1" >&2; exit 2 ;;
esac
