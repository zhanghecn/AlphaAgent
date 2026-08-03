# 涨停记忆 × 竞价缺口 打板回测 v1（盘前股性池 + 竞价确认 + T+1）

> 上游裁决：`memory/06_backtests/limit_up_leader_first_board_fused_score_v2_20260803.md`
> （L7_recent_touch lift 2.51/召回 50%）+ `limit_up_leader_first_board_structure_20260802.md`
> ⑮（竞价梯度 14 个月单调）。本文件是第一版可交易模拟的计划。

## Context（为什么做）

三轮结构研究的落地结论：D-1 通用层唯一过滤级条件 = **近 20 个市场日有过 zt/zbgc 触碰**
（涨停记忆/股性）；D 日执行层 = **竞价缺口**（1-4% 为可交易区间，≥4% 追高、≥9.5% 一字
买不进）。主人指示「先做一版」打板模拟看效果。

## 模型（全部信息在买入时可见，无未来函数）

- **池（D-1 收盘可观测）**：主板合格票（`is_eligible_main_board`）+ D-1 未涨停
  （`_is_first_board_candidate` 口径）+ 近 20 个市场日有过 zt/zbgc 触碰。
- **确认（D 日竞价可观测）**：竞价缺口 `open(D)/close(D-1)-1`。
- **买入**：D 日开盘价。**卖出**：T+1 = D+1 开盘价（主口径；A 股 T+1 当日不可卖）。
  另报 D 日 open→close 盘中口径（仅信息，不可执行）。
- **成本（预声明）**：双边 0.2%（佣金万 2.5×2 + 印花税千 0.5 + 滑点≈0.1%）。

## 对照臂（单变量隔离，预声明）

| 臂 | 条件 | 回答的问题 |
|---|---|---|
| A 仅竞价 | 全市场 gap∈[1%,4%) | 竞价梯度本身赚不赚钱 |
| B 组合 | 涨停记忆 + gap∈[1%,4%) | **本模型** |
| C 记忆无确认 | 涨停记忆 + gap<1%（含低开） | 不要竞价确认行不行 |
| D 追高 | 涨停记忆 + gap∈[4%,9.5%) | 追更高缺口值不值 |

另报：B 臂按缺口细分桶（1-2%/2-4%）+ 全部记忆票六桶梯度复核；B 臂逐月胜率/均值
（一致性纪律）；结局标签（当日触板率/封板率/首板后≥2板占比）仅作分组统计。

## 口径与边界

- 窗口 2025-06-27..2026-07-31；事件前向加载 45 自然日（覆盖 20 市场日记忆回溯删失），
  日线 end+10 自然日（让窗口末尾的交易能 T+1 出场）。
- D+1 为该票下一根日线（停牌则顺延，收益如实计）；D+1 开盘价缺失 → 该笔剔除并计数。
- ≥2 板占比的分母限「D 日恰为首板」的交易（`extract_first_board_samples` wave 口径），
  窗口末端峰值有右删失，只作参考。
- 不做仓位管理/复利（v2 再说）：报逐笔胜率/均值/分位数/月度，容量（日均笔数）单列。
- 只读研究：不写任何数据库表。

## v2 卖出规则（主人 2026-08-03 定稿，与 v1 同报告双口径并列）

v1 结果全臂亏损（B 臂均净 -0.33%、毛 -0.13%），诊断=卖出规则一刀切砍掉了连板利润。
主人定稿 v2 卖出规则：

- 持有期每日判定：**涨停（收盘≥前收×1.098）→ 以收盘价卖出当前仓位一半**；
  **未涨停 → 以收盘价卖出全部剩余**。T+1 买入当天不可卖，从次日走起。
- 数据耗尽/达 20 日持有上限 → 最后可得收盘价强制清仓（exit_reason 标记删失）。
- 报告同表并列 v1/v2 双口径 + B 臂卖出原因分布 + v2 逐月一致性。

## 文件清单

- 新建 `alphaagent/server/services/limit_up/recent_touch_auction_backtest.py`（只读）
- 新建 `tests/alphaagent/test_recent_touch_auction_backtest.py`
- 产物 `memory/06_backtests/recent_touch_auction_backtest_20260803.{json,md}`

## 验证

```bash
uv run pytest tests/alphaagent/test_recent_touch_auction_backtest.py -v
docker compose --profile research run --rm --no-deps -v "$PWD:/app" alphaagent-research \
  python -m alphaagent.server.services.limit_up.recent_touch_auction_backtest \
  --start 2025-06-27 --end 2026-07-31 \
  --json-output memory/06_backtests/recent_touch_auction_backtest_20260803.json \
  --markdown-output memory/06_backtests/recent_touch_auction_backtest_20260803.md
```
