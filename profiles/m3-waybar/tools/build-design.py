#!/usr/bin/env python3
"""waybar-m3 · tools/build-design.py

生成 design.html：把「Wi-Fi 开关 / 蓝牙开关 / 电量 / 控制中心」这套新设计
先用 HTML 画出来给用户确认。确认之后才写 config.jsonc / style.css / scripts。

设计约束（与真实配置一致，否则预览没有参考价值）：
  · 颜色只从 colors.css 读，页面里全部走 CSS 变量，不写死十六进制
  · 尺寸沿用 style.css 的 em 基准（1em = 18px）与真实内边距
    （window padding 0 0.89em = 16px，模块间距 0.44em = 8px）
  · 文案尽量取本机真实状态（nmcli / upower / pactl / brightnessctl）

    python3 tools/build-design.py
"""

from __future__ import annotations

import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
BAR_W = 1536  # 本机 eDP-1 上 waybar 的逻辑宽度（1920 物理 / 1.25 缩放）


def U(h: str) -> str:
    return chr(int(h, 16))


# Material Symbols Rounded 子集字体里的码点（tools/expand-icon-font.py 生成）
ICON = {
    # 既有
    "public": U("e80b"), "search": U("ef7a"), "mic": U("e31d"), "fedora": U("f30a"),
    # 电量
    "battery_full": U("e1a4"), "battery_charging_full": U("e1a3"),
    "battery_alert": U("e19c"), "battery_5_bar": U("ebd4"), "battery_2_bar": U("ebe0"),
    # Wi-Fi
    "wifi": U("e63e"), "wifi_off": U("e648"), "signal_wifi_4_bar": U("e1d8"),
    "signal_wifi_off": U("e1da"),
    # 蓝牙
    "bluetooth": U("e1a7"), "bluetooth_connected": U("e1a8"), "bluetooth_disabled": U("e1a9"),
    "bluetooth_searching": U("e1aa"),
    # 控制中心
    "tune": U("e429"), "settings": U("e8b8"), "close": U("e14c"), "check": U("e5ca"),
    "do_not_disturb_on": U("e15c"), "do_not_disturb_off": U("e643"),
    "airplanemode_active": U("e195"), "nightlight": U("ef5e"), "bolt": U("ea0b"),
    "volume_up": U("e050"), "volume_down": U("e04d"), "volume_off": U("e04f"),
    "brightness_low": U("e1ad"), "brightness_medium": U("e3ab"),
    "lock": U("e88d"), "logout": U("e9ba"), "restart_alt": U("f053"),
    "toggle_on": U("e9f6"), "toggle_off": U("e9f5"), "music_note": U("e3a1"),
    "headphones": U("e310"), "keyboard": U("e312"), "mouse": U("e323"),
}


# ── 颜色：从 colors.css 读，解析一层 @别名 ───────────────────────
def read_palette() -> dict[str, str]:
    pal: dict[str, str] = {}
    aliases: dict[str, str] = {}
    for line in (ROOT / "colors.css").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("@define-color"):
            continue
        parts = line.rstrip(";").split()
        if len(parts) < 3:
            continue
        name, val = parts[1], parts[2]
        (aliases if val.startswith("@") else pal)[name] = val
    for k, v in aliases.items():
        pal[k] = pal.get(v.lstrip("@"), v)
    return pal


PAL = read_palette()


def col(name: str) -> str:
    return PAL.get(name, "#000000")


# ── 真实状态探测（失败就用设计默认值，页面不能因为命令挂了就空）──────
def sh(cmd: str) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=8)
        return (r.stdout + r.stderr).strip()
    except Exception:
        return ""


def probe_state() -> dict:
    s: dict = {}

    bat = sh("upower -i /org/freedesktop/UPower/devices/battery_BAT0")
    pct = 80
    for ln in bat.splitlines():
        if "percentage" in ln:
            digits = "".join(c for c in ln if c.isdigit())
            if digits:
                pct = int(digits)
    s["battery_pct"] = pct
    s["battery_charging"] = ("pending-charge" in bat) or ("state:" in bat and "charging" in bat
                                                        and "discharging" not in bat)

    cur, nets = None, []
    for ln in sh("nmcli -t -f ACTIVE,SSID,SIGNAL device wifi list --rescan no").splitlines():
        p = ln.split(":", 3)
        if len(p) < 3 or not p[1]:
            continue
        nets.append((p[1], int(p[2] or 0)))
        if p[0] == "是" and cur is None:
            cur = (p[1], int(p[2] or 0))
    s["wifi_on"] = cur is not None
    s["wifi_ssid"] = cur[0] if cur else ""
    s["wifi_sig"] = cur[1] if cur else 0
    if cur:
        nets = [n for n in nets if n[0] == cur[0]] + [n for n in nets if n[0] != cur[0]]
    s["wifi_nets"] = nets[:5]

    s["bt_adapter"] = bool(sh("bluetoothctl list").strip())
    s["bt_powered"] = "Powered: yes" in sh("bluetoothctl show 2>/dev/null")
    s["bt_dev_name"] = ""
    if s["bt_powered"]:
        for ln in sh("bluetoothctl devices Connected 2>/dev/null").splitlines():
            if ln.startswith("Device"):
                s["bt_dev_name"] = ln.split(" ", 2)[2] if len(ln.split(" ", 2)) > 2 else ""
                break

    try:
        sinks = json.loads(sh("pactl -f json list sinks 2>/dev/null"))
        s["volume"] = int(sinks[0]["volume"]["front-left"]["value_percent"].rstrip("%"))
    except Exception:
        s["volume"] = 28

    br = sh("brightnessctl -m 2>/dev/null").split(",")
    s["brightness"] = int(br[3].rstrip("%")) if len(br) >= 4 else 100

    s["clock"] = sh("date '+%H:%M'") or "13:17"
    wd = sh("date '+%u'").strip()
    cn = {"1": "一", "2": "二", "3": "三", "4": "四", "5": "五", "6": "六", "7": "日"}
    s["date"] = sh("date '+%m月%d日'") + " 周" + cn.get(wd, "日")
    return s


# ── HTML 片段 ────────────────────────────────────────────────
def mi(name: str, cls: str = "") -> str:
    return f'<span class="mi {cls}">{ICON[name]}</span>'


def battery_cell(st: dict) -> str:
    pct = st["battery_pct"]
    if st.get("battery_charging"):
        ico = "battery_charging_full"
    elif pct <= 20:
        ico = "battery_alert"
    elif pct >= 95:
        ico = "battery_full"
    elif pct >= 60:
        ico = "battery_5_bar"
    else:
        ico = "battery_2_bar"
    cls = "cell batt"
    if pct <= 15 and not st.get("battery_charging"):
        cls += " low"
    elif st.get("battery_charging"):
        cls += " charging"
    return (f'<div class="{cls}" title="电量 {pct}%">'
            f'{mi(ico)}<span class="pct">{pct}%</span></div>')


def wifi_cell(st: dict) -> str:
    if st["wifi_on"]:
        return (f'<div class="cell tgl on" title="Wi-Fi：{st["wifi_ssid"]} · 信号 {st["wifi_sig"]}%">'
                f'{mi("wifi")}</div>')
    return f'<div class="cell tgl off" title="Wi-Fi：已关闭">{mi("wifi_off")}</div>'


def bt_cell(st: dict) -> str:
    if not st["bt_adapter"]:
        return f'<div class="cell tgl na" title="蓝牙：本机无适配器">{mi("bluetooth_disabled")}</div>'
    if st["bt_powered"]:
        dev = st.get("bt_dev_name") or ""
        tip = f"蓝牙：已开启{(' · ' + dev) if dev else '（未连接设备）'}"
        ico = "bluetooth_connected" if dev else "bluetooth"
        return f'<div class="cell tgl on" title="{tip}">{mi(ico)}</div>'
    return f'<div class="cell tgl off" title="蓝牙：已关闭">{mi("bluetooth")}</div>'


def cc_cell() -> str:
    return f'<div class="cell tgl panel" title="控制中心">{mi("tune")}</div>'


def cluster(st: dict, variant: str = "A") -> str:
    """右侧状态集群。A=分开胶囊 B=合并分段 C=电量仅图标"""
    b, w, t, c = battery_cell(st), wifi_cell(st), bt_cell(st), cc_cell()
    if variant == "B":
        return (f'<div class="cluster seg">{b}<span class="div"></span>{w}'
                f'<span class="div"></span>{t}<span class="div"></span>{c}</div>')
    if variant == "C":
        icon_only = b.replace(f'<span class="pct">{st["battery_pct"]}%</span>', "")
        icon_only = icon_only.replace("cell batt", "cell batt icononly")
        return f'<div class="cluster">{icon_only}{w}{t}{c}</div>'
    return f'<div class="cluster">{b}{w}{t}{c}</div>'


def slider(frac: float, kind: str) -> str:
    pct = max(0, min(100, int(round(frac * 100))))
    ico = "brightness_low" if kind == "bright" else "volume_up"
    return (f'<div class="slider" title="{pct}%"><span class="mi sico">{ICON[ico]}</span>'
            f'<div class="track"><div class="fill" style="width:{pct}%"></div>'
            f'<div class="handle" style="left:{pct}%"></div></div></div>')


def old_bar(st: dict) -> str:
    """改造前：右区只有 tray + 两个滑块"""
    return f'''<div class="bar">
  <div class="zone left"><div class="ws"><span class="nf">{ICON["fedora"]}</span> 1</div>
    <div class="clock">{st["clock"]}</div>
    <div class="searchbar"><div class="search"><span class="mi">{ICON["search"]}</span><span>搜索</span></div>
      <div class="mic">{mi("mic")}</div></div></div>
  <div class="zone center"><div class="media">{mi("music_note")}<span>宁静的星夜 · 电台</span></div></div>
  <div class="zone right"><div class="tray"><i></i><i></i><i></i></div>
    {slider(st["volume"] / 100, "vol")}{slider(st["brightness"] / 100, "bright")}</div>
</div>'''


def bar(st: dict, variant: str = "A", narrow: bool = False) -> str:
    cls = "bar narrow" if narrow else "bar"
    return f'''<div class="{cls}">
  <div class="zone left"><div class="ws"><span class="nf">{ICON["fedora"]}</span> 1</div>
    <div class="clock">{st["clock"]}</div>
    <div class="searchbar"><div class="search"><span class="mi">{ICON["search"]}</span><span>搜索</span></div>
      <div class="mic">{mi("mic")}</div></div></div>
  <div class="zone center"><div class="media">{mi("music_note")}<span>宁静的星夜 · 电台</span></div></div>
  <div class="zone right"><div class="tray"><i></i><i></i><i></i></div>
    {slider(st["volume"] / 100, "vol")}{slider(st["brightness"] / 100, "bright")}
    {cluster(st, variant)}</div>
</div>'''


def demo_bar(st: dict) -> str:
    """交互演示用的 bar：三个开关带 id，其余照旧"""
    b = battery_cell(st).replace('<div class="cell batt', '<div id="d-batt" class="cell batt')
    w = wifi_cell(st).replace('<div class="cell tgl', '<div id="d-wifi" class="cell tgl')
    t = bt_cell(st).replace('<div class="cell tgl', '<div id="d-bt" class="cell tgl')
    c = cc_cell().replace('<div class="cell tgl', '<div id="d-cc" class="cell tgl')
    return f'''<div class="bar">
  <div class="zone left"><div class="ws"><span class="nf">{ICON["fedora"]}</span> 1</div>
    <div class="clock">{st["clock"]}</div>
    <div class="searchbar"><div class="search"><span class="mi">{ICON["search"]}</span><span>搜索</span></div>
      <div class="mic">{mi("mic")}</div></div></div>
  <div class="zone center"><div class="media">{mi("music_note")}<span>宁静的星夜 · 电台</span></div></div>
  <div class="zone right"><div class="tray"><i></i><i></i><i></i></div>
    {slider(st["volume"] / 100, "vol")}{slider(st["brightness"] / 100, "bright")}
    <div class="cluster">{b}{w}{t}{c}</div></div>
</div>'''


def figure(inner: str, cap: str, badge: str = "", cls: str = "") -> str:
    b = f'<span class="badge">{badge}</span>' if badge else ""
    return (f'<figure class="row{(" " + cls) if cls else ""}">'
            f'<figcaption>{b}{cap}</figcaption>'
            f'<div class="screen"><div class="centerline"></div>{inner}'
            f'<div class="align"></div></div></figure>')


# ── 控制中心 ─────────────────────────────────────────────────
def cc_tile(icon: str, label: str, sub: str, on: bool) -> str:
    return (f'<div class="tile{" on" if on else ""}">'
            f'<span class="mi t-ico">{ICON[icon]}</span>'
            f'<div class="t-txt"><div class="t-label">{label}</div>'
            f'<div class="t-sub">{sub}</div></div>'
            f'<span class="mi t-state">{ICON["toggle_on" if on else "toggle_off"]}</span></div>')


def cc_slider(icon: str, frac: float) -> str:
    pct = max(0, min(100, int(round(frac * 100))))
    return (f'<div class="pslider"><span class="mi">{ICON[icon]}</span>'
            f'<div class="ptrack"><div class="pfill" style="width:{pct}%"></div>'
            f'<div class="phandle" style="left:{pct}%"></div></div>'
            f'<span class="pval">{pct}%</span></div>')


def cc_panel(st: dict) -> str:
    wifi = cc_tile("wifi" if st["wifi_on"] else "wifi_off", "Wi-Fi",
                   st["wifi_ssid"] if st["wifi_on"] else "已关闭", st["wifi_on"])
    if not st["bt_adapter"]:
        bt = cc_tile("bluetooth_disabled", "蓝牙", "无适配器", False)
    else:
        bt = cc_tile("bluetooth_connected" if st["bt_powered"] else "bluetooth", "蓝牙",
                     (st.get("bt_dev_name") or ("已开启" if st["bt_powered"] else "已关闭")),
                     st["bt_powered"])
    dnd = cc_tile("do_not_disturb_on", "勿扰", "关闭", False)
    night = cc_tile("nightlight", "夜览", "关闭", False)

    bico = "battery_charging_full" if st["battery_charging"] else "battery_5_bar"
    state = "充电中" if st["battery_charging"] else "预计可用 3 小时 20 分"

    rows = ""
    for ssid, sig in st["wifi_nets"]:
        active = ssid == st["wifi_ssid"]
        ico = "wifi" if sig >= 70 else ("signal_wifi_4_bar" if sig >= 40 else "signal_wifi_off")
        rows += (f'<div class="lrow{" active" if active else ""}">'
                 f'<span class="mi">{ICON[ico]}</span>'
                 f'<span class="lname">{ssid}</span>'
                 f'{"<span class=\'mi lcheck\'>" + ICON["check"] + "</span>" if active else ""}'
                 f'<span class="lsig">{sig}%</span></div>')

    return f'''<div class="cc">
    <div class="cc-h"><span class="cc-title">控制中心</span>
      <span class="cc-date">{st["date"]}</span>
      <span class="mi cc-close">{ICON["close"]}</span></div>
    <div class="grid2">{wifi}{bt}{dnd}{night}</div>
    <div class="sliders">{cc_slider("volume_up", st["volume"] / 100)}
      {cc_slider("brightness_low", st["brightness"] / 100)}</div>
    <div class="bcard"><span class="mi b-ico">{ICON[bico]}</span>
      <span class="bnum">{st["battery_pct"]}%</span>
      <span class="bsub">{state}</span>
      <span class="chip">{mi("bolt")} 节电</span></div>
    <div class="plist"><div class="plist-h"><span class="mi">{ICON["wifi"]}</span>可用网络</div>
      {rows}</div>
    <div class="cc-foot">
      <span class="foot-btn"><span class="mi">{ICON["lock"]}</span>锁定</span>
      <span class="foot-btn"><span class="mi">{ICON["logout"]}</span>注销</span>
      <span class="foot-btn"><span class="mi">{ICON["restart_alt"]}</span>重启</span>
    </div>
</div>'''


def control_center(st: dict) -> str:
    return f'<div class="ccwrap">{cc_panel(st)}</div>'


# ── 静态 CSS（不含颜色，全部走 :root 变量）─────────────────────
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0b0d;color:var(--on-surface);font-family:'Roboto',system-ui,sans-serif;
  font-size:18px;line-height:1.5;-webkit-font-smoothing:antialiased}
.mi{font-family:'Material Symbols Rounded';font-weight:400;font-style:normal;
  font-size:20px;line-height:1;display:inline-flex;align-items:center;justify-content:center}

h1{font-size:26px;font-weight:500;margin:32px auto 6px;width:var(--bar-w)}
h2{font-size:17px;font-weight:500;letter-spacing:.2px;margin:0 0 12px;color:var(--on-surface)}
h2 .num{color:var(--primary);margin-right:8px}
.lead{width:var(--bar-w);margin:0 auto 24px;color:var(--on-surface-variant);font-size:15px;
  max-width:var(--bar-w)}
.lead code{color:var(--primary);font-family:ui-monospace,monospace;font-size:13px}
.section{width:var(--bar-w);margin:40px auto 0}
.section > .note{width:auto;margin:10px 0 0}
.note{color:var(--on-surface-variant);font-size:13px;line-height:1.7}
.note code{color:var(--primary);font-family:ui-monospace,monospace;font-size:12px}

/* ── 屏幕框 ── */
.screen{position:relative;width:var(--bar-w);border-radius:18px;overflow:hidden;
  background:linear-gradient(120deg,#1b2a4a,#3a2b4d 55%,#4a2b3a);
  padding:14px 0 16px;}
.centerline{position:absolute;left:50%;top:0;bottom:0;width:0;
  border-left:1px dashed color-mix(in srgb,var(--primary) 60%,transparent)}
figure.row{margin:0 0 26px}
figcaption{width:var(--bar-w);margin:0 auto 8px;font-size:13px;color:var(--on-surface-variant)}
.badge{display:inline-block;padding:1px 9px;border-radius:9px;font-size:11px;font-weight:500;
  background:color-mix(in srgb,var(--primary) 26%,transparent);color:var(--primary);
  margin-right:8px;vertical-align:1px}

/* ── bar ── */
.bar{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;
  height:40px;padding:0 16px}
.zone{display:flex;align-items:center;height:40px}
.zone.left{justify-content:flex-start;gap:8px}
.zone.center{justify-content:center}
.zone.right{justify-content:flex-end;gap:8px}

.ws{display:flex;align-items:center;gap:6px;height:40px;min-width:40px;padding:0 10px;
  border-radius:20px;background:color-mix(in srgb,var(--primary) 95%,transparent);
  color:var(--on-primary);font-size:18px;font-weight:500}
.nf{font-family:'BitstromWera Nerd Font Propo','Roboto';font-size:20px;line-height:1}
.clock{font-size:22px;color:var(--on-surface);padding:0 8px}

.searchbar{display:flex;align-items:center}
.search{display:flex;align-items:center;gap:8px;height:40px;min-width:216px;padding:0 8px 0 16px;
  border-radius:20px 0 0 20px;background:color-mix(in srgb,var(--sch) 88%,transparent);
  color:var(--on-surface-variant);font-size:15px}
.search .mi{font-size:20px}
.mic{display:flex;align-items:center;justify-content:center;height:40px;width:40px;
  border-radius:0 20px 20px 0;background:color-mix(in srgb,var(--sch) 88%,transparent);
  color:var(--on-surface-variant);font-size:20px}

.media{display:flex;align-items:center;gap:8px;height:38px;min-width:412px;padding:0 16px;
  border-radius:19px;background:color-mix(in srgb,var(--sch) 88%,transparent);
  color:var(--on-surface);font-size:22px;white-space:nowrap;overflow:hidden}
.media .mi{font-size:22px;color:var(--on-surface-variant)}

.tray{display:flex;align-items:center;gap:6px;height:38px;padding:0 12px;border-radius:19px;
  background:color-mix(in srgb,var(--sch) 88%,transparent)}
.tray i{display:block;width:18px;height:18px;border-radius:5px;background:var(--outline)}
.tray i:nth-child(1){background:var(--primary)}
.tray i:nth-child(2){background:var(--secondary)}
.tray i:nth-child(3){background:var(--inverse-surface)}

/* 滑块 */
.slider{display:flex;align-items:center;gap:6px;height:40px}
.sico{font-size:20px;color:var(--on-surface-variant)}
.track{position:relative;width:100px;height:10px;border-radius:5px;
  background:color-mix(in srgb,var(--secondary-container) 92%,transparent)}
.track::after{content:'';position:absolute;right:0;top:50%;transform:translateY(-50%);
  width:6px;height:6px;border-radius:50%;background:var(--on-surface-variant)}
.fill{position:absolute;left:0;top:0;height:10px;border-radius:5px;background:var(--primary);
  margin-right:4px}
.handle{position:absolute;top:50%;transform:translate(-50%,-50%);width:3px;height:30px;
  border-radius:2px;background:var(--primary)}

/* ── 状态集群 ── */
.cluster{display:flex;align-items:center;height:40px;gap:4px}
.cell{display:flex;align-items:center;justify-content:center;height:38px;flex:none;
  background:color-mix(in srgb,var(--sch) 88%,transparent);
  color:var(--on-surface-variant);border-radius:19px;cursor:pointer;
  transition:background .18s,color .18s}
.cell.batt{gap:6px;padding:0 14px 0 12px;font-size:15px;font-weight:500;
  color:var(--on-surface)}
.cell.batt .mi{font-size:20px}
.cell.batt.low{color:var(--on-error-container);
  background:color-mix(in srgb,var(--error-container) 80%,transparent)}
.cell.batt.low .mi{color:var(--on-error-container)}
.cell.batt.charging{color:var(--on-primary);
  background:color-mix(in srgb,var(--primary-container) 85%,transparent)}
.cell.batt.icononly{padding:0;width:38px}
.cell.batt.icononly .pct{display:none}
.cell.tgl{width:38px;font-size:21px}
.cell.tgl.on{background:color-mix(in srgb,var(--primary) 95%,transparent);color:var(--on-primary)}
.cell.tgl.off{background:color-mix(in srgb,var(--sch) 88%,transparent);color:var(--outline)}
.cell.tgl.na{background:color-mix(in srgb,var(--sch) 60%,transparent);
  color:var(--outline-variant);cursor:default}
.cell.tgl.panel{color:var(--on-surface-variant)}
/* B：合并成一个分段胶囊 */
.cluster.seg{gap:0;padding:0 4px;background:color-mix(in srgb,var(--sch) 88%,transparent);
  border-radius:19px}
.cluster.seg .cell{background:transparent;border-radius:15px;height:32px}
.cluster.seg .cell.batt{padding:0 10px}
.cluster.seg .div{width:1px;height:18px;background:var(--outline-variant);flex:none}
.cluster.seg .cell.tgl.on{background:color-mix(in srgb,var(--primary) 95%,transparent)}

.bar.narrow .track{width:87px}
/* 交互演示 */
.ccwrap.hidden{display:none}
.cell.tgl{user-select:none}
.demo-hint{width:var(--bar-w);margin:10px auto 0;font-size:13px;color:var(--on-surface-variant)}
/* 状态画廊 */
.gal{display:grid;grid-template-columns:repeat(auto-fill,minmax(430px,1fr));gap:14px;
  width:var(--bar-w)}
.gcard{display:flex;align-items:center;gap:14px;padding:12px 16px;border-radius:16px;
  background:color-mix(in srgb,var(--sc) 92%,transparent);
  border:1px solid var(--outline-variant)}
.gcard .cluster{height:38px}
.gtxt{flex:1;min-width:0}
.gt{font-size:14px;font-weight:500;color:var(--on-surface)}
.gs{font-size:12px;color:var(--on-surface-variant)}

/* ── 控制中心 ── */
.ccwrap{display:flex;justify-content:flex-end;padding:0 16px}
.cc{width:376px;border-radius:26px;padding:16px;font-size:14px;
  background:color-mix(in srgb,var(--sch) 97%,transparent);
  border:1px solid var(--outline-variant);box-shadow:0 16px 48px rgba(0,0,0,.5)}
.cc-h{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.cc-title{font-size:19px;font-weight:500}
.cc-date{font-size:12px;color:var(--on-surface-variant)}
.cc-close{margin-left:auto;font-size:20px;color:var(--on-surface-variant);cursor:pointer}
.grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-bottom:12px}
.tile{display:flex;align-items:center;gap:8px;padding:10px;border-radius:20px;
  min-width:0;background:color-mix(in srgb,var(--sc) 95%,transparent);
  border:1px solid transparent;cursor:pointer}
.tile.on{background:color-mix(in srgb,var(--primary) 95%,transparent);color:var(--on-primary)}
.t-ico{font-size:22px;flex:none}
.t-txt{flex:1;min-width:0}
.t-label{font-size:13px;font-weight:500;line-height:1.3}
.t-sub{font-size:11px;opacity:.78;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  line-height:1.35}
.t-state{font-size:20px;flex:none;opacity:.85}
.sliders{display:flex;flex-direction:column;gap:8px;margin-bottom:12px}
.pslider{display:flex;align-items:center;gap:10px;height:26px}
.pslider .mi{font-size:18px;color:var(--on-surface-variant);flex:none}
.ptrack{position:relative;flex:1;height:12px;border-radius:6px;
  background:color-mix(in srgb,var(--secondary-container) 92%,transparent)}
.ptrack::after{content:'';position:absolute;right:0;top:50%;transform:translateY(-50%);
  width:6px;height:6px;border-radius:50%;background:var(--on-surface-variant)}
.pfill{position:absolute;left:0;top:0;height:12px;border-radius:6px;background:var(--primary)}
.phandle{position:absolute;top:50%;transform:translate(-50%,-50%);width:4px;height:24px;
  border-radius:2px;background:var(--primary)}
.pval{font-size:11px;color:var(--on-surface-variant);width:32px;text-align:right;flex:none}
.bcard{display:flex;align-items:center;gap:10px;padding:10px 14px;border-radius:20px;
  background:color-mix(in srgb,var(--sc) 95%,transparent);margin-bottom:12px}
.b-ico{font-size:26px;color:var(--on-surface);flex:none}
.bnum{font-size:22px;font-weight:500}
.bsub{font-size:11px;color:var(--on-surface-variant);flex:1;min-width:0;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chip{font-size:11px;padding:4px 9px;border-radius:12px;flex:none;
  background:color-mix(in srgb,var(--schh) 90%,transparent);color:var(--on-surface-variant);
  display:flex;align-items:center;gap:3px}
.chip .mi{font-size:14px}
.plist{border-radius:20px;background:color-mix(in srgb,var(--sc) 95%,transparent);
  padding:8px 6px;margin-bottom:12px}
.plist-h{display:flex;align-items:center;gap:7px;padding:2px 10px 7px;font-size:12px;
  color:var(--on-surface-variant)}
.plist-h .mi{font-size:15px}
.lrow{display:flex;align-items:center;gap:9px;padding:7px 10px;border-radius:12px;font-size:13px}
.lrow.active{background:color-mix(in srgb,var(--primary) 20%,transparent)}
.lrow .mi{font-size:17px;color:var(--on-surface-variant);flex:none}
.lrow.active .mi{color:var(--primary)}
.lname{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lsig{font-size:11px;color:var(--on-surface-variant);flex:none}
.lcheck{color:var(--primary)!important}
.cc-foot{display:flex;gap:8px}
.foot-btn{flex:1;display:flex;align-items:center;justify-content:center;gap:5px;padding:9px;
  border-radius:16px;font-size:12px;background:color-mix(in srgb,var(--sc) 95%,transparent);
  color:var(--on-surface-variant);cursor:pointer}
.foot-btn .mi{font-size:17px}

/* ── 表格 ── */
table{border-collapse:collapse;width:var(--bar-w);font-size:13px}
th,td{text-align:left;padding:8px 16px 8px 0;vertical-align:top;
  border-bottom:1px solid var(--outline-variant);color:var(--on-surface-variant)}
th{color:var(--on-surface);font-weight:500;font-size:12px;letter-spacing:.3px;
  text-transform:uppercase;opacity:.75}
td:first-child{color:var(--on-surface);white-space:nowrap}
td code,th code{font-family:ui-monospace,monospace;font-size:12px;color:var(--primary)}

/* 待确认 */
.todo{width:var(--bar-w);border-radius:18px;padding:16px 20px;margin-top:14px;
  background:color-mix(in srgb,var(--primary) 10%,transparent);
  border:1px solid color-mix(in srgb,var(--primary) 30%,transparent)}
.todo ol{margin:6px 0 0 20px;font-size:13.5px;color:var(--on-surface-variant);line-height:2}
.todo b{color:var(--on-surface)}
footer{width:var(--bar-w);margin:40px auto 60px;color:var(--outline);font-size:12px}
/* 对齐自检徽标（由页面内 JS 实测后填入） */
.align{display:flex;justify-content:center;padding:6px 0 0}
.align span{font-size:11px;padding:2px 10px;border-radius:10px;
  font-family:ui-monospace,monospace;letter-spacing:.2px}
.align .ok{background:color-mix(in srgb,#4caf50 22%,transparent);color:#8bd88f}
.align .off{background:color-mix(in srgb,var(--error) 20%,transparent);color:var(--error)}
"""


SCRIPT = """
<script>
// 逐个 bar 实测「中间那个胶囊」相对屏幕中线的偏移，写回徽标。
// 必须等字体加载完再量，否则用的是 fallback 字体宽度，数字会偏。
function annotateAlign() {
  document.querySelectorAll('figure.row').forEach(function (fig) {
    var scr = fig.querySelector('.screen');
    var med = fig.querySelector('.media');
    var slot = fig.querySelector('.align');
    if (!scr || !med || !slot || slot.dataset.done) return;
    var s = scr.getBoundingClientRect();
    var m = med.getBoundingClientRect();
    var off = Math.round((m.left + m.width / 2) - (s.left + s.width / 2));
    var span = document.createElement('span');
    if (off === 0) { span.className = 'ok'; span.textContent = '中线对齐 0 px'; }
    else { span.className = 'off';
           span.textContent = '中线偏移 ' + (off > 0 ? '+' : '') + off + ' px'; }
    slot.appendChild(span);
    slot.dataset.done = '1';
  });
}
if (document.fonts && document.fonts.ready) {
  document.fonts.ready.then(annotateAlign);
} else {
  window.addEventListener('load', annotateAlign);
}
window.addEventListener('resize', annotateAlign);

// ── 交互演示：Wi-Fi / 蓝牙 / 控制中心 ──
(function () {
  var G = { wifi: '\ue63e', wifi_off: '\ue648', bt: '\ue1a7', bt_on: '\ue1a8' };
  var icon = function (el) { return el.querySelector('.mi'); };

  function bindToggle(id, onGlyph, offGlyph, onTip, offTip) {
    var el = document.getElementById(id);
    if (!el || el.classList.contains('na')) return;
    el.addEventListener('click', function () {
      var on = el.classList.contains('on');
      el.classList.remove('on', 'off');
      el.classList.add(on ? 'off' : 'on');
      icon(el).textContent = on ? offGlyph : onGlyph;
      el.title = on ? offTip : onTip;
    });
  }
  bindToggle('d-wifi', G.wifi, G.wifi_off, 'Wi-Fi：A401_5G · 信号 52%', 'Wi-Fi：已关闭');
  bindToggle('d-bt', G.bt_on, G.bt, '蓝牙：已开启', '蓝牙：已关闭');

  var ccBtn = document.getElementById('d-cc');
  var ccWrap = document.getElementById('d-ccwrap');
  if (ccBtn && ccWrap) {
    ccBtn.addEventListener('click', function () {
      ccWrap.classList.toggle('hidden');
      ccBtn.classList.toggle('active', !ccWrap.classList.contains('hidden'));
    });
  }
  var batt = document.getElementById('d-batt');
  if (batt && ccWrap) {
    batt.addEventListener('click', function () { ccWrap.classList.remove('hidden'); });
  }
  // 面板里的关闭按钮
  var ccClose = ccWrap && ccWrap.querySelector('.cc-close');
  if (ccClose) ccClose.addEventListener('click', function () { ccWrap.classList.add('hidden'); });
})();
</script>
"""


def build(st: dict) -> str:
    # 变体用的状态
    van = dict(st, wifi_on=True, bt_adapter=True, bt_powered=True, bt_dev_name="",
               battery_pct=80, battery_charging=False)
    now = dict(st)
    low = dict(van, battery_pct=15)
    chg = dict(van, battery_pct=88, battery_charging=True, wifi_on=False, bt_powered=False)
    woff = dict(van, wifi_on=False)
    btoff = dict(van, bt_powered=False)
    bton = dict(van, bt_powered=True, bt_dev_name="WH-1000XM5")
    full = dict(van, battery_pct=100)
    na = dict(van, bt_adapter=False)

    gallery = [
        (bton, "Wi-Fi 已连接 · 蓝牙已连耳机", "两个开关都点亮，实底 primary"),
        (woff, "Wi-Fi 已关闭", "图标换 wifi_off，底色回到 surface_container_high"),
        (btoff, "蓝牙已开启、未连设备", "图标用 bluetooth（无线状态），仍是 ON 色"),
        (na, "蓝牙：无适配器", "本机当前就是这种：降低不透明度，不可点"),
        (chg, "充电中 · 88%", "图标 battery_charging_full，primary_container 底色"),
        (low, "低电量 15%", "切到 error 色系，并触发告警图标 battery_alert"),
        (full, "满电 100%", "battery_full"),
    ]
    gal_html = "".join(
        f'<div class="gcard">{cluster(s)}'
        f'<div class="gtxt"><div class="gt">{t}</div><div class="gs">{d}</div></div></div>'
        for s, t, d in gallery
    )

    css_vars = "\n".join(f"  --{k.replace('_', '-')}:{v};" for k, v in PAL.items()
                         if k in {
                             "primary", "on_primary", "primary_container", "on_primary_container",
                             "secondary", "secondary_container", "on_secondary_container",
                             "tertiary_container", "on_tertiary_container",
                             "surface", "surface_container_low", "surface_container",
                             "surface_container_high", "surface_container_highest",
                             "on_surface", "on_surface_variant", "outline", "outline_variant",
                             "inverse_surface", "inverse_on_surface", "error", "on_error",
                             "error_container", "on_error_container"})
    css_vars += f"\n  --bar-w:{BAR_W}px;"

    real_bt = ("无适配器" if not st["bt_adapter"]
               else ("已开启" if st["bt_powered"] else "已关闭"))

    demo = demo_bar(van)
    cc_body = cc_panel(st)

    body = f"""
<h1>waybar-m3 · 设计稿 v2：Wi-Fi / 蓝牙开关 · 电量 · 控制中心</h1>
<p class="lead">
  这是<b>纯 HTML 设计稿</b>，配色全部取自 <code>colors.css</code> 的 M3 角色，尺寸沿用
  <code>style.css</code> 的换算法（1em = 18px，bar 内边距 16px，模块间距 8px，bar 高 40px），
  所以下面看到的就是 waybar 里真实的比例。文案尽量取本机真实状态。<br>
  <b>先确认这一版设计，确认之后我再动 config.jsonc / style.css / scripts。</b>
</p>

<div class="section">
<h2><span class="num">1</span>现在的右侧（改造前）</h2>
<figure class="row"><figcaption>右区只有 托盘 + 音量 + 亮度，没有状态开关</figcaption>
  <div class="screen"><div class="centerline"></div>{old_bar(st)}<div class="align"></div></div></figure>
</div>

<div class="section">
<h2><span class="num">2</span>三种方案全做一遍（每个都配两种滑块宽度）</h2>

<figure class="row"><figcaption><span class="badge">A · 滑块 100px（现状）</span>
  四个独立胶囊，电量带百分比。右区需要 572px，超出可用宽度 546px</figcaption>
  <div class="screen"><div class="centerline"></div>{bar(van, "A")}<div class="align"></div></div></figure>

<figure class="row"><figcaption><span class="badge">A · 滑块 87px</span>
  同上，只把音量/亮度轨道各缩 13px，「A 的完整形态」</figcaption>
  <div class="screen"><div class="centerline"></div>{bar(van, "A", narrow=True)}<div class="align"></div></div></figure>

<figure class="row"><figcaption><span class="badge">B · 滑块 100px</span>
  合并成分段胶囊，中间 1px 分隔线；右区 565px，仍差 19px</figcaption>
  <div class="screen"><div class="centerline"></div>{bar(van, "B")}<div class="align"></div></div></figure>

<figure class="row"><figcaption><span class="badge">B · 滑块 87px</span>
  窄滑块之后回到中线</figcaption>
  <div class="screen"><div class="centerline"></div>{bar(van, "B", narrow=True)}<div class="align"></div></div></figure>

<figure class="row"><figcaption><span class="badge">C · 滑块 100px</span>
  电量只显示图标，右区 530px，什么都不用改就居中</figcaption>
  <div class="screen"><div class="centerline"></div>{bar(van, "C")}<div class="align"></div></div></figure>

<p class="note">
  每张图下面那枚徽标是页面<b>实测</b>的中线偏移，不是手写数字。
  结论：<b>A</b> 信息最全，代价是滑块要缩到 87px；<b>B</b> 最紧凑，同样要缩滑块；
  <b>C</b> 唯一零改动，但看不到百分比。三者开关的状态色完全一致，换方案只影响排布。
</p>
</div>

<div class="section">
<h2><span class="num">3</span>可交互演示（真的能点）</h2>
<div class="screen" id="demo-screen">
  <div class="centerline"></div>
  {demo}
  <div class="ccwrap hidden" id="d-ccwrap">
    {cc_body}
  </div>
</div>
<p class="note">
  点 <b>Wi-Fi</b> / <b>蓝牙</b> 可切换开、关；点 <b>tune</b> 展开/收起控制中心；
  点电量胶囊也能打开控制中心。这里只是看交互手感，不会真的去动系统。
</p>
</div>

<div class="section">
<h2><span class="num">4</span>各种状态怎么表现</h2>
<div class="gal">{gal_html}</div>
<p class="note">
  ON = <code>primary</code> 实底 + <code>on_primary</code> 图标；OFF = <code>surface_container_high</code>
  底 + <code>outline</code> 图标；不可用 = 底色与图标同时降透明度 + 标签显示「无适配器」。
  电量 &lt; 15% 切 <code>error</code> 色系，充电时换 <code>battery_charging_full</code> 并改成
  <code>primary_container</code> 底色。
</p>
</div>

<div class="section">
<h2><span class="num">5</span>本机真实状态（下面这条是照当前系统画的）</h2>
<figure class="row"><figcaption><span class="badge">真实</span>
  电量 {st["battery_pct"]}% · Wi-Fi {st["wifi_ssid"] or "已关"} · 蓝牙 {real_bt}</figcaption>
  <div class="screen"><div class="centerline"></div>{bar(now, "A")}<div class="align"></div></div></figure>
</div>

<div class="section">
<h2><span class="num">6</span>控制中心（点 tune 按钮弹出，贴右上角）</h2>
<div class="screen" style="padding-bottom:20px">
  {bar(st, "A").replace('title="控制中心"', 'title="控制中心" style="outline:2px solid var(--primary);outline-offset:1px"')}
  {control_center(st)}
</div>
<p class="note">
  2×2 开关卡（Wi-Fi / 蓝牙 / 勿扰 / 夜览）+ 音量亮度滑块 + 电量卡 + Wi-Fi 列表 + 锁定/注销/重启。
  总高约 600px，在 1536×960 的逻辑屏上留得出底部空间。
</p>
</div>

<div class="section">
<h2><span class="num">7</span>设计规格 → waybar 实现</h2>
<table>
  <tr><th>位置</th><th>模块</th><th>M3 角色 / 尺寸</th><th>左键</th><th>右键</th></tr>
  <tr><td>右</td><td><code>custom/battery</code></td><td>胶囊 38px 高 · 图标 20px + 15px 数字 · radius 19</td>
      <td>打开控制中心</td><td>百分比 / 仅图标 切换</td></tr>
  <tr><td>右</td><td><code>custom/wifi</code></td><td>38×38 圆 · ON <code>primary</code> / OFF <code>outline</code></td>
      <td>开/关 Wi-Fi</td><td>网络列表</td></tr>
  <tr><td>右</td><td><code>custom/bluetooth</code></td><td>38×38 圆 · 同上一套状态色</td>
      <td>开/关蓝牙</td><td>已配对设备</td></tr>
  <tr><td>右</td><td><code>custom/panel</code></td><td>38×38 圆 · <code>tune</code> 图标</td>
      <td>开/关控制中心</td><td>—</td></tr>
  <tr><td>面板</td><td>开关卡 ×4</td><td>卡片 radius 20 · ON 实底 primary</td>
      <td>切换</td><td>—</td></tr>
  <tr><td>面板</td><td>滑块 ×2</td><td>轨道 12px · 手柄 4×24</td>
      <td>拖动 / 点击定位</td><td>静音</td></tr>
</table>
</div>

<div class="section">
<h2><span class="num">8</span>实现方式（确认后才动手）</h2>
<p class="note">
  · Wi-Fi 开关用 <code>nmcli radio wifi on|off</code>（本机 <code>/dev/rfkill</code> 不可用，不能用 rfkill）<br>
  · 蓝牙开关用 <code>bluetoothctl power on|off</code>；本机 <code>bluetoothctl list</code> 为空，
    即<b>当前没有蓝牙适配器</b>，会一直落在「不可用」那一档，接上适配器后自动恢复<br>
  · 电量走 waybar 原生 <code>battery</code> 模块（BAT0），只做样式，不写脚本<br>
  · 控制中心第一版用 fuzzel 列表实现（和现有 <code>scripts/panel.sh</code> 同一套），
    开关行用 fuzzel 的 dmenu 模式；如果想要真正的图形面板，再单独做 GTK/浏览器面板
</p>
</div>

<div class="todo">
<h2 style="margin-bottom:4px">还差你拍板的两件事</h2>
<ol>
  <li>状态集群选 <b>A</b> / <b>B</b> / <b>C</b>？（第 2 节三种都做了，每张图下面有实测中线偏移）</li>
  <li>如果选 A 或 B：滑块轨道<b>缩到 87px</b> 换中线对齐，还是保持 100px 接受偏移？
      选 C 则不用动滑块。</li>
</ol>
<p style="margin:10px 0 0;font-size:13px;color:var(--on-surface-variant)">
  已定：控制中心开关卡 = <b>Wi-Fi / 蓝牙 / 勿扰 / 夜览</b>；右侧顺序 = 托盘 → 音量 → 亮度 → 电量 → Wi-Fi → 蓝牙 → 控制中心。
</p>
</div>

<footer>由 tools/build-design.py 生成 · 颜色来自 colors.css · 尺寸对齐 style.css</footer>
"""
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>waybar-m3 · 设计稿 v2（Wi-Fi / 蓝牙开关 · 电量 · 控制中心）</title>
<style>
@font-face{{font-family:'Material Symbols Rounded';
  src:url('fonts/MaterialSymbolsRounded-subset.ttf') format('truetype')}}
@font-face{{font-family:'Roboto';src:url('fonts/Roboto-subset.ttf') format('truetype')}}
:root{{
{css_vars}
}}
{CSS}
</style></head><body>
{body}
{SCRIPT}
</body></html>
"""


def main() -> None:
    st = probe_state()
    page = build(st)
    out = ROOT / "design.html"
    out.write_text(page, encoding="utf-8")
    print(f"已写出 {out}（{len(page)} 字节）")


if __name__ == "__main__":
    main()
