# Limit-up Recognition Gate Reverse Daily Winner Research Implementation Plan

> **For agentic workers:** Execute this research plan inline, task by task. The repository policy forbids commits unless the user explicitly requests one; verification checkpoints replace commit steps.

**Goal:** 在不改动 `limit-up-core-abc-v2` 的前提下，移除半年触板次数门作为研究反事实，逐日审计 D+1 高收益赢家，并分批比较原 `2-6` 门的真实覆盖与风险代价。

**Architecture:** 复用 `quality_opportunity_reverse` 的正式首板/二进三母池、正式涨停价入场和 D+1 官方收盘。新分析只把 `profitability_gate_passed` 作为“移除次数门后”的研究母池，其余决策时条件不变；D+1 收益只作标签。独立 CLI 仅从历史数据库读数据，写入 Markdown/JSON 证据，不触及实时推荐、账户或策略合同。

**Tech Stack:** Python 3.11、pandas、pytest、PostgreSQL/SQLAlchemy、Docker Compose `alphaagent-research`。

---

## Fixed definitions

| 项目 | 固定定义 |
|---|---|
| 反事实母池 | `profitability_gate_passed is True`；只移除 `prior_limit_count_126` 的 `2-6` 识别门 |
| 原门通过 | `recognition_gate_passed is True`，即次数在 `2-6` 内 |
| 原门增量 | 反事实母池中原门未通过的候选；`<=1`、`7-9`、`>=10`、次数缺失分别报告 |
| 高收益标签 | D+1 官方净收益 `return_pct >= 5.0`；`>=8.0` 仅作既有敏感性标签 |
| 日级账本 | 每日保留全部 `>=5%` 候选，按 D+1 收益排序并标记每日最高者；账本只用于逆向发现 |
| 分批核查 | 固定 `2025`、`2026_01_02`、`2026_03_07` 三个既有时间批次；所有分桶均报告，不按结果删桶 |

禁止使用高收益标签、日终概念、未来价格或“当天最终第一名”决定任何候选的成员资格。任何结果均为 `reverse_discovery_only`，不能改变正式门或实时推荐。

## Execution record

- 已于 `2026-07-30` 完成：新研究模块、逐日赢家账本、分桶/分期报告和隔离容器回放均已执行。
- 产物为 `memory/06_backtests/limit_up_recognition_gate_reverse_daily_winner_20260730.md` 和 `.json`；结论为 `reverse_discovery_only`，不修改 `core_quality.py` 或正式 `v2` 合同。

### Task 1: Lock the no-frequency counterfactual and outcome isolation

**Files:**

- Modify: `alphaagent/server/services/limit_up/quality_opportunity_reverse.py`
- Modify: `tests/alphaagent/test_limit_up_quality_opportunity_reverse.py`

- [x] **Step 1: Add failing membership-isolation tests**

```python
def test_frequency_gate_removed_pool_uses_only_profitability_state() -> None:
    frame = build_opportunity_reverse_frame(
        [_order("600001.SSE", limit_count=8, sample_count=5, combined_rate=40)],
        [_trade("600001.SSE", 8.0)],
    )
    changed_outcome = build_opportunity_reverse_frame(
        [_order("600001.SSE", limit_count=8, sample_count=5, combined_rate=40)],
        [_trade("600001.SSE", -8.0)],
    )
    assert frequency_gate_removed_mask(frame).tolist() == [True]
    assert frequency_gate_removed_mask(changed_outcome).tolist() == [True]
```

- [x] **Step 2: Implement the fixed research masks**

```python
def frequency_gate_removed_mask(frame: pd.DataFrame) -> pd.Series:
    """Keep only profitability-qualified rows after removing the count gate."""


def frequency_gate_delta_mask(frame: pd.DataFrame) -> pd.Series:
    """Return profitability-qualified rows rejected only by the count gate."""
```

`frequency_gate_removed_mask()` must read only `profitability_gate_passed`. `frequency_gate_delta_mask()` must be the intersection of that mask and the negation of `recognition_gate_passed`; no return field may appear in either expression.

- [x] **Step 3: Run the focused tests**

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_quality_opportunity_reverse.py
```

Expected: PASS; reversing D+1 returns changes labels but not either membership mask.

### Task 2: Build daily high-return ledger and count-bucket comparisons

**Files:**

- Modify: `alphaagent/server/services/limit_up/quality_opportunity_reverse.py`
- Modify: `tests/alphaagent/test_limit_up_quality_opportunity_reverse.py`

- [x] **Step 1: Add failing daily-ledger tests**

```python
def test_daily_high_return_ledger_keeps_all_same_day_winners() -> None:
    frame = build_opportunity_reverse_frame(
        [
            _order("600001.SSE", limit_count=4, sample_count=5, combined_rate=40),
            _order("600002.SSE", limit_count=8, sample_count=5, combined_rate=40),
        ],
        [_trade("600001.SSE", 6.0), _trade("600002.SSE", 8.0)],
    )
    ledger = build_daily_high_return_winner_ledger(frame)
    assert ledger[["daily_high_return_rank", "frequency_gate_passed"]].to_dict("records") == [
        {"daily_high_return_rank": 1, "frequency_gate_passed": False},
        {"daily_high_return_rank": 2, "frequency_gate_passed": True},
    ]
```

- [x] **Step 2: Implement the immutable daily audit**

```python
def build_daily_high_return_winner_ledger(
    frame: pd.DataFrame,
    *,
    high_return_pct: float = HIGH_RETURN_PCT,
) -> pd.DataFrame:
    """Return all post-settlement high-return labels by day, never a selection rule."""


def evaluate_frequency_gate_reverse(frame: pd.DataFrame) -> dict[str, object]:
    """Compare the frozen count gate with a research-only removed-gate counterfactual."""
```

The ledger must add `frequency_group`, `frequency_gate_passed`, `daily_high_return_rank`, and `daily_high_return_count`. `frequency_group` uses the existing bins `<=1`, `2-3`, `4-6`, `7-9`, `10+`, and `missing`. It must first apply `frequency_gate_removed_mask()`, then the D+1 label, sort by `trade_date`, descending `return_pct`, ascending `vt_symbol`, and keep every matching candidate.

`evaluate_frequency_gate_reverse()` must emit all of the following for the full sample and each fixed time batch: original-gate summary, removed-gate incremental summary, each count-bucket summary, D+1 positive-rate, `>=5%` hit rate, `>=8%` hit rate, average return, hard-loss rate, number of candidate days, number of high-return days, and daily-top-winner capture by the original gate. It must report `INSUFFICIENT` for a bucket with fewer than 15 closed rows and must not choose a preferred bucket.

- [x] **Step 3: Run the focused tests**

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_quality_opportunity_reverse.py
```

Expected: PASS; a daily ledger contains every high-return row, including winners rejected by the original gate.

### Task 3: Add a read-only research entrypoint and durable evidence

**Files:**

- Create: `alphaagent/server/services/limit_up/recognition_gate_reverse_discovery.py`
- Create: `tests/alphaagent/test_limit_up_recognition_gate_reverse_discovery.py`
- Create: `memory/06_backtests/limit_up_recognition_gate_reverse_daily_winner_20260730.json`
- Create: `memory/06_backtests/limit_up_recognition_gate_reverse_daily_winner_20260730.md`
- Modify: `memory/06_backtests/README.md`

- [x] **Step 1: Add a pure rendering test**

```python
def test_rendered_report_marks_daily_winners_as_reverse_discovery_only() -> None:
    markdown = render_markdown({
        "status": "reverse_discovery_only",
        "high_return_pct": 5.0,
        "time_batches": {},
        "daily_high_return_winners": [],
    })
    assert "不构成可交易规则" in markdown
```

- [x] **Step 2: Implement the loader, report renderer, and CLI**

```python
def run_research(*, start: date, end: date) -> dict[str, object]:
    """Load the frozen history ledger and return the reverse-only frequency audit."""


def render_markdown(result: Mapping[str, object]) -> str:
    """Render fixed batch comparisons and daily winner evidence."""
```

`run_research()` must use `history_repository.load_history_range()`, `scheduled_execution.extract_scheduled_orders()`, `first_board_stock_gene_research.attach_prior_stock_gene_evidence_to_orders()`, `history_repository.load_account_daily_bars()`, and `quality_no_trade_reverse.build_official_closed_trade_evidence()` before calling `build_opportunity_reverse_frame()` and `evaluate_frequency_gate_reverse()`. It must set `status` to `reverse_discovery_only`, include the requested date range and input counts, and never call scheduler registration, snapshot persistence, recommendation storage, or order APIs.

- [x] **Step 3: Run the read-only report**

```bash
docker compose --profile research run --rm --no-deps -v "$PWD:/workspace" -w /workspace \
  alphaagent-research python -m alphaagent.server.services.limit_up.recognition_gate_reverse_discovery \
  --start 2023-03-28 --end 2026-07-29 \
  --json-output memory/06_backtests/limit_up_recognition_gate_reverse_daily_winner_20260730.json \
  --markdown-output memory/06_backtests/limit_up_recognition_gate_reverse_daily_winner_20260730.md
```

Expected: JSON and Markdown contain all count buckets, all three time batches, and daily high-return winners; neither file claims a production promotion.

### Task 4: Verify isolation and record the decision boundary

**Files:**

- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md` only if the report proves a new durable limitation

- [x] **Step 1: Run verification**

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_quality_opportunity_reverse.py tests/alphaagent/test_limit_up_recognition_gate_reverse_discovery.py
uv run python -m compileall -q alphaagent/server/services/limit_up
git diff --check
```

Expected: PASS. Existing `core_quality.py` remains unchanged.

- [x] **Step 2: Record the result without turning a label into a rule**

The evidence index must link the two artifacts and state whether the original `2-6` gate captures or misses daily high-return labels. Any count bucket that looks favorable in one batch but fails another remains `REJECT`; a favorable result in every historical batch remains `SHADOW_ONLY` until natural-forward criteria are separately frozen and met.

## Self-review

- The study removes one condition only in a read-only counterfactual; it does not change entry timing, exits, stock-gene criteria, C rescue ordering, capacity, or the formal strategy version.
- Every selected daily winner is selected after D+1 settlement and is explicitly marked non-actionable.
- Comparisons retain all candidates and all count buckets, so daily “top” outcomes cannot hide same-day losing alternatives.
- The report distinguishes retrospective hit coverage from a forward-valid trading rule.
