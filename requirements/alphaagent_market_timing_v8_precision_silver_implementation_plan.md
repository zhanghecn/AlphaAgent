# Precision-First Silver Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop emitting statistically failed ordinary breakdown silver events while preserving every gold, top-silver, and structural-silver event.

**Architecture:** Keep factor computation and public setup constants unchanged. Narrow `candidate_setup` at its existing arbitration boundary so an ordinary silver zone with `trend_breakdown >= SILVER_ENTER` returns neutral unless the independently computed structural-breakdown flag is true.

**Tech Stack:** Python 3.13, pytest, FastAPI service layer, PostgreSQL panel cache, Docker Compose.

---

### Task 1: Lock the signal boundary with failing tests

**Files:**
- Modify: `tests/alphaagent/services/quant/test_market_timing_no_lookahead.py`

- [x] **Step 1: Add an ordinary-breakdown fixture and regression test**

```python
def _ordinary_breakdown_factor(day: date) -> fac.MarketTimingFactors:
    return fac.MarketTimingFactors(
        trade_date=day,
        phase="retreat",
        trend=40.0,
        momentum=40.0,
        breadth=40.0,
        structure=50.0,
        volume=50.0,
        bull_force=40.0,
        bear_force=70.0,
        close_above_ma20=False,
        mom_5d=-2.0,
        mom_20d=-3.0,
        macd_top=42.0,
        breadth_top=68.0,
        evidence={"trend_breakdown": 88.0},
    )


def test_ordinary_breakdown_silver_is_suppressed_without_structural_consensus():
    factor = _ordinary_breakdown_factor(date(2026, 7, 7))

    assert sig.candidate_direction(factor) == "SILVER"
    assert sig.candidate_setup(factor) == (None, None)
    assert sig.detect_events([factor], [100.0], [0.0]) == []
```

- [x] **Step 2: Add an explicit retained-top-silver assertion**

```python
def test_top_silver_remains_available():
    factor = _timing_factor(date(2026, 5, 29), "SILVER")

    assert sig.candidate_setup(factor) == ("SILVER", sig.SETUP_TOP_SILVER)
```

- [x] **Step 3: Run the focused tests and verify the new ordinary-breakdown test fails**

Run:

```bash
uv run --group server pytest tests/alphaagent/services/quant/test_market_timing_no_lookahead.py -q -k "ordinary_breakdown or top_silver"
```

Expected: the ordinary-breakdown assertion fails because v7 still returns `BREAKDOWN_SILVER`; the retained-top test passes.

### Task 2: Apply the minimal arbitration change

**Files:**
- Modify: `alphaagent/server/services/quant/market_timing/signal.py`
- Test: `tests/alphaagent/services/quant/test_market_timing_no_lookahead.py`

- [x] **Step 1: Update the module history and suppress only ordinary breakdown silver**

```python
# In candidate_setup, after candidate_direction(factor):
if direction == "SILVER":
    breakdown = float(factor.evidence.get("trend_breakdown") or 0.0)
    if breakdown >= SILVER_ENTER:
        return None, None
    return direction, SETUP_TOP_SILVER
```

Keep `SETUP_BREAKDOWN_SILVER` defined for stored payload and frontend compatibility. Do not change factor thresholds, gold logic, structural-breakdown priority, danger-state logic, or confirmation status handling.

- [x] **Step 2: Run the focused tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/services/quant/test_market_timing_no_lookahead.py -q -k "ordinary_breakdown or top_silver or structural_breakdown"
```

Expected: all selected tests pass.

- [x] **Step 3: Run the complete market-timing suite**

Run:

```bash
uv run --group server pytest tests/alphaagent/services/quant/test_market_timing_no_lookahead.py tests/alphaagent/services/quant/test_market_timing_backtest.py tests/alphaagent/services/quant/test_market_timing_intraday.py -q
```

Expected: all tests pass with no gold or structural-silver regressions.

### Task 3: Refresh the real panel and record the durable result

**Files:**
- Modify: `memory/07_market_timing/market_timing_design.md`

- [x] **Step 1: Rebuild the API and refresh the persisted panel**

Run:

```bash
docker compose up -d --build alphaagent-api
docker compose exec -T alphaagent-api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/market-timing/refresh', timeout=120).read().decode())"
```

Expected: the API becomes healthy and refresh returns a successful response ending on the latest market date.

- [x] **Step 2: Verify real event signatures and accuracy**

Read `market_timing_panel.panel` and assert:

```python
assert not [event for event in signals if event["setup_type"] == "BREAKDOWN_SILVER"]
assert len([event for event in signals if event["direction"] == "GOLD"]) == 55
assert len([event for event in signals if event["direction"] == "SILVER"]) == 9
assert event_by_date["2026-03-13"]["setup_type"] == "STRUCTURAL_BREAKDOWN_SILVER"
assert event_by_date["2026-06-11"]["setup_type"] == "REVERSAL_GOLD"
assert "2026-07-07" not in event_by_date
```

Compare the gold signature with pre-change SHA-256 `b30746cbe057084f798153d8ec1c5fc1a71acd573425d3182a35eecb0c90018e` and the retained-silver signature with `f50ad5ab8292f4731f9797b89d0db53cf4e208fa29f75120ffdbac0d118188ba`.

- [x] **Step 3: Update current-state memory**

Replace stale v7 signal counts and limitations with v8 facts: ordinary breakdown silver disabled, gold signature unchanged, strict silver count and candidate-date statistics, verification commands, and the remaining small-sample risk.

- [x] **Step 4: Commit only market-timing files**

```bash
git add alphaagent/server/services/quant/market_timing/signal.py \
  tests/alphaagent/services/quant/test_market_timing_no_lookahead.py \
  memory/07_market_timing/market_timing_design.md \
  requirements/alphaagent_market_timing_v8_precision_silver_implementation_plan.md
git commit -m "fix(market-timing): remove unreliable breakdown silver signals"
```

Expected: unrelated dirty limit-up work remains unstaged.
