#!/usr/bin/env bash
# waybar-m3 · install.sh
# 把配置装到 ~/.config/waybar-m3，并按需安装字体。
#
#   ./install.sh                 装配置 + 字体
#   ./install.sh --no-fonts      只装配置
#   ./install.sh --prefix DIR    装到别的目录
#   ./install.sh --link          额外让 ~/.config/waybar 指向本配置（原配置会先备份）
#
# 为什么字体默认要装：Material Symbols Rounded 不在 Fedora 仓库里，
# 不装的话图标位置会显示成豆腐块（□）。Roboto 同理（有 dnf 包）。
# 字体下载到 ~/.local/share/fonts，不需要 sudo。

set -euo pipefail

SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PREFIX="${HOME}/.config/waybar-m3"
FONT_DIR="${WAYBAR_M3_FONT_DIR:-${HOME}/.local/share/fonts}"
WITH_FONTS=1
LINK=0

ROBOTO_URL="https://raw.githubusercontent.com/googlefonts/roboto-2/main/src/hinted/Roboto-Regular.ttf"
MATERIAL_SYMBOLS_URL="https://raw.githubusercontent.com/google/material-design-icons/master/variablefont/MaterialSymbolsRounded%5BFILL%2CGRAD%2Copsz%2Cwght%5D.ttf"

usage() { sed -n '2,12p' "$0"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --no-fonts) WITH_FONTS=0 ;;
        --prefix)   PREFIX="${2:?--prefix 需要一个目录}"; shift ;;
        --link)     LINK=1 ;;
        -h|--help)  usage; exit 0 ;;
        *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

say()  { printf '\033[1;35m▸\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*" >&2; }

# ── 1. 安装配置 ───────────────────────────────────────────────

say "安装到 $PREFIX"
mkdir -p "$PREFIX/scripts"
install -m 0644 "$SRC/config.jsonc" "$PREFIX/config.jsonc"
install -m 0644 "$SRC/style.css"    "$PREFIX/style.css"
install -m 0644 "$SRC/colors.css"   "$PREFIX/colors.css"
for f in "$SRC"/scripts/*.sh; do
    install -m 0755 "$f" "$PREFIX/scripts/$(basename "$f")"
done
# .py 也要带（controlcenter.py 是图形控制中心）
for f in "$SRC"/scripts/*.py; do
    [ -e "$f" ] && install -m 0755 "$f" "$PREFIX/scripts/$(basename "$f")"
done
# tools/ 也要带上：换壁纸后用 set-colors.sh 重新推导配色
mkdir -p "$PREFIX/tools"
for f in "$SRC"/tools/*.sh; do
    [ -e "$f" ] && install -m 0755 "$f" "$PREFIX/tools/$(basename "$f")"
done
install -m 0644 "$SRC/colors.prompt.css" "$PREFIX/colors.prompt.css"
say "配置与脚本就位（$(find "$PREFIX/scripts" -name '*.sh' | wc -l) 个脚本）"

# ── 2. 字体 ───────────────────────────────────────────────────

have_font() {
    fc-list : family 2>/dev/null | tr ',' '\n' | sed 's/^ *//; s/ *$//' | grep -qxF "$1"
}

fetch_font() {
    local url="$1" out="$2" name="$3"
    if ! command -v curl >/dev/null 2>&1; then
        warn "没有 curl，跳过 $name 的下载"
        return 1
    fi
    say "下载 $name → $out"
    if curl -fsSL --retry 2 --max-time 300 "$url" -o "$out.part"; then
        mv "$out.part" "$out"
        return 0
    fi
    rm -f "$out.part"
    warn "$name 下载失败，请手动安装"
    return 1
}

if [ "$WITH_FONTS" = 1 ]; then
    mkdir -p "$FONT_DIR"
    changed=0

    if have_font "Roboto"; then
        say "Roboto 已安装"
    else
        fetch_font "$ROBOTO_URL" "$FONT_DIR/Roboto-Regular.ttf" "Roboto" && changed=1 \
            || warn "也可以改用：sudo dnf install google-roboto-fonts"
    fi

    if have_font "Material Symbols Rounded"; then
        say "Material Symbols Rounded 已安装"
    else
        # 官方变体字体约 15MB，包含全部 4000+ 图标
        fetch_font "$MATERIAL_SYMBOLS_URL" \
            "$FONT_DIR/MaterialSymbolsRounded.ttf" "Material Symbols Rounded（约 15MB）" && changed=1
    fi

    if [ "$changed" = 1 ]; then
        command -v fc-cache >/dev/null 2>&1 && fc-cache -f "$FONT_DIR" >/dev/null 2>&1 || true
        say "字体缓存已刷新"
    fi

    missing=""
    have_font "Roboto" || missing="$missing Roboto"
    have_font "Material Symbols Rounded" || missing="$missing MaterialSymbolsRounded"
    if [ -n "$missing" ]; then
        warn "仍缺少字体：$missing —— 图标会显示成方块"
    else
        say "字体齐全（Roboto + Material Symbols Rounded）"
    fi
fi

# ── 3. 可选：接管 ~/.config/waybar ────────────────────────────

if [ "$LINK" = 1 ]; then
    target="${HOME}/.config/waybar"
    if [ -e "$target" ] && [ ! -L "$target" ]; then
        backup="${target}.bak.$(date +%Y%m%d%H%M%S)"
        say "备份现有配置 → $backup"
        mv "$target" "$backup"
    fi
    mkdir -p "$(dirname "$target")"
    ln -sfn "$PREFIX" "$target"
    say "~/.config/waybar → $PREFIX"
fi

# ── 4. 后续步骤 ───────────────────────────────────────────────

cat <<EOF

装好了。两种用法：

  1) 单独试跑（不影响你现有的 waybar）：
       waybar -c "$PREFIX/config.jsonc" -s "$PREFIX/style.css"

  2) 让现有配置用上它：把上面那条命令写进 niri 的 config.kdl，或者用 --link 重装。

容器框的消息来源按顺序是 mako → dunst → 消息池，用这条命令看当前实际生效的是哪个：
  "$PREFIX/scripts/messages.sh" source

没有通知守护进程时，也可以直接往消息池塞消息：
  "$PREFIX/scripts/message-add.sh" qq 女神 我喜欢你

面板想要“从右侧滑入”的动画，需要 swaync（装上后 panel.sh 会自动改用它）：
  sudo dnf install SwayNotificationCenter

EOF
