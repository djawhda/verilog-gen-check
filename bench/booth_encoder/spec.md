# booth_encoder：radix-4 Booth 编码器（选通信号）

Booth 乘法器 FPGA 模型里的编码模块：把乘数的 3 位窗口编码成五选一的选通信号。

## 接口

```verilog
module booth_encoder(
    input  wire [2:0]        bits_in,             // {b2, b1, b0}
    input  wire              window_valid,
    output wire [4:0]        gates,               // 独热码 {n2, p2, n1, p1, zero}
    output wire [4:0]        complementary_gates, // 等于 ~gates
    output reg  signed [2:0] digit,               // Booth 数字 -2..+2
    output reg  [2:0]        address              // 0:zero 1:p1 2:n1 3:p2 4:n2
);
```

## 行为（纯组合逻辑）

radix-4 Booth 数字：`digit = -2*b2 + b1 + b0`，即

| bits_in | 000 | 001 | 010 | 011 | 100 | 101 | 110 | 111 |
|---|---|---|---|---|---|---|---|---|
| digit | 0 | +1 | +1 | +2 | −2 | −1 | −1 | 0 |

- `window_valid = 1`：`gates` 是对应的独热码：digit=0 → `5'b00001`（zero），+1 → `5'b00010`（p1），−1 → `5'b00100`（n1），+2 → `5'b01000`（p2），−2 → `5'b10000`（n2）。
- `window_valid = 0`：`gates = 5'b00001`，`digit = 0`，`address = 0`。
- `complementary_gates = ~gates`。
- `digit`、`address` 由 `gates` 决定：zero→(0,0)，p1→(+1,1)，n1→(−1,2)，p2→(+2,3)，n2→(−2,4)。
- 不能产生锁存器。
