#!/usr/bin/env python3
"""vcheck: Verilog 静态检查 + 仿真流水线，输出结构化报告和修复提示。

四层静态检查 + 一层仿真：
  syntax  iverilog -g2012 编译（语法、未声明、模块/端口绑定）
  lint    Verilator --lint-only -Wall（阻塞/非阻塞、锁存、位宽、多驱动、组合环路……）
  slang   slang -Weverything（有符号/无符号混合运算、位宽转换、case 默认分支……）
  rules   自定义规则（rules.py：wire 多处 assign 等多驱动、复位遗漏）
  synth   Yosys proc/check（推断锁存器、多驱动、无驱动、逻辑环路、资源统计）
  sim     iverilog + vvp 运行自检测试台（输出 TB_PASS / TB_FAIL）
  vivado  可选：Vivado 综合（服务器上有 Vivado 时用 --vivado 打开）

用法:
  python3 vcheck.py rtl/*.v --top dac_map [--tb tb.sv] [--json r.json] [--md r.md] [--log-dir runs/dac_map]
退出码: 0 = 通过（无 blocker/major，仿真通过）；1 = 未通过；2 = 工具缺失或参数错误。
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time
from collections import Counter, OrderedDict

# ---------------------------------------------------------------- 分类与提示
SEVERITY_ORDER = {"blocker": 0, "major": 1, "minor": 2, "info": 3}

CATEGORY = {
    # category: (severity, hint)
    "SYNTAX":      ("blocker", "语法错误：检查本行和上一行的分号、begin/end、括号、endcase/endmodule 是否配对。"),
    "ELAB":        ("blocker", "未声明 / 无法绑定的信号、模块或端口：检查拼写，信号先声明后使用，实例端口名与模块定义一致。"),
    "BLKSEQ":      ("major",   "时序 always 块（posedge/negedge）里用了阻塞赋值 '='：改为非阻塞 '<='。"),
    "COMBDLY":     ("major",   "组合 always 块里用了非阻塞 '<='：改为阻塞 '='，否则仿真与综合结果可能不一致。"),
    "LATCH":       ("major",   "组合逻辑有未赋值的路径，会推断出锁存器：在 always 块开头给所有输出赋默认值，或补全 else / default。"),
    "WIDTH_TRUNC": ("major",   "位宽截断：确认目标位宽够不够；确实要截断时显式取位，如 y = x[7:0]。"),
    "SIGN":        ("major",   "有符号和无符号混合运算：Verilog 里只要有一个操作数无符号，整个表达式就按无符号算，负数会出错。用 $signed() 统一，或把相关信号声明为 signed。"),
    "MULTIDRIVEN": ("major",   "同一信号被多个 always 块或 assign 驱动：每个信号只在一个 always 块或一条 assign 里赋值。"),
    "LOOP":        ("major",   "组合环路：组合逻辑的输出又回到了自己的输入，需要用寄存器断开，或检查是否写错信号名。"),
    "UNDRIVEN":    ("major",   "信号被使用但没有驱动：补上赋值，或检查是否写错名字。"),
    "IMPLICIT":    ("major",   "隐式线网（未声明就使用）：显式声明 wire 并写明位宽；建议文件开头加 `default_nettype none。"),
    "RANGE":       ("major",   "位选或数组下标越界：检查下标范围和声明的位宽。"),
    "CASE":        ("minor",   "case 没有 default 或没有覆盖全部取值：组合逻辑里会产生锁存器，补 default 分支。"),
    "WIDTH_EXPAND":("minor",   "位宽扩展：确认是零扩展还是符号扩展；常数写明位宽，如 10'd512。"),
    "PARAM_WIDTH": ("minor",   "参数/常量初值的位宽比表达式窄：只要数值本身不超出范围就没问题；可以用 12'(N-1) 这类写法消除提示。"),
    "SIGN_CONV":   ("minor",   "赋值时有符号属性发生变化：确认这里是否需要符号扩展。"),
    "PORT":        ("minor",   "端口没有连接或位宽不匹配：检查实例化时的端口列表。"),
    "CLOCK":       ("minor",   "时钟/复位用法可疑（同一信号既作同步又作异步、时钟进入数据通路等）：确认设计意图。"),
    "SIMONLY":     ("minor",   "仿真专用写法（#延时、initial 里的时序语句）不能综合：RTL 里去掉，放到测试台。"),
    "RESET":       ("minor",   "寄存器在复位分支里没有复位：上电后是不定值 X。除非是故意不复位的数据寄存器，否则在复位分支里补上。"),
    "STYLE":       ("info",    "代码风格提示。"),
    "UNUSED":      ("info",    "未使用的信号/参数：确认是否漏接；确实多余可以删掉。"),
    "OTHER":       ("minor",   "其他警告：阅读原始信息判断。"),
    "SIM_FAIL":    ("blocker", "功能仿真失败：对照规格检查输出在第几个时钟周期有效、边界值、复位值、有符号运算和舍入方式。"),
    "SIM_TIMEOUT": ("blocker", "仿真超时：检查状态机是否卡死、计数器是否永远达不到终值、valid/ready 握手。"),
    "TOOL":        ("info",    "工具信息。"),
    "SYNTH_UNSUPPORTED": ("minor", "Yosys 前端不支持这种写法（iverilog/Verilator 已通过）：综合层检查被跳过；如要让综合检查生效，可把端口初值改成复位赋值。"),
}

VERILATOR_MAP = {
    "BLKSEQ": "BLKSEQ", "COMBDLY": "COMBDLY", "LATCH": "LATCH", "NOLATCH": "STYLE",
    "WIDTH": "WIDTH_TRUNC", "WIDTHTRUNC": "WIDTH_TRUNC", "WIDTHEXPAND": "WIDTH_EXPAND",
    "WIDTHXZEXPAND": "WIDTH_EXPAND", "WIDTHCONCAT": "WIDTH_TRUNC",
    "CASEINCOMPLETE": "CASE", "CASEX": "CASE", "CASEOVERLAP": "CASE", "CASEWITHX": "CASE",
    "MULTIDRIVEN": "MULTIDRIVEN", "UNOPTFLAT": "LOOP", "ALWCOMBORDER": "LOOP",
    "UNDRIVEN": "UNDRIVEN", "IMPLICIT": "IMPLICIT", "SELRANGE": "RANGE",
    "UNUSEDSIGNAL": "UNUSED", "UNUSEDPARAM": "UNUSED", "UNUSEDGENVAR": "UNUSED", "UNUSED": "UNUSED",
    "PINMISSING": "PORT", "PINCONNECTEMPTY": "PORT", "PINNOCONNECT": "PORT",
    "SYNCASYNCNET": "CLOCK", "CLKDATA": "CLOCK", "MULTICLK": "CLOCK",
    "INITIALDLY": "SIMONLY", "STMTDLY": "SIMONLY", "TIMESCALEMOD": "STYLE",
    "DECLFILENAME": "STYLE", "EOFNEWLINE": "STYLE", "VARHIDDEN": "STYLE", "GENUNNAMED": "STYLE",
    "PROCASSWIRE": "ELAB", "BLKANDNBLK": "MULTIDRIVEN", "CMPCONST": "OTHER", "UNSIGNED": "OTHER",
}
# Verilator 里这些只是风格提醒，不当问题
VERILATOR_SKIP = {"DECLFILENAME", "EOFNEWLINE"}

SLANG_MAP = {
    "width-trunc": "WIDTH_TRUNC", "width-expand": "WIDTH_EXPAND", "port-width-trunc": "PORT",
    "port-width-expand": "PORT", "arith-op-mismatch": "SIGN", "sign-compare": "SIGN",
    "sign-conversion": "SIGN_CONV", "case-default": "CASE", "case-enum": "CASE",
    "case-not-wildcard": "CASE", "case-overlap": "CASE", "case-incomplete": "CASE",
    "implicit-net-port": "IMPLICIT", "unused-net": "UNUSED", "unused-variable": "UNUSED",
    "unused-port": "UNUSED", "unused-param": "UNUSED", "unused-but-set-variable": "UNUSED",
    "unused-but-set-net": "UNUSED", "unused-def": "UNUSED", "unused-genvar": "UNUSED",
    "unused-typedef": "UNUSED", "unused-import": "UNUSED", "unused-assertion-decl": "UNUSED",
    "unused-result": "UNUSED", "unused-config-cell": "UNUSED", "unused-config-instance": "UNUSED",
    "multiple-always-assigns": "MULTIDRIVEN", "index-oob": "RANGE", "range-oob": "RANGE",
    "range-width-oob": "RANGE", "unconnected-port": "PORT", "unconnected-unnamed-port": "PORT",
    "implicit-conv": "WIDTH_EXPAND", "float-int-conv": "OTHER", "constant-conversion": "WIDTH_TRUNC",
    "missing-top": "TOOL", "explicit-static": "STYLE", "empty-stmt": "STYLE",
    "empty-member": "STYLE", "empty-body": "STYLE", "dup-attr": "STYLE", "incomplete-return": "OTHER",
    "nonblocking-in-always-comb": "COMBDLY", "blocking-in-always-ff": "BLKSEQ",
    "padding": "STYLE", "useless-cast": "STYLE", "case-dup": "CASE",
}
SLANG_SKIP = {"missing-top", "top-module", "unused-def"}


def issue(stage, tool, code, category, file=None, line=None, col=None, message="", raw=""):
    sev, hint = CATEGORY.get(category, CATEGORY["OTHER"])
    return OrderedDict(stage=stage, tool=tool, code=code, category=category, severity=sev,
                       file=file, line=line, col=col, message=message.strip(), hint=hint,
                       raw=raw.strip()[:400], waived=False, waiver_reason=None)


# 工具输出的 "文件:行:列:" 前缀：兼容 POSIX 路径和 Windows 盘符路径（C:\dir\x.v:12:3:）
FPATH = r"(?:[A-Za-z]:)?[^:\n]*?\.(?:sv|v|vh)"


def run(cmd, cwd=None, timeout=120, stdin=None):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           input=stdin, errors="replace", encoding="utf-8")
        return p.returncode, p.stdout + p.stderr, time.time() - t0, False
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"")
        out = out.decode(errors="replace") if isinstance(out, bytes) else out
        return -9, out, time.time() - t0, True
    except FileNotFoundError:
        return -127, f"tool not found: {cmd[0]}", 0.0, False


def which_or_none(name):
    return shutil.which(name)


def base(p):
    return os.path.basename(p) if p else p

# ---------------------------------------------------------------- 各阶段

def stage_syntax(files, top, incdirs, defines, workdir):
    cmd = ["iverilog", "-g2012", "-o", os.devnull, "-s", top]
    cmd += [f"-I{d}" for d in incdirs] + [f"-D{d}" for d in defines] + files
    rc, out, dt, _ = run(cmd, cwd=workdir)
    issues = []
    for ln in out.splitlines():
        m = re.match(r"^(?P<file>" + FPATH + r"):(?P<line>\d+):\s*(?P<rest>.*)$", ln)
        if not m:
            continue
        rest = m.group("rest")
        if re.match(r"syntax error", rest, re.I):
            issues.append(issue("syntax", "iverilog", "syntax", "SYNTAX", m["file"], int(m["line"]), None, rest, ln))
        elif rest.startswith("error:") or rest.startswith("sorry:"):
            msg = rest.split(":", 1)[1]
            cat = "SYNTAX" if re.search(r"syntax|malformed|Invalid module item|expected", msg, re.I) else "ELAB"
            if re.search(r"port|width", msg, re.I) and "Unable to bind" not in msg and cat != "SYNTAX":
                cat = "ELAB"
            issues.append(issue("syntax", "iverilog", "error", cat, m["file"], int(m["line"]), None, msg, ln))
        elif rest.startswith("warning:"):
            msg = rest.split(":", 1)[1]
            cat = "PORT" if re.search(r"[Pp]ort", msg) else ("WIDTH_TRUNC" if "truncat" in msg else "OTHER")
            if re.search(r"implicit", msg, re.I):
                cat = "IMPLICIT"
            issues.append(issue("syntax", "iverilog", "warning", cat, m["file"], int(m["line"]), None, msg, ln))
    if rc != 0 and not any(i["severity"] == "blocker" for i in issues):
        issues.append(issue("syntax", "iverilog", "error", "ELAB", None, None, None,
                            "iverilog 编译失败：" + out.strip()[-300:], out))
    return dict(ok=rc == 0, rc=rc, seconds=round(dt, 2), log=out[-4000:]), issues


def stage_lint(files, top, incdirs, defines, workdir):
    cmd = ["verilator", "--lint-only", "-Wall", "--top-module", top, "-Wno-fatal",
           "-Wno-DECLFILENAME", "-Wno-EOFNEWLINE", "--timing"]
    cmd += [f"-I{d}" for d in incdirs] + [f"+define+{d}" for d in defines] + files
    rc, out, dt, _ = run(cmd, cwd=workdir)
    if "--timing" in cmd and "Unknown option" in out and "--timing" in out:
        cmd.remove("--timing"); rc, out, dt, _ = run(cmd, cwd=workdir)
    issues = []
    for ln in out.splitlines():
        m = re.match(r"^%(?P<kind>Warning|Error)(?:-(?P<code>[A-Z0-9_]+))?:\s*(?P<file>" + FPATH
                     + r"):(?P<line>\d+):(?P<col>\d+):\s*(?P<msg>.*)$", ln)
        if not m:
            continue
        code = m["code"] or ("ERROR" if m["kind"] == "Error" else "WARN")
        if code in VERILATOR_SKIP:
            continue
        if m["kind"] == "Error" and not m["code"]:
            msg = m["msg"]
            cat = "SYNTAX" if re.search(r"syntax error|Unsupported|unexpected", msg) else "ELAB"
        else:
            cat = VERILATOR_MAP.get(code, "OTHER")
        if cat == "WIDTH_TRUNC" and "Initial value" in m["msg"]:
            src = source_line(m["file"], int(m["line"]), files) or ""
            if re.search(r"\b(localparam|parameter)\b", src) or not re.search(r"\b(reg|wire|logic)\b", src):
                cat = "PARAM_WIDTH"
        issues.append(issue("lint", "verilator", code, cat, m["file"], int(m["line"]), int(m["col"]), m["msg"], ln))
    return dict(ok=not any(i["severity"] in ("blocker", "major") for i in issues), rc=rc,
                seconds=round(dt, 2), log=out[-4000:]), issues


SLANG_RUNNER = r"""
import sys
from pyslang import driver
d = driver.Driver(); d.addStandardArgs()
args = sys.argv[1:]
ok = d.parseCommandLine("slang " + " ".join('"%s"' % a for a in args))
ok = ok and d.processOptions() and d.parseAllSources()
if not ok:
    sys.exit(3)
comp = d.createCompilation()
d.reportCompilation(comp, False)
sys.exit(0 if d.reportDiagnostics(False) else 1)
"""


def stage_slang(files, top, incdirs, defines, workdir):
    try:
        import pyslang  # noqa: F401
    except Exception:
        return dict(ok=True, skipped=True, reason="pyslang 未安装（pip install pyslang）"), []
    args = ["-Weverything", "--top", top, "--ignore-unknown-modules", "--color-diagnostics=false"]
    args += [f"-I{d}" for d in incdirs] + [f"-D{d}" for d in defines] + files
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(SLANG_RUNNER); runner = fh.name
    rc, out, dt, _ = run([sys.executable, "-I", runner] + args, cwd=workdir)
    os.unlink(runner)
    if "--color-diagnostics" in out and "unknown" in out.lower():
        args.remove("--color-diagnostics=false")
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write(SLANG_RUNNER); runner = fh.name
        rc, out, dt, _ = run([sys.executable, "-I", runner] + args, cwd=workdir)
        os.unlink(runner)
    out = re.sub(r"\x1b\[[0-9;]*m", "", out)
    issues = []
    for ln in out.splitlines():
        m = re.match(r"^(?P<file>" + FPATH + r"):(?P<line>\d+):(?P<col>\d+): (?P<sev>warning|error|fatal error): (?P<msg>.*?)(?: \[-W(?P<code>[\w-]+)\])?$", ln)
        if not m:
            continue
        code = m["code"] or ("error" if "error" in m["sev"] else "warning")
        if code in SLANG_SKIP:
            continue
        if "error" in m["sev"]:
            msg = m["msg"]
            cat = "SYNTAX" if re.search(r"expected|syntax|unexpected", msg) else "ELAB"
            if re.search(r"multiple (continuous assignments|drivers)|driven by multiple", msg):
                cat = "MULTIDRIVEN"
        else:
            cat = SLANG_MAP.get(code, "OTHER")
            if code == "arith-op-mismatch":
                # slang 在位宽不同但符号相同时也报；只有一边 signed、一边 unsigned 才是符号问题
                tm = re.findall(r"'([^']*)'", m["msg"])
                if len(tm) >= 2 and (("signed" in tm[0]) == ("signed" in tm[1])):
                    cat = "WIDTH_EXPAND"
        issues.append(issue("slang", "slang", code, cat, m["file"], int(m["line"]), int(m["col"]), m["msg"], ln))
    return dict(ok=not any(i["severity"] in ("blocker", "major") for i in issues), rc=rc,
                seconds=round(dt, 2), log=out[-4000:]), issues


def locate_signal(name, files):
    """在源码里找信号的声明行，给只报信号名的 Yosys 消息补上行号。"""
    pat = re.compile(r"\b(reg|wire|logic|output|input|inout|integer)\b[^;]*?\b" + re.escape(name) + r"\b")
    for f in files:
        try:
            for n, ln in enumerate(open(f, encoding="utf-8", errors="replace"), 1):
                if pat.search(ln.split("//")[0]):
                    return f, n
        except OSError:
            pass
    return None


def shorten_paths(text):
    text = re.sub(r"([A-Za-z]:\\[^\s:'`$]*\\)([\w.\-]+\.s?v)", r"\2", text)
    return re.sub(r"(/[^\s:'`$]+/)([\w.\-]+\.s?v)", r"\2", text)


def stage_synth(files, top, incdirs, defines, workdir, prior_blocked=False):
    if not which_or_none("yosys"):
        return dict(ok=True, skipped=True, reason="yosys 未安装"), []
    incs = " ".join(f"-I{d}" for d in incdirs)
    defs = " ".join(f"-D{d}" for d in defines)
    script = (f"read_verilog -sv -DSYNTHESIS {defs} {incs} " + " ".join(f'"{f}"' for f in files) + "; "
              f"hierarchy -check -top {top}; proc; flatten; opt_clean; check; opt; stat")
    rc, out, dt, _ = run(["yosys", "-p", script], cwd=workdir, timeout=300)
    issues = []
    lines = out.splitlines()
    loc_re = re.compile(r"([A-Za-z]:\\[\w.\\\-]+\.s?v|[\w./\-]+\.s?v):(\d+)")
    for i, ln in enumerate(lines):
        s = ln.strip()
        cat = None
        if "Latch inferred for signal" in s:
            cat = "LATCH"
        elif s.startswith("ERROR:") or re.match(r"^\S+\.s?v:\d+: ERROR:", s):
            cat = "SYNTAX" if re.search(r"syntax error", s) else "ELAB"
            if not prior_blocked:
                # iverilog 已经编译通过，Yosys 报错多半是它的前端不支持某种合法写法（如端口带初值）
                cat = "SYNTH_UNSUPPORTED"
        elif s.startswith("Warning:"):
            if "multiple conflicting drivers" in s or "is driven by multiple" in s:
                cat = "MULTIDRIVEN"
            elif "logic loop" in s:
                cat = "LOOP"
            elif "has no driver" in s or "is used but has no driver" in s:
                cat = "UNDRIVEN"
            elif "implicitly declared" in s:
                cat = "IMPLICIT"
            elif "Resizing cell port" in s:
                cat = "PORT"
            elif "Driver-driver conflict" in s:
                cat = "MULTIDRIVEN"
            elif "Replacing memory" in s or "is ignored" in s or "Ignoring" in s:
                cat = "TOOL"
            else:
                cat = "OTHER"
        if cat is None:
            continue
        # 多驱动/环路的具体信号在后续几行
        ctx = s
        if cat in ("MULTIDRIVEN", "LOOP"):
            ctx = s + " " + " ".join(x.strip() for x in lines[i + 1:i + 4] if x.startswith("    "))
        m = loc_re.search(ctx)
        f, l = (m.group(1), int(m.group(2))) if m else (None, None)
        if cat == "TOOL":
            continue
        if f is None or cat in ("MULTIDRIVEN", "UNDRIVEN", "LATCH"):
            sm = re.search(r"(?:drivers for|conflict for|Wire|loop in module \\S+ :)\s+\\?(?:[\w$]+\.)?\\?(\w+)", ctx) if cat != "LATCH" else re.search(r"signal `\\[\w$]+\.\\(\w+)'", ctx)
            if sm:
                loc = locate_signal(sm.group(1), files)
                if loc and (f is None or cat != "LATCH"):
                    f, l = loc
        ctx = shorten_paths(ctx)
        issues.append(issue("synth", "yosys", cat.lower(), cat, f, l, None, ctx[:300], s))
    stat = {}
    m = re.search(r"Number of cells:\s+(\d+)", out)
    if m:
        stat["cells"] = int(m.group(1))
    for k in ("\\$_DFF", "$dff", "$adff", "$sdff", "$dlatch", "$mul", "$add", "$sub", "$div"):
        pass
    cells = re.findall(r"^\s+(\$\S+)\s+(\d+)\s*$", out, re.M)
    cells += [(name, n) for n, name in re.findall(r"^\s+(\d+)\s+(\$\S+)\s*$", out, re.M)]
    if cells:
        stat["cell_types"] = {}
        for name, n in cells:
            stat["cell_types"][name] = stat["cell_types"].get(name, 0) + int(n)
    ok = rc == 0 and not any(i["severity"] in ("blocker", "major") for i in issues)
    if rc != 0 and not issues:
        issues.append(issue("synth", "yosys", "error", "ELAB" if prior_blocked else "SYNTH_UNSUPPORTED",
                            None, None, None, shorten_paths(out.strip()[-300:]), out))
    if any(i["category"] == "SYNTH_UNSUPPORTED" for i in issues):
        ok = False
    return dict(ok=ok, rc=rc, seconds=round(dt, 2), stat=stat, log=out[-3000:]), issues


def stage_sim(files, tb, tbtop, incdirs, defines, timeout, workdir):
    simdir = tempfile.mkdtemp(prefix="vcheck_sim_")
    vvp = os.path.join(simdir, "sim.vvp")
    cmd = ["iverilog", "-g2012", "-o", vvp, "-s", tbtop] + [f"-I{d}" for d in incdirs]
    cmd += [f"-D{d}" for d in defines] + files + [tb]
    rc, out, dt, _ = run(cmd, cwd=workdir)
    if rc != 0:
        shutil.rmtree(simdir, ignore_errors=True)
        return dict(ok=False, compiled=False, seconds=round(dt, 2), log=out[-3000:]), [
            issue("sim", "iverilog", "tb-compile", "ELAB", None, None, None,
                  "测试台和设计一起编译失败（多半是端口名/位宽和规格不一致）：" + out.strip()[-400:], out)]
    rc, sout, dt2, to = run(["vvp", "-n", vvp], cwd=workdir, timeout=timeout)
    shutil.rmtree(simdir, ignore_errors=True)
    passed = ("TB_PASS" in sout) and ("TB_FAIL" not in sout) and not to and rc == 0
    issues = []
    if to:
        issues.append(issue("sim", "vvp", "timeout", "SIM_TIMEOUT", None, None, None, f"仿真超过 {timeout} s", sout[-500:]))
    elif not passed:
        fails = [l for l in sout.splitlines() if re.search(r"TB_FAIL|FAIL|ERROR|mismatch|expected|fatal", l, re.I)]
        msg = "\n".join(fails[:12]) if fails else sout.strip()[-600:]
        if re.search(r"=\s*[01]*[xX][01xXzZ]*\b", msg):
            msg += ("\n（输出里有 x，即未知值。常见原因：寄存器没复位或没赋初值；组合逻辑写成 always @* 时，"
                    "如果仿真 0 时刻输入没有变化，这个块不会执行，输出一直是 x，可改用 assign 或 always_comb。）")
        issues.append(issue("sim", "vvp", "tb-fail", "SIM_FAIL", None, None, None, msg, sout[-1500:]))
    return dict(ok=passed, compiled=True, seconds=round(dt + dt2, 2), log=sout[-3000:]), issues


VIVADO_TCL = """
set files [list {files}]
foreach f $files {{ read_verilog -sv $f }}
synth_design -top {top} -part {part} -mode out_of_context
report_utilization -file {util}
puts "VCHECK_SYNTH_DONE"
"""


def stage_rules(files):
    """自定义规则层（rules.py）：多驱动、复位遗漏。"""
    import time as _t
    t0 = _t.time()
    try:
        import rules
    except Exception as e:
        return dict(ok=True, skipped=True, reason=f"rules.py 载入失败: {e}"), []
    issues = []
    for f in files:
        try:
            found = rules.analyze(f)
        except Exception as e:  # 规则层出错不影响其他检查
            issues.append(issue("rules", "vcheck-rules", "internal", "TOOL", f, None, None, f"规则层异常: {e}"))
            continue
        for r in found:
            issues.append(issue("rules", "vcheck-rules", r["category"].lower(), r["category"], f, r["line"], None, r["message"]))
    return dict(ok=not any(i["severity"] in ("blocker", "major") for i in issues), seconds=round(_t.time() - t0, 2)), issues


def stage_vivado(files, top, part, workdir):
    if not which_or_none("vivado"):
        return dict(ok=True, skipped=True, reason="vivado 不在 PATH"), []
    d = tempfile.mkdtemp(prefix="vcheck_viv_")
    tcl = os.path.join(d, "s.tcl")
    open(tcl, "w").write(VIVADO_TCL.format(files=" ".join('{%s}' % os.path.abspath(f) for f in files),
                                            top=top, part=part, util=os.path.join(d, "util.txt").replace("\\", "/")))
    rc, out, dt, _ = run(["vivado", "-mode", "batch", "-nojournal", "-nolog", "-source", tcl], cwd=d, timeout=1800)
    issues = []
    for ln in out.splitlines():
        m = re.match(r"^(CRITICAL WARNING|ERROR|WARNING): \[(?P<id>[^\]]+)\] (?P<msg>.*)$", ln)
        if not m:
            continue
        msg, cid = m["msg"], m["id"]
        if "inferring latch" in msg:
            cat = "LATCH"
        elif "multi-driven" in msg or "multiple driver" in msg:
            cat = "MULTIDRIVEN"
        elif ln.startswith("ERROR"):
            cat = "ELAB"
        elif "truncat" in msg or "width" in msg:
            cat = "WIDTH_TRUNC" if "truncat" in msg else "WIDTH_EXPAND"
        elif ln.startswith("CRITICAL"):
            cat = "OTHER"
        else:
            continue
        lm = re.search(r"\[([^\]]+\.s?v):(\d+)\]", msg)
        issues.append(issue("vivado", "vivado", cid, cat, lm.group(1) if lm else None,
                            int(lm.group(2)) if lm else None, None, msg, ln))
    util = open(os.path.join(d, "util.txt")).read()[-3000:] if os.path.exists(os.path.join(d, "util.txt")) else ""
    shutil.rmtree(d, ignore_errors=True)
    ok = "VCHECK_SYNTH_DONE" in out and not any(i["severity"] in ("blocker", "major") for i in issues)
    return dict(ok=ok, rc=rc, seconds=round(dt, 2), utilization=util), issues

# ---------------------------------------------------------------- 汇总

WAIVE_RE = re.compile(r"vcheck-waive:\s*([A-Z_,\s]+?)(?:\s+(.*))?$")


def apply_waivers(issues, files):
    src = {}
    for f in files:
        try:
            src[os.path.abspath(f)] = open(f, encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            pass
    byname = {os.path.basename(k): v for k, v in src.items()}
    for it in issues:
        if not it["file"] or not it["line"]:
            continue
        lines = src.get(os.path.abspath(it["file"])) or byname.get(os.path.basename(it["file"]))
        if not lines:
            continue
        for ln_no in (it["line"], it["line"] - 1):
            if 1 <= ln_no <= len(lines):
                m = WAIVE_RE.search(lines[ln_no - 1])
                if m:
                    cats = {c.strip() for c in m.group(1).replace(",", " ").split()}
                    if it["category"] in cats:
                        it["waived"] = True
                        it["waiver_reason"] = (m.group(2) or "").strip() or "(未写原因)"
                        break


def dedup(issues):
    """不同工具在同一位置报同一类问题时合并，记下是哪几个工具确认的。"""
    out, seen = [], {}
    for it in issues:
        key = (base(it["file"]), it["line"], it["category"]) if it["line"] else None
        if key and key in seen:
            seen[key]["confirmed_by"] = sorted(set(seen[key]["confirmed_by"]) | {it["tool"]})
            continue
        it["confirmed_by"] = [it["tool"]]
        out.append(it)
        if key:
            seen[key] = it
    return out


def source_line(file, line, files):
    for f in files:
        if file and (os.path.abspath(f) == os.path.abspath(file) or os.path.basename(f) == os.path.basename(file)):
            try:
                ls = open(f, encoding="utf-8", errors="replace").read().splitlines()
                if 1 <= line <= len(ls):
                    return ls[line - 1].rstrip()
            except OSError:
                return None
    return None


def to_markdown(rep, files, max_items=30):
    s = rep["summary"]
    L = [f"# vcheck 报告：{rep['top']}", "",
         f"结论：**{'通过' if rep['pass'] else '未通过'}**　blocker {s['blocker']} · major {s['major']} · minor {s['minor']} · info {s['info']} · 已豁免 {s['waived']}", ""]
    L.append("| 阶段 | 结果 | 用时/s |")
    L.append("|---|---|---|")
    for k, v in rep["stages"].items():
        r = "跳过（" + v.get("reason", "") + "）" if v.get("skipped") else ("通过" if v.get("ok") else "有问题")
        L.append(f"| {k} | {r} | {v.get('seconds', '')} |")
    L.append("")
    if not rep.get("static_checks_complete", True):
        L += ["注意：有静态检查层被跳过或工具返回了错误码，这份结论不是完整五层检查的结论。", ""]
    act = [i for i in rep["issues"] if not i["waived"] and i["severity"] != "info"]
    act.sort(key=lambda i: (SEVERITY_ORDER[i["severity"]], i["file"] or "", i["line"] or 0))
    if act:
        L.append("## 需要处理的问题（按严重程度）")
        for n, it in enumerate(act[:max_items], 1):
            loc = f"{base(it['file'])}:{it['line']}" if it["line"] else "（无行号）"
            L.append(f"{n}. **[{it['severity']}] {it['category']}** `{loc}` — {it['message'][:300]}")
            code = source_line(it["file"], it["line"], files) if it["line"] else None
            if code:
                L.append(f"   - 源码：`{code.strip()[:160]}`")
            L.append(f"   - 报告工具：{', '.join(it['confirmed_by'])}；提示：{it['hint']}")
        if len(act) > max_items:
            L.append(f"… 另有 {len(act) - max_items} 条，见 JSON。")
    w = [i for i in rep["issues"] if i["waived"]]
    if w:
        L.append("\n## 已豁免")
        for it in w:
            L.append(f"- {it['category']} `{base(it['file'])}:{it['line']}`：{it['waiver_reason']}")
    sim = rep["stages"].get("sim")
    if sim and not sim.get("skipped") and not sim.get("ok"):
        L.append("\n## 仿真输出（末尾）\n```\n" + sim.get("log", "")[-1200:] + "\n```")
    return "\n".join(L) + "\n"


def check(files, top, tb=None, tbtop=None, incdirs=(), defines=(), stages=None, sim_timeout=120,
          vivado=False, part="xc7z020clg400-2"):
    files = [os.path.abspath(f).replace(chr(92), "/") for f in files]
    workdir = os.path.dirname(files[0]) if files else os.getcwd()
    incdirs = list(incdirs) + sorted({os.path.dirname(f) for f in files})
    stages = stages or ["syntax", "lint", "slang", "rules", "synth", "sim"]
    rep = OrderedDict(top=top, files=[os.path.basename(f) for f in files], time=time.strftime("%Y-%m-%d %H:%M:%S"),
                      tools={}, stages=OrderedDict(), issues=[])
    for t in ("iverilog", "verilator", "yosys", "vivado"):
        rep["tools"][t] = bool(which_or_none(t))
    all_issues = []
    if "syntax" in stages:
        r, i = stage_syntax(files, top, incdirs, defines, workdir); rep["stages"]["syntax"] = r; all_issues += i
    blocked = any(x["severity"] == "blocker" for x in all_issues)
    if "lint" in stages:
        r, i = stage_lint(files, top, incdirs, defines, workdir); rep["stages"]["lint"] = r; all_issues += i
    if "slang" in stages:
        r, i = stage_slang(files, top, incdirs, defines, workdir); rep["stages"]["slang"] = r; all_issues += i
    if "rules" in stages and not blocked:
        r, i = stage_rules(files); rep["stages"]["rules"] = r; all_issues += i
    if "synth" in stages:
        if blocked:
            rep["stages"]["synth"] = dict(ok=False, skipped=True, reason="语法/绑定错误未修好")
        else:
            r, i = stage_synth(files, top, incdirs, defines, workdir, blocked); rep["stages"]["synth"] = r; all_issues += i
    if vivado and not blocked:
        r, i = stage_vivado(files, top, part, workdir); rep["stages"]["vivado"] = r; all_issues += i
    if "sim" in stages and tb:
        if blocked:
            rep["stages"]["sim"] = dict(ok=False, skipped=True, reason="语法/绑定错误未修好")
        else:
            tbtop = tbtop or detect_top(tb)
            r, i = stage_sim(files, os.path.abspath(tb), tbtop, incdirs, defines, sim_timeout, os.path.dirname(os.path.abspath(tb)))
            rep["stages"]["sim"] = r; all_issues += i
    apply_waivers(all_issues, files)
    issues = dedup(all_issues)
    rep["issues"] = issues
    act = [i for i in issues if not i["waived"]]
    c = Counter(i["severity"] for i in act)
    rep["summary"] = OrderedDict(blocker=c["blocker"], major=c["major"], minor=c["minor"], info=c["info"],
                                 waived=sum(1 for i in issues if i["waived"]),
                                 by_category=dict(Counter(i["category"] for i in act)),
                                 raw_by_tool=dict(Counter((i["tool"]) for i in all_issues)))
    sim_ok = rep["stages"].get("sim", {}).get("ok", True) if tb else True
    required = [s for s in ("syntax", "lint", "slang", "rules", "synth") if s in stages]
    ran = [s for s in required if s in rep["stages"] and not rep["stages"][s].get("skipped")]
    # 工具跑了但返回码非 0、又没解析出问题：当作没通过（防止工具出错时漏报）。工具没装而跳过的层不算失败，
    # 但 static_checks_complete 为 False，报告里会注明"不是完整五层"。
    rep["static_checks_complete"] = len(ran) == len(required) and all(rep["stages"][s].get("rc", 0) == 0 for s in ran)
    rep["static_pass"] = all(rep["stages"][s].get("rc", 0) == 0 for s in ran) and not any(
        i["stage"] != "sim" and i["severity"] in ("blocker", "major") for i in act)
    rep["pass"] = rep["static_pass"] and sim_ok and c["blocker"] == 0
    return rep


def detect_top(tb):
    mods = re.findall(r"^\s*module\s+(\w+)", open(tb, encoding="utf-8", errors="replace").read(), re.M)
    return mods[-1] if mods else "tb"


def next_round_dir(log_dir):
    os.makedirs(log_dir, exist_ok=True)
    n = 1 + max([int(m.group(1)) for d in os.listdir(log_dir) for m in [re.match(r"round_(\d+)$", d)] if m] or [0])
    p = os.path.join(log_dir, f"round_{n:02d}")
    os.makedirs(p)
    return p, n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="RTL 源文件（不含测试台）")
    ap.add_argument("--top", required=True)
    ap.add_argument("--tb", help="自检测试台（打印 TB_PASS / TB_FAIL）")
    ap.add_argument("--tb-top")
    ap.add_argument("-I", "--inc", action="append", default=[])
    ap.add_argument("-D", "--define", action="append", default=[])
    ap.add_argument("--stages", default="syntax,lint,slang,rules,synth,sim")
    ap.add_argument("--sim-timeout", type=int, default=120)
    ap.add_argument("--vivado", action="store_true", help="额外跑 Vivado 综合（需要 vivado 在 PATH）")
    ap.add_argument("--part", default="xc7z020clg400-2")
    ap.add_argument("--json"); ap.add_argument("--md")
    ap.add_argument("--log-dir", help="每次检查存一轮：源码副本 + 报告，用于记录纠错过程")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    for t in ("iverilog", "verilator"):
        if not which_or_none(t):
            print(f"缺少 {t}", file=sys.stderr); sys.exit(2)
    rep = check(a.files, a.top, a.tb, a.tb_top, a.inc, a.define, a.stages.split(","), a.sim_timeout, a.vivado, a.part)
    md = to_markdown(rep, [os.path.abspath(f) for f in a.files])
    if a.log_dir:
        d, n = next_round_dir(a.log_dir)
        rep["round"] = n
        for f in a.files:
            shutil.copy(f, d)
        json.dump(rep, open(os.path.join(d, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        open(os.path.join(d, "report.md"), "w", encoding="utf-8").write(md)
    if a.json:
        json.dump(rep, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.md:
        open(a.md, "w", encoding="utf-8").write(md)
    if not a.quiet:
        print(md)
    sys.exit(0 if rep["pass"] else 1)


if __name__ == "__main__":
    main()
