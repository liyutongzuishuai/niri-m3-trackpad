#!/usr/bin/env bash
# waybar-m3 · scripts/control.sh
#
# 控制中心。点击 bar 最右边的 tune 按钮（或电量胶囊）弹出。
#
#   control.sh toggle | open        打开控制中心
#   control.sh status               on / off / na（Wi-Fi）
#
# 第一版用 fuzzel 的 dmenu 模式做「能立刻用的控制中心」：
#   · 电量、Wi-Fi、蓝牙、音量、亮度、勿扰、夜览 + 锁定/注销/重启，一屏列完
#   · 每行 Enter 执行，音量/亮度会再开一层子菜单
# 设计稿里那套卡片式面板（2×2 开关卡 + 真滑块）需要独立窗口，
# 不在这一版里 —— 先把功能落地，样式后续再做。
#
# 配色全部走 lib.sh 的 fuzzel_theme_flags，和搜索栏 / 消息面板同一套 M3 主题。

set -u
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "$SCRIPT_DIR/lib.sh"

WIFI="$SCRIPT_DIR/wifi.sh"
BT="$SCRIPT_DIR/bluetooth.sh"

# ── 单项状态 ────────────────────────────────────────────────

battery_text() {
    local cap=-- st=--
    [ -r /sys/class/power_supply/BAT0/capacity ] \
        && cap=$(cat /sys/class/power_supply/BAT0/capacity 2>/dev/null)
    [ -r /sys/class/power_supply/BAT0/status ] \
        && st=$(cat /sys/class/power_supply/BAT0/status 2>/dev/null)
    local word
    case "$st" in
        Charging)        word="充电中" ;;
        Discharging)     word="放电中" ;;
        Full)            word="已充满" ;;
        "Not charging")  word="未充电" ;;
        "")              word="" ;;
        *)               word="$st" ;;
    esac
    if [ -n "$word" ]; then printf '%s%%  ·  %s' "$cap" "$word"; else printf '%s%%' "$cap"; fi
}

wifi_text() {
    local st ssid
    st=$("$WIFI" status)
    case "$st" in
        on)
            ssid=$(LC_ALL=C nmcli -t -f ACTIVE,SSID device wifi list --rescan no 2>/dev/null \
                   | awk -F: '$1=="yes" && $2!="" {print $2; exit}')
            if [ -n "${ssid:-}" ]; then printf '已连接  %s' "$ssid"; else printf '已开启'; fi ;;
        off) printf '已关闭' ;;
        *)   printf '不可用' ;;
    esac
}

bt_text() {
    case "$("$BT" status)" in
        on)
            local dev
            dev=$(timeout 2 bluetoothctl devices Connected 2>/dev/null | sed -n 's/^Device [^ ]* //p' | head -n1)
            if [ -n "${dev:-}" ]; then printf '已连接  %s' "$dev"; else printf '已开启'; fi ;;
        off) printf '已关闭' ;;
        *)   printf '无适配器' ;;
    esac
}

vol_pct() { bash "$SCRIPT_DIR/slider.sh" volume --bar 2>/dev/null | sed -n 's/.*"percentage":\([0-9]*\).*/\1/p'; }
bri_pct() {
    has brightnessctl || { printf ''; return; }
    brightnessctl -m 2>/dev/null | head -n1 | awk -F, '{gsub(/%/,"",$4); print $4}'
}

dnd_on() { makoctl mode 2>/dev/null | grep -q '^do-not-disturb$'; }
night_on() { pgrep -x wlsunset >/dev/null 2>&1; }

# ── 子菜单 ──────────────────────────────────────────────────

submenu() {   # submenu <提示> <行...>
    local prompt="$1"; shift
    local -a flags
    mapfile -t flags < <(fuzzel_theme_flags 30 8 top-right)
    printf '%s\n' "$@" \
        | fuzzel "${flags[@]}" --dmenu --prompt="$prompt " --placeholder="选择" || true
}

level_menu() {   # level_menu volume|brightness
    local kind="$1" sel
    sel=$(submenu "$([ "$kind" = volume ] && echo 音量 || echo 亮度)" \
            "0%" "25%" "50%" "75%" "100%" \
            "$([ "$kind" = volume ] && echo '静音开关' || echo '最亮')" \
            "拖动滑块…")
    [ -n "${sel:-}" ] || return 0
    case "$sel" in
        *%)      bash "$SCRIPT_DIR/slider.sh" "$kind" set "${sel%\%}" ;;
        静音开关) bash "$SCRIPT_DIR/slider.sh" volume mute ;;
        最亮)     bash "$SCRIPT_DIR/slider.sh" brightness max ;;
        拖动滑块…) bash "$SCRIPT_DIR/slider.sh" "$kind" popup ;;
    esac
}

# ── 动作 ────────────────────────────────────────────────────

do_lock() {
    if has swaylock; then swaylock -f -c "$(m3 surface)" || notify "锁定失败" "swaylock 返回非 0"
    elif has loginctl; then loginctl lock-session
    else notify "没有锁屏工具" "装 swaylock"; fi
}

do_logout() {
    if has niri; then
        niri msg action quit --skip-confirmation >/dev/null 2>&1 || notify "注销失败" ""
    elif has loginctl; then
        loginctl terminate-session "${XDG_SESSION_ID:-}" 2>/dev/null || notify "注销失败" ""
    else
        notify "注销失败" "找不到 niri / loginctl"
    fi
}

do_reboot() {
    if has systemctl; then
        systemctl reboot || notify "重启失败" "可能需要权限"
    else
        notify "重启失败" "没有 systemctl"
    fi
}

do_night_toggle() {
    if night_on; then
        pkill -x wlsunset && notify "夜览已关闭" ""
    else
        if ! has wlsunset; then notify "夜览不可用" "装 wlsunset"; return 0; fi
        setsid wlsunset -t 4000 -T 6500 >/dev/null 2>&1 &
        sleep 0.3
        night_on && notify "夜览已开启" "色温 4000K" || notify "夜览启动失败" ""
    fi
}

do_dnd_toggle() {
    if ! has makoctl; then notify "勿扰不可用" "没有 mako"; return 0; fi
    makoctl mode -t do-not-disturb >/dev/null 2>&1 \
        && { dnd_on && notify "勿扰已开启" "" || notify "勿扰已关闭" ""; } \
        || notify "勿扰切换失败" "mako 没在运行？"
}

# ── 主面板 ──────────────────────────────────────────────────

open_panel() {
    local tmp sel act
    local -a flags
    m3_mktempdir
    tmp="$M3_TMPDIR"

    : >"$tmp/display"
    : >"$tmp/actions"

    add_row() {   # add_row <显示文本> <动作>
        printf '%s\n' "$1" >>"$tmp/display"
        printf '%s\n' "$2" >>"$tmp/actions"
    }

    add_row "电量       $(battery_text)"                       none
    add_row "Wi-Fi      $(wifi_text)"                          wifi-toggle
    add_row "Wi-Fi 网络…"                                       wifi-menu
    add_row "蓝牙       $(bt_text)"                             bt-toggle
    if [ "$("$BT" status)" != na ]; then
        add_row "蓝牙设备…"                                      bt-menu
    fi
    add_row "音量       $(vol_pct)%"                             vol-menu
    add_row "亮度       $(bri_pct)%"                             bri-menu
    add_row "勿扰       $(dnd_on && echo 开 || echo 关)"          dnd-toggle
    add_row "夜览       $(night_on && echo 开 || echo 关)"         night-toggle
    add_row "锁定"                                               lock
    add_row "注销"                                               logout
    add_row "重启"                                               reboot

    mapfile -t flags < <(fuzzel_theme_flags 44 12 top-right)
    sel=$(fuzzel "${flags[@]}" --dmenu \
            --prompt="控制中心 " \
            --placeholder="↑↓ 选择，Enter 执行" \
            <"$tmp/display") || return 0
    [ -n "${sel:-}" ] || return 0

    act=$(awk -v n="$sel" '$0==n {print NR}' "$tmp/display" | head -n1)
    [ -n "${act:-}" ] || return 0
    act=$(sed -n "${act}p" "$tmp/actions")

    case "$act" in
        none)        return 0 ;;
        wifi-toggle) "$WIFI" toggle ;;
        wifi-menu)   "$WIFI" menu ;;
        bt-toggle)   "$BT" toggle ;;
        bt-menu)     "$BT" menu ;;
        vol-menu)    level_menu volume ;;
        bri-menu)    level_menu brightness ;;
        dnd-toggle)  do_dnd_toggle ;;
        night-toggle) do_night_toggle ;;
        lock)        do_lock ;;
        logout)      do_logout ;;
        reboot)      do_reboot ;;
    esac
}

# 有没有图形面板的条件：python3 + PyGObject + gtk-layer-shell 都在
can_gui() {
    command -v python3 >/dev/null 2>&1 || return 1
    [ -x "$SCRIPT_DIR/controlcenter.py" ] || return 1
    python3 - <<'PY' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gtk, GtkLayerShell
PY
}

case "${1:-open}" in
    toggle|open)
        if can_gui; then
            # controlcenter.py 自带单实例逻辑：再点一次就关掉
            exec python3 "$SCRIPT_DIR/controlcenter.py"
        else
            open_panel
        fi ;;
    --fuzzel) open_panel ;;      # 调试用：强制走 fuzzel 版
    *) printf 'control.sh: 未知参数 %s\n' "$1" >&2; exit 2 ;;
esac
