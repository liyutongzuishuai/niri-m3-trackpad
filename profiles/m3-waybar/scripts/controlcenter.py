#!/usr/bin/env python3
# waybar-m3 · scripts/controlcenter.py
#
# 图形控制中心：GTK3 + gtk-layer-shell，贴屏幕右上角，样式照 design.html 第 5 节 1:1 还原。
#
#   controlcenter.py            打开面板
#
# 和 fuzzel 版的区别：设计稿是「2×2 开关卡 + 真滑块 + 电量卡 + 网络列表」的卡片面板，
# fuzzel 只能弹一列文本，做不出这个结构。这里用 GTK 真控件画：
#   · 开关卡   点击即切，卡面颜色/图标/副标题即时更新
#   · 滑块     真的 Gtk.Scale，可拖动，松手才写系统（避免拖动时每像素都调一次）
#   · 网络行   点击连接
#   · 底部     锁定 / 注销 / 重启
#
# 颜色全部从 colors.css 读，不在本文件里写死任何十六进制值。
# 尺寸照 design.html：面板 376px 宽、圆角 26px、内边距 16px；
#   卡片圆角 20px、滑块轨道 12px、手柄 4×24、页脚按钮圆角 16px。

from __future__ import annotations

import os
import re
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
COLORS = os.path.join(ROOT, "colors.css")


# ── 颜色 ─────────────────────────────────────────────────────
def load_palette() -> dict[str, str]:
    """按角色名读 colors.css，别名再解析一层。"""
    pal: dict[str, str] = {}
    alias: dict[str, str] = {}
    try:
        raw = open(COLORS, encoding="utf-8").read()
    except OSError:
        raw = ""
    for line in raw.splitlines():
        m = re.match(r"\s*@define-color\s+(\S+)\s+([^;]+);", line)
        if not m:
            continue
        name, val = m.group(1), m.group(2).strip()
        (alias if val.startswith("@") else pal)[name] = val
    for k, v in alias.items():
        pal[k] = pal.get(v.lstrip("@"), "#F2B8B5")
    return pal


PAL = load_palette()


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 8:
        h = h[:6]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgba(role: str, alpha: float) -> str:
    r, g, b = hex_rgb(PAL.get(role, "#F2B8B5"))
    return f"rgba({r},{g},{b},{alpha:.3f})"


def solid(role: str) -> str:
    return PAL.get(role, "#F2B8B5")


# ── 图标码点（Material Symbols Rounded）────────────────────────
def I(cp: str) -> str:
    return chr(int(cp, 16))


ICO = {
    "wifi": I("e63e"), "wifi_off": I("e648"),
    "signal_wifi_4_bar": I("e1d8"), "signal_wifi_off": I("e1da"),
    "bluetooth": I("e1a7"), "bluetooth_connected": I("e1a8"),
    "bluetooth_disabled": I("e1a9"),
    "dnd_on": I("e15c"), "dnd_off": I("e643"),
    "nightlight": I("ef5e"),
    "volume": I("e050"), "brightness": I("e1ad"),
    "battery_charging": I("e1a3"), "battery_5": I("ebd4"),
    "battery_alert": I("e19c"), "battery_full": I("e1a4"),
    "bolt": I("ea0b"), "lock": I("e88d"), "logout": I("e9ba"),
    "restart": I("f053"), "close": I("e14c"), "check": I("e5ca"),
    "toggle_on": I("e9f6"), "toggle_off": I("e9f5"),
    # 性能模式三档：码点用 tools/find-icon.py 查实，且未被 Nerd Font 抢占
    #   eco     = eco 叶子（节能）
    #   balance = battery_saver 电池（平衡）
    #   rocket  = bolt 闪电（性能）—— 语义上「满血」也比速度计直白
    # 注：rocket_launch / balance / scale / trending_up 都被 Nerd Font 占用了，
    # 虽然指定了字体族能正确渲染，但留个安全的更稳。
    "eco": I("ea35"),
    "balance": I("efde"),
    "rocket": I("ea0b"),
}


# ── 系统状态 ─────────────────────────────────────────────────
def run(cmd: str, timeout: float = 6.0) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception:
        return ""


def battery() -> tuple[int, str]:
    cap = "—"
    try:
        cap = open("/sys/class/power_supply/BAT0/capacity").read().strip()
    except OSError:
        pass
    st = ""
    try:
        st = open("/sys/class/power_supply/BAT0/status").read().strip()
    except OSError:
        pass
    return (int(cap) if cap.isdigit() else -1), st


def battery_word(st: str) -> str:
    return {"Charging": "充电中", "Discharging": "放电中", "Full": "已充满",
            "Not charging": "未充电"}.get(st, st)


def wifi_on() -> bool:
    return run("LC_ALL=C nmcli -t -f WIFI g").strip() == "enabled"


def wifi_current() -> tuple[str, int]:
    for ln in run("LC_ALL=C nmcli -t -f ACTIVE,SSID,SIGNAL device wifi list "
                  "--rescan no").splitlines():
        p = ln.split(":", 2)
        if len(p) == 3 and p[0] == "yes" and p[1]:
            try:
                return p[1], int(p[2])
            except ValueError:
                return p[1], 0
    return "", 0


def wifi_networks(limit: int = 5) -> list[tuple[str, int]]:
    seen: dict[str, int] = {}
    for ln in run("LC_ALL=C nmcli -t -f SSID,SIGNAL device wifi list "
                  "--rescan no").splitlines():
        m = re.match(r"^(.*):(\d+)$", ln)
        if not m:
            continue
        ssid, sig = m.group(1), int(m.group(2))
        if ssid and (ssid not in seen or sig > seen[ssid]):
            seen[ssid] = sig
    cur, _ = wifi_current()
    items = sorted(seen.items(), key=lambda kv: -kv[1])
    if cur:
        items = [i for i in items if i[0] == cur] + [i for i in items if i[0] != cur]
    return items[:limit]


def bt_adapter() -> bool:
    return bool(run("timeout 2 bluetoothctl list").strip())


def bt_on() -> bool:
    return "Powered: yes" in run("timeout 2 bluetoothctl show")


def bt_name() -> str:
    out = run("timeout 2 bluetoothctl devices Connected")
    for ln in out.splitlines():
        if ln.startswith("Device"):
            parts = ln.split(" ", 2)
            if len(parts) == 3:
                return parts[2].strip()
    return ""


def dnd_on() -> bool:
    return "do-not-disturb" in run("makoctl mode")


def night_on() -> bool:
    return bool(run("pgrep -x wlsunset").strip())


def volume_pct() -> int:
    out = run("pactl get-sink-volume @DEFAULT_SINK@")
    m = re.search(r"(\d+)%", out)
    return int(m.group(1)) if m else 0


def brightness_pct() -> int:
    out = run("brightnessctl -m")
    parts = out.strip().split(",")
    if len(parts) >= 4:
        try:
            return int(parts[3].rstrip("%"))
        except ValueError:
            pass
    return 0


# ── 性能模式 ─────────────────────────────────────────────────
# 本机没有 power-profiles-daemon，但装了 tuned，而且它的 polkit 规则
# com.redhat.tuned.switch_profile 的 allow_active=yes —— 普通用户不用密码就能切。
# tuned 会一次把 platform_profile / governor / EPP 都改好（实测三档都对）。
#
#   节能 → powersave            platform_profile=low-power   governor=powersave
#   平衡 → balanced             platform_profile=balanced    EPP=balance_performance
#   性能 → throughput-performance  platform_profile=performance governor=performance
POWER_MODES = [
    ("eco", "节能", "powersave"),
    ("balance", "平衡", "balanced"),
    ("rocket", "性能", "throughput-performance"),
]


def power_mode() -> str:
    """返回 eco / balance / rocket，判断不了就给 balance。"""
    active = run("tuned-adm active")
    m = re.search(r":\s*(\S+)", active)
    name = m.group(1) if m else ""
    for key, _label, profile in POWER_MODES:
        if name == profile:
            return key
    # tuned 没在跑时退回直接读 platform_profile
    try:
        pp = open("/sys/firmware/acpi/platform_profile").read().strip()
    except OSError:
        pp = ""
    return {"low-power": "eco", "quiet": "eco",
            "balanced": "balance",
            "performance": "rocket"}.get(pp, "balance")


def power_label(key: str) -> str:
    for k, label, _p in POWER_MODES:
        if k == key:
            return label
    return "平衡"


def power_set(key: str) -> bool:
    profile = next((p for k, _l, p in POWER_MODES if k == key), None)
    if not profile:
        return False
    if not has("tuned-adm"):
        return False
    # tuned-adm 走 polkit，普通用户即可；失败不抛异常，交给调用方提示
    out = run(f"timeout 25 tuned-adm profile {profile}", 30)
    return "failed" not in out.lower() and "error" not in out.lower()


def power_available() -> bool:
    return has("tuned-adm") or os.path.exists("/sys/firmware/acpi/platform_profile")


def has(cmd: str) -> bool:
    return bool(run(f"command -v {cmd}").strip())


# ── CSS ──────────────────────────────────────────────────────
def build_css() -> str:
    """尺寸/圆角/字号照 design.html 的 .cc / .tile / .pslider / .bcard / .lrow / .foot-btn。"""
    return f"""
window {{ background: transparent; }}

/* 这个窗口是 RGBA + layer-shell，窗口本身没有底色。
   design.html 里卡片用 0.95 透明度，是因为底下已经铺了一层不透明面板；
   这里没有那层，所以卡片必须用实色，否则壁纸上的文字会透上来。 */
.cc {{
    background-color: {solid('surface_container_high')};
    border: 1px solid {rgba('outline_variant', 1.0)};
    border-radius: 26px;
    padding: 16px;
}}
.mi {{ font-family: "Material Symbols Rounded"; font-size: 22px;
       padding: 0; margin: 0; }}
label {{ padding: 0; margin: 0; }}
.lbl {{ font-family: "Roboto"; }}
.dim {{ color: {solid('on_surface_variant')}; }}

/* 标题栏 */
.hdr {{ margin-bottom: 14px; }}
.title {{ font-family: "Roboto"; font-size: 19px; font-weight: 500;
          color: {solid('on_surface')}; }}
.date  {{ font-family: "Roboto"; font-size: 12px;
          color: {solid('on_surface_variant')}; }}
.close {{ color: {solid('on_surface_variant')}; font-size: 20px;
          padding: 2px 4px; border-radius: 10px; }}
.close:hover {{ background-color: {rgba('on_surface', 0.08)}; }}

/* 2×2 开关卡 */
.tile {{
    background-color: {solid('surface_container')};
    border: 1px solid transparent;
    border-radius: 20px;
    padding: 10px;
}}
.tile:hover {{ background-color: {solid('surface_container_highest')}; }}
.tile.on {{
    background-color: {solid('primary')};
    color: {solid('on_primary')};
}}
.tile.on:hover {{ background-color: {solid('primary')}; }}
.tile.on .t-label, .tile.on .t-sub {{ color: {solid('on_primary')}; }}
.t-ico {{ font-size: 22px; }}
.t-label {{ font-family: "Roboto"; font-size: 13px; font-weight: 500;
            color: {solid('on_surface')}; }}
.t-sub {{ font-family: "Roboto"; font-size: 11px;
          color: {solid('on_surface_variant')}; }}
.t-state {{ font-size: 20px; color: {solid('on_surface_variant')};
            padding-right: 2px; }}
.tile.on .t-state, .tile.on .t-ico {{ color: {solid('on_primary')}; }}

/* 滑块 */
.pslider {{ min-height: 26px; }}
.pslider .mi {{ font-size: 18px; color: {solid('on_surface_variant')}; }}
.pval {{ font-family: "Roboto"; font-size: 11px;
         color: {solid('on_surface_variant')}; }}

scale trough {{
    background-color: {rgba('secondary_container', 0.92)};
    min-height: 12px; border-radius: 6px; border: none;
}}
scale highlight {{ background-color: {solid('primary')};
                  border-radius: 6px; border: none; }}
/* 手柄 4×24：GTK3 会把 slider 高度算进控件高度，用负 margin 让它溢出细轨道 */
scale slider {{
    background-color: {solid('primary')};
    background-image: none; box-shadow: none;
    min-width: 4px; min-height: 24px;
    border-radius: 2px; border: none;
    margin: -6px 0;
}}
scale slider:hover {{ background-color: {solid('on_primary_container')}; }}

/* 电量卡 */
.bcard {{
    background-color: {solid('surface_container')};
    border-radius: 20px; padding: 10px 14px;
    margin-bottom: 12px;
}}
.b-ico {{ font-size: 26px; color: {solid('on_surface')}; }}
.bnum {{ font-family: "Roboto"; font-size: 22px; font-weight: 500;
         color: {solid('on_surface')}; }}
.bsub {{ font-family: "Roboto"; font-size: 11px;
         color: {solid('on_surface_variant')}; }}
.chip .mi {{ font-size: 14px; }}
.chip-txt {{ font-family: "Roboto"; font-size: 11px; }}
.chip {{ font-family: "Roboto"; font-size: 11px;
         background-color: {solid('surface_container_highest')};
         color: {solid('on_surface_variant')};
         border-radius: 12px; padding: 4px 9px; }}
.chip:hover {{ background-image: linear-gradient(rgba(255,255,255,0.10),
                                                 rgba(255,255,255,0.10)); }}
/* 性能模式胶囊：三档用实色底 + 高对比前景，保证在深色卡片上看得清。
   （一开始用 tertiary_container 0.55 透明，结果和卡片几乎同色，图标糊掉。） */
.mode-eco     {{ background-color: {solid('tertiary_container')};
                 color: {solid('on_tertiary_container')}; }}
.mode-balance {{ background-color: {solid('secondary_container')};
                 color: {solid('on_secondary_container')}; }}
.mode-rocket  {{ background-color: {solid('primary_container')};
                 color: {solid('on_primary_container')}; }}


/* 网络列表 */
.plist {{ background-color: {solid('surface_container')};
          border-radius: 20px; padding: 8px 6px; margin-bottom: 12px; }}
.plist-h {{ font-family: "Roboto"; font-size: 12px;
            color: {solid('on_surface_variant')}; padding: 2px 10px 7px; }}
.lrow {{ border-radius: 12px; padding: 7px 10px; }}
.lrow:hover {{ background-color: {rgba('on_surface', 0.06)}; }}
.lrow.active {{ background-color: {rgba('primary', 0.20)}; }}
.lrow .mi {{ font-size: 17px; color: {solid('on_surface_variant')}; }}
.lrow.active .mi {{ color: {solid('primary')}; }}
.lname {{ font-family: "Roboto"; font-size: 13px; color: {solid('on_surface')}; }}
.lsig  {{ font-family: "Roboto"; font-size: 11px;
          color: {solid('on_surface_variant')}; }}
.lcheck {{ color: {solid('primary')}; font-size: 17px; }}
.empty {{ font-family: "Roboto"; font-size: 12px;
          color: {solid('on_surface_variant')}; padding: 6px 10px; }}

/* 页脚 */
.foot-btn {{
    background-color: {solid('surface_container')};
    color: {solid('on_surface_variant')};
    border-radius: 16px; padding: 9px;
    font-family: "Roboto"; font-size: 12px;
}}
.foot-btn:hover {{ background-color: {solid('surface_container_highest')}; }}
.foot-btn .mi {{ font-size: 17px; }}
"""


def icon_label(glyph: str, cls: str = "mi") -> Gtk.Label:
    """图标标签。始终带上 mi 类（Material Symbols 字体族）。

    只加尺寸类不加 mi 会掉到默认字体 —— 本机 Nerd Font 也声明了
    U+EBD4 / U+E63E 等码点，于是渲染成 Nerd 的图标（实测踩过：
    电量卡显示成一个层叠状的怪符号）。
    """
    lbl = Gtk.Label(label=glyph)
    ctx = lbl.get_style_context()
    ctx.add_class("mi")
    if cls and cls != "mi":
        ctx.add_class(cls)
    return lbl


def text_label(text: str, cls: str) -> Gtk.Label:
    lbl = Gtk.Label(label=text)
    lbl.get_style_context().add_class(cls)
    lbl.set_xalign(0.0)
    return lbl


class Tile(Gtk.EventBox):
    """一张开关卡：图标 + 标题 + 副标题 + 右侧开关字形。整卡可点。"""

    def __init__(self, icon: str, label: str, on_click):
        super().__init__()
        self.get_style_context().add_class("tile")
        # visible_window=True：EventBox 只有真窗口才会绘制 CSS 的 background。
        # 设成 False 时卡片完全没有底色，壁纸会直接透上来（实测踩过）。
        self.set_visible_window(True)

        row = Gtk.Box(spacing=8)
        row.set_margin_top(0)
        self.add(row)

        self.ico = icon_label(icon)
        row.pack_start(self.ico, False, False, 0)

        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        txt.set_valign(Gtk.Align.CENTER)
        self.label_lbl = text_label(label, "t-label")
        self.sub_lbl = text_label("", "t-sub")
        self.sub_lbl.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self.sub_lbl.set_max_width_chars(14)
        txt.pack_start(self.label_lbl, False, False, 0)
        txt.pack_start(self.sub_lbl, False, False, 0)
        row.pack_start(txt, True, True, 0)

        self.state = icon_label(ICO["toggle_off"], "t-state")
        self.state.set_valign(Gtk.Align.CENTER)
        row.pack_end(self.state, False, False, 0)

        self.connect("button-release-event", lambda *_: (on_click(), True)[1])

    def update(self, icon: str, sub: str, on: bool, enabled: bool = True) -> None:
        ctx = self.get_style_context()
        if on:
            ctx.add_class("on")
        else:
            ctx.remove_class("on")
        self.ico.set_text(icon)
        self.sub_lbl.set_text(sub)
        self.state.set_text(ICO["toggle_on"] if on else ICO["toggle_off"])
        self.set_sensitive(enabled)
        self.set_tooltip_text(sub)


class Slider(Gtk.Box):
    """图标 + 真 Gtk.Scale + 右侧百分比。松手才写系统。"""

    def __init__(self, icon: str, lo: int, hi: int, on_commit):
        super().__init__(spacing=10)
        self.get_style_context().add_class("pslider")
        self.on_commit = on_commit
        self._setting = False

        self.pack_start(icon_label(icon), False, False, 0)

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
        self.scale.set_draw_value(False)
        self.scale.set_increments(1, 5)
        self.scale.set_hexpand(True)
        self.scale.set_valign(Gtk.Align.CENTER)
        self.scale.connect("value-changed", self._changed)
        self.scale.connect("button-release-event", self._commit)
        self.pack_start(self.scale, True, True, 0)

        self.val = text_label("", "pval")
        self.val.set_xalign(1.0)
        self.val.set_size_request(32, -1)
        self.pack_end(self.val, False, False, 0)

    def set_value(self, v: int) -> None:
        """从系统状态回填滑块。不应触发写回，也不该让标签闪成中间值。"""
        self._setting = True
        self.scale.set_value(v)
        # GTK 的 value-changed 是异步派发的：set_value 返回时信号可能还没跑。
        # 这里显式把标签按目标值写好，并留一个 idle 回调兜住迟到的信号。
        self.val.set_text(f"{int(v)}%")
        GLib.idle_add(self._finish_setting)

    def _finish_setting(self) -> bool:
        self._setting = False
        self.val.set_text(f"{int(self.scale.get_value())}%")
        return False

    def _changed(self, sc) -> None:
        if self._setting:
            return
        self.val.set_text(f"{int(sc.get_value())}%")

    def _commit(self, *_a) -> bool:
        self.on_commit(int(self.scale.get_value()))
        return False


class ControlCenter:
    def __init__(self) -> None:
        self.win = Gtk.Window()
        self.win.set_decorated(False)
        self.win.set_resizable(False)
        self.win.set_skip_taskbar_hint(True)
        self.win.set_skip_pager_hint(True)

        # RGBA：圆角外面必须是透明的
        screen = self.win.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.win.set_visual(visual)
        self.win.set_app_paintable(True)

        GtkLayerShell.init_for_window(self.win)
        GtkLayerShell.set_layer(self.win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self.win, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self.win, GtkLayerShell.Edge.RIGHT, True)
        # bar 40px + 8px 间隙；右边 16px 与 bar 的内边距对齐
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.TOP, 46)
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.RIGHT, 16)
        GtkLayerShell.set_keyboard_interactivity(
            self.win, GtkLayerShell.KeyboardMode.ON_DEMAND)

        prov = Gtk.CssProvider()
        prov.load_from_data(build_css().encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            screen, prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._build()

        self.win.connect("key-press-event", self._on_key)
        self.win.connect("focus-out-event", lambda *_: (self.quit(), False)[1])
        self.refresh()

    # ── UI ────────────────────────────────────────────────
    def _build(self) -> None:
        outer = Gtk.Box()
        outer.get_style_context().add_class("cc")
        self.win.add(outer)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        col.set_size_request(344, -1)  # 376 - 16*2 padding
        outer.pack_start(col, True, True, 0)

        # 标题栏
        hdr = Gtk.Box(spacing=10)
        hdr.get_style_context().add_class("hdr")
        hdr.pack_start(text_label("控制中心", "title"), False, False, 0)
        self.date_lbl = text_label("", "date")
        self.date_lbl.set_valign(Gtk.Align.CENTER)
        hdr.pack_start(self.date_lbl, False, False, 0)

        close = Gtk.EventBox()
        close.set_visible_window(True)
        close.get_style_context().add_class("close")
        close.add(icon_label(ICO["close"], "mi"))
        close.connect("button-release-event", lambda *_: (self.quit(), True)[1])
        hdr.pack_end(close, False, False, 0)
        col.pack_start(hdr, False, False, 0)

        # 2×2 开关卡
        grid = Gtk.Grid()
        grid.set_margin_top(0)
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        grid.set_hexpand(True)
        grid.set_column_spacing(8)
        grid.set_row_spacing(8)
        self.tile_wifi = Tile(ICO["wifi"], "Wi-Fi", self.toggle_wifi)
        self.tile_bt = Tile(ICO["bluetooth"], "蓝牙", self.toggle_bt)
        self.tile_dnd = Tile(ICO["dnd_on"], "勿扰", self.toggle_dnd)
        self.tile_night = Tile(ICO["nightlight"], "夜览", self.toggle_night)
        grid.attach(self.tile_wifi, 0, 0, 1, 1)
        grid.attach(self.tile_bt, 1, 0, 1, 1)
        grid.attach(self.tile_dnd, 0, 1, 1, 1)
        grid.attach(self.tile_night, 1, 1, 1, 1)
        col.pack_start(grid, False, False, 0)

        # 滑块
        sl = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.sl_vol = Slider(ICO["volume"], 0, 100, self.set_volume)
        self.sl_bri = Slider(ICO["brightness"], 0, 100, self.set_brightness)
        sl.pack_start(self.sl_vol, False, False, 0)
        sl.pack_start(self.sl_bri, False, False, 0)
        col.pack_start(sl, False, False, 0)

        # 电量卡
        bcard = Gtk.Box(spacing=10)
        bcard.get_style_context().add_class("bcard")
        self.b_ico = icon_label(ICO["battery_5"], "b-ico")
        bcard.pack_start(self.b_ico, False, False, 0)
        self.b_num = text_label("—", "bnum")
        self.b_num.set_xalign(0.0)
        bcard.pack_start(self.b_num, False, False, 0)
        self.b_sub = text_label("", "bsub")
        self.b_sub.set_ellipsize(3)
        bcard.pack_start(self.b_sub, True, True, 0)
        # 性能模式胶囊（设计稿里是「节电」静态 chip，这里做成可点循环切换）
        # 节能 → 平衡 → 性能 → 节能…，颜色随档位变（节能绿 / 平衡中性 / 性能橙）
        self.mode_chip = Gtk.EventBox()
        self.mode_chip.set_visible_window(True)
        self.mode_chip.get_style_context().add_class("chip")
        self.mode_chip.get_style_context().add_class("mode-eco")
        chiprow = Gtk.Box(spacing=3)
        self.mode_ico = icon_label(ICO["eco"], "chip-ico")
        self.mode_txt = text_label("节能", "chip-txt")
        chiprow.pack_start(self.mode_ico, False, False, 0)
        chiprow.pack_start(self.mode_txt, False, False, 0)
        self.mode_chip.add(chiprow)
        self.mode_chip.connect(
            "button-release-event",
            lambda *_: (self.cycle_power_mode(), True)[1])
        self.mode_chip.set_tooltip_text(
            "性能模式：点击切换 节能 → 平衡 → 性能")
        bcard.pack_end(self.mode_chip, False, False, 0)
        col.pack_start(bcard, False, False, 0)

        # 网络列表
        self.plist = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.plist.get_style_context().add_class("plist")
        ph = Gtk.Box(spacing=7)
        ph.get_style_context().add_class("plist-h")
        ph.pack_start(icon_label(ICO["wifi"]), False, False, 0)
        ph.pack_start(text_label("可用网络", "plist-h"), False, False, 0)
        self.plist.pack_start(ph, False, False, 0)
        self.net_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.plist.pack_start(self.net_box, False, False, 0)
        col.pack_start(self.plist, False, False, 0)

        # 页脚
        foot = Gtk.Box(spacing=8)
        for glyph, text, cb in (
            (ICO["lock"], "锁定", self.do_lock),
            (ICO["logout"], "注销", self.do_logout),
            (ICO["restart"], "重启", self.do_reboot),
        ):
            btn = Gtk.EventBox()
            btn.set_visible_window(True)
            btn.get_style_context().add_class("foot-btn")
            box = Gtk.Box(spacing=5)
            box.set_halign(Gtk.Align.CENTER)
            box.pack_start(icon_label(glyph), False, False, 0)
            box.pack_start(text_label(text, "foot-btn"), False, False, 0)
            btn.add(box)
            btn.connect("button-release-event",
                        lambda _w, _e, f=cb: (f(), True)[1])
            foot.pack_start(btn, True, True, 0)
        col.pack_start(foot, False, False, 0)

    # ── 状态刷新 ───────────────────────────────────────────
    def refresh(self) -> None:
        self.date_lbl.set_text(run("date '+%m月%d日'").strip() and
                              run("date '+%m月%d日 '").strip() +
                              "周" + "一二三四五六日"[int(run("date +%u").strip() or 1) - 1])

        # Wi-Fi
        on = wifi_on()
        ssid, sig = wifi_current()
        sub = (f"{ssid} · 信号 {sig}%" if ssid else "已开启") if on else "已关闭"
        self.tile_wifi.update(ICO["wifi"] if on else ICO["wifi_off"], sub, on)

        # 蓝牙
        if not bt_adapter():
            self.tile_bt.update(ICO["bluetooth_disabled"], "无适配器", False, enabled=False)
        else:
            b_on = bt_on()
            name = bt_name()
            self.tile_bt.update(
                ICO["bluetooth_connected"] if name else ICO["bluetooth"],
                name or ("已开启" if b_on else "已关闭"), b_on)

        d = dnd_on()
        self.tile_dnd.update(ICO["dnd_on"] if d else ICO["dnd_off"],
                             "已开启" if d else "关闭", d)

        n = night_on()
        self.tile_night.update(ICO["nightlight"], "已开启" if n else "关闭", n)

        self.sl_vol.set_value(volume_pct())
        self.sl_bri.set_value(brightness_pct())

        cap, st = battery()
        charging = st in ("Charging", "Full")
        if cap >= 0:
            if charging:
                ico = ICO["battery_charging"]
            elif cap <= 15:
                ico = ICO["battery_alert"]
            elif cap >= 95:
                ico = ICO["battery_full"]
            else:
                ico = ICO["battery_5"]
            self.b_ico.set_text(ico)
            self.b_num.set_text(f"{cap}%")
            self.b_sub.set_text(self._battery_detail(cap, st))
        else:
            self.b_num.set_text("—")
            self.b_sub.set_text("没有电池")

        self._update_mode_chip()
        self._refresh_networks(ssid if on else "")

    def _update_mode_chip(self) -> None:
        key = power_mode()
        ctx = self.mode_chip.get_style_context()
        for cls in ("mode-eco", "mode-balance", "mode-rocket"):
            ctx.remove_class(cls)
        ctx.add_class(f"mode-{key}")
        self.mode_ico.set_text(ICO[key])
        self.mode_txt.set_text(power_label(key))
        self.mode_chip.set_sensitive(power_available())

    def cycle_power_mode(self) -> None:
        """节能 → 平衡 → 性能 → 节能。tuned 走 polkit，不需要密码。"""
        if not power_available():
            return
        order = [k for k, _l, _p in POWER_MODES]
        cur = power_mode()
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else order[0]
        if power_set(nxt):
            self._update_mode_chip()
            GLib.timeout_add(1500, lambda: (self._update_mode_chip(), False)[1])
        else:
            # 切失败（polkit 拒绝 / tuned 没装）就把界面退回真实状态
            self._update_mode_chip()

    def _battery_detail(self, cap: int, status: str) -> str:
        """副标题：优先给剩余时间，拿不到就退回状态词。"""
        word = battery_word(status)
        if status == "Charging":
            return word
        if status == "Full":
            return "已充满"
        out = run("upower -i /org/freedesktop/UPower/devices/battery_BAT0")
        for ln in out.splitlines():
            if "time to empty" in ln:
                val = ln.split(":", 1)[1].strip()
                if val and "0 seconds" not in val:
                    return f"预计可用 {val}"
        return word or "—"

    def _refresh_networks(self, current: str) -> None:
        for child in self.net_box.get_children():
            self.net_box.remove(child)
        if not wifi_on():
            self.net_box.pack_start(text_label("Wi-Fi 已关闭", "empty"), False, False, 0)
            self.net_box.show_all()
            return
        nets = wifi_networks(5)
        if not nets:
            self.net_box.pack_start(text_label("没扫描到网络", "empty"), False, False, 0)
            self.net_box.show_all()
            return
        for ssid, sig in nets:
            row = Gtk.EventBox()
            row.set_visible_window(True)
            row.get_style_context().add_class("lrow")
            if ssid == current:
                row.get_style_context().add_class("active")
            box = Gtk.Box(spacing=9)
            glyph = (ICO["wifi"] if sig >= 70
                     else ICO["signal_wifi_4_bar"] if sig >= 40
                     else ICO["signal_wifi_off"])
            box.pack_start(icon_label(glyph), False, False, 0)
            name = text_label(ssid, "lname")
            name.set_ellipsize(3)
            box.pack_start(name, True, True, 0)
            if ssid == current:
                box.pack_start(icon_label(ICO["check"], "lcheck"), False, False, 0)
            box.pack_end(text_label(f"{sig}%", "lsig"), False, False, 0)
            row.add(box)
            row.connect("button-release-event",
                        lambda _w, _e, s=ssid: (self.connect_wifi(s), True)[1])
            self.net_box.pack_start(row, False, False, 0)
        self.net_box.show_all()

    # ── 动作 ──────────────────────────────────────────────
    def toggle_wifi(self) -> None:
        run("nmcli radio wifi " + ("off" if wifi_on() else "on"), 15)
        self.after(400)

    def toggle_bt(self) -> None:
        if not bt_adapter():
            return
        run("timeout 10 bluetoothctl power " + ("off" if bt_on() else "on"), 15)
        self.after(600)

    def toggle_dnd(self) -> None:
        if has("makoctl"):
            run("makoctl mode -t do-not-disturb")
            self.after(200)

    def toggle_night(self) -> None:
        if night_on():
            run("pkill -x wlsunset")
        elif has("wlsunset"):
            subprocess.Popen(["setsid", "wlsunset", "-t", "4000", "-T", "6500"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.after(500)

    def connect_wifi(self, ssid: str) -> None:
        run(f'LC_ALL=C nmcli --wait 25 device wifi connect "{ssid}"', 30)
        self.after(800)

    def set_volume(self, v: int) -> None:
        if has("wpctl"):
            run(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {v}%")
        else:
            run(f"pactl set-sink-volume @DEFAULT_SINK@ {v}%")

    def set_brightness(self, v: int) -> None:
        run(f"brightnessctl set {v}%")

    def do_lock(self) -> None:
        self.quit()
        if has("swaylock"):
            subprocess.Popen(["swaylock", "-f", "-c", solid("surface")])
        else:
            run("loginctl lock-session")

    def do_logout(self) -> None:
        self.quit()
        run("niri msg action quit --skip-confirmation")

    def do_reboot(self) -> None:
        self.quit()
        run("systemctl reboot")

    def after(self, ms: int) -> None:
        GLib.timeout_add(ms, lambda: (self.refresh(), False)[1])

    def _on_key(self, _w, ev) -> bool:
        if ev.keyval == Gdk.KEY_Escape:
            self.quit()
            return True
        return False

    def quit(self) -> None:
        Gtk.main_quit()

    def run(self) -> None:
        self.win.show_all()
        Gtk.main()


def main() -> int:
    # 单实例：再点一次就是关掉（和 toggle 语义一致）
    pidfile = os.path.join(
        os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "waybar-m3-cc.pid")
    running = False
    try:
        running = os.path.exists(pidfile) and os.kill(
            int(open(pidfile).read().strip()), 0) is None
    except (OSError, ValueError):
        running = False
    if running:
        try:
            os.kill(int(open(pidfile).read().strip()), 15)
        except (OSError, ValueError):
            pass
        return 0
    with open(pidfile, "w") as fh:
        fh.write(str(os.getpid()))
    try:
        ControlCenter().run()
    finally:
        try:
            os.unlink(pidfile)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
