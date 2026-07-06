# Market Timing Design

这个文件记录大盘择时模块的当前设计和已验证限制。具体实验过程不要继续追加到这里；新实验应写到 `memory/06_backtests/` 或独立研究报告。

## Current Semantics

- 金手指：大盘状态转向可进攻或回调企稳后的看多信号。
- 银手指：大盘状态转向防守或顶部风险后的看空信号。
- 产品用法：金/银手指不作为用户手动策略开关；在量化候选中作为内部市场环境因子、风险解释和排序上下文。
- 当前与 Top20 研究的关系：金/银手指单独不够精准，必须结合 setup、均线位置、量能、收盘位置、主线、右尾保护和失败风险。
- v4 候选+确认两状态（2026-07-04 起）：每个候选事件标在【候选日 i】，`status` 记次日确认结果 —— `CONFIRMED`(次日同向, state 改变) / `INVALIDATED`(次日反向假突破, 事件保留) / `PENDING`(序列末端待确认)。事件存在性不依赖未来，被否决的候选不再被静默丢弃（修复 v2.4.2「候选被未来抹掉」的语义未来函数）。

## Algorithm Shape

大盘基准：

- 用 `market_context.INDEX_WEIGHTS` 对 7 大指数日收益率加权，再 cumprod 成综合序列。
- 图表可以展示上证指数，但信号基于综合序列。

主要因子族：

- trend：趋势。
- momentum：动量，包含 MACD/RSI/ROC 等技术代理。
- breadth：市场广度。
- structure：波动结构、风险分、连阳/收敛。
- volume：量能和量价同向。
- top-divergence：MACD 顶背离、广度顶背离等顶部风险。

硬约束：

- 所有特征严格只用 `<=t` 数据。
- 未来收益只用于 backtest/eval 标签，不进入信号生成。
- 信号生成和回测评估物理隔离。
- 无未来函数测试必须覆盖“篡改 t 之后数据，t 及以前因子/信号不变”。

## Implementation Entrypoints

模块：

```text
alphaagent/server/services/quant/market_timing/
  series.py
  factors.py
  signal.py
  backtest.py
```

脚本和测试：

```bash
uv run python scripts/market_timing_eval.py
uv run pytest tests/alphaagent/services/quant/test_market_timing_no_lookahead.py -q
```

面板服务：

- `market_timing_panel`: 单行 JSONB 预计算表。
- `POST /api/market-timing/refresh`: 强制刷新。
- `GET /api/market-timing/panel`: 面板读取，优先内存缓存，再库缓存，再现算。
- 盘中实时（2026-07-04 起）：`panel.start_intraday_refresher()` daemon thread（`main.py` lifespan 启动）盘中每 5min force_refresh；`_compute_panel` 盘中追加 `series.intraday_today_bar()`（七大指数实时点位 `INDEX_WEIGHTS` 加权合成）到 composite 末尾，今天 ctx 用昨天近似（广度滞后，其他因子实时），今天候选自动 PENDING。内存 TTL 盘中 5min / 盘后 30min。非盘中/拉取失败/volume=0 退化为昨日 panel。解决「盘中错过信号、收盘后才看到」的问题；限制是广度滞后一天、PENDING 非确认、5min 间隔。

## Current Evidence Summary

- 早期 v1/v2 事件型金手指在 2024-05 至 2026-06 牛市样本上能抓到回调企稳，但银手指因为缺少熊市/大顶样本无法有效验证。
- v3 仓位状态机解决金/银频繁交替问题，但金手指从“回调企稳”语义转为“状态切换进场”后，胜率接近市场择时真实难度。
- v5/v6 的失败样本分析显示，MACD 顶背离和广度顶背离是过滤错误金手指的有效方向；这是数据驱动改进，不是盲目加顺势过滤。
- 由于样本只有 2024-05 至 2026-06，且整体偏牛，强信号样本很少，银手指无法被充分证伪或证实。
- 当前结论：金/银手指可以作为内部因子和解释层，但不能单独决定买卖，也不能替代个股候选质量研究。
- v2.4.1 (候选即发) vs v2.4.2 (次日确认) 在同一历史下事件**零重合**：v2.4.1 产 17 个（如 `2026-02-02 SILVER`），v2.4.2 产 8 个（如 `2026-02-06 SILVER`，标在确认日且次日反向的假突破被过滤）。两版差异曾被误判为未来函数，实际是算法版本差异。
- 本地 `/market` 面板已于 2026-07-04 升级到 v4 候选+确认两状态：缓存 20 个事件（8 CONFIRMED + 12 INVALIDATED），7/1 GOLD 以 INVALIDATED 保留（不再消失），`2026-02-02` 等历史候选同样保留。
- v4 回测对比回应了「次日确认是循环论证」的质疑：CONFIRMED 金手指 5/10/20 日胜率 75%/75%/100%、均收益 +9.81%/+6.79%/+11.31%；被过滤的 INVALIDATED 假突破方向命中仅 27%/45%/27%、均收益 -0.20%/-0.51%/+1.38%。两组显著差异 → 次日确认是真预测力，不是数据窥视。

## How To Use In Quant Research

- 在 Top20 研究中，金/银手指应作为 D 日可见特征进入 meta-feature table。
- 不要只比较“金手指 vs 银手指”；要分 setup 和位置，例如 `bottom_reclaim + after_silver + retreat`、`dragon_pullback + after_gold_6_20 + warming`。
- 银手指后退潮修复对 `bottom_reclaim/bottom_ma_repair` 更有价值；弱金或假回暖可能对应低吸首启失败风险。
- 行情标签若与个股结构冲突，优先看具体结构：均线修复阶段、MA20/MA60 距离、量能可控、收盘位置、主线扩散和 D+1 跟随。

## Open Risks

- 需要更长历史指数数据覆盖 2015、2018、2021 等熊市/大顶阶段，否则银手指准确率不能定论。
- 当前样本强信号数量少，bootstrap CI 宽，阈值可能过拟合。
- 市场择时更适合作为候选 ranker 的上下文因子，不适合作为硬开关；硬开关容易漏掉个股右尾。
- 运维：`market_timing_panel` 库缓存 TTL=24h + 进程内 30min，**算法变更不会自动失效**。改 signal/factors 算法后必须两步：① `docker compose up --build -d alphaagent-api`（+ `alphaagent-web` 若改前端）重建镜像让容器代码跟上源码（2026-07-04 即发现本地容器停在 v2.4.1，而源码已更新）；② `POST /api/market-timing/refresh` 强制重算落库。否则线上/本地/源码三方展示不同版本事件，极易被误判为未来函数。
- 线上 `agu.yantiandao.com` 截至 2026-07-04 仍是旧版本（v2.4.1 或更早），仍有「金手指消失」问题。本地 v4 改完后需打新 tag 触发 ghcr 发版对齐（待主人提供线上密码/ssh）。
- no-lookahead 守护测试覆盖 v4 全路径：事件存在性不被未来抹除（`test_invalidated_candidates_not_erased`）+ status 与次日方向一致 + 假突破保留为 INVALIDATED 不被丢弃。见 `tests/alphaagent/services/quant/test_market_timing_no_lookahead.py`。
