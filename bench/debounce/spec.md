# debounce：按键/拨码开关同步与消抖

开发板上用拨码开关切换回放波形，开关信号需要先同步到时钟域再消抖。

## 接口

```verilog
module debounce #(
    parameter integer N = 4            // 连续 N 个时钟稳定才认为变化，2..1048576
)(
    input  wire clk,
    input  wire rst,                   // 同步复位，高有效
    input  wire din,                   // 异步输入
    output reg  dout,                  // 消抖后的电平
    output reg  rise,                  // dout 从 0 变 1 的那个周期为 1
    output reg  fall                   // dout 从 1 变 0 的那个周期为 1
);
```

## 行为（每个上升沿，右边都用沿之前的值）

内部寄存器：两级同步 `s1`、`s2`，计数器 `cnt`（位宽要能放下 N-1）。

```
if (rst)  s1, s2, dout, cnt, rise, fall 全部清 0
else:
    s1 <= din;  s2 <= s1;
    rise <= 0;  fall <= 0;
    if (s2 == dout)          cnt <= 0;
    else if (cnt == N-1)     begin dout <= s2; cnt <= 0; rise <= s2; fall <= ~s2; end
    else                     cnt <= cnt + 1;
```

也就是：同步后的信号 `s2` 必须连续 N 个沿都和 `dout` 不同，`dout` 才翻转，翻转的同一拍输出一个时钟宽的 `rise` 或 `fall`。
