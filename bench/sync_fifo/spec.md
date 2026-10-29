# sync_fifo：同步 FIFO

## 接口

```verilog
module sync_fifo #(
    parameter integer W = 8,            // 数据位宽
    parameter integer DEPTH_LOG2 = 4    // 深度 = 2^DEPTH_LOG2
)(
    input  wire                  clk,
    input  wire                  rst,     // 同步复位，高有效
    input  wire                  wr_en,
    input  wire [W-1:0]          din,
    input  wire                  rd_en,
    output reg  [W-1:0]          dout,
    output wire                  full,
    output wire                  empty,
    output wire [DEPTH_LOG2:0]   count    // 当前存储的字数，0..2^DEPTH_LOG2
);
```

## 行为

- `full`、`empty`、`count` 是当前状态的组合输出：`empty = (count == 0)`，`full = (count == 2^DEPTH_LOG2)`。
- 每个上升沿，用沿之前的 `full`/`empty` 判断：
  - 写成功 = `wr_en && !full`：把 `din` 写到队尾。
  - 读成功 = `rd_en && !empty`：把队头的字放到 `dout`（寄存器输出，沿之后可见），并出队。读不成功时 `dout` 保持。
  - 同时读写都成功时 `count` 不变。满时同时读写：读成功、写失败；空时同时读写：写成功、读失败。
- `rst = 1`：清空 FIFO，`dout <= 0`。
- 存储用寄存器数组，深度必须是 2 的幂。
