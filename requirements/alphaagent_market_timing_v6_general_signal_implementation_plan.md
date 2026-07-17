# Market Timing v6 General Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不引入仓位逻辑和未来函数的前提下，为 `/market` 增加经过长历史验证的 `REVERSAL_GOLD` 弱势衰竭反转金，并保留现有银手指行为。

**Architecture:** 历史/盘中综合指数增加宽基上涨参与度；信号层用纯函数从 `<=t` 收盘序列识别反转金候选，再由 `t+1` 价格和参与度更新确认状态。事件增加 `setup_type`，面板直接使用最新日候选区作为当前方向，不再沿用历史事件模拟持仓状态。

**Tech Stack:** Python 3.11、SQLAlchemy、FastAPI 服务层、pytest、React 18、TypeScript、Vitest、Docker Compose、Playwright CLI。

---

### Task 1: 用失败测试固定反转金和无未来函数语义

**Files:**
- Modify: `tests/alphaagent/services/market_timing/test_market_timing_no_lookahead.py`
- Modify: `alphaagent/server/services/market_timing/signal.py`

- [ ] **Step 1: 添加可控弱势收盘序列 helper**

在测试中构造至少 24 个收盘价，使候选日满足 RSI2、10 日收益、20 日回撤和
日涨跌幅四个边界。因子本身保持银区，以验证反转金的因果优先级：

```python
def _reversal_closes() -> list[float]:
    closes = [100.0 + index * 0.1 for index in range(12)]
    closes.extend([100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0, 92.0])
    closes.extend([91.4, 90.9, 91.5])
    return closes
```

- [ ] **Step 2: 添加反转候选、确认、参与度和优先级测试**

断言候选日输出 `GOLD / REVERSAL_GOLD`；次日上涨且 `up_ratio>=0.5` 时
`CONFIRMED`，参与度不足时 `INVALIDATED`；候选日仍然是弱银因子时也由反转金
优先。

```python
events = sig.detect_events(factors, closes, up_ratios=[1.0] * len(closes))
event = next(item for item in events if item.setup_type == sig.SETUP_REVERSAL_GOLD)
assert event.trade_date == factors[-2].trade_date
assert event.direction == "GOLD"
assert event.status == sig.STATUS_CONFIRMED
assert event.confirm_date == factors[-1].trade_date
```

- [ ] **Step 3: 添加边界和冷却测试**

覆盖当日跌幅 `<-1%`、10 日跌幅 `>-2%`、20 日回撤 `>-3%` 均不触发；连续
反转区只记录一次，10 个交易日内不重复记录同类候选。

- [ ] **Step 4: 添加 prefix 稳定测试**

先用候选日为序列末端运行，再追加任意未来数据；断言候选的日期、方向和
`setup_type` 不变，只允许 `status/confirm_date` 从 `PENDING` 更新。

- [ ] **Step 5: 运行测试并确认失败**

Run: `uv run pytest tests/alphaagent/services/market_timing/test_market_timing_no_lookahead.py -q`

Expected: 新测试因缺少 `SETUP_REVERSAL_GOLD`、`setup_type` 和第三个参数失败。

- [ ] **Step 6: 实现最小候选纯函数和事件元数据**

在 `signal.py` 定义 setup 常量和固定阈值，并让候选 helper 只读取传入前缀：

```python
SETUP_TREND_GOLD = "TREND_GOLD"
SETUP_REVERSAL_GOLD = "REVERSAL_GOLD"
SETUP_TOP_SILVER = "TOP_SILVER"
SETUP_BREAKDOWN_SILVER = "BREAKDOWN_SILVER"

REVERSAL_RSI2_MAX = 20.0
REVERSAL_RETURN_10D_MAX = -2.0
REVERSAL_DRAWDOWN_20D_MAX = -3.0
REVERSAL_RETURN_1D_MIN = -1.0
REVERSAL_RETURN_1D_MAX = 0.5
REVERSAL_COOLDOWN = 10

def is_reversal_gold(closes: list[float]) -> bool:
    if len(closes) < 21:
        return False
    return_1d = (closes[-1] / closes[-2] - 1.0) * 100.0
    return_10d = (closes[-1] / closes[-11] - 1.0) * 100.0
    drawdown_20d = (closes[-1] / max(closes[-20:]) - 1.0) * 100.0
    rsi2 = ser.rsi(closes, 2)
    return bool(
        rsi2 is not None
        and rsi2 <= REVERSAL_RSI2_MAX
        and return_10d <= REVERSAL_RETURN_10D_MAX
        and drawdown_20d <= REVERSAL_DRAWDOWN_20D_MAX
        and REVERSAL_RETURN_1D_MIN <= return_1d <= REVERSAL_RETURN_1D_MAX
    )
```

`TimingSignal` 增加默认 `setup_type`；`detect_events` 接收可选
`up_ratios: list[float | None] | None`，反转金先于原候选区，使用独立 10 日冷却。
反转金确认要求次日上涨且可用 `up_ratio>=0.5`；参与度缺失时只检查上涨。

- [ ] **Step 7: 运行无未来函数测试**

Run: `uv run pytest tests/alphaagent/services/market_timing/test_market_timing_no_lookahead.py -q`

Expected: PASS。

### Task 2: 给综合指数增加宽基上涨参与度

**Files:**
- Modify: `alphaagent/server/services/market_timing/series.py`
- Modify: `tests/alphaagent/services/market_timing/test_market_timing_intraday.py`

- [ ] **Step 1: 添加盘中参与度失败测试**

构造 4 个上涨、3 个下跌的指数 quote，断言：

```python
bar = ser.intraday_today_bar(100.0, 1e9)
assert bar is not None
assert bar.up_ratio == pytest.approx(4 / 7)
```

- [ ] **Step 2: 运行单测并确认失败**

Run: `uv run pytest tests/alphaagent/services/market_timing/test_market_timing_intraday.py -q -k up_ratio`

Expected: `CompositeBar` 没有 `up_ratio`。

- [ ] **Step 3: 扩展 CompositeBar 和历史合成**

在字段末尾增加兼容默认值：

```python
@dataclass(frozen=True)
class CompositeBar:
    trade_date: date
    close: float
    turnover: float
    return_pct: float
    up_ratio: float | None = None
```

`load_composite_series` 在每个交易日按有前收盘的有效指数统计 `up_count` 和
`valid_count`，用 `up_count / valid_count` 写入 bar。首日没有前收盘时为 `None`。

- [ ] **Step 4: 扩展盘中合成**

`intraday_today_bar` 在已有有效 ret 循环内累计上涨数和有效数，并把比例写入
返回 bar；不改变无行情、零成交量和异常退化逻辑。

- [ ] **Step 5: 运行序列和盘中测试**

Run: `uv run pytest tests/alphaagent/services/market_timing/test_market_timing_intraday.py tests/alphaagent/services/market_timing/test_market_timing_no_lookahead.py -q`

Expected: PASS。

### Task 3: 让面板按 v6 区域和 setup 输出

**Files:**
- Modify: `alphaagent/server/services/market_timing/panel.py`
- Modify: `tests/alphaagent/services/market_timing/test_market_timing_intraday.py`

- [ ] **Step 1: 修改当前方向测试为非持仓语义**

把旧“中性沿用银手指”断言替换为：

```python
assert mt_panel._resolve_current_direction(_factor(day, "GOLD"), silver) == "GOLD"
assert mt_panel._resolve_current_direction(_factor(day, "NEUTRAL"), silver) == "NEUTRAL"
```

增加反转金日的 `timing_series` 断言，检查 `zone_direction="GOLD"`、
`setup_type="REVERSAL_GOLD"`。

- [ ] **Step 2: 运行面板测试并确认失败**

Run: `uv run pytest tests/alphaagent/services/market_timing/test_market_timing_intraday.py -q`

Expected: 中性日仍返回最后银手指，序列没有 `setup_type`。

- [ ] **Step 3: 接入 up_ratio 和历史前缀**

`_compute_panel` 改为：

```python
events = sig.detect_events(
    factor_seq,
    [bar.close for bar in comp],
    [bar.up_ratio for bar in comp],
)
```

让 `_build_timing_series` 接收 `closes`，逐日调用信号层的 setup helper，避免页面
继续用旧 `candidate_direction(factor)` 计算区域。

- [ ] **Step 4: 序列化 setup_type 并修复当前方向**

在 overview 的 `latest_signal`、chart signals、timing daily event 和 accuracy rows
中透传 `setup_type`。`_resolve_current_direction` 只返回最新候选区或
`NEUTRAL`，不读取 `latest_signal` 作为兜底。

- [ ] **Step 5: 运行后端目标测试**

Run: `uv run pytest tests/alphaagent/services/market_timing/test_market_timing_no_lookahead.py tests/alphaagent/services/market_timing/test_market_timing_intraday.py tests/alphaagent/services/market_timing/test_market_timing_backtest.py -q`

Expected: PASS。

### Task 4: 保留 setup 级表现审计和前端类型

**Files:**
- Modify: `alphaagent/server/services/market_timing/backtest.py`
- Modify: `tests/alphaagent/services/market_timing/test_market_timing_backtest.py`
- Modify: `frontend/src/api/marketTiming.ts`
- Modify: `frontend/src/features/market-timing/TimingRecentTable.tsx`
- Modify: `frontend/src/features/market-timing/timingPresentation.spec.ts`

- [ ] **Step 1: 添加表现行 setup_type 失败测试**

让测试事件带 `setup_type=SETUP_REVERSAL_GOLD`，断言确认后和候选行都保留：

```python
assert confirmed_row["setup_type"] == sig.SETUP_REVERSAL_GOLD
assert candidate_row["setup_type"] == sig.SETUP_REVERSAL_GOLD
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `uv run pytest tests/alphaagent/services/market_timing/test_market_timing_backtest.py -q`

Expected: row 缺少 `setup_type`。

- [ ] **Step 3: 在表现明细透传 setup_type**

`backtest._evaluate_rows` 增加 `"setup_type": ev.setup_type`；
`panel._serialize_accuracy_rows` 同步序列化。现有 buckets 继续按方向/档位聚合，
避免破坏 API。

- [ ] **Step 4: 更新 TypeScript 类型和最近事件提示**

增加：

```ts
export type TimingSetupType =
  | "TREND_GOLD"
  | "REVERSAL_GOLD"
  | "TOP_SILVER"
  | "BREAKDOWN_SILVER";
```

在 `TimingSignal`、`TimingDailyEvent`、`AccuracyRow` 和 latest signal 增加
`setup_type`。最近交易日事件的 title 对反转金显示“弱势衰竭反转金”，其余
显示方向和候选/确认日期，不新增仓位文案。

- [ ] **Step 5: 运行前端测试和构建**

Run: `pnpm --dir frontend test -- timingPresentation.spec.ts`

Expected: PASS。

Run: `pnpm --dir frontend run build`

Expected: PASS。

### Task 5: 真实数据回归、缓存刷新和浏览器验收

**Files:**
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/07_market_timing/market_timing_design.md`

- [ ] **Step 1: 运行完整目标测试**

Run: `uv run pytest tests/alphaagent/services/market_timing/test_market_timing_no_lookahead.py tests/alphaagent/services/market_timing/test_market_timing_intraday.py tests/alphaagent/services/market_timing/test_market_timing_backtest.py -q`

Expected: PASS。

- [ ] **Step 2: 运行后端编译和前端全量验证**

Run: `uv run python -m compileall alphaagent/server/services/market_timing`

Run: `pnpm --dir frontend test`

Run: `pnpm --dir frontend run build`

Expected: 全部 PASS。

- [ ] **Step 3: 重建本地服务并强制刷新**

Run: `docker compose up --build -d alphaagent-api alphaagent-web`

然后通过已登录网关调用 `POST /api/market-timing/refresh`，避免 24 小时数据库缓存
继续返回 v5 事件。

- [ ] **Step 4: 核对真实 API 事件**

检查 panel JSON：

```text
2026-06-11 GOLD / REVERSAL_GOLD / CONFIRMED / 2026-06-12
2026-06-26 no REVERSAL_GOLD
2026-07-07 SILVER / CONFIRMED / 2026-07-08
```

同时核对 `factor_date`、`quote_date`、正式/否决/待确认计数和两套表现起点。

- [ ] **Step 5: 用 Playwright 验收桌面和移动端**

打开 `http://localhost:8080/market`，检查 `1920x1080` 和 `390x844`：K 线信号、
最近日期、setup 提示正常；无文字重叠、全页横向溢出或控制台错误。

- [ ] **Step 6: 更新长期记忆**

在 `memory/07_market_timing/market_timing_design.md` 用 v6 当前状态替换 v5 当前
结论；在 `memory/06_backtests/README.md` 链接设计和固定分段证据，不粘贴原始
实验日志。

> 项目规则禁止未获授权的 `git commit` 和 `git push`，因此本计划没有提交步骤。
