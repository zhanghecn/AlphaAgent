# AlphaAgent Limit-Up Top5 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only `/limit-up` MVP that ranks the latest main-board limit-up events into market dragon Top5 and runs a conservative historical proxy backtest without treating fast sealed boards as filled.

**Architecture:** Add a feature-first `alphaagent.server.services.limit_up` package containing pure domain rules, database loading, and orchestration. Expose two read-only FastAPI endpoints and a React Query page. Reuse current event, sector-flow, membership, daily-bar, and stock-flow tables; do not add schema or mutate product baselines in this MVP.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy Core, PostgreSQL, pytest, React 18, TypeScript, TanStack Query, Tailwind, Vite.

---

## Scope

This plan implements one vertical slice from the approved design:

- Main-board, non-ST 10cm events only.
- Latest post-close dashboard from existing `limit_pool_zt` and `limit_pool_zbgc` rows.
- Previous available concept-fund-flow date as the no-lookahead sector input for historical proxy ranking.
- Board-internal dragon rank, then market Top5.
- Conservative and optimistic fill scenarios.
- D+1 open exit with costs.
- Explicit data coverage and proxy limitations.

This MVP does not implement Tick/L2 queue simulation, LightGBM training, intraday sector snapshots, persisted backtest runs, or live order placement. Those remain blocked by historical snapshot coverage and follow after the MVP validates field semantics.

## File Map

- Create `alphaagent/server/services/limit_up/domain.py`: pure parsing, ranking, fill, price, and metric rules.
- Create `alphaagent/server/services/limit_up/repository.py`: read-only SQLAlchemy queries and normalized row loading.
- Create `alphaagent/server/services/limit_up/service.py`: dashboard and proxy-backtest orchestration.
- Create `alphaagent/server/services/limit_up/__init__.py`: public service exports.
- Create `alphaagent/server/api/limit_up.py`: HTTP parameter validation and response wrapping.
- Modify `alphaagent/server/api/router.py`: register the feature router.
- Create `tests/alphaagent/test_limit_up_mvp.py`: pure unit tests and route contract tests.
- Create `frontend/src/api/limitUp.ts`: typed API contracts and fetchers.
- Create `frontend/src/pages/LimitUpPage.tsx`: dense Top5 and proxy-backtest workspace.
- Modify `frontend/src/App.tsx`: lazy route registration.
- Modify `frontend/src/components/AppShell.tsx`: navigation entry using the existing shell.
- Modify `memory/03_data/data_flow.md`, `memory/06_backtests/README.md`, and `memory/09_decisions/decisions.md` only after verified local results exist.

### Task 1: Pure Limit-Up Domain Rules

**Files:**
- Create: `alphaagent/server/services/limit_up/domain.py`
- Create: `tests/alphaagent/test_limit_up_mvp.py`

- [ ] **Step 1: Write failing tests for main-board filtering and fast-board fills**

```python
from alphaagent.server.services.limit_up.domain import (
    event_fill_status,
    is_eligible_main_board,
)


def test_limit_up_mvp_excludes_non_main_board_and_st() -> None:
    assert is_eligible_main_board("600001.SSE", "主板样本") is True
    assert is_eligible_main_board("002001.SZSE", "深市样本") is True
    assert is_eligible_main_board("300001.SZSE", "创业样本") is False
    assert is_eligible_main_board("688001.SSE", "科创样本") is False
    assert is_eligible_main_board("600002.SSE", "ST样本") is False


def test_limit_up_mvp_fast_sealed_board_is_not_filled() -> None:
    event = {"first_limit_time": "093001", "open_times": 0}
    assert event_fill_status(event, "conservative") == "unfilled_fast_board"
    assert event_fill_status(event, "optimistic") == "unfilled_fast_board"


def test_limit_up_mvp_resealed_board_is_conservatively_fillable() -> None:
    event = {"first_limit_time": "101500", "open_times": 2}
    assert event_fill_status(event, "conservative") == "filled_reseal_proxy"
```

- [ ] **Step 2: Run the tests and verify import failure**

Run: `uv run pytest tests/alphaagent/test_limit_up_mvp.py -q`

Expected: FAIL because `alphaagent.server.services.limit_up.domain` does not exist.

- [ ] **Step 3: Implement the pure domain module**

Implement these stable interfaces:

```python
def normalize_limit_time(value: object) -> str | None: ...
def is_eligible_main_board(vt_symbol: str, name: str) -> bool: ...
def event_fill_status(event: dict[str, object], scenario: str) -> str: ...
def main_board_limit_price(previous_close: float) -> float: ...
def percentile_ranks(values: dict[str, float | None]) -> dict[str, float]: ...
def rank_dragon_candidates(events: list[dict[str, object]], *, limit: int = 5) -> list[dict[str, object]]: ...
def summarize_proxy_trades(trades: list[dict[str, object]]) -> dict[str, object]: ...
```

`event_fill_status` rules:

```python
if first_limit_time <= "09:31:00" and open_times == 0:
    return "unfilled_fast_board"
if scenario == "conservative" and open_times <= 0:
    return "unfilled_queue_unknown"
if scenario == "conservative":
    return "filled_reseal_proxy"
return "filled_non_fast_proxy"
```

`rank_dragon_candidates` first sorts within `sector_id`, keeps sector dragon rank 1-2, then sorts globally by `dragon_score`, caps to `limit`, and assigns `market_dragon_rank`.

- [ ] **Step 4: Run pure tests**

Run: `uv run pytest tests/alphaagent/test_limit_up_mvp.py -q`

Expected: PASS for filtering, time normalization, ranking cap, fast-board rejection, and summary calculations.

### Task 2: Read-Only Repository

**Files:**
- Create: `alphaagent/server/services/limit_up/repository.py`
- Modify: `tests/alphaagent/test_limit_up_mvp.py`

- [ ] **Step 1: Add repository normalization tests**

```python
from alphaagent.server.services.limit_up.repository import normalize_event_row


def test_limit_up_event_row_normalizes_chinese_raw_fields() -> None:
    row = {
        "vt_symbol": "600001.SSE",
        "event_date": "20260709",
        "event_type": "limit_pool_zt",
        "raw": {
            "名称": "主板样本",
            "最新价": 11.0,
            "首次封板时间": "093502",
            "最后封板时间": "101000",
            "炸板次数": 1,
            "连板数": 2,
            "封板资金": 100000000,
            "成交额": 600000000,
            "流通市值": 5000000000,
            "换手率": 12.3,
        },
    }
    item = normalize_event_row(row)
    assert item["trade_date"] == "2026-07-09"
    assert item["first_limit_time"] == "09:35:02"
    assert item["limit_times"] == 2
    assert item["is_sealed"] is True
```

- [ ] **Step 2: Implement repository functions**

```python
def normalize_event_row(row: Mapping[str, object]) -> dict[str, object]: ...
def load_limit_up_dataset(start: date | None = None, end: date | None = None) -> dict[str, object]: ...
```

`load_limit_up_dataset` returns one bounded data bundle:

```python
{
    "events": [...],
    "memberships": [...],
    "sector_flows": [...],
    "stock_flows": [...],
    "daily_bars": [...],
    "coverage": {
        "event_start": "2026-06-12",
        "event_end": "2026-07-09",
        "event_trade_days": 21,
        "sector_flow_trade_days": 15,
    },
}
```

Use one query per table, bounded by requested dates and relevant symbols. Controllers must not issue SQL directly.

- [ ] **Step 3: Run repository normalization tests**

Run: `uv run pytest tests/alphaagent/test_limit_up_mvp.py -q`

Expected: PASS.

### Task 3: Dashboard and Dragon Top5 Service

**Files:**
- Create: `alphaagent/server/services/limit_up/service.py`
- Create: `alphaagent/server/services/limit_up/__init__.py`
- Modify: `tests/alphaagent/test_limit_up_mvp.py`

- [ ] **Step 1: Add service tests with an injected data bundle**

```python
from alphaagent.server.services.limit_up.service import build_limit_up_dashboard


def test_limit_up_dashboard_returns_only_five_market_dragons(sample_limit_up_dataset) -> None:
    dashboard = build_limit_up_dashboard(sample_limit_up_dataset)
    assert dashboard["status"] == "ready"
    assert len(dashboard["top_dragons"]) <= 5
    assert all(item["sector_dragon_rank"] <= 2 for item in dashboard["top_dragons"])
    assert dashboard["limitations"]
```

- [ ] **Step 2: Implement the dashboard orchestration**

```python
def build_limit_up_dashboard(dataset: dict[str, object]) -> dict[str, object]: ...
def get_limit_up_dashboard() -> dict[str, object]: ...
```

For the latest event date, attach the latest available same-day sector flow for display, calculate cross-sectional percentiles, then calculate:

```text
dragon_score = 35 * sector_flow_percentile
             + 25 * position_score
             + 20 * seal_strength_score
             + 10 * stock_flow_percentile
             + 10 * turnover_quality_score
```

The latest dashboard is explicitly `mode=post_close_snapshot`, because current event rows contain final daily seal fields.

- [ ] **Step 3: Run dashboard tests**

Run: `uv run pytest tests/alphaagent/test_limit_up_mvp.py -q`

Expected: PASS.

### Task 4: Conservative Historical Proxy Backtest

**Files:**
- Modify: `alphaagent/server/services/limit_up/service.py`
- Modify: `tests/alphaagent/test_limit_up_mvp.py`

- [ ] **Step 1: Add fast-board and D+1 return tests**

```python
from alphaagent.server.services.limit_up.service import build_limit_up_proxy_backtest


def test_proxy_backtest_does_not_trade_fast_board(sample_limit_up_dataset) -> None:
    report = build_limit_up_proxy_backtest(sample_limit_up_dataset, exit_mode="next_open")
    fast = next(item for item in report["orders"] if item["vt_symbol"] == "600001.SSE")
    assert fast["conservative_status"] == "unfilled_fast_board"
    assert all(trade["vt_symbol"] != "600001.SSE" for trade in report["scenarios"]["conservative"]["trades"])
```

- [ ] **Step 2: Implement the proxy backtest**

```python
def build_limit_up_proxy_backtest(
    dataset: dict[str, object],
    *,
    exit_mode: str = "next_open",
    commission_rate: float = 0.0003,
    stamp_tax_rate: float = 0.0005,
    slippage_bps: float = 10.0,
) -> dict[str, object]: ...

def get_limit_up_proxy_backtest(start: date | None, end: date | None, exit_mode: str) -> dict[str, object]: ...
```

Historical ranking uses the previous available concept-flow date, prior board streak, current first-touch time, and prior daily liquidity. It does not use current final seal amount for ranking. Produce `conservative` and `optimistic` scenarios, D+1 open returns, cumulative equal-weight equity, orders, trades, and coverage warnings.

- [ ] **Step 3: Run backtest tests**

Run: `uv run pytest tests/alphaagent/test_limit_up_mvp.py -q`

Expected: PASS, including no-lookahead input assertions and fast-board non-fill.

### Task 5: FastAPI Contract

**Files:**
- Create: `alphaagent/server/api/limit_up.py`
- Modify: `alphaagent/server/api/router.py`
- Modify: `tests/alphaagent/test_limit_up_mvp.py`

- [ ] **Step 1: Add route contract tests**

```python
def test_limit_up_dashboard_route_registered(monkeypatch) -> None:
    monkeypatch.setattr(limit_up_api, "get_limit_up_dashboard", lambda: {"status": "ready", "top_dragons": []})
    response = TestClient(create_app()).get("/api/limit-up/dashboard")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ready"


def test_limit_up_backtest_rejects_invalid_exit_mode() -> None:
    response = TestClient(create_app()).get("/api/limit-up/backtest?exit_mode=invalid")
    assert response.status_code == 422
```

- [ ] **Step 2: Implement and register the router**

```python
router = APIRouter(prefix="/limit-up", tags=["limit-up"])

@router.get("/dashboard", response_model=None)
def dashboard(): ...

@router.get("/backtest", response_model=None)
def backtest(
    start: date | None = None,
    end: date | None = None,
    exit_mode: Literal["next_open", "next_close"] = "next_open",
): ...
```

Use `ok`, `fail`, and `JSONResponse`; return 503 for missing database and a safe 500 envelope for unexpected errors.

- [ ] **Step 3: Run route and unit tests**

Run: `uv run pytest tests/alphaagent/test_limit_up_mvp.py -q`

Expected: PASS.

### Task 6: React Workbench

**Files:**
- Create: `frontend/src/api/limitUp.ts`
- Create: `frontend/src/pages/LimitUpPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/AppShell.tsx`

- [ ] **Step 1: Add typed API contracts**

Define `LimitUpDashboard`, `LimitUpDragon`, `LimitUpSector`, `LimitUpBacktest`, and `LimitUpScenario`, then expose:

```typescript
export function fetchLimitUpDashboard() {
  return apiClient.get<LimitUpDashboard>("/limit-up/dashboard");
}

export function fetchLimitUpBacktest(exitMode: "next_open" | "next_close" = "next_open") {
  return apiClient.get<LimitUpBacktest>(`/limit-up/backtest?exit_mode=${exitMode}`);
}
```

- [ ] **Step 2: Build the page**

Use React Query with a 30-second dashboard refresh and no automatic backtest refresh. The page contains:

- compact page header and data-mode warning;
- one unframed summary strip;
- two-column sector-fund ranking and dragon Top5 table;
- selected-dragon evidence panel;
- proxy-backtest section with conservative/optimistic comparison and recent trades;
- loading, unavailable, insufficient-data, and error states.

Use existing `rise`/`fall`, border, background, and typography tokens. Do not add gradients, hero copy, nested cards, decorative motion, or a metric-card wall.

- [ ] **Step 3: Register route and navigation**

Add lazy route `/limit-up` in `App.tsx` and a `Flame` icon navigation item labeled `打板研究` in `AppShell.tsx`.

- [ ] **Step 4: Build the frontend**

Run: `pnpm --dir frontend run build`

Expected: TypeScript and Vite build succeed.

### Task 7: Local Data Run, Browser Verification, and Memory

**Files:**
- Modify after verification: `memory/03_data/data_flow.md`
- Modify after verification: `memory/06_backtests/README.md`
- Modify after verification: `memory/09_decisions/decisions.md`

- [ ] **Step 1: Run focused backend verification**

Run:

```bash
uv run pytest tests/alphaagent/test_limit_up_mvp.py -q
uv run python -m compileall alphaagent/server/api/limit_up.py alphaagent/server/services/limit_up
```

Expected: all tests pass and compileall exits 0.

- [ ] **Step 2: Rebuild API and web services**

Run:

```bash
docker compose up -d --build alphaagent-api alphaagent-web
```

Expected: both services start; `docker compose ps` reports API healthy.

- [ ] **Step 3: Smoke-test real endpoints**

Run inside the API container or through the gateway with authentication:

```bash
curl -fsS http://localhost:8000/api/limit-up/dashboard
curl -fsS 'http://localhost:8000/api/limit-up/backtest?exit_mode=next_open'
```

Expected: wrapped success responses with real coverage, Top5, fast-board rejected orders, and two scenarios.

- [ ] **Step 4: Verify `/limit-up` in Playwright**

Open desktop and mobile viewports. Confirm no overlap, Top5 cap, readable table scrolling, loading/error states, and real endpoint data. Save no screenshots as long-lived artifacts unless needed for a defect report.

- [ ] **Step 5: Record durable verified facts**

Update memory with the exact event/flow coverage, endpoint commands, proxy-backtest metrics, and limitation that Tick/L2 queue execution remains unimplemented.

- [ ] **Step 6: Check worktree quality**

Run: `git diff --check`

Expected: no whitespace errors. Do not commit because project rules require explicit user authorization.

## Plan Self-Review

- The MVP covers the requested visible first version, Top5 ranking, existing-backtest comparison, historical proxy selection, success/return reporting, and fast-board non-fill.
- Exact Tick/L2 execution and multi-year sector-flow history are intentionally not claimed by the MVP; both are surfaced as data limitations.
- Backend types use snake_case consistently with existing APIs; frontend types match those keys.
- The service function names used by API and tests are defined once and match across tasks.
- No production database write or strategy baseline mutation occurs in this plan.
