# Limit-up Recognition Gate Robustness Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Repository policy forbids commits unless the user explicitly requests one; verification checkpoints replace commit steps.

**Goal:** 在不修改 `limit-up-core-abc-v2` 正式合同的前提下，验证 `prior_limit_count_126 > 6` 候选是否存在可重复、可在决策时识别的条件式救援。

**Architecture:** 新增只读研究模块，复用冻结历史、`scheduled_execution`、`core_quality` 与官方 D+1 收盘结算。研究只比较预注册的高频分组和既有 C 组件，在时间滚动 calibration 选择，在锁定 holdout 一次性验收；任何不通过的结果只产出反证报告。

**Tech Stack:** Python 3.11、pandas、PostgreSQL/SQLAlchemy、pytest、现有 `walk_forward_contract`、Markdown/JSON 证据。

---

## Completion record

- 计划创建于 `2026-07-30`，尚未执行；当前唯一正式合同仍为 `limit-up-core-abc-v2`。
- 研究不得写入 `actionable_recommendations`、`portfolio`、实时快照、API 或页面。
- 已有反证必须保留：直接放开 `>6` 的盈利门通过组为 161 笔、胜率 `46.5839%`、均值 `-0.2464%`；`>6 + repair` 在局部正式事件表现好，但在 806 日代理为 `38.4615%/-1.3171%`，不能晋级。
- 当前 C 已覆盖 `prior_limit_count_126_above_6` 的受限救援；本研究不能把 C 历史代理包装成自然前向成绩。

## Pre-registered variants

所有变体使用同一正式涨停价入场、D+1 官方收盘、费用与独立标准槽位。`2-6` 基线不参与调参。

| 名称 | 决策时资格 | 角色 |
|---|---|---|
| `baseline_2_to_6` | 当前 A/B 基座 | 对照，不可被研究结果改写 |
| `over6_existing_c` | `>6`、盈利门通过、现有 C 因果组件和时序均通过 | 唯一可晋级候选 |
| `over6_7_to_9_existing_c` | 上项且次数 `7-9` | calibration 解释性子组 |
| `over6_10_plus_existing_c` | 上项且次数 `>=10` | calibration 解释性子组 |
| `over6_repair_only_negative_control` | `>6`、盈利门通过、`prior_market_phase=repair` | 已拒绝的负对照 |

禁止新增静态概念名称、日终成员、未来收益、结果后换票，或在锁定 holdout 后增加参数。`<2` 低辨识度组不在本轮范围内，避免把不同经济假设混成一次调参。

### Task 1: Freeze the mother pool and outcome contract

**Files:**

- Create: `alphaagent/server/services/limit_up/recognition_gate_robustness.py`
- Create: `tests/alphaagent/test_limit_up_recognition_gate_robustness.py`

- [ ] **Step 1: Write causal-contract tests**

```python
def test_membership_ignores_future_return_values() -> None:
    original = build_mother_pool(_orders(), _trades([8.0, -8.0]))
    mutated = build_mother_pool(_orders(), _trades([-8.0, 8.0]))
    assert original[["signal_date", "vt_symbol"]].equals(
        mutated[["signal_date", "vt_symbol"]]
    )


def test_frequency_boundaries_are_inclusive() -> None:
    assert classify_frequency_group(6) == "2_to_6"
    assert classify_frequency_group(7) == "7_to_9"
    assert classify_frequency_group(9) == "7_to_9"
    assert classify_frequency_group(10) == "10_plus"
```

- [ ] **Step 2: Verify the tests fail before implementation**

Run:

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_recognition_gate_robustness.py
```

Expected: FAIL because the research module does not exist.

- [ ] **Step 3: Implement the immutable input builder**

```python
def build_mother_pool(
    orders: Sequence[Mapping[str, object]],
    closed_trades: Sequence[Mapping[str, object]],
) -> pd.DataFrame:
    """Join decision-time orders to official D+1 outcomes without outcome filtering."""


def classify_frequency_group(limit_count: object) -> str:
    """Return '<=1', '2_to_6', '7_to_9', '10_plus', or 'missing'."""


def is_over6_base_rejection(candidate: Mapping[str, object]) -> bool:
    """Require the exact profitability-pass and recognition-above-six state."""
```

Use `scheduled_execution.extract_scheduled_orders()` for order membership and `quality_no_trade_reverse.build_official_closed_trade_evidence()` for settlement. Do not use raw daily bars, post-close rankings, or a second entry/exit formula.

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_recognition_gate_robustness.py
```

Expected: PASS; changing D+1 outcomes affects metrics only, never membership.

### Task 2: Implement only the registered high-frequency masks

**Files:**

- Modify: `alphaagent/server/services/limit_up/recognition_gate_robustness.py`
- Modify: `tests/alphaagent/test_limit_up_recognition_gate_robustness.py`

- [ ] **Step 1: Write Causality and negative-control tests**

```python
def test_existing_c_mask_requires_causal_component_and_no_prior_ab() -> None:
    rows = [_over6_row(causal_component=True), _over6_row(prior_ab_seen=True)]
    assert variant_mask("over6_existing_c", pd.DataFrame(rows)).tolist() == [True, False]


def test_repair_only_is_never_promotable() -> None:
    result = evaluate_variant("over6_repair_only_negative_control", _frame())
    assert result["role"] == "negative_control"
    assert result["promotion_eligible"] is False
```

- [ ] **Step 2: Add fixed masks and chronological C ordering**

```python
VARIANT_NAMES = (
    "baseline_2_to_6",
    "over6_existing_c",
    "over6_7_to_9_existing_c",
    "over6_10_plus_existing_c",
    "over6_repair_only_negative_control",
)


def variant_mask(name: str, frame: pd.DataFrame) -> pd.Series:
    """Return one pre-registered decision-time membership mask."""
```

For C variants call `core_quality.c_quality_gate()` and replay the same signal-time ordering, `prior_ab_seen`, and one-C-per-day rule as `core_quality.filter_core_quality_qualified_orders()`. Strict concept components require point-in-time membership; current-membership proxy rows are reportable but cannot promote a variant.

- [ ] **Step 3: Run focused tests**

Run:

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_recognition_gate_robustness.py
```

Expected: PASS.

### Task 3: Reuse chronological windows and block-bootstrap evidence

**Files:**

- Modify: `alphaagent/server/services/limit_up/recognition_gate_robustness.py`
- Modify: `tests/alphaagent/test_limit_up_recognition_gate_robustness.py`

- [ ] **Step 1: Write time-isolation tests**

```python
def test_training_and_calibration_only_use_matured_outcomes() -> None:
    windows = build_recognition_windows(_samples(), trading_dates=_calendar())
    assert all(
        sample.result_date < window.test_start
        for window in windows
        for sample in (*window.training_samples, *window.calibration_samples)
    )


def test_locked_holdout_cannot_select_variant() -> None:
    selected = select_variant_from_calibration(_calibration_reports())
    assert selected["selection_basis"] == "calibration_only"
```

- [ ] **Step 2: Reuse the fixed chronological configuration**

```python
RESEARCH_CONFIG = WalkForwardConfig(
    training_days=252,
    calibration_days=63,
    test_days=63,
    holdout_days=120,
    bootstrap_samples=2000,
    random_seed=20260730,
)


def build_recognition_windows(
    samples: Sequence[ModelSample], *, trading_dates: Sequence[date]
) -> list[WalkForwardWindow]:
    return build_walk_forward_windows(
        samples, config=RESEARCH_CONFIG, trading_dates=trading_dates
    )
```

Do not shorten `252/63/63/120` to obtain a result. The reused splitter only permits training and calibration rows with `result_date < test_start`; insufficient variants must report `INSUFFICIENT`.

- [ ] **Step 3: Add date-block bootstrap comparison**

```python
def date_block_bootstrap_delta(
    baseline: pd.DataFrame,
    variant: pd.DataFrame,
    *,
    draws: int = 2000,
    seed: int = 20260730,
) -> dict[str, float]:
    """Resample complete signal dates and return percentile intervals of net-return deltas."""
```

Resample complete `signal_date` blocks, never individual rows, to preserve same-day dependence.

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_recognition_gate_robustness.py
```

Expected: PASS; holdout cannot affect selection and no D+1 label crosses into training.

### Task 4: Freeze acceptance gates and write read-only evidence

**Files:**

- Modify: `alphaagent/server/services/limit_up/recognition_gate_robustness.py`
- Create: `memory/06_backtests/limit_up_recognition_gate_robustness_20260730.md`
- Create: `memory/06_backtests/limit_up_recognition_gate_robustness_20260730.json`
- Modify: `memory/06_backtests/README.md`
- Test: `tests/alphaagent/test_limit_up_recognition_gate_robustness.py`

- [ ] **Step 1: Write acceptance-gate tests**

```python
def test_acceptance_requires_every_oos_and_holdout_gate() -> None:
    report = acceptance_report(
        incremental=_summary(closed=15, win_rate=60.0, mean_return=0.1),
        combined=_summary(win_rate=60.0, compound=11.0, drawdown=-8.0),
        baseline=_summary(compound=10.0, drawdown=-8.0),
        combined_two_slot_account={
            "total_return_pct": 11.0,
            "max_drawdown_pct": -8.0,
            "hard_loss_rate": 0.0,
        },
        baseline_two_slot_account={
            "total_return_pct": 10.0,
            "max_drawdown_pct": -8.0,
            "hard_loss_rate": 0.0,
        },
        added_trade_days=10,
        bootstrap={"mean_delta_lower_95": 0.01},
    )
    assert report["passed"] is True


def test_acceptance_rejects_single_trade_gain_when_two_slot_account_regresses() -> None:
    report = acceptance_report(
        incremental=_summary(closed=15, win_rate=60.0, mean_return=0.1),
        combined=_summary(win_rate=60.0, compound=11.0, drawdown=-8.0),
        baseline=_summary(compound=10.0, drawdown=-8.0),
        combined_two_slot_account={
            "total_return_pct": 9.0,
            "max_drawdown_pct": -8.0,
            "hard_loss_rate": 0.0,
        },
        baseline_two_slot_account={
            "total_return_pct": 10.0,
            "max_drawdown_pct": -8.0,
            "hard_loss_rate": 0.0,
        },
        added_trade_days=10,
        bootstrap={"mean_delta_lower_95": 0.01},
    )
    assert report["passed"] is False
```

- [ ] **Step 2: Implement the fixed promotion report**

```python
def acceptance_report(
    *,
    baseline: Mapping[str, object],
    incremental: Mapping[str, object],
    combined: Mapping[str, object],
    baseline_two_slot_account: Mapping[str, object],
    combined_two_slot_account: Mapping[str, object],
    added_trade_days: int,
    bootstrap: Mapping[str, float],
) -> dict[str, object]:
    """Return all gates; never mutate the formal contract."""
```

A candidate must pass in aggregate expanding OOS and again in locked holdout: at least 15 incremental closed trades and 10 added days; incremental and combined win rate at least 60%; positive incremental mean return; higher combined daily equal-weight compound return; no worse drawdown or hard-loss rate; and a positive 95% date-block bootstrap lower bound for incremental mean-return delta. In addition, replay the baseline and selected variant with `cash_backtest.simulate_limit_up_account()` using the same post-`filter_core_quality_qualified_orders()` signal order, official bars, official trading calendar, `next_close`, and `CashBacktestConfig(initial_cash=100_000, max_positions=2)`. The combined two-slot account must have a higher `total_return_pct` and no worse `max_drawdown_pct` or `hard_loss_rate`; this prevents a high-frequency candidate from crowding out later A-tier entries. The negative control must remain rejected.

- [ ] **Step 3: Add a research-only CLI**

```bash
docker compose --profile research run --rm --no-deps -v "$PWD:/workspace" -w /workspace \
  alphaagent-research python -m alphaagent.server.services.limit_up.recognition_gate_robustness \
  --start 2023-03-28 --end 2026-07-29 \
  --json-output memory/06_backtests/limit_up_recognition_gate_robustness_20260730.json \
  --markdown-output memory/06_backtests/limit_up_recognition_gate_robustness_20260730.md
```

The CLI may read PostgreSQL and write only its requested evidence artifacts. It must not call scheduler registration, live refresh routes, `save_snapshot()`, or any order API.

- [ ] **Step 4: Verify isolation and report content**

Run:

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_recognition_gate_robustness.py
uv run --group server pytest -q tests/alphaagent/test_limit_up_*.py
uv run python -m compileall -q alphaagent/server/services/limit_up
git diff --check
```

Expected: PASS. The report must record source range, input fingerprint, variant registry, fold metrics, holdout metrics, independent-signal and two-slot-account metrics, bootstrap intervals, failures, and `REJECT`/`INSUFFICIENT`/`SHADOW_ONLY`.

### Task 5: Require natural forward evidence before a separate promotion plan

**Files:**

- Create: `memory/06_backtests/limit_up_recognition_gate_forward_20260730.md`
- Modify only after all gates pass: `alphaagent/server/services/limit_up/core_quality.py`
- Test only after all gates pass: `tests/alphaagent/test_limit_up_core_quality.py`

- [ ] **Step 1: Start shadow-only collection**

Record a possible high-frequency rescue beside v2 as `research_only`. It must not affect real-time recommendations, portfolio capacity, or historical v2 metrics.

- [ ] **Step 2: Freeze natural-forward acceptance before observing outcomes**

Require at least 15 incremental closed trades, 10 added trade days, 60 new trading days, two market phases, combined and incremental win rate at least 60%, positive incremental mean return, higher combined compound return, and no worse drawdown or hard-loss rate. The same candidate must also improve the two-slot cash account's total return without worsening its drawdown or hard-loss rate.

- [ ] **Step 3: Prepare a separate promotion proposal only after passing**

Any production change needs a new contract version, preserves v2 history unchanged, adds regression coverage for `6/7/9/10` boundaries and same-day A/C/B ordering, and requires explicit user approval before deployment.

## Self-review

- The scope is only the high-frequency `>6` rescue question. It does not retune the lower boundary, B entry time, exit, concept names, or portfolio capacity.
- Every selectable rule uses data known by the signal. D+1 outcomes are only used after membership and time windows are frozen.
- Existing proxy contradictions, the rejected repair-only rule, and current C forward uncertainty remain part of the report rather than being discarded.
- Any failed historical or forward gate leaves `limit-up-core-abc-v2` unchanged.
