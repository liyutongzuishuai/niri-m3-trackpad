#!/usr/bin/env bash
# waybar-m3 · tools/set-colors.sh
# 从壁纸推导 M3 配色并写入 colors.css。
# 配置与脚本都只按角色名引用颜色，所以换主题只需要换这一个文件。
#
#   tools/set-colors.sh                     用 niri 配置里的壁纸 + scheme-content
#   tools/set-colors.sh -t scheme-fidelity  换 scheme（先跑 --list 看效果）
#   tools/set-colors.sh -i ~/w.jpg          换壁纸
#   tools/set-colors.sh --list              列出各 scheme 会得到的主色/强调色
#   tools/set-colors.sh --prompt            还原提示词给的那套紫色
#   tools/set-colors.sh --dir DIR           输出到指定目录（默认 ~/.config/waybar-m3）

set -euo pipefail

SELF_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PROJECT_DIR="$(dirname "$SELF_DIR")"
DIR="${WAYBAR_M3_DIR:-$HOME/.config/waybar-m3}"
SCHEME="scheme-content"
MODE="dark"
IMAGE=""
ACTION="generate"

usage() { sed -n '2,12p' "$0"; }

# 默认壁纸：niri 配置里第一个 background-image
detect_wallpaper() {
    local kdl="${XDG_CONFIG_HOME:-$HOME/.config}/niri/config.kdl" p
    [ -r "$kdl" ] || return 1
    p=$(grep -oE '"[^"]+\.(jpg|jpeg|png|webp)"' "$kdl" | head -n1 | tr -d '"')
    [ -n "$p" ] && [ -r "$p" ] && printf '%s' "$p"
}

while [ $# -gt 0 ]; do
    case "$1" in
        -t|--type)  SCHEME="${2:?--type 需要一个 scheme}"; shift ;;
        -i|--image) IMAGE="${2:?--image 需要一个路径}"; shift ;;
        -m|--mode)  MODE="${2:?--mode 需要 light 或 dark}"; shift ;;
        --dir)      DIR="${2:?--dir 需要一个目录}"; shift ;;
        --prompt)   ACTION="prompt" ;;
        --list)     ACTION="list" ;;
        -h|--help)  usage; exit 0 ;;
        *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

command -v matugen >/dev/null 2>&1 || { echo "需要 matugen：sudo dnf install matugen" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "需要 jq" >&2; exit 1; }

# matugen 要求配置里有 templates 字段。给个空的最小配置，
# 这样就不会触发用户自己 config.toml 里的模板（否则会把 kitty/btop/mako 一起重写）。
TMP_CFG_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_CFG_DIR"' EXIT
TMP_CFG="$TMP_CFG_DIR/matugen.toml"
printf '[config]\n\n[templates]\n' > "$TMP_CFG"

palette() { # <image> <scheme> → JSON
    matugen image "$1" -c "$TMP_CFG" --json hex --mode "$MODE" --type "$2" 2>/dev/null
}

# ── --list：先看各 scheme 出什么色 ────────────────────────────
if [ "$ACTION" = list ]; then
    [ -n "$IMAGE" ] || IMAGE="$(detect_wallpaper)" || { echo "找不到壁纸，用 -i 指定" >&2; exit 1; }
    printf '壁纸：%s\n\n' "$IMAGE"
    printf '%-20s %-9s %-9s %-9s\n' scheme primary secondary tertiary
    for t in scheme-content scheme-fidelity scheme-tonal-spot scheme-expressive \
             scheme-vibrant scheme-rainbow scheme-neutral scheme-monochrome; do
        json="$(palette "$IMAGE" "$t")"
        [ -n "$json" ] || continue
        printf '%-20s %-9s %-9s %-9s\n' "$t" \
            "$(jq -r '.colors.primary.dark' <<<"$json")" \
            "$(jq -r '.colors.secondary.dark' <<<"$json")" \
            "$(jq -r '.colors.tertiary.dark' <<<"$json")"
    done
    exit 0
fi

# ── --prompt：还原提示词给的那套紫色 ──────────────────────────
if [ "$ACTION" = prompt ]; then
    src="$PROJECT_DIR/colors.prompt.css"
    [ -r "$src" ] || { echo "找不到 $src" >&2; exit 1; }
    mkdir -p "$DIR"
    install -m 0644 "$src" "$DIR/colors.css"
    echo "已还原提示词配色 → $DIR/colors.css"
    exit 0
fi

# ── 从壁纸生成 ────────────────────────────────────────────────
[ -n "$IMAGE" ] || IMAGE="$(detect_wallpaper)" \
    || { echo "niri 配置里没找到 background-image，用 -i 指定壁纸" >&2; exit 1; }
[ -r "$IMAGE" ] || { echo "壁纸不存在：$IMAGE" >&2; exit 1; }

JSON="$(palette "$IMAGE" "$SCHEME")"
[ -n "$JSON" ] || { echo "matugen 没有输出，检查壁纸路径或 scheme 名" >&2; exit 1; }

mkdir -p "$DIR"
OUT="$DIR/colors.css"

emit() { printf '@define-color %-26s %s;\n' "$1" "$(jq -r --arg r "$1" '.colors[$r].dark' <<<"$JSON")"; }
section() { printf '/* ── %s ── */\n' "$1"; }

{
    printf '/*\n'
    printf ' * waybar-m3 · colors.css\n'
    printf ' * Material 3 深色配色，由 matugen 从壁纸推导\n'
    printf ' *\n'
    printf ' * 壁纸：%s\n' "$IMAGE"
    printf ' * scheme：%s（%s）\n' "$SCHEME" "$MODE"
    printf ' * 生成：%s · %s\n' "$(date '+%F %T')" "$(matugen --version 2>/dev/null | head -1)"
    printf ' *\n'
    printf ' * 这是整套配置唯一的颜色来源：style.css 与所有脚本都只按角色名引用颜色，\n'
    printf ' * 不写死任何十六进制值。换壁纸后重新跑 tools/set-colors.sh 即可。\n'
    printf ' * 提示词给的那套紫色保留在 colors.prompt.css（--prompt 可还原）。\n'
    printf ' */\n\n'

    section Primary
    for r in primary on_primary primary_container on_primary_container; do emit "$r"; done
    echo
    section "Secondary / Tertiary"
    for r in secondary secondary_container on_secondary_container \
             tertiary_container on_tertiary_container; do emit "$r"; done
    echo
    section Surface
    for r in surface surface_container_low surface_container \
             surface_container_high surface_container_highest; do emit "$r"; done
    echo
    section "On-surface / Outline"
    for r in on_surface on_surface_variant outline outline_variant; do emit "$r"; done
    echo
    section Inverse
    for r in inverse_surface inverse_on_surface inverse_primary; do emit "$r"; done
    echo
    section Error
    for r in error on_error error_container on_error_container; do emit "$r"; done
    echo
    printf '/* ── 别名：只引用上面的角色，不引入新颜色 ── */\n'
    for pair in "background @surface" "surface_dim @surface" \
                "surface_bright @surface_container_highest" "surface_variant @outline_variant" \
                "shadow @surface" "scrim @surface"; do
        # shellcheck disable=SC2086
        set -- $pair
        printf '@define-color %-26s %s;\n' "$1" "$2"
    done
} > "$OUT"

# ── 自检：style.css 与脚本用到的角色是否都在新文件里 ──────────
missing=""
for r in $( { grep -ohE '@[a-z_]+' "$PROJECT_DIR/style.css" | tr -d '@' | grep -v '^import$';
              grep -ohE 'm3 [a-z_]+' "$PROJECT_DIR"/scripts/*.sh | awk '{print $2}'; } | sort -u ); do
    grep -qE "^[[:space:]]*@define-color[[:space:]]+${r}[[:space:]]" "$OUT" || missing="$missing $r"
done
if [ -n "$missing" ]; then
    printf '缺少角色：%s\n' "$missing" >&2
    exit 1
fi

printf '已写入 %s\n' "$OUT"
printf '  primary %s · secondary %s · tertiary_container %s\n' \
    "$(jq -r '.colors.primary.dark' <<<"$JSON")" \
    "$(jq -r '.colors.secondary.dark' <<<"$JSON")" \
    "$(jq -r '.colors.tertiary_container.dark' <<<"$JSON")"
echo "自检通过：style.css 与脚本用到的角色全部齐备 ✓"
echo
echo "让 waybar 重新读样式："
echo "  pkill -SIGUSR2 waybar     # reload_style_on_change 已开，通常改完自动生效"
