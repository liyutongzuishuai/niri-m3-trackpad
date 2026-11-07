#!/usr/bin/env bash
# tools/probe-bar.sh — 临时换一份 style 跑 waybar、截屏、量几何，然后恢复。
# 只用于开发验证，不进配置。
#
#   tools/probe-bar.sh <style变体文件> [配置文件]
set -u
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
STYLE="${1:?需要 style 变体路径}"
CONF="${2:-$HOME/.config/waybar-m3/config.jsonc}"

pkill -x waybar 2>/dev/null
sleep 0.6
waybar -c "$CONF" -s "$STYLE" >"$ROOT/.test-runtime/probe.log" 2>&1 &
sleep 3.5
niri msg action screenshot-screen -d true >/dev/null 2>&1
sleep 1.8

SHOT=$(ls -t "$HOME"/Pictures/Screenshots/*.png | head -1)
python3 - "$SHOT" <<'PY'
import sys
from importlib.machinery import SourceFileLoader
m = SourceFileLoader('mp', 'tools/measure-bar.py').load_module()
W, H, ch, rows = m.load_png(sys.argv[1])
scale = 1.25
y = int(40 * scale / 2)
line = rows[y]
TAGS = {
    (0xFF, 0, 0): 'workspaces', (0, 0xFF, 0): 'clock', (0, 0, 0xFF): 'search',
    (0xFF, 0xFF, 0): 'mic', (0xFF, 0, 0xFF): 'media', (0, 0xFF, 0xFF): 'tray',
    (0xFF, 0x80, 0): 'vol', (0x80, 0, 0xFF): 'bri', (0, 0xFF, 0x80): 'battery',
    (0xFF, 0, 0x80): 'wifi', (0x80, 0x80, 0x80): 'bt', (0xFF, 0xFF, 0xFF): 'panel',
}
segs = {}
for x in range(W):
    o = x * ch
    c = (line[o], line[o + 1], line[o + 2])
    if c in TAGS:
        n = TAGS[c]
        segs.setdefault(n, [x, x])
        segs[n][1] = x

print(f'{"模块":<12}{"x0":>6}{"x1":>6}{"逻辑宽":>9}')
for n, (a, b) in sorted(segs.items(), key=lambda kv: kv[1][0]):
    print(f'{n:<12}{a:>6}{b:>6}{(b - a + 1) / scale:>9.1f}')

if 'media' in segs:
    a, b = segs['media']
    cx = (a + b) / 2
    print(f'\n>>> media 中心 {cx:.1f}  屏幕中线 {W / 2:.1f}  '
          f'偏移 {(cx - W / 2) / scale:+.2f} 逻辑px')
if segs:
    lo = min(v[0] for v in segs.values())
    hi = max(v[1] for v in segs.values())
    print(f'>>> 左端 {lo / scale:.1f} 逻辑px   右端距屏幕边 {(W - hi) / scale:.1f} 逻辑px')
    left = [v for k, v in segs.items() if k in ('workspaces', 'clock', 'search', 'mic')]
    right = [v for k, v in segs.items() if k in ('tray', 'vol', 'bri', 'battery', 'wifi', 'bt', 'panel')]
    if left and right:
        lw = (max(v[1] for v in left) - min(v[0] for v in left) + 1) / scale
        rw = (max(v[1] for v in right) - min(v[0] for v in right) + 1) / scale
        print(f'>>> 左区 {lw:.1f}  右区 {rw:.1f}  差 {rw - lw:+.1f} 逻辑px')
PY
