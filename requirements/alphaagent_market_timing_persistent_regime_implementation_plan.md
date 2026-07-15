# AlphaAgent 金银手指持续行情状态实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让最近一次已确认的金银手指从确认日起持续定义行情状态，直到相反手指确认，同时保留每日候选区域用于诊断。

**Architecture:** 在 `signal.py` 增加只依赖交易日和已确认事件的纯状态序列函数；`panel.py` 用该序列统一生成 `overview.current_direction` 与 `timing_series[].active_direction`。前端只展示后端状态，并把持续行情、候选区域和离散事件明确分开。

**Tech Stack:** Python 3.11、pytest、FastAPI JSON 载荷、React 18、TypeScript、Vitest、Vite、Docker Compose。

---

### Task 1: 建立因果的金银行情状态序列

**Files:**
- Modify: `tests/alphaagent/services/quant/test_market_timing_no_lookahead.py`
- Modify: `alphaagent/server/services/quant/market_timing/signal.py`

- [ ] **Step 1: 写持续状态与未来稳定性的失败测试**

在无未来函数测试中增加一个只构造事件的 helper：

```python
def _event(
    candidate_date: date,
    direction: str,
    status: str,
    confirm_date: date | None,
) -> sig.TimingSignal:
    return sig.TimingSignal(
        trade_date=candidate_date,
        direction=direction,
        status=status,
        grade="WEAK",
        bull_force=70.0 if direction == "GOLD" else 40.0,
        bear_force=70.0 if direction == "SILVER" else 40.0,
        phase="warming" if direction == "GOLD" else "retreat",
        setup_type=(
            sig.SETUP_TREND_GOLD
            if direction == "GOLD"
            else sig.SETUP_TOP_SILVER
        ),
        confirm_date=confirm_date,
        reasons=[],
    )
```

增加测试，明确确认日才生效、待确认和已否决不切换、相反确认才反转：

```python
def test_active_direction_starts_on_confirmation_and_persists_until_reversal():
    start = date(2026, 6, 11)
    dates = [start + timedelta(days=index) for index in range(6)]
    events = [
        _event(dates[0], "GOLD", sig.STATUS_CONFIRMED, dates[1]),
        _event(dates[2], "SILVER", sig.STATUS_INVALIDATED, dates[3]),
        _event(dates[4], "SILVER", sig.STATUS_PENDING, None),
    ]

    assert sig.build_active_directions(dates, events) == [
        "NEUTRAL",
        "GOLD",
        "GOLD",
        "GOLD",
        "GOLD",
        "GOLD",
    ]

    confirmed_reversal = events + [
        _event(dates[4], "SILVER", sig.STATUS_CONFIRMED, dates[5]),
    ]
    assert sig.build_active_directions(dates, confirmed_reversal) == [
        "NEUTRAL",
        "GOLD",
        "GOLD",
        "GOLD",
        "GOLD",
        "SILVER",
    ]
```

增加前缀稳定测试：

```python
def test_active_direction_history_is_stable_when_future_reversal_is_appended():
    start = date(2026, 6, 11)
    dates = [start + timedelta(days=index) for index in range(5)]
    gold = _event(dates[0], "GOLD", sig.STATUS_CONFIRMED, dates[1])
    silver = _event(dates[3], "SILVER", sig.STATUS_CONFIRMED, dates[4])

    prefix = sig.build_active_directions(dates[:4], [gold])
    complete = sig.build_active_directions(dates, [gold, silver])

    assert complete[:4] == prefix
    assert complete[-1] == "SILVER"
```

- [ ] **Step 2: 运行测试并确认因缺少纯函数而失败**

Run:

```bash
uv run --group server pytest tests/alphaagent/services/quant/test_market_timing_no_lookahead.py -q -k active_direction
```

Expected: FAIL，错误包含 `signal has no attribute 'build_active_directions'`。

- [ ] **Step 3: 实现最小纯状态函数**

在 `TimingSignal` 之后增加：

```python
def build_active_directions(
    trade_dates: list[date],
    events: list[TimingSignal],
) -> list[str]:
    """从确认日起延续最近金银方向，不读取确认日之后的数据。"""
    confirmed_by_date = {
        event.confirm_date: event.direction
        for event in events
        if event.status == STATUS_CONFIRMED and event.confirm_date is not None
    }
    active = "NEUTRAL"
    directions: list[str] = []
    for trade_date in trade_dates:
        confirmed = confirmed_by_date.get(trade_date)
        if confirmed in {"GOLD", "SILVER"}:
            active = confirmed
        directions.append(active)
    return directions
```

不要读取 `closes`、`up_ratios` 或收益标签，也不要修改 `detect_events`。

- [ ] **Step 4: 运行状态测试和完整无未来测试**

Run:

```bash
uv run --group server pytest tests/alphaagent/services/quant/test_market_timing_no_lookahead.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交领域层变更**

```bash
git add -- alphaagent/server/services/quant/market_timing/signal.py tests/alphaagent/services/quant/test_market_timing_no_lookahead.py
git commit -m "feat(market-timing): carry confirmed direction state"
```

### Task 2: 让面板统一输出持续行情状态

**Files:**
- Modify: `tests/alphaagent/services/quant/test_market_timing_intraday.py`
- Modify: `alphaagent/server/services/quant/market_timing/signal.py`
- Modify: `alphaagent/server/services/quant/market_timing/panel.py`

- [ ] **Step 1: 把面板测试改成持续状态契约**

删除直接验证 `_resolve_current_direction` 读取最新候选区的两个测试，增加：

```python
def test_timing_series_carries_confirmed_direction_through_neutral_zones():
    start = date(2026, 6, 11)
    factors = [
        _factor(start + timedelta(days=index), "GOLD" if index == 0 else "NEUTRAL")
        for index in range(5)
    ]
    events = [
        _signal(
            start,
            "GOLD",
            confirm_date=start + timedelta(days=1),
        ),
        _signal(
            start + timedelta(days=3),
            "SILVER",
            status=sig.STATUS_PENDING,
        ),
    ]

    rows = mt_panel._build_timing_series(factors, events)

    assert [row["active_direction"] for row in rows] == [
        "NEUTRAL",
        "GOLD",
        "GOLD",
        "GOLD",
        "GOLD",
    ]
    assert rows[-1]["zone_direction"] == "NEUTRAL"
```

增加 overview 契约测试：

```python
def test_overview_uses_active_direction_instead_of_latest_candidate_zone():
    day = date(2026, 7, 15)
    latest = _factor(day, "NEUTRAL")
    gold = _signal(
        date(2026, 6, 11),
        "GOLD",
        confirm_date=date(2026, 6, 12),
    )

    overview = mt_panel._build_overview(
        latest,
        gold,
        [{"date": "2026-07-14", "close": 100.0}, {"date": str(day), "close": 99.0}],
        "GOLD",
        sig.NORMAL,
    )

    assert overview["current_direction"] == "GOLD"
    assert overview["latest_signal"]["confirm_date"] == "2026-06-12"
```

在原 `test_timing_series_keeps_daily_dates_and_event_confirmation` 中补充
`active_direction` 断言，确认银事件只在 `confirm_date` 对应行开始生效。

增加盘中确认截止测试，确保次日盘中涨跌不能提前确认前一日候选：

```python
def test_confirmation_cutoff_keeps_next_day_intraday_event_pending():
    start = date(2026, 7, 14)
    factors = [_factor(start, "GOLD"), _factor(start + timedelta(days=1), "NEUTRAL")]

    events = sig.detect_events(
        factors,
        [100.0, 101.0],
        confirmed_through=start,
    )

    assert len(events) == 1
    assert events[0].status == sig.STATUS_PENDING
    assert events[0].confirm_date is None
```

- [ ] **Step 2: 运行面板目标测试并确认失败**

Run:

```bash
uv run --group server pytest tests/alphaagent/services/quant/test_market_timing_intraday.py -q -k "active_direction or overview_uses_active or timing_series_keeps"
```

Expected: FAIL，缺少 `active_direction`，`_build_overview` 尚未接受持续方向参数，
并且 `detect_events` 尚未接受 `confirmed_through`。

- [ ] **Step 3: 在逐日面板中接入状态序列**

在 `_build_timing_series` 进入循环前计算：

```python
active_directions = sig.build_active_directions(
    [factor.trade_date for factor in factors],
    events,
)
```

每行载荷增加：

```python
"active_direction": active_directions[index],
```

保留现有 `zone_direction` 计算，不能用持续状态覆盖它。

- [ ] **Step 4: 删除候选区版 current_direction，并由逐日状态驱动 overview**

删除 `_resolve_current_direction`。把 `_build_overview` 签名改为：

```python
def _build_overview(
    latest: Any,
    latest_signal: Any,
    index_bars: list[dict],
    current_direction: str,
    danger_state: str = sig.NORMAL,
) -> dict:
```

载荷直接使用：

```python
"current_direction": current_direction,
```

在 `_compute_panel` 构建完 `timing_series` 后计算并传入：

```python
current_direction = (
    timing_series[-1]["active_direction"] if timing_series else "NEUTRAL"
)
```

调用 `_build_overview` 时传入 `current_direction` 和 `latest_danger_state`，不再传
`factor_closes`、`factor_up_ratios`。`latest_signal` 仍取最后一个
`STATUS_CONFIRMED` 事件。

- [ ] **Step 5: 阻止盘中数据提前确认反转事件**

给 `detect_events` 增加可选确认截止日，不改变默认回测行为：

```python
def detect_events(
    factor_seq: list[MarketTimingFactors],
    closes: list[float] | None = None,
    up_ratios: list[float | None] | None = None,
    confirmed_through: date | None = None,
) -> list[TimingSignal]:
```

在得到 `status` 和 `confirm_index` 后、构造 `reasons` 前增加：

```python
if (
    confirm_index is not None
    and confirmed_through is not None
    and factor_seq[confirm_index].trade_date > confirmed_through
):
    status = STATUS_PENDING
    confirm_index = None
```

在 `_compute_panel` 判断是否追加盘中 bar：

```python
has_live_bar = live_index_bar is not None
events = sig.detect_events(
    factor_seq,
    factor_closes,
    factor_up_ratios,
    confirmed_through=end if has_live_bar else None,
)
```

因此昨日候选在今日盘中仍是 `PENDING`，只有收盘日线进入数据库并重算后才正式
切换；默认 `confirmed_through=None` 的研究和回测结果完全不变。

- [ ] **Step 6: 运行全部市场择时后端测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/services/quant/test_market_timing_backtest.py \
  tests/alphaagent/services/quant/test_market_timing_no_lookahead.py \
  tests/alphaagent/services/quant/test_market_timing_intraday.py -q
```

Expected: PASS；事件检测、准确率与现有关键日期断言不变。

- [ ] **Step 7: 提交面板契约变更**

```bash
git add -- alphaagent/server/services/quant/market_timing/signal.py alphaagent/server/services/quant/market_timing/panel.py tests/alphaagent/services/quant/test_market_timing_intraday.py
git commit -m "feat(market-timing): expose persistent market regime"
```

### Task 3: 展示本轮行情和逐日持续状态

**Files:**
- Modify: `frontend/src/api/marketTiming.ts`
- Modify: `frontend/src/features/market-timing/TimingHero.tsx`
- Modify: `frontend/src/features/market-timing/TimingHero.spec.tsx`
- Modify: `frontend/src/features/market-timing/TimingRecentTable.tsx`
- Create: `frontend/src/features/market-timing/TimingRecentTable.spec.tsx`
- Modify: `frontend/src/features/market-timing/timingPresentation.spec.ts`

- [ ] **Step 1: 写前端持续状态展示的失败测试**

把 `TimingHero.spec.tsx` 的 fixture 改为可传入当前方向和匹配的最近已确认事件。
金行情断言：

```tsx
expect(gold).toContain("当前行情");
expect(gold).toContain("金手指");
expect(gold).toContain("2026-06-12 确认");
expect(gold).toContain("持续至银手指确认");
expect(gold).not.toContain("当前无金银信号");
```

银行情使用 `latest_signal.direction="SILVER"`，断言：

```tsx
expect(silver).toContain("银手指");
expect(silver).toContain("持续至金手指确认");
```

中性 fixture 使用 `latest_signal=null`，继续断言“无信号”。

新建 `TimingRecentTable.spec.tsx`，构造中性、金行情和银行情三行：

```tsx
const rows: TimingDailyState[] = [
  {
    date: "2026-06-11",
    bull_force: 60,
    bear_force: 40,
    active_direction: "NEUTRAL",
    zone_direction: "GOLD",
    danger_state: "NORMAL",
    phase: "warming",
    event: null,
  },
  {
    date: "2026-06-12",
    bull_force: 55,
    bear_force: 45,
    active_direction: "GOLD",
    zone_direction: "NEUTRAL",
    danger_state: "NORMAL",
    phase: "warming",
    event: null,
  },
  {
    date: "2026-07-01",
    bull_force: 40,
    bear_force: 70,
    active_direction: "SILVER",
    zone_direction: "SILVER",
    danger_state: "DANGER",
    phase: "retreat",
    event: null,
  },
];

const html = renderToStaticMarkup(
  <TimingRecentTable series={rows} loading={false} />,
);
expect(html).toContain("行情状态");
expect(html).toContain("候选区域");
expect(html).toContain("金行情");
expect(html).toContain("银行情");
```

在 `timingPresentation.spec.ts` 的所有 `TimingDailyState` fixture 增加
`active_direction`。

- [ ] **Step 2: 运行组件测试并确认失败**

Run:

```bash
pnpm --dir frontend exec vitest run \
  src/features/market-timing/TimingHero.spec.tsx \
  src/features/market-timing/TimingRecentTable.spec.tsx \
  src/features/market-timing/timingPresentation.spec.ts
```

Expected: FAIL，类型缺少 `active_direction`，页面缺少持续状态文案和表格行。

- [ ] **Step 3: 扩展 TypeScript API 契约**

在 `TimingDailyState` 中增加：

```ts
active_direction: TimingDirection;
```

把文件顶部注释改为“金手指=金行情，银手指=银行情，直到相反已确认手指反转”，
不改变 `TimingDirection` 联合类型。

- [ ] **Step 4: 修改当前摘要为持续行情语义**

`SignalRing` 中心小标题由“当前状态”改为“当前行情”。在合力条下增加本轮说明：

```tsx
const activeSignal =
  overview.latest_signal?.direction === direction
    ? overview.latest_signal
    : null;
const reversalLabel = direction === "GOLD" ? "银手指" : "金手指";
```

```tsx
{direction !== "NEUTRAL" && activeSignal && (
  <p className="text-sm text-muted-foreground">
    本轮{DIRECTION_LABEL[direction]} · {activeSignal.confirm_date ?? activeSignal.date} 确认
    · 持续至{reversalLabel}确认
  </p>
)}
```

中性分支保留“当前无金银信号”。不要重新加入含糊的“最近信号”标签。

- [ ] **Step 5: 在最近交易日表区分行情、候选区和事件**

在“结构风险”与原区域行之间增加：

```tsx
<tr className="border-b border-border/50">
  <th className="px-2 py-2 text-left font-medium text-muted-foreground">行情状态</th>
  {rows.map((row) => (
    <td
      key={row.date}
      className={cn("px-1 py-2 text-center font-medium", directionClass(row.active_direction))}
    >
      {row.active_direction === "GOLD"
        ? "金行情"
        : row.active_direction === "SILVER"
          ? "银行情"
          : "中性"}
    </td>
  ))}
</tr>
```

把原“当日区域”表头改为“候选区域”，其单元格继续读取 `zone_direction`。

- [ ] **Step 6: 运行前端目标测试和生产构建**

Run:

```bash
pnpm --dir frontend test
pnpm --dir frontend run build
```

Expected: 全部测试 PASS，TypeScript 与 Vite 构建成功。

- [ ] **Step 7: 提交前端展示变更**

```bash
git add -- \
  frontend/src/api/marketTiming.ts \
  frontend/src/features/market-timing/TimingHero.tsx \
  frontend/src/features/market-timing/TimingHero.spec.tsx \
  frontend/src/features/market-timing/TimingRecentTable.tsx \
  frontend/src/features/market-timing/TimingRecentTable.spec.tsx \
  frontend/src/features/market-timing/timingPresentation.spec.ts
git commit -m "feat(market-timing): show persistent gold silver regime"
```

### Task 4: 更新当前事实并验证真实页面

**Files:**
- Modify: `memory/07_market_timing/market_timing_design.md`

- [ ] **Step 1: 更新持久项目记忆**

把“当前状态直接使用最新交易日候选区”的旧语义替换为：

```markdown
- “当前行情”使用最近一次已确认金银事件形成的因果状态：从 `confirm_date`
  起持续沿用该方向，直到相反方向事件确认；`PENDING/INVALIDATED` 不切换。
  `zone_direction` 仍仅表示当日候选区域，`active_direction` 表示逐日行情状态。
```

把旧的“当前摘要中性时不显示历史金手指”说明替换为：

```markdown
- 当前摘要读取 `overview.current_direction` 的持续行情状态，并用
  `overview.latest_signal.confirm_date` 解释本轮起点。最近交易日表分别展示
  `active_direction`、`zone_direction` 和事件确认状态，避免混淆行情、候选区和事件。
```

在证据中记录当前真实面板结论：`2026-06-11` 金手指于 `2026-06-12` 确认，
在没有已确认银手指反转时，`2026-07-15` 的 `current_direction` 与最后一条
`active_direction` 均为 `GOLD`。

- [ ] **Step 2: 运行完整静态和测试验证**

Run:

```bash
git diff --check
uv run --group server pytest \
  tests/alphaagent/services/quant/test_market_timing_backtest.py \
  tests/alphaagent/services/quant/test_market_timing_no_lookahead.py \
  tests/alphaagent/services/quant/test_market_timing_intraday.py -q
pnpm --dir frontend test
pnpm --dir frontend run build
```

Expected: `git diff --check` 无输出，后端和前端测试全部 PASS，生产构建成功。

- [ ] **Step 3: 重建服务并强制刷新面板缓存**

Run:

```bash
docker compose up --build -d alphaagent-api alphaagent-web
docker compose exec -T alphaagent-api python -c "import urllib.request; r=urllib.request.Request('http://127.0.0.1:8000/api/market-timing/refresh', method='POST'); print(urllib.request.urlopen(r, timeout=120).status)"
docker compose ps alphaagent-api alphaagent-web alphaagent-gateway
```

Expected: 刷新返回 `200`，三个服务均为 running/healthy。

- [ ] **Step 4: 校验真实面板状态契约**

Run:

```bash
docker compose exec -T alphaagent-api python -c "import json,urllib.request; p=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/market-timing/panel', timeout=30))['data']; o=p['overview']; r=p['timing_series'][-1]; assert o['current_direction']==r['active_direction']=='GOLD'; assert o['latest_signal']['date']=='2026-06-11'; assert o['latest_signal']['confirm_date']=='2026-06-12'; print(o['quote_date'],o['current_direction'],r['active_direction'],o['latest_signal']['confirm_date'])"
```

Expected: 输出最新行情日期以及 `GOLD GOLD 2026-06-12`。

- [ ] **Step 5: 用浏览器验证桌面和手机效果**

打开 `http://localhost:8080/market`，分别检查 `1440x1000` 与 `390x844`：

- 指环显示“当前行情 / 金手指”。
- 摘要显示“2026-06-12 确认”和“持续至银手指确认”。
- 最近交易日表存在“行情状态”和“候选区域”两行。
- 页面无横向整体溢出，控制台无 error/warning。

- [ ] **Step 6: 提交记忆更新**

```bash
git add -- memory/07_market_timing/market_timing_design.md
git commit -m "docs(market-timing): record persistent regime semantics"
```

- [ ] **Step 7: 最终检查提交边界**

Run:

```bash
git status --short
git log -6 --oneline
```

Expected: 本任务只提交市场择时相关文件；现有涨停研究工作区改动保持原样，未被
暂存、覆盖或提交。
