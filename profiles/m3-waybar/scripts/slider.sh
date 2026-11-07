#!/usr/bin/env bash
# waybar-m3 · scripts/slider.sh
# M3 Expressive 滑块：16dp 粗轨道 + 44dp 手柄（手柄左侧 primary，右侧 secondaryContainer）。
#
# waybar 没有原生滑块控件，所以轨道与手柄用字形画出来：
#   █ (U+2588 实心方块)  = 轨道
#   ┃ (U+2503 粗竖线)    = 手柄
# 格子总数固定，因此数值变化时宽度不会跳动。
#
#   slider.sh volume|brightness --bar        给 waybar 的 JSON
#   slider.sh volume|brightness up|down      滚轮 ±5%
#   slider.sh volume mute                    静音开关
#   slider.sh volume|brightness popup        可拖动的 GTK 滑块（zenity）
#   slider.sh brightness max                 亮度拉满
#   slider.sh volume|brightness set <0-100>  直接设到某个百分比（控制中心用）

set -u
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "$SCRIPT_DIR/lib.sh"

COLS="${WAYBAR_M3_SLIDER_COLS:-10}"      # 轨道格子数（固定，避免宽度跳动）
TRACK_RISE="${WAYBAR_M3_TRACK_RISE:-3000}" # 轨道相对手柄的抬升，Pango 单位（约 3px）
HANDLE_SIZE="${WAYBAR_M3_HANDLE_SIZE:-33pt}" # 手柄字号 ≈ 44px 高
STEP="${WAYBAR_M3_STEP:-5}"              # 滚轮步长（百分比）

# ── 音量 ──────────────────────────────────────────────────────

volume_pct() {
    if has wpctl; then
        wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>/dev/null | awk '{printf "%d", $2 * 100}'
    elif has pactl; then
        # 不解析本地化文本，只取第一个百分比数字
        pactl get-sink-volume @DEFAULT_SINK@ 2>/dev/null | grep -o '[0-9]\+%' | head -n1 | tr -d '%'
    fi
}

volume_muted() {
    if has wpctl; then
        wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>/dev/null | grep -q '\[MUTED\]'
    elif has pactl; then
        pactl get-sink-mute @DEFAULT_SINK@ 2>/dev/null | grep -qi 'yes'
    else
        return 1
    fi
}

volume_step() {
    local sign="$1"
    if has wpctl; then
        wpctl set-volume -l 1.5 @DEFAULT_AUDIO_SINK@ "${STEP}%${sign}" >/dev/null 2>&1
    elif has pactl; then
        pactl set-sink-volume @DEFAULT_SINK@ "${STEP}%${sign}" >/dev/null 2>&1
    fi
}

volume_set() {
    if has wpctl; then
        wpctl set-volume @DEFAULT_AUDIO_SINK@ "$1%" >/dev/null 2>&1
    elif has pactl; then
        pactl set-sink-volume @DEFAULT_SINK@ "$1%" >/dev/null 2>&1
    fi
}

volume_mute_toggle() {
    if has wpctl; then
        wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle >/dev/null 2>&1
    elif has pactl; then
        pactl set-sink-mute @DEFAULT_SINK@ toggle >/dev/null 2>&1
    fi
}

# ── 亮度 ──────────────────────────────────────────────────────

brightness_pct() {
    has brightnessctl || return 1
    brightnessctl -m 2>/dev/null | head -n1 | awk -F, '{gsub(/%/, "", $4); print $4}'
}

brightness_step() { brightnessctl set "${STEP}%$1" >/dev/null 2>&1; }
brightness_set()  { brightnessctl set "$1%" >/dev/null 2>&1; }

# ── 绘制 ──────────────────────────────────────────────────────

# render <百分比> <填充色> <空白色> <手柄色>
render() {
    local pct="$1" fc="$2" ec="$3" hc="$4"
    local filled=$(( pct * COLS / 100 )) empty
    [ "$filled" -lt 0 ] && filled=0
    [ "$filled" -gt "$COLS" ] && filled="$COLS"
    empty=$(( COLS - filled ))
    printf "<span foreground='%s' rise='%s'>%s</span><span foreground='%s' size='%s'>┃</span><span foreground='%s' rise='%s'>%s</span>" \
        "$fc" "$TRACK_RISE" "$(repeat_char '█' "$filled")" \
        "$hc" "$HANDLE_SIZE" \
        "$ec" "$TRACK_RISE" "$(repeat_char '█' "$empty")"
}

render_unavailable() {
    render 0 "$(m3 outline_variant)" "$(m3 surface_container_highest)" "$(m3 outline)"
}

do_bar() {
    local kind="$1" pct="" text tooltip="" cls="normal"
    case "$kind" in
        volume)
            pct=$(volume_pct)
            if [ -z "$pct" ]; then
                cls="unavailable"; pct=0
                text=$(render_unavailable)
                tooltip="找不到音频输出设备（需要 wpctl 或 pactl）"
            elif volume_muted; then
                cls="muted"
                text=$(render "$pct" "$(m3 outline_variant)" "$(m3 surface_container_highest)" "$(m3 outline)")
                tooltip="音量已静音 · 滚轮调整，左键取消静音，右键拖动滑块"
            else
                text=$(render "$pct" "$(m3 primary)" "$(m3 secondary_container)" "$(m3 primary)")
                tooltip="音量 ${pct}% · 滚轮调整，左键静音，右键拖动滑块"
            fi ;;
        brightness)
            if pct=$(brightness_pct) && [ -n "$pct" ]; then
                text=$(render "$pct" "$(m3 primary)" "$(m3 secondary_container)" "$(m3 primary)")
                tooltip="亮度 ${pct}% · 滚轮调整，左键拖动滑块，右键拉满"
            else
                cls="unavailable"; pct=0
                text=$(render_unavailable)
                tooltip="找不到背光设备（需要 brightnessctl）"
            fi ;;
        *) printf 'slider.sh: 未知滑块 %s\n' "$kind" >&2; exit 2 ;;
    esac
    jq -cn --arg text "$text" --arg tooltip "$tooltip" --arg class "$cls" \
           --argjson percentage "${pct:-0}" \
        '{text: $text, tooltip: $tooltip, class: $class, percentage: $percentage}'
}

do_popup() {
    local kind="$1" pct v
    if ! has zenity; then
        notify "缺少 zenity" "安装 zenity 后可以使用可拖动的滑块。"
        return 0
    fi
    case "$kind" in
        volume)     pct=$(volume_pct); [ -n "$pct" ] || pct=50 ;;
        brightness) pct=$(brightness_pct) || pct=50 ;;
    esac
    zenity --scale \
        --title="$([ "$kind" = volume ] && printf '音量' || printf '亮度')" \
        --text="" --value="$pct" --min-value=0 --max-value=100 \
        --print-partial --width=320 2>/dev/null |
    while read -r v; do
        [ -n "$v" ] || continue
        case "$kind" in
            volume)     volume_set "$((v))" ;;
            brightness) brightness_set "$((v))" ;;
        esac
    done
}

kind="${1:-volume}"
action="${2:---bar}"
case "$kind" in volume|brightness) ;; *) printf 'slider.sh: 未知滑块 %s\n' "$kind" >&2; exit 2 ;; esac

case "$action" in
    --bar)  do_bar "$kind" ;;
    up)
        if [ "$kind" = volume ]; then volume_step +; else brightness_step +; fi ;;
    down)
        if [ "$kind" = volume ]; then volume_step -; else brightness_step -; fi ;;
    mute)   volume_mute_toggle ;;
    max)    brightness_set 100 ;;
    set)
        value="${3:-}"
        case "$value" in
            ''|*[!0-9]*) printf 'slider.sh: set 需要一个 0-100 的数字\n' >&2; exit 2 ;;
        esac
        [ "$value" -gt 100 ] && value=100
        if [ "$kind" = volume ]; then volume_set "$value"; else brightness_set "$value"; fi ;;
    popup)  do_popup "$kind" ;;
    *) printf 'slider.sh: 未知动作 %s\n' "$action" >&2; exit 2 ;;
esac
