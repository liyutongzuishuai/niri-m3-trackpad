#!/usr/bin/env python3
"""按 ligature 名查 Material Symbols 字体里的码点。

用法：
    python3 tools/find-icon.py eco battery_saver bolt rocket_launch

原理：Material Symbols 是 ligature 字体 —— 输入文字名（如 "eco"）时，
GSUB 会把这一串字符替换成对应字形。所以要反过来查：
先建「字形名 → 码点」映射，再从 GSUB 的 ligature 表里找出
「输入序列 → 字形」，就能知道某个名字最终指向哪个码点。
"""
import sys
from fontTools.ttLib import TTFont

FONT = (str(Path.home() / ".local/share/fonts/") +
        "MaterialSymbolsRounded.ttf")


def build_index(path):
    f = TTFont(path)
    cmap = f.getBestCmap()
    name2cp = {}
    for cp, gname in cmap.items():
        name2cp.setdefault(gname, cp)

    # GSUB 里的 ligature：component 序列 → ligature 字形名
    ligatures = {}
    if "GSUB" in f:
        for lookup in f["GSUB"].table.LookupList.Lookup:
            for st in getattr(lookup, "SubTable", []):
                if not hasattr(st, "ligatureSets"):
                    continue
                for li, ligset in enumerate(st.ligatureSets):
                    if ligset is None:
                        continue
                    for lig in ligset:
                        comps = lig.Component
                        word = "".join(
                            chr(name2cp.get(c, 0)) for c in comps
                        ).strip()
                        if word and word.isprintable():
                            ligatures.setdefault(word, lig.LigGlyph)
    return cmap, name2cp, ligatures


def main(argv):
    cmap, name2cp, ligatures = build_index(FONT)
    print(f"字体：{FONT}\n码点数 {len(cmap)}，ligature {len(ligatures)}\n")
    if not argv:
        argv = ["eco", "battery_saver", "bolt", "rocket_launch"]
    for want in argv:
        cp = None
        glyph = ligatures.get(want)
        if glyph and glyph in name2cp:
            cp = name2cp[glyph]
        elif want in name2cp:
            cp = name2cp[want]
        if cp is None:
            # 再退一步：字形名里包含这个词
            cands = [(c, g) for c, g in cmap.items() if want in str(g)]
            if cands:
                c, g = sorted(cands)[0]
                print(f"{want:24} U+{c:04X}  (字形名 {g})")
            else:
                print(f"{want:24} 找不到")
        else:
            print(f"{want:24} U+{cp:04X}  → {chr(cp)!r}")


if __name__ == "__main__":
    main(sys.argv[1:])
