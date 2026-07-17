# Cycle Leader Identity Comparison Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compare the three preregistered return-independent D-1 leader identity modes on every observed concept main-rise session, and only reopen the frozen pullback study if one mode consistently improves on the current market-recognition baseline.

**Architecture:** Extend the existing cycle candidate ledger with the exact causal feature contract used by strict-forward Top3 ranking, then rank the same event-candidate pool under all three public `LeaderIdentityMode` values. A new identity-comparison module attaches only return-independent future identity labels, evaluates five chronological blocks, applies a frozen improvement gate, and conditionally reuses the existing five pullback moments without inventing another entry rule.

**Tech Stack:** Python 3.11+, pandas, NumPy, existing AlphaAgent cycle, leader-identity, event-neutral minute, D+1 cash execution and research-report helpers, pytest, Ruff.

---

## Frozen Contract

- Historical complete concept membership is still unavailable. Every result is explicitly `event_candidate_pool_proxy`, never strict concept-member Top3 or formal performance.
- A candidate becomes rankable only after its event recognition date and only with bars through D-1.
- Identity features match the existing strict-forward definitions:
  - cycle-relative return uses the completed session immediately before cycle start as the anchor;
  - strong day means daily return at least 5%;
  - strong-day count is measured from cycle start through D-1;
  - sessions since strong uses the completed history through D-1;
  - capacity uses trailing 20-session median traded value and the frozen CNY 100 million threshold.
- Compare only the existing modes:
  - `cycle_relative_strength`;
  - `market_recognition_lexicographic`;
  - `recognition_consensus`.
- A mode/session is qualified only when it produces exactly three eligible Top3 rows.
- Identity selection never reads low-suction entry or D+1 return fields. Its labels are limited to:
  - next-session Top3 retention within the same cycle;
  - first 5% strong event on D..D+5, using 6 as the no-event sentinel;
  - capacity pass rate.
- Completed-period market/return Top1 coverage is descriptive only and cannot select a mode.
- Use the existing five chronological event blocks. Each block requires at least 100 retention observations and 50 complete strong-event observations for every mode. Winner order is retention descending, strong-event lead ascending, capacity descending, stable mode-name tie-break. Exactly one mode must win at least 3/5 blocks.
- The current baseline is `market_recognition_lexicographic`. A different proxy mode is an improvement only when its pooled metric tuple is lexicographically better than the baseline in both blocks 1-3 and blocks 4-5.
- Low-suction outcomes remain unread unless that improvement gate passes. If it passes, reuse the already frozen MA5, MA10, VWAP, 1% drawdown and 3% drawdown moments, next-5m-open entry, D+1-close exit and normal/double costs.
- Blocks 4-5 and all pullback returns were visible in prior studies. No result is an untouched holdout, no formal identity is frozen, and `formal_metrics` remains null.

### Task 1: Exact D-1 identity features

**Files:**
- Modify: `alphaagent/server/services/low_suction/cycle_leader_study.py`
- Modify: `alphaagent/server/services/low_suction/event_recognition_falsification.py`
- Modify: `tests/alphaagent/services/low_suction/test_cycle_leader_study.py`

- [x] **Step 1: Write failing causal-feature tests**

Assert each dynamic row exposes a separate `identity_feature_status`, pre-cycle-anchor relative return, 5% cycle strong-day count, sessions since the latest 5% day, 20-session median traded value and capacity flag. Mutating D or later bars must not change any of them.

- [x] **Step 2: Run the focused test and confirm failure**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_cycle_leader_study.py -q
```

Expected: assertions fail because the exact identity feature columns do not exist.

- [x] **Step 3: Implement the minimal feature extension**

Add causal columns without changing the existing dynamic market-recognition ordering:

```python
IDENTITY_STRONG_DAY_PCT = 5.0
IDENTITY_CAPACITY_MIN_MEDIAN_VALUE = 100_000_000.0

# Returned by _dynamic_candidate_row
identity_feature_status: str
identity_cycle_relative_return: float | None
identity_strong_day_count_cycle: int | None
identity_sessions_since_strong: int | None
identity_turnover_median_20d: float | None
identity_capacity_passed: bool
```

Load the existing `stock_daily_bars.turnover` column in the event input query. Require both stock and concept pre-cycle anchors, a D-1 close and 20 completed turnover observations before marking the identity feature row complete; do not substitute `close * volume` for this strict-forward-compatible capacity field.

- [x] **Step 4: Run focused tests and Ruff**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_cycle_leader_study.py -q
uvx ruff check alphaagent/server/services/low_suction/cycle_leader_study.py alphaagent/server/services/low_suction/event_recognition_falsification.py tests/alphaagent/services/low_suction/test_cycle_leader_study.py
```

Expected: all pass.

### Task 2: Three-mode rank ledger and identity labels

**Files:**
- Create: `alphaagent/server/services/low_suction/cycle_leader_identity_study.py`
- Create: `tests/alphaagent/services/low_suction/test_cycle_leader_identity_study.py`

- [x] **Step 1: Write failing rank-ledger tests**

Cover all three `LeaderIdentityMode` values, exact-three qualification, deterministic ranks, rejection of `realized_`, `future_`, trade-return and exit columns, and invariance to D/future price mutation.

- [x] **Step 2: Implement the public rank builder**

```python
def build_cycle_identity_mode_ranks(dynamic_candidates: pd.DataFrame) -> pd.DataFrame:
    """Rank the same D-1 event-candidate pool under all frozen identity modes."""
```

Map the Task 1 fields into `rank_prevalidated_leader_identities()`, retain `cycle_id`, `stock_name` and D-1 cutoff evidence, then add `mode_pool_size`, `mode_top3_qualified`, `mode_top1` and qualified `mode_top3` flags.

- [x] **Step 3: Write failing label tests**

Use a synthetic calendar to prove that retention only compares the next real session in the same cycle, strong-event lead scans D..D+5 with sentinel 6, incomplete horizons remain null, and realized leader labels are attached only after ranks are frozen.

- [x] **Step 4: Implement the separated label builder**

```python
def build_cycle_identity_labels(
    ranks: pd.DataFrame,
    stock_bars: pd.DataFrame,
    realized_leaders: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> pd.DataFrame:
    """Attach return-independent future identity labels after D-1 ranking."""
```

- [x] **Step 5: Run the new focused test file**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_cycle_leader_identity_study.py -q
```

Expected: all pass.

### Task 3: Block metrics, improvement gate and conditional pullback bridge

**Files:**
- Modify: `alphaagent/server/services/low_suction/cycle_leader_identity_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_cycle_leader_identity_study.py`

- [x] **Step 1: Write failing metric and selection tests**

Assert metrics contain all/development/validation/block segments, all three modes survive even when unqualified, insufficient blocks have no winner, a unique 3/5 winner is selected, and a non-baseline mode must beat market recognition in both pooled segments before status becomes `improved_proxy_identity_found`.

- [x] **Step 2: Implement identity-only metrics and evaluation**

```python
def build_cycle_identity_metrics(labels: pd.DataFrame) -> pd.DataFrame:
    """Summarize retention, strong-event lead, capacity and oracle coverage."""

def evaluate_cycle_identity_modes(metrics: pd.DataFrame) -> dict[str, Any]:
    """Select a stable proxy mode without reading low-suction returns."""
```

Return block winners, win counts, candidate mode, development/validation deltas, the improvement status, `formal_selected_mode=None` and `low_suction_outcomes_read=False`.

- [x] **Step 3: Write failing conditional bridge tests**

Assert the bridge does not invoke a supplied pullback runner when the identity gate fails. When the gate passes, assert only the selected mode's qualified Top1/Top3 columns are transformed to the existing dynamic identity contract.

- [x] **Step 4: Implement the conditional bridge**

```python
def build_selected_mode_dynamic_identity(
    ranks: pd.DataFrame,
    selected_mode: str,
) -> pd.DataFrame:
    """Adapt one improved mode to the frozen pullback identity columns."""
```

The real-data runner must branch before loading minute bars or executing D+1 outcomes.

- [x] **Step 5: Run focused tests and Ruff**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_cycle_leader_identity_study.py -q
uvx ruff check alphaagent/server/services/low_suction/cycle_leader_identity_study.py tests/alphaagent/services/low_suction/test_cycle_leader_identity_study.py
```

Expected: all pass.

### Task 4: Deterministic report and read-only CLI

**Files:**
- Modify: `alphaagent/server/services/low_suction/cycle_leader_identity_study.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `tests/alphaagent/services/low_suction/test_cycle_leader_identity_study.py`

- [x] **Step 1: Write failing report and CLI tests**

Assert JSON preserves every rank and metric row, Markdown prints the three modes and five block winners, proxy/formal identities are distinct, the event-candidate limitation is explicit, and `v2-cycle-leader-identity-study` accepts only `--format` and `--output`.

- [x] **Step 2: Implement real-data loading and report rendering**

```python
def run_cycle_leader_identity_study() -> dict[str, Any]:
    """Run identity comparison and conditionally reuse frozen pullback outcomes."""

def render_cycle_leader_identity_json(report: Mapping[str, Any]) -> str:
    ...

def render_cycle_leader_identity_markdown(report: Mapping[str, Any]) -> str:
    ...
```

Persist coverage, input fingerprints, mode overlap, all ranks, all identity metrics, evaluation, optional pullback diagnostics and explicit data/validation limitations.

- [x] **Step 3: Register and verify the CLI**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_cycle_leader_identity_study.py -q
uvx ruff check alphaagent/server/services/low_suction/cli.py alphaagent/server/services/low_suction/cycle_leader_identity_study.py tests/alphaagent/services/low_suction/test_cycle_leader_identity_study.py
```

Expected: all pass.

### Task 5: Execute the real study and preserve evidence

**Files:**
- Create: `memory/06_backtests/low_suction_cycle_leader_identity_study_20260717.md`
- Create: `memory/06_backtests/low_suction_cycle_leader_identity_study_20260717.json`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Generate Markdown and JSON from the same database snapshot**

```bash
uv run python -m alphaagent.server.services.low_suction.cli \
  v2-cycle-leader-identity-study --format markdown \
  --output memory/06_backtests/low_suction_cycle_leader_identity_study_20260717.md
uv run python -m alphaagent.server.services.low_suction.cli \
  v2-cycle-leader-identity-study --format json \
  --output memory/06_backtests/low_suction_cycle_leader_identity_study_20260717.json
```

- [x] **Step 2: Inspect before concluding**

Report per mode and segment: qualified concept sessions, Top3 observations, retention sample/rate, strong-event sample/median/within-five rate, capacity pass, realized market/return Top1 coverage and mode overlap. State every block winner, whether 3/5 stability passed, whether the candidate beat market recognition in both pooled segments, and whether pullback outcomes were read.

- [x] **Step 3: Update durable memory**

Link both artifacts, record the JSON SHA256, replace stale next-work text, and preserve the strict-member limitation and formal-null status.

- [x] **Step 4: Run full verification**

```bash
uv run pytest tests/alphaagent/services/low_suction -q
uv run pytest tests/alphaagent/test_data_sync_schedule.py -q
uvx ruff check alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
uv run python -m compileall -q alphaagent/server/services/low_suction
uv run python -m json.tool memory/06_backtests/low_suction_cycle_leader_identity_study_20260717.json >/dev/null
git diff --check
```

Expected: all pass. Do not commit, push, restart the healthy API or read the locked outer holdout.

## Self-Review

- The study compares existing preregistered modes; it does not invent weights or a fourth score after seeing outcomes.
- Identity labels do not include low-suction returns, entry prices, MFE/MAE or exit fields.
- Oracle completed-period leaders are diagnostic columns only.
- The conditional branch is before minute loading and trade labeling, so a failed identity gate provably leaves pullback outcomes unread.
- A proxy-selected mode never becomes a formal strict-historical or production mode.
