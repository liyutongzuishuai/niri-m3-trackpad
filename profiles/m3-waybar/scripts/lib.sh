#!/usr/bin/env bash
# waybar-m3 · scripts/lib.sh
# 公共函数，被其它脚本 source。
# 颜色一律从 colors.css 的 M3 角色名解析 —— 脚本里不出现写死的颜色值。
# 注意：matugen 模板输出的 @define-color 带前导空格（`    @define-color primary ...`），
# 所以正则必须容忍缩进 —— 否则换成 matugen 生成的 colors.css 后，脚本会静默取色失败、
# 退回 error 色（粉红），而 CSS 那边看起来完全正常。

M3_DIR="${WAYBAR_M3_DIR:-$HOME/.config/waybar-m3}"
M3_COLORS="${WAYBAR_M3_COLORS:-$M3_DIR/colors.css}"

# m3 <角色名> → #RRGGBB
# 找不到角色时回退到 error 色，方便一眼看出角色名拼错。
m3() {
    local role="$1" hex="" alias=""
    if [ -r "$M3_COLORS" ]; then
        hex=$(sed -n "s/^[[:space:]]*@define-color[[:space:]]\{1,\}${role}[[:space:]]\{1,\}\(#[0-9A-Fa-f]\{6,8\}\).*/\1/p" \
              "$M3_COLORS" | head -n 1)
        if [ -z "$hex" ]; then
            # 别名（@define-color background @surface;）再解析一层
            alias=$(sed -n "s/^[[:space:]]*@define-color[[:space:]]\{1,\}${role}[[:space:]]\{1,\}@\([A-Za-z0-9_]\{1,\}\).*/\1/p" \
                    "$M3_COLORS" | head -n 1)
            if [ -n "$alias" ]; then
                hex=$(sed -n "s/^[[:space:]]*@define-color[[:space:]]\{1,\}${alias}[[:space:]]\{1,\}\(#[0-9A-Fa-f]\{6,8\}\).*/\1/p" \
                      "$M3_COLORS" | head -n 1)
            fi
        fi
    fi
    printf '%s' "${hex:-#F2B8B5}"
}

# rgba8 <角色名> → 8 位 RGBA（不带 #），fuzzel 只认这种格式
rgba8() {
    local hex
    hex=$(m3 "$1" | tr -d '#')
    case "${#hex}" in
        6) printf '%sff' "$hex" ;;
        8) printf '%s' "$hex" ;;
        *) printf 'F2B8B5ff' ;;
    esac
}

# has <命令> → 存在返回 0
has() { command -v "$1" >/dev/null 2>&1; }

# notify <标题> <正文>
notify() {
    has notify-send && notify-send -a waybar-m3 "$1" "${2:-}" >/dev/null 2>&1 || true
}

# 重复一个字符 n 次（n=0 时输出空）
repeat_char() {
    local ch="$1" n="$2"
    [ "$n" -gt 0 ] 2>/dev/null || return 0
    printf "%s" "$ch"
    local i
    for ((i = 1; i < n; i++)); do printf "%s" "$ch"; done
}

# truncate_cols <最大列数> <文本>
# 按显示宽度截断（CJK 记 2 列，其它记 1 列），超长补 …。
# 这样 412dp 的容器框不会被长标题撑破。
truncate_cols() {
    local max="$1"; shift
    printf '%s' "$*" | python3 -c '
import sys, unicodedata
maxc = int(sys.argv[1])
s = sys.stdin.read().strip()
w = lambda t: sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in t)
if w(s) <= maxc:
    print(s)
else:
    out = ""
    for ch in s:
        if w(out + ch) > maxc - 1:
            break
        out += ch
    print(out + "…")
' "$max"
}

# 建临时目录并注册退出清理。
# 坑：不能把路径放在函数的 local 里再 trap EXIT —— 函数一返回 local 就失效，
# 退出时 trap 会因为 set -u 报「未绑定的变量」，而且临时目录根本不会被删掉（每次都漏一个）。
# 所以路径存在全局变量里，trap 只引用全局。
M3_TMPDIR=""
m3_mktempdir() {
    M3_TMPDIR=$(mktemp -d)
    trap 'rm -rf "$M3_TMPDIR"' EXIT
}

# xml_escape <文本> → 放进 pango 标记里安全的文本
xml_escape() {
    printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'
}

# fuzzel_theme_flags [宽度] [行数] [锚点] [上边距] → 输出 fuzzel 的 M3 主题参数（一行一个）
# 颜色全部来自 colors.css；fuzzel 只接受不带 # 的 8 位 RGBA。
#
# 锚点必须和调用方在 bar 上的位置一致：搜索栏 / 工作区按钮在左边 → top-left，
# 消息面板在右边 → top-right。之前一律 top-right，所以点左边的搜索栏会在右上角弹出来。
# 上边距默认 48 = bar 高 40 + 8px 间隙，让面板落在 bar 下面而不是压住它。
# 面板高度：16 + 5×36 + 16 = 212（对上提示词里 412×212 的容器高度）。
fuzzel_theme_flags() {
    local width="${1:-48}" lines="${2:-5}" anchor="${3:-top-right}" ymargin="${4:-48}"
    printf '%s\n' \
        "--anchor=${anchor}" "--x-margin=16" "--y-margin=${ymargin}" \
        "--width=$width" "--lines=$lines" "--line-height=36" \
        "--horizontal-pad=20" "--vertical-pad=16" "--inner-pad=8" \
        "--border-width=0" "--border-radius=28" "--selection-radius=20" \
        "--font=Roboto:size=14" \
        "--background-color=$(rgba8 surface_container_high)" \
        "--text-color=$(rgba8 on_surface)" \
        "--prompt-color=$(rgba8 on_surface_variant)" \
        "--placeholder-color=$(rgba8 on_surface_variant)" \
        "--input-color=$(rgba8 on_surface)" \
        "--match-color=$(rgba8 primary)" \
        "--selection-color=$(rgba8 secondary_container)" \
        "--selection-text-color=$(rgba8 on_secondary_container)" \
        "--selection-match-color=$(rgba8 primary)" \
        "--counter-color=$(rgba8 on_surface_variant)" \
        "--border-color=$(rgba8 outline_variant)"
}

# friendly_name <binary> <application.name>
# 把进程名换成给人看的名字，例如 zen → zen浏览器（提示词里的写法）。
friendly_name() {
    local bin="${1:-}" app="${2:-}" key
    key=$(printf '%s' "${bin:-$app}" | tr '[:upper:]' '[:lower:]')
    case "$key" in
        *zen*)              printf 'zen浏览器' ;;
        *firefox*)          printf 'firefox浏览器' ;;
        *chromium*)         printf 'chromium浏览器' ;;
        *chrome*)           printf 'chrome浏览器' ;;
        *linuxqq*|*qq*)     printf 'qq' ;;
        *telegram*)         printf 'telegram' ;;
        *discord*)          printf 'discord' ;;
        *spotify*)          printf 'spotify' ;;
        *mpv*)              printf 'mpv' ;;
        *vlc*)              printf 'vlc' ;;
        *deadbeef*)         printf 'deadbeef' ;;
        *celluloid*)        printf 'celluloid' ;;
        *feishu*|*lark*)    printf '飞书' ;;
        *wechat*|*weixin*)  printf '微信' ;;
        "")                 printf '未知' ;;
        *)                  printf '%s' "${app:-$bin}" ;;
    esac
}

# json_emit <class> <text> [tooltip] [alt]
# 给 waybar 的 custom 模块（return-type: json）输出一行 JSON。
# 交给 python 序列化：SSID / 设备名里出现引号、反斜杠也不会把 JSON 弄坏。
json_emit() {
    python3 - "$@" <<'PY'
import json, sys
cls, text = sys.argv[1], sys.argv[2]
tooltip = sys.argv[3] if len(sys.argv) > 3 else ""
alt = sys.argv[4] if len(sys.argv) > 4 else ""
out = {"text": text, "class": cls}
if tooltip:
    out["tooltip"] = tooltip
if alt:
    out["alt"] = alt
print(json.dumps(out, ensure_ascii=False))
PY
}
