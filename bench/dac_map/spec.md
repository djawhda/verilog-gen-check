# dac_map：定点数到 DAC 码的映射

TaOx 回放工程里，把 ROM 读出的 16 位有符号数映射成 10 位 DAC 码。

## 接口

```verilog
module dac_map #(
    parameter signed [31:0] G = 32'sd26817,      // 增益，可以为负（DA 模块反相时）
    parameter signed [47:0] O = 48'sd536870912,  // 偏置
    parameter integer       S = 20                // 右移位数，0..40
)(
    input  wire               clk,
    input  wire               rst,       // 同步复位，高有效
    input  wire               in_valid,
    input  wire signed [15:0] x,
    output reg         [9:0]  code,
    output reg                sat,       // 本次结果被钳位
    output reg                out_valid
);
```

## 行为

- 运算：`y = (x * G + O) >>> S`。全部按 **48 位有符号**运算，`>>>` 是算术右移（向负无穷取整）。题目保证 `|x*G + O| < 2^47`，不需要处理溢出。
- 钳位：`y < 0` 时 `code = 0`；`y > 1023` 时 `code = 1023`；否则 `code = y[9:0]`。发生钳位时 `sat = 1`，否则 `sat = 0`。
- 时序：寄存器输出，延迟 1 个时钟。每个上升沿：
  - `rst = 1`：`code <= 512`，`sat <= 0`，`out_valid <= 0`。
  - 否则 `out_valid <= in_valid`；`in_valid = 1` 时按上面更新 `code` 和 `sat`；`in_valid = 0` 时 `code`、`sat` 保持。
- 可综合 Verilog-2001 / SystemVerilog，不要用 `initial`。
