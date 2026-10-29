# llm_loop 结果（repair，后端 openai / deepseek-v4-pro）

题目 30；最多 5 轮；反馈方式 full；时间 2026-10-28 12:06:16

- 首轮编译通过：29/30
- 首轮静态干净（无 blocker/major）：27/30
- 首轮测试台通过：29/30
- 首轮全部通过（pass@1）：27/30
- 经过纠错循环最终通过：30/30

| 题目 | 首轮编译 | 首轮静态 | 首轮仿真 | 最终 | 轮数 | 各轮 blocker/major/minor |
|---|---|---|---|---|---|---|
| booth_encoder__005_width | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/2 |
| booth_encoder__004_latch | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| booth_encoder__007_signed | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| booth_mul4__000_latch | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| booth_mul4__009_multidrive | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| booth_mul4__013_operator | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| dac_map__020_multidrive | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| dac_map__029_reset | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| dac_map__024_offbyone | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| debounce__012_multidrive | ✗ | ✗ | ✗ | ✓ | 2 | 2/0/0 → 0/0/1 |
| debounce__017_reset | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| debounce__016_operator | ✓ | ✗ | ✓ | ✓ | 2 | 0/1/1 → 0/0/1 |
| lin_lookup__004_width | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| lin_lookup__010_multidrive | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/1 |
| lin_lookup__005_width | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/1 |
| pwm__012_width | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| pwm__016_multidrive | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| pwm__025_reset | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| replay_addr__016_latch | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| replay_addr__021_multidrive | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| replay_addr__027_reset | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| sync_fifo__019_reset | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/1 |
| sync_fifo__016_operator | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/1 |
| sync_fifo__012_multidrive | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/1 |
| uart_tx__018_offbyone | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| uart_tx__020_operator | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| uart_tx__011_width | ✓ | ✗ | ✓ | ✓ | 2 | 0/1/0 → 0/0/0 |
| weighted_sum__012_width | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/0 |
| weighted_sum__019_multidrive | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/1 |
| weighted_sum__023_operator | ✓ | ✓ | ✓ | ✓ | 1 | 0/0/1 |
