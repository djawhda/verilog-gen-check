# weighted_sum：Booth 部分积加权求和（0.45 倍，带舍入的流水线）

Booth 乘法器 FPGA 模型里的累加模块。两路部分积（Q20 定点，单位 V）按 `PP0 + 4·PP1` 合成，再乘 9/20（对应原电路 400k/888.9k 和 400k/222.2k 的电阻比）。

## 接口

```verilog
module weighted_sum(
    input  wire               clk,
    input  wire               rst,                 // 同步复位，高有效
    input  wire signed [31:0] pp0_q20,
    input  wire signed [31:0] pp1_q20,
    output wire signed [31:0] unscaled_q20,        // 组合输出
    output reg  signed [31:0] inverting_sum_q20,
    output reg  signed [31:0] product_q20
);
```

## 行为

- `unscaled_q20 = pp0_q20 + 4·pp1_q20`（组合逻辑，32 位）。
- 记 `u` 为 `unscaled_q20[27:0]` 按 28 位有符号数解释。题目保证 `|u| ≤ 14 000 000`。
- `R = round(9·u / 20)`，舍入方式为**四舍五入、远离零**：先对 `|9u|` 加 10 再整除 20，最后补回符号。例：u=10 → 90/20=4.5 → 5；u=−10 → −5；u=1 → 0.45 → 0。
- 流水线：把输入在某个上升沿被采样记为第 0 个沿，则
  - 第 3 个沿之后 `inverting_sum_q20 = −R`；
  - 第 4 个沿之后 `product_q20 = +R`。

  输入每个周期都可以变，各级同时处理不同的数据。
- `rst = 1`：所有内部寄存器和输出寄存器清零。
- 不能用除法 IP；`/ 20` 可以直接写除法运算符。
