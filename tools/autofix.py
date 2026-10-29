#!/usr/bin/env python3
"""autofix：机械类错误的确定性修复（不需要大模型），每一步都重新检查确认。

能修的类别：
  SYNTAX   漏分号：在报错行或上一行行尾补 ';'，重新编译确认
  ELAB     信号名写错：换成编辑距离最近的已声明信号，重新编译确认
  BLKSEQ   时序块阻塞赋值：'=' -> '<='
  COMBDLY  组合块非阻塞赋值：'<=' -> '='
其余类别（锁存、位宽、符号、多驱动、功能错误）涉及设计意图，交给大模型按报告修。

用法: python3 autofix.py file.v --top TOP [--tb tb.sv] [--max-iter 5]
"""
import argparse, json, os, re, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vcheck  # noqa: E402
import mutate  # noqa: E402

FIXABLE = ("SYNTAX", "ELAB", "BLKSEQ", "COMBDLY")


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def score(rep):
    s = rep["summary"]
    return (s["blocker"], s["major"], s["minor"])


def candidates(src_lines, it, src_text):
    """对一条问题给出若干候选改法（新的行列表），由调用方逐个验证。"""
    cat, ln = it["category"], it["line"]
    out = []
    if not ln:
        return out
    i = ln - 1
    if cat == "SYNTAX":
        for j in (i - 1, i, i - 2):
            if 0 <= j < len(src_lines):
                c = mutate.code_part(src_lines[j]).rstrip()
                is_stmt = bool(mutate.assign_positions(c, "<=") or mutate.assign_positions(c, "="))
                if c and (is_stmt or not c.endswith(")")) and not c.endswith((";", "begin", "end", ",", "(", "else")) and \
                   not re.search(r"\b(endcase|endmodule|endfunction|case\s*\(.*\))\s*$", c):
                    new = list(src_lines)
                    rest = src_lines[j][len(mutate.code_part(src_lines[j])):]
                    new[j] = c + ";" + (" " + rest.strip() if rest.strip() else "")
                    out.append(("在第 %d 行行尾补分号" % (j + 1), new))
    elif cat == "ELAB":
        m = re.search(r"`([A-Za-z_]\w*)|'([A-Za-z_]\w*)'|identifier '?([A-Za-z_]\w*)", it["message"] + " " + it["raw"])
        bad = next((g for g in (m.groups() if m else ()) if g), None)
        if bad:
            names = mutate.declared_names(src_text) - {bad}
            ranked = sorted(names, key=lambda n: (edit_distance(bad, n), abs(len(n) - len(bad))))[:2]
            for good in ranked:
                if edit_distance(bad, good) <= max(2, len(bad) // 3):
                    new = [re.sub(r"\b%s\b" % re.escape(bad), good, l) for l in src_lines]
                    out.append((f"把未声明的 {bad} 改成已声明的 {good}", new))
    elif cat in ("BLKSEQ", "COMBDLY") and 0 <= i < len(src_lines):
        c = mutate.code_part(src_lines[i])
        op, rep_op = ("=", "<=") if cat == "BLKSEQ" else ("<=", "=")
        pos = mutate.assign_positions(c, op)
        col = (it.get("col") or 1) - 1
        pos.sort(key=lambda p: abs(p - col))
        for p in pos[:2]:
            new = list(src_lines)
            new[i] = src_lines[i][:p] + rep_op + src_lines[i][p + len(op):]
            out.append((f"第 {ln} 行 '{op}' 改成 '{rep_op}'", new))
    return out


def autofix(path, top, tb=None, max_iter=5, stages=None, log=None):
    """原地修改 path；返回 (最终报告, 修复记录)。"""
    log = log if log is not None else []
    rep = vcheck.check([path], top, tb, stages=stages)
    for _ in range(max_iter):
        todo = [it for it in rep["issues"] if it["category"] in FIXABLE and not it["waived"]
                and os.path.basename(it["file"] or "") == os.path.basename(path)]
        if not todo:
            break
        todo.sort(key=lambda it: (vcheck.SEVERITY_ORDER[it["severity"]], it["line"] or 0))
        src_text = open(path, encoding="utf-8").read()
        lines = src_text.splitlines()
        improved = False
        for it in todo:
            for desc, new in candidates(lines, it, src_text):
                tmpd = tempfile.mkdtemp(prefix="afx_")
                tmp = os.path.join(tmpd, os.path.basename(path))
                for side in os.listdir(os.path.dirname(os.path.abspath(path))):   # ROM 初始化、include 文件
                    if side.endswith((".mem", ".hex", ".coe", ".vh", ".svh")):
                        shutil.copy(os.path.join(os.path.dirname(os.path.abspath(path)), side), tmpd)
                open(tmp, "w", encoding="utf-8").write("\n".join(new) + "\n")
                r2 = vcheck.check([tmp], top, tb, stages=stages)
                shutil.rmtree(tmpd, ignore_errors=True)
                if score(r2) < score(rep):
                    open(path, "w", encoding="utf-8").write("\n".join(new) + "\n")
                    log.append(dict(fix=desc, category=it["category"], before=score(rep), after=score(r2)))
                    rep = vcheck.check([path], top, tb, stages=stages)
                    improved = True
                    break
            if improved:
                break
        if not improved:
            break
    return rep, log


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file"); ap.add_argument("--top", required=True); ap.add_argument("--tb")
    ap.add_argument("--max-iter", type=int, default=5); ap.add_argument("--json")
    a = ap.parse_args()
    rep, log = autofix(a.file, a.top, a.tb, a.max_iter)
    for x in log:
        print(f"已修复 [{x['category']}] {x['fix']}  (blocker/major/minor {x['before']} -> {x['after']})")
    print("结论：", "通过" if rep["pass"] else "仍有问题，剩余交给大模型", rep["summary"]["by_category"])
    if a.json:
        json.dump(dict(log=log, report=rep), open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sys.exit(0 if rep["pass"] else 1)


if __name__ == "__main__":
    main()
