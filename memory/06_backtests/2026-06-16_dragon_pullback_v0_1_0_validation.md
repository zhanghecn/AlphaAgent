# Dragon Pullback v0.1.0 Validation

日期：2026-06-16  
策略：`mainline_dragon_pullback / 0.1.0`  
性质：并行研究策略，旧 `mainline_leader_pullback / 0.1.1` 保留为备份/基线。

## 实现摘要

- 新增 `alphaagent/server/services/quant/strategies/dragon_pullback.py`。
- 新增策略常量和兼容 wrapper：`DRAGON_PULLBACK_STRATEGY_ID`、`score_dragon_pullback()`。
- 注册新策略 `mainline_dragon_pullback`，默认买入分 `76`。
- 新策略识别：
  - MA5/MA10/MA20 承接类型。
  - 龙回头状态：`STRONG_LEG_CONFIRMED`、`PULLBACK_OBSERVE`、`SUPPORT_ACCEPTED`、`TAIL_BUY_READY`、`DISTRIBUTION_RISK`、`INVALIDATED`。
  - MA5 下穿 MA10 弱反抽拒绝。
  - 高位爆量近跌停/长上影派发风险拒绝。
- 回测卖出对新策略使用趋势化退出，不再使用旧策略固定 `18%` 全仓止盈。
- 执行模型对新策略可使用 `support_price`/MA10/MA20 作为尾盘参考价，避免 MA10 承接形态仍被信号日 MA5 单点误杀。

## 测试

通过：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
# 178 passed, 1 warning

uv run pytest tests/alphaagent/test_factors.py -q
# 8 passed

uv run python -m compileall alphaagent/server/services/quant alphaagent/server/services/backtest
# passed
```

API 容器已重建：

```bash
docker compose up -d --build alphaagent-api
```

`GET /api/quant/strategies` 已显示 `mainline_dragon_pullback / 0.1.0`。

## 关键日期复核

| 股票 | 日期 | 旧策略 | 新策略 | 新状态 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 合肥城建 | 2025-11-03 | BUY | 拒绝 | `INVALIDATED` / `weak_rebound_ma5_below_ma10` | 修复弱反抽误买 |
| 合肥城建 | 2025-11-04 | BUY | 拒绝 | `INVALIDATED` / `weak_rebound_ma5_below_ma10` | 修复弱反抽误买 |
| 合肥城建 | 2026-05-21 | BUY | 拒绝 | `DISTRIBUTION_RISK` | 修复高位派发日误买 |
| 合肥城建 | 2026-05-08 | 非 BUY | BUY | `TAIL_BUY_READY` | 捕捉慢推后回踩弱转强 |
| 云南锗业 | 2026-04-29 | 非 BUY | 观察 | `SUPPORT_ACCEPTED` / `ma10_support` | 识别 MA10 承接，但未直接买入 |
| 云南锗业 | 2026-04-30 | 非 BUY | 观察 | `SUPPORT_ACCEPTED` / `ma10_support` | 识别 MA10 承接，但未直接买入 |
| 剑桥科技 | 2026-04-14 | 非 BUY | 观察 | `STRONG_LEG_CONFIRMED` | 识别为启动强势候选，不直接买 |
| 剑桥科技 | 2026-05-12 | BUY | BUY | `TAIL_BUY_READY` | 保留后期 MA5 回踩买点 |

## 组合回测对比

参数：

```text
start=2026-02-02
end=2026-06-13
included_boards=main
max_symbols=80
max_positions=8
candidate_limit=20
execution_model=strict_1430
tail_entry_start=14:30
tail_entry_end=14:30
```

结果：

| 策略 | 收益率 | 最大回撤 | 买入 | 卖出 | 胜率 | 买入成交来源 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `mainline_leader_pullback` | 50.00% | -7.22% | 65 | 61 | 55.7% | 33 daily proxy / 32 real 14:30 |
| `mainline_dragon_pullback` | 88.18% | -11.91% | 41 | 36 | 50.0% | 27 daily proxy / 14 real 14:30 |

结论：

- 新策略在该组合样本上收益明显提高，交易笔数更少。
- 新策略最大回撤更大，风控尚未优于旧策略。
- 两者都包含历史 `daily_close_proxy` 买入，不能当作完整严格 14:30 真实收益结论。

## 六股单股对比

参数：

```text
start=2025-10-14
end=2026-06-15
symbols=[单股]
max_positions=1
max_position_pct=1.0
execution_model=strict_1430
```

| 股票 | 旧收益 | 新收益 | 旧回撤 | 新回撤 | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| 云南锗业 | 33.13% | 10.94% | -12.24% | -26.07% | 新策略变差，主要是更早试错和趋势退出回撤更大 |
| 江海股份 | 23.71% | 150.74% | -7.01% | -13.21% | 收益显著改善，但回撤扩大 |
| 剑桥科技 | -13.19% | -13.55% | -21.82% | -27.32% | 仍未解决，买点/卖点都需继续优化 |
| 合肥城建 | -6.16% | 5.97% | -6.16% | -21.79% | 收益转正，但回撤偏大 |
| 金安国纪 | 64.72% | 211.29% | -5.76% | -15.90% | 收益显著改善，但回撤扩大 |
| 亨通光电 | 55.78% | 54.75% | -9.17% | -9.10% | 基本持平 |

## 当前结论

`mainline_dragon_pullback / 0.1.0` 已经完成第一版优化和可对比回测：

- 买点解释明显改善，能修复合肥城建弱反抽和高位派发误买。
- 能把云南锗业 2026-04-29/04-30 识别为 MA10 承接观察，但仍未直接买入，偏保守。
- 组合样本收益从 50.00% 提高到 88.18%，但最大回撤扩大到 -11.91%。
- 六股单股表现分化，说明新策略不能直接替代旧策略作为最终生产策略。

下一步应继续做：

- 补齐严格 14:30 分钟线，减少 `daily_close_proxy`。
- 对云南锗业/剑桥科技单股退化做交易归因。
- 增加分批止盈账本支持，而不是当前全仓趋势退出。
- 加强回撤控制和仓位分层，降低新策略最大回撤。

