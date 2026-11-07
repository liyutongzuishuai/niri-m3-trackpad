#!/usr/bin/env python3
"""waybar-m3 · tools/build-preview.py

生成 preview.html：颜色取自 colors.css，文案取自各脚本的真实输出，
尺寸与 style.css 用同一套 em 值（基准 18px），所以看到的就是 waybar 里的比例。
容器宽度 1536px = 本机 eDP-1 上 waybar 的逻辑宽度（1920 物理 / 1.25 缩放）。

布局按 config.jsonc 的三区还原：左 / 中 / 右，中间那条用屏幕中线校验。

    python3 tools/build-preview.py
"""

from __future__ import annotations

import html
import json
import os
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNTIME = ROOT / ".test-runtime"
BAR_WIDTH = 1536  # waybar 在本机的逻辑宽度

ICON = {"public": "\ue80b", "search": "\uef7a", "mic": "\ue31d", "fedora": "\uf30a"}


# ── 颜色：从 colors.css 读，别名解析一层 ──────────────────────

def read_colors() -> dict[str, str]:
    txt = (ROOT / "colors.css").read_text(encoding="utf-8")
    raw = dict(re.findall(r"^\s*@define-color\s+(\w+)\s+(#[0-9A-Fa-f]{6,8})\s*;", txt, re.M))
    alias = dict(re.findall(r"^\s*@define-color\s+(\w+)\s+@(\w+)\s*;", txt, re.M))
    out = dict(raw)
    for k, v in alias.items():
        out[k] = out.get(v, "#FF00FF")
    return out


# ── 跑脚本，拿真实数据 ────────────────────────────────────────

def run(args, env_extra: dict | None = None) -> str:
    env = os.environ.copy()
    env.update({"WAYBAR_M3_DIR": str(ROOT), "WAYBAR_M3_SPOOL": str(RUNTIME / "messages.jsonl")})
    env.update(env_extra or {})
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                       env=env, cwd=str(ROOT))
    return r.stdout.strip()


def pango_to_html(s: str) -> str:
    """把 pango 标记转成等价的 HTML span。"""
    def fix(m: re.Match) -> str:
        attrs = m.group(1)
        styles = []
        if fg := re.search(r"foreground='([^']+)'", attrs):
            styles.append(f"color:{fg.group(1)}")
        if sz := re.search(r"size='(\d+)pt'", attrs):
            styles.append(f"font-size:{round(int(sz.group(1)) * 4 / 3)}px")
        if rise := re.search(r"rise='(-?\d+)'", attrs):
            styles.append(f"position:relative;top:{-round(int(rise.group(1)) / 1024)}px")
        return f'<span style="{";".join(styles)}">' if styles else "<span>"

    return re.sub(r"<span ([^>]*)>", fix, s)


# ── 状态准备 ──────────────────────────────────────────────────

def prepare() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "bin").mkdir(parents=True, exist_ok=True)
    stub = RUNTIME / "bin" / "pactl"
    stub.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    stub.chmod(0o755)
    seed_spool()


def seed_spool(with_message: bool = True) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    body = ""
    if with_message:
        body = json.dumps({"app": "qq", "summary": "女神", "body": "我喜欢你"},
                          ensure_ascii=False) + "\n"
    (RUNTIME / "messages.jsonl").write_text(body, encoding="utf-8")


def state_env(no_audio: bool, with_message: bool) -> dict:
    env = {}
    if no_audio:
        env["PATH"] = f"{RUNTIME / 'bin'}:{os.environ['PATH']}"
        env["WAYBAR_M3_MESSAGE_SOURCE"] = "spool"
        seed_spool(with_message)
    return env


def current_workspace() -> str:
    try:
        for ws in json.loads(run(["niri", "msg", "--json", "workspaces"])):
            if ws.get("is_focused"):
                return str(ws.get("idx"))
    except Exception:
        pass
    return "1"


def volume_pct() -> int:
    m = re.search(r"Volume:\s*([0-9.]+)", run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]))
    return round(float(m.group(1)) * 100) if m else 40


def brightness_pct() -> int:
    lines = run(["brightnessctl", "-m"]).splitlines()
    if lines and len(lines[0].split(",")) >= 4:
        return int(lines[0].split(",")[3].rstrip("%"))
    return 40


# ── 渲染 ──────────────────────────────────────────────────────

def slider_html(pct: int) -> str:
    return ('<div class="slider">'
            f'<div class="trough"><div class="highlight" style="width:{pct}%"></div></div>'
            f'<div class="handle" style="left:calc({pct}% - 2px)"></div>'
            "</div>")


def bar_row(c: dict, env_extra: dict, caption: str, badge: str, old: bool = False) -> str:
    media = json.loads(run([ROOT / "scripts/media.sh", "--bar"], env_extra))
    search = pango_to_html(run([ROOT / "scripts/search.sh", "--bar"]))
    clock = run(["date", "+%H:%M:%S"])
    ws, vol, bri = current_workspace(), volume_pct(), brightness_pct()
    cls = media["class"]

    # 工作区按钮：Nerd Font 的 Fedora logo（config.jsonc 里用 font_family 钉死字体族）
    left = (f'<div class="ws"><span class="nf">{ICON["fedora"]}</span> {ws}</div>'
            f'<div class="clock">{clock}</div>'
            f'<div class="searchbar"><div class="search">{search}</div>'
            f'<div class="mic"><span class="mi">{ICON["mic"]}</span></div></div>')
    center = f'<div class="media {cls}">{media["text"]}</div>'
    # tray 里的图标运行时来自各应用的 pixmap，这里用色块代表位置
    tray = ('<div class="tray">'
            f'<div class="trayicon" style="background:{c["primary"]}"></div>'
            f'<div class="trayicon" style="background:{c["secondary"]}"></div>'
            f'<div class="trayicon" style="background:{c["on_tertiary_container"]}"></div>'
            '</div>')
    right = tray + slider_html(vol) + slider_html(bri)   # 顺序跟 config.jsonc 的 modules-right 一致

    if old:
        inner = f'<div class="zone left">{left}{center}{right}</div>'
    else:
        inner = (f'<div class="zone left">{left}</div>'
                 f'<div class="zone center">{center}</div>'
                 f'<div class="zone right">{right}</div>')

    return f"""
<figure class="row">
  <figcaption><span class="badge {cls}">{badge}</span> {html.escape(caption)}</figcaption>
  <div class="screen">
    <div class="centerline"></div>
    <div class="bar{' old' if old else ''}">{inner}</div>
  </div>
</figure>"""


def main() -> None:
    prepare()
    c = read_colors()
    vol, bri = volume_pct(), brightness_pct()

    rows = [
        bar_row(c, {}, "上一版：全塞在 modules-left，一行只占 45% 宽度", "旧", old=True),
        bar_row(c, state_env(False, True),
                "现在：左（Fedora 图标·时钟·搜索·mic）+ 中（容器框，对齐屏幕中线）+ 右（音量·亮度·tray）", "playing"),
        bar_row(c, state_env(True, True), "没有音频输出、但有消息 → tertiaryContainer 底色", "message"),
        bar_row(c, state_env(True, False), "都没有 → 空状态提示", "idle"),
    ]

    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>waybar-m3 · 预览</title>
<style>
@font-face {{ font-family:"Material Symbols Rounded"; src:url("fonts/MaterialSymbolsRounded-subset.ttf"); }}
@font-face {{ font-family:"Roboto"; src:url("fonts/Roboto-subset.ttf"); }}

* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{
  font-family:"Roboto","Noto Sans CJK SC",sans-serif;
  background:#0b0a0e; color:{c['on_surface']}; padding:24px 24px 40px;
}}
h1 {{ font-size:19px; font-weight:500; margin-bottom:6px; }}
p.lead {{ color:{c['on_surface_variant']}; font-size:13px; line-height:1.7; margin-bottom:20px; }}
code {{ font-family:ui-monospace,monospace; color:{c['primary']}; }}
figure.row {{ margin-bottom:22px; }}
figcaption {{ font-size:12px; color:{c['on_surface_variant']}; margin-bottom:8px; }}
.badge {{
  display:inline-block; padding:1px 7px; border-radius:8px; font-size:11px;
  background:{c['secondary_container']}; color:{c['on_secondary_container']};
}}
.badge.message {{ background:{c['tertiary_container']}; color:{c['on_tertiary_container']}; }}
.badge.idle {{ background:{c['surface_container_highest']}; color:{c['on_surface_variant']}; }}
.badge.旧 {{ background:{c['outline_variant']}; color:{c['on_surface_variant']}; }}

.screen {{
  position:relative; width:{BAR_WIDTH}px; border-radius:14px; overflow:hidden;
  background:
    radial-gradient(1000px 340px at 12% -10%, #3b2a63 0%, transparent 60%),
    radial-gradient(800px 300px at 88% 120%, #123a4a 0%, transparent 55%),
    linear-gradient(120deg, #1a1722 0%, #241f2e 45%, #14131a 100%);
}}
/* 屏幕中线：用来核对中间那组是不是真的居中 */
.centerline {{ position:absolute; left:50%; top:0; bottom:0; width:0;
  border-left:1px dashed rgba(210,188,252,0.55); }}

/* ══ 以下数值与 style.css 逐条对应（基准字号 18px，1em = 18px）══
   三区：左 / 中 / 右 —— grid 1fr auto 1fr，中间列天然落在中线上 */
.bar {{ display:grid; grid-template-columns:1fr auto 1fr; align-items:center;
  padding:0 16px; font-size:18px; font-weight:400; }}
.bar .zone {{ display:flex; align-items:center; }}
.bar .zone.left {{ justify-self:start; }}
.bar .zone.center {{ justify-self:center; }}
.bar .zone.right {{ justify-self:end; }}
.mi {{ font-family:"Material Symbols Rounded"; font-weight:normal; }}
.nf {{ font-family:"BitstromWera Nerd Font Propo"; font-size:0.694em; }}
.tray {{ display:flex; align-items:center; gap:6px; margin-left:8px; padding:0 12px;
  min-height:38px; border-radius:19px;
  background-color:color-mix(in srgb, {c['surface_container_high']} 88%, transparent); }}
.trayicon {{ width:32px; height:32px; border-radius:6px; }}

.ws {{                                    /* #workspaces button */
  min-width:40px; height:40px; border-radius:20px; padding:0 10px;
  display:flex; align-items:center; justify-content:center; gap:6px;
  font-size:18px; font-weight:500;
  background:color-mix(in srgb, {c['secondary_container']} 92%, transparent);
  color:{c['on_secondary_container']};
}}
.clock {{ margin-left:8px; padding:0 8px; font-size:22px; color:{c['on_surface']}; }}
.searchbar {{ display:flex; margin-left:8px; }}
.search {{                               /* #custom-search */
  min-height:40px; min-width:216px; padding:0 8px 0 16px;
  border-radius:20px 0 0 20px; display:flex; align-items:center; gap:8px;
  font-size:15px; color:{c['on_surface_variant']};
  background:color-mix(in srgb, {c['surface_container_high']} 88%, transparent);
}}
.mic {{                                  /* #custom-mic */
  min-width:40px; min-height:40px; padding:0 16px 0 6px;
  border-radius:0 20px 20px 0; display:flex; align-items:center;
  font-size:20px; color:{c['on_surface_variant']};
  background:color-mix(in srgb, {c['surface_container_high']} 88%, transparent);
}}
.media {{                                /* #custom-media（modules-center）*/
  margin:0 8px; padding:0 16px; min-width:412px; min-height:38px;
  border-radius:19px; display:flex; align-items:center; justify-content:center;
  font-size:22px; color:{c['on_surface']}; white-space:nowrap; overflow:hidden;
  background:color-mix(in srgb, {c['surface_container_high']} 88%, transparent);
}}
.media.message {{ background:color-mix(in srgb, {c['tertiary_container']} 92%, transparent); }}
.media.idle {{ font-size:15px; color:{c['on_surface_variant']}; }}

.slider {{ position:relative; margin-left:8px; width:100px; height:30px;
  display:flex; align-items:center; }}
.trough {{ width:100%; height:10px; border-radius:5px;
  background-color:color-mix(in srgb, {c['secondary_container']} 92%, transparent);
  background-image:radial-gradient(circle closest-side, {c['on_surface_variant']} 0%, {c['on_surface_variant']} 65%, transparent 66%);
  background-size:6px 6px; background-position:right center; background-repeat:no-repeat; }}
.highlight {{ height:10px; border-radius:5px; background:{c['primary']}; margin-right:4px; }}
.handle {{ position:absolute; top:50%; transform:translateY(-50%);
  width:3px; height:30px; border-radius:2px; background:{c['primary']}; }}

/* 上一版（全塞 modules-left，34px 高）—— 只用于对比 */
.bar.old {{ display:flex; }}
.bar.old .zone.left {{ justify-self:auto; }}
.bar.old .ws {{ min-width:30px; height:30px; border-radius:15px; padding:0 6px; font-size:16px; gap:4px; }}
.bar.old .clock {{ margin-left:6px; padding:0 5px; font-size:20px; }}
.bar.old .searchbar {{ margin-left:6px; }}
.bar.old .search {{ min-height:30px; min-width:144px; padding:0 6px 0 10px;
  border-radius:15px 0 0 15px; font-size:14px; gap:6px; }}
.bar.old .mic {{ min-width:30px; min-height:30px; padding:0 10px 0 4px;
  border-radius:0 15px 15px 0; font-size:20px; }}
.bar.old .media {{ margin:0 0 0 6px; padding:0 9px; min-width:234px; min-height:30px;
  border-radius:15px; font-size:16px; }}
.bar.old .media.idle {{ font-size:14px; }}
.bar.old .slider {{ margin-left:8px; width:60px; height:20px; }}
.bar.old .trough, .bar.old .highlight {{ height:6px; border-radius:3px; }}
.bar.old .handle {{ width:4px; height:20px; }}

table {{ border-collapse:collapse; font-size:12px; margin-top:8px; }}
td, th {{ text-align:left; padding:4px 16px 4px 0; color:{c['on_surface_variant']}; }}
th {{ color:{c['on_surface']}; font-weight:500; }}
</style></head><body>

<h1>waybar-m3 · 预览（{BAR_WIDTH}px 逻辑宽度 = 本机 eDP-1 上 bar 的实际宽度）</h1>
<p class="lead">
  三区布局：左 / 中 / 右，<span style="color:{c['primary']}">虚线是屏幕中线</span>，用来核对中间那组是否真的居中。<br>
  颜色来自 <code>colors.css</code> 的 M3 角色；文案来自 <code>scripts/*.sh</code> 的真实输出
  （时钟是当前时间，音量 {vol}%、亮度 {bri}% 是真实值）。bar 背景透明，这里垫了渐变壁纸。
</p>

{''.join(rows)}

<table>
  <tr><th>位置</th><th>模块</th><th>M3 对应 / 尺寸</th></tr>
  <tr><td>左</td><td>niri/workspaces</td><td>filled tonal icon button · 40px 圆 · Nerd Font Fedora logo (U+F30A)</td></tr>
  <tr><td>左</td><td>clock</td><td>headlineMedium 缩比 · 22px · onSurface</td></tr>
  <tr><td>左</td><td>custom/search + custom/mic</td><td>search bar · 40px 高 · 圆角 20px · surfaceContainerHigh</td></tr>
  <tr><td>中</td><td>custom/media</td><td>容器框 · 412×38px · 圆角 19px · 正文 22px</td></tr>
  <tr><td>右</td><td>pulseaudio/slider · backlight/slider</td><td>M3 Expressive slider · 轨道 10px · 手柄 3×30px · 末端 stop indicator</td></tr>
  <tr><td>右</td><td>tray</td><td>系统托盘 · icon-size 32（waybar 默认 16 的两倍）· 图标由各应用提供，这里用色块占位</td></tr>
</table>

</body></html>
"""
    (ROOT / "preview.html").write_text(page, encoding="utf-8")
    print(f"已生成 {ROOT / 'preview.html'}")


if __name__ == "__main__":
    main()
