# AlphaAgent Live Limit-Up Gate State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live limit-up desk preserve an intraday market repair confirmation, distinguish permanent strategy rejection from temporary trigger conditions, and show an actionable pre-seal state without weakening the existing trading thresholds.

**Architecture:** `live_policy.py` owns one pure market-gate state transition and one structured set of execution checks. `live_service.py` computes that gate before lane evaluation so a confirmed intraday repair can remove only duplicated D-1 market blockers. Trace persistence projects the exact evidence used by the decision, and the frontend maps backend states without re-inventing trading logic.

**Tech Stack:** Python 3.11+, FastAPI service layer, SQLAlchemy/PostgreSQL, pytest, React/TypeScript, Vitest, Playwright, Docker Compose.

**Repository rule:** Do not create Git commits unless the user separately authorizes them. Preserve all existing uncommitted two-day trace changes.

---

### Task 1: Add the intraday market-repair state transition

**Files:**

- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `alphaagent/server/services/limit_up/live_policy.py`

- [ ] **Step 1: Add failing persistence and revocation tests**

Add tests beside `test_market_gate_allows_prior_ebb_only_after_live_repair_confirmation`:

```python
def _previous_live_snapshot(
    captured_at: datetime,
    *,
    repair_state: str,
    repair_confirmed_at: str | None = None,
) -> dict[str, object]:
    return {
        "trade_date": captured_at.date().isoformat(),
        "captured_at": captured_at.isoformat(),
        "recommendations": {
            "market_gate": {
                "repair_state": repair_state,
                "repair_confirmed": repair_state == "repair_confirmed",
                "repair_confirmed_at": repair_confirmed_at,
                "reasons": [],
            }
        },
    }


def test_market_repair_stays_confirmed_when_next_snapshot_delta_is_zero() -> None:
    repaired_at = datetime(2026, 7, 14, 9, 59, 22, tzinfo=SHANGHAI)
    current_at = datetime(2026, 7, 14, 9, 59, 38, tzinfo=SHANGHAI)
    previous = _previous_live_snapshot(
        repaired_at,
        repair_state="repair_confirmed",
        repair_confirmed_at=repaired_at.isoformat(),
    )

    result = build_live_recommendations(
        [],
        _market(
            sentiment={"phase": "ice", "failed_limit_up_rate": 0.54},
            sealed_count=24,
            failed_count=7,
            failed_rate=7 / 31,
            sealed_change=0,
            failed_change=0,
        ),
        current_at,
        previous_snapshot=previous,
    )

    gate = result["market_gate"]
    assert gate["passed"] is True
    assert gate["repair_state"] == "repair_confirmed"
    assert gate["repair_confirmed_at"] == repaired_at.isoformat()


def test_market_repair_is_revoked_by_failed_rate_breakdown() -> None:
    previous_at = datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI)
    current_at = datetime(2026, 7, 14, 10, 6, tzinfo=SHANGHAI)
    previous = _previous_live_snapshot(
        previous_at,
        repair_state="repair_confirmed",
        repair_confirmed_at=previous_at.isoformat(),
    )

    result = build_live_recommendations(
        [],
        _market(
            sentiment={"phase": "ice", "failed_limit_up_rate": 0.54},
            sealed_count=20,
            failed_count=12,
            failed_rate=0.375,
            sealed_change=-2,
            failed_change=2,
        ),
        current_at,
        previous_snapshot=previous,
    )

    gate = result["market_gate"]
    assert gate["passed"] is False
    assert gate["repair_state"] == "repair_revoked"
    assert "炸板率" in gate["repair_revoked_reason"]
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q -k "market_repair_stays or market_repair_is_revoked"
```

Expected: both tests fail because the current market gate does not persist `repair_state`.

- [ ] **Step 3: Add a public pure gate builder and same-day previous-state reader**

In `live_policy.py`, expose the gate without duplicating policy in the service:

```python
def build_live_market_gate(
    context: Mapping[str, object],
    captured_at: datetime,
    previous_snapshot: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return _market_gate(
        context,
        session_stage(captured_at),
        captured_at,
        previous_snapshot,
    )
```

Change `build_live_recommendations` to accept an optional precomputed gate and otherwise call this builder:

```python
def build_live_recommendations(
    candidates: Sequence[Mapping[str, object]],
    market_context: Mapping[str, object],
    captured_at: datetime,
    previous_snapshot: Mapping[str, object] | None = None,
    *,
    market_gate: Mapping[str, object] | None = None,
) -> dict[str, object]:
    stage = session_stage(captured_at)
    resolved_market_gate = dict(
        market_gate
        or build_live_market_gate(market_context, captured_at, previous_snapshot)
    )
```

Implement `_same_day_previous_gate` by parsing `previous_snapshot["captured_at"]`, converting it with `_local_datetime`, comparing it to the current Shanghai date, and returning `previous_snapshot["recommendations"]["market_gate"]` only for the same date.

- [ ] **Step 4: Implement the state transition**

Replace the one-frame repair boolean with these rules:

```python
health_reasons = []
if not auction_stage and sealed_count < 5:
    health_reasons.append("主板封板家数不足5只")
if not auction_stage and failed_rate is not None and failed_rate > 0.35:
    health_reasons.append(f"实时炸板率{failed_rate * 100:.1f}%超过35%")

instant_repair = bool(
    prior_weak
    and not auction_stage
    and not health_reasons
    and sealed_change > 0
    and failed_change < 0
)
previous_state = str(previous_gate.get("repair_state") or "pending_repair")
previous_confirmed = previous_state == "repair_confirmed"

if instant_repair:
    repair_state = "repair_confirmed"
elif previous_confirmed and health_reasons:
    repair_state = "repair_revoked"
elif previous_confirmed:
    repair_state = "repair_confirmed"
elif previous_state == "repair_revoked":
    repair_state = "repair_revoked"
else:
    repair_state = "pending_repair" if prior_weak else "not_required"
```

Preserve `repair_confirmed_at` while confirmed; set it to the current timestamp on a new confirmation. Return `repair_state`, `repair_confirmed`, `repair_confirmed_at`, `repair_evidence_at`, and `repair_revoked_reason` in the gate payload.

- [ ] **Step 5: Run focused and existing market-gate tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q -k "market_gate or market_repair"
```

Expected: all selected tests pass.

---

### Task 2: Remove duplicated D-1 market blockers after confirmed repair

**Files:**

- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `alphaagent/server/services/limit_up/lane_research.py`

- [ ] **Step 1: Add a failing live two-to-three test**

Create a fixture whose only blockers before the live override are `market_retreat` and `market_failed_rate_high`. Assert that `_attach_lane_decisions(..., market_gate={"repair_confirmed": True})` removes only those two blockers, while a second fixture with `prior_board_evidence_missing` remains blocked.

```python
def test_confirmed_live_repair_removes_only_duplicated_d1_market_blockers() -> None:
    candidate = _candidate(
        "600001.SSE",
        board_level=3,
        previous_limit_up=True,
        lane_feature_ready=True,
        sector_heat=70.0,
        sector_dragon_rank=1,
        auction_gap_pct=3.0,
        prior_turnover_rate=15.0,
        prior_amount_ratio_5d=1.5,
        prior_amplitude_pct=7.0,
        prior_low_change_pct=-1.0,
        prior_market_two_to_three_rate=0.30,
        prior_board={
            "is_sealed": True,
            "first_limit_time": "10:10:00",
            "last_limit_time": "10:25:00",
            "open_times": 1,
        },
        financial_snapshot={"publish_date": "2026-06-30"},
    )
    live_service._attach_lane_decisions(
        [candidate],
        _market(sentiment={"phase": "ice", "failed_limit_up_rate": 0.54}),
        datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
        market_gate={"repair_confirmed": True},
    )

    assert "market_retreat" not in candidate["lane_blockers"]
    assert "market_failed_rate_high" not in candidate["lane_blockers"]
```

- [ ] **Step 2: Run the new test and confirm the signature failure**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py::test_confirmed_live_repair_removes_only_duplicated_d1_market_blockers -q
```

Expected: FAIL because `_attach_lane_decisions` does not accept `market_gate`.

- [ ] **Step 3: Compute the gate before lane evaluation**

Import `build_live_market_gate` in `live_service.py`. In `build_live_snapshot`, compute it immediately after `_market_context`:

```python
market_gate = build_live_market_gate(
    market_context,
    local_at,
    previous_snapshot,
)
_attach_lane_decisions(
    sector_front,
    market_context,
    local_at,
    market_gate=market_gate,
)
recommendations = build_live_recommendations(
    ranked,
    market_context,
    local_at,
    previous_snapshot=previous_snapshot,
    market_gate=market_gate,
)
```

- [ ] **Step 4: Pass an explicit live-only flag into lane research**

Add an optional keyword argument to `_attach_lane_decisions` and `_live_research_candidate`, then emit:

```python
"live_market_repair_confirmed": bool(
    market_gate and market_gate.get("repair_confirmed")
),
```

In `lane_research._shared_blockers`, guard only the two D-1 market checks:

```python
live_repair = candidate.get("live_market_repair_confirmed") is True
if lane != "first_board" and not live_repair:
    # existing phase and failed-rate blockers
```

Do not bypass industry heat, leader rank, prior-board evidence, risk stack, fundamental risk, or high-board L2 checks.

- [ ] **Step 5: Run lane and live regression tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_live.py -q
```

Expected: all tests pass.

---

### Task 3: Separate hard rejection from temporary trigger confirmation

**Files:**

- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `alphaagent/server/services/limit_up/live_policy.py`

- [ ] **Step 1: Add failing state-classification tests**

Add three tests:

```python
def test_market_pending_keeps_structurally_eligible_near_limit_candidate_approaching() -> None:
    signal = build_live_recommendations(
        [_candidate("600001.SSE", state="near_limit", distance_to_limit_pct=0.6)],
        _market(
            sentiment={"phase": "ice", "failed_limit_up_rate": 0.54},
            sealed_change=0,
            failed_change=0,
        ),
        datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
    )["lanes"]["now"][0]

    assert signal["action"] == "observe"
    assert signal["signal_state"] == "approaching_trigger"
    assert signal["blocking_scope"] == "market"


def test_structural_lane_failure_is_rejected() -> None:
    candidate = _candidate(
        "600001.SSE",
        state="near_limit",
        lane_decision="blocked",
        lane_blockers=["limit_up_gene_missing"],
    )
    signal = build_live_recommendations(
        [candidate],
        _market(),
        datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
    )["lanes"]["now"][0]

    assert signal["action"] == "pass"
    assert signal["signal_state"] == "rejected"
    assert signal["blocking_scope"] == "structural"


def test_sweep_checks_expose_the_same_heat_and_expansion_thresholds_used_to_trigger() -> None:
    candidate = _candidate(
        "600001.SSE",
        state="near_limit",
        distance_to_limit_pct=0.5,
        sector_heat=55,
        sector_touch_count=2,
    )
    signal = build_live_recommendations(
        [candidate],
        _market(),
        datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
    )["lanes"]["now"][0]

    assert signal["signal_state"] == "approaching_trigger"
    checks = {check["code"]: check for check in signal["trigger_checks"]}
    assert checks["sector_heat"]["required"] == ">=60"
    assert checks["sector_expansion"]["required"] == ">=3只"
```

- [ ] **Step 2: Run the tests and confirm current invalidation behavior**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q -k "market_pending_keeps or structural_lane_failure_is_rejected or sweep_checks_expose"
```

Expected: all new tests fail with the old `invalidated/pass` behavior or absent checks.

- [ ] **Step 3: Replace hidden boolean sweep logic with structured checks**

Add constants for the existing thresholds and return checks with `code`, `label`, `status`, `observed`, and `required`:

```python
SWEEP_MAX_DISTANCE_PCT = 1.0
SWEEP_MIN_SECTOR_HEAT = 60.0
SWEEP_MIN_SECTOR_TOUCH_COUNT = 3
BASE_MIN_SECTOR_HEAT = 45.0
BASE_MIN_SECTOR_TOUCH_COUNT = 2
```

Create `_candidate_execution_checks(candidate, entry_kind, require_expansion)` and derive both `_candidate_execution_reasons` and `_sweep_ready` from those checks. Missing or currently weak dynamic values use `status="pending"`; structural lane checks remain `failed`.

- [ ] **Step 4: Make `_now_signal` classify in this order**

Implement the order explicitly:

1. Already sealed/resealed without a prior trigger: `pass/missed`.
2. Structural lane or board restriction: `pass/rejected` with `blocking_scope="structural"`.
3. Market state pending/revoked: `observe/approaching_trigger` for a near-limit candidate with `blocking_scope="market"`.
4. Dynamic execution checks pending: `observe/approaching_trigger` with `blocking_scope="dynamic"`.
5. All checks passed and candidate remains pre-seal: `buy_now/trigger_ready`.

Extend `_signal` with optional keyword arguments:

```python
signal_state: str | None = None,
blocking_scope: str = "none",
pending_reasons: Sequence[str] = (),
```

Store those fields in the signal. Extend `_trigger_checks` with the exact execution checks used for the action.

- [ ] **Step 5: Keep validation from hiding research triggers**

Retain `_apply_signal_validation` behavior that changes automatic `action`, but add an assertion that `research_action`, `signal_state`, `blocking_scope`, and `trigger_checks` survive unchanged.

- [ ] **Step 6: Run all live-policy tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_next_session_plan.py tests/alphaagent/test_limit_up_forward_validation.py -q
```

Expected: all tests pass.

---

### Task 4: Persist complete two-day decision evidence

**Files:**

- Modify: `tests/alphaagent/test_limit_up_live_trace.py`
- Modify: `alphaagent/server/services/limit_up/live_trace_repository.py`
- Modify: `alphaagent/server/services/limit_up/live_trace_service.py`

- [ ] **Step 1: Expand the projection test**

Update `test_trace_projection_keeps_diagnostics_without_full_research_payload` so the projected candidate retains:

```python
"sector_heat": 62.5,
"sector_touch_count": 3,
"sector_main_net_inflow": 120_000_000.0,
"stock_main_net_inflow": 30_000_000.0,
"turnover_rate": 8.2,
"portfolio_selected": True,
```

and still drops `financial_snapshot` and the full `historical_evidence` payload.

- [ ] **Step 2: Add signal evidence fields to trace fixtures**

Make `_trace_signal` include `blocking_scope`, `pending_reasons`, and structured `trigger_checks`. Assert the symbol event returned by `build_symbol_trace` preserves these fields and the market gate `repair_state/repair_confirmed_at`.

- [ ] **Step 3: Run trace tests and confirm projection failure**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live_trace.py -q
```

Expected: projection assertions fail before the field lists are expanded.

- [ ] **Step 4: Extend the compact whitelists and event serializer**

Add only decision evidence to `TRACE_CANDIDATE_FIELDS` and `TRACE_SIGNAL_FIELDS`; do not persist financial statements or full analog samples. Extend `_normalized_state`/event serialization in `live_trace_service.py` with the new scalar fields and checks.

- [ ] **Step 5: Run live trace and API tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live_trace.py tests/alphaagent/test_api.py -q
```

Expected: all tests pass.

---

### Task 5: Present the real state without “hard gate” ambiguity

**Files:**

- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/features/limitUp/nextSessionPlan.ts`
- Modify: `frontend/src/features/limitUp/nextSessionPlan.spec.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Modify: `frontend/src/features/limitUp/liveTrace.ts`
- Modify: `frontend/src/features/limitUp/liveTrace.spec.ts`

- [ ] **Step 1: Add failing presentation tests**

Add cases asserting:

```typescript
expect(signalStatePresentation(signal("rejected"))).toEqual({
  label: "硬性排除",
  tone: "negative",
});

expect(signalStatePresentation({
  ...signal("approaching_trigger"),
  blocking_scope: "market",
})).toEqual({
  label: "等待市场修复",
  tone: "warning",
});
```

Keep the existing assertion that `trigger_ready + research_only + action=pass` remains “买点触发（人工确认）”.

- [ ] **Step 2: Extend API types**

Add:

```typescript
blocking_scope?: "none" | "market" | "dynamic" | "structural" | string;
pending_reasons?: string[];
```

to `LimitUpLiveSignal`, repair metadata to `recommendations.market_gate`, and decision-evidence fields to `LimitUpLiveTraceEvent`.

- [ ] **Step 3: Update the pure status mapping**

Change `signalStatePresentation` to accept `blocking_scope`. Map market waiting before generic approaching, map `rejected` to “硬性排除”, and retain all trigger/missed/stale precedence.

- [ ] **Step 4: Show one concise missing condition**

In the existing recommendation row, render `pending_reasons[0]` as the main reason and `还差 N 项` when more remain. Do not add a new card, strategy switch, or explanatory section.

- [ ] **Step 5: Update trace labels and run frontend tests**

Run:

```bash
cd frontend && pnpm vitest run src/features/limitUp/nextSessionPlan.spec.ts src/features/limitUp/liveTrace.spec.ts
```

Expected: all selected tests pass.

- [ ] **Step 6: Run the production build**

Run:

```bash
cd frontend && pnpm build
```

Expected: TypeScript and Vite production build complete without errors.

---

### Task 6: Replay, regress, and deploy the completed behavior

**Files:**

- Update: `memory/03_data/data_flow.md`
- Create: `memory/06_backtests/limit_up_live_gate_replay_20260714.md`

- [ ] **Step 1: Run the full relevant backend suite**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_*.py tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_api.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Rebuild the API and web containers**

Run:

```bash
docker compose up -d --build alphaagent-api alphaagent-web alphaagent-gateway
docker compose ps
```

Expected: API and gateway are healthy; web is running.

- [ ] **Step 3: Replay the saved 2026-07-14 snapshots**

Use `load_snapshots_between` and the new pure `build_live_market_gate/build_live_recommendations` functions inside the API container. Process snapshots in timestamp order while passing the previous reconstructed snapshot. Record:

- first repair confirmation and any revocation;
- number of `approaching_trigger`, `trigger_ready`, `rejected`, and `missed` transitions;
- every trigger timestamp, symbol, pre-seal state, and later same-day sealed/failed outcome;
- candidates that remain excluded because of structural or execution checks.

The replay must not mutate `limit_up_signal_snapshots` or `limit_up_live_trace_snapshots`.

- [ ] **Step 4: Write the compact replay evidence**

Write the counts, trigger table, false-positive checks, and known data limitations to `memory/06_backtests/limit_up_live_gate_replay_20260714.md`. Update the current-state paragraph in `memory/03_data/data_flow.md` and link to the report; do not append a chat-style chronology.

- [ ] **Step 5: Verify the API payload**

Authenticate through the existing local gateway or call the service in the API container. Confirm the latest payload contains `repair_state`, stable `repair_confirmed_at`, `blocking_scope`, and exact `trigger_checks`, and that stale snapshots still force all actions to pass.

- [ ] **Step 6: Verify desktop and mobile UI with Playwright**

Open `http://localhost:8080/limit-up` at `1440x1000` and `390x844`. Confirm:

- “等待市场修复”, “接近买点，还差 N 项”, “硬性排除”, “买点触发（人工确认）”, and “已封板，错过不追” render from the correct fixture/live states;
- current candidates and two-day trace do not overlap or cause whole-page horizontal scrolling;
- no console errors or failed limit-up API requests occur.

- [ ] **Step 7: Check the final diff without committing**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors. Report all pre-existing and newly changed files separately; do not commit until explicitly authorized.
