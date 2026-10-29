# uart_tx：UART 发送器（8N1）

## 接口

```verilog
module uart_tx #(
    parameter integer CLKS_PER_BIT = 434      // 50 MHz / 115200
)(
    input  wire       clk,
    input  wire       rst,       // 同步复位，高有效
    input  wire       start,     // 空闲时为 1 的那个上升沿开始发送
    input  wire [7:0] data,
    output reg        tx,        // 空闲为 1
    output wire       busy
);
```

## 行为

- 帧格式：1 个起始位（0）、8 个数据位（**低位先发**）、1 个停止位（1），每位持续正好 `CLKS_PER_BIT` 个时钟。
- 时序：设 `start = 1` 且空闲时的上升沿为第 0 个沿。该沿锁存 `data`，并令 `tx <= 0`（起始位开始）。第 `k·CLKS_PER_BIT` 个沿（k = 1..9）切换到第 k 位（k=1..8 为数据位 0..7，k=9 为停止位）。第 `10·CLKS_PER_BIT` 个沿起回到空闲（tx 保持 1），并且从这个沿起可以接受新的 `start`。
- `busy`：从第 0 个沿之后到第 `10·CLKS_PER_BIT` 个沿之前为 1，其余时间为 0。忙时的 `start` 被忽略。
- `rst = 1`：回到空闲，`tx <= 1`。
