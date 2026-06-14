# 2026-06-14 严格尾盘买入对照回测 42

## Current State

- 基准回测：`#41`，区间 `2025-10-14` 至 `2026-06-12`，主板 120 只，`strict_entry=true`，`minute_entry_required=false`。
- 严格尾盘回测：`#42`，同区间、同股票池、同入场评分，但 `minute_entry_required=true`，不允许 D+1 开盘回退。
- 当前真实 `1m` 分钟线覆盖：47,040 行，196 只股票，仅 `2026-06-11` 至 `2026-06-12` 两个交易日。
- 为验证新周期链路，从现有 `1m` 测试派生写入 `5m` 9,604 行、`10m` 4,900 行；这些派生数据只用于功能验证，不代表完整历史分钟数据。

## Result

| 回测 | 买入执行 | 总收益 | 最大回撤 | 平仓交易 | 买入成交 | 买入拒绝 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `#41` | 允许尾盘分钟，失败回退 D+1 开盘 | 56.57% | -15.01% | 146 | 153 | 0 |
| `#42` | 只允许 D+1 尾盘分钟 | -0.25% | -0.25% | 0 | 2 | 783 |
| `#43` | 严格尾盘，`minute_interval=5m` | -0.25% | 待报告页查看 | 0 | 2 | 784 |
| `#44` | 严格尾盘，`minute_interval=10m` | -0.25% | 待报告页查看 | 0 | 2 | 784 |

`#41` 买入成交中 152 笔是 `daily_next_open_fallback`，只有 1 笔是 `minute_tail_ma5`。它收益高，但不能作为严格尾盘低吸验证。

`#42` 只有 2 笔真实尾盘分钟买入，分别为：

- `600522.SSE`，`2026-06-11 14:57`，接近 `2026-06-10` 可见 MA5。
- `603986.SSE`，`2026-06-12 14:30`，接近 `2026-06-11` 可见 MA5。

`#43/#44` 与 `#42` 结果几乎一致，说明把周期从 1 分钟切到 5/10 分钟没有解决收益问题；真正瓶颈仍是 2025-10 至 2026-06 期间大多数 D+1 尾盘分钟线缺失。

## Assessment

- `#42/#43/#44` 没有证明严格尾盘策略收益更高；当前样本无法得出收益结论，因为分钟线覆盖太少，绝大多数历史候选无法验证尾盘成交。
- `#41` 的高收益主要来自 D+1 开盘回退成交；对用户提出的“早盘来不及买入”场景不够真实。
- 当前没有发现买入未来函数：信号在 D 日收盘生成，D+1 才执行；尾盘 MA5 使用信号日及以前可见日线。
- 当前卖出仍是 D 日收盘确认、D+1 开盘卖出；尚未实现尾盘卖出或盘中止损卖出。
- 下一步要评估严格尾盘收益，必须先补齐候选股票对应 D+1 的真实历史分钟线；可用 `1m/5m/10m` 固定一个周期重跑 `minute_entry_required=true`，但不能根据回测收益反复挑周期。
- 执行质量报告已增加 `strict_tail_rejected_count` 和“尾盘分钟缺口拒单”诊断；如果严格分钟回测有大量 `tail_entry_not_triggered`，报告应显示 warning，不能仅因已成交买单 100% 来自分钟尾盘而显示通过。

## Evidence

- `#41`: final equity `1,565,694.92`，total return `56.57%`，buy modes: `daily_next_open_fallback=152`、`minute_tail_ma5=1`。
- `#42`: final equity `997,472.89`，total return `-0.25%`，buy modes: `minute_tail_ma5=2`，rejected buy orders: `tail_entry_not_triggered=779`、`limit_up_or_no_bar=4`。
- `#43`: final equity `997,522.95`，total return `-0.2477%`，`minute_interval=5m`，buy modes: `minute_tail_ma5=2`，rejected buy orders: `tail_entry_not_triggered=780`、`limit_up_or_no_bar=4`。
- `#44`: final equity `997,522.95`，total return `-0.2477%`，`minute_interval=10m`，buy modes: `minute_tail_ma5=2`，rejected buy orders: `tail_entry_not_triggered=780`、`limit_up_or_no_bar=4`。
- 浏览器验证：临时前端 `http://localhost:5174/quant` 指向当前源码 API `http://127.0.0.1:18000/api`，可选择 `5m`，回测页显示“严格拒单”和“成交真实性检查”，数据页显示所选分钟周期；无 failed requests 和 console errors。
