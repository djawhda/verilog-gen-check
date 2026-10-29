#!/usr/bin/env python3
"""错误注入：对标准答案自动注入 11 类常见 RTL 错误，生成待检测/待修复的"坏代码"。

每个变异体只改一处，记录类别、行号和改动说明。
  静态类：syntax  typo  blocking  nonblocking  latch  width  signed  multidrive
  功能类：offbyone  operator  reset       （静态工具原则上查不出，靠测试台）
"""
import argparse, json, os, random, re, sys

KEYWORDS = set("""module endmodule input output inout wire reg logic signed unsigned integer parameter localparam
always begin end if else case endcase default assign posedge negedge function endfunction automatic
initial for genvar generate endgenerate or and not xor""".split())

EXPECT = {
    "syntax": "SYNTAX", "typo": "ELAB", "blocking": "BLKSEQ", "nonblocking": "COMBDLY",
    "latch": "LATCH", "width": "WIDTH_TRUNC", "signed": "SIGN", "multidrive": "MULTIDRIVEN",
    "offbyone": "FUNC", "operator": "FUNC", "reset": "FUNC",
}
DESC = {
    "syntax": "删掉一个分号", "typo": "把一个信号名写错", "blocking": "时序块里 <= 改成 =",
    "nonblocking": "组合块里 = 改成 <=", "latch": "删掉组合 case 的 default 分支",
    "width": "内部信号位宽少 1 位", "signed": "去掉一个 signed", "multidrive": "同一信号多加一个驱动",
    "offbyone": "比较边界差 1", "operator": "+/- 写反", "reset": "漏掉一个复位赋值",
}


def code_part(line):
    return line.split("//")[0]


def blocks(lines):
    """给每一行标注所在的 always 块类型：'seq' / 'comb' / None（近似：到下一个模块级语句为止）。"""
    kind, out = None, []
    for ln in lines:
        c = code_part(ln)
        if re.search(r"\balways\b", c):
            kind = "seq" if re.search(r"@\s*\(\s*(posedge|negedge)", c) else "comb"
        elif re.search(r"^\s*(assign|endmodule|function|module|wire|reg|localparam|always|initial)\b", c):
            kind = None
        out.append(kind)
    return out


def assign_positions(c, op):
    """在一行代码里找赋值运算符的位置（括号平衡、不是比较运算）。"""
    pos = []
    for m in re.finditer(re.escape(op), c):
        i = m.start()
        if op == "=":
            if (i > 0 and c[i - 1] in "<>=!") or (i + 1 < len(c) and c[i + 1] == "="):
                continue
        if op == "<=" and i + 2 < len(c) and c[i + 2] == "=":
            continue
        # 从语句开头（上一个 ; 或行首）到这里括号要平衡
        start = c.rfind(";", 0, i) + 1
        seg = c[start:i]
        seg = re.sub(r"\b(if|case|while)\s*\(.*?\)", "", seg)  # 去掉已闭合的条件
        if seg.count("(") != seg.count(")") or seg.count("[") != seg.count("]") or seg.count("{") != seg.count("}"):
            continue
        if re.search(r"\b(wire|reg|logic|localparam|parameter|integer|for)\b", c[:i]):
            continue
        pos.append(i)
    return pos


def sites_syntax(lines, kinds):
    out = []
    for n, ln in enumerate(lines):
        c = code_part(ln)
        if kinds[n] and c.rstrip().endswith(";") and not re.search(r"\b(endcase|endmodule)\b", c):
            out.append((n, "删掉行尾分号"))
    return out


def mut_syntax(lines, site):
    n, _ = site
    c = code_part(lines[n]); rest = lines[n][len(c):]
    i = c.rstrip().rfind(";")
    lines[n] = c[:i] + c[i + 1:] + rest
    return lines


def declared_names(src):
    names = set()
    for m in re.finditer(r"\b(?:input|output|inout|wire|reg|logic|integer)\b([^;()]*)", strip_c(src)):
        for nm in re.findall(r"\b([A-Za-z_]\w*)\b", re.sub(r"\[[^\]]*\]", "", m.group(1))):
            if nm not in KEYWORDS:
                names.add(nm)
    return names


def strip_c(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def sites_typo(lines, kinds, src):
    names = declared_names(src)
    out = []
    for n, ln in enumerate(lines):
        c = code_part(ln)
        if not kinds[n]:
            continue
        for op in ("<=", "="):
            for i in assign_positions(c, op):
                end = c.find(";", i)
                rhs = c[i + len(op):end if end > 0 else len(c)]
                for m in re.finditer(r"\b([A-Za-z_]\w*)\b", rhs):
                    k = i + len(op) + m.start()
                    if k > 0 and c[k - 1] in "'$`":      # 12'd0 里的 d0、$signed、`define 不算信号名
                        continue
                    if m.group(1) in names:
                        out.append((n, i + len(op) + m.start(), m.group(1)))
                break
    return out


def mut_typo(lines, site):
    n, col, name = site
    lines[n] = lines[n][:col] + name + "_r" + lines[n][col + len(name):]
    return lines


def sites_op(lines, kinds, want_kind, op):
    out = []
    for n, ln in enumerate(lines):
        if kinds[n] != want_kind:
            continue
        for i in assign_positions(code_part(ln), op):
            out.append((n, i))
    return out


def mut_blocking(lines, site):
    n, i = site
    lines[n] = lines[n][:i] + "=" + lines[n][i + 2:]
    return lines


def mut_nonblocking(lines, site):
    n, i = site
    lines[n] = lines[n][:i] + "<=" + lines[n][i + 1:]
    return lines


def sites_latch(lines, kinds):
    out = []
    for n, ln in enumerate(lines):
        if kinds[n] == "comb" or (kinds[n] is None and re.search(r"\bdefault\s*:", code_part(ln))):
            c = code_part(ln)
            if re.match(r"^\s*default\s*:", c) and c.rstrip().endswith(";") and not re.search(r"\bbegin\b", c) or \
               re.match(r"^\s*default\s*:.*\bend\b\s*$", c):
                # 只在组合块或函数里的 case 上做
                out.append((n,))
    return out


def mut_latch(lines, site):
    lines[site[0]] = ""          # 整行删掉（保留空行，行号不变）
    return lines


def sites_width(lines, kinds):
    out = []
    for n, ln in enumerate(lines):
        c = code_part(ln)
        if re.match(r"^\s*(reg|wire)\b", c) and not re.search(r"\b(input|output)\b", c):
            m = re.search(r"\[(\d+)\s*:\s*0\]", c)
            if m and int(m.group(1)) >= 2:
                out.append((n, m.start(), m.end(), int(m.group(1))))
    return out


def mut_width(lines, site):
    n, a, b, w = site
    lines[n] = lines[n][:a] + f"[{w - 1}:0]" + lines[n][b:]
    return lines


def sites_signed(lines, kinds):
    out = []
    for n, ln in enumerate(lines):
        c = code_part(ln)
        for m in re.finditer(r"\bsigned\b\s*", c):
            if c[max(0, m.start() - 1)] == "$":
                continue
            out.append((n, m.start(), m.end()))
        for m in re.finditer(r"\$signed\s*\(", c):
            out.append((n, m.start(), m.end(), "call"))
    return out


def mut_signed(lines, site):
    n, a, b = site[:3]
    ln = lines[n]
    if len(site) == 4:  # 去掉 $signed( ... ) 外壳
        depth, j = 1, b
        while j < len(ln) and depth:
            depth += {"(": 1, ")": -1}.get(ln[j], 0); j += 1
        lines[n] = ln[:a] + "(" + ln[b:j - 1] + ")" + ln[j:]
    else:
        lines[n] = ln[:a] + ln[b:]
    return lines


def sites_multidrive(lines, kinds, src):
    clk = re.search(r"@\s*\(\s*posedge\s+(\w+)", src)
    out = []
    seen = set()
    for n, ln in enumerate(lines):
        c = code_part(ln)
        if kinds[n] == "seq" and clk:
            for i in assign_positions(c, "<="):
                m = re.search(r"(\w+)\s*(\[[^\]]*\])?\s*$", c[:i])
                if m and m.group(1) not in seen and m.group(1) not in KEYWORDS:
                    seen.add(m.group(1)); out.append(("seq", m.group(1), clk.group(1)))
        m = re.match(r"^\s*assign\s+(\w+)\s*=", c) or re.match(r"^\s*wire\b[^=;]*?\b(\w+)\s*=", c)
        if m and m.group(1) not in seen:
            seen.add(m.group(1)); out.append(("assign", m.group(1), None))
    return out


def mut_multidrive(lines, site):
    kind, name, clk = site
    idx = max(i for i, l in enumerate(lines) if re.search(r"\bendmodule\b", l))
    add = f"    always @(posedge {clk}) {name} <= 0;" if kind == "seq" else f"    assign {name} = 0;"
    # 有多个模块时插到定义该信号的那个模块末尾
    for i in range(len(lines)):
        if re.search(r"\bendmodule\b", lines[i]) and any(re.search(r"\b%s\b" % re.escape(name), l) for l in lines[:i]):
            idx = i; break
    lines.insert(idx, add)
    return lines


def sites_offbyone(lines, kinds):
    out = []
    for n, ln in enumerate(lines):
        c = code_part(ln)
        if not (kinds[n] or re.match(r"^\s*(assign|wire)\b", c)):
            continue
        for m in re.finditer(r"(?<![<>=!])(==|<=|>=|<|>)(?![<>])\s*(\d+'[sS]?d)?(\d+)\b", c):
            op = m.group(1)
            if op == "<=" and m.start() in assign_positions(c, "<="):
                continue
            out.append((n, m.start(3), m.end(3), int(m.group(3))))
        for m in re.finditer(r"(?<![<>=!])(<|>)(?![<>=])", c):
            out.append((n, m.start(), m.end(), m.group(1)))
    return out


def mut_offbyone(lines, site):
    n, a, b, v = site
    ln = lines[n]
    if isinstance(v, int):
        lines[n] = ln[:a] + str(v + 1) + ln[b:]
    else:
        lines[n] = ln[:a] + v + "=" + ln[b:]
    return lines


def sites_operator(lines, kinds):
    out = []
    for n, ln in enumerate(lines):
        c = code_part(ln)
        if not (kinds[n] or re.match(r"^\s*(assign|wire)\b", c)):
            continue
        depth = 0
        for i, ch in enumerate(c):
            if ch == "[": depth += 1
            elif ch == "]": depth -= 1
            elif ch in "+-" and depth == 0 and not re.match(r"[^{}]*\)\s*\{", c[i:]):  # 跳过 {(N+1){...}} 复制次数
                prev = c[:i].rstrip()
                if prev and (prev[-1].isalnum() or prev[-1] in ")]_") and not re.search(r"[eE]$", prev):
                    if i + 1 < len(c) and c[i + 1] in "+-:":
                        continue
                    out.append((n, i, ch))
    return out


def mut_operator(lines, site):
    n, i, ch = site
    lines[n] = lines[n][:i] + ("-" if ch == "+" else "+") + lines[n][i + 1:]
    return lines


def sites_reset(lines, kinds):
    out = []
    in_rst, depth = False, 0
    for n, ln in enumerate(lines):
        c = code_part(ln)
        if re.search(r"\bif\s*\(\s*(rst|reset)\b[^)]*\)\s*begin\b", c):
            in_rst, depth = True, 0
            tail = c[c.find("begin") + 5:]
            for m in re.finditer(r"(\w+)\s*<=\s*[^;]+;", tail):
                out.append((n, c.find("begin") + 5 + m.start(), c.find("begin") + 5 + m.end()))
            continue
        if in_rst:
            if re.search(r"^\s*end\b", c):
                in_rst = False; continue
            for m in re.finditer(r"(\w+)\s*<=\s*[^;]+;", c):
                out.append((n, m.start(), m.end()))
    return out


def mut_reset(lines, site):
    n, a, b = site
    lines[n] = lines[n][:a] + " " * 0 + lines[n][b:]
    return lines


OPS = {
    "syntax": (lambda L, K, S: sites_syntax(L, K), mut_syntax),
    "typo": (lambda L, K, S: sites_typo(L, K, S), mut_typo),
    "blocking": (lambda L, K, S: sites_op(L, K, "seq", "<="), mut_blocking),
    "nonblocking": (lambda L, K, S: sites_op(L, K, "comb", "="), mut_nonblocking),
    "latch": (lambda L, K, S: sites_latch(L, K), mut_latch),
    "width": (lambda L, K, S: sites_width(L, K), mut_width),
    "signed": (lambda L, K, S: sites_signed(L, K), mut_signed),
    "multidrive": (lambda L, K, S: sites_multidrive(L, K, S), mut_multidrive),
    "offbyone": (lambda L, K, S: sites_offbyone(L, K), mut_offbyone),
    "operator": (lambda L, K, S: sites_operator(L, K), mut_operator),
    "reset": (lambda L, K, S: sites_reset(L, K), mut_reset),
}


def mutants_for(src, per_op=3, seed=1):
    rng = random.Random(seed)
    lines0 = src.splitlines()
    kinds = blocks(lines0)
    out = []
    for op, (finder, mut) in OPS.items():
        sites = finder(lines0, kinds, src)
        rng.shuffle(sites)
        made = set()
        for s in sites:
            if len(made) >= per_op:
                break
            new = mut(list(lines0), s)
            text = "\n".join(new) + "\n"
            if text == src or text in made:
                continue
            made.add(text)
            line_no = s[0] + 1 if isinstance(s[0], int) else None
            diff = [(i + 1, a, b) for i, (a, b) in enumerate(zip(lines0, new)) if a != b][:1]
            out.append(dict(op=op, expect=EXPECT[op], desc=DESC[op], line=line_no,
                            before=diff[0][1].strip() if diff else None,
                            after=diff[0][2].strip() if diff else (new[-2].strip() if op == "multidrive" else None),
                            text=text))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src"); ap.add_argument("--out", required=True)
    ap.add_argument("--per-op", type=int, default=3); ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    src = open(a.src, encoding="utf-8").read()
    os.makedirs(a.out, exist_ok=True)
    ms = mutants_for(src, a.per_op, a.seed)
    base = os.path.basename(a.src)
    for k, m in enumerate(ms):
        d = os.path.join(a.out, f"{k:03d}_{m['op']}")
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, base), "w", encoding="utf-8").write(m.pop("text"))
        json.dump(m, open(os.path.join(d, "mutation.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(ms)} 个变异体 -> {a.out}")


if __name__ == "__main__":
    main()
