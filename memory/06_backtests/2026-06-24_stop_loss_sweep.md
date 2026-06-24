# Stop Loss Sweep + CPCV 验证（support_stop 止损优化）

## Current state

第二阶段：针对胜率 32% 的真凶 support_stop（125 笔亏 -88 万，55% 止损后5日回升=误杀），
扫描 `stop_loss_pct` 并 CPCV 验证。

- 扫描：`stop_loss_pct ∈ {0.07, 0.08, 0.09, 0.10, 0.12}`，全区间 5000 股，2025-03-26..2026-06-18。
- CPCV 验证：stop_0.07 vs stop_0.08，n_groups=3，max_symbols=5000，max_position_pct=0.1（对齐 #194）。

## 结果

### 扫描（当前数据，全样本）

| stop | return | win | maxdd | sharpe | pf | support_stop |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0.07 | 48.4% | 30.9% | -21.4% | 1.63 | 1.29 | 111笔/-80万 |
| **0.08** | **65.0%** | 31.7% | -21.2% | **2.08** | **1.45** | 108笔/-75万 |
| 0.09 | 64.2% | 31.7% | -21.3% | 2.06 | 1.44 | 108笔 |
| 0.10 | 64.2% | 31.7% | -21.3% | 2.06 | 1.44 | 108笔 |
| 0.12 | 64.2% | 31.7% | -21.3% | 2.06 | 1.44 | 107笔 |

- **stop=0.08 是甜蜜点**：return +16.6pp、sharpe +0.45、pf +0.16，maxdd 不恶化。
- **0.09+ 完全平台**（再放宽无用，support×0.965 接管）。
- support_stop 只减 3 笔（111→108），收益提升主要来自"扛过 -7% 误杀后回升"的交易，印证 55% 误杀分析。

### CPCV 验证（stop_0.07 vs stop_0.08）

| 指标 | 值 | 解读 |
| --- | --- | --- |
| **PBO** | **0.333** | ✅ < 0.5，样本外稳健（对比 loose PBO 1.0 过拟合） |
| OOS 排名分布 | {0:1, 1:2} | IS 最优 → OOS 2/3 路径仍最好 |
| Deflated Sharpe | 0.697 | ⚠️ < 0.95，优势不算强 |
| OOS 年化 Sharpe | 0.961 | 偏低（path1 拖累） |

路径明细：path0 IS 最优 0.08→OOS 输 0.07；path1 IS 最优 0.08→OOS 赢；path2 IS 最优 0.07→OOS 赢。

## 结论

- **stop=0.08 通过 CPCV 验证**（PBO 0.333 < 0.5），**不是过拟合**，是真实净正向改进。
- 满足 plan 落地条件：return↑ + win↑ + maxdd 可控 + PBO<0.5。
- **caveats**：胜率仅升 0.8pp（30.9%→31.7%，提升在收益端不在胜率端）；DSR 0.697<0.95 优势不强；3 路径样本少。
- **对比第一阶段**：放宽进场门控（loose）PBO=1.0 严重过拟合被否；放宽止损（0.08）PBO=0.333 稳健通过。同为"放宽"，进场端放宽=过拟合，止损端放宽=合理（因为 55% 是误杀）。

## How to verify / reproduce

```bash
# 扫描（api 容器内，~50 分钟）
docker cp scripts/stop_loss_sweep.py vnpy-alphaagent-api-1:/app/scripts/stop_loss_sweep.py
docker exec vnpy-alphaagent-api-1 python scripts/stop_loss_sweep.py
# CPCV 验证（~78 分钟）
docker cp alphaagent/server/services/backtest/overfit_validation.py vnpy-alphaagent-api-1:/app/alphaagent/server/services/backtest/overfit_validation.py
docker cp scripts/stop_cpcv.py vnpy-alphaagent-api-1:/app/scripts/stop_cpcv.py
docker exec vnpy-alphaagent-api-1 python scripts/stop_cpcv.py
```

诊断脚本：`scripts/stop_loss_sweep.py`、`scripts/stop_cpcv.py`（一次性，不入正式包）。

## 落地状态（已实施 2026-06-24）

主人确认"改默认 + 补测试"。**走量化页 API 测试时发现关键遗漏**：只改 `schemas.py` 默认不够，API/服务层有 **5 处独立的 `stop_loss_pct` hardcode 0.07**，必须全部同步否则量化页/候选/回放路径仍用 0.07：

1. `alphaagent/server/services/backtest/schemas.py:25`（BacktestParams 默认）
2. `alphaagent/server/api/backtests.py:673`（`_params_from_payload`——量化页 POST 回测入口，**最关键**，不传 stop_loss_pct 时用这里）
3. `alphaagent/server/services/quant/screening_payloads.py:465`（`default_risk_control`——候选 trade_plan 显示的止损位）
4. `alphaagent/server/services/quant/strategy_replay.py:37`（`run_replay`——个股策略回放）
5. `alphaagent/server/services/backtest/engine.py:4087`（`raw_params` 解析——backtest 还原）

全部 0.07→0.08 + 补单测 `test_dragon_pullback_default_stop_loss_0p08_survives_seven_pct_drawdown`（pass）。全量回归 **502 passed**，4 个预存 fail（文案）与本改动无关。

**容器生效方式**：镜像重建因 `download.docker.com` 网络失败（apt-get docker-ce-cli SSL reset），临时用 `docker cp` 5 文件进 `vnpy-alphaagent-api-1` + `docker compose restart alphaagent-api` 让 0.08 在容器生效。**正式重建待网络恢复**（否则容器一旦 `up --build` 成功会回退镜像里的 0.07）。

## Open risks / next work

- **数据漂移**：当前数据 stop=0.07 跑出 return 48%（#194 是 83%），因 06-19 后数据同步调整了历史 K线/评分辅助数据。绝对值不可比 #194，但 0.07 vs 0.08 相对比较有效。
- **DSR 0.697 偏弱**：0.08 优势真实但不强，建议落地后持续观察实盘/更大样本（n_groups=6 复核）。
- **胜率端提升有限**：0.08 主要提收益（扛过误杀），胜率仍 31.7%。若要提胜率，下一步看 `fragile_structure_stop`（8 笔）或进场质量。
- **support×0.965 仍未参数化**：0.09+ 平台说明 0.965 接管，若后续要再优化可参数化该系数（`simulation.py:2083`）。
- **踩坑**：扫描自检未复现 #194（数据漂移），基准改为"当前数据 0.07"；TaskStop 会在容器留 python 残留进程，需 `/proc` 手动清理。
