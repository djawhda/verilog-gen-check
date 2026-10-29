"""用完整工具链（Icarus + Verilator + slang + 自定义规则 + Yosys + 仿真）复核 llm_loop 评测产出的 RTL。
用法：python3 tools/recheck_full.py <verilog_skill 目录> <评测结果目录（含 gen_*、repair_* 子目录）> <输出.json>"""
import glob, json, os, shutil, sys, tempfile
SK = sys.argv[1]          # verilog_skill 目录
EV = sys.argv[2]          # 评测解压目录
OUT = sys.argv[3]
sys.path.insert(0, os.path.join(SK, "tools"))
import benchlib  # noqa: E402

tasks = {t["name"]: t for t in benchlib.load_tasks(os.path.join(SK, "bench"))}
STAGES = ["syntax", "lint", "slang", "rules", "synth", "sim"]


def check(task, src):
    d = tempfile.mkdtemp(prefix="rc_")
    f = os.path.join(d, task["top"] + ".v")
    shutil.copy(src, f)
    rep = benchlib.check_candidate(task, [f], stages=STAGES)
    s = rep["summary"]
    cats = sorted(set(i["category"] for i in rep["issues"] if i["severity"] in ("blocker", "major")))
    minor = sorted(set(i["category"] for i in rep["issues"] if i["severity"] == "minor"))
    tools = sorted(set(i.get("tool", "") for i in rep["issues"] if i["severity"] in ("blocker", "major")))
    shutil.rmtree(d, ignore_errors=True)
    return dict(passed=bool(rep["pass"]), static_pass=bool(rep["static_pass"]), blocker=s["blocker"], major=s["major"],
                minor=s["minor"], cats=cats, minor_cats=minor, tools=tools)


def rounds(tdir):
    return sorted(glob.glob(os.path.join(tdir, "round_[0-9][0-9]")))


res = {}
RUNS = sorted(d for d in os.listdir(EV) if os.path.isdir(os.path.join(EV, d)))
for run in [d for d in RUNS if d.startswith("gen_")]:
    res[run] = {}
    for tdir in sorted(glob.glob(os.path.join(EV, run, "*/"))):
        name = os.path.basename(tdir.rstrip("/"))
        if name not in tasks:
            continue
        t = tasks[name]
        rr = [r for r in rounds(tdir) if os.path.exists(os.path.join(r, t["top"] + ".v"))]
        server = json.load(open(os.path.join(tdir, "result.json"), encoding="utf-8"))
        res[run][name] = dict(first=check(t, os.path.join(rr[0], t["top"] + ".v")),
                              final=check(t, os.path.join(rr[-1], t["top"] + ".v")),
                              n_rounds=len(rr), server_first=server["first_pass"], server_final=server["final_pass"])
        print(run, name, res[run][name]["first"]["passed"], res[run][name]["final"]["passed"], flush=True)

for run in [d for d in RUNS if d.startswith("repair_")]:
  res[run] = {}
  for tdir in sorted(glob.glob(os.path.join(EV, run, "*/"))):
      name = os.path.basename(tdir.rstrip("/"))
      base = name.split("__")[0]
      if base not in tasks:
          continue
      t = tasks[base]
      server = json.load(open(os.path.join(tdir, "result.json"), encoding="utf-8"))
      mut = os.path.join(tdir, "round_00", "before_autofix.v")
      rr = [r for r in rounds(tdir) if r[-2:] != "00" and os.path.exists(os.path.join(r, t["top"] + ".v"))]
      e = dict(op=server.get("op"), model_called=server.get("model_called"), server_initial_pass=server.get("initial_pass"),
               server_final=server["final_pass"], mutant=check(t, mut))
      if rr:
          e["model_final"] = check(t, os.path.join(rr[-1], t["top"] + ".v")); e["n_rounds"] = len(rr)
      res[run][name] = e
      print(run, name, "mutant", e["mutant"]["passed"], e["mutant"]["cats"], "model", e.get("model_final", {}).get("passed"), flush=True)

json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
