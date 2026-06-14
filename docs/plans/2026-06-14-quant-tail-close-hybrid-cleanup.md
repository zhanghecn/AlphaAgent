# Quant Tail Close Hybrid Cleanup Implementation Plan

> Superseded: 本计划已被 `docs/plans/2026-06-14-quant-cleanup-master-plan.md` 取代。后续执行以 master plan 为准，本文件仅保留历史上下文。

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 AlphaAgent 量化回测从“D 收盘信号 -> D+1 开盘/分钟回退”的旧模型，调整为用户当前认可的“历史日线尾盘代理 + 近端 14:30 真实分钟”的混合尾盘回测，并清理 5/10 分钟、CSV 主流程等残留复杂度。

**Architecture:** 新增一等执行模型 `tail_close_hybrid`，默认使用 D-1 候选/信号、D 日尾盘执行：有 D 日 14:30 分钟 bar 时用真实分钟价，否则用 D 日 close 作为尾盘代理价，并在 raw/audit/metrics 中分开统计。保留 `strict_1430` 作为严格分钟模式；旧 D+1 开盘模式仅作兼容/对比，前端默认不再强调。

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy Core, PostgreSQL, React + TypeScript + Vite, TanStack Query, pytest.

---

## 当前实现结论

- 当前核心文件是 `alphaagent/server/services/backtest/engine.py`。
- `BacktestParams` 目前用 `intraday_entry`、`minute_entry_required`、`minute_interval`、`tail_entry_*` 拼执行逻辑，没有明确的执行模型字段。
- 当前组合回测逻辑是：
  - D 日收盘后 `_score_day(..., current_day, ...)` 生成候选。
  - 买入加入 `pending_buys`，在 D+1 执行。
  - 买入优先 D+1 尾盘分钟 MA5，失败后回退 D+1 open；`minute_entry_required=true` 时拒单。
  - 卖出是 D 日收盘触发，D+1 open 执行。
- 这与用户当前策略不一致。用户要的是：
  - 历史没有分钟线时，用 D 日 close 近似尾盘成交。
  - 最近有 14:30 分钟线时，用真实 14:30 成交。
  - 不能让 CSV 成为主流程。
  - 5 分钟、10 分钟功能现在是多余复杂度。
- 当前普通 AkShare 路径可拿近端分钟线，例如 `2026-06-12 14:30`；但不能可靠覆盖 2025 至 2026-06-13 全历史。

## 要删除/隐藏的内容

1. 前端量化回测和数据同步 UI 删除 `5m/10m` 选择，只保留 `1m 14:30 快照`。
2. 后端组合回测停止接受新 `5m/10m` 参数；兼容旧回测展示，但新建回测统一归一为 `1m`。
3. 删除或废弃 TDX `10m` 聚合路径及其测试，除非其他数据导入仍明确依赖。
4. `/quant` 页面删除“严格分钟预设”按钮，改为执行模型选择。
5. CSV 导入/供应商 manifest 不作为主流程入口展示；保留为折叠的高级兜底或后台 API，避免误导用户以为 CSV 是推荐方案。
6. 报告中删除“D+1 开盘回退是默认”的文案，改为“日线尾盘代理 / 真实 14:30 / 严格拒单”三类。

## 要重构的内容

1. `BacktestParams` 增加 `execution_model`：
   - `tail_close_hybrid`：默认。D-1 候选，D 日尾盘执行；优先 14:30 分钟，没有则 D close 代理。
   - `strict_1430`：只有 D 日 14:30 分钟 bar 才成交，没有就拒单。
   - `legacy_next_open`：旧模型兼容，用于旧报告/对比，不作为默认 UI。
2. 将买入撮合从 `_resolve_buy_fill()` 拆成清晰函数：
   - `_resolve_tail_hybrid_buy_fill()`
   - `_resolve_strict_1430_buy_fill()`
   - `_resolve_legacy_next_open_buy_fill()`
3. 卖出撮合也要与执行模型一致：
   - `tail_close_hybrid`：持仓超过 T+1 后，D 日尾盘按 14:30 或 D close 代理卖出。
   - `strict_1430`：有 14:30 才卖；无分钟 bar 时保留持仓并记 rejected/blocked。
   - `legacy_next_open`：保留旧 D+1 open 逻辑。
4. 执行 raw 统一记录：
   - `execution_model`
   - `execution_mode`
   - `signal_date`
   - `execute_date`
   - `price_source`
   - `minute_bar_count`
   - `proxy_used`
   - `limit_blocked`
   - `ma5`
   - `ma5_distance_pct`
5. 指标和报告按照执行来源拆分：
   - `minute_1430_count`
   - `daily_close_proxy_count`
   - `strict_1430_rejected_count`
   - `limit_up_blocked_buy_count`
   - `limit_down_blocked_sell_count`

## 要调整的策略语义

1. `score_stock(..., trade_date)` 仍只使用 `trade_date` 及以前日线，不能未来函数。
2. 默认买入候选应从 D-1 生成，D 日尾盘执行。
3. D 日 close 只能作为“尾盘代理价/尾盘代理触发”，不能在报告里称为严格真实分钟。
4. 金安国纪这类个股复核时，要显示：
   - D-1 是否进入观察池。
   - D 日是否触发尾盘买入。
   - 成交价来源是 `minute_1430` 还是 `daily_close_proxy`。
   - 如果没买，原因是分数、MA5 偏离、涨停买不到、仓位不足还是数据缺失。

## 要新增的功能

1. 新增 AkShare 近端 14:30 缺口补数 provider：
   - `provider=akshare`
   - 读取 `AkShareAdapter.stock_bars(..., interval="1m", start_date=D, end_date=D)`
   - 只写入目标窗口 `14:30-14:30` 的 bar，避免全量分钟线膨胀。
   - 对历史取不到的数据明确返回 `source_unavailable_for_date`。
2. 数据管理页的分钟线任务默认：
   - 数据源：AkShare 近端。
   - 周期：固定 1m。
   - 窗口：固定 14:30。
   - dry-run 默认开启。
3. 回测报告增加“执行模型说明”和“代理/真实占比”。
4. 股票详情单股回测使用同一执行模型，不能和组合回测逻辑分叉。

---

### Task 1: 增加执行模型参数和兼容解析

**Files:**
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Modify: `frontend/src/features/quant/constants.ts`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Step 1: Write failing tests**

Add tests:

```python
def test_backtest_params_default_execution_model_is_tail_close_hybrid():
    params = engine.BacktestParams()
    assert params.execution_model == "tail_close_hybrid"
    assert params.minute_interval == "1m"


def test_backtest_params_rejects_new_5m_10m_backtests():
    with pytest.raises(ValueError):
        engine.BacktestParams(minute_interval="5m")
    with pytest.raises(ValueError):
        engine.BacktestParams(minute_interval="10m")
```

**Step 2: Run focused tests**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py::test_backtest_params_default_execution_model_is_tail_close_hybrid -q
```

Expected: fail because `execution_model` does not exist.

**Step 3: Implement minimal model parsing**

In `BacktestParams`, add:

```python
execution_model: str = "tail_close_hybrid"
```

Add helper:

```python
SUPPORTED_EXECUTION_MODELS = {"tail_close_hybrid", "strict_1430", "legacy_next_open"}

def _normalize_execution_model(value: Any) -> str:
    model = str(value or "tail_close_hybrid").strip().lower()
    aliases = {
        "hybrid": "tail_close_hybrid",
        "tail": "tail_close_hybrid",
        "strict": "strict_1430",
        "strict_minute": "strict_1430",
        "next_open": "legacy_next_open",
    }
    model = aliases.get(model, model)
    if model not in SUPPORTED_EXECUTION_MODELS:
        raise ValueError(f"Unsupported execution model: {model}")
    return model
```

In `__post_init__`, normalize it.

**Step 4: API payload compatibility**

Update `_params_from_payload()` and `create_backtest()` parsing to pass `execution_model`. If absent, default to `tail_close_hybrid`.

**Step 5: Frontend constants**

In `frontend/src/features/quant/constants.ts`:

```ts
export type ExecutionModel = "tail_close_hybrid" | "strict_1430" | "legacy_next_open";
export type MinuteInterval = "1m";
export const MINUTE_INTERVAL_OPTIONS = [{ value: "1m", label: "1分钟 / 14:30快照" }] as const;
```

Add `execution_model: "tail_close_hybrid"` to defaults.

**Step 6: Run tests**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
```

Expected: existing failures around 5m/10m references; fix in later tasks.

---

### Task 2: 实现 tail_close_hybrid 买入撮合

**Files:**
- Modify: `alphaagent/server/services/backtest/engine.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Step 1: Write failing tests**

Add tests:

```python
def test_tail_close_hybrid_buy_uses_1430_minute_when_available():
    # Build D-1 signal, D daily bar, D 14:30 minute bar.
    # Expect BUY on D with execution_mode == "minute_1430".
```

```python
def test_tail_close_hybrid_buy_uses_daily_close_proxy_when_minute_missing():
    # Build D-1 signal, D daily bar, no minute bars.
    # Expect BUY on D close with execution_mode == "daily_close_proxy".
```

**Step 2: Run tests**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "tail_close_hybrid_buy" -q
```

Expected: fail because current execution uses `daily_next_open_fallback` or `minute_tail_ma5`.

**Step 3: Add fill resolver**

Add:

```python
def _resolve_tail_hybrid_buy_fill(order, current_day, daily_bar, bar_index, minute_index, params):
    vt_symbol = str(order["vt_symbol"])
    signal_date = _as_date(order.get("signal_date"))
    ma5 = _ma5_for_entry_day(bar_index.get(vt_symbol, {}), signal_date)
    minute_bar = _exact_minute_bar(minute_index.get(vt_symbol, {}).get(current_day, []), params.tail_entry_start)
    if minute_bar:
        return _tail_fill_payload("minute_1430", minute_bar.close_price, current_day, signal_date, ma5, params, minute_bar)
    return _tail_fill_payload("daily_close_proxy", daily_bar.close_price, current_day, signal_date, ma5, params, None)
```

Use MA5 tolerance in both paths. If tolerance fails, return rejected `tail_entry_not_triggered`.

**Step 4: Dispatch by model**

Modify `_resolve_buy_fill()`:

```python
if params.execution_model == "tail_close_hybrid":
    return _resolve_tail_hybrid_buy_fill(...)
if params.execution_model == "strict_1430":
    return _resolve_strict_1430_buy_fill(...)
return _resolve_legacy_next_open_buy_fill(...)
```

**Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "tail_close_hybrid_buy or tail_entry" -q
```

Expected: pass after updating old expected mode names.

---

### Task 3: 调整默认买入时序为 D-1 候选、D 尾盘执行

**Files:**
- Modify: `alphaagent/server/services/backtest/engine.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Step 1: Write failing test**

```python
def test_tail_close_hybrid_uses_previous_trade_day_signal_for_same_day_tail_buy():
    # Given scores on 2026-06-11 and execution day 2026-06-12,
    # expect trade_date 2026-06-12, signal_date 2026-06-11.
```

**Step 2: Run test**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "previous_trade_day_signal" -q
```

Expected: fail until raw fields/modes are changed.

**Step 3: Keep pending architecture but change fill price**

The existing pending buy architecture already scores current day and executes next trading day. Keep it for `tail_close_hybrid`, but make the D+1 execution price tail-based instead of open-based. This means:

```text
score day = D-1
execute day = D
fill price = D 14:30 if present, else D close proxy
```

**Step 4: Add raw payload**

Ensure filled trade raw contains:

```json
{
  "execution_model": "tail_close_hybrid",
  "mode": "minute_1430|daily_close_proxy",
  "signal_date": "D-1",
  "execute_date": "D",
  "price_source": "stock_minute_bars|stock_daily_bars",
  "proxy_used": true|false
}
```

**Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "previous_trade_day_signal or tail_close_hybrid_buy" -q
```

Expected: pass.

---

### Task 4: 重构卖出撮合为尾盘模型并处理 T+1

**Files:**
- Modify: `alphaagent/server/services/backtest/engine.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Step 1: Write failing tests**

Add:

```python
def test_tail_close_hybrid_sell_uses_daily_close_proxy_and_respects_t_plus_one():
    # Buy on D, same D sell signal must not sell.
    # D+1 sell signal can fill at D+1 close proxy.
```

```python
def test_tail_close_hybrid_sell_uses_1430_minute_when_available():
    # Existing position, D 14:30 minute available.
    # Sell fill uses minute_1430_sell.
```

**Step 2: Run tests**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "tail_close_hybrid_sell" -q
```

Expected: fail because current sell is D+1 open.

**Step 3: Implement sell resolver**

Add:

```python
def _resolve_tail_hybrid_sell_fill(position, current_day, daily_bar, minute_index, params):
    minute_bar = _exact_minute_bar(...)
    if minute_bar:
        return {"status": "filled", "price": minute_bar.close_price, "mode": "minute_1430_sell", ...}
    return {"status": "filled", "price": daily_bar.close_price, "mode": "daily_close_proxy_sell", ...}
```

**Step 4: Fill same day after sell signal**

For `tail_close_hybrid`, when `_sell_reason()` returns a reason and `current_day > position.entry_date`, fill immediately on `current_day` using tail resolver instead of adding `pending_sells`.

**Step 5: Keep legacy path**

For `legacy_next_open`, keep existing `pending_sells` path unchanged.

**Step 6: Run tests**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "tail_close_hybrid_sell or signal_events" -q
```

Expected: pass after updating signal event expectations.

---

### Task 5: 增加涨跌停和不可成交处理

**Files:**
- Modify: `alphaagent/server/services/backtest/engine.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Step 1: Write failing tests**

Add:

```python
def test_tail_close_hybrid_rejects_buy_when_close_limit_up():
    # D close limit-up means proxy tail buy may not be executable.
```

```python
def test_tail_close_hybrid_blocks_sell_when_close_limit_down():
    # D close limit-down means sell is blocked and position remains.
```

**Step 2: Implement helpers**

Add board-aware helpers:

```python
def _daily_limit_pct(vt_symbol: str) -> float:
    # main board 10, STAR/ChiNext 20, BSE 30
```

```python
def _is_limit_up_close(vt_symbol: str, bar: Bar) -> bool:
    return bar.change_pct is not None and bar.change_pct >= _daily_limit_pct(vt_symbol) - 0.2
```

Same for limit down.

**Step 3: Wire into buy/sell**

- Buy: reject with reason `limit_up_tail_unfilled`.
- Sell: reject/block with reason `limit_down_tail_blocked`, position remains.

**Step 4: Run tests**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "limit_up or limit_down" -q
```

Expected: pass.

---

### Task 6: 更新指标、报告、审计文案

**Files:**
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `frontend/src/features/quant/BacktestAnalysis.tsx`
- Modify: `frontend/src/features/quant/BacktestSummary.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Step 1: Update metrics**

Replace old metric names:

- `minute_tail_entry_count` -> `minute_1430_count`
- `daily_open_fallback_count` -> `daily_close_proxy_count`

Keep old keys only if needed for old report compatibility.

**Step 2: Update execution quality report**

Report:

- 真实 14:30 成交占比。
- 日线收盘代理占比。
- 严格 14:30 拒单数量。
- 涨停买不到数量。
- 跌停卖不出数量。

**Step 3: Update method/assumptions**

`_backtest_method()` should say:

```text
D-1 收盘后生成 D 日观察池；D 日尾盘执行。若 D 日 14:30 分钟线存在则用真实分钟价，否则用 D close 作为尾盘代理价。
```

**Step 4: Update audit messages**

Add messages for:

- `minute_1430`
- `daily_close_proxy`
- `minute_1430_sell`
- `daily_close_proxy_sell`
- `limit_up_tail_unfilled`
- `limit_down_tail_blocked`

**Step 5: Run tests**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "report or audit or metrics" -q
```

Expected: pass.

---

### Task 7: 清理前端回测参数 UI

**Files:**
- Modify: `frontend/src/features/quant/constants.ts`
- Modify: `frontend/src/features/quant/BacktestParamsForm.tsx`
- Modify: `frontend/src/features/quant/BacktestPanel.tsx`
- Modify: `frontend/src/pages/QuantTradingPage.tsx`

**Step 1: Replace advanced checkboxes**

Remove:

- `尝试尾盘分钟入场`
- `强制分钟成交`
- `分钟周期 5m/10m`

Add segmented/select control:

```ts
const EXECUTION_MODEL_OPTIONS = [
  { value: "tail_close_hybrid", label: "尾盘混合" },
  { value: "strict_1430", label: "严格14:30" },
  { value: "legacy_next_open", label: "旧版D+1开盘" },
];
```

Default selected: `tail_close_hybrid`.

**Step 2: Remove strict preset button**

Remove `onStrictMinutePreset` from `BacktestPanel` header or convert it to set `execution_model="strict_1430"`.

**Step 3: Keep tail time simple**

Only show `14:30` time input if strict mode is selected; otherwise show read-only `14:30 快照 / D close 代理`.

**Step 4: Build**

Run:

```bash
pnpm --dir frontend run build
```

Expected: pass with existing Vite chunk warning only.

---

### Task 8: 清理数据管理页分钟线同步 UI

**Files:**
- Modify: `frontend/src/pages/DataManagementPage.tsx`
- Modify: `frontend/src/api/dataSync.ts`
- Modify: `alphaagent/server/services/data_sync.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Step 1: UI cleanup**

For “股票分钟 K 线”:

- Default mode remains `backtest_gaps`.
- Provider options: `AkShare近端`, `TDX公开源`, `Tushare Pro`, `vn.py本地库` if wired.
- Interval is fixed `1m` and no longer selectable.
- Tail start/end default and displayed as `14:30`。
- Hide CSV/manifests from primary UI.

**Step 2: Backend normalization**

In `_run_sync_stock_minute_gap_bars()`, normalize interval to `1m` for new calls.

**Step 3: Remove 10m aggregation tests**

Delete or rewrite:

- `test_stock_minute_sync_gap_mode_uses_tdx_1m_then_aggregates_10m`

**Step 4: Run tests**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "minute_sync" -q
pnpm --dir frontend run build
```

Expected: pass.

---

### Task 9: 新增 AkShare 14:30 缺口补数 provider

**Files:**
- Create: `alphaagent/server/services/data_providers/akshare_minute_import.py`
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `alphaagent/server/api/data_sync.py`
- Modify: `frontend/src/api/dataSync.ts`
- Modify: `frontend/src/pages/DataManagementPage.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Step 1: Write failing test**

```python
def test_akshare_gap_import_writes_only_1430_snapshot(monkeypatch):
    # Fake AkShareAdapter.stock_bars returns 240 rows including 14:30.
    # Expect _upsert_minute_bars called with one item.
```

**Step 2: Implement provider**

Provider signature:

```python
def import_akshare_minute_bars_for_gaps(
    *,
    gap_csv_text: str = "",
    gap_file_path: str = "",
    interval: str = "1m",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:30",
    dry_run: bool = True,
    max_gaps: int = 200,
) -> dict[str, Any]:
```

Rules:

- Only support `1m`.
- For each unique `(vt_symbol, trade_date)`, call `AkShareAdapter.stock_bars(... start_date=trade_date, end_date=trade_date)`.
- Filter `trade_date 14:30`.
- Write only filtered bars.
- Return `source_unavailable_for_date` for empty days.

**Step 3: Wire provider**

In `_normalize_minute_gap_provider`, accept `akshare`.

In `_run_sync_stock_minute_gap_bars`, dispatch to the new provider.

**Step 4: API endpoint**

Optional direct endpoint:

```text
POST /api/data-sync/imports/minute-bars/akshare-gaps
```

Only add if frontend needs direct provider import. Otherwise use existing job endpoint with `provider=akshare`.

**Step 5: Run tests**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "akshare_gap or minute_sync" -q
```

Expected: pass.

---

### Task 10: 更新严格流水线和缺口导出语义

**Files:**
- Modify: `alphaagent/server/services/backtest/strict_pipeline.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `frontend/src/features/quant/MinuteDataWizard.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Step 1: Rename strict mode semantics**

Strict pipeline should set:

```python
execution_model="strict_1430"
minute_interval="1m"
tail_entry_start="14:30"
tail_entry_end="14:30"
```

**Step 2: Gap export**

`backtest_minute_gap_csv()` should export rejected strict 14:30 orders only. Update note:

```text
用于补齐 D 日 14:30 快照，不再导出 5m/10m 或 14:30-14:57 区间。
```

**Step 3: Frontend**

`MinuteDataWizard` should say:

```text
严格 14:30 数据补数
```

and avoid encouraging CSV as the main path.

**Step 4: Run tests**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strict_minute or minute_gap" -q
pnpm --dir frontend run build
```

Expected: pass.

---

### Task 11: 金安国纪复核入口

**Files:**
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/quant.py`
- Modify: `frontend/src/pages/StockDetailPage.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Step 1: Add diagnostic fields**

For symbol signal history and single-symbol backtest, expose:

- observation date
- execution date
- candidate score
- entry signal true/false
- execution mode
- price source
- reject reason

**Step 2: Test 金安国纪 path generically**

Do not hardcode real DB data in unit test. Use synthetic `002636.SZSE` bars to verify:

- historical daily close proxy creates at least one buy when score rules pass.
- missing minute data no longer means zero trades in hybrid mode.

**Step 3: Browser verification target**

Manual smoke after implementation:

```text
/stocks/002636.SZSE
run single-symbol backtest
verify chart markers and audit show daily_close_proxy or minute_1430
```

---

### Task 12: Verification and cleanup

**Files:**
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/09_decisions/decisions.md`

**Step 1: Full backend tests**

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run pytest tests/alphaagent/test_api.py -q
```

Expected: pass.

**Step 2: Compile**

Run:

```bash
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/data_sources alphaagent/server/db
```

Expected: pass.

**Step 3: Frontend build**

Run:

```bash
pnpm --dir frontend run build
```

Expected: pass, only existing Vite chunk-size warning acceptable.

**Step 4: Docker rebuild**

Run:

```bash
docker compose up -d --build alphaagent-api alphaagent-web
```

Expected: API healthy, Web reachable at `http://localhost:5173`。

**Step 5: Real API smoke**

Run:

```bash
curl -sS http://localhost:8000/api/health
curl -sS -X POST http://localhost:8000/api/backtests \
  -H 'content-type: application/json' \
  -d '{"start":"2025-10-14","max_symbols":120,"execution_model":"tail_close_hybrid","persist":true}'
```

Expected:

- Backtest returns `status=ready`.
- Trades include `daily_close_proxy` and/or `minute_1430`.
- Report execution quality separates proxy vs true 14:30.

**Step 6: Real browser smoke**

Use Playwright/Node with `--no-sandbox` if root sandbox blocks Chromium:

- Open `http://localhost:5173/quant`
- Verify execution model selector exists.
- Verify 5m/10m no longer visible.
- Run backtest.
- Open selected report and verify execution quality labels.
- Open `http://localhost:5173/data`
- Verify “股票分钟 K 线” is fixed to `1m / 14:30` and AkShare provider is visible.

**Step 7: Memory hygiene**

Update memory with final durable facts:

- `memory/03_data/data_flow.md`: new minute provider and execution models.
- `memory/05_runtime/run_debug.md`: verification commands and result.
- `memory/09_decisions/decisions.md`: decision to use `tail_close_hybrid` as default, strict 14:30 as verification mode, CSV as last-resort admin path.

**Step 8: Commit**

Only commit if the user explicitly asks. Suggested commit message:

```bash
git add alphaagent/server frontend/src tests/alphaagent memory docs/plans
git commit -m "feat: add tail-close hybrid quant backtest"
```

---

## Implementation Order

1. Parameters and compatibility.
2. Hybrid buy fill.
3. Hybrid sell fill and T+1.
4. Limit-up/down handling.
5. Metrics/report/audit.
6. Frontend cleanup.
7. AkShare near-date 14:30 provider.
8. Strict pipeline cleanup.
9. 金安国纪 single-symbol verification.
10. Full tests, Docker, browser smoke, memory update.

## Non-Goals

- 不用 CSV 作为推荐主流程。
- 不承诺 AkShare 能补齐 2025 至 2026-06-13 全历史分钟线。
- 不把 D close proxy 称为严格真实分钟回测。
- 不在本次重构里接券商实盘下单。
- 不修改 `vnpy/` 官方核心。
