#!/usr/bin/env python3
"""从截图里量 bar：找出黑底上的胶囊/按钮色块，输出每块的 x 范围。

只用于验证，不进入配置。
"""
import struct
import sys
import zlib


def load_png(path):
    d = open(path, 'rb').read()
    pos = 8
    W = H = 0
    idat = b''
    color = None
    while pos < len(d):
        ln = struct.unpack('>I', d[pos:pos + 4])[0]
        typ = d[pos + 4:pos + 8]
        data = d[pos + 8:pos + 8 + ln]
        if typ == b'IHDR':
            W, H, depth, color = struct.unpack('>IIBB', data[:10])
        elif typ == b'IDAT':
            idat += data
        elif typ == b'IEND':
            break
        pos += 12 + ln
    raw = zlib.decompress(idat)
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[color]
    stride = W * ch
    prev = bytearray(stride)
    rows = []

    def paeth(a, b, c):
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        return a if pa <= pb and pa <= pc else (b if pb <= pc else c)

    i = 0
    for _ in range(H):
        f = raw[i]; i += 1
        line = bytearray(raw[i:i + stride]); i += stride
        if f == 1:
            for x in range(ch, stride):
                line[x] = (line[x] + line[x - ch]) & 255
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                a = line[x - ch] if x >= ch else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
        elif f == 4:
            for x in range(stride):
                a = line[x - ch] if x >= ch else 0
                c = prev[x - ch] if x >= ch else 0
                line[x] = (line[x] + paeth(a, prev[x], c)) & 255
        rows.append(bytes(line))
        prev = line
    return W, H, ch, rows


def main():
    W, H, ch, rows = load_png(sys.argv[1])
    scale = 1.25
    bar_h = int(40 * scale)  # 50 物理像素
    y = bar_h // 2

    def px(x):
        o = x * ch
        r = rows[y][o]
        return rows[y][o], rows[y][o + 1], rows[y][o + 2]

    # 黑底上只要不是全黑就算「有东西」，但文字抗锯齿会有微弱边缘，
    # 用亮度阈值 24 过滤掉边缘噪声
    runs = []
    start = None
    for x in range(W):
        r, g, b = px(x)
        on = (r + g + b) > 24
        if on and start is None:
            start = x
        elif not on and start is not None:
            if x - start >= 6:
                runs.append((start, x, x - start))
            start = None
    if start is not None:
        runs.append((start, W, W - start))

    print(f'截图 {W}x{H}  取 y={y}（bar 中线）')
    print(f'{"#":>2} {"x0":>5} {"x1":>5} {"宽px":>6} {"宽逻辑":>7}')
    for i, (a, b, w) in enumerate(runs, 1):
        print(f'{i:>2} {a:>5} {b:>5} {w:>6} {w / scale:>7.1f}')

    if runs:
        right_edge = runs[-1][1]
        print(f'\n右端 x={right_edge}，距屏幕右边 {W - right_edge} 物理px'
              f'（= {(W - right_edge) / scale:.1f} 逻辑px）')
        # 中间那条胶囊：找最长的连续块里靠近屏幕中心的
        mid = W / 2
        cand = min(runs, key=lambda r: abs((r[0] + r[1]) / 2 - mid))
        cx = (cand[0] + cand[1]) / 2
        print(f'最靠中线那块：x={cand[0]}..{cand[1]}  中心={cx:.1f}  '
              f'偏离屏幕中线 {(cx - mid) / scale:+.1f} 逻辑px')


main()
