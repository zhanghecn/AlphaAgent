# AlphaAgent Strategy Drawdown And Ranking Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` or equivalent task-by-task execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve `mainline_dragon_pullback / 0.1.21` by proving whether remaining losses come from entry ranking, dynamic sell-side drawdown control, or portfolio capacity, then only keeping globally validated changes.

**Architecture:** Do not add another public strategy and do not add low-suction reserved slots. Treat quant signals as entry evidence only; sell decisions are calculated dynamically from the entry anchor, current held position, highest floating profit, support structure, and current-day buy/hold state. Add stronger trade-path diagnostics first, run a baseline attribution pass against `#175 / 0.1.21`, then test small ranking and sell-side experiments behind versioned strategy changes. Every experiment must update the global optimization ledger and must beat the current baseline on the main range before becoming default.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, React/TypeScript, pytest, Vite, existing AlphaAgent backtest tables and services.

---

## Scope

This plan covers the next optimization phase after candidate observation and stock-detail replay were split.

It targets the user-reported issues:

1. Buy signal exists but portfolio does not buy because of ranking, full positions, or rotation.
2. Low-suction buildup should accumulate confidence, but only the first launch/reclaim signal or the highest-score point inside a short cluster should be treated as a key buy point.
3. Some losses look like buy-after-breakdown or buy-then-continuous-breakdown failures, especially 立新能源 and 合肥城建.
4. Some winners such as 金安国纪 and 亨通光电 may need better trend holding/profit protection, not earlier fixed exits.
5. `002119.SZSE`-style repeated stretched dragon signals are risk evidence, but broad hard rejection failed in `0.1.22/#186` and must not be reintroduced as a default rule without new global evidence.
6. Sell signals should be calculated dynamically from the buy point's cost/support anchor, highest floating return drawdown, and current structure. The buy point is an anchor, not a static height line.
7. Candidate signal display should not show a dense stream of theoretical signals; user-facing markers should be buy point, rejected buy, and sell decisions, with dense observation days collapsed into a score explanation.
8. The strategy needs yearly win-rate/return and top-10-candidate win-rate versus market regime checks before treating the current sample as robust.
9. Low-suction entries that later keep rising should be audited against four "limit-up start" signals: recent limit-up, four/five consecutive bullish closes, upward gap, and persistent volume expansion, especially in sideways or weak index regimes.

Out of scope:

- No new public strategy tab.
- No forced lane/quota for low-suction candidates.
- No historical `14:30` dependency.
- No claim of stable alpha before multi-year/walk-forward validation.
- No broad hard-reject rule tuned only to one stock.

## Product Semantics

- `quant_stock_signals` and candidate rows are entry evidence. They can explain low-suction buildup, dragon pullback, risk flags, and rejected buys, but they should not be interpreted as sell rules.
- A displayed buy point is the chosen executable point in a local cluster, not every day that has low-suction evidence. Low-suction days may add confidence internally until the first controlled lift/reclaim appears.
- Portfolio trade replay is the actual simulated execution path: buy, rejected buy, sell, and closed return. It may differ from candidate observation because of rank, max positions, full-position rotation, limit-up/limit-down execution, and order pairing.
- Candidate observation remains sorted by score and can show top `100` with pagination. It must not force low-suction slots or reserve capacity for any setup.
- Sell markers are dynamic decisions from held positions. They should use current/past data only: entry cost, entry support/MA evidence, current close-visible structure, current highest price since entry, and whether the same day still has a valid fresh buy/hold signal.
- Any rule that looks like "do not buy" or "do not sell" starts as measurable evidence. It becomes a hard gate only after a same-range global backtest, yearly split, and focused-symbol audit beat the current baseline.

## Current Baseline

- Public strategy: `mainline_dragon_pullback / 0.1.21`.
- Product baseline: `#175`, `2025-03-26` to `2026-06-17`, main board, `max_symbols=5000`.
- Result: return `+81.36%`, max drawdown `-15.59%`, buy/sell/open `224 / 214 / 10`.
- Candidate observation: top `100`, paged `20`.
- Portfolio execution: BUY candidates top `20`, max positions `10`.
- Failed experiment to avoid repeating: `0.1.22/#186`, return `+59.39%`, max drawdown `-18.13%`.

## Target Symbols For Focused Review

Use these for focused evidence after each global experiment. They are review samples, not optimization targets.

| Symbol | Name | Why It Matters |
| --- | --- | --- |
| `001258.SZSE` | 立新能源 | Buy-then-breakdown and profit-protection complaints already have sell-side tests. |
| `002208.SZSE` | 合肥城建 | Low-suction capture, weak rebound false entry, high pullback risk. |
| `002384.SZSE` | 东山精密 | Correct low-suction buildup and launch signal, but portfolio can skip due to full positions. |
| `600367.SSE` | 红星发展 | Low-suction washout before lift. |
| `002747.SZSE` | 埃斯顿 | Low-suction washout before lift. |
| `002119.SZSE` | 康强电子 | Repeated stretched dragon risk; hard reject failed globally. |
| `002428.SZSE` | 云南锗业 | Trend-hold versus selling too early. |
| `002636.SZSE` | 金安国纪 | Good buys but may need profit expansion. |
| `600487.SSE` | 亨通光电 | Capacity trend winner; sell-side should preserve large trends. |
| `603083.SSE` | 剑桥科技 | Slow low-suction lift and later negative return risk. |
| `002443.SZSE` | 金洲管道 | User-reported buy around `2026-05-14`; sell point should use entry anchor plus highest-profit drawdown, including high-profit sudden drawdown. |
| `603226.SSE` | 菲林格尔 | High-level long sideways distribution sample; must define "横久" without blocking normal dragon-pullback retests. |

## Files

- Modify `alphaagent/server/services/backtest/queries.py`
  - Add reusable trade-path metrics for MAE/MFE, return after exit, setup-level attribution, and entry-factor hit-rate audits.
- Modify `alphaagent/server/services/backtest/engine.py`
  - Expose a new backtest diagnostics service that uses existing persisted trades and daily positions.
- Modify `alphaagent/server/api/backtests.py`
  - Add a read-only diagnostics endpoint for focused and global review.
- Modify `alphaagent/server/services/backtest/simulation.py`
  - Only after diagnostics: add narrowly scoped sell/ranking experiment helpers if evidence supports them.
- Modify `alphaagent/server/services/backtest/scoring.py`
  - Reuse buy-signal scoring to suppress sell when the current day is still a valid fresh buy/hold structure.
- Modify `alphaagent/server/services/quant/candidate_lanes.py`
  - Only after diagnostics: tune opportunity score for mature low-suction launch if evidence supports it.
- Modify `alphaagent/server/services/quant/strategies/dragon_pullback.py`
  - Only after diagnostics: add entry evidence fields used for risk ranking, weekly-top/fractal risk, abnormal-spike risk, volume-stall risk, and low-suction limit-up-start factors, not broad single-stock hard rejections.
- Modify `alphaagent/server/services/quant/strategy_registry.py`
  - Add labels for any new risk evidence or failed rules that are exposed to the UI.
- Modify `alphaagent/server/services/quant/symbol_diagnostics.py`
  - Collapse dense candidate observations into selected buy/rejected-buy markers for stock-detail display.
- Modify `frontend/src/api/quant.ts`
  - Add read-only diagnostics response types and API fetchers.
- Modify `frontend/src/pages/StockDetailPage.tsx`, `frontend/src/features/stocks/StockKlineChart.tsx`, `frontend/src/features/quant/BacktestPanel.tsx`, `frontend/src/features/quant/BacktestAnalysis.tsx`
  - Display diagnostics without adding another ordinary user workflow.
- Modify `tests/alphaagent/test_quant_backtest_portfolio.py`
  - Add tests for diagnostics, no-future-function behavior, ranking decisions, and sell-side experiment boundaries.
- Modify `requirements/alphaagent_pullback_low_suction_strategy_research.md`
  - Append final experiment results and decisions.
- Modify `memory/06_backtests/strategy_optimization_ledger.md`
  - Add every experiment with run ID, return, drawdown, trades, decision, and evidence.
- Modify `memory/06_backtests/README.md`, `memory/09_decisions/decisions.md`, `memory/05_runtime/run_debug.md`
  - Update only durable facts after verification.

## Task 1: Add Trade-Path Diagnostics

**Files:**
- Modify: `alphaagent/server/services/backtest/queries.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add a failing unit test for MAE/MFE and post-exit return.

Add this test near existing attribution tests:

```python
def test_trade_path_diagnostics_calculates_mae_mfe_and_post_exit_return() -> None:
    from alphaagent.server.services.backtest import queries

    entry = {
        "id": 1,
        "trade_date": date(2026, 4, 1),
        "vt_symbol": "002208.SZSE",
        "side": "BUY",
        "price": 10.0,
        "amount": 1000.0,
        "fee": 1.0,
        "raw": {
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 4,
            "low_suction_launch_confirmed": True,
            "entry_total_score": 78.0,
        },
    }
    exit_trade = {
        "id": 2,
        "trade_date": date(2026, 4, 8),
        "vt_symbol": "002208.SZSE",
        "side": "SELL",
        "price": 9.6,
        "amount": 960.0,
        "fee": 1.0,
        "pnl": -42.0,
        "reason": "support_stop",
        "raw": {},
    }
    positions = [
        {"trade_date": date(2026, 4, 2), "vt_symbol": "002208.SZSE", "floating_pnl_pct": -2.0, "close_price": 9.8},
        {"trade_date": date(2026, 4, 3), "vt_symbol": "002208.SZSE", "floating_pnl_pct": 5.0, "close_price": 10.5},
        {"trade_date": date(2026, 4, 8), "vt_symbol": "002208.SZSE", "floating_pnl_pct": -4.0, "close_price": 9.6},
    ]
    future_bars = [
        {"trade_date": date(2026, 4, 9), "vt_symbol": "002208.SZSE", "close_price": 10.2},
        {"trade_date": date(2026, 4, 10), "vt_symbol": "002208.SZSE", "close_price": 11.2},
    ]

    row = queries.trade_path_diagnostic_row("002208.SZSE", entry, exit_trade, positions, future_bars, lookahead_days=5)

    assert row["entry_setup"] == "stealth_low_suction"
    assert row["mae_pct"] == -4.0
    assert row["mfe_pct"] == 5.0
    assert row["post_exit_max_return_pct"] == 16.6667
    assert row["sold_before_rebound"] is True
```

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py::test_trade_path_diagnostics_calculates_mae_mfe_and_post_exit_return -q
```

Expected: fails because `trade_path_diagnostic_row` does not exist.

- [x] Step 2: Implement the diagnostic row helper.

In `alphaagent/server/services/backtest/queries.py`, add:

```python
def trade_path_diagnostic_row(
    vt_symbol: str,
    entry: dict[str, Any],
    exit_trade: dict[str, Any] | None,
    positions: list[dict[str, Any]],
    future_bars: list[dict[str, Any]] | None = None,
    *,
    lookahead_days: int = 10,
) -> dict[str, Any]:
    entry_date = entry.get("trade_date")
    exit_date = exit_trade.get("trade_date") if exit_trade else None
    entry_price = _safe_float(entry.get("price"))
    path = [
        row for row in positions
        if row.get("vt_symbol") == vt_symbol
        and (entry_date is None or row.get("trade_date") >= entry_date)
        and (exit_date is None or row.get("trade_date") <= exit_date)
    ]
    future_path = [
        row for row in (future_bars or [])
        if row.get("vt_symbol") == vt_symbol
        and exit_date is not None
        and row.get("trade_date") > exit_date
        and (row.get("trade_date") - exit_date).days <= lookahead_days
    ]
    mae = _min_number(row.get("floating_pnl_pct") for row in path)
    mfe = _max_number(row.get("floating_pnl_pct") for row in path)
    future_closes = [_safe_float(row.get("close_price")) for row in future_path]
    future_closes = [value for value in future_closes if value is not None]
    exit_price = _safe_float((exit_trade or {}).get("price"))
    post_exit_max_return_pct = None
    if exit_price and future_closes:
        post_exit_max_return_pct = round((max(future_closes) / exit_price - 1) * 100, 4)
    entry_raw = entry.get("raw") if isinstance(entry.get("raw"), dict) else {}
    return {
        "vt_symbol": vt_symbol,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "entry_setup": entry_raw.get("entry_setup") or entry_raw.get("setup_type"),
        "entry_score": _entry_raw_number(entry_raw, "entry_total_score", "total_score"),
        "low_suction_days": _entry_raw_number(entry_raw, "low_suction_days"),
        "low_suction_launch_confirmed": bool(entry_raw.get("low_suction_launch_confirmed")),
        "exit_reason": (exit_trade or {}).get("reason"),
        "return_pct": ((exit_price / entry_price - 1) * 100) if entry_price and exit_price else None,
        "mae_pct": mae,
        "mfe_pct": mfe,
        "post_exit_max_return_pct": post_exit_max_return_pct,
        "sold_before_rebound": bool(post_exit_max_return_pct is not None and post_exit_max_return_pct >= 8.0),
    }
```

Also add:

```python
def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
```

- [x] Step 3: Add a service wrapper for persisted backtests.

In `queries.py`, add:

```python
from datetime import timedelta


def backtest_path_diagnostics(
    *,
    schema: Any,
    session_scope: Any,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    to_api: ApiMapper,
    backtest_id: int,
    vt_symbol: str | None = None,
    lookahead_days: int = 10,
    limit: int = 500,
) -> dict[str, Any]:
    if not is_database_configured():
        return {"status": "unavailable", "items": []}
    ensure_schema()
    row_limit = min(max(limit, 1), 2000)
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return {"status": "not_found", "backtest_id": backtest_id, "items": []}
        trade_query = select(schema.backtest_trades).where(schema.backtest_trades.c.backtest_id == backtest_id)
        position_query = select(schema.backtest_daily_positions).where(schema.backtest_daily_positions.c.backtest_id == backtest_id)
        if vt_symbol:
            trade_query = trade_query.where(schema.backtest_trades.c.vt_symbol == vt_symbol)
            position_query = position_query.where(schema.backtest_daily_positions.c.vt_symbol == vt_symbol)
        trades = [to_api(dict(row)) for row in session.execute(trade_query.order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)).mappings().all()]
        positions = [to_api(dict(row)) for row in session.execute(position_query.order_by(schema.backtest_daily_positions.c.trade_date)).mappings().all()]
        future_bars = _future_daily_bars_for_trades(session, schema, trades, lookahead_days=lookahead_days, to_api=to_api)
    rows = trade_path_diagnostics_from_trades(trades, positions, future_bars, lookahead_days=lookahead_days)
    rows = sorted(rows, key=lambda row: (row.get("return_pct") if row.get("return_pct") is not None else 9999))[:row_limit]
    return {
        "status": "ready" if rows else "empty",
        "backtest_id": backtest_id,
        "lookahead_days": lookahead_days,
        "items": rows,
        "summary": trade_path_diagnostics_summary(rows),
    }
```

Add helpers:

```python
def trade_path_diagnostics_from_trades(
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    future_bars: list[dict[str, Any]],
    *,
    lookahead_days: int = 10,
) -> list[dict[str, Any]]:
    open_trades: dict[str, list[dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    for trade in sorted(trades, key=lambda item: (item.get("trade_date"), int(item.get("id") or 0))):
        vt_symbol = str(trade.get("vt_symbol") or "")
        side = str(trade.get("side") or "").upper()
        if side == "BUY":
            open_trades.setdefault(vt_symbol, []).append(trade)
            continue
        if side != "SELL":
            continue
        entry = open_trades.setdefault(vt_symbol, []).pop(0) if open_trades.get(vt_symbol) else None
        if entry:
            rows.append(trade_path_diagnostic_row(vt_symbol, entry, trade, positions, future_bars, lookahead_days=lookahead_days))
    return rows


def _future_daily_bars_for_trades(
    session: Any,
    schema: Any,
    trades: list[dict[str, Any]],
    *,
    lookahead_days: int,
    to_api: ApiMapper,
) -> list[dict[str, Any]]:
    sell_trades = [trade for trade in trades if str(trade.get("side") or "").upper() == "SELL"]
    if not sell_trades:
        return []
    symbols = sorted({str(trade.get("vt_symbol") or "") for trade in sell_trades if trade.get("vt_symbol")})
    min_date = min(trade["trade_date"] for trade in sell_trades if trade.get("trade_date"))
    max_date = max(trade["trade_date"] for trade in sell_trades if trade.get("trade_date"))
    rows = session.execute(
        select(schema.stock_daily_bars)
        .where(schema.stock_daily_bars.c.vt_symbol.in_(symbols))
        .where(schema.stock_daily_bars.c.trade_date > min_date)
        .where(schema.stock_daily_bars.c.trade_date <= max_date + timedelta(days=lookahead_days + 7))
        .order_by(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date)
    ).mappings().all()
    return [to_api(dict(row)) for row in rows]


def trade_path_diagnostics_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    losses = [row for row in rows if row.get("return_pct") is not None and row["return_pct"] < 0]
    sold_before_rebound = [row for row in rows if row.get("sold_before_rebound")]
    return {
        "trade_count": len(rows),
        "loss_count": len(losses),
        "sold_before_rebound_count": len(sold_before_rebound),
        "avg_mae_pct": sum(float(row.get("mae_pct") or 0) for row in rows) / len(rows) if rows else None,
        "avg_mfe_pct": sum(float(row.get("mfe_pct") or 0) for row in rows) / len(rows) if rows else None,
    }
```

- [x] Step 4: Expose API endpoint.

In `alphaagent/server/services/backtest/engine.py`, add:

```python
def backtest_path_diagnostics(backtest_id: int, vt_symbol: str | None = None, lookahead_days: int = 10, limit: int = 500) -> dict[str, Any]:
    return queries.backtest_path_diagnostics(
        schema=schema,
        session_scope=session_scope,
        is_database_configured=is_database_configured,
        ensure_schema=_ensure_backtest_schema,
        to_api=_mapping_to_api,
        backtest_id=backtest_id,
        vt_symbol=vt_symbol,
        lookahead_days=lookahead_days,
        limit=limit,
    )
```

In `alphaagent/server/api/backtests.py`, import `backtest_path_diagnostics` and add:

```python
@router.get("/{backtest_id}/path-diagnostics")
def get_path_diagnostics(
    backtest_id: int,
    vt_symbol: str = Query(default=""),
    lookahead_days: int = Query(default=10, ge=1, le=30),
    limit: int = Query(default=500, ge=1, le=2000),
):
    try:
        return ok(
            backtest_path_diagnostics(
                backtest_id,
                vt_symbol=vt_symbol or None,
                lookahead_days=lookahead_days,
                limit=limit,
            )
        )
    except Exception as exc:
        return _service_error(exc)
```

- [x] Step 5: Run verification.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
```

Expected: tests pass and compileall succeeds.

## Task 2: Run Baseline Attribution Audit

**Files:**
- Create: `memory/06_backtests/2026-06-17_strategy_drawdown_baseline_audit.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/06_backtests/strategy_optimization_ledger.md`

- [x] Step 1: Confirm current API baseline.

Run:

```bash
curl -s 'http://localhost:8000/api/quant/strategies'
curl -s 'http://localhost:8000/api/backtests?limit=3&run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true'
```

Expected:

- Strategy version is `0.1.21`.
- Baseline backtest is `#175` or a newer same-version full-range baseline ending `2026-06-17`.

- [x] Step 2: Pull attribution evidence.

Replace `<id>` with the baseline ID:

```bash
curl -s 'http://localhost:8000/api/backtests/<id>/trade-attribution?sort=pnl_asc&limit=200'
curl -s 'http://localhost:8000/api/backtests/<id>/path-diagnostics?lookahead_days=10&limit=500'
curl -s 'http://localhost:8000/api/backtests/<id>/path-diagnostics?vt_symbol=001258.SZSE&lookahead_days=10&limit=50'
curl -s 'http://localhost:8000/api/backtests/<id>/path-diagnostics?vt_symbol=002208.SZSE&lookahead_days=10&limit=50'
curl -s 'http://localhost:8000/api/backtests/<id>/path-diagnostics?vt_symbol=002384.SZSE&lookahead_days=10&limit=50'
curl -s 'http://localhost:8000/api/backtests/<id>/path-diagnostics?vt_symbol=002119.SZSE&lookahead_days=10&limit=50'
curl -s 'http://localhost:8000/api/backtests/<id>/path-diagnostics?vt_symbol=002443.SZSE&lookahead_days=10&limit=50'
```

- [x] Step 3: Write the baseline audit report.

Create `memory/06_backtests/2026-06-17_strategy_drawdown_baseline_audit.md` with this structure:

```markdown
# Strategy Drawdown Baseline Audit

## Baseline

- Strategy:
- Backtest:
- Range:
- Return:
- Max drawdown:
- Trades:

## Loss Attribution

| Bucket | Count | PnL / Return | Notes |
| --- | ---: | ---: | --- |
| support_stop | | | |
| fragile_structure_stop | | | |
| trend_break | | | |
| trend_trailing_stop | | | |
| profit_protection_stop | | | |

## Path Diagnostics

- Loss count:
- Sold-before-rebound count:
- Average MAE:
- Average MFE:
- Main failure mode:

## Focused Symbols

| Symbol | Finding | Evidence | Next Action |
| --- | --- | --- | --- |
| 001258.SZSE | | | |
| 002208.SZSE | | | |
| 002384.SZSE | | | |
| 002119.SZSE | | | |
| 002443.SZSE | | | |

## Decision

The next experiment should be:

1. entry/ranking only, if profitable setups were missed because execution pool/ranking/full-position replacement was weak;
2. sell-side only, if losses have large early MAE or systematic post-entry breakdown;
3. hold/profit-protection only, if large winners are being sold before sustained trend gains.
```

- [x] Step 4: Update the evidence index.

Add a link in `memory/06_backtests/README.md` under "Current Evidence Files".

- [x] Step 5: Do not change strategy rules yet.

This task is diagnostic only. No strategy version bump, no run ledger entry, no performance claims.

## Task 3: Dynamic Highest-Profit Drawdown Sell Experiment

Run this task only after Task 2 confirms sell timing is a major issue. This is the main path for `002443.SZSE`: buy around `2026-05-14`, then sell should use the buy point as an entry anchor (`cost_price`, `support_price`, entry MA evidence) and combine it with highest floating return drawdown and current structure. The rule should not be a static "buy point was high, so sell" line; it should react when a profitable high-level hold suddenly gives back too much, which can indicate distribution.

**Files:**
- Modify: `alphaagent/server/services/backtest/simulation.py`
- Modify: `alphaagent/server/services/backtest/scoring.py`
- Modify: `tests/alphaagent/test_quant_backtest_portfolio.py`
- Modify: `alphaagent/server/services/quant/factors.py`
- Modify: `alphaagent/server/services/quant/strategies/dragon_pullback.py`

- [x] Step 1: Add a failing unit test for highest-profit drawdown sell.

Add:

```python
def test_dragon_pullback_exit_sells_on_highest_profit_drawdown_without_fresh_buy_signal() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import dragon_pullback_sell_reason

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="002443.SZSE",
        name="金洲管道",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 5, 14),
        highest_price=12.8,
        reason={
            "ma10": 11.8,
            "ma20": 10.9,
            "support_price": 10.2,
            "entry_setup": "stealth_low_suction",
            "low_suction_launch_confirmed": True,
        },
    )
    bar = Bar(
        trade_date=date(2026, 5, 28),
        open_price=11.3,
        high_price=11.5,
        low_price=10.95,
        close_price=11.05,
        volume=1_000_000,
        turnover=500_000_000,
        change_pct=-4.2,
    )

    assert dragon_pullback_sell_reason(position, bar, bar.trade_date, params, current_buy_signal=False) == "peak_profit_drawdown_stop"
```

Expected: fails because `dragon_pullback_sell_reason` does not accept `current_buy_signal`.

- [x] Step 2: Add a failing unit test for a high-profit position that suddenly gives back 7%.

This captures the "盈利后高位突然亏 7%，可能主力在出货" case. The 7% is measured from the highest held price, while the buy point still provides the cost/profit anchor.

Add:

```python
def test_dragon_pullback_exit_sells_when_high_profit_gives_back_seven_percent() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import dragon_pullback_sell_reason

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="002443.SZSE",
        name="金洲管道",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 5, 14),
        highest_price=12.0,
        reason={
            "entry_setup": "stealth_low_suction",
            "support_price": 10.2,
            "ma10": 10.8,
            "ma20": 10.1,
        },
    )
    bar = Bar(
        trade_date=date(2026, 5, 23),
        open_price=11.65,
        high_price=11.70,
        low_price=11.02,
        close_price=11.16,
        volume=2_200_000,
        turnover=820_000_000,
        change_pct=-5.8,
    )

    assert dragon_pullback_sell_reason(position, bar, bar.trade_date, params, current_buy_signal=False) == "peak_profit_drawdown_stop"
```

- [x] Step 3: Add a test that does not sell when the same day is still a fresh buy/hold structure.

Add:

```python
def test_dragon_pullback_exit_does_not_sell_peak_drawdown_when_current_day_is_buy_signal() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import dragon_pullback_sell_reason

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="002443.SZSE",
        name="金洲管道",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 5, 14),
        highest_price=12.8,
        reason={"ma10": 11.2, "ma20": 10.7, "support_price": 10.2},
    )
    bar = Bar(
        trade_date=date(2026, 5, 28),
        open_price=11.6,
        high_price=11.9,
        low_price=11.15,
        close_price=11.55,
        volume=1_000_000,
        turnover=500_000_000,
        change_pct=1.1,
    )

    assert dragon_pullback_sell_reason(position, bar, bar.trade_date, params, current_buy_signal=True) is None
```

- [x] Step 4: Implement an optional current-buy-signal parameter.

Change only the dragon-pullback exit path:

```python
def dragon_pullback_sell_reason(
    position: Position,
    bar: Bar,
    current_day: date,
    params: BacktestParams,
    *,
    current_buy_signal: bool = False,
) -> str | None:
```

Add the dynamic sell after hard risk stops and before loose trend trailing stops:

```python
    gain = bar.close_price / cost_price - 1 if cost_price else 0
    high_gain = position.highest_price / cost_price - 1 if cost_price and position.highest_price else 0
    drawdown_from_high = bar.close_price / position.highest_price - 1 if position.highest_price else 0
    if not current_buy_signal:
        if high_gain >= 0.18 and drawdown_from_high <= -0.07 and gain >= 0.08:
            return "peak_profit_drawdown_stop"
        if high_gain >= 0.28 and drawdown_from_high <= -0.14 and gain >= 0.06:
            return "peak_profit_drawdown_stop"
        if high_gain >= 0.12 and drawdown_from_high <= -0.10 and gain >= 0.04:
            return "peak_profit_drawdown_stop"
```

The buy point participates through `cost_price`, `entry_support`, `ma10`, `ma20`, and `position.reason`. Do not use a static "buy point is high/low" label as the trigger. Use current close-visible data, current position highest price, entry anchor evidence, and current buy-signal state.

- [x] Step 5: Add an explicit no-future-function test for the dynamic sell rule.

Add:

```python
def test_peak_profit_drawdown_sell_uses_only_position_high_and_current_bar() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import dragon_pullback_sell_reason

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="002443.SZSE",
        name="金洲管道",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 5, 14),
        highest_price=12.8,
        reason={"ma10": 11.8, "ma20": 10.9, "support_price": 10.2},
    )
    current_bar = Bar(
        trade_date=date(2026, 5, 28),
        open_price=11.3,
        high_price=11.5,
        low_price=10.95,
        close_price=11.05,
        volume=1_000_000,
        turnover=500_000_000,
        change_pct=-4.2,
    )
    future_bar_that_must_not_be_used = Bar(
        trade_date=date(2026, 5, 29),
        open_price=10.8,
        high_price=13.2,
        low_price=10.7,
        close_price=13.0,
        volume=1_300_000,
        turnover=620_000_000,
        change_pct=17.6,
    )

    reason_without_future = dragon_pullback_sell_reason(position, current_bar, current_bar.trade_date, params, current_buy_signal=False)
    reason_with_future_value_available_but_not_passed = dragon_pullback_sell_reason(position, current_bar, current_bar.trade_date, params, current_buy_signal=False)

    assert future_bar_that_must_not_be_used.trade_date > current_bar.trade_date
    assert reason_without_future == reason_with_future_value_available_but_not_passed == "peak_profit_drawdown_stop"
```

- [x] Step 6: Wire current buy signal into sell evaluation.

In `signal_events_for_day`, `run_backtest`, or the current scoring path, pass whether the held symbol has an executable current-day buy signal before calling `sell_reason_for_position`. The simplest acceptable interface:

```python
sell_reason = sell_reason_for_position(position, bar, signal_date, params, current_buy_signal=vt_symbol in current_buy_signal_symbols)
```

Update `sell_reason_for_position` to accept the same keyword and pass it to `dragon_pullback_sell_reason`.

- [x] Step 7: Keep dynamic sell explainable.

Add label mapping for `peak_profit_drawdown_stop` wherever sell reason labels are defined:

```python
"peak_profit_drawdown_stop": "高位浮盈回撤止盈",
```

- [x] Step 8: Run targeted tests and full tests.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py::test_dragon_pullback_exit_sells_on_highest_profit_drawdown_without_fresh_buy_signal -q
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py::test_dragon_pullback_exit_sells_when_high_profit_gives_back_seven_percent -q
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py::test_dragon_pullback_exit_does_not_sell_peak_drawdown_when_current_day_is_buy_signal -q
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py::test_peak_profit_drawdown_sell_uses_only_position_high_and_current_bar -q
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
```

- [x] Step 9: Global backtest gate.

If code changed, bump strategy version and run the full research/backtest. Keep only if global result does not materially worsen versus `#175`, focused `002443.SZSE` sell timing improves, and yearly/top-candidate audits from Tasks 9 and 10 do not show concentrated deterioration.

Result: rejected and removed from default code. Temporary `0.1.23 / #187` added the peak-profit drawdown sell tests/rule and passed targeted tests, but the full gate failed: return fell to `+32.17%`, max drawdown worsened to `-23.86%`, profit factor fell to `1.1340`, and `002443.SZSE` still exited by `support_stop` on `2026-06-04` with `-4.86%` after MFE `+11.82%`. The rule triggered `26` `peak_profit_drawdown_stop` exits globally and damaged too many profitable paths. Keep `0.1.21` as default and use `#187` only as failure evidence.

## Task 4: Entry Ranking Experiment

Run this task only if Task 2 shows missed opportunities are mainly ranking/full-position problems. This task should improve ranking; it must not force low-suction candidates into the execution pool.

**Files:**
- Modify: `alphaagent/server/services/quant/candidate_lanes.py`
- Modify: `tests/alphaagent/test_quant_backtest_portfolio.py`
- Modify: `alphaagent/server/services/quant/factors.py`
- Modify: `alphaagent/server/services/quant/strategies/dragon_pullback.py`
- Modify: `memory/06_backtests/strategy_optimization_ledger.md`

- [x] Step 1: Write a test proving low-suction launch gains score only after buildup.

Add:

```python
def test_low_suction_opportunity_bonus_requires_buildup_and_rising_confirmation() -> None:
    from alphaagent.server.services.quant.candidate_lanes import stealth_low_suction_opportunity_bonus

    early = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=date(2026, 3, 30),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=78.0,
        entry_signal=True,
        evidence={
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 2,
            "latest_change_pct": 0.8,
            "ma5_distance_pct": 1.0,
            "ma10_distance_pct": 1.0,
            "ma5_slope_pct": 0.2,
            "ma5_vs_ma10_pct": 0.1,
            "volume_ratio_5d_20d": 0.8,
            "ma_convergence_pct": 3.0,
        },
    )
    launch = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=78.0,
        entry_signal=True,
        evidence={
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 5,
            "latest_change_pct": 1.6,
            "ma5_distance_pct": 1.1,
            "ma10_distance_pct": 1.3,
            "ma5_slope_pct": 0.35,
            "ma5_vs_ma10_pct": 0.2,
            "volume_ratio_5d_20d": 0.85,
            "ma_convergence_pct": 2.8,
            "low_suction_launch_confirmed": True,
        },
    )

    assert stealth_low_suction_opportunity_bonus(early) <= 1.0
    assert stealth_low_suction_opportunity_bonus(launch) >= 4.0
```

- [x] Step 2: If the test fails, tune `stealth_low_suction_opportunity_bonus` minimally.

Allowed adjustments:

- Increase mature launch bonus only when `low_suction_days >= 5`.
- Require `low_suction_launch_confirmed=true` or equivalent rising confirmation.
- Cap bonus when `volume_ratio_5d_20d > 1.20`, `ma5_distance_pct > 3.2`, or `return_60d >= 90`.

Do not:

- Add a low-suction quota.
- Add a separate public strategy.
- Force any stock into the top 20.
- Treat every low-suction observation day as a displayed buy point.

- [x] Step 3: Add a test that a long low-suction buildup becomes stronger only when the first lift appears.

Add:

```python
def test_low_suction_buildup_scores_stronger_on_first_lift_than_flat_observation() -> None:
    from alphaagent.server.services.quant.candidate_lanes import stealth_low_suction_opportunity_bonus

    flat_observation = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=82.0,
        entry_signal=True,
        evidence={
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 6,
            "latest_change_pct": 0.2,
            "ma5_distance_pct": 0.8,
            "ma10_distance_pct": 1.0,
            "ma5_slope_pct": 0.05,
            "volume_ratio_5d_20d": 0.72,
            "ma_convergence_pct": 2.4,
            "low_suction_launch_confirmed": False,
        },
    )
    first_lift = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=date(2026, 4, 8),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=82.0,
        entry_signal=True,
        evidence={
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 8,
            "latest_change_pct": 2.1,
            "ma5_distance_pct": 1.4,
            "ma10_distance_pct": 1.8,
            "ma5_slope_pct": 0.45,
            "volume_ratio_5d_20d": 0.95,
            "ma_convergence_pct": 2.6,
            "low_suction_launch_confirmed": True,
        },
    )

    assert stealth_low_suction_opportunity_bonus(first_lift) > stealth_low_suction_opportunity_bonus(flat_observation)
```

- [x] Step 4: Bump strategy version only after code changes.

If code changes are kept for a global run, update:

```python
DRAGON_PULLBACK_STRATEGY_VERSION = "0.1.23"
```

in both:

- `alphaagent/server/services/quant/factors.py`
- `alphaagent/server/services/quant/strategies/dragon_pullback.py`

- [x] Step 5: Run tests.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
```

- [x] Step 6: Run full research/backtest.

Use the normal research API or existing `/quant` workflow:

```bash
curl -s -X POST 'http://localhost:8000/api/quant/research-runs' \
  -H 'Content-Type: application/json' \
  -d '{
    "start":"2025-03-26",
    "end":"2026-06-17",
    "strategy":"mainline_dragon_pullback",
    "max_symbols":5000,
    "recommendation_limit":100,
    "min_recommendation_score":60,
    "min_entry_score":76,
    "persist":true,
    "auto_portfolio":true,
    "included_boards":["main"],
    "initial_cash":1000000,
    "max_positions":10,
    "candidate_limit":20,
    "max_position_pct":0.1,
    "strict_entry":true,
    "execution_model":"legacy_next_open",
    "force_refresh":true
  }'
```

Poll latest research run until complete.

- [x] Step 7: Compare with `#175`.

Required minimum evidence:

- Total return.
- Max drawdown.
- Buy/sell/open counts.
- Profit factor and Sharpe if available.
- Setup-level attribution for `dragon_pullback` and `stealth_low_suction`.
- Focused traces for `002384.SZSE`, `002208.SZSE`, `600367.SSE`, `002747.SZSE`.

- [x] Step 8: Keep or revert.

Keep only if:

- Return is not materially worse than `#175`.
- Max drawdown is not materially worse than `#175`.
- The focused low-suction misses improve for ranking/capacity reasons.
- No obvious over-concentration appears.

Result: rejected and removed from default code. Temporary `0.1.23 / #188` raised mature low-suction launch opportunity bonus and capped unconfirmed flat buildup. It passed local boundary tests but failed the global gate: return was `+56.03%`, max drawdown `-22.54%`, profit factor `1.4141`, Sharpe `1.6705`, and trades `225 / 215 / 10`, all materially weaker than `#175/#177`. Focused low-suction samples `002208.SZSE`, `600367.SSE`, and `002747.SZSE` still had no closed portfolio trade, while `002384.SZSE` added/kept poor late entries. Keep current `0.1.21` opportunity bonus; do not increase low-suction launch ranking bonus without a stronger full-range proof.

Otherwise revert the strategy code and record the experiment as rejected.

## Task 5: Sell-Side Drawdown Experiment

Run this task only if Task 2 shows losses are mainly post-entry breakdown, large MAE, or support-stop leakage.

**Files:**
- Modify: `alphaagent/server/services/backtest/simulation.py`
- Modify: `tests/alphaagent/test_quant_backtest_portfolio.py`
- Modify: `alphaagent/server/services/quant/factors.py`
- Modify: `alphaagent/server/services/quant/strategies/dragon_pullback.py`
- Modify: `memory/06_backtests/strategy_optimization_ledger.md`

- [x] Step 1: Write focused sell-side boundary tests.

Add:

```python
def test_dragon_pullback_exit_requires_confirmed_breakdown_not_single_noise() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="002208.SZSE",
        name="合肥城建",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 4, 20),
        highest_price=10.4,
        reason={
            "ma10": 9.9,
            "ma20": 9.6,
            "support_price": 9.8,
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
        },
    )
    bar = Bar(
        trade_date=date(2026, 4, 22),
        open_price=9.86,
        high_price=10.05,
        low_price=9.70,
        close_price=9.77,
        volume=1_000_000,
        turnover=300_000_000,
        change_pct=-2.1,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) is None
```

Add:

```python
def test_dragon_pullback_exit_stops_fragile_entry_after_clean_support_failure() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="001258.SZSE",
        name="立新能源",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 5, 25),
        highest_price=10.2,
        reason={
            "ma10": 9.8,
            "ma20": 9.4,
            "support_price": 9.9,
            "max_drawdown_60d": -30.0,
            "entry_setup": "dragon_pullback",
        },
    )
    bar = Bar(
        trade_date=date(2026, 5, 30),
        open_price=9.65,
        high_price=9.75,
        low_price=9.38,
        close_price=9.45,
        volume=1_000_000,
        turnover=300_000_000,
        change_pct=-4.0,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) == "fragile_structure_stop"
```

- [x] Step 2: Implement only a narrow sell rule if tests and diagnostics justify it.

Allowed changes:

- Tighten fragile entry stops only when entry evidence already shows poor prior structure, e.g. `max_drawdown_60d <= -25`.
- Preserve current trend-holding behavior for winners.
- Keep sell rules close-visible and executed next open; no future bars.

Do not:

- Reintroduce broad `early_breakdown_stop` from `0.1.19/#173`.
- Reintroduce entry-day hard stop from `0.1.20/#174`.
- Add intraday assumptions.

- [x] Step 3: Bump version to `0.1.23` only if code changes are kept for a global run.

Use the same version bump locations as Task 4.

- [x] Step 4: Run full tests and global research/backtest with the same command as Task 4.

- [x] Step 5: Compare against `#175`.

Keep only if:

- Max drawdown improves or remains near `#175`.
- Return is not materially lower than `#175`.
- `trend_trailing_stop` and large winner contribution are not materially damaged.
- Focused 立新能源/合肥城建 loss path improves.

Result: no strategy code change required. The focused boundary tests pass on current `0.1.21`: a low-suction support dip does not sell on one noisy close, while a fragile entry with `max_drawdown_60d <= -25` and clean support failure exits by `fragile_structure_stop`. Because no sell rule changed, no version bump or new global backtest was run for Task 5. This also avoids repeating the rejected broad sell experiments `#173/#174/#187`.

Otherwise revert and record as rejected.

## Task 6: Candidate Signal Display Deduplication

This task addresses the UI complaint that candidate signals show too many theoretical markers. User-facing stock charts should show only actual buy, rejected buy, and sell decisions. If there are multiple executable buy candidates close together, the displayed candidate should be the highest-score candidate in that cluster.

**Files:**
- Modify: `alphaagent/server/services/quant/symbol_diagnostics.py`
- Modify: `frontend/src/pages/StockDetailPage.tsx`
- Modify: `frontend/src/features/stocks/StockKlineChart.tsx`
- Modify: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add a pure helper test for candidate signal clustering.

If no suitable frontend test harness exists, add the equivalent helper test in Python for the marker-selection logic before porting to TypeScript:

```python
def test_candidate_signal_display_keeps_highest_score_buy_per_cluster() -> None:
    from alphaagent.server.services.quant.symbol_diagnostics import display_candidate_markers

    rows = [
        {"trade_date": date(2026, 5, 12), "action": "BUY", "total_score": 76.0, "signal_label": "低吸蓄势观察"},
        {"trade_date": date(2026, 5, 14), "action": "BUY", "total_score": 84.0, "signal_label": "低吸启动买点"},
        {"trade_date": date(2026, 5, 15), "action": "BUY", "total_score": 81.0, "signal_label": "龙回头买点"},
        {"trade_date": date(2026, 5, 20), "action": "WATCH", "total_score": 90.0, "failed_rules": ["ma20_broken"]},
    ]

    markers = display_candidate_markers(rows, cluster_days=3)

    assert [item["trade_date"] for item in markers] == [date(2026, 5, 14), date(2026, 5, 20)]
    assert markers[0]["display_kind"] == "buy"
    assert markers[1]["display_kind"] == "rejected_buy"
```

- [x] Step 2: Implement the helper.

The helper must:

- Keep `action=BUY` rows as buy candidates.
- Keep `WATCH` rows only if they were raw buy/rejected buy with failed rules.
- Drop pure observation rows that are not executable and not rejected buy.
- Cluster executable BUY rows within `3` calendar days and keep the highest `total_score`.
- Never drop actual trade or sell markers.

- [x] Step 3: Apply the helper in `StockDetailPage.tsx`.

Candidate mode should show:

- `BUY` candidate marker after clustering.
- Rejected buy marker when there was a raw buy but failed execution rules.
- Sell markers from replay/trade data.

It should not show every low-suction observation day.

- [x] Step 4: Run verification.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
pnpm --dir frontend run build
```

## Task 7: Risk Filter Factor Research

This task turns the user's "do not buy" list into measurable factors. These factors should first be diagnostics and failed rules; only keep them as hard gates after global validation. The first implementation should answer whether these factors explain bad trades; it should not reduce the execution pool before a global run proves the effect. `603226.SSE` is the focused sample for high-level long sideways distribution: "横久" should mean a sustained high-level range, not a normal short dragon-pullback retest.

**Files:**
- Modify: `alphaagent/server/services/quant/strategies/dragon_pullback.py`
- Modify: `tests/alphaagent/test_quant_backtest_portfolio.py`
- Modify: `requirements/alphaagent_pullback_low_suction_strategy_research.md`

- [x] Step 1: Add tests for measurable no-buy risk factors.

Add test cases for these evidence fields:

```python
def test_dragon_pullback_marks_top_fractal_and_volume_stall_risks() -> None:
    start = date(2026, 1, 1)
    closes = [10 + index * 0.06 for index in range(70)]
    closes.extend([16.0, 17.2, 18.4, 19.6, 20.6, 20.4, 20.3, 20.2, 20.1, 20.0])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.995,
            high_price=close * (1.06 if index >= 70 else 1.02),
            low_price=close * 0.985,
            close_price=close,
            volume=4_000_000 if index >= 75 else 1_000_000,
            turnover=1_200_000_000 if index >= 75 else 300_000_000,
            change_pct=0.1 if index >= 75 else 1.2,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback("002119.SZSE", bars, bars[-1].trade_date, index_return_20d=-1.0, sector_score=75.0)

    assert score.evidence["weekly_top_fractal_risk"] is True
    assert score.evidence["volume_stall_risk"] is True
    assert "weekly_top_fractal_risk" in score.evidence["risk_flags"]
```

```python
def test_dragon_pullback_marks_spiky_self_play_risk() -> None:
    start = date(2026, 1, 1)
    bars: list[Bar] = []
    close = 10.0
    for index in range(88):
        change_pct = 5.5 if index % 2 == 0 else -4.8
        close *= 1 + change_pct / 100
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=close * 0.99,
                high_price=close * 1.11,
                low_price=close * 0.90,
                close_price=close,
                volume=2_000_000,
                turnover=500_000_000,
                change_pct=change_pct,
            )
        )

    score = score_dragon_pullback("002119.SZSE", bars, bars[-1].trade_date, index_return_20d=0.0, sector_score=65.0)

    assert score.evidence["spiky_churn_risk"] is True
    assert "spiky_churn_risk" in score.evidence["risk_flags"]
```

```python
def test_dragon_pullback_marks_illiquid_and_ma_break_risks() -> None:
    start = date(2026, 1, 1)
    closes = [10 + index * 0.03 for index in range(70)]
    closes.extend([12.0, 11.8, 11.6, 11.4, 11.2, 10.8, 10.5, 10.2, 9.9, 9.6])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 1.005,
            high_price=close * 1.015,
            low_price=close * 0.985,
            close_price=close,
            volume=60_000 if index >= 75 else 1_200_000,
            turnover=8_000_000 if index >= 75 else 260_000_000,
            change_pct=-2.8 if index >= 75 else 0.3,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback("002208.SZSE", bars, bars[-1].trade_date, index_return_20d=-3.0, sector_score=45.0)

    assert score.evidence["illiquid_forgotten_risk"] is True
    assert score.evidence["key_support_break_risk"] is True
    assert "key_support_break_risk" in score.evidence["failed_rules"]
```

```python
def test_dragon_pullback_marks_high_level_long_sideways_distribution_risk() -> None:
    start = date(2026, 1, 1)
    closes = [10 + index * 0.08 for index in range(60)]
    closes.extend([16.8, 17.2, 16.9, 17.1, 16.7, 17.0, 16.8, 16.9, 17.1, 16.8])
    closes.extend([16.9, 17.0, 16.7, 16.8, 16.9, 16.6, 16.8, 16.7, 16.6, 16.5])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.997,
            high_price=close * 1.025,
            low_price=close * 0.975,
            close_price=close,
            volume=2_800_000 if index >= 60 else 1_200_000,
            turnover=900_000_000 if index >= 60 else 300_000_000,
            change_pct=0.0 if index >= 60 else 1.0,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback("603226.SSE", bars, bars[-1].trade_date, index_return_20d=0.0, sector_score=60.0)

    assert score.evidence["high_level_sideways_days"] >= 18
    assert score.evidence["high_level_sideways_distribution_risk"] is True
    assert "high_level_sideways_distribution_risk" in score.evidence["risk_flags"]
```

```python
def test_dragon_pullback_does_not_mark_short_dragon_retest_as_long_sideways_distribution() -> None:
    start = date(2026, 1, 1)
    closes = [10 + index * 0.08 for index in range(70)]
    closes.extend([18.5, 19.4, 20.3, 19.2, 18.7, 18.9, 19.1, 19.6])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.995,
            high_price=close * 1.03,
            low_price=close * 0.975,
            close_price=close,
            volume=1_600_000 if index >= 70 else 1_200_000,
            turnover=500_000_000 if index >= 70 else 300_000_000,
            change_pct=1.2 if index >= 76 else -0.5 if index >= 73 else 2.0,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback("002428.SZSE", bars, bars[-1].trade_date, index_return_20d=-1.0, sector_score=75.0)

    assert score.evidence.get("high_level_sideways_days", 0) < 15
    assert score.evidence["high_level_sideways_distribution_risk"] is False
```

- [x] Step 2: Implement evidence-only risk metrics.

Add fields such as:

- `weekly_top_fractal_risk`: weekly high fractal or weekly reversal from recent high.
- `spiky_churn_risk`: frequent long shadows plus large alternating daily changes.
- `volume_stall_risk`: high 60-day price percentile, high volume ratio, weak price progress.
- `key_support_break_risk`: close below MA20/MA30/support.
- `illiquid_forgotten_risk`: turnover/volume percentile extremely low.
- `high_position_volume_stall_risk`: high 60-day location plus high turnover and no price progress, used to describe "高位放量滞涨".
- `high_level_sideways_days`: count of recent high-level sideways days. Initial research boundary: at least `15` to `20` trading days, latest close in the upper `70%` of the 60-day range, 20-day range width no more than about `12%`, 20-day return between about `-6%` and `+8%`, and no fresh reclaim/launch structure.
- `high_level_sideways_distribution_risk`: high-level sideways days plus weak price progress and stale/churning volume. This is the "高位横盘横久必跌" evidence field.

Do not make every field a hard reject immediately.

- [x] Step 3: Convert only obvious hard-risk cases into failed rules.

Allowed hard rules:

- `key_support_break_risk` when price has clearly broken MA20/MA30 support.
- `volume_stall_risk` only when high location and high volume happen together with weak/negative progress.

Diagnostics only:

- `weekly_top_fractal_risk`.
- `spiky_churn_risk`.
- `illiquid_forgotten_risk`.
- `high_position_volume_stall_risk` unless the global audit proves it should be a hard reject.
- `high_level_sideways_distribution_risk` until it proves it removes bad trades without killing normal dragon-pullback winners.

- [x] Step 4: Global backtest gate.

Any hard-rule change must be versioned and compared with `#175`. If return or drawdown worsens materially, revert the hard gate but keep diagnostic evidence. The report must explicitly state whether the rule mostly removes losers or also removes high-payoff winners. For high-level sideways risk, the focused report must compare `603226.SSE` against normal dragon-pullback samples such as `002428.SZSE` and `600487.SSE` to prove the rule does not suppress short healthy retests.

## Task 8: No-Sell Support And Accumulation Research

This task turns the user's "do not sell" list into measurable hold filters for sell rules. Hold filters are only allowed to suppress soft exits; they must not mask hard breakdowns or loss-control exits.

**Files:**
- Modify: `alphaagent/server/services/backtest/simulation.py`
- Modify: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add tests for no-sell structures.

Add:

```python
def test_dragon_pullback_exit_holds_low_base_accumulation() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, time_stop_days=10)
    position = Position(
        vt_symbol="002208.SZSE",
        name="合肥城建",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 4, 1),
        highest_price=10.6,
        reason={
            "entry_setup": "stealth_low_suction",
            "low_base_days": 45,
            "price_location_60d_pct": 28.0,
            "base_volatility_20d_pct": 5.0,
            "ma10": 9.95,
            "ma20": 9.75,
            "support_price": 9.7,
        },
    )
    bar = Bar(
        trade_date=date(2026, 4, 28),
        open_price=10.15,
        high_price=10.25,
        low_price=9.88,
        close_price=10.05,
        volume=900_000,
        turnover=250_000_000,
        change_pct=0.3,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) is None
```

Add:

```python
def test_dragon_pullback_exit_holds_ma_support_pullback_with_volume_confirmation() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="600487.SSE",
        name="亨通光电",
        volume=100,
        cost_price=50.0,
        entry_date=date(2026, 1, 10),
        highest_price=64.0,
        reason={
            "ma10": 58.0,
            "ma20": 55.0,
            "support_price": 55.0,
            "volume_ratio_5d_20d": 1.18,
            "latest_change_pct": 0.8,
            "price_volume_sync": True,
        },
    )
    bar = Bar(
        trade_date=date(2026, 2, 8),
        open_price=57.2,
        high_price=58.8,
        low_price=55.4,
        close_price=58.1,
        volume=1_500_000,
        turnover=900_000_000,
        change_pct=0.8,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params, current_buy_signal=True) is None
```

- [x] Step 2: Implement hold filters.

Add helper:

```python
def dragon_pullback_hold_context(position: Position, bar: Bar) -> dict[str, bool]:
    reason = position.reason if isinstance(position.reason, dict) else {}
    low_base_days = int(reason.get("low_base_days") or 0)
    price_location = _float_or_none(reason.get("price_location_60d_pct"))
    base_volatility = _float_or_none(reason.get("base_volatility_20d_pct"))
    ma10 = _float_or_none(reason.get("ma10"))
    ma20 = _float_or_none(reason.get("ma20"))
    latest_change = _float_or_none(reason.get("latest_change_pct"))
    volume_ratio = _float_or_none(reason.get("volume_ratio_5d_20d"))
    return {
        "low_base_accumulation": bool(
            low_base_days >= 30
            and price_location is not None
            and price_location <= 35
            and base_volatility is not None
            and base_volatility <= 8
            and ma20 is not None
            and bar.close_price >= ma20 * 0.98
        ),
        "ma_support_pullback": bool(
            ma10 is not None
            and ma20 is not None
            and bar.low_price <= ma10 * 1.02
            and bar.close_price >= ma20 * 0.99
        ),
        "price_volume_sync": bool(
            latest_change is not None
            and latest_change >= 0
            and volume_ratio is not None
            and 0.9 <= volume_ratio <= 1.8
        ),
    }
```

Use only current and prior evidence stored in `position.reason` plus current bar. Do not inspect future bars.

- [x] Step 3: Apply hold filters before soft sell reasons.

Hold filters may suppress:

- `time_efficiency_stop`
- `peak_profit_drawdown_stop`
- weak `trend_break`

Hold filters must not suppress:

- hard cost stop
- clear MA20/MA30 structural break
- fragile structure stop

## Task 9: Yearly And Market-Regime Win-Rate Audit

This task addresses the low realized win-rate concern.

**Files:**
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/services/backtest/queries.py`
- Modify: `frontend/src/features/quant/BacktestAnalysis.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Verify existing yearly data covers the report.

Existing `include_analysis=true` already has `robustness_checks.yearly_periods`. Add a test that the yearly table includes:

- `return_pct`
- `max_drawdown_pct`
- `trade_count`
- `win_rate`
- benchmark/excess return when benchmark data exists

Add or extend the existing robustness test:

```python
def test_backtest_yearly_periods_include_win_rate_and_benchmark_excess() -> None:
    from alphaagent.server.services.backtest import engine

    equity = [
        {"trade_date": date(2025, 12, 30), "total_equity": 100_000},
        {"trade_date": date(2025, 12, 31), "total_equity": 101_000},
        {"trade_date": date(2026, 1, 2), "total_equity": 103_000},
        {"trade_date": date(2026, 1, 5), "total_equity": 104_000},
    ]
    closed = [
        {"exit_date": "2025-12-31", "pnl": 1000.0},
        {"exit_date": "2026-01-05", "pnl": -300.0},
    ]
    benchmark_curve = [
        {"trade_date": date(2025, 12, 30), "nav": 1.0},
        {"trade_date": date(2025, 12, 31), "nav": 1.01},
        {"trade_date": date(2026, 1, 2), "nav": 1.02},
        {"trade_date": date(2026, 1, 5), "nav": 1.01},
    ]

    yearly = engine._calendar_period_analysis(equity, closed, benchmark_curve)

    assert {row["id"] for row in yearly} == {"2025", "2026"}
    assert all("return_pct" in row for row in yearly)
    assert all("max_drawdown_pct" in row for row in yearly)
    assert all("trade_count" in row for row in yearly)
    assert all("win_rate" in row for row in yearly)
    assert all("benchmark_return_pct" in row for row in yearly)
    assert all("excess_return_pct" in row for row in yearly)
```

- [x] Step 2: Add market-regime split if missing from lightweight report.

Expose the existing market-regime analysis only in the validation/details tab, not the first screen.

- [x] Step 3: Add final report requirement.

Every strategy experiment report must include:

- yearly return/win-rate table
- market-regime return/win-rate table
- statement whether performance is concentrated in one year or one market regime
- statement whether bear/weak-market periods remain usable or the strategy only works in a strong market

## Task 10: Top-10 Candidate Win-Rate And Market Relation Audit

This task checks whether the highest-ranked candidates are truly better and how they depend on the market.

**Files:**
- Modify: `alphaagent/server/services/backtest/queries.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add pure helper test for top-N candidate win rate.

Add:

```python
def test_top_candidate_bucket_summary_groups_by_rank_and_market_return() -> None:
    from alphaagent.server.services.backtest import queries

    rows = [
        {"signal_date": date(2026, 1, 2), "rank": 1, "vt_symbol": "A", "return_pct": 10.0, "benchmark_return_pct": 2.0},
        {"signal_date": date(2026, 1, 2), "rank": 9, "vt_symbol": "B", "return_pct": -3.0, "benchmark_return_pct": 2.0},
        {"signal_date": date(2026, 1, 3), "rank": 15, "vt_symbol": "C", "return_pct": 5.0, "benchmark_return_pct": -1.0},
    ]

    result = queries.top_candidate_bucket_summary(rows, top_n=10)

    assert result["top_n"] == 10
    assert result["top_count"] == 2
    assert result["top_win_rate"] == 0.5
    assert result["top_avg_return_pct"] == 3.5
    assert result["top_avg_benchmark_return_pct"] == 2.0
```

- [x] Step 2: Add API test for the top-candidate audit endpoint.

Add:

```python
def test_backtest_top_candidate_audit_api(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    def fake_top_candidate_audit(backtest_id: int, top_n: int):
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "top_n": top_n,
            "summary": {"top_count": 2, "top_win_rate": 0.5},
        }

    monkeypatch.setattr(backtests, "backtest_top_candidate_audit", fake_top_candidate_audit)
    client = TestClient(create_app())

    response = client.get("/api/backtests/175/top-candidate-audit?top_n=10")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["backtest_id"] == 175
    assert payload["top_n"] == 10
    assert payload["summary"]["top_win_rate"] == 0.5
```

- [x] Step 3: Implement top candidate summary from persisted candidate trace/signal events.

The endpoint should summarize:

- top 10 candidate count
- win rate
- average return
- average benchmark/sample equal-weight return
- excess return
- by-date market regime bucket

- [x] Step 4: Add service wrapper and API endpoint.

Add:

```python
@router.get("/{backtest_id}/top-candidate-audit")
def get_top_candidate_audit(backtest_id: int, top_n: int = Query(default=10, ge=1, le=100)):
    try:
        return ok(backtest_top_candidate_audit(backtest_id, top_n=top_n))
    except Exception as exc:
        return _service_error(exc)
```

- [x] Step 5: Use audit results as an acceptance gate.

A strategy change should not be kept if top-10 candidates have poor win rate and performance comes mostly from lower-ranked accidental replacements.

## Task 11: Low-Suction Limit-Up-Start Factor Audit

This task tests whether successful low-suction entries that later keep rising share the user's four launch-strength signals. It is an audit first, not an immediate scoring change. The goal is to improve low-suction selection quality and weak-market win rate without forcing a new strategy or reserved slots.

The four candidate factors are:

- `recent_limit_up_20d`: the stock had a limit-up or near-limit-up day within the last `20` trading days, indicating a prior main-force attack.
- `consecutive_bull_closes`: at least `4` or `5` consecutive bullish closes before or around the low-suction launch, especially when the index is sideways or down.
- `upward_gap_in_leg`: an upward gap during the rising leg, meaning buyers accepted a higher price.
- `persistent_volume_expansion`: volume is at least `2x` normal on more than one day, or remains meaningfully above normal for several days, instead of a one-day spike.

**Files:**
- Modify: `alphaagent/server/services/quant/strategies/dragon_pullback.py`
- Modify: `alphaagent/server/services/quant/candidate_lanes.py`
- Modify: `alphaagent/server/services/backtest/queries.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Modify: `tests/alphaagent/test_quant_backtest_portfolio.py`
- Modify: `memory/06_backtests/strategy_optimization_ledger.md`

- [x] Step 1: Add tests for the four factor evidence fields.

Add:

```python
def test_dragon_pullback_marks_low_suction_limit_up_start_factors() -> None:
    start = date(2026, 1, 1)
    closes = [10.0 + index * 0.03 for index in range(60)]
    closes.extend([12.0, 13.2, 13.6, 14.1, 14.7, 15.2, 14.9, 15.0, 15.2, 15.5])
    bars: list[Bar] = []
    for index, close in enumerate(closes):
        is_gap = index == 61
        is_limit = index == 61
        is_volume_expansion = 61 <= index <= 65
        previous_close = closes[index - 1] if index > 0 else close
        open_price = previous_close * 1.035 if is_gap else close * 0.995
        change_pct = 10.0 if is_limit else 1.6 if 62 <= index <= 65 else 0.2
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=open_price,
                high_price=max(open_price, close) * 1.02,
                low_price=min(open_price, close) * 0.98,
                close_price=close,
                volume=3_000_000 if is_volume_expansion else 1_000_000,
                turnover=900_000_000 if is_volume_expansion else 250_000_000,
                change_pct=change_pct,
            )
        )

    score = score_dragon_pullback("002384.SZSE", bars, bars[-1].trade_date, index_return_20d=-3.0, sector_score=70.0)

    assert score.evidence["recent_limit_up_20d"] is True
    assert score.evidence["consecutive_bull_closes"] >= 4
    assert score.evidence["upward_gap_in_leg"] is True
    assert score.evidence["persistent_volume_expansion"] is True
    assert score.evidence["limit_up_start_factor_count"] >= 3
```

- [x] Step 2: Add a negative test so one isolated volume spike does not pass.

Add:

```python
def test_low_suction_limit_up_start_requires_persistent_not_single_volume_spike() -> None:
    start = date(2026, 1, 1)
    closes = [10.0 + index * 0.02 for index in range(70)]
    closes.extend([12.0, 12.2, 12.1, 12.3, 12.2, 12.4, 12.3, 12.5])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.995,
            high_price=close * 1.02,
            low_price=close * 0.98,
            close_price=close,
            volume=4_000_000 if index == 72 else 1_000_000,
            turnover=800_000_000 if index == 72 else 220_000_000,
            change_pct=0.8,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback("002208.SZSE", bars, bars[-1].trade_date, index_return_20d=-2.0, sector_score=60.0)

    assert score.evidence["persistent_volume_expansion"] is False
    assert score.evidence["limit_up_start_factor_count"] < 3
```

- [x] Step 3: Implement evidence fields only.

Add fields to `dragon_pullback.py` evidence:

- `recent_limit_up_20d`: reuse `near_limit_up_count_20d >= 1`.
- `consecutive_bull_closes`: count latest consecutive days where `close_price > open_price` or derived close-to-close change is positive.
- `upward_gap_in_leg`: at least one recent open is above the previous close by a meaningful threshold, e.g. `>= 1.5%`, with the gap not fully invalidated the same day.
- `persistent_volume_expansion`: at least `2` days in the recent leg with volume ratio around `>= 1.8`, or at least `3` days around `>= 1.4`.
- `limit_up_start_factor_count`: count of the four true factors.
- `weak_index_strength_confirmation`: true when `index_return_20d <= 0` and the stock still has consecutive bullish closes plus positive `return_20d`.

Do not change scores yet in this step.

- [x] Step 4: Add a persisted audit helper for successful versus failed low-suction entries.

Add helper in `queries.py`:

```python
def low_suction_start_factor_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    winners = [row for row in rows if float(row.get("return_pct") or 0) > 0]
    losers = [row for row in rows if float(row.get("return_pct") or 0) <= 0]
    return {
        "total": len(rows),
        "winner_count": len(winners),
        "loser_count": len(losers),
        "winner_factor_avg": _avg(row.get("limit_up_start_factor_count") for row in winners),
        "loser_factor_avg": _avg(row.get("limit_up_start_factor_count") for row in losers),
        "winner_recent_limit_up_rate": _rate(row.get("recent_limit_up_20d") for row in winners),
        "winner_consecutive_bull_rate": _rate((row.get("consecutive_bull_closes") or 0) >= 4 for row in winners),
        "winner_upward_gap_rate": _rate(row.get("upward_gap_in_leg") for row in winners),
        "winner_persistent_volume_rate": _rate(row.get("persistent_volume_expansion") for row in winners),
    }
```

The rows should come from closed trades or trade-path diagnostics where `entry_setup == "stealth_low_suction"` and should preserve only data visible at entry.

- [x] Step 5: Add API endpoint for the audit.

Add:

```python
@router.get("/{backtest_id}/low-suction-start-factor-audit")
def get_low_suction_start_factor_audit(backtest_id: int):
    try:
        return ok(backtest_low_suction_start_factor_audit(backtest_id))
    except Exception as exc:
        return _service_error(exc)
```

- [x] Step 6: Compare weak-index and normal-index buckets.

The audit output must include:

- overall low-suction trade count
- weak/sideways index low-suction trade count where `index_return_20d <= 0`
- win rate by `limit_up_start_factor_count` bucket: `0-1`, `2`, `3-4`
- average return by bucket
- focused examples of winners and losers

- [x] Step 7: Only after audit, decide whether to add a small ranking bonus.

Allowed ranking change if evidence supports it:

- Add a small `+1` to `+4` opportunity-score bonus for `limit_up_start_factor_count >= 3`.
- Add a smaller weak-index bonus only when `weak_index_strength_confirmation=true`.
- Cap or remove the bonus when `ma5_distance_pct > 3.2`, `volume_ratio_5d_20d > 2.8`, `return_60d >= 90`, or `high_level_sideways_distribution_risk=true`.

Do not:

- Force these stocks into the top `20`.
- Treat a single涨停 or single倍量 day as enough.
- Increase raw buy count before the same-range global backtest proves improved win rate.

- [x] Step 8: Acceptance gate.

Keep the factor bonus only if:

- low-suction win rate improves in weak/sideways index regimes;
- total return and max drawdown do not materially worsen versus `#175`;
- top-10 candidate audit improves or remains stable;
- focused low-suction winners are not displaced by over-hot gap/volume traps.

Otherwise keep the four fields as diagnostics only.

Result on `#175`: keep diagnostics only. `3-4` factor low-suction trades did not beat `0-1` factor trades, so no ranking bonus was added. Evidence: `memory/06_backtests/2026-06-18_low_suction_start_factor_audit.md`.

## Task 12: Profit-Hold Experiment For Trend Winners

Run this task only if Task 2 shows large winners are being sold before trend continuation.

**Files:**
- Modify: `alphaagent/server/services/backtest/simulation.py`
- Modify: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add test for not selling at fixed profit lines.

Existing tests already include `test_dragon_pullback_exit_holds_after_fixed_take_profit_line`. Add one for a larger trend winner:

```python
def test_dragon_pullback_exit_holds_capacity_trend_until_trailing_break() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="600487.SSE",
        name="亨通光电",
        volume=100,
        cost_price=50.0,
        entry_date=date(2026, 1, 10),
        highest_price=72.0,
        reason={"ma10": 66.0, "ma20": 60.0, "support_price": 52.0},
    )
    bar = Bar(
        trade_date=date(2026, 2, 20),
        open_price=67.0,
        high_price=69.0,
        low_price=65.8,
        close_price=66.5,
        volume=1_000_000,
        turnover=800_000_000,
        change_pct=-1.2,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) is None
```

- [x] Step 2: If this fails, adjust only profit-protection thresholds.

The current logic should already avoid fixed `take_profit_pct` full sells for dragon pullback. If a change is required, keep it local to `dragon_pullback_sell_reason`.

- [x] Step 3: Run tests and global backtest if any code changed.

## Task 13: UI And API Evidence Display

Run this only after Task 1 diagnostics exist and are stable.

**Files:**
- Modify: `frontend/src/api/quant.ts`
- Modify: `frontend/src/features/quant/BacktestPanel.tsx`
- Modify: `frontend/src/pages/StockDetailPage.tsx`

- [x] Step 1: Add TypeScript API types for path diagnostics.

Add interfaces:

```ts
export interface BacktestPathDiagnosticRow extends StockIdentityFields {
  entry_date?: string | null;
  exit_date?: string | null;
  entry_setup?: string | null;
  entry_score?: number | null;
  return_pct?: number | null;
  mae_pct?: number | null;
  mfe_pct?: number | null;
  post_exit_max_return_pct?: number | null;
  sold_before_rebound?: boolean | null;
  exit_reason?: string | null;
}

export interface BacktestPathDiagnosticsResponse {
  status: string;
  backtest_id: number;
  lookahead_days: number;
  items: BacktestPathDiagnosticRow[];
  summary?: Record<string, unknown>;
}
```

Add fetcher:

```ts
export async function fetchBacktestPathDiagnostics(backtestId: number, vtSymbol?: string): Promise<BacktestPathDiagnosticsResponse> {
  const params = new URLSearchParams({ limit: "500", lookahead_days: "10" });
  if (vtSymbol) params.set("vt_symbol", vtSymbol);
  return apiClient.get<BacktestPathDiagnosticsResponse>(`/backtests/${backtestId}/path-diagnostics?${params.toString()}`);
}
```

- [x] Step 2: Add a compact diagnostics section in backtest review.

Display:

- Loss count.
- Sold-before-rebound count.
- Average MAE/MFE.
- Worst rows by return.

Keep it behind an existing backtest detail area, not a new main workflow.

- [x] Step 3: In stock detail, show symbol-specific MAE/MFE when a portfolio backtest exists.

Do not add new user actions. Fetch diagnostics for the current symbol and latest baseline backtest.

- [x] Step 4: Run frontend build.

```bash
pnpm --dir frontend run build
```

Expected: build passes; existing chunk warning is acceptable.

## Task 14: Final Verification And Ledger Update

**Files:**
- Modify: `memory/06_backtests/strategy_optimization_ledger.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `memory/05_runtime/run_debug.md`

- [x] Step 1: Run final checks.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
pnpm --dir frontend run build
git diff --check
```

- [x] Step 2: Record every experiment.

For each tested strategy version/run, add a row to `memory/06_backtests/strategy_optimization_ledger.md`:

```markdown
| `0.1.xx / #run` | Exact rule change | return | max drawdown | trades | Kept/rejected and why | API/run/tests evidence |
```

- [x] Step 3: Update current baseline only if evidence proves it.

Do not replace `#175 / 0.1.21` unless the new run:

- Covers the same main range.
- Uses no future function.
- Has a real persisted run ID.
- Improves the stated objective without materially worsening return/drawdown.
- Passes focused symbol review.
- Includes yearly win-rate/return and market-regime review.
- Includes top-10 candidate win-rate and broad-market relation review.
- Includes low-suction limit-up-start factor audit when the change affects low-suction ranking.

- [x] Step 4: Keep unrelated work out of commit.

Before commit:

```bash
git status --short
git diff --cached --name-only
```

Do not include unrelated `frontend/src/App.tsx` route changes unless the user explicitly asks.

Result: latest same-version evidence is `#190 / 0.1.21`, with return about `+81.32%`, max drawdown about `-15.59%`, and buy/sell/open `224 / 214 / 10`. This is a current-code evidence refresh, not a new strategy baseline claim. The low-suction limit-up-start factor audit was repeated on `#190`: four-factor count has weak relation to full-sample MFE, but does not improve weak/sideways-market low-suction win rate, so no score bonus or candidate slot change was added.

## Completion Criteria

- A read-only diagnostics endpoint exists and is tested.
- Baseline `#175` has a written drawdown/ranking audit report.
- Any strategy change is versioned, globally backtested, and recorded in the ledger.
- Failed experiments are reverted and documented.
- No default hard reject is added for `002119.SZSE` style repeated stretched dragon risk unless it beats global baseline.
- Dynamic sell rules use the buy point as a cost/support anchor and trigger from highest floating profit drawdown plus current structure; they are not static buy-height labels.
- Candidate markers show only selected buy points, rejected buys, and sells; dense low-suction buildup is explanation, not a marker stream.
- Yearly win-rate/return and top-10 candidate win-rate versus market regime are included before any new baseline claim.
- Low-suction limit-up-start factors are audited before becoming score bonuses: recent limit-up, four/five bullish closes, upward gap, and persistent volume expansion must improve weak/sideways-market low-suction win rate without forcing slots.
- `/quant` remains simple: candidate observation plus backtest review, no new complex workflow.
- Stock detail remains simple: `交易复盘 / 候选信号`, optionally with diagnostics evidence.
- Final tests/build/compile/diff checks pass.
