#!/usr/bin/env bash
# waybar-m3 · scripts/bluetooth.sh
#
# 蓝牙开关与状态。
#
#   --bar / --text   给 waybar 用（--bar 输出 JSON）
#   toggle           开 / 关蓝牙
#   menu             fuzzel 里连接 / 断开已配对设备
#   status           on / off / na
#
# 本机现状：bluetoothd 在跑，但 `bluetoothctl list` 是空的 —— 没有蓝牙适配器。
# 这时状态固定落在 na（图标 bluetooth_disabled、降透明度、点了只提示），
# 接上适配器后不用改任何配置，会自动变成 on / off 两档。

set -u
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "$SCRIPT_DIR/lib.sh"

ICO_ON=$'\ue1a8'    # bluetooth_connected
ICO_IDLE=$'\ue1a7'  # bluetooth
ICO_NA=$'\ue1a9'    # bluetooth_disabled

has_adapter() { [ -n "$(timeout 2 bluetoothctl list 2>/dev/null)" ]; }

powered() {
    timeout 2 bluetoothctl show 2>/dev/null | grep -q '^[[:space:]]*Powered: yes'
}

# 已连接的设备名（没有则空）
connected_name() {
    timeout 2 bluetoothctl devices Connected 2>/dev/null \
        | sed -n 's/^Device [^ ]* //p' | head -n1
}

status() {
    if ! has bluetoothctl; then printf 'na'; return; fi
    has_adapter || { printf 'na'; return; }
    if powered; then printf 'on'; else printf 'off'; fi
}

# ── 输出 ────────────────────────────────────────────────────

print_bar() {
    local st dev text cls tip
    st=$(status)
    case "$st" in
        on)
            dev=$(connected_name)
            if [ -n "${dev:-}" ]; then
                text=$ICO_ON
                tip=$(printf '蓝牙：已连接 %s\n左键：关闭蓝牙\n右键：设备列表' "$dev")
            else
                text=$ICO_IDLE
                tip=$'蓝牙：已开启（未连接设备）\n左键：关闭蓝牙\n右键：设备列表'
            fi
            cls="on" ;;
        off)
            text=$ICO_IDLE; cls="off"
            tip=$'蓝牙：已关闭\n左键：开启蓝牙' ;;
        *)
            text=$ICO_NA; cls="na"
            tip=$'蓝牙：本机没有蓝牙适配器\n（接上适配器后自动可用）' ;;
    esac

    if [ "${1:-}" = "--text" ]; then
        printf '%s' "$text"
    else
        json_emit "$cls" "$text" "$tip"
    fi
}

# ── 动作 ────────────────────────────────────────────────────

do_toggle() {
    local st
    st=$(status)
    if [ "$st" = na ]; then
        notify "蓝牙不可用" "本机没有蓝牙适配器"
        return 0
    fi
    if ! has bluetoothctl; then
        notify "蓝牙不可用" "没有 bluez"
        return 0
    fi
    if [ "$st" = on ]; then
        timeout 10 bluetoothctl power off >/dev/null 2>&1 \
            && notify "蓝牙已关闭" "" || notify "关闭蓝牙失败" ""
    else
        timeout 10 bluetoothctl power on >/dev/null 2>&1 \
            && notify "蓝牙已开启" "" || notify "开启蓝牙失败" ""
    fi
}

do_menu() {
    if [ "$(status)" = na ]; then notify "蓝牙不可用" "本机没有蓝牙适配器"; return 0; fi
    if ! has fuzzel; then notify "缺少 fuzzel" ""; return 0; fi

    local tmp line mac name sel act
    local -a flags
    m3_mktempdir
    tmp="$M3_TMPDIR"

    while IFS= read -r line; do
        [[ $line =~ ^Device[[:space:]]+([0-9A-Fa-f:]+)[[:space:]]+(.+)$ ]] || continue
        mac="${BASH_REMATCH[1]}"
        name="${BASH_REMATCH[2]}"
        printf '%s\t%s\n' "$mac" "$name" >>"$tmp/raw"
    done < <(timeout 5 bluetoothctl devices Paired 2>/dev/null)

    if [ ! -s "$tmp/raw" ]; then
        notify "还没有配对过的设备" "先用 bluetoothctl 配对一次"
        return 0
    fi

    # 已连接的排最前
    act=$(connected_name)
    awk -F'\t' -v c="${act:-}" \
        '{printf "%s\t%s%s\n", $1, $2, ($2==c ? "  ·  已连接" : "")}' "$tmp/raw" >"$tmp/menu"

    mapfile -t flags < <(fuzzel_theme_flags 40 8 top-right)
    sel=$(cut -f2- "$tmp/menu" \
          | fuzzel "${flags[@]}" --dmenu --prompt="蓝牙 " --placeholder="选择设备") || return 0
    [ -n "${sel:-}" ] || return 0

    mac=$(awk -F'\t' -v d="$sel" '$2==d {print $1; exit}' "$tmp/menu")
    [ -n "${mac:-}" ] || return 0

    if printf '%s' "$sel" | grep -q '已连接'; then
        timeout 15 bluetoothctl disconnect "$mac" >/dev/null 2>&1 \
            && notify "已断开" "$sel" || notify "断开失败" "$sel"
    else
        timeout 20 bluetoothctl connect "$mac" >/dev/null 2>&1 \
            && notify "已连接" "$sel" || notify "连接失败" "$sel"
    fi
}

case "${1:---bar}" in
    --bar)   print_bar ;;
    --text)  print_bar --text ;;
    toggle)  do_toggle ;;
    menu)    do_menu ;;
    status)  status ;;
    *) printf 'bluetooth.sh: 未知参数 %s\n' "$1" >&2; exit 2 ;;
esac
