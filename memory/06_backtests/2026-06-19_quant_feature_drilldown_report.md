# Quant Feature Drilldown Report

日期：2026-06-19
基线：`#203 / #194`
策略：`mainline_dragon_pullback / 0.1.21`
区间：`2025-03-26..2026-06-18`
执行：`legacy_next_open`，候选观察前 100，组合执行 BUY 前 20，最大持仓 10。

## 摘要

本报告执行 `requirements/alphaagent_quant_feature_drilldown_next_execution_plan.md` 的第一轮可验证切片：补齐候选执行归因、低吸/龙回头生命周期摘要、动态市场只读分类器，并用真实 API 抽样验证。

当前产品基线仍为 `#203/#194`，收益 `+82.99%`，最大回撤 `-15.59%`。`baseline_reason=implicit_common_start_date`，并提示存在更长起点默认参数回测；当前仍按同结束日中最常见起点选择产品基线。

## 新增只读能力

- `factor-audit` 新增 `candidate_execution_attribution`，把前 20 候选与同回测信号计划、订单、成交、固定持有后验连接起来，输出成交数、错过数、错过候选后验收益和未成交原因分布。
- `strategy-timeline` 新增 `lifecycle_segments`，把低吸蓄势簇和首个有效上拉连接，避免把低吸蓄势每天画成 BUY。
- `market_context.classify_dynamic_market_context` 新增只读动态大盘/主线分类器，可区分 `mainline_pullback`、`narrow_mainline_bull`、`choppy_rotation`、`weak_rebound`、`risk_off` 等状态，并显式返回 `not_used_for_signal_score=true`。
- `/quant` 因子审计面板新增“候选执行归因”小表，不新增按钮或主流程。

## 因子审计总览

| 审计 | 样本 | 胜率 | 平均观察收益 | 错过候选数 | 错过胜数 | 错过平均收益 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `factor_10` | 10 | 90.00% | 205.34% | 6 | 6 | 244.97% |
| `factor_20` | 20 | 65.00% | 121.03% | 6 | 6 | 244.97% |
| `factor_100` | 100 | 66.00% | 36.12% | 12 | 8 | 122.34% |
| `factor_20_exstrong` | 9 | 100.00% | 229.15% | 6 | 6 | 244.97% |
| `factor_100_exstrong` | 50 | 78.00% | 54.17% | 12 | 8 | 122.34% |

注意：这里的收益是固定持有后验，不是组合真实成交收益。错过候选收益也只是审计标签，不能参与信号日评分、排序、买卖或换仓。

## Top100 分桶

### 入场类型

| 分桶 | 样本 | 胜率 | 平均观察收益 |
| --- | ---: | ---: | ---: |
| `dragon_pullback` | 45 | 71.11% | 66.48% |
| `low_position_reclaim` | 15 | 86.67% | 25.38% |
| `unknown` | 40 | 52.50% | 5.99% |

### 低位承接类型

| 分桶 | 样本 | 胜率 | 平均观察收益 |
| --- | ---: | ---: | ---: |
| `ma_support_reclaim` | 7 | 85.71% | 5.30% |
| `platform_accumulation_launch` | 8 | 87.50% | 42.94% |
| `none` | 85 | 62.35% | 38.01% |

### 市场环境

| 分桶 | 样本 | 胜率 | 平均观察收益 |
| --- | ---: | ---: | ---: |
| `choppy_rotation` | 39 | 71.79% | 43.22% |
| `false_bull` | 11 | 100.00% | 93.00% |
| `strong_broad` | 50 | 54.00% | 18.07% |

### 低吸天数

| 分桶 | 样本 | 胜率 | 平均观察收益 |
| --- | ---: | ---: | ---: |
| `0` | 26 | 88.46% | 110.97% |
| `1-2` | 19 | 47.37% | 4.33% |
| `3-5` | 43 | 60.47% | 13.34% |
| `6-10` | 12 | 66.67% | 5.90% |

### 启动质量

| 分桶 | 样本 | 胜率 | 平均观察收益 |
| --- | ---: | ---: | ---: |
| `high_close_launch` | 6 | 83.33% | 24.74% |
| `late_pullback_launch` | 2 | 100.00% | 67.31% |
| `not_low_suction` | 45 | 71.11% | 65.94% |
| `repeated_launch` | 1 | 0.00% | -3.10% |
| `unconfirmed_buildup` | 46 | 58.70% | 7.92% |

## 候选执行归因

`factor_100` 的前 20 执行候选归因：

| 状态/原因 | 样本 | 成交 | 错过 | 后验胜率 | 后验均值 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 已成交 | 10 | 10 | 0 | 70.00% | 45.66% |
| 候选未进计划 | 9 | 0 | 9 | 77.78% | 162.45% |
| 计划未下单 | 3 | 0 | 3 | 33.33% | 2.01% |

解释：

- 当前 top20 中有 `12` 个候选没有真实成交，固定持有后验里 `8` 个为正。
- 最大问题不是“候选页没找到好票”，而是候选、理论计划、真实组合成交之间仍存在执行归因差异。
- `candidate_not_planned` 需要继续拆成理论持仓状态、历史信号缓存缺口、候选计划生成口径等原因；这一步不能直接推导为扩大持仓或强行换仓。

## 买卖问题矩阵

| 问题 | 样本 | 胜率 | 平均收益 | 卖早数 | 坏替换数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 替换交易变差 (`replacement_bad`) | 80 | 43.75% | 7.17% | 12 | 66 |
| 卖早反弹 (`sold_too_early`) | 48 | 6.25% | -6.85% | 48 | 21 |
| 买点问题 (`buy_point_bad`) | 26 | 0.00% | -7.12% | 0 | 0 |
| 趋势赢家 (`healthy_trend_winner`) | 26 | 100.00% | 29.47% | 16 | 0 |
| 卖点回撤问题 (`sell_giveback`) | 21 | 0.00% | -6.43% | 3 | 11 |
| 未归类 | 13 | 38.46% | -1.39% | 2 | 0 |

结论仍然是：亏损不是单一买点问题。`replacement_bad` 和 `sold_too_early` 样本量更大，说明卖点和释放仓位后的替换质量必须与买点一起审计。

## Support Stop 拆分

| 上下文 | 样本 | 平均收益 | 平均 MFE | 卖后反弹数 |
| --- | ---: | ---: | ---: | ---: |
| 真失败启动止损 | 49 | -7.84% | -2.63% | 0 |
| 止损后反弹 | 41 | -6.94% | 0.82% | 41 |
| 有承接但后续破支撑 | 14 | -5.36% | 4.34% | 0 |
| 浮盈回吐后破位 | 13 | -8.87% | 11.41% | 0 |
| 高浮盈后止损又反弹 | 7 | -6.30% | 12.25% | 7 |
| 其他支撑止损 | 1 | -5.78% | 5.89% | 0 |

`support_stop` 必须分上下文，不能用一个通用“早卖/不卖/回撤止盈”规则替代。

## 重点股票复核

### `603439.SSE`

`2026-05-11` 在当前 `#203` 基线下 `candidate-trace` 返回 `not_selected`：没有进入当前回测策略候选或信号计划。`strategy-timeline` 只在 `2026-06-17` 出现低吸蓄势簇，`2026-06-18` 是关键 BUY。结论：当前基线无法证明 5/11 被识别，后续需要用 `signal-history` 或重建历史候选缓存补证。

### `002384.SZSE`

`2026-04-01` 是低位承接转强 BUY，rank 3，score 97.57；`candidate-trace` 显示理论低吸洗盘信号进入低吸通道执行池第 7 名，但执行日组合满仓 10/10 且未触发换仓。`2026-06-03` 是低吸蓄势观察簇，后续 `2026-06-09` 是 BUY，`2026-06-15` 成交。结论：策略不是没识别东山精密，而是组合执行/理论持仓状态与换仓约束导致关键点没有全都成交。

### `601179.SSE`

`2026-02-02..02-04` 是经典龙回头 BUY，`2026-02-03` 成交后 `2026-02-06` support_stop。`2026-02-25` 是后续低吸/低位承接启动，low_suction_days=3，rank 48，未进入执行前 20。结论：2/3 偏早，2/25 更像用户说的低吸蓄力点，但当日排序不足。

### `600352.SSE`

`2026-03-11` 是低吸首启/重复启动 BUY，rank 1 并成交，随后 support_stop。结论：这不是“没有买入趋势”，而是买入后的启动失败；应归入买点质量/弱环境假启动审计，不应直接硬改低吸加分。

### `002240.SZSE`

`2026-03-11` 是低位承接 BUY，rank 2 并成交，后续 support_stop。结论：该样本属于“低吸确认但启动失败”，需要叠加市场未回暖、量能/收盘位置和替换质量审计，而不是简单取消低吸。

### `002443.SZSE`

`2026-05-13` 是龙回头 BUY，rank 5，`2026-05-14` 成交，`2026-06-04` support_stop。该票仍是卖点/浮盈回撤重点样本，应进入 `sell_giveback` 和 support-stop context 继续拆分。

### `002119.SZSE`

`2026-02-05` 是高分经典龙回头 BUY，rank 1 并成交，后续亏损。当前更像重复龙回头/高位风险叠加卖点亏损；此前重复龙回头硬拒实验全局失败，因此继续作为诊断桶，不直接默认硬拒。

## 动态大盘/主线画像

新增 `classify_dynamic_market_context` 后，系统可以在审计层表达：

- 科技等主线强但指数回踩时输出 `mainline_pullback`，避免把主线回踩简单等同熊市过滤。
- 资金流缺失时输出 `fund_flow_state=insufficient_data`，并在解释里标注资金流历史不足。
- 恐慌下跌、广度很弱或资金大幅流出时输出 `risk_off` 和高 `market_warning_level`。

该函数已单测证明 `not_used_for_signal_score=true`，目前只作为审计和 UI 解释，不参与默认交易规则。

## 决策

结论：

- 买点问题占比：`buy_point_bad` 26 / 214，约 12.15%。另有 `600352.SSE`、`002240.SZSE` 这类低吸确认后失败样本，需要继续按市场/量能/启动质量拆窄桶。
- 卖点/回撤问题占比：`sold_too_early` 48 / 214，`sell_giveback` 21 / 214，合计约 32.24%。
- 满仓/替换问题占比：`replacement_bad` 80 / 214；新增 top20 候选执行归因显示前 20 审计候选中仍有 12 个没成交，且 8 个固定持有后验为正。
- 低吸首个有效上拉是否优于纯蓄势：生命周期摘要已能把蓄势簇和首个有效上拉分开；但 top100 分桶仍显示 `unconfirmed_buildup` 样本多且非零胜率，不能硬过滤。
- 龙回头/低吸重叠是否增强或冲突：当前只能解释，不能直接加分。`low_position_reclaim` 后验胜率高但样本只有 15。
- 排除强势行情后 top10/top20 是否仍有效：固定持有后验仍为正，但样本明显缩小，且资金流长历史仍不足。
- 大盘/主线画像是否足以进入动态规则：暂时不足。它已能审计 `mainline_pullback` 和 `risk_off`，但还需要更长历史资金/主线覆盖。
- 当前不进入默认规则修改。下一步应继续补 `candidate_not_planned` 的细分归因、重点日期 `signal-history` 补证、全量测试和更长历史市场/主线覆盖。

## 验证

已执行：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "candidate_execution_attribution or factor_audit or strategy_timeline or lifecycle_segments" -q
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "dynamic_market_context or market_context_summary or fund_flow_marker" -q
uv run python -m compileall alphaagent/server/services/backtest/factor_audit.py alphaagent/server/services/backtest/engine.py alphaagent/server/services/quant/low_suction_quality.py alphaagent/server/services/quant/market_context.py
pnpm --dir frontend run build
docker compose up -d --build alphaagent-api
```

API 抽样：

- `GET /api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5` 返回 `#203/#194`。
- `GET /api/backtests/203/factor-audit?top_limit=100` 返回 `candidate_execution_attribution`。
- `GET /api/backtests/203/factor-audit?top_limit=100&exclude_strong_market=true` 返回 ready。
- `GET /api/backtests/203/strategy-timeline?vt_symbol=002384.SZSE` 返回 `lifecycle_segments`。
- `GET /api/backtests/203/setup-market-exit-audit?lookahead_days=10` 返回 `buy_sell_problem_matrix` 和 `support_stop_context_audit`。
- `GET /api/backtests/203/candidate-trace?...` 已抽样 `002384.SZSE`、`603439.SSE`、`601179.SSE`、`600352.SSE`、`002240.SZSE`、`002443.SZSE`、`002119.SZSE`。

剩余风险：

- `candidate_not_planned` 仍需要进一步拆成理论持仓、缓存缺口、计划生成口径等子类。
- 浏览器页面级烟测已补做，但未做逐个重点股票的截图比对。
