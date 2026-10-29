#!/usr/bin/env python3
"""llm_loop：大模型生成 Verilog → vcheck 静态检查 + 测试台 → 把报告反馈给模型修改，循环到通过。

两种模式
  gen     只给规格，让模型从零写 RTL（考"自动生成"）
  repair  给注入了错误的代码和 vcheck 报告，让模型改（考"静态纠错"）

后端（--backend）
  openai     任何 OpenAI 兼容接口（OpenAI、DeepSeek、通义、本地 vLLM……）：--base-url --model，密钥在环境变量
  anthropic  Anthropic Messages API：--model，密钥在 ANTHROPIC_API_KEY
  cmd        任意命令行智能体（例如 Codex CLI）：--cmd 模板里 {prompt_file} 换成提示词文件，
             {out_file} 换成回答文件（模板里没有 {out_file} 时读 stdout）
  replay     测试用：按 --replay-dir/<task>/round_XX.v 依次"回答"，用来验证闭环本身

每一轮都存 prompt、回答、代码、报告，最后汇总 summary.json / summary.md。
例:
  python3 llm_loop.py --mode gen --backend openai --base-url https://api.deepseek.com/v1 --model deepseek-chat \
      --api-key-env DEEPSEEK_API_KEY --out ../results/gen_deepseek
  python3 llm_loop.py --mode gen --backend cmd --cmd 'codex exec --skip-git-repo-check -o {out_file} - < {prompt_file}' \
      --out ../results/gen_codex
"""
import argparse, json, os, re, shutil, subprocess, sys, time, urllib.request
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import benchlib, vcheck, autofix  # noqa: E402

RULES = """你是数字电路 RTL 工程师。按规格写可综合的 Verilog-2001 / SystemVerilog 模块，必须遵守：
1. 模块名、端口名、端口位宽和有无符号、参数名和默认值，与规格完全一致。
2. 时序 always 块（posedge）里只用非阻塞赋值 <=；组合 always 块（always @*）里只用阻塞赋值 =。
3. 组合逻辑在 always 块开头给所有输出赋默认值，case 必须有 default，不能产生锁存器。
4. 每个信号只在一个 always 块或一条 assign 里驱动。
5. 有符号运算：参与运算的操作数都要是 signed（声明为 signed 或用 $signed()），符号扩展写清楚；常数写明位宽。
6. 不要在 RTL 里用 # 延时、$display；除 ROM 的 $readmemh 外不要用 initial。
7. 文件第一行写 `timescale 1ns/1ps。
8. 只输出一个 ```verilog 代码块，里面是完整的设计代码（不要写测试台）。"""

FEEDBACK = """上一版代码没有通过检查。下面是 vcheck 报告（四层静态检查 + 测试台）。
请：逐条修复 blocker 和 major；minor 能改就改，确实不需要改的，在那一行末尾加注释 `// vcheck-waive: 类别 原因`。
保持模块接口不变，输出修改后的完整代码（一个 ```verilog 代码块）。

## 上一版代码
```verilog
{code}
```

## vcheck 报告
{report}"""

REPAIR = """下面这份代码有问题，vcheck 报告附在后面。请根据报告和规格修好它：保持模块接口不变，输出修改后的完整代码（一个 ```verilog 代码块）。

## 待修代码
```verilog
{code}
```

## vcheck 报告
{report}"""


def build_first_prompt(task, mode, code=None, report_md=None):
    head = RULES + "\n\n## 规格\n\n" + task["spec_text"]
    if mode == "gen":
        return head
    return head + "\n\n" + REPAIR.format(code=code, report=report_md)


def feedback_md(rep, files, feedback):
    md = vcheck.to_markdown(rep, files, max_items=25)
    if feedback == "static":
        # 只给静态信息；仿真只告诉通过与否，不给具体失败向量
        md = re.sub(r"\n## 仿真输出（末尾）\n```.*?```", "\n仿真：未通过（static 模式不提供失败细节）。", md, flags=re.S)
        md = re.sub(r"(\*\*\[blocker\] SIM_FAIL\*\*[^\n]*?— ).*?(\n   - )", r"\1测试台未通过\2", md, flags=re.S)
    return md


def extract_code(text, top):
    blocks = re.findall(r"```(?:verilog|systemverilog|sv|v)?\s*\n(.*?)```", text, re.S | re.I)
    cands = [b for b in blocks if re.search(r"\bmodule\s+%s\b" % re.escape(top), b)] or \
            [b for b in blocks if "module" in b]
    if cands:
        return cands[-1].strip() + "\n"
    m = re.search(r"(`timescale[^\n]*\n)?\s*module\b.*\bendmodule\b", text, re.S)
    return (m.group(0).strip() + "\n") if m else None


class Backend:
    def __init__(self, a):
        self.a = a
        self.usage = []

    def ask(self, prompt, task, rnd, workdir):
        b = self.a.backend
        t0 = time.time()
        if b == "openai":
            out = self._openai(prompt)
        elif b == "anthropic":
            out = self._anthropic(prompt)
        elif b == "cmd":
            out = self._cmd(prompt, workdir)
        elif b == "replay":
            p = os.path.join(self.a.replay_dir, task["name"], f"round_{rnd:02d}.v")
            out = "```verilog\n" + open(p, encoding="utf-8").read() + "```" if os.path.exists(p) else "（没有更多回答）"
        else:
            raise SystemExit("未知后端 " + b)
        return out, round(time.time() - t0, 1)

    def _post(self, url, headers, body):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        for attempt in range(4):
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=self.a.timeout) as r:
                    d = json.loads(r.read().decode())
                print(f"[api] ok {time.time() - t0:.0f}s (try {attempt + 1})", file=sys.stderr, flush=True)
                return d
            except Exception as e:  # 网络抖动重试
                print(f"[api] fail {time.time() - t0:.0f}s (try {attempt + 1}/4): {type(e).__name__}: {e}",
                      file=sys.stderr, flush=True)
                if attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))

    def _openai(self, prompt):
        key = os.environ.get(self.a.api_key_env or "OPENAI_API_KEY", "")
        body = dict(model=self.a.model, messages=[{"role": "user", "content": prompt}], temperature=self.a.temperature)
        d = self._post(self.a.base_url.rstrip("/") + "/chat/completions",
                       {"Authorization": "Bearer " + key, "Content-Type": "application/json"}, body)
        self.usage.append(d.get("usage"))
        return d["choices"][0]["message"]["content"]

    def _anthropic(self, prompt):
        key = os.environ.get(self.a.api_key_env or "ANTHROPIC_API_KEY", "")
        body = dict(model=self.a.model, max_tokens=8000, temperature=self.a.temperature,
                    messages=[{"role": "user", "content": prompt}])
        d = self._post((self.a.base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages",
                       {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, body)
        self.usage.append(d.get("usage"))
        return "".join(c.get("text", "") for c in d.get("content", []))

    def _cmd(self, prompt, workdir):
        pf = os.path.join(workdir, "prompt.md")
        of = os.path.join(workdir, "answer.txt")
        open(pf, "w", encoding="utf-8").write(prompt)
        cmd = self.a.cmd.replace("{prompt_file}", pf).replace("{out_file}", of)
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=self.a.timeout, cwd=workdir)
        if "{out_file}" in self.a.cmd and os.path.exists(of):
            return open(of, encoding="utf-8", errors="replace").read()
        return p.stdout


def run_task(task, a, be, start_code=None, label=None):
    name = label or task["name"]
    tdir = os.path.join(a.out, name)
    shutil.rmtree(tdir, ignore_errors=True)
    os.makedirs(tdir)
    hist = []
    code = start_code
    rep = None
    rtl_name = task["top"] + ".v"
    if a.mode == "repair":
        # 第 0 轮：待修代码本身的报告
        p0 = os.path.join(tdir, "round_00"); os.makedirs(p0)
        open(os.path.join(p0, rtl_name), "w", encoding="utf-8").write(code)
        if a.autofix_first:
            _, flog = autofix.autofix(os.path.join(p0, rtl_name), task["top"], os.path.join(task["dir"], task["tb"]))
            code = open(os.path.join(p0, rtl_name), encoding="utf-8").read()
            hist.append(OrderedDict(round=0, source="autofix", steps=[x["fix"] for x in flog]))
        rep = benchlib.check_candidate(task, [os.path.join(p0, rtl_name)])
        json.dump(rep, open(os.path.join(p0, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        if rep["pass"]:
            hist.append(OrderedDict(round=0, passed=True, note="autofix 已修好，不需要模型"))
            return finish(task, name, tdir, hist, a)
        prompt = build_first_prompt(task, "repair", code, feedback_md(rep, [os.path.join(p0, rtl_name)], a.feedback))
    else:
        prompt = build_first_prompt(task, "gen")
    for rnd in range(1, a.rounds + 1):
        rdir = os.path.join(tdir, f"round_{rnd:02d}"); os.makedirs(rdir)
        open(os.path.join(rdir, "prompt.md"), "w", encoding="utf-8").write(prompt)
        try:
            ans, secs = be.ask(prompt, task, rnd, rdir)
        except Exception as e:
            hist.append(OrderedDict(round=rnd, error=f"模型调用失败: {e}")); break
        open(os.path.join(rdir, "response.md"), "w", encoding="utf-8").write(ans or "")
        new = extract_code(ans or "", task["top"])
        if not new:
            hist.append(OrderedDict(round=rnd, model_seconds=secs, error="回答里没有找到代码"))
            prompt = prompt + "\n\n注意：上一次回答里没有 ```verilog 代码块，请只输出完整代码。"
            continue
        f = os.path.join(rdir, rtl_name)
        open(f, "w", encoding="utf-8").write(new)
        rep = benchlib.check_candidate(task, [f])
        json.dump(rep, open(os.path.join(rdir, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        md = feedback_md(rep, [f], a.feedback)
        open(os.path.join(rdir, "report.md"), "w", encoding="utf-8").write(md)
        s = rep["summary"]
        hist.append(OrderedDict(round=rnd, model_seconds=secs,
                                compiled=rep["stages"].get("syntax", {}).get("ok", False),
                                static_pass=rep["static_pass"],
                                sim_pass=rep["stages"].get("sim", {}).get("ok", False),
                                passed=rep["pass"], blocker=s["blocker"], major=s["major"], minor=s["minor"],
                                waived=s["waived"], categories=s["by_category"]))
        if rep["pass"]:
            break
        prompt = build_first_prompt(task, "gen") + "\n\n" + FEEDBACK.format(code=new.strip(), report=md)
    return finish(task, name, tdir, hist, a)


def finish(task, name, tdir, hist, a):
    rounds = [h for h in hist if h.get("round", 0) >= 1]
    first = rounds[0] if rounds else {}
    res = OrderedDict(task=name, top=task["top"], mode=a.mode,
                      first_compiled=bool(first.get("compiled")), first_static_pass=bool(first.get("static_pass")),
                      first_sim_pass=bool(first.get("sim_pass")), first_pass=bool(first.get("passed")),
                      final_pass=any(h.get("passed") for h in hist),
                      rounds_used=len(rounds), history=hist)
    json.dump(res, open(os.path.join(tdir, "result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return res


def summary_md(results, a):
    n = len(results)
    f = lambda k: sum(1 for r in results if r[k])
    L = [f"# llm_loop 结果（{a.mode}，后端 {a.backend}{(' / ' + a.model) if a.model else ''}）", "",
         f"题目 {n}；最多 {a.rounds} 轮；反馈方式 {a.feedback}；时间 {time.strftime('%Y-%m-%d %H:%M:%S')}", "",
         f"- 首轮编译通过：{f('first_compiled')}/{n}",
         f"- 首轮静态干净（无 blocker/major）：{f('first_static_pass')}/{n}",
         f"- 首轮测试台通过：{f('first_sim_pass')}/{n}",
         f"- 首轮全部通过（pass@1）：{f('first_pass')}/{n}",
         f"- 经过纠错循环最终通过：{f('final_pass')}/{n}", "",
         "| 题目 | 首轮编译 | 首轮静态 | 首轮仿真 | 最终 | 轮数 | 各轮 blocker/major/minor |", "|---|---|---|---|---|---|---|"]
    yn = lambda b: "✓" if b else "✗"
    for r in results:
        tr = " → ".join(f"{h.get('blocker', '?')}/{h.get('major', '?')}/{h.get('minor', '?')}" for h in r["history"] if h.get("round", 0) >= 1)
        L.append(f"| {r['task']} | {yn(r['first_compiled'])} | {yn(r['first_static_pass'])} | {yn(r['first_sim_pass'])} | "
                 f"{yn(r['final_pass'])} | {r['rounds_used']} | {tr} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["gen", "repair"], default="gen")
    ap.add_argument("--backend", choices=["openai", "anthropic", "cmd", "replay"], required=True)
    ap.add_argument("--model"); ap.add_argument("--base-url", default="https://api.openai.com/v1")
    ap.add_argument("--api-key-env"); ap.add_argument("--cmd"); ap.add_argument("--replay-dir")
    ap.add_argument("--temperature", type=float, default=0.2); ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--feedback", choices=["full", "static"], default="full",
                    help="full：报告含测试台失败细节；static：只给静态问题，仿真只说通过与否")
    ap.add_argument("--bench", default=benchlib.DEFAULT_BENCH); ap.add_argument("--tasks", nargs="*")
    ap.add_argument("--mutants", help="repair 模式：eval_mutants.py 生成的 mutants 目录")
    ap.add_argument("--ops", nargs="*", help="repair 模式只取这些错误类别")
    ap.add_argument("--per-task", type=int, default=3, help="repair 模式每题最多取几个变异体")
    ap.add_argument("--autofix-first", action="store_true", help="repair 模式先跑确定性 autofix，剩下的再给模型")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.backend in ("openai", "anthropic") and not a.model:
        raise SystemExit("--model 必填")
    if a.backend == "cmd" and not a.cmd:
        raise SystemExit("--cmd 必填")
    os.makedirs(a.out, exist_ok=True)
    tasks = benchlib.load_tasks(a.bench, a.tasks)
    be = Backend(a)
    results = []
    if a.mode == "gen":
        for t in tasks:
            r = run_task(t, a, be); results.append(r)
            print(f"{t['name']:14s} 最终{'通过' if r['final_pass'] else '未通过'}  轮数 {r['rounds_used']}")
    else:
        if not a.mutants:
            raise SystemExit("repair 模式需要 --mutants")
        undetected = {}
        mev = os.path.join(os.path.dirname(os.path.abspath(a.mutants)), "mutation_eval.json")
        if os.path.exists(mev):
            for row in json.load(open(mev, encoding="utf-8"))["rows"]:
                undetected[(row["task"], row["mutant"])] = not row["detected"]
        for t in tasks:
            mdir = os.path.join(a.mutants, t["name"])
            if not os.path.isdir(mdir):
                continue
            # 按错误类别轮流选（每题起始类别错开），保证各类都有样本；原来按目录顺序会只选到编号靠前的几类
            byop = {}
            for d in sorted(os.listdir(mdir)):
                if d.endswith("_autofix") or not os.path.isdir(os.path.join(mdir, d)):
                    continue
                if undetected.get((t["name"], d)):   # 检查链和测试台都发现不了的变异体（多为等价变异）不拿来考纠错
                    continue
                op = d.split("_", 1)[1]
                if a.ops and op not in a.ops:
                    continue
                byop.setdefault(op, []).append(d)
            order = [o for o in (a.ops or sorted(byop)) if o in byop]
            k0 = tasks.index(t) % max(len(order), 1)
            order = order[k0:] + order[:k0]
            chosen = []
            while len(chosen) < a.per_task and any(byop[o] for o in order):
                for o in order:
                    if byop[o] and len(chosen) < a.per_task:
                        chosen.append(byop[o].pop(0))
            for d in chosen:
                op = d.split("_", 1)[1]
                code = open(os.path.join(mdir, d, t["ref"]), encoding="utf-8").read()
                code = re.sub(r"[ \t]*//[^\n]*(标准答案|取自队友)[^\n]*", "", code)   # 不把来源注释给模型
                r = run_task(t, a, be, start_code=code, label=f"{t['name']}__{d}")
                r["op"] = op; results.append(r)
                print(f"{t['name']}/{d:20s} 最终{'通过' if r['final_pass'] else '未通过'}  轮数 {r['rounds_used']}")
    json.dump(dict(args=vars(a), results=results, usage=be.usage), open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    md = summary_md(results, a)
    open(os.path.join(a.out, "summary.md"), "w", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    main()
