#!/usr/bin/env python3
"""纠错评测按错误类别汇总；可选核对样本是否和指定的 selection 文件一致。

用法：python tools/repair_by_category.py results/repair_xxx/summary.json [selection_balanced.json] [输出.md]
给了输出文件就按 UTF-8 写进去（Windows PowerShell 用 > 重定向会变成 UTF-16，所以建议给输出文件）。
"""
import json, sys
from collections import OrderedDict

ORDER = ["width", "latch", "signed", "multidrive", "reset", "offbyone", "operator"]


def main(summary, selection=None, out=None):
    s = json.load(open(summary, encoding="utf-8"))
    R = s["results"]
    L = []
    if selection:
        want = {f"{x['task']}__{x['mutant']}" for x in json.load(open(selection, encoding="utf-8"))}
        got = {r["task"] for r in R}
        L += [f"样本核对：和 `{selection}` {'完全一致' if want == got else '不一致'}（指定 {len(want)} 个，实际 {len(got)} 个）"]
        if want != got:
            L += [f"- 少了：{sorted(want - got)}", f"- 多了：{sorted(got - want)}"]
        L.append("")
    rows = OrderedDict((op, dict(n=0, orig=0, auto=0, model=0, first=0, final_model=0, final=0)) for op in ORDER)
    calls = 0
    for r in R:
        op = r.get("op", "?")
        d = rows.setdefault(op, dict(n=0, orig=0, auto=0, model=0, first=0, final_model=0, final=0))
        d["n"] += 1
        h0 = [h for h in r["history"] if h.get("round") == 0]
        steps = next((h.get("steps", []) for h in h0 if h.get("source") == "autofix"), [])
        no_model = any(h.get("passed") for h in h0)
        if no_model:
            d["auto" if steps else "orig"] += 1
        else:
            d["model"] += 1
            d["first"] += bool(r["first_pass"])
            d["final_model"] += bool(r["final_pass"])
            calls += sum(1 for h in r["history"] if h.get("round", 0) >= 1)
        d["final"] += bool(r["final_pass"])
    pct = lambda a, b: f"{a}/{b} ({a / b:.0%})" if b else "N/A"
    L += ["| 类别 | 样本 | 原始已过 | autofix 修好 | 模型接手 | 模型第 1 轮修好 | 模型最终修好 | 全流程最终通过 |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
    tot = dict(n=0, orig=0, auto=0, model=0, first=0, final_model=0, final=0)
    for op, d in rows.items():
        if d["n"] == 0:
            continue
        for k in tot:
            tot[k] += d[k]
        L.append(f"| {op} | {d['n']} | {d['orig']} | {d['auto']} | {d['model']} | {pct(d['first'], d['model'])} | "
                 f"{pct(d['final_model'], d['model'])} | {pct(d['final'], d['n'])} |")
    d = tot
    L.append(f"| 合计 | {d['n']} | {d['orig']} | {d['auto']} | {d['model']} | {pct(d['first'], d['model'])} | "
             f"{pct(d['final_model'], d['model'])} | {pct(d['final'], d['n'])} |")
    L += ["", f"模型调用轮次合计：{calls}"]
    txt = "\n".join(L) + "\n"
    if out:
        open(out, "w", encoding="utf-8").write(txt)
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    print(txt)


if __name__ == "__main__":
    main(*sys.argv[1:4])
