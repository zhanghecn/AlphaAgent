# Formal Qualified Touch Readiness Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Repository policy forbids commits unless the user explicitly requests one, so verification checkpoints replace commit steps.

**Goal:** 研究并冻结一套只使用当前及以前信息的板前算法，估计“该股票后续真实触板且触板时通过 `limit-up-core-abc-v2` 正式质量门”的联合概率，同时给出提前时间、误报、召回和 D+1 质量证据。

**Architecture:** 新增一个与产品链隔离的研究模块，直接复用 `core_quality.public_quality_gate()` 作为唯一正式质量判定，不建立第二套板前质量门。研究分为正式标签、不可挽救母池、逐时点特征、时间切分校准和最近自然帧审计五层；概念同时计算全体指标、排除候选自身指标和候选领先度。研究未通过前不恢复板前表、任务、API、页面或买点。

**Tech Stack:** Python 3.11、SQLAlchemy/PostgreSQL、pandas/scikit-learn、pytest、Markdown/CSV 研究证据。

## Completion record

- 可用历史数据研究已于 `2026-07-29` 完成，决策为 `REJECT/INSUFFICIENT`，不是待实现的
  板前产品方案。
- 完整母池和模型消融在隔离的历史工作树执行；主分支只保留因果合同、覆盖审计、冻结证据
  验收和最终报告。由于所有概率档均未通过发布门，没有把已删除的板前产品仓储、模型、任务、
  API 或页面重新引入主分支。
- 冻结证据为 `memory/06_backtests/limit_up_formal_touch_readiness_20260728.json`；完整消融
  临时输出和因果输入分别用 SHA-256
  `9d78d1da7df788c6a795556dc7bac04733bf136a060ad55dc8713ee87d5c56a4`、
  `76ce23985e2f6ca596e61a9872cf8feace40614b9182535671ba1c97e9744729` 固定。
- 严格动态概念不是“验证失败”，而是覆盖不足：冻结切分只有 `0/0/2` 日，未达到
  `20/10/10` 日。粗行业扩散代理已经验证为负增量，不能替代严格概念。

---

### Task 1: Freeze the causal research contract

**Files:**
- Create: `alphaagent/server/services/limit_up/formal_touch_readiness.py`
- Test: `tests/alphaagent/test_limit_up_formal_touch_readiness.py`

- [x] **Step 1: Write contract tests**

```python
def test_joint_label_requires_touch_and_formal_quality() -> None:
    assert joint_event_label(later_touched=True, formal_actionable=True) == 1
    assert joint_event_label(later_touched=True, formal_actionable=False) == 0
    assert joint_event_label(later_touched=False, formal_actionable=False) == 0


def test_counterfactual_touch_uses_public_contract() -> None:
    decision = evaluate_touch_now(candidate, observed_at)
    assert decision["public_quality_contract_version"] == "limit-up-core-abc-v2"
    assert decision["public_quality_trigger_observed"] is True
```

- [x] **Step 2: Verify the tests fail before implementation**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_formal_touch_readiness.py`

Expected: import failure because the research module does not exist.

- [x] **Step 3: Implement the immutable contract**

Implement these public research functions:

```python
def joint_event_label(*, later_touched: bool, formal_actionable: bool) -> int: ...

def evaluate_touch_now(
    candidate: Mapping[str, object],
    observed_at: datetime,
    *,
    prior_ab_seen: bool = False,
    c_already_selected: bool = False,
) -> dict[str, object]: ...

def classify_quality_requirement(
    blocker_code: str,
) -> Literal["mandatory", "progressive", "trigger"]: ...
```

`evaluate_touch_now()` must copy the candidate, inject only the counterfactual current trigger time, and call `core_quality.public_quality_gate(..., trigger_observed=True)`. It must not duplicate A/B/C thresholds.

- [x] **Step 4: Run focused tests**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_formal_touch_readiness.py`

Expected: PASS.

### Task 2: Build a label-independent mother pool and point-in-time trajectories

**Files:**
- Modify: `alphaagent/server/services/limit_up/formal_touch_readiness.py`
- Create: `alphaagent/server/services/limit_up/formal_touch_readiness_repository.py`
- Test: `tests/alphaagent/test_limit_up_formal_touch_readiness.py`

- [x] **Step 1: Test mother-pool invariance and strict timing**

```python
def test_mutating_outcomes_does_not_change_mother_pool_membership() -> None:
    original = build_mother_pool(static_rows, outcomes)
    mutated = build_mother_pool(static_rows, inverted_outcomes)
    assert pool_fingerprint(original) == pool_fingerprint(mutated)


def test_point_rows_stop_before_first_touch() -> None:
    rows = build_pre_touch_rows(observations, touch_at)
    assert rows
    assert all(row["observed_at"] < touch_at for row in rows)
```

- [x] **Step 2: Implement repository reads with existing tables**

Read `limit_up_radar_frames`, `limit_up_radar_observations`, `limit_up_concept_strength_snapshots`, `stock_minute_bars` and frozen formal orders. Mother-pool membership may use only main-board/risk/data-freshness/prior-only fields known before the first `>=3%` observation. Outcome fields may be joined only after the pool fingerprint is frozen.

- [x] **Step 3: Add explicit coverage gates**

Every date must report radar-frame coverage, minute coverage, concept-membership date, concept quote coverage, formal-label coverage and whether the source is natural v2, old-frame replay or historical proxy. Dates with incomplete point-in-time concept data remain in the non-concept ablation but are excluded from strict concept validation.

- [x] **Step 4: Run focused tests and a bounded data load**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_formal_touch_readiness.py`

Run: `docker compose run --rm --no-deps -v /root/project/ai/vnpy:/app alphaagent-api python -m alphaagent.server.services.limit_up.formal_touch_readiness --audit-only`

Expected: tests pass and the command prints deterministic date/pair/row counts without writing product tables.

### Task 3: Calculate quality progress, leave-one-out concept breadth, funds and momentum

**Files:**
- Modify: `alphaagent/server/services/limit_up/formal_touch_readiness.py`
- Modify: `alphaagent/server/services/limit_up/formal_touch_readiness_repository.py`
- Test: `tests/alphaagent/test_limit_up_formal_touch_readiness.py`

- [x] **Step 1: Test leave-one-out calculations**

```python
def test_leave_one_out_removes_candidate_from_breadth() -> None:
    result = leave_one_out_concept_metrics(concept, candidate_change_pct=8.2)
    assert result["strong_5_count_ex_self"] == concept["strong_5_count"] - 1
    assert result["strong_7_count_ex_self"] == concept["strong_7_count"] - 1
    assert result["observed_count_ex_self"] == concept["observed_count"] - 1
```

- [x] **Step 2: Implement registered feature families**

Use only these pre-registered families:

```text
quality_static: A/B/C tier prior, current hypothetical formal decision, missing mandatory count,
                progressive A/B/C component count, quality win estimate, D+1 estimate
concept_full:   rank percentile, median/average change, rise ratio, strong 3/5/7 breadth,
                near-limit/touched/sealed breadth and 1/3/5-minute acceleration
concept_ex_self: observed/rise/strong/near-limit counts and rates after removing the candidate
leadership:     candidate change minus concept average/median, leader rank and rank percentile
funds:          stock and sector main net inflow ratio, current turnover acceleration,
                D-1 industry turnover ratio
momentum:       change, distance to limit, 1/3/5-minute price slope, volume/turnover slope,
                pullback from intraday high and recovery slope
market:         time bucket and D-1 market phase
```

No company name, concept name, month, result-day leader identity, future touch count or day-end concept state may enter features.

- [x] **Step 3: Mark approximate leave-one-out fields**

If persisted frames lack the member-level values needed to recompute medians, weighted scores or cross-sectional ranks exactly, retain the original value only as `*_full`, set the unavailable `*_ex_self` field to null and fail the strict concept coverage gate. Do not approximate those fields with day-end data.

- [x] **Step 4: Run unit tests**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_formal_touch_readiness.py`

Expected: PASS.

### Task 4: Fit, calibrate and validate the joint probability by date

**Files:**
- Modify: `alphaagent/server/services/limit_up/formal_touch_readiness.py`
- Test: `tests/alphaagent/test_limit_up_formal_touch_readiness.py`

- [x] **Step 1: Test chronological split isolation**

```python
def test_date_split_has_no_overlap() -> None:
    split = chronological_split(trade_dates)
    assert max(split.fit) < min(split.calibration)
    assert max(split.calibration) < min(split.validation)
```

- [x] **Step 2: Fit only interpretable baselines**

Compare preregistered ablations rather than unrestricted feature search:

```text
Q       = quality progress only
Q+M     = quality + individual momentum
Q+M+F   = quality + momentum + funds
Q+M+C   = quality + momentum + strict concept features
Q+M+F+C = full registered feature set
```

Use class-weighted logistic regression as the calibrated baseline. Fit preprocessing and model coefficients on `fit`, choose regularization and isotonic/Platt calibration on `calibration`, then freeze before `validation`. One stock/day contributes at most its earliest crossing for each threshold.

- [x] **Step 3: Freeze acceptance metrics**

For thresholds 60%, 70% and 80%, report joint-event precision, formal-touch recall, median/P25 lead time, daily visible count, false-positive count, D+1 win rate and mean D+1 net return. A threshold is product-eligible only when validation contains at least 30 earliest-crossing samples, precision is at least the displayed probability minus 5 percentage points, formal-touch recall is at least 30%, median lead time is at least 2 trading minutes, D+1 win rate is at least 60%, and mean D+1 net return is positive.

- [x] **Step 4: Add negative controls**

Repeat validation after shuffling labels within date and after removing concept/fund features. The chosen model must beat both base rate and shuffled control on Brier score and PR-AUC. Otherwise the result is rejected regardless of a favorable small threshold bucket.

- [x] **Step 5: Run model tests**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_formal_touch_readiness.py`

Expected: PASS.

### Task 5: Generate the historical and recent-natural evidence

**Files:**
- Create: `memory/06_backtests/limit_up_formal_touch_readiness_20260728.md`
- Create only when row-level evidence is available: `memory/06_backtests/limit_up_formal_touch_readiness_20260728.csv`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Run the complete read-only research command**

Run: `docker compose run --rm --no-deps -v /root/project/ai/vnpy:/app alphaagent-api python -m alphaagent.server.services.limit_up.formal_touch_readiness --output /tmp/formal-touch-readiness.json`

Expected: one JSON report containing current coverage, frozen ablations, thresholds, lead times,
formal-touch recall, D+1 outcomes and the reapplied acceptance audit. The command validates the
frozen result rather than fitting again on the already viewed validation dates, and must not write
product database tables.

- [x] **Step 2: Audit natural v2 separately**

The report must keep `2026-07-28` natural `limit-up-core-abc-v2` frames separate from `limit-up-live-v15` and v1 replay frames. Old frames may diagnose timing but never enter natural-forward performance.

- [x] **Step 3: Write conclusions without overstating missing data**

If strict concept history has fewer than 20 fit, 10 calibration and 10 validation dates, report the concept branch as insufficient. If no threshold satisfies every acceptance metric, freeze the product state as `research_only` and state the exact additional natural sample requirement.

- [x] **Step 4: Update durable memory in place**

Replace stale board-before conclusions in the research index and decisions file with the joint-target result. Keep detailed tables in the dedicated report and only link the conclusion from overview memory.

### Task 6: Verify isolation and decide the reliable product shape

**Files:**
- Test: `tests/alphaagent/test_limit_up_formal_touch_readiness.py`
- Test: `tests/alphaagent/test_limit_up_core_quality.py`
- Test: `tests/alphaagent/test_limit_up_live.py`
- Test: `tests/alphaagent/test_limit_up_scheduled_execution.py`

- [x] **Step 1: Verify no product integration exists**

Run: `rg -n "formal_touch_readiness" alphaagent/server frontend | sort`

Expected: references exist only in the research module and its tests; live recommendation, scheduling, API and frontend contain no import.

- [x] **Step 2: Run regressions**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_formal_touch_readiness.py tests/alphaagent/test_limit_up_core_quality.py tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_scheduled_execution.py`

Run: `uv run python -m compileall -q alphaagent/server/services/limit_up`

Run: `git diff --check`

Expected: all pass.

- [x] **Step 3: Publish one of two evidence-backed decisions**

```text
PASS: restore one observation-only board-before product using the shared formal gate,
      publish calibrated joint probability and quality readiness, and keep actual touch as
      the only upgrade to formal buy_now.

REJECT/INSUFFICIENT: keep the 3% raw radar and formal touch system unchanged, continue
      collecting the exact missing point-in-time fields, and do not display an invented
      60%/70%/80% probability.
```

The final answer must include the exact reason for the decision, available historical evidence, natural-forward evidence, and the shortest path to a reliable live rollout.
