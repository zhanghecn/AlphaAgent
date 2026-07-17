# AlphaAgent 银状态恢复金研究实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改生产 v9 的前提下，构造三个因果恢复金研究版本，并用持续状态、逐银区间和逐区间留一结果决定是否存在值得前向观察的银转金规则。

**Architecture:** `backtest.py` 承担纯研究状态构造和区间评估，复用现有 `TimingSignal` 与状态回测口径；评估脚本把 v9 与 R1/R2/R3 放在相同真实数据上比较；生产 `signal.py`、panel API、前端和数据库均不改动。

**Tech Stack:** Python 3.13、dataclass、pytest、PostgreSQL 真实行情、现有 Docker Compose。

---

### Task 1: 固定恢复金候选和确认行为

**Files:**
- Modify: `tests/alphaagent/services/market_timing/test_market_timing_backtest.py`

- [x] **Step 1: 增加银事件测试帮助函数**

在现有 `_event` 后增加明确方向和 setup 的帮助函数，避免每个测试手写完整数据类：

```python
def _silver_event(
    trade_date: date,
    confirm_date: date,
) -> sig.TimingSignal:
    return replace(
        _event(trade_date, sig.STATUS_CONFIRMED, confirm_date),
        direction="SILVER",
        bull_force=40.0,
        bear_force=70.0,
        phase="retreat",
        setup_type=sig.SETUP_TOP_SILVER,
    )
```

- [x] **Step 2: 添加 R1/R2/R3 参数化测试**

用至少 8 根可手算 bar，先在第 2 根确认基础银，再让第 6 根分别满足 R1、R2、
R3，第 7 根满足统一确认条件。断言候选和确认日、setup、状态及逐日方向：

```python
@pytest.mark.parametrize(
    ("variant", "candidate_factor"),
    [
        (bt.RECOVERY_R1_REPAIR, {"bull": 50.0, "bear": 60.0, "mom_5d": -1.0, "above_ma20": False}),
        (bt.RECOVERY_R2_BULL_CROSS, {"bull": 60.0, "bear": 50.0, "mom_5d": 1.0, "above_ma20": False}),
        (bt.RECOVERY_R3_MA20, {"bull": 60.0, "bear": 50.0, "mom_5d": 1.0, "above_ma20": True}),
    ],
)
def test_recovery_gold_variants_confirm_only_after_broad_follow_through(
    variant: str,
    candidate_factor: dict[str, float | bool],
) -> None:
    bars = _bars(
        [100.0, 99.0, 98.0, 97.0, 96.0, 98.0, 99.0, 100.0],
        [0.1, 0.1, 0.1, 0.1, 0.1, 0.6, 0.6, 0.6],
    )
    factors = [
        _factor(
            bar.trade_date,
            bull=40.0,
            bear=70.0,
            mom_5d=-1.0,
            above_ma20=False,
        )
        for bar in bars
    ]
    factors[5] = _factor(bars[5].trade_date, **candidate_factor)
    factors[6] = _factor(
        bars[6].trade_date,
        bull=60.0,
        bear=50.0,
        mom_5d=1.0,
        above_ma20=True,
    )
    silver = _silver_event(bars[0].trade_date, bars[1].trade_date)
    result = bt.build_recovery_gold_state(factors, bars, [silver], variant=variant)
    event = result["events"][0]
    assert (event.trade_date, event.confirm_date, event.status) == (
        bars[5].trade_date,
        bars[6].trade_date,
        sig.STATUS_CONFIRMED,
    )
    assert event.setup_type == bt.SETUP_RECOVERY_GOLD
    assert result["directions"][1:6] == ["SILVER"] * 5
    assert result["directions"][6:] == ["GOLD"] * 2
```

测试只替换候选日与确认日的 bearish 默认 factors，不能依赖未来标签帮助触发。

- [x] **Step 3: 添加确认否决和输入守护测试**

分别让 `t+1` 收跌、参与度缺失、多头未反超，断言候选为 `INVALIDATED` 且方向
保持银。另断言未知 variant、长度不一致和日期错位抛 `ValueError`。

- [x] **Step 4: 运行测试确认接口缺失**

```bash
uv run --group server pytest \
  tests/alphaagent/services/market_timing/test_market_timing_backtest.py \
  -q -k recovery_gold
```

Expected: 因缺少 `RECOVERY_R*`、`SETUP_RECOVERY_GOLD` 和构造函数失败。

### Task 2: 实现因果恢复金研究状态

**Files:**
- Modify: `alphaagent/server/services/market_timing/backtest.py`
- Test: `tests/alphaagent/services/market_timing/test_market_timing_backtest.py`

- [x] **Step 1: 增加固定研究常量**

从 `signal` 的现有导入中同时引入 `STATUS_INVALIDATED` 和 `STATUS_PENDING`，再增加：

```python
SETUP_RECOVERY_GOLD = "RECOVERY_GOLD"
RECOVERY_R1_REPAIR = "R1_REPAIR"
RECOVERY_R2_BULL_CROSS = "R2_BULL_CROSS"
RECOVERY_R3_MA20 = "R3_MA20"
RECOVERY_VARIANTS = (
    RECOVERY_R1_REPAIR,
    RECOVERY_R2_BULL_CROSS,
    RECOVERY_R3_MA20,
)
RECOVERY_UP_RATIO_MIN = 0.50
RECOVERY_BEAR_MAX = 65.0


def _recovery_grade(bull_force: float) -> str:
    if bull_force >= 72.0:
        return "STRONG"
    if bull_force >= 66.0:
        return "MEDIUM"
    return "WEAK"
```

- [x] **Step 2: 实现当日候选判断**

增加 `_matches_recovery_gold`，只读当前索引及以前数据。R1 使用 MA5、参与度和
`bear<65`；R2 使用 MA5、参与度、正 5 日动量和多头反超；R3 使用
`factor.close_above_ma20` 代替 MA5，其余与 R2 相同。

```python
def _matches_recovery_gold(
    variant: str,
    factor: MarketTimingFactors,
    series: list[CompositeBar],
    index: int,
) -> bool:
    up_ratio = series[index].up_ratio
    if up_ratio is None or up_ratio < RECOVERY_UP_RATIO_MIN:
        return False
    closes = [bar.close for bar in series[: index + 1]]
    above_ma5 = len(closes) >= 5 and closes[-1] > sum(closes[-5:]) / 5
    if variant == RECOVERY_R1_REPAIR:
        return above_ma5 and factor.bear_force < RECOVERY_BEAR_MAX
    common = (
        factor.mom_5d is not None
        and factor.mom_5d > 0
        and factor.bull_force >= factor.bear_force
    )
    return common and (
        above_ma5
        if variant == RECOVERY_R2_BULL_CROSS
        else factor.close_above_ma20
    )
```

- [x] **Step 3: 实现统一次日确认**

```python
def _recovery_gold_confirmed(
    factors: list[MarketTimingFactors],
    series: list[CompositeBar],
    candidate_index: int,
) -> bool:
    confirm_index = candidate_index + 1
    if confirm_index >= len(series):
        return False
    up_ratio = series[confirm_index].up_ratio
    factor = factors[confirm_index]
    return bool(
        series[confirm_index].close > series[candidate_index].close
        and up_ratio is not None
        and up_ratio >= RECOVERY_UP_RATIO_MIN
        and factor.bull_force >= factor.bear_force
    )
```

基础 v9 在确认日存在任何已确认事件时优先，恢复候选不能与其争夺方向。

- [x] **Step 4: 实现 `build_recovery_gold_state`**

函数返回 `{"directions": list[str], "events": list[TimingSignal]}`。逐日先应用基础
确认事件，再应用上一日恢复确认，最后仅在活动方向仍为银且恢复区从假变真时记录
候选。末日候选为 `PENDING`；其余按次日条件记 `CONFIRMED/INVALIDATED`。

```python
def build_recovery_gold_state(
    factors: list[MarketTimingFactors],
    series: list[CompositeBar],
    base_events: list[TimingSignal],
    *,
    variant: str,
) -> dict:
    if variant not in RECOVERY_VARIANTS:
        raise ValueError(f"unknown recovery variant: {variant}")
    if len(factors) != len(series):
        raise ValueError("factors 与 series 长度必须一致")
    if any(
        factor.trade_date != bar.trade_date
        for factor, bar in zip(factors, series, strict=True)
    ):
        raise ValueError("factors 与 series 日期必须对齐")

    base_by_confirm = {
        event.confirm_date: event.direction
        for event in base_events
        if event.status == STATUS_CONFIRMED
        and event.confirm_date is not None
        and event.direction in {"GOLD", "SILVER"}
    }
    recovery_by_confirm: dict[date, bool] = {}
    recovery_events: list[TimingSignal] = []
    directions: list[str] = []
    active = "NEUTRAL"
    recovery_zone = False

    for index, (factor, bar) in enumerate(zip(factors, series, strict=True)):
        base_direction = base_by_confirm.get(bar.trade_date)
        if base_direction is not None:
            active = base_direction
        elif recovery_by_confirm.get(bar.trade_date):
            active = "GOLD"

        if base_direction is not None:
            recovery_zone = False
            directions.append(active)
            continue

        matches = active == "SILVER" and _matches_recovery_gold(
            variant,
            factor,
            series,
            index,
        )
        entered = matches and not recovery_zone
        recovery_zone = matches if active == "SILVER" else False
        if entered:
            confirm_index = index + 1
            if confirm_index >= len(series):
                status = STATUS_PENDING
                confirm_date = None
            else:
                confirm_date = series[confirm_index].trade_date
                blocked = confirm_date in base_by_confirm
                confirmed = not blocked and _recovery_gold_confirmed(
                    factors,
                    series,
                    index,
                )
                status = STATUS_CONFIRMED if confirmed else STATUS_INVALIDATED
                if confirmed:
                    recovery_by_confirm[confirm_date] = True
            recovery_events.append(
                TimingSignal(
                    trade_date=bar.trade_date,
                    direction="GOLD",
                    status=status,
                    grade=_recovery_grade(factor.bull_force),
                    bull_force=factor.bull_force,
                    bear_force=factor.bear_force,
                    phase=factor.phase,
                    setup_type=SETUP_RECOVERY_GOLD,
                    confirm_date=confirm_date,
                    reasons=[f"variant={variant}", status],
                )
            )
        directions.append(active)

    return {"directions": directions, "events": recovery_events}
```

实现必须保持事件存在性只取决于候选日；次日只决定 status 和 confirm_date。

- [x] **Step 5: 运行恢复金测试**

Expected: Task 1 新测试全部 PASS。

### Task 3: 固定去重、优先级和前缀稳定

**Files:**
- Modify: `tests/alphaagent/services/market_timing/test_market_timing_backtest.py`
- Modify: `alphaagent/server/services/market_timing/backtest.py`

- [x] **Step 1: 添加恢复区去重测试**

构造连续三日满足 R2、首个候选次日否决的序列，断言连续恢复区只有一个候选；
条件先离开再重新进入后才出现第二个候选。

- [x] **Step 2: 添加基础事件优先级测试**

让恢复候选确认日同时存在基础确认银，断言恢复事件不确认且活动方向为银；让基础
确认金先到达，断言当日不再新建恢复候选。

- [x] **Step 3: 添加银状态限定测试**

同样的 R1/R2/R3 因子出现在 `NEUTRAL` 或 `GOLD` 时不得生成恢复事件。

- [x] **Step 4: 添加前缀和未来污染测试**

先对候选日截断，断言末日事件为 `PENDING`；追加确认日后只改变该事件状态并从
确认日切金。把确认日之后的 bar、factor 和参与度改成极端值，历史前缀必须不变。

- [x] **Step 5: 运行全部市场择时后端测试**

```bash
uv run --group server pytest \
  tests/alphaagent/services/market_timing/test_market_timing_backtest.py \
  tests/alphaagent/services/market_timing/test_market_timing_no_lookahead.py \
  tests/alphaagent/services/market_timing/test_market_timing_intraday.py -q
```

Expected: PASS，生产 v9 测试签名不变。

### Task 4: 实现逐银区间和留一评估

**Files:**
- Modify: `alphaagent/server/services/market_timing/backtest.py`
- Modify: `tests/alphaagent/services/market_timing/test_market_timing_backtest.py`

- [x] **Step 1: 提取带索引的方向区间**

增加 `_direction_run_ranges(directions)`，输出 `(direction, start_index, end_index)`；
让现有 `_state_run_summary` 复用它，保持原统计不变。

- [x] **Step 2: 添加逐银区间结果测试**

构造两个基础银区间：一个恢复确认后 5 日上涨，另一个确认后 5 日下跌。断言第一
个为 `IMPROVED`，第二个为 `FALSE_RECOVERY`，不足 5 日为 `IMMATURE`。

- [x] **Step 3: 实现 `evaluate_recovery_gold_runs`**

```python
def evaluate_recovery_gold_runs(
    base_directions: list[str],
    recovery_events: list[TimingSignal],
    series: list[CompositeBar],
) -> list[dict]:
    if len(base_directions) != len(series):
        raise ValueError("base_directions 与 series 长度必须一致")
    index_by_date = {
        bar.trade_date: index
        for index, bar in enumerate(series)
    }
    confirmed_dates = sorted(
        event.confirm_date
        for event in recovery_events
        if event.status == STATUS_CONFIRMED and event.confirm_date is not None
    )
    rows: list[dict] = []
    for direction, start, end in _direction_run_ranges(base_directions):
        if direction != "SILVER":
            continue
        start_date = series[start].trade_date
        end_date = series[end].trade_date
        recovery_date = next(
            (
                value
                for value in confirmed_dates
                if start_date <= value <= end_date
            ),
            None,
        )
        recovery_index = index_by_date.get(recovery_date)
        if recovery_index is None:
            outcome = "NO_RECOVERY"
            return_5d = None
            advanced_days = 0
        elif recovery_index + 5 >= len(series):
            outcome = "IMMATURE"
            return_5d = None
            advanced_days = end - recovery_index + 1
        else:
            return_5d = (
                series[recovery_index + 5].close
                / series[recovery_index].close
                - 1.0
            ) * 100.0
            outcome = "IMPROVED" if return_5d > 0 else "FALSE_RECOVERY"
            advanced_days = end - recovery_index + 1
        rows.append(
            {
                "run_start": start_date,
                "run_end": end_date,
                "open_run": end == len(series) - 1,
                "recovery_confirm_date": recovery_date,
                "advanced_days": advanced_days,
                "return_5d": return_5d,
                "outcome": outcome,
            }
        )
    return rows
```

每行固定输出基础银起止、是否开放、首个确认恢复日、提前交易日数、确认后 5 日
收益和 `IMPROVED/FALSE_RECOVERY/IMMATURE/NO_RECOVERY`。

- [x] **Step 4: 添加逐区间留一测试**

用两个银区间构造不同收益，断言每次删除的日期属于正确基础区间，且 base/candidate
的 5 日命中率、平均收益和 `3%` 不利来自剩余日期。

- [x] **Step 5: 实现 `evaluate_silver_run_leave_one_out`**

```python
def evaluate_silver_run_leave_one_out(
    base_directions: list[str],
    candidate_directions: list[str],
    series: list[CompositeBar],
) -> list[dict]:
    if len(base_directions) != len(series) or len(candidate_directions) != len(series):
        raise ValueError("方向序列与 series 长度必须一致")
    if not series:
        return []
    rows: list[dict] = []
    for direction, start, end in _direction_run_ranges(base_directions):
        if direction != "SILVER":
            continue
        omitted = set(range(start, end + 1))
        base_filtered = [
            "NEUTRAL" if index in omitted else value
            for index, value in enumerate(base_directions)
        ]
        candidate_filtered = [
            "NEUTRAL" if index in omitted else value
            for index, value in enumerate(candidate_directions)
        ]
        reports = {
            "base": evaluate_direction_states(
                base_filtered,
                series,
                split_date=series[0].trade_date,
            ),
            "candidate": evaluate_direction_states(
                candidate_filtered,
                series,
                split_date=series[0].trade_date,
            ),
        }
        metrics: dict[str, object] = {
            "omitted_start": series[start].trade_date,
            "omitted_end": series[end].trade_date,
        }
        for name, report in reports.items():
            bucket = next(
                (
                    item
                    for item in report["buckets"]
                    if item.period == "ALL"
                    and item.direction == "SILVER"
                    and item.horizon == 5
                ),
                None,
            )
            metrics[f"{name}_count"] = bucket.count if bucket else 0
            metrics[f"{name}_hit_rate"] = bucket.hit_rate if bucket else None
            metrics[f"{name}_avg_return"] = bucket.avg_return if bucket else None
            metrics[f"{name}_adverse_3pct_rate"] = (
                bucket.adverse_3pct_rate if bucket else None
            )
        rows.append(metrics)
    return rows
```

对每个基础银区间，把该区间日期在两个方向序列中临时置为 `NEUTRAL`，复用
`evaluate_direction_states` 提取 `ALL/SILVER/5d` 指标，不修改输入列表。

- [x] **Step 6: 运行状态评估测试**

Expected: 新旧状态评估测试全部 PASS。

### Task 5: 扩展真实数据实验

**Files:**
- Modify: `scripts/market_timing_eval.py`

- [x] **Step 1: 构造四个恢复版本**

保留现有 v8/v9/波动迟滞输出，另外从 `V9_CURRENT` 基础事件构造
`R1_REPAIR/R2_BULL_CROSS/R3_MA20`。断言方向长度与 bar 完全一致。

- [x] **Step 2: 打印恢复候选和运行摘要**

为每个版本输出候选/确认/否决数量、最新方向、金银覆盖、转换和短区间。

- [x] **Step 3: 打印状态核心门槛**

输出 `ALL/EARLY/LATE` 的 5 日金银指标、全样本银 10 日指标、最坏反弹和
`3%` 不利比例，并逐条打印设计门槛是否通过。

- [x] **Step 4: 打印逐银区间和留一结果**

逐版本列出 5 个基础银区间的恢复分类，再列出每个 leave-one-run-out fold 相对
v9 的银 5 日平均收益和 `3%` 不利差值。

- [x] **Step 5: 运行真实脚本**

```bash
docker compose exec -T alphaagent-api python - < scripts/market_timing_eval.py
```

Expected: v9 仍为 65 个候选、42 个确认、最新银；随后出现 R1/R2/R3 完整对照，
数据库不发生写入。

### Task 6: 写入证据并完成回归

**Files:**
- Create: `memory/06_backtests/market_timing_recovery_gold_validation_2026_07_15.md`
- Modify: `memory/07_market_timing/market_timing_design.md`
- Modify: `requirements/alphaagent_market_timing_recovery_gold_research_implementation_plan.md`

- [x] **Step 1: 写入完整真实报告**

记录数据区间、固定三候选、候选事件、四版本状态表、逐银区间、留一结果、每项
决策门槛、样本限制和接受/拒绝结论。失败指标不得省略。

- [x] **Step 2: 更新市场择时概览**

只记录当前结论、生产是否改变、验证命令及详细报告链接；不复制长表。

- [x] **Step 3: 最终验证**

```bash
uv run --group server pytest \
  tests/alphaagent/services/market_timing/test_market_timing_backtest.py \
  tests/alphaagent/services/market_timing/test_market_timing_no_lookahead.py \
  tests/alphaagent/services/market_timing/test_market_timing_intraday.py -q
uvx ruff check --ignore E702 \
  alphaagent/server/services/market_timing/backtest.py \
  tests/alphaagent/services/market_timing/test_market_timing_backtest.py \
  scripts/market_timing_eval.py
pnpm --dir frontend test
pnpm --dir frontend run build
git diff --check
```

- [x] **Step 4: 提交**

只暂存本计划列出的市场择时文件，不纳入并行 `limit_up`、memory 或 requirements
改动：

```bash
git add -- \
  alphaagent/server/services/market_timing/backtest.py \
  tests/alphaagent/services/market_timing/test_market_timing_backtest.py \
  scripts/market_timing_eval.py \
  memory/06_backtests/market_timing_recovery_gold_validation_2026_07_15.md \
  memory/07_market_timing/market_timing_design.md \
  requirements/alphaagent_market_timing_recovery_gold_research_implementation_plan.md
git commit -m "test(market-timing): evaluate silver recovery gold"
```
