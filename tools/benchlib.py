"""题库公共函数：读题目、检查一份候选 RTL（vcheck + 题目专用规则）。"""
import json, os, re, sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vcheck  # noqa: E402

DEFAULT_BENCH = os.path.join(os.path.dirname(HERE), "bench")


def load_tasks(bench_dir=DEFAULT_BENCH, names=None):
    tasks = []
    for d in sorted(os.listdir(bench_dir)):
        p = os.path.join(bench_dir, d, "meta.json")
        if not os.path.isfile(p):
            continue
        if names and d not in names:
            continue
        m = json.load(open(p, encoding="utf-8"))
        m["dir"] = os.path.join(bench_dir, d)
        m["name"] = d
        m["spec_text"] = open(os.path.join(m["dir"], m["spec"]), encoding="utf-8").read()
        tasks.append(m)
    return tasks


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def spec_rule_issues(task, files):
    """题目专用规则（例如 booth_mul4 禁止乘法运算符）。"""
    out = []
    for rule in task.get("forbid", []):
        for f in files:
            src = strip_comments(open(f, encoding="utf-8", errors="replace").read())
            src = re.sub(r"\(\*.*?\*\)", "", src)            # 属性 (* ... *)
            src = re.sub(r'"[^"\n]*"', '""', src)               # 字符串
            src = re.sub(r"@\s*\(\s*\*\s*\)|@\s*\*", "@()", src)  # always @* / @(*)
            for n, ln in enumerate(src.splitlines(), 1):
                if re.search(rule["regex"], ln):
                    it = vcheck.issue("spec", "spec-rule", "forbid", "SPEC_RULE", f, n, None, rule["why"], ln)
                    it["severity"] = "major"
                    it["hint"] = "违反题目规格的硬性要求：" + rule["why"]
                    out.append(it)
    return out


def check_candidate(task, rtl_files, log_dir=None, stages=None, sim_timeout=120):
    import shutil
    for f in task.get("extra_files", []):      # 例如 ROM 初始化文件，综合检查要在源码目录里找到它
        for r in rtl_files:
            dst = os.path.join(os.path.dirname(os.path.abspath(r)), f)
            if not os.path.exists(dst):
                shutil.copy(os.path.join(task["dir"], f), dst)
    rep = vcheck.check(rtl_files, task["top"], tb=os.path.join(task["dir"], task["tb"]),
                       stages=stages, sim_timeout=sim_timeout)
    extra = spec_rule_issues(task, rtl_files)
    if extra:
        rep["issues"].extend(extra)
        rep["summary"]["major"] += len(extra)
        rep["summary"]["by_category"]["SPEC_RULE"] = len(extra)
        rep["static_pass"] = False
        rep["pass"] = False
    if log_dir:
        d, n = vcheck.next_round_dir(log_dir)
        rep["round"] = n
        import shutil
        for f in rtl_files:
            shutil.copy(f, d)
        md = vcheck.to_markdown(rep, rtl_files)
        json.dump(rep, open(os.path.join(d, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        open(os.path.join(d, "report.md"), "w", encoding="utf-8").write(md)
    return rep


def validate(bench_dir=DEFAULT_BENCH):
    """标准答案必须：静态无 blocker/major，测试台通过。"""
    rows = []
    for t in load_tasks(bench_dir):
        rep = check_candidate(t, [os.path.join(t["dir"], t["ref"])])
        rows.append(OrderedDict(task=t["name"], passed=rep["pass"], minor=rep["summary"]["minor"],
                                sim=rep["stages"].get("sim", {}).get("log", "").strip().splitlines()[:1]))
    return rows


if __name__ == "__main__":
    for r in validate(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BENCH):
        print(("OK  " if r["passed"] else "BAD ") + r["task"].ljust(14), "minor=%d" % r["minor"], r["sim"])
