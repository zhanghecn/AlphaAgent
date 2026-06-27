# trend_acceleration Exit 参数优化验证（trailing/take_profit/信号门控）

## Current state

第三阶段：验证 trend_acceleration 的 exit 参数 + 信号门控优化。**结论：所有参数级优化
过拟合或无效，均不落地。trend 需要 STRUCTURAL 改进，单参数无解。**

测试方向（覆盖主人列的三方向）：
- trailing（让趋势奔跑）：全样本赢家 0.10，**CPCV PBO=0.667 过拟合，不落地**
- take_profit：组合验证证明保持 0.18 最优（放宽冲突暴跌）
- 信号过滤-砍假加速（return_5d 门控收紧）：非单调无效，stop_loss 笔数不减
- 加因子（成交量）：trend 已有 volume_ratio（1.05~2.80），边际收益小

## 根因

trend 走 **generic evaluate_exit**（`factors.py:434`，固定 stop_loss/take_profit/trailing/time_stop
阈值），**不用**龙回头的精细 sell（`dragon_pullback_sell_reason`，`simulation.py:2061`——只在
`strategy==DRAGON_PULLBACK` 时走）。stop_loss -84万（追高假加速）是结构性问题，单参数无法解决。

baseline（tp=0.18/tr=0.08/sl=0.08）：return 47.9%, win 41.0%, sharpe 1.17。reason 分布：
- take_profit 67笔/**+152万**（趋势真买点，全胜 avg +22699）
- trailing_stop 198笔/-34万（假突破高点回撤 8%）
- stop_loss 60笔/**-81万**（追高假加速，全亏 avg -13501）

## 结果

### trailing 扫描（take_profit 固定 0.18）
| trailing | return | sharpe | pf | stop_loss |
| ---: | ---: | ---: | ---: | --- |
| 0.08(基线) | 47.9% | 1.17 | 1.25 | 60笔/-81万 |
| **0.10** | **64.7%** | **1.56** | **1.47** | 73笔/-84万 |
| 0.12 | 58.9% | 1.42 | 1.41 | 81笔/-88万 |
| 0.15 | 49.1% | 1.26 | 1.39 | 77笔/-90万 |
| 0.20 | 62.3% | 1.51 | 1.45 | 97笔/-109万 |

**非单调窄峰**（0.10峰，0.12/0.15回落，0.20又升）→ 过拟合信号。stop_loss 始终 -81~-109万纹丝不动。

### 组合验证（trailing × take_profit）
take_profit 放宽全部暴跌：tp=0.25/tr=0.10 return **27.2%**（maxdd -25.7%）。**take_profit 0.18
必须保持**——trend 趋势股 +18% 后易回调，0.18 锁利是对的，推迟止盈让利润回吐到 trailing。

### CPCV（tr_0.08 vs tr_0.10）
| 指标 | 值 | 解读 |
| --- | --- | --- |
| **PBO** | **0.667** | ❌ >0.5 过拟合 |
| Deflated Sharpe | 0.771 | ⚠️ <0.95 不显著 |
| path0 | IS最优tr_0.10→OOS None(最差) | ❌ |
| path1 | →OOS 0.151(赢) | ✓ |
| path2 | →OOS 2.745(最差) | ❌ |

对比：stop_loss 0.08 CPCV **PBO=0.333 ✅**（机制=扛过55%误杀，大样本稳健）；
trailing 0.10 **PBO=0.667 ❌**（窄峰无机制支撑）。同为"放宽"，止损端放宽稳健，trailing 端放宽过拟合。

### A' 信号门控（return_5d 上限收紧，exit 固定 tr=0.10/tp=0.18）
| r5d上限 | return | sharpe | stop_loss |
| ---: | ---: | ---: | --- |
| 18(基线) | 64.7% | 1.56 | 73笔/-84万 |
| 16 | 47.9% | 1.23 | 72笔/-79万 |
| 14 | 65.0% | 1.57 | 64笔/-74万 |
| 12 | 32.4% | 0.93 | 74笔/-84万 |

**非单调无效**，stop_loss 笔数不减（73/72/64/74）。**return_5d 不是追高假加速的可靠特征**。

## 结构性 sell 改造（trend_acceleration_sell_reason，v1/v2）

写 trend 专用 sell（ma20 支撑止损/profit_protection/ma10 trailing），改 simulation.py 加 trend
分支。`position.reason = SignalScore.evidence`（trend 有 ma10/ma20/max_drawdown_60d，无 support_price）。

| 版本 | return | sharpe | maxdd | take_profit | stop_loss |
| ---: | ---: | ---: | ---: | --- | --- |
| baseline(generic evaluate_exit) | 47.9% | 1.17 | -21.6% | 67笔/+152万 | 60笔/-81万 |
| v1(保守: ma10 trailing gain>5% + 保守 profit_protection) | 46.8% | 1.24 | -19.0% | 62笔/+156万 | 91笔/-108万 |
| v2(激进: ma10 trailing gain>0 + 早 profit_protection high_gain≥10%) | **28.9%** | 0.85 | -18.4% | 56笔/+125万 | 90笔/-94万 |

**结论：exit 结构性改造调不了 return**。v1 return 持平（风险微改善 sharpe+0.07/maxdd+2.6pp），
v2 暴跌（早 profit_protection 砍 take_profit -31万）。根因：trend return 由进场质量决定
（take_profit 真趋势 +156万 vs stop_loss 追高 -108万），exit 改造只能调风险。
**已 `git checkout` 回退 simulation.py + 容器 cp 同步，不落地。**

## 真正的解：latest_change_pct > 0 门控（数据驱动突破，2026-06-25）

逐笔分析 stop_loss(追高) vs take_profit(真趋势) 的进场特征（`scripts/trend_entry_analysis.py`，
FIFO 配对 BUY raw(evidence) → SELL outcome），发现最强区分信号：

| feature | take_profit(median) | stop_loss(median) | 区分度 |
| --- | --- | --- | --- |
| **latest_change_pct** | **+1.39** | **-0.87** | 🔥 极强 |
| return_5d | 8.84 | 10.07 | 弱（A' 无效印证）|
| max_drawdown_60d | -14.24 | -16.38 | 中 |
| acceleration_score | 100 | 100 | 无（全满）|

**根因**：stop_loss 追高假加速进场**当日是跌的**（median -0.87），属"前几天涨过、当日回调中追入"；
真趋势进场当日涨（median +1.39），趋势在加速。当前门控只防涨停（`change_pct <= 8.5`），不要求当日涨，
放进了当日下跌的假加速。**A' 收紧 return_5d 找错特征**（stop_loss 的 return_5d 只略高 10.07 vs 8.84）。

**门控 `latest_change_pct > 0`**（要求进场当日涨）效果（exit=baseline tr0.08/tp0.18）：
| 指标 | baseline | >0 门控 | 变化 |
| --- | --- | --- | --- |
| return | 47.9% | **61.6%** | **+13.7pp** |
| sharpe | 1.17 | **1.50** | +0.33 |
| maxdd | -21.6% | **-18.1%** | +3.5pp |
| stop_loss | 60笔/-81万 | **50笔/-57万** | **-24万** |
| take_profit | 67笔/+152万 | 71笔/+158万 | +6万 |

**分时段稳健性**（Q2/Q3 都赢，**非窄峰过拟合**，区别于 trailing 0.10 的 PBO=0.667）：
| 段 | gated return | orig return | gated sl | orig sl |
| --- | --- | --- | --- | --- |
| Q1(2025-03~08) | 无信号(buy=1) | 无信号 | - | - |
| Q2(2025-09~2026-01) | 6.1% | -1.2% | 29/-26万 | 25/-28万 |
| Q3(2026-02~06) | 58.1% | 48.6% | 21/-29万 | 29/-48万 |

机制支撑：trend="趋势加速"，加速应在当日涨；当日跌的"加速"是假加速（回调中追入）。这是结构性门控，
非任意窄峰拟合。

## 落地状态（已实施 2026-06-25，主人确认）

改 `trend_acceleration.py` entry_signal：`latest.change_pct <= 8.5` → `0 < latest.change_pct <= 8.5`。
- 补 2 单测（`test_quant_backtest_portfolio.py`）：`test_trend_acceleration_rejects_non_positive_change_pct`
  （门控拦截 change_pct=0）+ `test_trend_acceleration_does_not_use_future_bars`（无未来函数：传入未来 bar 信号不变，
  验证 `visible_bars` 的 `<= trade_date` 过滤）。3 测试全过。
- **无未来函数**：`latest.change_pct` 是信号日（`visible_bars[-1]`，`<= trade_date`）当天收盘涨跌，信号日收盘后已知，
  `legacy_next_open` 次日开盘买入。单测显式验证未来 bar 不影响信号。
- 容器全样本确认 return **61.6%**（与扫描一致），stop_loss 50笔/-57万。
- 回归 **504 passed**，4 预存 fail（dragon_pullback/candidate_trace 文案）与本改动无关（git stash 验证）。
- 容器生效：`docker cp` trend_acceleration.py 进 `vnpy-alphaagent-api-1`（镜像重建待网络恢复，同 stop_loss 0.08）。

## 结论

- **B（trailing 0.10）+ A'（return_5d 门控）+ 结构性 sell 均不落地**：CPCV 过拟合 / 无效 / return持平。
- **但 latest_change_pct > 0 门控有效**（数据驱动 + 分时段稳健），是真正的优化方向，待落地。
- **trend 参数优化空间已尽**——CPCV 证明 exit 参数（trailing/take_profit）和单一门控都在过拟合窄峰区。
- stop_loss -84万 追高假加速 + trailing -34万 假突破是**结构性问题**，单参数无解。
- **take_profit +152万（全胜）证明 trend 买点判断对**，问题在 exit 管理（generic evaluate_exit 太粗）。

## 下一步方向（return 提升只能靠进场端，需数据驱动 + 主人确认）

exit 改造（trailing/结构性 sell）已证天花板=风险改善，return 调不动。trend return 瓶颈是
**进场质量**（stop_loss 91笔追高假加速 -108万）。提升 return 必须过滤追高进场：

1. **数据驱动分析 stop_loss 单的 entry 特征**：A' 的 return_5d 盲调无效（非单调），要找真实特征。
   hook score_trend_acceleration 记录每个 entry 的指标，标记哪些后来 stop_loss，找真正的追高信号
  （可能是不在回踩位置/未洗盘/特定 sector/量价背离等）。这是 A' 的正确做法（数据驱动，非盲调）。
2. **加回踩结构因子**：真正的回踩结构（缩量+均线承接+弱转强），即龙回头 low_suction 核心移植。
   成本高，偏离 trend"趋势加速"定位，且 trend 是内部策略（不在 `PUBLIC_STRATEGY_IDS`）。
3. **接受 trend 作为辅助策略**：take_profit +156万 证明买点对，exit 粗糙但能赚。优先级低于龙回头主线。

## How to verify

```bash
# trailing/take_profit 扫描（容器内，~25 分钟）
docker exec vnpy-alphaagent-api-1 python /app/trend_exit_sweep.py --phase all
# 组合验证（~17 分钟）
docker exec vnpy-alphaagent-api-1 python /app/trend_combo.py
# CPCV（~22 分钟，trend 信号少比龙回头快）
docker exec vnpy-alphaagent-api-1 python /app/trend_cpcv.py
# A' 门控扫描（sed 覆盖容器 trend_acceleration.py，测完自动 cp 原版恢复）
#   bash 循环 r5d∈{18,16,14,12}，调 scripts/trend_signal_one.py
```

诊断脚本（一次性，不入正式包）：`scripts/trend_exit_sweep.py`, `trend_combo.py`,
`trend_cpcv.py`, `trend_signal_one.py`。结果落盘容器 `/tmp/trend_*.json`。

## Open risks / next work

- trend 是内部策略（不在 `PUBLIC_STRATEGY_IDS`），当前只龙回头暴露给前端。trend 优化优先级低于龙回头。
- 结构性改进（复用龙回头 sell）要谨慎：dragon_pullback_sell_reason 依赖 position.reason 里的
  ma10/ma20/support_price/max_drawdown_60d 等 entry context，trend 的 score 函数需补存这些。
- 主线 trend_acceleration.py / schemas.py **未改**（A' 用 sed 临时覆盖容器，已恢复）。
- 落地决策待主人：是否值得为 trend 做结构性 sell 改造，还是接受 trend 作为辅助策略。
