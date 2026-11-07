#!/usr/bin/env python3
"""waybar-m3 · tools/expand-icon-font.py

把 fonts/MaterialSymbolsRounded-subset.ttf 扩充成新的图标集。
菜单设计稿需要 wifi / 蓝牙 / 电量 / 控制中心 / 开关 / 亮度 / 媒体等图标，
原来的 subset 只有 9 个码点，不够用。

    python3 tools/expand-icon-font.py            # 就地扩充 fonts/MaterialSymbolsRounded-subset.ttf
    python3 tools/expand-icon-font.py --check    # 只校验：列出码点与名字，不写文件

码点不是猜的：从安装版的 Material Symbols 可变字体（~/.local/share/fonts/waybar-m3/）
里按 ligature 名（wifi / wifi_off / bluetooth ...）逐个查 cmap 得到。
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
SUBSET = ROOT / "fonts" / "MaterialSymbolsRounded-subset.ttf"

# 安装版可变字体的候选路径（换机器时装到别处也能找到）
FULL_FONT_CANDIDATES = [
    "~/.local/share/fonts/waybar-m3/MaterialSymbolsRounded.ttf",
    "~/.local/share/fonts/MaterialSymbolsRounded.ttf",
    "/usr/share/fonts/material-symbols/MaterialSymbolsRounded.ttf",
]

# 第一版 preview 就已经在用的码点（保持兼容）
LEGACY_CP = {
    "public": 0xE80B,
    "search": 0xEF7A,
    "mic": 0xE31D,
    "notifications": 0xE7F4,
    "volume_up": 0xE050,
    "volume_mute": 0xE04F,
    "brightness_medium": 0xE3AB,
    "music_note": 0xE3A1,
    "chat": 0xE0B7,
    "screen_share": 0xE0E2,
}

# 新设计需要的图标（ligature 名）。码点由本脚本从整字体里查出来。
# 注意：signal_wifi 只有 0/4 两档（3/2/1 档不存在），
# 信号强弱改用 wifi_1_bar / wifi_2_bar / wifi（满格）表达，和 wifi_off 成套。
WANT = {
    # wifi
    "wifi": 0, "wifi_off": 0, "wifi_1_bar": 0, "wifi_2_bar": 0,
    "signal_wifi_off": 0, "signal_wifi_4_bar": 0,
    "network_wifi": 0, "wifi_find": 0, "wifi_tethering": 0,
    # 蓝牙
    "bluetooth": 0, "bluetooth_connected": 0, "bluetooth_disabled": 0,
    # 电量
    "battery_full": 0, "battery_charging_full": 0,
    "battery_6_bar": 0, "battery_5_bar": 0, "battery_4_bar": 0,
    "battery_3_bar": 0, "battery_2_bar": 0, "battery_1_bar": 0, "battery_0_bar": 0,
    "battery_alert": 0, "battery_android_frame_full": 0, "battery_horiz_075": 0,
    "battery_horiz_000": 0, "battery_vert_050": 0,
    # 开关 / 控制中心
    "toggle_on": 0, "toggle_off": 0,
    "power_settings_new": 0, "settings": 0, "check": 0, "close": 0, "more_horiz": 0,
    "more_vert": 0, "expand_more": 0, "arrow_drop_down": 0, "link_off": 0,
    "lock": 0, "lock_open": 0, "airplanemode_active": 0, "devices": 0,
    "dark_mode": 0, "light_mode": 0, "display_settings": 0, "tv": 0,
    "fullscreen": 0, "logout": 0, "restart_alt": 0,
    "battery_profile": 0, "battery_saver": 0,
    # 控制中心里还需要的
    "tune": 0, "do_not_disturb_on": 0, "chevron_right": 0, "screenshot": 0,
    "nightlight": 0, "cast": 0, "router": 0, "headphones": 0, "watch": 0,
    "mouse": 0, "keyboard": 0, "wallpaper": 0, "wb_twilight": 0,
    "bluetooth_searching": 0, "battery_charging_50": 0, "battery_charging_80": 0,
    "notification_important": 0, "mark_unread_chat_alt": 0, "lightbulb": 0, "bolt": 0,
    # 媒体
    "play_arrow": 0, "pause": 0, "skip_next": 0, "skip_previous": 0,
    # brightness_low / volume_down 与 LEGACY_CP 的 brightness_medium / volume_up 成套
    "brightness_low": 0, "volume_down": 0,
}

DROP = ["gvar", "HVAR", "avar", "STAT", "DSIG"]


def full_font() -> TTFont:
    for cand in FULL_FONT_CANDIDATES:
        p = pathlib.Path(cand).expanduser()
        if p.is_file():
            return TTFont(p)
    sys.exit("找不到安装版 Material Symbols Rounded 字体（试过：" + ", ".join(FULL_FONT_CANDIDATES) + "）")


def resolve(font: TTFont) -> dict[str, int]:
    cmap = font.getBestCmap()
    names = set(font.getGlyphOrder())
    out, missing = {}, []
    for lig in WANT:
        if lig in names:
            for cp, gn in cmap.items():
                if gn == lig:
                    out[lig] = cp
                    break
            else:
                missing.append(lig)
        else:
            missing.append(lig)
    if missing:
        sys.exit("这些 ligature 在字体里不存在：" + ", ".join(missing))
    return out


def all_cp(font: TTFont, resolved: dict[str, int]) -> list[tuple[str, int]]:
    """全部图标（老的 + 新的）→ (ligature 名, codepoint)，按 ligature 名排序。"""
    merged = dict(LEGACY_CP)
    merged.update(resolved)
    return sorted(merged.items())


def write(cps: set[int]) -> None:
    font = full_font()
    opts = subset.Options()
    opts.flavor = None
    opts.hinting = True
    opts.notdef_outline = True
    opts.name_IDs = ["*"]
    opts.name_legacy = True
    opts.name_languages = ["*"]
    opts.glyph_names = True
    opts.legacy_kern = False
    opts.drop_tables = list(opts.drop_tables) + DROP
    ss = subset.Subsetter(options=opts)
    ss.populate(unicodes=sorted(cps))
    ss.subset(font)
    font.save(str(SUBSET))

    check = TTFont(str(SUBSET)).getBestCmap()
    if set(check) != cps:
        sys.exit(f"写入后校验失败：少了 {len(cps - set(check))} 个码点")
    print(f"已写出 {SUBSET}（{SUBSET.stat().st_size} 字节，{len(cps)} 个码点）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只打印码点表，不写文件")
    args = ap.parse_args()

    font = full_font()
    resolved = resolve(font)
    cps = set(LEGACY_CP.values()) | set(resolved.values())

    if args.check:
        print(f"共 {len(cps)} 个码点\n")
        for lig, cp in all_cp(font, resolved):
            print(f"  {lig:26s} U+{cp:04X}  {chr(cp)}")
        return

    write(cps)
    for lig, cp in all_cp(font, resolved):
        print(f"  {lig:26s} U+{cp:04X}  {chr(cp)}")


if __name__ == "__main__":
    main()
