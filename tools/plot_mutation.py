#!/usr/bin/env python3
"""把 mutation_eval.json 画成"各类错误被哪一层发现"的堆叠条形图（PNG，用于报告/答辩）。"""
import json, sys, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e0"
C_MAJOR, C_HINT, C_SIM, C_MISS = "#2a78d6", "#1baf7a", "#eb6834", "#c9c8c2"


def pick_font():
    for name in ("Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", "WenQuanYi Zen Hei", "SimHei", "Microsoft YaHei"):
        if any(name in f.name for f in font_manager.fontManager.ttflist):
            return name
    return None


def main(src, out):
    d = json.load(open(src, encoding="utf-8"))
    rows = d["rows"]
    order = ["syntax", "typo", "blocking", "nonblocking", "multidrive", "width", "latch", "signed", "reset", "offbyone", "operator"]
    label = {"syntax": "漏分号", "typo": "信号名写错", "blocking": "时序块用了 =", "nonblocking": "组合块用了 <=",
             "multidrive": "多处驱动", "width": "位宽少 1 位", "latch": "case 缺 default", "signed": "去掉 signed",
             "reset": "漏复位", "offbyone": "边界差 1", "operator": "+/- 写反"}
    data = []
    for op in order:
        rs = [r for r in rows if r["op"] == op]
        if not rs:
            continue
        a = sum(r["static_major"] for r in rs)
        b = sum((not r["static_major"]) and r["static_any"] for r in rs)
        c = sum((not r["static_any"]) and r["sim_fail"] for r in rs)
        m = len(rs) - a - b - c
        data.append((f"{label[op]}（{len(rs)}）", a / len(rs), b / len(rs), c / len(rs), m / len(rs), (a, b, c, m)))
    f = pick_font()
    if f:
        plt.rcParams["font.family"] = f
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(9.6, 0.42 * len(data) + 1.7), dpi=160)
    fig.patch.set_facecolor(SURFACE); ax.set_facecolor(SURFACE)
    y = list(range(len(data)))[::-1]
    names = ["静态检查报错（blocker/major）", "静态检查提示（minor）", "只有测试台发现", "都没发现（等价改动）"]
    cols = [C_MAJOR, C_HINT, C_SIM, C_MISS]
    for yi, (lab, *fr, cnt) in zip(y, data):
        left = 0.0
        for k, (w, col) in enumerate(zip(fr, cols)):
            if w <= 0:
                continue
            ax.barh(yi, w, left=left, height=0.62, color=col, edgecolor=SURFACE, linewidth=2)
            if w >= 0.07:
                ax.text(left + w / 2, yi, str(cnt[k]), ha="center", va="center", fontsize=8.5,
                        color="#ffffff" if col in (C_MAJOR, C_SIM) else INK)
            left += w
    ax.set_yticks(y); ax.set_yticklabels([r[0] for r in data], fontsize=9.5, color=INK)
    ax.set_xlim(0, 1); ax.set_xticks([0, .25, .5, .75, 1]); ax.set_xticklabels(["0", "25%", "50%", "75%", "100%"], color=INK2, fontsize=8.5)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8); ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in cols]
    ax.legend(handles, names, ncol=4, loc="lower left", bbox_to_anchor=(0, 1.01), frameon=False, fontsize=8.5,
              handlelength=1.0, handleheight=0.8, columnspacing=1.2, labelcolor=INK2)
    tot = len(rows)
    det = sum(r["detected_any"] for r in rows)
    fig.text(0.01, 0.985, f"注入的错误被哪一层发现（10 道题，{tot} 个变异体；括号里是个数）", fontsize=11.5, color=INK, va="top", weight="bold")
    fig.text(0.01, 0.012, f"合计：静态报错 {sum(r['static_major'] for r in rows)}，静态提示 {sum((not r['static_major']) and r['static_any'] for r in rows)}，"
             f"只有测试台发现 {sum((not r['static_any']) and r['sim_fail'] for r in rows)}，都没发现 {tot - det}"
             f"（都是去掉 signed：那些地方已显式符号扩展或只按位使用，行为不变）",
             fontsize=8, color=INK2)
    plt.tight_layout(rect=(0, 0.03, 1, 0.935))
    plt.savefig(out, facecolor=SURFACE)
    print("saved", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
