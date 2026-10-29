#!/usr/bin/env python3
"""错误注入评测：统计各类注入错误被哪一层发现，以及确定性自动修复能修好多少。

对每道题：标准答案先跑一遍作为基线；每个变异体跑 vcheck（四层静态 + 测试台），
只把"比基线多出来的问题"算作检出。然后对变异体跑 autofix，看能否恢复到通过。

用法: python3 eval_mutants.py --out ../results/mutation [--per-op 4] [--seed 1] [--jobs 2]
"""
import argparse, json, os, shutil, sys, time
from collections import Counter, OrderedDict, defaultdict
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import benchlib, mutate, vcheck, autofix  # noqa: E402

STATIC_TOOLS = ("iverilog", "verilator", "slang", "vcheck-rules", "yosys", "spec-rule")


def sig(rep, min_sev="minor"):
    lim = vcheck.SEVERITY_ORDER[min_sev]
    return Counter((i["tool"], i["category"]) for i in rep["issues"]
                   if i["stage"] not in ("sim",) and vcheck.SEVERITY_ORDER[i["severity"]] <= lim and not i["waived"])


def new_issues(rep, base_sig, min_sev="minor"):
    s = sig(rep, min_sev)
    return {k: v - base_sig.get(k, 0) for k, v in s.items() if v > base_sig.get(k, 0)}


def run_one(job):
    task, mdir, base_minor, base_major = job
    m = json.load(open(os.path.join(mdir, "mutation.json"), encoding="utf-8"))
    rtl = os.path.join(mdir, task["ref"])
    t0 = time.time()
    rep = benchlib.check_candidate(task, [rtl])
    new_minor = new_issues(rep, Counter({tuple(k.split("|")): v for k, v in base_minor.items()}), "minor")
    new_major = new_issues(rep, Counter({tuple(k.split("|")): v for k, v in base_major.items()}), "major")
    sim = rep["stages"].get("sim", {})
    row = OrderedDict(task=task["name"], mutant=os.path.basename(mdir), op=m["op"], expect=m["expect"],
                      line=m["line"], before=m["before"], after=m["after"])
    row["static_major"] = bool(new_major)
    row["static_any"] = bool(new_minor)
    row["tools_major"] = sorted({k[0] for k in new_major})
    row["tools_any"] = sorted({k[0] for k in new_minor})
    row["categories"] = sorted({k[1] for k in new_minor})
    row["expected_hit"] = m["expect"] in row["categories"] or (m["expect"] == "ELAB" and "SYNTAX" in row["categories"])
    row["sim_ran"] = not sim.get("skipped", False) and "sim" in rep["stages"]
    row["sim_fail"] = row["sim_ran"] and not sim.get("ok", False)
    row["detected"] = row["static_major"] or row["sim_fail"]
    row["detected_any"] = row["static_any"] or row["sim_fail"]
    row["initial_pass"] = bool(rep["pass"])
    row["check_seconds"] = round(time.time() - t0, 2)
    # 确定性自动修复
    fixdir = mdir + "_autofix"
    shutil.rmtree(fixdir, ignore_errors=True)
    os.makedirs(fixdir)
    shutil.copy(rtl, fixdir)
    for f in task.get("extra_files", []):
        shutil.copy(os.path.join(task["dir"], f), fixdir)
    frtl = os.path.join(fixdir, task["ref"])
    try:
        frep, flog = autofix.autofix(frtl, task["top"], os.path.join(task["dir"], task["tb"]))
        frep2 = benchlib.check_candidate(task, [frtl])
        row["autofix_steps"] = [x["fix"] for x in flog]
        row["autofix_pass"] = bool(frep2["pass"]) and not row["initial_pass"]
    except Exception as e:  # 记录而不中断
        row["autofix_steps"] = ["异常: %s" % e]
        row["autofix_pass"] = False
    return row


def summarize(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["op"]].append(r)
    order = list(mutate.OPS.keys())
    table = []
    for op in order + ["合计"]:
        rs = rows if op == "合计" else by.get(op, [])
        if not rs:
            continue
        n = len(rs)
        simr = [r for r in rs if r["sim_ran"]]
        d = OrderedDict(op=op, desc=mutate.DESC.get(op, "全部"), n=n,
                        static_major=sum(r["static_major"] for r in rs),
                        static_any=sum(r["static_any"] for r in rs),
                        expected_hit=sum(r["expected_hit"] for r in rs),
                        sim_ran=len(simr), sim_fail=sum(r["sim_fail"] for r in simr),
                        detected=sum(r["detected"] for r in rs),
                        detected_any=sum(r["detected_any"] for r in rs),
                        static_only=sum(r["static_major"] and not r["sim_fail"] for r in rs),
                        sim_only=sum(r["sim_fail"] and not r["static_major"] for r in rs),
                        missed=sum(not r["detected_any"] for r in rs),
                        initial_fail=sum(not r["initial_pass"] for r in rs),
                        autofix_pass=sum(r["autofix_pass"] for r in rs))
        for t in STATIC_TOOLS:
            d["tool_" + t] = sum(t in r["tools_any"] for r in rs)
        table.append(d)
    return table


def pct(a, b):
    return "—" if b == 0 else f"{100.0 * a / b:.0f}%"


def to_md(table, rows, meta):
    L = ["# 错误注入评测结果", "",
         f"生成时间 {meta['time']}；题目 {meta['tasks']} 道；变异体 {len(rows)} 个（每类每题最多 {meta['per_op']} 个，随机种子 {meta['seed']}）。",
         "检出 = 比标准答案多出 blocker/major 级静态问题，或测试台失败。提示 = 多出 minor 级问题。", "",
         "## 各类错误由哪一层发现", "",
         "| 注入的错误 | 个数 | 静态检出(major+) | 静态有提示 | 命中预期类别 | 仿真失败/跑了仿真 | 总检出 | 只有静态发现 | 只有仿真发现 | 完全漏掉 | autofix 修好/原本不通过 |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in table:
        L.append(f"| {d['desc']}（{d['op']}） | {d['n']} | {d['static_major']} ({pct(d['static_major'], d['n'])}) | "
                 f"{d['static_any']} ({pct(d['static_any'], d['n'])}) | {d['expected_hit']} | {d['sim_fail']}/{d['sim_ran']} | "
                 f"{d['detected']} ({pct(d['detected'], d['n'])}) | {d['static_only']} | {d['sim_only']} | {d['missed']} | "
                 f"{d['autofix_pass']}/{d['initial_fail']} ({pct(d['autofix_pass'], d['initial_fail'])}) |")
    L += ["", "## 各工具贡献（报出新问题的变异体个数，minor 及以上）", "",
          "| 注入的错误 | " + " | ".join(STATIC_TOOLS) + " |", "|---|" + "---|" * len(STATIC_TOOLS)]
    for d in table:
        L.append(f"| {d['desc']} | " + " | ".join(str(d['tool_' + t]) for t in STATIC_TOOLS) + " |")
    miss = [r for r in rows if not r["detected_any"]]
    if miss:
        L += ["", "## 完全漏掉的变异体（静态和测试台都没发现）", "",
              "这类改动在本题测试台覆盖的输入下与原设计行为相同（等价变异），或测试台覆盖不足。", ""]
        for r in miss:
            L.append(f"- {r['task']} / {r['mutant']} 第 {r['line']} 行：`{r['before']}` → `{r['after']}`")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench", default=benchlib.DEFAULT_BENCH)
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-op", type=int, default=4); ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--tasks", nargs="*")
    a = ap.parse_args()
    tasks = benchlib.load_tasks(a.bench, a.tasks)
    mroot = os.path.join(a.out, "mutants")
    shutil.rmtree(mroot, ignore_errors=True)
    jobs = []
    for t in tasks:
        ref = os.path.join(t["dir"], t["ref"])
        base = benchlib.check_candidate(t, [ref])
        assert base["pass"], f"标准答案 {t['name']} 没通过，先修题库"
        bmin = {"|".join(k): v for k, v in sig(base, "minor").items()}
        bmaj = {"|".join(k): v for k, v in sig(base, "major").items()}
        src = open(ref, encoding="utf-8").read()
        for k, m in enumerate(mutate.mutants_for(src, a.per_op, a.seed)):
            d = os.path.join(mroot, t["name"], f"{k:03d}_{m['op']}")
            os.makedirs(d)
            open(os.path.join(d, t["ref"]), "w", encoding="utf-8").write(m.pop("text"))
            json.dump(m, open(os.path.join(d, "mutation.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            jobs.append((t, d, bmin, bmaj))
    t0 = time.time()
    with Pool(a.jobs) as p:
        rows = p.map(run_one, jobs, chunksize=1)
    table = summarize(rows)
    meta = dict(time=time.strftime("%Y-%m-%d %H:%M:%S"), tasks=len(tasks), per_op=a.per_op, seed=a.seed,
                seconds=round(time.time() - t0, 1),
                tools={t: bool(shutil.which(t)) for t in ("iverilog", "verilator", "yosys")})
    json.dump(dict(meta=meta, table=table, rows=rows), open(os.path.join(a.out, "mutation_eval.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    open(os.path.join(a.out, "mutation_eval.md"), "w", encoding="utf-8").write(to_md(table, rows, meta))
    print(to_md(table, rows, meta))
    print(f"用时 {meta['seconds']} s")


if __name__ == "__main__":
    main()
