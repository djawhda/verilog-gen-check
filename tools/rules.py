"""vcheck 自定义规则层：补上通用工具查不到的两类问题。

R1 MULTIDRIVEN（major）：同一信号在多个 always 块 / assign / 带初值的 wire 里被驱动。
   wire 被两条 assign 驱动在 Verilog 里是合法的"线与/决议"，iverilog、Verilator、slang 都不报，
   但在 FPGA 设计里几乎一定是错误。
R2 RESET（minor）：带同步/异步复位分支的 always 块里，某个寄存器在正常分支被赋值，复位分支里却没有复位。
   数据通路寄存器有时故意不复位，所以只作提示。
"""
import re

KW = set("""always assign begin end if else case casez casex endcase default posedge negedge or and not
for while repeat forever function endfunction task endtask module endmodule input output inout wire reg
logic integer genvar generate endgenerate localparam parameter signed unsigned initial""".split())


def _blank_comments(src):
    src = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), src, flags=re.S)
    src = re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), src)
    return re.sub(r'"[^"\n]*"', lambda m: '"' + " " * (len(m.group(0)) - 2) + '"', src)


def _line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def _match_block(text, i):
    """text[i:] 以 begin 开头时返回匹配的 end 之后的位置。"""
    depth = 0
    for m in re.finditer(r"\b(begin|end)\b", text[i:]):
        depth += 1 if m.group(1) == "begin" else -1
        if depth == 0:
            return i + m.end()
    return len(text)


def _stmt_end(text, i):
    """单条语句（可能带 if/else）结束的位置。"""
    m = re.match(r"\s*begin\b", text[i:])
    if m:
        return _match_block(text, i + m.start() + len(m.group(0)) - 5)
    j = text.find(";", i)
    j = len(text) if j < 0 else j + 1
    m = re.match(r"\s*else\b", text[j:])
    if m:
        return _stmt_end(text, j + m.end())
    return j


def _lhs_names(body):
    """一段过程代码里被赋值的信号名（含位置）。"""
    out = []
    body_nf = re.sub(r"\bfor\s*\(([^;]*);([^;]*);([^)]*)\)", lambda m: " " * len(m.group(0)), body)
    for m in re.finditer(r"(<=|(?<![<>=!])=(?!=))", body_nf):
        i = m.start()
        cands = [body_nf.rfind(";", 0, i)]
        for kw in ("begin", "else"):
            k = max((mm.end() for mm in re.finditer(r"\b%s\b" % kw, body_nf[:i])), default=-1)
            cands.append(k - 1 if k >= 0 else -1)
        c = body_nf.rfind(":", 0, i)
        if c > body_nf.rfind("?", 0, i) and body_nf.rfind("[", 0, i) < body_nf.rfind("]", 0, i) + 1:
            cands.append(c)
        start = max(cands)
        seg = body_nf[start + 1:i]
        # 去掉 if (...) / case 标签之类前缀
        seg = re.sub(r"^.*\)\s*", "", seg) if seg.count("(") == seg.count(")") and ")" in seg else seg
        if seg.count("(") != seg.count(")"):
            continue  # 在括号里：比较运算
        seg = seg.strip()
        if not seg or re.search(r"[<>!=]$", seg):
            continue
        if seg.startswith("{"):
            names = re.findall(r"\b([A-Za-z_]\w*)\b", re.sub(r"\[[^\]]*\]", "", seg))
        else:
            mm = re.match(r"^([A-Za-z_]\w*)\s*(\[.*\])?$", seg)
            names = [mm.group(1)] if mm else []
        for n in names:
            if n not in KW:
                out.append((n, i))
    return out


def _paren_end(text, k):
    """text[k] 是 "(" 时返回匹配的 ")" 之后的位置。"""
    depth, q = 0, k
    while q < len(text):
        depth += {"(": 1, ")": -1}.get(text[q], 0); q += 1
        if depth == 0:
            break
    return q


def _full_stmt_end(text, i):
    """模块层一条语句结束的位置：if/else 链（else 归最近的 if）、begin…end、for (…) 语句、case…endcase、单条 ;。"""
    m = re.match(r"\s*(if|for)\s*\(", text[i:])
    if m:
        q = _paren_end(text, i + m.end() - 1)
        t_end = _full_stmt_end(text, q)
        if m.group(1) == "if":
            em = re.match(r"\s*else\b", text[t_end:])
            if em:
                return _full_stmt_end(text, t_end + em.end())
        return t_end
    m = re.match(r"\s*begin\b", text[i:])
    if m:
        return _match_block(text, i + m.start() + len(m.group(0)) - 5)
    m = re.match(r"\s*case[zx]?\b", text[i:])
    if m:
        e = re.search(r"\bendcase\b", text[i:])
        return len(text) if not e else i + e.end()
    j = text.find(";", i)
    return len(text) if j < 0 else j + 1


def _gen_if_branches(body, exclude):
    """模块层（不在 always/initial 块里）的 generate if/else 分支：[(编号, 分支 0/1, 起点, 终点)]。
    else if 链里后面的 if 自己再编号，嵌套在前一个 if 的 else 分支里。"""
    out, nid = [], 0
    for m in re.finditer(r"\bif\s*\(", body):
        i = m.start()
        if any(a <= i < b for a, b in exclude):
            continue
        q = _paren_end(body, m.end() - 1)
        t_end = _full_stmt_end(body, q)
        nid += 1
        out.append((nid, 0, q, t_end))
        em = re.match(r"\s*else\b", body[t_end:])
        if em:
            e0 = t_end + em.end()
            out.append((nid, 1, e0, _full_stmt_end(body, e0)))
    return out


def _exclusive(p1, p2, branches):
    """两个位置是否在同一个 generate if 的不同分支里（不会同时被生成）。"""
    a = {b[0]: b[1] for b in branches if b[2] <= p1 < b[3]}
    b = {x[0]: x[1] for x in branches if x[2] <= p2 < x[3]}
    return any(k in b and b[k] != v for k, v in a.items())


def _modules(text):
    for m in re.finditer(r"\bmodule\s+(\w+)(.*?)\bendmodule\b", text, re.S):
        yield m.group(1), m.start(), m.group(0)


def analyze(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    text = _blank_comments(raw)
    issues = []
    for mname, mstart, body in _modules(text):
        # 函数 / 任务体不算驱动
        body_nf = re.sub(r"\b(function|task)\b.*?\b(endfunction|endtask)\b", lambda m: re.sub(r"[^\n]", " ", m.group(0)), body, flags=re.S)
        memories = set(re.findall(r"\b(?:reg|logic|wire)\b[^;=]*?\b(\w+)\s*\[[^\]]*\]\s*;", body_nf))
        loopvars = set(re.findall(r"\b(?:integer|genvar)\s+([\w\s,]+);", body_nf))
        loopvars = {v.strip() for g in loopvars for v in g.split(",")}
        drivers = {}

        def add(name, kind, pos):
            if name in memories or name in loopvars or name in KW:
                return
            drivers.setdefault(name, []).append((kind, _line_of(text, mstart + pos), pos))

        blocks = []     # always / initial 块的范围：里面的 if 是过程语句，不是 generate if
        for am in re.finditer(r"\b(always(_ff|_comb|_latch)?|initial)\b", body_nf):
            j = am.end()
            sm = re.match(r"\s*@\s*(\*|\([^)]*\))", body_nf[j:])
            if sm:
                j += sm.end()
            blocks.append((am.start(), _stmt_end(body_nf, j)))
        gen_br = _gen_if_branches(body_nf, blocks)

        # always 块
        for am in re.finditer(r"\balways(_ff|_comb|_latch)?\b", body_nf):
            j = am.end()
            sm = re.match(r"\s*@\s*(\*|\([^)]*\))", body_nf[j:])
            if sm:
                j += sm.end()
            end = _stmt_end(body_nf, j)
            blk = body_nf[j:end]
            seen = set()
            for n, p in _lhs_names(blk):
                if n not in seen:
                    seen.add(n); add(n, "always", j + p)
            # R2：复位分支
            rm = re.match(r"\s*(?:begin\b\s*(?::\s*\w+)?)?\s*if\s*\(\s*(!|~)?\s*(rst|reset|rst_n|rstn|reset_n|areset|srst|aresetn)\b", blk)
            if rm:
                k = blk.find("(", rm.start(2) - 6)
                depth, q = 0, k
                while q < len(blk):
                    depth += {"(": 1, ")": -1}.get(blk[q], 0); q += 1
                    if depth == 0:
                        break
                rend = _stmt_end(blk, q)
                rst_names = {n for n, _ in _lhs_names(blk[q:rend])}
                rest = [(n, p) for n, p in _lhs_names(blk[rend:])]
                reported = set()
                for n, p in rest:
                    if n not in rst_names and n not in reported and n not in memories:
                        reported.add(n)
                        issues.append(dict(category="RESET", line=_line_of(text, mstart + j + rend + p), name=n,
                                           message=f"寄存器 {n} 在复位分支里没有复位（模块 {mname}）"))
        # assign
        for am in re.finditer(r"\bassign\b([^;]*?)(?<![<>=!])=(?!=)", body_nf):
            lhs = re.sub(r"\[[^\]]*\]", "", am.group(1))
            for n in re.findall(r"\b([A-Za-z_]\w*)\b", lhs):
                add(n, "assign", am.start())
        # wire x = expr;
        for wm in re.finditer(r"\bwire\b([^;=,()\n]*?)\b(\w+)\s*=(?!=)", body_nf):
            add(wm.group(2), "wire 初值", wm.start(2))
        for n, ds in drivers.items():
            if len(ds) > 1:
                # 互斥的 generate if/else 分支里各有一处驱动，只会生成其中一处，不算多驱动
                bad = [d for d in ds if any(e is not d and not _exclusive(d[2], e[2], gen_br) for e in ds)]
                if len(bad) > 1:
                    where = "、".join(f"第 {l} 行（{k}）" for k, l, _ in bad)
                    issues.append(dict(category="MULTIDRIVEN", line=bad[1][1], name=n,
                                       message=f"信号 {n} 有 {len(bad)} 处驱动：{where}"))
    return issues
