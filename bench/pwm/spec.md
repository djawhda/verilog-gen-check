# pwm：PWM 发生器（占空比在周期起点更新）

## 接口

```verilog
module pwm #(
    parameter integer PERIOD = 256        // 周期时钟数，2..65536
)(
    input  wire       clk,
    input  wire       rst,             // 同步复位，高有效
    input  wire [7:0] duty,            // 高电平时钟数（大于等于 PERIOD 时恒为高）
    output reg        pwm_out,
    output reg        period_start
);
```

## 行为

内部计数器 `cnt` 从 0 数到 `PERIOD-1` 再回到 0；`duty_l` 是锁存的占空比。

- `rst = 1` 的上升沿：`cnt <= 0`，`duty_l <= 0`，`pwm_out <= 0`，`period_start <= 0`。
- 复位释放后的第 1 个上升沿记为第 0 个沿。第 n 个沿之后：
  - `cnt = n mod PERIOD`；
  - 当 `cnt == 0` 时，`duty_l` 更新为该沿采到的 `duty`；其余时候保持；
  - `period_start = (cnt == 0)`；
  - `pwm_out = (cnt < duty_l)`，这里的 `cnt`、`duty_l` 都是该沿之后的新值。

即输出都是寄存器输出，并且和计数器同拍：每个周期第一个时钟 `period_start` 为 1，`pwm_out` 在新周期的第一个时钟就按新的占空比输出。
