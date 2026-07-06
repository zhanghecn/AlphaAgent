# 2026-07-06 收尾与收益算法重写交接

## 当前收尾结论

本轮停止继续沿旧收益口径调 `bottom_reclaim` 加分。核心原因不是超跌反弹无效，而是旧口径把“尾盘买入后第二天是否涨”和“后面拿多少天、怎么卖”混在一起，导致每次优化都会卡在胜率、平均收益、右尾、左尾之间取舍。

旧口径下最新只读尝试已经撤掉代码，不进生产。实验内容是 `after_silver_6_20 / retreat + bottom_reclaim + rank21-60` 正向加分：

- 6 月窗口 `2026-06-09..2026-07-03`：baseline `299` eval，胜率 `42.4749%`，平均 `+1.9446%`，right>=20 `25`，left<=5 `88`。
- 该临时加分后：胜率升到 `44.4816%`，但平均降到 `+1.7184%`，right>=20 降到 `21`，left<=5 降到 `83`。
- 换入 22 笔胜率 `68.1818%`，平均 `+2.3618%`，但换出 22 笔平均 `+5.4366%`，right>=20 有 `4` 笔。
- 被误伤右尾包括 `600206.SSE 有研新材 +87.9791%`、`000672.SZSE 上峰材料 +30.2128%`、`603002.SSE 宏昌电子 +27.0833%`、`600999.SSE 招商证券 +21.8994%`、`603260.SSE 合盛硅业 +16.9061%`。
- 3 月压力窗口 `2026-03-13..2026-03-24` 没有触发，不改善也不恶化。

因此结论是：不能继续靠“普通 bottom_reclaim rank21-60 加分”解决问题。它解决小亏和小胜，不解决策略真正需要的右尾收益，还会把已抓到的右尾挤出去。

## 已完成到哪里

当前生产默认仍是：

- `mainline_dragon_pullback / 0.1.52`
- 用户侧只有一个策略。
- 龙回头、低吸、超跌反弹、退潮高低切、金/银手指都只作为内部 lane、候选源和正向机会因子。

已经完成并可作为后续基础：

- `bottom_reclaim` 已融合为超跌反弹内部 lane，能抓 `002407.SZSE` 这类底部收复。
- `secondary_breakout_confirm + deep_cycle_secondary_breakout_reversal` 已用于识别 `603260.SSE` 这类低位二次确认。
- 严格 `secondary_breakout_confirm + frontrow` 空位补位已合入生产，解决 `603260.SSE 2026-06-09` 进入 Top20 的问题。
- 银后轮动漏选右尾、金后期低吸爬升、退潮板生存候选源已有窄版生产因子，仍然不增加用户选择。
- `after_silver_6_20 / warming` 已验证为假回暖弱桶，继续用日线低吸/超跌阈值加分会伤 right-tail，不应再投入。

## 收尾清理

本轮已清理：

- 撤掉失败的 `silver_6_20_retreat_bottom_rank60_bonus` 临时代码和对应测试。
- 删除旧 Top20 口径下的未跟踪实验模块、CLI、测试和过期超跌研究计划文档。
- 删除 `memory/06_backtests` 顶层的生产过程长报告，只保留当前台账和本交接文件。
- 删除两份已失效临时 JSON：
  - `memory/06_backtests/cache/top20_secondary_breakout_bottom_rank60_june_20260609_20260703_v034_20260706.json`
  - `memory/06_backtests/cache/top20_secondary_breakout_bottom_rank60_march_20260313_20260324_v034_20260706.json`
- 没有后台回测进程残留。

没有清理的内容：

- 当前生产源码、前端、市场择时、主线复盘和测试改动仍保留在 git 工作区，等待按主题拆分提交。
- `memory/06_backtests/cache/` 仍可能有可再生成 JSON/cache。后续只在需要复核旧结论时再使用，不作为长期阅读入口。

## 新收益算法目标

新的主目标改为“尾盘买入后的下一交易日必须涨”，不再把初始选股优化绑定到多日卖点收益。

建议把收益标签拆成两层：

1. D 日信号出现，按 D 日尾盘价买入。
2. D+1 必须上涨，作为主筛选目标。
3. 只有 D+1 已经上涨的票，才进入 D+2/D+3 是否格局拿的二级判断。

主标签：

- `tail_entry_price`: D 日收盘价，后续可替换成尾盘均价。
- `d1_open_return_pct`: D+1 开盘相对 D 收盘收益。
- `d1_high_runup_pct`: D+1 最高价相对 D 收盘收益。
- `d1_low_drawdown_pct`: D+1 最低价相对 D 收盘回撤。
- `d1_close_return_pct`: D+1 收盘相对 D 收盘收益。
- `d1_success`: `d1_close_return_pct > 0`，这是主胜率。
- `d1_quality_success`: `d1_close_return_pct > 0` 且 `d1_high_runup_pct >= 1.5%` 且 `d1_low_drawdown_pct > -3%`，用于排除次日大幅水下后勉强翻红。

第三天格局标签：

- `d2_close_return_pct`、`d3_close_return_pct`: D+2/D+3 收盘相对 D 收盘收益。
- `d2_d3_best_runup_pct`: D+2/D+3 最高收益。
- `hold_to_d3_worthwhile`: D+1 成功后，D+2/D+3 至少有一次比 D+1 收盘更高，且没有跌回 D 日买入价下方。
- `take_profit_next_day`: D+1 成功但 D+2/D+3 回撤明显，说明该类只适合次日走人。

这个口径把问题拆开：

- 选股层先只优化“尾盘买，明天能不能涨”。
- 持仓层再判断“涨了之后第三天要不要格局”。
- 旧的多日卖点收益只作为辅助诊断，不再作为 Top20 排序主目标。

## 后续执行方案

第一步：新增只读标签生成器。

- 从现有候选池生成 D 日全量候选，不只 Top20。
- 对每条候选写入 `tail_entry_price`、D+1 开高低收收益、D+2/D+3 格局标签。
- 不使用未来字段训练 D 日买入；D+2/D+3 只作为事后标签。

第二步：重跑全量分桶。

- 按 `dragon_pullback`、`low_suction_first_lift`、`low_suction_buildup`、`bottom_reclaim`、`secondary_breakout_confirm` 分开统计。
- 按金手指/银手指、`retreat/warming/rotation`、3 月压力窗口、6 月修复窗口分开统计。
- 输出每个桶的 `d1_success`、`d1_quality_success`、`d1_close_return_pct`、`d1_low_drawdown_pct`、`hold_to_d3_worthwhile`。

第三步：重新定义优化目标。

- 默认 Top20 排序主目标改为提高 `d1_quality_success`。
- 平均多日收益、right-tail、旧卖点收益降级为二级约束。
- 一票否决：任何方案如果把 D+1 大幅低开/低走数量增加，不能晋升。

第四步：再回到个股分析。

- 对 D+1 成功票研究共同特征：题材、板质量、量能、收盘位置、MA 修复阶段、金/银区间。
- 对 D+1 失败票研究共同特征：假修复、无承接、过热、弱题材、退潮早段、尾盘兑现。
- 特别复核 `002407.SZSE`、`603260.SSE`、3 月压力窗口上涨票和 6 月被误伤右尾。

第五步：只在新口径通过后再改生产因子。

- 生产仍保持单一 `mainline_dragon_pullback`。
- 内部可以继续隐藏 lane 和正向因子，但晋升门槛改为 D+1 成功率优先。
- D+2/D+3 只影响卖出/持仓模块，不再反向污染 D 日选股。

## 下一次开工入口

建议下一次直接做：

1. 新增 `tail_entry_next_day_label` 只读研究器。
2. 跑 `2024-05-28..2026-07-03` 全量候选标签。
3. 先出中文表格：超跌反弹区域、低吸区域、龙回头区域，在不同金/银手指区间的 D+1 胜率和 D+2/D+3 格局率。
4. 再决定哪些因子进入生产。
