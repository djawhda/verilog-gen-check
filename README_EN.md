# verilog-gen-check

🌐 [简体中文](README.md) | **English**

**LLM-driven Verilog generation with a five-layer static checker and closed-loop repair**

[![vcheck self-test](https://github.com/djawhda/verilog-gen-check/actions/workflows/ci.yml/badge.svg)](https://github.com/djawhda/verilog-gen-check/actions/workflows/ci.yml)

This repository provides the RTL module for the project “AI-driven End-to-end Design of a Memristor-based Booth Analog Multiplier.” It packages the workflow “write RTL from a specification → check → revise using the report” as a skill that agents such as Claude Code and Codex can invoke directly. The checking pipeline uses open-source tools, and each round's generated code, reports, and changes are saved for reproducibility and auditing.

![Verilog generation and checking pipeline](docs/pipeline.png)

## Why use it?

- LLMs write Verilog quickly, but errors such as width truncation, latches, multiple drivers, and mixed signedness can survive functional simulation. Missing resets, off-by-one errors, and incorrect operators can also escape static checks. A single checking method leaves gaps.
- Commercial lint and synthesis tools have costly licenses and may be affected by export restrictions. This repository uses four open-source tools—Icarus Verilog, Verilator, slang, and Yosys—plus custom rules, and can run on Linux or Windows.
- Reports contain structured categories, severity levels, source locations, and repair hints that can be fed directly back to the LLM.

## Five static layers + simulation

| Layer | Tool | Main checks |
|---|---|---|
| L1 syntax | `iverilog -g2012` | Syntax, undeclared signals, module and port binding |
| L2 lint | `verilator --lint-only -Wall` | Incorrect blocking/nonblocking assignments, latches, width truncation and extension, combinational loops, undriven signals |
| L3 semantic | `slang -Weverything` (pyslang) | Mixed signed/unsigned arithmetic, sign conversions, missing `default` in `case` statements |
| L4 rules | `tools/rules.py` | Multiple drivers, distinguishing mutually exclusive `generate if/else` branches; registers missing resets |
| L5 synth | `yosys proc; check` | Inferred latches, conflicting drivers, logic loops |
| sim | `iverilog + vvp` | Self-checking testbenches reporting `TB_PASS` / `TB_FAIL` and failing vectors |

Issues have four severity levels: blocker, major, minor, and info. Reports of the same issue category on the same source line are merged, with the confirming tools recorded. An end-of-line comment of the form `// vcheck-waive: CATEGORY reason` can waive an issue; all waivers are listed separately in the report. Mechanical errors—missing semicolons, misspelled signal names, and incorrect blocking/nonblocking assignments—can first be repaired deterministically by `tools/autofix.py`, reducing model calls.

## Quick start

```bash
# 1. Install tools (Ubuntu 24.04; Windows users can use OSS CAD Suite)
sudo apt install iverilog verilator yosys   # Ubuntu 24.04: Icarus 12.0, Verilator 5.020, Yosys 0.33
pip install "pyslang==12.1.0"      # Same version as CI

# 2. Self-test: the reference answers for all 10 tasks should pass
python3 tools/benchlib.py

# 3. Check your own design
python3 tools/vcheck.py my.v --top my_top --tb tb_my_top.sv --log-dir runs/my_top
python3 tools/autofix.py my.v --top my_top --tb tb_my_top.sv      # Optional: deterministic repair first
```

### Use as an agent skill

- **Claude Code**: place the entire repository in `~/.claude/skills/verilog-gen-check/` for personal use, or in `.claude/skills/verilog-gen-check/` inside your project. The agent follows the workflow in `SKILL.md`.
- **Codex and other agents**: reference `SKILL.md` in `AGENTS.md` or your prompt, and allow the agent to run `tools/vcheck.py`.

### Evaluate the LLM repair loop

`tools/llm_loop.py` supports four backends: OpenAI-compatible APIs (DeepSeek, Qwen, or local vLLM), the Anthropic API, arbitrary command-line programs (such as `codex exec`), and replay:

```bash
export DEEPSEEK_API_KEY=...
# Generation: provide only the specification, with up to 5 rounds
python3 tools/llm_loop.py --mode gen --backend openai --base-url https://api.deepseek.com/v1 \
    --model deepseek-v4-pro --api-key-env DEEPSEEK_API_KEY --rounds 5 --out results/gen_deepseek
# Repair: sample 30 mutants balanced across 7 error categories;
# run autofix first, then pass the remaining errors to the model
python3 tools/llm_loop.py --mode repair --mutants results/mutation/mutants --autofix-first \
    --ops width latch signed multidrive reset offbyone operator --per-task 3 --feedback full \
    --backend openai --base-url https://api.deepseek.com/v1 --model deepseek-v4-pro \
    --api-key-env DEEPSEEK_API_KEY --temperature 0.2 --rounds 5 --out results/repair_balanced_deepseek
python3 tools/repair_by_category.py results/repair_balanced_deepseek/summary.json \
    results/llm_eval_two_models/selection_balanced.json results/repair_balanced_deepseek/按类别.md
```

For each task and round, the workflow saves `prompt.md`, `response.md`, code, and `report.json/md`, with an overview in `summary.md`.

## Benchmark tasks

The 10 tasks come from an actual FPGA project. Each includes a specification (`spec.md`), a reference answer, a self-checking testbench, and `meta.json`:

| Task | What it exercises |
|---|---|
| `booth_encoder` | Radix-4 Booth encoding, one-hot selection |
| `booth_mul4` | Booth algorithm, sign extension, no `*` operator (256 exhaustive cases) |
| `weighted_sum` | Fixed-point rounding, pipeline latency |
| `dac_map` | 48-bit signed fixed-point arithmetic, negative gain, clamping |
| `lin_lookup` | ROM initialization (asinh-to-linear lookup table), address offsets |
| `replay_addr` | Clock-divider counting, restart on slot changes, synchronization pulses |
| `sync_fifo` / `uart_tx` / `pwm` / `debounce` | Full/empty detection, cycle-accurate timing, synchronization, debouncing |

## Evaluation results

**Mutation testing (no LLM required).** Across the 10 reference answers, 229 errors in 11 categories were injected. The checking pipeline plus testbenches detected 206 (90%): static layers detected 163, and 43 were detected only by testbenches. Verilator alone detected 55 errors that the other checks missed; custom rules alone detected 18.

![Mutation detection results](docs/mutation.png)

**Two LLMs.** Results were rechecked with the same testbenches and all five static checking layers:

| Metric | gpt-6.1-sol (Codex) | deepseek-v4-pro (API) |
|---|---|---|
| Generation: passed on the initial attempt (two groups combined) | 19/20 | 19/20 |
| Generation: passed after the repair loop with full feedback | 10/10 | 10/10 |
| Repair: fixed in round 1, on 30 samples balanced across 7 categories | 30/30 | 27/30 |
| Repair: fixed by the end of the repair loop | 30/30 | 30/30 |

![LLM evaluation results](docs/llm_eval.png)

Raw records, per-task logs, and review reports are in `results/`.

## Repository layout

```text
SKILL.md                Agent workflow
tools/                  vcheck.py  rules.py  autofix.py  mutate.py  eval_mutants.py  llm_loop.py  repair_by_category.py  benchlib.py
bench/<task>/           spec.md  <task>.v  tb.sv  meta.json
results/mutation/       Mutation evaluation results and all mutants
results/llm_eval_two_models/   Review reports and per-task JSON for both models
results/repair_balanced_deepseek-v4-pro/   DeepSeek balanced repair summary
.github/workflows/ci.yml        Reference-answer self-tests and mutation smoke tests on each commit
```

## Citation

If this repository helps your work, please cite it as follows. The original team name and project title are retained:

```text
CXW钓鱼队. 忆阻器 Booth 模拟乘法器的 AI 全流程设计：verilog-gen-check. 2026. https://github.com/djawhda/verilog-gen-check
```

## License

MIT. See [LICENSE](LICENSE).
