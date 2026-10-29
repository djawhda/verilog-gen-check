# lin_lookup：asinh 电流码转线性电流（查找表）

TaOx 回放工程里，电流 ROM 存的是 asinh 压缩码 `c = round(asinh(I/1nA)·2048)`（16 位有符号）。线性显示时用 4096 项查找表还原电流。

## 接口

```verilog
module lin_lookup #(
    parameter LUT_FILE = "lut_asinh_to_linear.mem"   // $readmemh 格式，4096 行，每行 4 位十六进制
)(
    input  wire               clk,
    input  wire signed [15:0] c,
    output reg  signed [15:0] i_lin      // LSB = 0.1 uA
);
```

## 行为

- 查找表：`reg [15:0] lut [0:4095]`，用 `$readmemh(LUT_FILE, lut)` 初始化（这是 FPGA 上 ROM 初始化的标准写法，允许放在 `initial` 里）。
- 地址：`idx = (c + 32768) >> 4`，结果是 0…4095 的 12 位无符号数。注意 `c + 32768` 必须用足够的位宽计算，不能在 16 位里溢出。
- 时序：同步读，延迟 1 个时钟：每个上升沿 `i_lin <= lut[idx]`。没有复位。
- 可综合（Vivado 会推断成块 RAM）。
