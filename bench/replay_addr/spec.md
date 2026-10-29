# replay_addr：回放 ROM 地址发生器

TaOx 回放工程里，按拨码开关选的槽位，以各槽位自己的分频系数逐点扫 ROM。ROM 地址 = `{slot[2:0], idx[11:0]}`。

## 接口

```verilog
module replay_addr #(
    parameter integer N    = 4096,   // 每周期点数，2..4096
    parameter integer DIV0 = 342, DIV1 = 171, DIV2 = 342, DIV3 = 415,
    parameter integer DIV4 = 323, DIV5 = 348, DIV6 = 3418, DIV7 = 439   // 各槽位分频，2..65535
)(
    input  wire        clk,
    input  wire        rst,          // 同步复位，高有效
    input  wire [2:0]  slot,         // 已同步到 clk 的槽位选择
    output reg  [14:0] addr,         // {cur_slot, idx}
    output reg         tick,         // addr 更新到下一个点的那个周期为 1
    output reg         sync          // idx 从 N-1 回到 0 的那个周期为 1（接示波器外触发）
);
```

## 行为（每个时钟上升沿）

内部寄存器：`cur_slot[2:0]`、分频计数 `div_cnt[15:0]`、点号 `idx[11:0]`。`DIV(s)` 表示槽位 s 的分频参数。

1. `rst = 1`：`cur_slot <= slot`，`div_cnt <= 0`，`idx <= 0`，`addr <= {slot, 12'd0}`，`tick <= 0`，`sync <= 0`。
2. 否则若 `slot != cur_slot`（换槽位）：`cur_slot <= slot`，`div_cnt <= 0`，`idx <= 0`，`addr <= {slot, 12'd0}`，`tick <= 0`，`sync <= 0`。
3. 否则若 `div_cnt == DIV(cur_slot) - 1`：`div_cnt <= 0`；`idx` 前进一点（`idx == N-1` 时回到 0，否则加 1）；`addr <= {cur_slot, 新的 idx}`；`tick <= 1`；`sync <= (idx == N-1)`。
4. 否则：`div_cnt <= div_cnt + 1`，`tick <= 0`，`sync <= 0`，`addr`、`idx` 保持。

所以同一槽位内，每 `DIV(cur_slot)` 个时钟 `addr` 前进一次，`tick` 恰好在 `addr` 变成新值的那个周期为 1。
