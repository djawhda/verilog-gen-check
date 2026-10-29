---
name: verilog-gen-check
description: 按规格自动生成可综合 Verilog，并用五层静态检查（iverilog、Verilator、slang、自定义规则、Yosys）加测试台做闭环纠错，每一轮都留记录。用于写 RTL、修 RTL 报错、给 FPGA 工程做代码检查。
---

# Verilog 自动生成与静态纠错

这个 skill 让智能体（Codex、Claude 等）按规格写 Verilog，然后反复"检查 → 读报告 → 修改"，直到静态检查干净、测试台通过。检查工具都在 `tools/` 下，报告是结构化的，每条问题带类别、严重程度、源码行和修复提示。

## 0. 环境

第一次使用先确认工具齐全：

```bash
which iverilog verilator yosys          # 缺的话：apt install iverilog verilator yosys
python3 -c "import pyslang"             # 缺的话：pip install pyslang
python3 tools/vcheck.py --help
```

缺 yosys 或 pyslang 时对应层会自动跳过，报告里写明"跳过"，不要当成通过。

## 1. 读规格，先列清单

写代码前先从规格里整理出：

- 端口表：名字、方向、位宽、有无符号；参数名和默认值
- 时序：输出在第几个时钟沿有效、复位是同步还是异步、复位值
- 运算细节：定点格式、舍入方式（截断 / 四舍五入 / 远离零）、溢出和钳位
- 边界：计数器终值、满/空、回绕

规格有歧义就先问，不要猜。

## 2. 写 RTL（编码规范）

1. 模块名、端口、参数与规格完全一致。
2. 时序块（`always @(posedge clk)`）只用 `<=`；组合块（`always @*`）只用 `=`。
3. 组合块开头给所有输出赋默认值，`case` 必须有 `default`，不能产生锁存器。
4. 每个信号只在一个 always 块或一条 assign 里驱动。
5. 有符号运算：操作数都要是 signed（声明或 `$signed()`），符号扩展写清楚；常数写明位宽（`10'd512`、`48'sd0`）。
6. RTL 里不用 `#` 延时和 `$display`；除 ROM 的 `$readmemh` 外不用 `initial`。
7. 每个寄存器都在复位分支里复位（故意不复位的数据寄存器要注释说明）。
8. 文件第一行 `` `timescale 1ns/1ps ``。

## 3. 检查与纠错循环

```bash
# 先让确定性修复处理机械错误（漏分号、信号名写错、阻塞/非阻塞用反）
python3 tools/autofix.py rtl/top.v --top top --tb tb/tb_top.sv
# 完整检查；--log-dir 每跑一次自动存一轮（源码副本 + report.json + report.md）
python3 tools/vcheck.py rtl/top.v --top top --tb tb/tb_top.sv --log-dir runs/top
```

读 `report.md`，按 **blocker → major → minor** 的顺序修，每改一次重跑 vcheck。

| 严重程度 | 含义 | 处理 |
|---|---|---|
| blocker | 编不过、仿真失败或超时 | 必须修 |
| major | 很可能是错误：阻塞/非阻塞用反、锁存器、位宽截断、有符号和无符号混算、多驱动、未驱动、隐式线网、越界 | 必须修，或者写明理由豁免 |
| minor | 需要看一眼：case 缺 default、位宽扩展、符号转换、复位遗漏、参数位宽 | 能改就改 |
| info | 未使用信号、风格 | 可忽略 |

**豁免**：确认无害时，在那一行行尾写 `// vcheck-waive: 类别 原因`，例如
`integer_result <= unscaled >>> 16;  // vcheck-waive: WIDTH_TRUNC 乘积范围 -56..64，8 位够用`。
报告会单独列出所有豁免。**不要用豁免掩盖没弄懂的问题。**

**停止条件**：vcheck 结论为"通过"就停。5 轮还没通过就停下来，汇报剩下的问题和你的判断，不要继续乱改。

## 4. 没有测试台时

按规格写自检测试台：参考模型要**独立按规格实现**，不能照抄 RTL；逐周期比较输出；覆盖复位、边界值、随机值；最后打印 `TB_PASS ...` 或 `TB_FAIL ...`。输入在下降沿改变、检查放在上升沿之后，避免竞争。

## 5. 上板前（可选）

服务器上有 Vivado 时加 `--vivado --part xc7z020clg400-2`，额外跑一次 Vivado 综合（检查锁存器、多驱动等综合警告）。

## 6. 交付

- 最终 RTL 和最终 `report.md`
- `runs/<top>/round_XX/`：每一轮的代码和报告（这就是纠错过程的证据）
- 一句话总结：用了几轮、修掉了哪些类别的问题、有哪些豁免

## 7. 批量评测（比赛展示用）

```bash
# 错误注入：11 类错误各层检出率 + 确定性修复率（不需要大模型）
python3 tools/eval_mutants.py --out results/mutation
# 生成评测：只给规格，看首轮通过率和纠错后通过率
python3 tools/llm_loop.py --mode gen --backend openai --base-url <接口> --model <模型> --api-key-env <变量名> --out results/gen_<模型>
# 纠错评测：给注入错误的代码和报告，看能修好多少
python3 tools/llm_loop.py --mode repair --mutants results/mutation/mutants --autofix-first --backend ... --out results/repair_<模型>
```
