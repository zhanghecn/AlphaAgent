# Limit-up Recognition Gate Window Grid Research Implementation Plan

> **For agentic workers:** Execute this research plan inline, task by task. Repository policy forbids commits unless the user explicitly requests one; verification checkpoints replace commit steps.

**Goal:** 在不修改 `limit-up-core-abc-v2` 的前提下，比较 2/3/6 个月（42/63/126 交易日）和触板次数 `1..10` 的全部连续区间，找出是否存在跨时间段稳定的识别门候选。

**Architecture:** 新增只读网格研究模块，复用冻结历史候选、同股盈利门、官方日线、正式涨停价入场和 D+1 官方收盘。它只替换 A+B 基座中的“过去窗口内封板次数区间”，不改变 C、入场时点、退出、候选排序或真实推荐。所有组合先在固定的早期段选择，再独立报告后段；完整结果和所有被拒组合都写入证据。

**Tech Stack:** Python 3.11、pandas、NumPy、PostgreSQL/SQLAlchemy、pytest、Docker Compose `alphaagent-research`。

---

## Fixed research contract

| 项目 | 固定定义 |
|---|---|
| 母池 | `scheduled_execution.extract_scheduled_orders()` 后，复用 `first_board_profitability_gate()`；仅保留 `profitability_gate_passed=True` 的 A+B 反事实母池。首板保留同股盈利门，二进三因原合同不适用该门而自然通过。 |
| 计数 | 只用每个股票信号日前的已收盘日线，封板定义与 `history_engine.build_daily_feature_frame()` 完全一致：主板日涨幅 `9.2%..11.5%`。当前信号日绝不进入计数。 |
| 窗口 | `42`、`63`、`126` 个该股票的交易日，分别标注为 2/3/6 个月近似值。不是自然月，避免节假日和停牌造成含义漂移。 |
| 网格 | 对每个窗口穷举 `1 <= lower <= upper <= 10` 的所有 55 个闭区间，共 165 个组合；`126:2-6` 是固定当前 A+B 对照。 |
| 结算 | 正式涨停价入场、费用合同不变、D+1 官方收盘；高收益 `>=5%` 只用于覆盖描述，绝不决定成员资格。 |
| 排序/容量 | 信号成员按网格决定；两仓现金回测保留现有 A/B 时间顺序、A 优先级和为后到 A 保留的仓位规则。C 不进入此实验。 |

### Anti-overfit contract

1. 严格选择只允许使用候选历史的前 252 个交易日训练和随后的 63 日 calibration；之后按 63 日 expanding OOS 和最后 120 日 locked holdout 验收。不得因为结果而缩短这些窗口。
2. 严格组合必须在每个 selection/calibration/OOS/holdout 段有至少 15 笔闭合信号、胜率至少 60%、平均 D+1 净收益为正、硬亏率和日等权最大回撤不劣于 `126:2-6`，并在两仓账户中不劣化回撤且提高总收益。缺任何段就标记 `INSUFFICIENT_STRICT_VALIDATION`，不能称为最佳。
3. 由于冻结候选最早只有 `2025-06-27`，另固定输出 `2025_06_12`、`2026_01_02`、`2026_03_07` 三个已见批次，仅作描述性分批反证；全历史排序和这三个批次都不能晋级正式规则。
4. 选择分数固定为 calibration 段的日等权复利、平均收益、胜率、较低硬亏率、较高样本量的字典序；locked holdout 不可参与选择。对选择出的组合按完整 `signal_date` 块 bootstrap 报告与 `126:2-6` 的平均收益差分 95% 区间。

## Task 1: Freeze plan and add the 42/63 count fields

**Files:**

- Create: `requirements/alphaagent_limit_up_recognition_gate_window_grid_research_plan.md`
- Modify: `alphaagent/server/services/limit_up/lane_features.py`
- Modify: `tests/alphaagent/test_limit_up_lanes.py`

- [ ] Add `prior_limit_count_42` and `prior_limit_count_63` beside the existing 5/10/126 counts, using `_prior_group_count()` with the same cumulative sealed rows.
- [ ] Extend the existing rolling-count test to assert the 42/63 columns are strictly shifted and exactly match the reference rolling calculation.
- [ ] Run `uv run --group server pytest -q tests/alphaagent/test_limit_up_lanes.py`.

## Task 2: Build a frozen counterfactual frame

**Files:**

- Create: `alphaagent/server/services/limit_up/recognition_gate_window_grid_research.py`
- Create: `tests/alphaagent/test_limit_up_recognition_gate_window_grid_research.py`

- [ ] Add a test that changes D+1 returns and proves grid membership is unchanged.
- [ ] Add a test that recalculated 126-day values are joined by `(signal_date, vt_symbol)`, that missing counts fail closed, and that a mismatch with the frozen `prior_limit_count_126` is reported rather than hidden.
- [ ] Implement the loader using `history_repository.load_history_range()`, `scheduled_execution.extract_scheduled_orders()`, `first_board_stock_gene_research.attach_prior_stock_gene_evidence_to_orders()`, `history_engine.build_daily_feature_frame()`, and `quality_no_trade_reverse.build_official_closed_trade_evidence()`.
- [ ] Load daily bars only for symbols in the frozen candidate universe, beginning at the earliest persisted replay date, so research remains within the isolated service's resource budget.

## Task 3: Evaluate the complete registered grid

**Files:**

- Modify: `alphaagent/server/services/limit_up/recognition_gate_window_grid_research.py`
- Modify: `tests/alphaagent/test_limit_up_recognition_gate_window_grid_research.py`

- [ ] Add a test that exactly 165 variants are registered and includes `126:2-6`.
- [ ] Add tests for inclusive lower/upper boundaries and chronological selection isolation: a holdout return mutation must not change the selected configuration.
- [ ] Calculate independent-signal metrics, high-return daily coverage, fixed-batch summaries, full-history descriptive ranks, strict validation availability, and complete `REJECT`/`INSUFFICIENT` status for every variant.
- [ ] Replay only the calibration-selected candidate and baseline through `CashBacktestConfig(initial_cash=100_000, max_positions=2)`, then report both accounts without using that account outcome to choose parameters.
- [ ] Run focused tests and verify the formal quality contract has no edits.

## Task 4: Run read-only research and persist evidence

**Files:**

- Create: `memory/06_backtests/limit_up_recognition_gate_window_grid_20260730.md`
- Create: `memory/06_backtests/limit_up_recognition_gate_window_grid_20260730.json`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md` only for a verified durable conclusion
- Modify: `requirements/README.md`

- [ ] Provide CLI arguments for the fixed date range and requested JSON/Markdown paths. The CLI may read PostgreSQL and write only those two artifacts.
- [ ] Run only via:

```bash
docker compose --profile research run --rm --no-deps -T \
  -v "$PWD:/workspace" -w /workspace alphaagent-research python -m \
  alphaagent.server.services.limit_up.recognition_gate_window_grid_research \
  --start 2023-03-28 --end 2026-07-29 \
  --json-output memory/06_backtests/limit_up_recognition_gate_window_grid_20260730.json \
  --markdown-output memory/06_backtests/limit_up_recognition_gate_window_grid_20260730.md
```

- [ ] The report must state the full grid, input fingerprint, strict-data sufficiency, baseline, all per-window descriptive leaders, selected candidate (if any), OOS/holdout results, two-slot account comparison, and an explicit `SHADOW_ONLY` or `INSUFFICIENT_STRICT_VALIDATION` conclusion.

## Task 5: Verify and record only durable facts

**Files:**

- Test: `tests/alphaagent/test_limit_up_lanes.py`
- Test: `tests/alphaagent/test_limit_up_recognition_gate_window_grid_research.py`

- [ ] Run focused pytest, `uv run python -m compileall -q alphaagent/server/services/limit_up`, JSON parsing, and `git diff --check`.
- [ ] Update the evidence index and decisions with the resulting boundary. Do not add a formal rule, endpoint, recommendation, or `core_quality.py` change.

## Success criteria

- All 165 combinations are visible in the JSON rather than only the apparent winner.
- 42/63/126 counts use an identical, strictly prior trading-row definition.
- Holdout outcomes cannot change parameter choice.
- An insufficient strict history is reported honestly; no post-hoc time-window shortening or production promotion occurs.
