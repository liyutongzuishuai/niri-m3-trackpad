#!/usr/bin/env bash
# waybar-m3 · scripts/wifi.sh
#
# Wi-Fi 开关与状态。本机 /dev/rfkill 不存在（rfkill 用不了），所以一律走 NetworkManager。
#
#   --bar / --text   给 waybar 用（--bar 输出 JSON，--text 只输出图标）
#   toggle           开 / 关 Wi-Fi
#   menu             fuzzel 里选一个网络并连接
#   status           on / off / na（供别的脚本调用）
#
# 解析全部加 LC_ALL=C：nmcli 的 ACTIVE 列在中文环境是「是 / 否」，
# 只有 C locale 才是稳定的 yes / no。实测本机 IN-USE 列一直是空字符串，
# 所以用 ACTIVE 而不是 IN-USE —— 这一点踩过，记在这里。

set -u
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
. "$SCRIPT_DIR/lib.sh"

ICO_ON=$'\ue63e'   # wifi
ICO_OFF=$'\ue648'  # wifi_off

# ── 状态 ────────────────────────────────────────────────────

status() {
    if ! has nmcli; then printf 'na'; return; fi
    case "$(LC_ALL=C nmcli -t -f WIFI g 2>/dev/null)" in
        enabled)  printf 'on'  ;;
        disabled) printf 'off' ;;
        *)        printf 'na'  ;;
    esac
}

# 当前连着的 Wi-Fi → "SSID<TAB>信号%"，没连上则什么都不输出
connected() {
    LC_ALL=C nmcli -t -f ACTIVE,SSID,SIGNAL device wifi list --rescan no 2>/dev/null \
        | awk -F: '$1=="yes" && $2!="" {print $2 "\t" $3; exit}'
}

# ── 输出 ────────────────────────────────────────────────────

print_bar() {
    local st ssid sig text cls tip
    st=$(status)
    case "$st" in
        on)
            text=$ICO_ON
            cls="on"
            IFS=$'\t' read -r ssid sig < <(connected)
            if [ -n "${ssid:-}" ]; then
                tip=$(printf 'Wi-Fi：%s\n信号 %s%%\n左键：关闭 Wi-Fi\n右键：选择网络' \
                      "$ssid" "${sig:-?}")
            else
                tip=$'Wi-Fi：已开启（未连接）\n左键：关闭 Wi-Fi\n右键：选择网络'
            fi ;;
        off)
            text=$ICO_OFF
            cls="off"
            tip=$'Wi-Fi：已关闭\n左键：开启 Wi-Fi' ;;
        *)
            text=$ICO_OFF
            cls="na"
            tip=$'Wi-Fi：不可用\n（没有 nmcli 或没有无线设备）' ;;
    esac

    if [ "${1:-}" = "--text" ]; then
        printf '%s' "$text"
    else
        json_emit "$cls" "$text" "$tip"
    fi
}

# ── 动作 ────────────────────────────────────────────────────

do_toggle() {
    case "$(status)" in
        on)
            if nmcli radio wifi off >/dev/null 2>&1; then
                notify "Wi-Fi 已关闭" ""
            else
                notify "关闭 Wi-Fi 失败" "看看 nmcli radio wifi off 的输出"
            fi ;;
        off)
            if nmcli radio wifi on >/dev/null 2>&1; then
                notify "Wi-Fi 已开启" "正在连接上次的网络…"
            else
                notify "开启 Wi-Fi 失败" "看看 nmcli radio wifi on 的输出"
            fi ;;
        *)
            notify "Wi-Fi 不可用" "没有找到 nmcli 或无线设备" ;;
    esac
}

do_menu() {
    if ! has fuzzel; then notify "缺少 fuzzel" "装 fuzzel 才能选网络"; return; fi
    local tmp ssid sel
    local -a flags
    m3_mktempdir
    tmp="$M3_TMPDIR"

    # SSID 里可能有冒号，用贪婪匹配从右边切掉 SIGNAL 一列
    while IFS= read -r line; do
        [[ $line =~ ^(.*):([0-9]+)$ ]] || continue
        ssid="${BASH_REMATCH[1]}"
        [ -n "$ssid" ] || continue
        printf '%s\t%s\n' "${BASH_REMATCH[2]}" "$ssid" >>"$tmp/raw"
    done < <(LC_ALL=C nmcli -t -f SSID,SIGNAL device wifi list --rescan yes 2>/dev/null)

    if [ ! -s "$tmp/raw" ]; then
        notify "没有扫描到网络" "确认无线网卡没被关掉"
        return 0
    fi

    # 信号从强到弱，同名只留最强的那个
    sort -rn "$tmp/raw" | awk -F'\t' '!seen[$2]++ {printf "%s\t%s  ·  %s%%\n", $2, $2, $1}' \
        >"$tmp/menu"

    mapfile -t flags < <(fuzzel_theme_flags 40 10 top-right)
    sel=$(cut -f2- "$tmp/menu" \
          | fuzzel "${flags[@]}" --dmenu --prompt="Wi-Fi " --placeholder="选择网络") || return 0
    [ -n "${sel:-}" ] || return 0

    ssid=$(awk -F'\t' -v d="$sel" '$2==d {print $1; exit}' "$tmp/menu")
    [ -n "${ssid:-}" ] || return 0

    if LC_ALL=C nmcli --wait 25 device wifi connect "$ssid" >/dev/null 2>&1; then
        notify "已连接" "$ssid"
    else
        notify "连接失败" "$ssid"
    fi
}

# ── 入口 ────────────────────────────────────────────────────
case "${1:---bar}" in
    --bar)   print_bar ;;
    --text)  print_bar --text ;;
    toggle)  do_toggle ;;
    menu)    do_menu ;;
    status)  status ;;
    *) printf 'wifi.sh: 未知参数 %s\n' "$1" >&2; exit 2 ;;
esac
