# Low-Suction Market Risk Penalty Experiment

Date: 2026-06-19

## Purpose

用户指出 `601179.SSE`、`600352.SSE`、`002240.SZSE` 等在大盘下落阶段出现低吸/龙回头候选后胜率很低。前一轮只读路径诊断已经标记：

- `600352.SSE`：`2026-03-12`，`stealth_low_suction`，`入场环境=震荡但未回暖`，`启动诊断=启动后立即失败`。
- `002240.SZSE`：`2026-03-12`，`stealth_low_suction`，`入场环境=震荡但未回暖`，`启动诊断=启动后立即失败`。
- `601179.SSE`：`2026-02-03`，`dragon_pullback`，`early_dragon_pullback_risk=true`，更像过早经典龙回头，不是用户说的 `2026-02-24/02-25` 低吸蓄力后突破。

本实验验证一个默认关闭的排序降权开关：

- 参数：`enable_low_suction_market_risk_penalty=false` 默认关闭。
- 只对 `entry_setup=stealth_low_suction` 且 `low_suction_launch_confirmed=true` 生效。
- 当市场未回暖/弱广度/强风险与个股弱启动特征同时出现时，给排序分扣分，不硬拒买。

## Implementation Notes

- 新增 `BacktestParams.enable_low_suction_market_risk_penalty`，API、严格分钟 pipeline、strategy replay 参数 JSON 均已透传。
- 评分层新增 `low_suction_market_risk_penalty_adjustment()`，只改排序分和 evidence，不改默认策略。
- 回测缓存读取现在在默认关闭实验开启时补信号日市场上下文字段，避免旧 `quant_stock_signals.evidence` 缺 `dynamic_market_regime/recovery_state` 时实验失效。
- 基础性能修复：`_load_score_cache_from_persisted_signals()` 不再依赖 `params.persist`。临时 `persist=false` 回测也能复用已落库候选缓存。
- 缓存真实性修复：如果某个 run 只有稀疏 `quant_stock_signals` 行（例如 2025-08 早期每天 1-8 条），回测不再把它当完整候选池，而是回退重算，避免用不完整缓存得出假收益。

## Focused Window Result

窗口：`2025-10-09` 至 `2026-03-31`，main board，`max_positions=10`，执行 BUY 前 `20`，`min_entry_score=76`，`legacy_next_open`。

HTTP API 对比：

| Run | Return | Max Drawdown | Profit Factor | Buys / Sells | Trade Count | Conclusion |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| Baseline | `+5.26%` | `-18.27%` | `0.9215` | `147 / 137` | `284` | 弱市场窗口基线本身很差，确认用户指出的大盘下落阶段胜率问题。 |
| Experiment | `+4.56%` | `-22.70%` | `0.9383` | `151 / 141` | `292` | 降权没有改善，最大回撤显著恶化。 |

容器内直接调用 `run_backtest()` 复查同窗口得到同方向结果：

| Run | Return | Max Drawdown | Profit Factor | Buys / Sells | Trade Count |
| --- | ---: | ---: | ---: | --- | ---: |
| Baseline | `+5.64%` | `-19.15%` | `0.9544` | `146 / 136` | `282` |
| Experiment | `-3.92%` | `-23.10%` | `0.8062` | `139 / 129` | `268` |

两种口径数值略有差异来自请求期间缓存/回放路径和是否包含全部返回字段，但方向一致：实验更差。

## Focused Stock Check

同窗口容器内回测显示：

- `601179.SSE`
  - Baseline：`2026-02-03` BUY，`2026-02-06` `support_stop` SELL，亏损约 `-12,088`。
  - Experiment：仍然买入同一笔并同样 `support_stop`，没有被降权避开。
- `600352.SSE`
  - Baseline：`2026-03-12` BUY，`2026-03-16` `support_stop` SELL，亏损约 `-10,663`。
  - Experiment：仍然买入同一笔并同样 `support_stop`，没有被降权避开。
- `002240.SZSE`
  - Baseline：`2026-03-12` BUY，`2026-03-19` `support_stop` SELL，亏损约 `-12,054`。
  - Experiment：推迟到 `2026-03-16` BUY，`2026-03-18` `support_stop` SELL，亏损约 `-4,493`；单票亏损减小，但全局替换交易更差。

买点差异：

- Baseline-only BUY：`47` 个。
- Experiment-only BUY：`40` 个。
- 实验没有显著清除目标失败样本，反而改变排序后买入了一批更差替代票。

## Cache Coverage Note

本地 `quant_signal_runs` 覆盖 `2025-03-26..2026-06-18`，但 `quant_stock_signals` 在 `2025-08-06..2025-09-12` 只有稀疏行：

- `2025-08-06` 至 `2025-09-12` 多数日期只有 `1..45` 条。
- 从 `2025-09-15` 起候选缓存才达到 `>=50` 条，`2025-10-09` 后约 `2469` 条/日。

因此，完整 `2025-03-26..2026-06-18` 快速回测如果强行复用早期旧缓存会失真。当前代码已拒绝稀疏缓存并按日期混合缓存/重算：完整缓存日期继续复用，缺失或稀疏日期不进入 `score_cache`，由仿真阶段现场评分。这会让早期全量实验只重算缺口日期，而不是整段重算。

## Complete-Cache Long Window Recheck

修复按日期混合缓存后，重新跑 `2025-09-15..2026-06-18`。该区间避开了 2025-08 至 2025-09 上旬稀疏候选缓存。

| Run | Return | Max Drawdown | Profit Factor | Sharpe | Buys / Sells | Elapsed | Conclusion |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| Baseline | `+29.48%` | `-22.48%` | `1.1549` | `1.1746` | `220 / 210` | `57.20s` | 长区间基线可返回，混合缓存路径可用。 |
| Experiment | `+29.23%` | `-22.61%` | `1.1428` | `1.1518` | `215 / 205` | `69.53s` | 实验仍略弱，继续支持拒绝默认开启。 |

该长区间不是当前产品基线，因为当前产品基线仍是 `#203/#194` 的 `2025-03-26..2026-06-18` 全范围；这里仅用于验证完整缓存区间下实验方向是否改善。结果仍未改善。

## Decision

拒绝默认开启 `enable_low_suction_market_risk_penalty`。

原因：

- 只做低吸市场风险排序降权不能避开关键失败样本 `601179.SSE`、`600352.SSE`。
- 它会改变组合排序和替换交易，弱市场窗口收益下降、最大回撤恶化。
- 这说明“低吸确认 + 大盘未回暖”不能直接转成排序扣分；需要更窄的上下文模型，或者保留为候选风险标记。

保留的有效修复：

- 临时回测 `persist=false` 也复用完整候选缓存，减少重复计算。
- 稀疏旧候选缓存不再被当作完整候选池，避免收益对比失真。

## Next Work

- 不继续调参让该实验变好看，避免过拟合。
- 把 `低吸确认但大盘未回暖/启动失败` 保留为候选和路径诊断风险提示。
- 下一轮应研究“买点是否真的出现第一个有效上拉”，而不是简单看低吸天数或市场标签：
  - `stealth_low_suction` 中，低吸蓄势只作为观察加分；
  - 只有首个有效上拉、放量承接、收盘位置和市场/主线未崩同时满足时，才考虑可执行买点；
  - 对于大盘下落阶段，优先做只读标记或默认关闭实验，必须同时检查替换交易质量。
- 补齐/重建 `2025-03-26..2025-09-12` 的完整候选缓存后，再跑全区间对比。
