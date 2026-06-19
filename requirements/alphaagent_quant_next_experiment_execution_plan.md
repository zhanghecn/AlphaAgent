# AlphaAgent Quant Next Experiment Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not change the default product strategy unless this plan's promotion gate passes.

**Goal:** 在现有细粒度特征审计基础上，拆清候选没买、买后失败、支撑止损、卖早反弹、浮盈回吐和替换交易质量，再只用默认关闭实验验证是否能降低亏损并保住收益。

**Architecture:** 继续保持一个公开策略 `mainline_dragon_pullback / 0.1.21` 和一个简单用户流程。内部先增强只读归因，再分别做窄口径买点、卖点、回撤和换仓实验；每个实验默认关闭、可复现基线、可按年度/市场/排除强势/重点股票/机会成本报告。

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, existing `backtest_*` / `quant_*` tables, React/TypeScript, pytest, Vite, Docker Compose, evidence reports under `memory/06_backtests/`.

---

## 0. 后续执行快照

### 当前状态

这份计划用于后续继续执行，不是默认策略变更说明。当前已确认：

- 产品默认策略仍是 `mainline_dragon_pullback / 0.1.21`。
- 产品基线仍是 `#203/#194`，区间 `2025-03-26..2026-06-18`，收益约 `+82.99%`，最大回撤约 `-15.59%`。
- 历史研究执行模型仍是 `legacy_next_open`，即 D 日收盘可见信号、D+1 日线开盘执行。
- `Task 0` 已完成：基线冻结和 `baseline_only=true` 口径确认。
- `Task 1` 已完成：`candidate_not_planned` 已拆出子原因，并补充 `by_not_filled_subreason`。
- `Task 2` 已完成：重点股票逐日信号报告已写入 `memory/06_backtests/2026-06-19_quant_focus_symbol_signal_audit.md`。
- `signal-history` 已做读侧性能优化：市场画像按交易日批量预计算复用，窄区间重点查询约 `3..4.5s`。

### 下一步执行顺序

后续执行必须按下面顺序推进，每完成一个任务都要跑对应测试和 API 抽样，不能一次性把多个实验揉到一起：

1. 完成新增实验参数的全链路透传：schema、API payload、run params、strict pipeline、strategy replay JSON、baseline exclusion。
2. 补默认关闭测试：所有新增实验开关默认必须是 `False`，且一旦为 `True` 就不能进入 `baseline_only=true`。
3. 实现并验证 `Task 3` 支撑止损延迟确认实验。
4. 实现并验证 `Task 4` 高浮盈回撤保护实验。
5. 实现并验证 `Task 5` 低吸假启动观察/降权实验。
6. 实现并验证 `Task 6` 满仓和换仓质量实验。
7. 汇总 `Task 7` 实验报告，统一比较收益、回撤、胜率、年度、市场分组、排除强势行情、重点股票、替换质量和未来函数风险。
8. 做 `Task 8` 前端简单展示整合，只展示解释和归因，不新增普通用户复杂按钮。
9. 跑 `Task 9` 最终验证：后端测试、compileall、前端 build、`git diff --check`、Docker API 冒烟和页面烟测。

### 本轮优先级判断

后续实验优先处理“收益降低到底来自买点还是回撤/卖点”的问题：

- `002443.SZSE` 这类已有明显浮盈后回吐到亏损，优先进入高浮盈回撤保护实验。
- `600352.SSE`、`002240.SZSE` 这类低吸确认后假启动，优先进入低吸假启动观察/降权实验。
- `002384.SZSE` 这类有关键低吸信号但组合没买，优先用候选执行归因和满仓换仓质量解释，不直接扩大持仓。
- `603439.SSE` `2026-05-11` 如果当前策略没有识别，不能把后续卖点或换仓实验声称为已修复。
- `002119.SZSE` 重复龙回头风险不能直接硬拒，历史实验已经证明宽泛硬拒会拉低全局收益。

### 禁止事项

后续执行者必须遵守：

- 不修改默认公开策略参数，除非 `Task 7` 晋升门槛全部通过并有明确用户确认。
- 不新增第二个普通用户公开策略。
- 不恢复历史 `14:30` 依赖。
- 不把低吸蓄势期每天画成 BUY。
- 不把固定持有收益、MFE、MAE、卖后反弹、当前策略交易结果用于信号日评分、排序、买卖或仓位。
- 不按股票代码特判。
- 不让任何实验开关为 `true` 的回测进入 `baseline_only=true`。
- 不用单个股票修复结果替代全局、年度、市场分层和排除强势行情验证。

### 完成判定

后续执行完成时，必须能用报告和页面/API 证据回答：

- 收益变化来自买点改善、卖点改善、回撤控制、满仓换仓质量，还是市场强弱样本差异。
- 排除强势行情后，前 `10/20/100` 候选胜率和收益是否仍改善。
- 弱市、震荡、主线回踩、窄牛环境里是否至少两个市场桶不变差。
- 被过滤或提前卖出的赢家收益是否小于避免亏损收益。
- 卖出释放仓位后的替换交易质量是否没有变差。
- 股票详情和 `/quant` 页面展示是否仍保持简单，复杂归因只在解释区出现。

## 1. 当前起点

### 已完成证据

- 当前产品基线：`#203/#194`。
- 策略：`mainline_dragon_pullback / 0.1.21`。
- 区间：`2025-03-26..2026-06-18`。
- 执行：`legacy_next_open`，D 日收盘可见信号，D+1 日线开盘撮合。
- 结果：收益约 `+82.99%`，最大回撤约 `-15.59%`，买入/卖出/持仓中约 `224 / 214 / 10`。
- 候选观察：前 `100`，分页每页 `20`。
- 组合执行：BUY 候选前 `20`，最大持仓 `10`。
- 第一轮信号审计报告：`memory/06_backtests/2026-06-19_quant_feature_drilldown_report.md`。

### 第一轮结论

- `candidate_execution_attribution` 已证明：top20 审计候选里有 `12` 个没有真实成交，其中 `8` 个固定持有后验为正。
- `candidate_not_planned` 仍太粗，需要拆成理论持仓、缓存缺口、计划生成口径、执行池过滤等子原因。
- `support_stop` 不是一个问题，至少拆成真失败启动、止损后反弹、有承接后破支撑、浮盈回吐后破位、高浮盈后止损又反弹。
- `replacement_bad`、`sold_too_early`、`sell_giveback` 的样本量比单纯 `buy_point_bad` 更大，不能只改买点。
- 低吸蓄势不是每天 BUY；关键点是蓄势后的首个有效上拉。
- 低吸和龙回头是两套 setup，但共用均线承接、支撑、量能、收盘位置和市场状态；不能简单直接互相加分。
- 动态大盘/主线画像目前是审计层，资金流长历史不足，不能直接用于默认交易规则。

### 不可违反的边界

- 不新增第二个公开策略。
- 不恢复历史 `14:30` 依赖。
- 不强行给低吸保留名额。
- 不把低吸蓄势期每天画成 BUY。
- 不用固定持有收益、MFE、MAE、卖后反弹、当前策略结果参与信号日评分、排序、买卖或仓位。
- 不按股票代码特判。
- 不让任何实验参数为 true 的回测进入 `baseline_only=true`。
- 不在报告通过前修改默认买卖规则。

## 2. 下一轮要回答的问题

1. `candidate_not_planned` 到底是策略没有计划、已经理论持有、缓存不完整、schema 旧、执行池过滤，还是计划生成和候选页口径不一致？
2. 低吸买点失败到底发生在纯蓄势未启动、首个上拉量弱、回踩过久、市场未回暖，还是龙回头重复高位风险？
3. `support_stop` 里哪些应该更早卖，哪些应该多等一次支撑收复，哪些应该做浮盈保护？
4. 卖出释放的仓位是否买入了更差候选？如果是，卖出实验必须同时约束替换质量。
5. 满仓时错过的 top20 候选是否稳定强于当前持仓？如果不是，不能扩大持仓或放宽换仓。
6. 排除强势行情、按年度/市场分层后，实验是否仍提升胜率和收益？
7. 页面是否能用简单文本解释“为什么有信号没买、为什么买了后亏、为什么不改默认策略”？

## 3. 计划文件和代码边界

### 主要后端文件

- `alphaagent/server/services/backtest/factor_audit.py`
  - 扩展 candidate execution attribution 子原因。
  - 扩展 missed-candidate 与真实计划/订单/成交对齐。
- `alphaagent/server/services/backtest/engine.py`
  - 接入新增归因摘要、实验参数解析、报告入口。
- `alphaagent/server/services/backtest/queries.py`
  - 扩展 path diagnostics、setup/market/exit audit、replacement-quality attribution。
- `alphaagent/server/services/backtest/schemas.py`
  - 新增默认关闭实验参数。
- `alphaagent/server/services/backtest/simulation.py`
  - 实现默认关闭卖点/买点/换仓实验。
- `alphaagent/server/services/backtest/scoring.py`
  - 只在买点侧默认关闭实验中读取信号日可见字段做观察/降权。
- `alphaagent/server/services/backtest/baseline_policy.py`
  - 把新增实验参数加入产品基线排除列表。

### 主要前端文件

- `frontend/src/api/quant.ts`
  - 新增只读字段和实验对比结果类型。
- `frontend/src/features/quant/BacktestAnalysis.tsx`
  - 在现有回测分析里展示实验对比、候选没买子原因、卖点路径和替换质量。
- `frontend/src/features/quant/BacktestPanel.tsx`
  - 继续保持一个回测入口，不新增主按钮。
- `frontend/src/pages/StockDetailPage.tsx`
  - 股票详情时间线展示候选、计划、成交、卖出和未买原因的一条统一链路。

### 测试文件

- `tests/alphaagent/test_quant_backtest_portfolio.py`
  - 所有新增逻辑优先补定向单测。
  - 每个实验都必须证明默认参数复现基线。

### 证据文件

- 新增：`memory/06_backtests/YYYY-MM-DD_quant_next_experiment_report.md`
- 更新：`memory/06_backtests/README.md`
- 只有真实实验落库后才更新：`memory/06_backtests/strategy_optimization_ledger.md`
- 只有长期决策变化后才更新：`memory/09_decisions/decisions.md`

## 4. Task 0: 执行前冻结基线

**目的：** 确保所有实验都和当前产品基线比，不被更长区间或历史实验污染。

**Files:**

- Read: `memory/06_backtests/README.md`
- Read: `memory/06_backtests/strategy_optimization_ledger.md`
- Read: `memory/09_decisions/decisions.md`

- [x] **Step 1: 检查工作区**

Run:

```bash
git status --short
```

Expected:

- 记录 dirty files。
- 不 revert、不 reset、不 checkout 用户或前序改动。
- 不执行 `git commit`，除非用户明确要求。

- [x] **Step 2: 确认产品基线**

Run:

```bash
curl -sS 'http://localhost:8000/api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5' \
  | jq '.items[] | {id, strategy_version, start_date, end_date, total_return_pct, max_drawdown_pct, baseline_reason, baseline_warning}'
```

Expected:

- 返回 `#203/#194` 或后续明确标记为 `current_product` 的新基线。
- 不返回 `#195/#196/#197/#198/#199/#200/#201/#207/#208/#211` 等实验 run。

- [x] **Step 3: 记录本轮报告头**

Report header:

```text
基线：#203/#194
策略：mainline_dragon_pullback / 0.1.21
区间：2025-03-26..2026-06-18
执行：legacy_next_open
收益：+82.99%
最大回撤：-15.59%
买入/卖出/持仓中：224 / 214 / 10
```

## 5. Task 1: 拆分 `candidate_not_planned`

**目的：** 回答“候选页有信号为什么组合没买”，不要再把所有没计划都叫同一个原因。

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/services/backtest/queries.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] **Step 1: 增加子原因枚举测试**

Add test:

```python
def test_candidate_not_planned_subreason_separates_plan_gaps() -> None:
    from alphaagent.server.services.backtest.factor_audit import classify_candidate_plan_gap

    assert classify_candidate_plan_gap(
        {
            "rank": 3,
            "entry_action": "BUY",
            "candidate_trade_date": "2026-04-01",
            "vt_symbol": "002384.SZSE",
            "theoretical_position": {"is_holding": True, "entry_date": "2026-03-28"},
        },
        signal_events=[],
        orders=[],
        cache_coverage={"candidate_count": 100, "signal_count": 0},
    )["subreason"] == "already_theoretical_holding"

    assert classify_candidate_plan_gap(
        {
            "rank": 5,
            "entry_action": "BUY",
            "candidate_trade_date": "2026-05-11",
            "vt_symbol": "603439.SSE",
        },
        signal_events=[],
        orders=[],
        cache_coverage={"candidate_count": 8, "signal_count": 0},
    )["subreason"] == "candidate_cache_sparse_or_missing"
```

- [x] **Step 2: 实现子原因函数**

Required function:

```python
def classify_candidate_plan_gap(
    candidate: dict[str, object],
    *,
    signal_events: list[dict[str, object]],
    orders: list[dict[str, object]],
    cache_coverage: dict[str, object] | None = None,
) -> dict[str, object]:
    ...
```

Allowed `subreason` values:

- `already_theoretical_holding`
- `signal_event_missing`
- `candidate_cache_sparse_or_missing`
- `action_mismatch_resolved_to_watch`
- `execution_pool_filtered`
- `date_outside_replay_window`
- `planned_but_order_missing`
- `unknown_plan_gap`

Required output:

```json
{
  "reason": "candidate_not_planned",
  "subreason": "already_theoretical_holding",
  "label": "候选存在，但理论计划层已持有同股或没有重复写 BUY",
  "not_used_for_signal_score": true
}
```

- [x] **Step 3: 接入 `candidate_execution_attribution`**

For each missed row, add:

```json
{
  "not_filled_reason": "candidate_not_planned",
  "not_filled_subreason": "already_theoretical_holding",
  "not_filled_label": "候选存在，但理论计划层已持有同股或没有重复写 BUY"
}
```

- [x] **Step 4: API 抽样验证**

Run:

```bash
curl -sS 'http://localhost:8000/api/backtests/203/factor-audit?top_limit=100' \
  | jq '.candidate_execution_attribution.by_not_filled_reason, .candidate_execution_attribution.items[] | select(.not_filled_reason=="candidate_not_planned") | {trade_date, vt_symbol, rank, not_filled_subreason, not_filled_label}'
```

Expected:

- 不再只有粗粒度 `candidate_not_planned`。
- `002384.SZSE` `2026-04-01` 能解释为理论持仓/满仓/换仓约束中的明确一种或组合。
- `603439.SSE` `2026-05-11` 若没有候选，应明确显示未被当前候选缓存/策略识别，而不是误报已识别。

## 6. Task 2: 重点日期 signal-history 补证

**目的：** 对用户反复点名的股票逐日复核，判断是候选没识别、识别但没计划、计划但没成交，还是成交后卖点失败。

**Files:**

- Modify only if API lacks fields: `alphaagent/server/services/quant/symbol_diagnostics.py`
- Modify only if API lacks fields: `alphaagent/server/services/backtest/engine.py`
- Create report: `memory/06_backtests/YYYY-MM-DD_quant_focus_symbol_signal_audit.md`

- [x] **Step 1: 收集重点股票逐日信号**

Run:

```bash
for symbol in 002384.SZSE 603439.SSE 601179.SSE 600352.SSE 002240.SZSE 002119.SZSE 002443.SZSE; do
  curl -sS "http://localhost:8000/api/quant/symbols/${symbol}/signal-history?strategy=mainline_dragon_pullback&start=2026-01-01&end=2026-06-18" \
    > "/tmp/${symbol}_signal_history.json"
done
```

Expected:

- 每个日期能看到 `action`、`raw_entry_signal`、`executable_entry_signal`、`total_score`、`low_suction_stage_label`、`low_suction_launch_quality_label`、`low_suction_dragon_state`、`failed_rules`。

- [x] **Step 2: 收集重点候选追踪**

Run:

```bash
curl -sS 'http://localhost:8000/api/backtests/203/candidate-trace?vt_symbol=002384.SZSE&signal_date=2026-04-01'
curl -sS 'http://localhost:8000/api/backtests/203/candidate-trace?vt_symbol=603439.SSE&signal_date=2026-05-11'
curl -sS 'http://localhost:8000/api/backtests/203/candidate-trace?vt_symbol=601179.SSE&signal_date=2026-02-25'
curl -sS 'http://localhost:8000/api/backtests/203/candidate-trace?vt_symbol=600352.SSE&signal_date=2026-03-11'
curl -sS 'http://localhost:8000/api/backtests/203/candidate-trace?vt_symbol=002240.SZSE&signal_date=2026-03-11'
curl -sS 'http://localhost:8000/api/backtests/203/candidate-trace?vt_symbol=002119.SZSE&signal_date=2026-02-05'
curl -sS 'http://localhost:8000/api/backtests/203/candidate-trace?vt_symbol=002443.SZSE&signal_date=2026-05-13'
```

Expected classification:

- `recognized_and_filled`
- `recognized_not_planned`
- `planned_not_ordered`
- `ordered_rejected`
- `not_recognized_by_current_strategy`
- `recognized_watch_only`

- [x] **Step 3: 写重点报告**

Report sections:

```text
1. 东山精密 002384.SZSE：2026-03-27..2026-04-08，2026-06-09..2026-06-15
2. 红蜻蜓/603439.SSE：2026-05-08..2026-05-11 和当前缓存证据
3. 中国西电 601179.SSE：2026-02-03 vs 2026-02-24/25
4. 浙江龙盛 600352.SSE：2026-03-10..2026-03-12
5. 盛新锂能 002240.SZSE：2026-03-11/13
6. 康强电子 002119.SZSE：重复龙回头风险
7. 众业达 002443.SZSE：浮盈回撤卖点
```

Required conclusion per symbol:

```text
识别状态：
组合执行状态：
亏损/错过主因：
下一轮实验是否覆盖：
不能得出的结论：
```

## 7. Task 3: 支撑止损延迟确认实验

**目的：** 只对“疑似卖早且没有更好替换候选”的支撑止损多等一次确认，验证能否降低卖早亏损，同时不扩大回撤。

**Files:**

- Modify: `alphaagent/server/services/backtest/schemas.py`
- Modify: `alphaagent/server/services/backtest/simulation.py`
- Modify: `alphaagent/server/services/backtest/baseline_policy.py`
- Modify: `alphaagent/server/services/backtest/queries.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] **Step 1: 新增默认关闭参数测试**

Add test:

```python
def test_contextual_support_reclaim_delay_defaults_off_and_excluded_from_baseline() -> None:
    from alphaagent.server.services.backtest.baseline_policy import is_product_baseline_params
    from alphaagent.server.services.backtest.schemas import BacktestParams

    params = BacktestParams()
    assert params.enable_contextual_support_reclaim_delay is False

    assert is_product_baseline_params({"enable_contextual_support_reclaim_delay": False}) is True
    assert is_product_baseline_params({"enable_contextual_support_reclaim_delay": True}) is False
```

- [x] **Step 2: 加参数**

Add to `BacktestParams`:

```python
enable_contextual_support_reclaim_delay: bool = False
support_reclaim_delay_max_warning_level: int = 2
support_reclaim_delay_max_replacement_score_gap: float = 6.0
support_reclaim_delay_min_sell_day_range_pct: float = 5.0
```

Add `enable_contextual_support_reclaim_delay` to `RESEARCH_SWITCHES` in `baseline_policy.py`.

- [x] **Step 3: 实现可见条件**

Only delay `support_stop` when all are true on the sell signal day:

- `exit_reason == "support_stop"`。
- position had at least one visible positive path or early MFE `>= 0`。
- sell signal day振幅 `>= support_reclaim_delay_min_sell_day_range_pct`，说明可能是恐慌洗盘。
- current close has not broken hard loss threshold by more than `stop_loss_pct + 2%`。
- `market_warning_level <= support_reclaim_delay_max_warning_level` or market context is `mainline_pullback` / `choppy_rotation`。
- no same-day replacement candidate has score gap greater than `support_reclaim_delay_max_replacement_score_gap`。
- current day has no stronger explicit SELL reason such as `trend_break` or high-level distribution risk.

Decision:

```text
D 日触发 support_stop 但满足延迟条件：不立刻创建 D+1 卖单，创建 pending_reclaim_check。
D+1 收盘可见后仍未收复支撑/MA5/MA10 或大盘风险升高：D+2 开盘卖。
D+1 收复支撑且无强卖出信号：继续持有，后续仍按正常卖点状态机。
```

- [x] **Step 4: 重点验证**

Run experiment as non-baseline:

```bash
curl -sS -X POST 'http://localhost:8000/api/backtests/portfolio' \
  -H 'Content-Type: application/json' \
  -d '{
    "strategy": "mainline_dragon_pullback",
    "start": "2025-03-26",
    "end": "2026-06-18",
    "execution_model": "legacy_next_open",
    "candidate_limit": 20,
    "max_positions": 10,
    "max_symbols": 5000,
    "enable_contextual_support_reclaim_delay": true,
    "persist": true,
    "exclude_from_product_baseline": true
  }'
```

Expected report:

- Compare baseline vs experiment return, max drawdown, win rate, profit factor。
- `support_stop` count and loss must improve without cutting `trend_trailing_stop` profit materially。
- `002384.SZSE` sell-early cases should improve or be explained.
- `002443.SZSE` may not improve, because it is more like high-MFE giveback than rebound-prone support stop.

Promotion fail conditions:

- Return drops more than `2` percentage points.
- Max drawdown worsens.
- Trend winners removed profit exceeds avoided loser profit.
- Replacement quality worsens.

## 8. Task 4: 高浮盈回撤保护实验

**目的：** 针对 `002443.SZSE` 这类已有明显浮盈后回吐到亏损的问题，验证“收益高位回撤”能否在不截断趋势大肉的前提下保护利润。

**Files:**

- Modify: `alphaagent/server/services/backtest/schemas.py`
- Modify: `alphaagent/server/services/backtest/simulation.py`
- Modify: `alphaagent/server/services/backtest/baseline_policy.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] **Step 1: 新增默认关闭参数**

Add to `BacktestParams`:

```python
enable_contextual_peak_giveback_stop: bool = False
peak_giveback_min_high_gain_pct: float = 0.12
peak_giveback_max_current_gain_pct: float = 0.03
peak_giveback_drawdown_pct: float = 0.07
peak_giveback_min_holding_days: int = 5
```

Add `enable_contextual_peak_giveback_stop` to product baseline exclusions.

- [x] **Step 2: 加测试**

Add test:

```python
def test_contextual_peak_giveback_requires_visible_profit_and_no_current_buy_signal() -> None:
    from alphaagent.server.services.backtest.simulation import should_trigger_contextual_peak_giveback_stop

    decision = should_trigger_contextual_peak_giveback_stop(
        highest_return_pct=0.13,
        current_return_pct=0.02,
        holding_days=12,
        has_current_buy_or_hold_signal=False,
        market_warning_level=2,
        support_reclaim_failed=True,
        distribution_risk=True,
    )

    assert decision["trigger"] is True
    assert decision["reason"] == "contextual_peak_giveback_stop"

    protected = should_trigger_contextual_peak_giveback_stop(
        highest_return_pct=0.20,
        current_return_pct=0.10,
        holding_days=12,
        has_current_buy_or_hold_signal=True,
        market_warning_level=1,
        support_reclaim_failed=False,
        distribution_risk=False,
    )

    assert protected["trigger"] is False
```

- [x] **Step 3: 实验规则**

Trigger only when all are true:

- highest floating gain `>= 12%`。
- current gain `<= 3%`。
- giveback from peak `>= 7%`。
- holding days `>= 5`。
- no current same-stock BUY/HOLD protection。
- support reclaim failed or high-level volume stall/distribution risk is visible。
- market/mainline context is not `mainline_pullback` with strong theme alignment.

Do not trigger when:

- current position is still above MA5/MA10 with synchronized volume-price rise。
- current day has a fresh same-stock buy/hold signal。
- replacement quality is clearly worse and support is still valid.

- [x] **Step 4: 验证**

Required checks:

- `002443.SZSE` `2026-05-14 -> 2026-06-04` 是否提前保护。
- `healthy_trend_winner` 桶是否被截断。
- `trend_trailing_stop` 总收益是否大幅下降。
- 排除强势行情后是否仍改善。

Promotion fail conditions:

- 全局收益下降超过 `1` 个百分点。
- `healthy_trend_winner` 样本收益下降超过 `10%`。
- 被移除赢家收益大于避免亏损收益。

## 9. Task 5: 低吸假启动观察/降权实验

**目的：** 只针对“低吸蓄势后上拉但质量差、市场未回暖、量能/收盘异常”的窄桶，验证是否可以减少 `600352.SSE`、`002240.SZSE` 这类假启动亏损。

**Files:**

- Modify: `alphaagent/server/services/backtest/schemas.py`
- Modify: `alphaagent/server/services/backtest/scoring.py`
- Modify: `alphaagent/server/services/backtest/baseline_policy.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] **Step 1: 新增默认关闭参数**

Add to `BacktestParams`:

```python
enable_low_suction_false_launch_watch_gate: bool = False
low_suction_false_launch_min_days: int = 3
low_suction_false_launch_min_warning_level: int = 2
low_suction_false_launch_max_recovery_level: int = 1
```

Add the switch to product baseline exclusions.

- [x] **Step 2: 加测试**

Add test:

```python
def test_low_suction_false_launch_watch_gate_only_blocks_weak_unrecovered_lift() -> None:
    from alphaagent.server.services.backtest.scoring import classify_low_suction_false_launch_watch

    blocked = classify_low_suction_false_launch_watch(
        low_suction_days=4,
        launch_quality_bucket="weak_volume_launch",
        close_location_in_range=0.42,
        volume_ratio_5d_20d=0.76,
        market_warning_level=2,
        market_recovery_level=1,
        recent_limit_up_20d=False,
        theme_alignment="unknown",
    )
    assert blocked["watch_only"] is True

    allowed = classify_low_suction_false_launch_watch(
        low_suction_days=4,
        launch_quality_bucket="high_close_launch",
        close_location_in_range=0.82,
        volume_ratio_5d_20d=1.35,
        market_warning_level=1,
        market_recovery_level=2,
        recent_limit_up_20d=True,
        theme_alignment="aligned",
    )
    assert allowed["watch_only"] is False
```

- [x] **Step 3: 实验规则**

When enabled, convert BUY to WATCH or subtract enough score to leave the execution pool only when all are true:

- `low_suction_days >= 3`。
- setup is `stealth_low_suction` or `low_position_reclaim` or dragon/low-suction overlap。
- launch quality is `unconfirmed_buildup`, `weak_volume_launch`, `late_pullback_launch`, or `repeated_launch`。
- close location is not high, or volume ratio is weak/dead。
- market warning level `>= 2` and recovery level `<= 1`。
- no recent limit-up/near-limit-up, no strong theme alignment, no persistent volume expansion.

Do not block:

- first balanced lift with high close and acceptable volume。
- mainline pullback with strong theme alignment。
- low-position reclaim with clear MA reclaim and broad market recovery。

- [x] **Step 4: 验证重点票**

Must check:

- `600352.SSE` `2026-03-11`: should be flagged or downgraded if visible conditions match。
- `002240.SZSE` `2026-03-11/13`: should be flagged only if current evidence is weak lift/未回暖。
- `002384.SZSE` `2026-04-01` and `2026-06-09`: should not be wrongly blocked if signal-day quality is good。
- `601179.SSE` `2026-02-25`: should not be blocked only because rank is low; it needs actual weak-lift evidence。
- `603439.SSE` `2026-05-11`: if not recognized, experiment cannot claim it fixed the issue。

Promotion fail conditions:

- Global return falls more than `1` percentage point.
- Top10/top20 excluding-strong win rate falls.
- Removed winners return exceeds avoided losers return.
- It fixes named losers only by code-specific overfitting.

## 10. Task 6: 满仓和换仓质量实验

**目的：** 只有在 missed top20 候选稳定强于当前持仓时，才考虑调整换仓；不要为了东山精密这类好票直接扩大持仓或抢名额。

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/simulation.py`
- Modify: `alphaagent/server/services/backtest/schemas.py`
- Modify: `alphaagent/server/services/backtest/baseline_policy.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] **Step 1: 增加持仓机会成本表**

Required row shape:

```json
{
  "signal_date": "2026-04-01",
  "execute_date": "2026-04-02",
  "missed_symbol": "002384.SZSE",
  "missed_rank": 3,
  "missed_score": 97.57,
  "missed_return_20d": 0.0,
  "held_symbol": "000000.SZSE",
  "held_entry_score": 89.0,
  "held_unrealized_return_pct": -1.2,
  "held_support_state": "weak",
  "rotation_score_gap": 8.57,
  "replacement_quality_delta": 4.1,
  "not_used_for_signal_score": true
}
```

- [x] **Step 2: 新增默认关闭参数**

Add to `BacktestParams`:

```python
enable_missed_candidate_quality_rotation: bool = False
missed_rotation_min_score: float = 98.0
missed_rotation_min_score_gap: float = 10.0
missed_rotation_max_held_return_pct: float = 1.0
missed_rotation_min_held_days: int = 4
```

- [x] **Step 3: 实验规则**

Allow rotation only when all are true:

- missed candidate is in execution top20 and BUY。
- score `>= missed_rotation_min_score`。
- score gap to held position `>= missed_rotation_min_score_gap`。
- held position return `<= missed_rotation_max_held_return_pct`。
- held days `>= missed_rotation_min_held_days`。
- held position has weak support or no current same-stock buy/hold signal。
- replacement candidate is not `low_suction_unconfirmed_buildup`。

Promotion fail conditions:

- 增加换仓次数但收益不升。
- 最大回撤扩大。
- 替换交易坏样本增加。
- `healthy_trend_winner` 被提前卖掉。

## 11. Task 7: 实验报告和晋升门槛

**目的：** 每个实验都必须用同一格式证明收益提升来自哪里。

**Files:**

- Create: `memory/06_backtests/YYYY-MM-DD_quant_next_experiment_report.md`
- Update: `memory/06_backtests/README.md`
- Update only if persisted experiment exists: `memory/06_backtests/strategy_optimization_ledger.md`
- Update only if durable decision changes: `memory/09_decisions/decisions.md`

- [x] **Step 1: 每个实验报告必须包含**

```text
实验参数：
是否默认关闭：
是否排除 baseline_only：
基线 vs 实验：收益、最大回撤、胜率、profit factor、Sharpe、买入/卖出/持仓中
年度分组：
市场分组：
排除强势行情：
Top10 / Top20 / Top100 候选审计：
重点股票 before/after：
support_stop 上下文变化：
replacement quality 变化：
removed winners：
avoided losers：
added losers：
是否存在未来函数：
是否可能过拟合：
结论：拒绝 / 保留默认关闭继续研究 / 允许考虑晋升
```

- [x] **Step 2: 晋升条件**

An experiment can be considered for promotion only if all are true:

- Default-off backtest improves total return or keeps return within `1` percentage point while materially improving max drawdown.
- Max drawdown does not worsen.
- Profit factor does not worsen.
- Excluding-strong-market Top10/Top20 audit does not worsen.
- At least two market buckets do not worsen.
- At least one weak/choppy/mainline-pullback bucket improves.
- Removed winner return is lower than avoided loser return.
- Replacement quality does not worsen.
- Focus-symbol fixes are explained without stock-code special cases.
- All decision fields are visible on signal day or sell decision day.

If any item fails, keep the experiment default false and write the failure reason.

## 12. Task 8: 前端整合

**目的：** 用户界面继续简单，把复杂性藏在解释面板里。

**Files:**

- Modify: `frontend/src/api/quant.ts`
- Modify: `frontend/src/features/quant/BacktestAnalysis.tsx`
- Modify: `frontend/src/features/quant/BacktestPanel.tsx`
- Modify: `frontend/src/pages/StockDetailPage.tsx`

- [ ] **Step 1: `/quant` 不新增主按钮**

Allowed display changes:

- 在现有回测分析中加“实验对比”折叠区。
- 在候选执行归因中显示 `not_filled_subreason`。
- 在卖点归因中显示 `support_stop_context`、`replacement_quality`、`removed_winner_cost`。

Not allowed:

- 新增第二套量化入口。
- 新增让用户选择一堆实验参数的普通界面。
- 把默认关闭实验展示成当前策略收益。

- [ ] **Step 2: 股票详情统一时间线**

Display rules:

- `BUY_SIGNAL`: 理论关键买点。
- `BUY_REJECTED`: 理论买拒或执行拒绝。
- `BUY_FILLED`: 真实组合成交。
- `SELL_FILLED`: 真实组合卖出。
- `BUILDUP_CLUSTER`: 低吸蓄势簇，不画成 BUY。

Click marker payload must include:

```json
{
  "score": 97.57,
  "entry_family": "low_position_reclaim",
  "low_suction_stage_label": "低吸首个有效上拉",
  "low_suction_dragon_state_label": "低吸/龙回头重叠",
  "candidate_trace_status": "planned_not_ordered",
  "not_filled_subreason": "full_position_no_rotation",
  "sell_reason": "support_stop",
  "support_stop_context": "clean_float_profit_giveback"
}
```

## 13. Task 9: 最终验证

**目的：** 确认代码、API、页面、报告一致。

- [ ] **Step 1: 后端测试**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
```

Expected:

- All tests pass.

- [ ] **Step 2: 编译检查**

Run:

```bash
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
```

Expected:

- No compile errors.

- [ ] **Step 3: 前端构建**

Run:

```bash
pnpm --dir frontend run build
```

Expected:

- Build succeeds. Existing chunk-size warnings are acceptable if no new fatal error.

- [ ] **Step 4: diff 检查**

Run:

```bash
git diff --check
```

Expected:

- No whitespace errors.

- [ ] **Step 5: Docker API 冒烟**

Run:

```bash
docker compose up -d --build alphaagent-api
curl -sS 'http://localhost:8000/api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5'
curl -sS 'http://localhost:8000/api/backtests/203/factor-audit?top_limit=100'
curl -sS 'http://localhost:8000/api/backtests/203/setup-market-exit-audit?lookahead_days=10'
curl -sS 'http://localhost:8000/api/backtests/203/strategy-timeline?vt_symbol=002384.SZSE'
```

Expected:

- Baseline remains `#203/#194` or explicitly documented successor baseline.
- New experiment runs do not appear in `baseline_only=true`.
- Attribution payload contains subreasons.
- Timeline still contains lifecycle segments.

- [ ] **Step 6: 页面烟测**

Use Playwright with Chromium `--no-sandbox` when running as root.

Required pages:

- `http://localhost:5173/quant`
- `http://localhost:5173/stocks/002384.SZSE`
- `http://localhost:5173/stocks/002443.SZSE`

Expected:

- `/quant` shows baseline result, candidate execution attribution, yearly/market evidence.
- Stock detail shows unified timeline and no dense low-suction daily BUY markers.
- No blank data state when API has data.

## 14. 执行顺序

1. Task 0：冻结基线。
2. Task 1：拆 `candidate_not_planned` 子原因。
3. Task 2：重点日期 signal-history 补证。
4. Task 3：支撑止损延迟确认实验。
5. Task 4：高浮盈回撤保护实验。
6. Task 5：低吸假启动观察/降权实验。
7. Task 6：满仓和换仓质量实验。
8. Task 7：统一实验报告和晋升门槛。
9. Task 8：前端简单展示整合。
10. Task 9：最终验证。

## 15. 成功标准

完成后必须能回答：

- 东山精密 `002384.SZSE` 的关键低吸点到底是“识别没买”还是“组合满仓/理论持仓/换仓失败”。
- `603439.SSE` `2026-05-11` 是当前策略没识别，还是缓存缺证。
- `601179.SSE` `2026-02-03` 为什么偏早，`2026-02-25` 为什么更像低吸启动但排序不足。
- `600352.SSE` 和 `002240.SZSE` 的失败是否能被低吸假启动窄桶提前标记。
- `002119.SZSE` 重复龙回头风险为什么不能直接硬拒。
- `002443.SZSE` 是否能通过高浮盈回撤保护改善，而不截断趋势赢家。
- 支撑止损里哪些应多等一次确认，哪些必须及时卖。
- 满仓错过的 top20 候选是否真的比持仓更好。
- 排除强势行情后，实验是否仍提升收益/胜率或降低回撤。
- 默认策略是否仍保持 `#203/#194` 口径，实验是否严格默认关闭。

如果以上问题不能用报告和 API 证据回答，不允许进入默认策略修改。
