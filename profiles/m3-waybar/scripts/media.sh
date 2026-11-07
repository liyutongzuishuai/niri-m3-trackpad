#!/usr/bin/env bash
# waybar-m3 · scripts/media.sh
# 「谁在占用音频输出 / 有没有消息」的检测与呈现（提示词里的 412×52 容器框）。
#
#   --bar        给 waybar 的 JSON（text / tooltip / class）
#   --text       纯文本（面板与调试用）
#   --focus      把正在出声的那个窗口切到前台
#   --playpause  播放 / 暂停（需要该进程提供 MPRIS）
#
# 检测顺序与提示词一致：
#   1. 有进程在占用音频输出 → 显示「进程名：内容」
#   2. 没有音频输出         → 检测有没有消息，有就显示「进程名：内容」
#   3. 都没有               → 空状态提示
#
# 用 pactl 的 JSON 输出而不是解析人类可读文本：后者会随系统语言变化而失效。

set -u
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "$SCRIPT_DIR/lib.sh"

PILL_COLS="${WAYBAR_M3_PILL_COLS:-26}"
EMPTY_TEXT="${WAYBAR_M3_EMPTY_TEXT:-无音频输出 · 无消息}"

# ── 检测 ──────────────────────────────────────────────────────

# 正在出声的 sink-input：corked=false 表示没被暂停。
# 输出 TSV：application.name \t media.name \t portal app_id \t 二进制名
playing_sink_input() {
    has pactl || return 1
    pactl -f json list sink-inputs 2>/dev/null | jq -er '
        [ .[] | select(.corked == false) ]
        | .[0]
        | [ (.properties["application.name"] // .properties["application.process.binary"] // ""),
            (.properties["media.name"] // ""),
            (.properties["pipewire.access.portal.app_id"] // ""),
            (.properties["application.process.binary"] // "") ]
        | @tsv' 2>/dev/null
}

# 如果正在出声的进程同时提供 MPRIS，就用真正的曲名（浏览器标签页标题往往不是歌名）
mpris_title_for() {
    local want p
    want=$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')
    [ -n "$want" ] || return 1
    has playerctl || return 1
    for p in $(playerctl -l 2>/dev/null); do
        case "$(printf '%s' "$p" | tr '[:upper:]' '[:lower:]')" in
            *"$want"*)
                playerctl -p "$p" metadata --format '{{title}}' 2>/dev/null | head -n 1
                return 0 ;;
        esac
    done
    return 1
}

# 去掉浏览器标签页标题前面的 "(2) " 这类前缀
clean_content() {
    printf '%s' "$1" | sed -E 's/^\([0-9]+\)[[:space:]]*//'
}

# ── 呈现 ──────────────────────────────────────────────────────

# 容器框里的文字：进程名 / ：/ 内容，按状态取 M3 角色色。
# 标题用 onSurface，说明文字用 onSurfaceVariant（提示词的排版要求）。
pill_text() {
    local state="$1" app="$2" content="$3"
    app=$(xml_escape "$app")
    content=$(xml_escape "$content")
    case "$state" in
        playing)
            printf "<span foreground='%s'>%s</span><span foreground='%s'>：</span><span foreground='%s'>%s</span>" \
                "$(m3 on_surface_variant)" "$app" "$(m3 outline)" "$(m3 on_surface)" "$content" ;;
        message)
            printf "<span foreground='%s'>%s</span><span foreground='%s'>：</span><span foreground='%s'>%s</span>" \
                "$(m3 on_tertiary_container)" "$app" "$(m3 on_tertiary_container)" \
                "$(m3 on_tertiary_container)" "$content" ;;
        *)
            printf "<span foreground='%s'>%s</span>" "$(m3 on_surface_variant)" "$app" ;;
    esac
}

# 收集当前状态：输出 TSV  状态 \t 进程显示名 \t 内容 \t 正文
detect() {
    local line app media app_id binary name content latest mapp msum mbody t
    if line=$(playing_sink_input); then
        IFS=$'\t' read -r app media app_id binary <<<"$line"
        name=$(friendly_name "$binary" "$app")
        content=$(clean_content "$media")
        if t=$(mpris_title_for "${binary:-$app}") && [ -n "$t" ]; then
            content="$t"
        fi
        [ -n "$content" ] || content="$name"
        printf 'playing\t%s\t%s\t%s\n' "$name" "$content" ""
        return 0
    fi
    latest=$("$SCRIPT_DIR/messages.sh" latest 2>/dev/null)
    if [ -n "$latest" ]; then
        IFS=$'\t' read -r mapp msum mbody <<<"$latest"
        printf 'message\t%s\t%s\t%s\n' "$(friendly_name "" "$mapp")" "$msum" "$mbody"
        return 0
    fi
    printf 'idle\t%s\t\t\n' "$EMPTY_TEXT"
}

do_bar() {
    local state app content body text tooltip cls
    IFS=$'\t' read -r state app content body < <(detect)
    cls="$state"
    text=$(pill_text "$state" "$app" "$(truncate_cols "$PILL_COLS" "$content")")
    case "$state" in
        playing)
            tooltip=$(printf '正在占用音频输出：%s\n内容：%s\n\n左键：查看全部\n中键：播放/暂停\n右键：切到该窗口' \
                      "$app" "$content") ;;
        message)
            tooltip=$(printf '新消息 · %s\n%s\n\n左键：查看全部' "$app" "$content
$body") ;;
        *)
            tooltip=$(printf '%s\n\n没有进程在占用音频输出，也没有未读消息。\n消息来源：mako / dunst / 消息池（scripts/message-add.sh）' \
                      "$EMPTY_TEXT") ;;
    esac
    jq -cn --arg text "$text" --arg tooltip "$tooltip" --arg class "$cls" \
        '{text: $text, tooltip: $tooltip, class: $class}'
}

do_text() {
    local state app content body
    IFS=$'\t' read -r state app content body < <(detect)
    case "$state" in
        playing) printf '%s：%s\n' "$app" "$content" ;;
        message) printf '%s：%s\n' "$app" "$content" ;;
        *)       printf '%s\n' "$app" ;;
    esac
}

do_focus() {
    local line app media app_id binary id
    if ! line=$(playing_sink_input); then
        notify "没有音频输出" "当前没有进程在占用音频输出。"
        return 0
    fi
    IFS=$'\t' read -r app media app_id binary <<<"$line"
    has niri || { notify "找不到窗口" "需要 niri 才能定位窗口。"; return 0; }
    id=$(niri msg --json windows 2>/dev/null | jq -r --arg a "$app_id" --arg b "$binary" '
        [ .[] | select((.app_id // "") as $x
                       | ($x == $a) or ($x == $b) or (($b != "") and ($x | test($b; "i")))) ]
        | .[0].id // empty' 2>/dev/null)
    if [ -n "$id" ]; then
        niri msg action focus-window --id "$id" >/dev/null 2>&1 \
            || notify "切换失败" "无法聚焦窗口 $id。"
    else
        notify "$(friendly_name "$binary" "$app")" "找不到对应窗口，可能已经关闭。"
    fi
}

do_playpause() {
    if has playerctl && playerctl play-pause 2>/dev/null; then
        return 0
    fi
    notify "无法控制播放" "正在出声的进程没有提供 MPRIS 接口（浏览器标签页通常如此）。"
}

case "${1:---bar}" in
    --bar)       do_bar ;;
    --text)      do_text ;;
    --focus)     do_focus ;;
    --playpause) do_playpause ;;
    *) printf 'media.sh: 未知参数 %s\n' "$1" >&2; exit 2 ;;
esac
