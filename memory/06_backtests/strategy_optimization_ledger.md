# Strategy Optimization Ledger

这个文件只记录仍会影响后续行动的策略结论。实验过程、长表、raw JSON、截图和失败流水不放这里。

## Current Baseline

- 默认策略：`mainline_dragon_pullback / 0.1.63`。
- 产品形态：用户只看到一个量化策略；龙回头、低吸、超跌反弹是内部隐藏路由和独立因子组。
- 候选池：每日统一排序后只评审 `Top5 / Top10 / Top20`；质量过滤只在 TopN 内部发生，不从 Top11-20 或更后面补位。
- 金手指、银手指、退潮、回暖是内部择时上下文和加分/过滤条件，不作为用户开关。

## Metric Decision

当前主口径已经重写：

- 全历史所有交易日逐日统计，但每日只评审 `Top5 / Top10 / Top20`。
- D 日信号出现，按 D 日收盘价理论买入。
- D+1 收盘涨跌是主胜率和主平均收益。
- D+2/D+3 只回答是否值得格局拿，不作为主收益。
- 组合回测、D+1 开盘成交、卖点收益只做执行层诊断。

实现入口：

- `alphaagent/server/services/backtest/tail_entry_next_day_label.py`
- `alphaagent/server/services/backtest/factor_audit.py`
- `GET /api/backtests/{id}/candidate-trade-quality-report`
- `/quant` 候选质量面板

## Latest Verified Metrics

`0.1.63` 已在服务环境轻量刷新 `2025-06-03..2026-07-06`；数据全市场覆盖从 `2025-06-03` 开始，实际 D+1 可评价 BUY 推荐从 `2025-08-06` 开始。以下 D+1 主报告按 `2025-08-06..2026-07-06` 统计，source recommendations `4002`，BUY evaluated `3079`，missing D+1 `14`。

- 全样本：
  - Top5：`n=992`，胜率 `48.9919%`，均值 `+0.3269%`，中位数 `0.0000%`，接近涨停率 `10.0806%`，D+1 大跌率 `8.7702%`
  - Top10：`n=1926`，胜率 `49.1693%`，均值 `+0.3822%`，中位数 `0.0000%`，接近涨停率 `9.5016%`，D+1 大跌率 `8.0478%`
  - Top20：`n=3079`，胜率 `48.9120%`，均值 `+0.3195%`，中位数 `0.0000%`，接近涨停率 `8.8340%`，D+1 大跌率 `8.0546%`
- 内部买点区域 Top20：
  - 龙回头：`50.3282% / +0.4455%`
  - 低吸首启：`46.2366% / +0.0776%`
  - 超跌反弹启动：`48.0519% / +0.2749%`
  - 低吸蓄势：`53.2075% / +0.5899%`
  - 重叠信号：`45.4887% / +0.0091%`
- 金/银窗口 Top20：
  - 银后6-20日：`49.0330% / +0.4482%`
  - 银后20日+：`45.3202% / +0.1629%`
  - 银后0-5日：`47.6431% / +0.0924%`
  - 金后6-20日：`56.5972% / +0.7019%`
  - 金后0-5日：`44.9405% / -0.0021%`
  - 金后20日+：`45.8824% / +0.3782%`
- 3 月银手指压力窗口 `2026-03-13..2026-03-24`：
  - Top5：`52.5000% / +1.0473%`
  - Top10：`53.2468% / +0.8542%`
  - Top20：`50.9259% / +0.8070%`
- 6 月修复窗口 `2026-06-09..2026-07-03`：
  - Top5：`45.5556% / +0.3717%`
  - Top10：`47.1591% / +0.3302%`
  - Top20：`47.0000% / +0.1478%`

结论：`0.1.63` 合入的是窄过滤，不是独立策略。它只剔除 `oversold_rebound_start + after_gold_0_5 + 无近端活跃源 + close_location<=0.35` 的超跌反弹失败形态；相对 `0.1.62` 真正移除 7 笔，均值 `-1.9654%`，无接近涨停样本。

## Remaining Weak Buckets

- `after_gold_0_5`：Top20 `44.9405% / -0.0021%`，仍是金手指窗口弱点。
- `after_silver_late`：Top20 `45.3202% / +0.1629%`，胜率偏低，中位数 `-0.2954%`。
- `dragon_pullback::after_gold_0_5`：Top20 `38.8889% / -0.2741%`，D+1 大跌率 `14.5833%`。
- `low_suction_first_lift::after_silver_late`：Top20 `41.4634% / -0.0752%`。
- `dragon_low_suction_overlap::after_silver_6_20`：Top20 `41.6667% / -0.3683%`。
- `low_suction_first_lift::after_silver_0_5`：Top20 `44.8864% / -0.1362%`。

已知弱样本：

- 6 月修复窗口龙回头大跌：`600711.SSE 盛屯矿业`、`001359.SZSE 平安电工`、`002156.SZSE 通富微电`、`001896.SZSE 豫能控股`、`600110.SSE 诺德股份`、`002552.SZSE 宝鼎科技`、`603260.SSE 合盛硅业`。
- 6 月修复窗口低吸首启大跌：`603931.SSE 格林达`、`000063.SZSE 中兴通讯`、`601100.SSE 恒立液压`。
- 3 月银手指压力窗口大跌：`000534.SZSE 万泽股份`、`002800.SZSE 天顺股份`、`002015.SZSE 协鑫能科`、`002714.SZSE 牧原股份`、`000830.SZSE 鲁西化工`。

## Current Stock-Level Facts

- `002407.SZSE` 在 2026-06-08、2026-06-09 被识别为 `oversold_rebound_start + after_silver_6_20`，D+1 分别 `+0.9218%`、`+2.2982%`；这是标准底部修复/超跌反弹，0.1.63 的金后早期低位无活跃源过滤不影响它。
- `603260.SSE` 在 2026-06-25、2026-07-02 被识别为龙回头，D+1 分别 `-4.1482%`、`-6.9430%`；它不是当前超跌反弹成功样本，而是低位修复后被龙回头误吸。
- `603629.SSE 2026-03-18` 是活跃洗盘后 MA5 收复龙回头：近 20 日有涨停/近涨停来源，D-1 大跌洗盘，D 日强收复且 MA20 不过度拉伸，D+1 涨停。
- 3 月 `2026-03-13..2026-03-24` 是银手指后压力窗口；上涨股主要来自相对强势、低位补涨、高低切、首板/二板和特殊主线。
  - 赢家样本：`002310.SZSE 东方新能`、`601016.SSE 节能风电`、`600186.SSE 莲花控股`、`600152.SSE 维科技术`、`600780.SSE 通宝能源`、`603175.SSE 超颖电子`。
  - 成功共同特征：近端活跃源或退潮高低切、D 日不是低位阴跌收盘、D+1 右尾来自接近涨停，而不是普通超跌低吸。

## Rejected Conclusions

- 不做 `Top10 保护 / Top11-20 替换 / 后位补位`，这会绕开个股研究。
- 不把 `bottom_reclaim`、`secondary_breakout_confirm` 做宽泛加分；只能用严格特征和窗口验证后窄合入。
- 不继续用旧多日卖点收益 overfit 统一 Top20。
- `after_silver_late` 龙回头/重叠高位滞涨过滤虽然改善全局，但会打坏 `2026-03-13..2026-03-24` 银手指压力窗口，暂不实现。

## Execution Loop

1. 统计：全历史每日候选只看 Top5/10/20，输出全样本、月份、金银窗口、行情阶段、买点区域和重点区间矩阵。
2. 归因：对低胜率/负收益桶抽 D+1 涨停、接近涨停、D+1 大跌样本，按龙回头、低吸、超跌反弹分别看共同特征。
3. 方案：只提出可由 D 日可见数据表达的窄加分或窄过滤，例如量能、均线收复、近端涨停来源、低位修复确认、过热拉伸、收盘位置。
4. 执行：先 dry-run 比较误删赢家和避免输家，再合入默认策略版本。
5. 验收：新版本必须同时看全样本、月度、金手指/银手指窗口、3 月压力窗口、5 月弱窗口、6 月修复窗口；只改善单一窗口但伤全样本的方案撤回。

## Current Local Verification

- `uv run pytest tests/alphaagent/test_candidate_lanes_silver_rotation_bonus.py tests/alphaagent/test_tail_entry_next_day_label.py -q`：通过。
- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q -k "candidate_trade_quality_scope_uses_execution_selected_inside_candidate_limit or execution_pool_drops_stale_active_weak_decay_pullback_without_refill or execution_pool_promotes_bottom_reclaim"`：通过。
- `python -m py_compile alphaagent/server/services/backtest/tail_entry_next_day_label.py alphaagent/server/services/backtest/factor_audit.py alphaagent/server/services/backtest/engine.py alphaagent/server/services/quant/candidate_lanes.py`：通过。
- `git diff --check`：通过。
