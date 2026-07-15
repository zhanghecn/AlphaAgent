# AlphaAgent Unified Intraday Relay Portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Subagent execution is disabled for this repository task.

**Goal:** Remove one-to-two research and auction buys, add point-in-time two-to-three relay triggers to the existing first-board schedule, and verify the resulting two-position account against all frozen gates.

**Architecture:** Keep one execution clock and one cash account. Historical replay stores relay qualification separately from its D-day first-touch/reseal trigger; `scheduled_execution` extracts complete chronological pools and applies relay-before-first-board ordering only for equal timestamps. Live code consumes the same lane and clock contract, while high-board remains research-only because its frozen variants fail the drawdown gates.

**Tech Stack:** Python 3.11, FastAPI, pandas, SQLAlchemy/PostgreSQL, pytest, React/TypeScript, Vitest, Docker Compose.

---

## Project Constraints

- Do not modify `vnpy/` or official examples.
- Use `apply_patch` for manual edits.
- Do not run `git commit` or `git push`.
- Preserve existing concept-resonance worktree changes.
- Product lanes are frozen to `first_board` and `two_to_three`; `high_board` remains an independent research lane.
- Historical missing event/reseal evidence must be skipped, never replaced by auction open or daily close.

## File Map

- `alphaagent/server/services/limit_up/lane_research.py`: active lane contract, qualification rules and deterministic ranking.
- `alphaagent/server/services/limit_up/history_engine.py`: point-in-time historical candidate construction and persisted relay trigger evidence.
- `alphaagent/server/services/limit_up/scheduled_execution.py`: shared clock, relay trigger resolver, complete-pool order extraction and lane priority.
- `alphaagent/server/services/limit_up/cash_backtest.py`: chronological account ordering for simultaneous signals.
- `alphaagent/server/services/limit_up/history_service.py`: baseline/variant cash reports, merge gates, active cache scopes and public history ledgers.
- `alphaagent/server/services/limit_up/live_policy.py`: remove auction buys and emit relay actions only on a fresh first-touch/reseal trigger.
- `alphaagent/server/services/limit_up/live_service.py`: live qualification/trigger separation and product portfolio lane set.
- `alphaagent/server/services/limit_up/next_session_plan.py`: D-1 board-two/high-board observation plan without an auction buy instruction.
- `alphaagent/server/services/limit_up/walk_forward_contract.py`: remove one-to-two from active model contracts.
- `alphaagent/server/api/limit_up.py`: remove one-to-two from public query literals.
- `frontend/src/api/limitUp.ts`: active lane and comparison-report types.
- `frontend/src/features/limitUp/livePortfolio.ts`: unified product lane filtering.
- `frontend/src/features/limitUp/limitUpPresentation.ts`: remove the one-to-two user label.
- `alphaagent/server/services/limit_up/versions.py`: history/live/model version bumps.
- `tests/alphaagent/test_limit_up_lanes.py`, `test_limit_up_scheduled_execution.py`, `test_limit_up_cash_backtest.py`, `test_limit_up_live.py`, `test_limit_up_next_session_plan.py`, `test_limit_up_walk_forward_model.py`: backend behavior coverage.
- `frontend/src/features/limitUp/livePortfolio.spec.ts`, `limitUpPresentation.spec.ts`: frontend contract coverage.
- `memory/06_backtests/limit_up_unified_intraday_relay_backtest_20260715.md`: final evidence artifact.
- `memory/06_backtests/README.md`, `memory/09_decisions/decisions.md`, `memory/03_data/data_flow.md`, `memory/05_runtime/run_debug.md`: current-state memory updates.

### Task 1: Remove One-To-Two From Active Contracts

**Files:**
- Modify: `alphaagent/server/services/limit_up/lane_research.py`
- Modify: `alphaagent/server/services/limit_up/history_engine.py`
- Modify: `alphaagent/server/services/limit_up/history_service.py`
- Modify: `alphaagent/server/services/limit_up/walk_forward_contract.py`
- Modify: `alphaagent/server/api/limit_up.py`
- Test: `tests/alphaagent/test_limit_up_lanes.py`
- Test: `tests/alphaagent/test_limit_up_walk_forward_model.py`

- [ ] **Step 1: Write failing active-contract tests**

```python
def test_one_to_two_is_not_an_active_research_lane() -> None:
    assert BOARD_LANES == ("first_board", "two_to_three", "high_board")
    with pytest.raises(ValueError, match="removed"):
        evaluate_lane_candidate(_lane_candidate(target_board=2, prior_streak=1))


def test_history_generation_skips_target_board_two() -> None:
    candidates = _build_board_candidates(prior_streak=1, prior_limit_count_5=1)
    assert all(candidate["target_board"] != 2 for candidate in candidates)
```

- [ ] **Step 2: Run the tests and confirm the old lane is still active**

Run:

```bash
uv run pytest tests/alphaagent/test_limit_up_lanes.py -q -k "one_to_two_is_not_an_active or generation_skips_target"
```

Expected: FAIL because `BOARD_LANES` still contains `one_to_two` and board-two candidates are generated.

- [ ] **Step 3: Implement the active-lane boundary**

Use this contract in `lane_research.py`:

```python
BOARD_LANES = ("first_board", "two_to_three", "high_board")
REMOVED_BOARD_LANES = frozenset({"one_to_two"})


def evaluate_lane_candidate(candidate: Mapping[str, object]) -> dict[str, object]:
    lane = classify_board_lane(candidate)
    if lane in REMOVED_BOARD_LANES:
        raise ValueError(f"board lane removed: {lane}")
    # Existing active-lane evaluation follows unchanged.
```

In `history_engine._board_lane_candidates_from_day`, continue when `target_board == 2` before building a candidate. Filter legacy selected rows through `BOARD_LANES` in `history_service._selected_lane_candidates`. Remove `one_to_two` from `walk_forward_contract.BOARD_LANES`, `BOARD_LANE_ENTRY_MODES`, and the API `Literal` definitions for ledger, backtest and model-report routes.

- [ ] **Step 4: Replace old one-to-two behavior tests with removal tests**

Delete assertions that optimize, validate, cache or expose one-to-two. Keep market breadth fields such as `prior_market_one_to_two_rate`; they are market context, not an active strategy.

- [ ] **Step 5: Run focused contract tests**

```bash
uv run pytest tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_walk_forward_model.py -q
```

Expected: PASS, with no active one-to-two model/backtest expectation.

### Task 2: Rebuild Relay Entries From Point-In-Time Events

**Files:**
- Modify: `alphaagent/server/services/limit_up/scheduled_execution.py`
- Modify: `alphaagent/server/services/limit_up/history_engine.py`
- Modify: `alphaagent/server/services/limit_up/lane_research.py`
- Test: `tests/alphaagent/test_limit_up_scheduled_execution.py`
- Test: `tests/alphaagent/test_limit_up_lanes.py`

- [ ] **Step 1: Add failing trigger-resolution tests**

```python
def test_relay_trigger_uses_first_touch_inside_shared_window() -> None:
    result = resolve_relay_entry_trigger("10:12:03", [])
    assert result == {
        "status": "ready",
        "signal_time": "10:12:03",
        "signal_kind": "first_touch",
        "reason": None,
    }


def test_relay_trigger_requires_path_for_pre_ten_reseal() -> None:
    result = resolve_relay_entry_trigger("09:35:00", [])
    assert result["status"] == "missing_reseal_path"
    assert result["signal_time"] is None


def test_relay_trigger_uses_first_observable_window_reseal() -> None:
    path = _return_path(touch_at="09:36:00", break_at="09:57:00", reseal_at="10:03:00")
    result = resolve_relay_entry_trigger("09:36:00", path)
    assert result["signal_time"] == "10:03:00"
    assert result["signal_kind"] == "reseal"
```

- [ ] **Step 2: Verify the tests fail**

```bash
uv run pytest tests/alphaagent/test_limit_up_scheduled_execution.py -q -k "relay_trigger"
```

Expected: FAIL because the resolver does not exist.

- [ ] **Step 3: Implement the shared resolver**

Add to `scheduled_execution.py`:

```python
def resolve_relay_entry_trigger(
    first_limit_time: object,
    return_path: Sequence[object],
) -> dict[str, object]:
    first_time = _time_text(first_limit_time)
    if is_entry_time(first_time):
        return _relay_trigger("ready", first_time, "first_touch")
    if first_time < "10:00:00":
        if not return_path:
            return _relay_trigger("missing_reseal_path", None, None)
        reseal_time = first_reseal_time(return_path, not_before="10:00:00")
        if reseal_time and is_entry_time(reseal_time):
            return _relay_trigger("ready", reseal_time, "reseal")
        return _relay_trigger("no_window_reseal", None, None)
    return _relay_trigger("outside_entry_window", None, None)
```

- [ ] **Step 4: Persist qualification and trigger as separate fields**

For target board 3 or higher in `history_engine._board_lane_candidates_from_day`:

```python
current_event = event_evidence.get((symbol, trade_date))
return_path = _event_intraday_path(current_event, previous_close=row.get("prev_close")) if current_event else []
trigger = scheduled_execution.resolve_relay_entry_trigger(
    (current_event or {}).get("first_limit_time"),
    return_path,
)
candidate.update({
    "qualification_time": "09:25:00",
    "qualification_kind": "auction",
    "relay_trigger_status": trigger["status"],
    "relay_trigger_reason": trigger["reason"],
    "signal_time": trigger["signal_time"],
    "buy_time": trigger["signal_time"],
    "signal_kind": trigger["signal_kind"],
    "entry_price": candidate.get("limit_price") if trigger["status"] == "ready" else None,
})
```

Attach the current event and path prefix only up to `signal_time`. Recompute next-open/next-close outcome percentages from `limit_price`, not the discarded daily open. In `_high_board_rules`, read `qualification_kind` before falling back to `signal_kind` so a D-day trigger cannot change D-1 qualification semantics.

- [ ] **Step 5: Test missing, first-touch and reseal candidates**

```bash
uv run pytest tests/alphaagent/test_limit_up_scheduled_execution.py tests/alphaagent/test_limit_up_lanes.py -q
```

Expected: PASS; no relay order has `09:25`/`09:30` as its buy time.

### Task 3: Build One Chronological Product Order Stream

**Files:**
- Modify: `alphaagent/server/services/limit_up/scheduled_execution.py`
- Modify: `alphaagent/server/services/limit_up/cash_backtest.py`
- Test: `tests/alphaagent/test_limit_up_scheduled_execution.py`
- Test: `tests/alphaagent/test_limit_up_cash_backtest.py`

- [ ] **Step 1: Write failing complete-pool and priority tests**

```python
def test_extract_orders_includes_ready_two_to_three_but_not_high_board_by_default() -> None:
    orders = extract_scheduled_orders([_day_with_first_relay_and_high_board()])
    assert [order["lane"] for order in orders] == ["two_to_three", "first_board"]


def test_same_time_relay_fills_before_first_board() -> None:
    account = simulate_limit_up_account(
        [_signal("first_board", "10:06:00"), _signal("two_to_three", "10:06:00")],
        bars=_bars(),
        trade_dates=_trade_dates(),
        exit_mode="next_1430",
        config=CashBacktestConfig(max_positions=1),
    )
    buy = next(order for order in account["orders"] if order["side"] == "BUY" and order["status"] == "filled")
    assert buy["lane"] == "two_to_three"
```

- [ ] **Step 2: Confirm the old first-board-only extraction fails**

```bash
uv run pytest tests/alphaagent/test_limit_up_scheduled_execution.py tests/alphaagent/test_limit_up_cash_backtest.py -q -k "ready_two_to_three or same_time_relay"
```

Expected: FAIL because extraction and cash sorting are first-board-only.

- [ ] **Step 3: Implement product lane constants and extraction**

```python
RELAY_LANES = frozenset({"two_to_three", "high_board"})
PRODUCT_EXECUTION_LANES = ("first_board", "two_to_three")


def execution_lane_priority(lane: object) -> int:
    return 0 if str(lane) in RELAY_LANES else 1


def extract_scheduled_orders(
    history_rows: Sequence[Mapping[str, object]],
    *,
    included_lanes: Sequence[str] = PRODUCT_EXECUTION_LANES,
) -> list[dict[str, object]]:
    # Read every requested candidate_pool, require decision=eligible and an entry-window buy_time.
    # Relay rows additionally require relay_trigger_status=ready.
    # Deduplicate by entry_date + vt_symbol and sort chronologically.
```

Use sort order `entry_date`, `buy_time`, relay priority, descending point-in-time rank, pool rank, symbol. Add the same lane-priority term immediately after `buy_time` in `cash_backtest._entry_sort_key`. Different timestamps remain strictly chronological, so an earlier first board is never displaced by a later relay.

- [ ] **Step 4: Add coverage aggregation**

`scheduled_execution.relay_trigger_coverage()` must return eligible, event-missing, path-missing, no-window-trigger, ready, first-touch and reseal counts per relay lane and in total.

- [ ] **Step 5: Run execution tests**

```bash
uv run pytest tests/alphaagent/test_limit_up_scheduled_execution.py tests/alphaagent/test_limit_up_cash_backtest.py -q
```

Expected: PASS, including earlier-first-board/no-reservation and same-time-relay tests.

### Task 4: Add Frozen Portfolio Variant Gates

**Files:**
- Modify: `alphaagent/server/services/limit_up/history_service.py`
- Modify: `frontend/src/api/limitUp.ts`
- Test: `tests/alphaagent/test_limit_up_lanes.py`
- Test: `tests/alphaagent/test_limit_up_history.py`

- [ ] **Step 1: Write a failing report-shape test**

```python
def test_scheduled_report_selects_only_passing_relay_variant(monkeypatch) -> None:
    report = history_service._build_scheduled_history_backtest(None, None)
    assert report["portfolio_policy"]["included_lanes"] == ["first_board", "two_to_three"]
    assert report["relay_comparison"]["selected_variant"] == "first_board_two_to_three"
    assert report["relay_comparison"]["variants"]["first_board_high_board"]["passed"] is False
    assert "one_to_two_audit" not in report
```

- [ ] **Step 2: Verify failure against the old report**

```bash
uv run pytest tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_history.py -q -k "passing_relay_variant"
```

Expected: FAIL because the report is first-board-only and still exposes one-to-two audit data.

- [ ] **Step 3: Simulate the four frozen variants**

Build order sets for:

```python
VARIANT_LANES = {
    "first_board": ("first_board",),
    "first_board_two_to_three": ("first_board", "two_to_three"),
    "first_board_high_board": ("first_board", "high_board"),
    "first_board_all_relays": ("first_board", "two_to_three", "high_board"),
}
```

Load bars and D+1 14:30 exits once for the union of all orders. For each variant calculate full-period, design, time-validation, post-freeze and double-cost summaries.

- [ ] **Step 4: Implement the fixed merge gate**

```python
def _relay_variant_gate(
    summary: Mapping[str, object],
    validation: Mapping[str, object],
    stress: Mapping[str, object],
    baseline_summary: Mapping[str, object],
    baseline_validation: Mapping[str, object],
) -> dict[str, object]:
    checks = {
        "full_return_improved": _number(summary.get("total_return_pct")) > _number(baseline_summary.get("total_return_pct")),
        "full_drawdown": _number(summary.get("max_drawdown_pct")) >= -10.0,
        "validation_return_not_lower": _number(validation.get("total_return_pct")) >= _number(baseline_validation.get("total_return_pct")),
        "validation_drawdown": _number(validation.get("max_drawdown_pct")) >= -10.0,
        "double_cost_positive": _number(stress.get("total_return_pct")) > 0.0,
        "double_cost_drawdown": _number(stress.get("max_drawdown_pct")) >= -10.0,
    }
    return {"passed": all(checks.values()), "checks": checks}
```

Select the highest-return passing variant from the predefined set. Assert that it matches `scheduled_execution.PRODUCT_EXECUTION_LANES`; fail closed to first board if it does not. Remove `_one_to_two_execution_audit` and all report fields that publish one-to-two research.

- [ ] **Step 5: Use complete active pools for independent lane backtests**

Load non-compact history rows and call `extract_scheduled_orders(..., included_lanes=(lane,))` for first-board, two-to-three and high-board reports. Continue exposing high-board as research, but never include it in the selected product variant.

- [ ] **Step 6: Run history report tests**

```bash
uv run pytest tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_history.py -q
```

Expected: PASS; portfolio mode is unified, selected lanes are first-board/two-to-three, and no one-to-two audit is returned.

### Task 5: Align Live and Next-Session Behavior

**Files:**
- Modify: `alphaagent/server/services/limit_up/live_policy.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `alphaagent/server/services/limit_up/next_session_plan.py`
- Test: `tests/alphaagent/test_limit_up_live.py`
- Test: `tests/alphaagent/test_limit_up_next_session_plan.py`

- [ ] **Step 1: Add failing live behavior tests**

```python
def test_live_auction_never_emits_a_buy() -> None:
    signal = _now_signal(_eligible_relay(), "auction", _passed_gate(), _at("09:25:00"), 0)
    assert signal["action"] == "observe"


def test_live_two_to_three_first_touch_can_trigger_in_shared_window() -> None:
    signal = _build_relay_signal(first_time="10:06:02", state="sealed", captured_at="10:06:15")
    assert signal["action"] == "buy_now"
    assert signal["entry_kind"] == "first_touch"


def test_live_pre_ten_seal_without_new_window_reseal_is_not_bought() -> None:
    signal = _build_relay_signal(first_time="09:35:00", last_time="09:35:00", state="sealed", captured_at="10:05:00")
    assert signal["action"] == "observe"
```

- [ ] **Step 2: Verify old auction/L2 behavior fails**

```bash
uv run pytest tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_next_session_plan.py -q -k "auction_never or shared_window or pre_ten_seal"
```

Expected: FAIL because auction emits `buy_now` and three-board intraday signals are structurally blocked.

- [ ] **Step 3: Separate live qualification from fresh triggers**

For board level 3 or higher, set `qualification_kind="auction"` before lane evaluation. Derive a relay trigger only when:

```python
first_touch_ready = state in {"sealed", "resealed"} and is_entry_time(first_limit_time)
reseal_ready = (
    state == "resealed"
    and first_limit_time < "10:00:00"
    and open_times > 0
    and is_entry_time(last_limit_time)
)
fresh = trigger_time > previous_snapshot_time if previous_snapshot_time else trigger_age_seconds <= 90
```

Store `relay_trigger_status`, `relay_trigger_time` and `relay_trigger_kind` internally. Never infer a pre-10 reseal from the final sealed state alone.

- [ ] **Step 4: Update live policy and portfolio priority**

- Auction and auction-watch stages emit observations only.
- Board level 2 emits no current buy/research recommendation.
- After its D-1 structure has been converted into a target-board-3 observation, board level 2 is removed
  from public `candidates`, live traces, lane validation output and recommendation channels.
- Active relay signals require `lane_decision=eligible`, a fresh trigger, market/dynamic gates and the shared entry clock.
- `PORTFOLIO_EXECUTION_LANES` becomes `{first_board, two_to_three}`.
- `_live_portfolio_sort_key` sorts executable relay signals before executable first-board signals in the same snapshot; observations never block a ready first board.
- High-board signals remain visible only in independent research data and never enter `recommendations.portfolio`.

- [ ] **Step 5: Preserve D-1 structure without restoring one-to-two**

In `next_session_plan`, a sealed source board level 2 creates a target-board-3 observation; source board level 1 creates no target-board-2 plan. Replace auction-buy text with:

```python
{
    "action": "observe",
    "research_action": "observe",
    "buy_instruction": "次交易日10:00后仅在首次触板或可观察回封时进入综合候选",
    "valid_until": "下一交易日14:30",
}
```

Source board level 3 or higher may form a high-board research observation, but it is not a product execution lane.

- [ ] **Step 6: Run live/plan tests**

```bash
uv run pytest tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_next_session_plan.py -q
```

Expected: PASS with no auction buy and no one-to-two plan.

### Task 6: Remove One-To-Two From Frontend Contracts

**Files:**
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/features/limitUp/livePortfolio.ts`
- Modify: `frontend/src/features/limitUp/limitUpPresentation.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Test: `frontend/src/features/limitUp/livePortfolio.spec.ts`
- Test: `frontend/src/features/limitUp/limitUpPresentation.spec.ts`

- [ ] **Step 1: Add failing unified product tests**

```typescript
it("keeps first-board and two-to-three in the single product portfolio", () => {
  const portfolio = [
    signal("600010.SSE", 3, "buy_now"),
    signal("600011.SSE", 1, "buy_now"),
    signal("600012.SSE", 4, "buy_now"),
  ];
  expect(liveSignalsForScope(snapshot({ portfolio }), "portfolio").map(row => row.vt_symbol))
    .toEqual(["600010.SSE", "600011.SSE"]);
});
```

- [ ] **Step 2: Run the frontend test and confirm failure**

```bash
pnpm -C frontend test -- livePortfolio.spec.ts limitUpPresentation.spec.ts
```

Expected: FAIL because the product set is first-board-only.

- [ ] **Step 3: Update active TypeScript types and filters**

```typescript
export type BoardLaneKey = "first_board" | "two_to_three" | "high_board";

const PORTFOLIO_LANES = new Set<BoardLaneKey>([
  "first_board",
  "two_to_three",
]);
```

Remove the one-to-two label and `one_to_two_audit` response type. Make `boardLaneForLevel(2)` return `null`, and skip null lanes. Keep existing single composite page; do not add a lane selector, card or badge.

- [ ] **Step 4: Run frontend tests and build**

```bash
pnpm -C frontend test
pnpm -C frontend build
```

Expected: all Vitest tests pass and TypeScript/Vite production build succeeds.

### Task 7: Version, Full Regression and Historical Rebuild

**Files:**
- Modify: `alphaagent/server/services/limit_up/versions.py`
- Modify: `alphaagent/server/services/limit_up/scheduled_execution.py`
- Modify: `alphaagent/server/services/limit_up/cash_backtest.py`
- Test: all limit-up backend/frontend tests.

- [ ] **Step 1: Bump behavior versions**

```python
HISTORY_STRATEGY_VERSION = "limit-up-history-v15"
LIVE_STRATEGY_VERSION = "limit-up-live-v6"
WALK_FORWARD_MODEL_VERSION = "limit-up-walk-forward-v6"
SCHEDULED_EXECUTION_VERSION = "limit-up-scheduled-v4"
ACCOUNT_EXECUTION_VERSION = "limit-up-cash-v4"
```

- [ ] **Step 2: Run focused backend regression**

```bash
uv run pytest \
  tests/alphaagent/test_limit_up_lanes.py \
  tests/alphaagent/test_limit_up_scheduled_execution.py \
  tests/alphaagent/test_limit_up_cash_backtest.py \
  tests/alphaagent/test_limit_up_history.py \
  tests/alphaagent/test_limit_up_live.py \
  tests/alphaagent/test_limit_up_next_session_plan.py \
  tests/alphaagent/test_limit_up_walk_forward_model.py -q
```

Expected: PASS.

- [ ] **Step 3: Run all limit-up backend tests**

```bash
uv run pytest tests/alphaagent -q -k "limit_up"
```

Expected: PASS with no stale one-to-two API/cache expectation.

- [ ] **Step 4: Compile and check diffs**

```bash
uv run python -m compileall -q alphaagent/server/services/limit_up alphaagent/server/api/limit_up.py
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 5: Rebuild the v15 history ledger in the API container**

```bash
docker compose exec -T alphaagent-api python -c \
  'from alphaagent.server.services.limit_up.history_service import rebuild_history_sync; print(rebuild_history_sync())'
```

Expected: status `ready`, 603 or more persisted trading days, no target-board-2 active candidate pools, and relay coverage populated.

### Task 8: Verify Returns, Document Evidence and Deploy

**Files:**
- Create: `memory/06_backtests/limit_up_unified_intraday_relay_backtest_20260715.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`

- [ ] **Step 1: Export the authoritative portfolio and lane reports**

Run the cached service functions inside `alphaagent-api` for `portfolio`, `first_board`, `two_to_three` and `high_board`. Record full, phase, double-cost, coverage and gate-check summaries. Verify these directional expectations after the v15 rebuild:

```text
first_board baseline:             +224.0076% / -7.9408%
first_board + two_to_three:       +266.4491% / -8.0275%
two_to_three independent:          +27.7336% / -4.7516%
high_board independent:             -5.0319% / -13.4460%
```

Dates or newly matured D+1 rows may move exact values; compare variants from the same run and enforce gates rather than forcing these constants.

- [ ] **Step 2: Write the evidence artifact**

Include:

- 87/33 eligible relay candidates and 17/12 valid triggers.
- 21 first-touch and 8 reseal triggers.
- Missing event/path and no-window-trigger groups.
- Baseline and all three predefined relay variants.
- Full, design, time-validation, post-freeze and double-cost results.
- The explicit conclusion: two-to-three included, high-board excluded, one-to-two removed.
- Tick/L2, 14:30 close-proxy and event-selection-bias limitations.

- [ ] **Step 3: Update durable memory in place**

Replace stale “first-board-only” current-state bullets with the selected unified product. Remove the one-to-two internal-negative-control claim; old evidence remains only in archived reports, not current product state.

- [ ] **Step 4: Rebuild and restart application services**

```bash
docker compose up -d --build alphaagent-api alphaagent-web
docker compose ps
```

Expected: API healthy, web running, gateway/postgres/redis unchanged and healthy.

- [ ] **Step 5: Verify runtime contracts**

Check through the gateway at `http://localhost:8080`:

- `/api/limit-up/history/backtest?lane=portfolio` selects first-board/two-to-three.
- `lane=one_to_two` returns 422.
- live recommendations contain no auction buy and no one-to-two product row.
- strategy versions are v15/v6/v4 as applicable.
- `/limit-up` still presents one composite recommendation without new controls.

- [ ] **Step 6: Final hygiene checks**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; all unrelated pre-existing changes remain intact; no commit is created.
