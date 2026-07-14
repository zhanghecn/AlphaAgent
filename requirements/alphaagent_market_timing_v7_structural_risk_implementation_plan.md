# Market Timing v7 Structural Risk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不引入仓位逻辑和未来函数的前提下，为市场择时增加通用的 `STRUCTURAL_BREAKDOWN_SILVER` 事件与因果 `danger_state`，覆盖结构性破位到真实修复的连续危险阶段。

**Architecture:** 信号层用纯函数从对齐的 `factor_seq / closes / up_ratios` 计算当日强破位条件和迟滞危险状态，仅在 `NORMAL -> DANGER` 时生成一次结构性银手指事件。面板复用同一组纯函数输出当前方向和逐日危险状态；前端只展示该状态，不把它接入量化候选、涨停策略或仓位逻辑。

**Tech Stack:** Python 3.11、SQLAlchemy、pytest、FastAPI 服务层、React 18、TypeScript、Vitest、Docker Compose。

---

### Task 1: 用失败测试固定结构性破位与无未来函数语义

**Files:**
- Modify: `tests/alphaagent/services/quant/test_market_timing_no_lookahead.py`
- Modify: `alphaagent/server/services/quant/market_timing/signal.py`

- [x] **Step 1: 添加可控结构性因子 helper**

在测试文件增加不会满足普通银区 `bull_force < 55`、但满足 v7 强破位条件的
factor：

```python
def _structural_factor(day: date) -> fac.MarketTimingFactors:
    return fac.MarketTimingFactors(
        trade_date=day,
        phase="rotation",
        trend=55.0,
        momentum=50.0,
        breadth=40.0,
        structure=45.0,
        volume=50.0,
        bull_force=55.6,
        bear_force=75.4,
        close_above_ma20=False,
        mom_5d=-0.2,
        mom_20d=1.1,
        macd_top=80.0,
        breadth_top=82.0,
        evidence={"trend_breakdown": 83.0},
    )
```

- [x] **Step 2: 添加候选、确认、迟滞与修复测试**

构造 25 日序列：前 20 日平稳，索引 20 强破位，索引 21 小涨但仍低于 MA5，
索引 24 收复 MA5、宽基修复且 `bear<65`。断言：

```python
states = sig.build_danger_states(factors, closes, up_ratios)
event = next(
    item for item in sig.detect_events(factors, closes, up_ratios)
    if item.setup_type == sig.SETUP_STRUCTURAL_BREAKDOWN_SILVER
)

assert states[20:24] == [sig.DANGER] * 4
assert states[24] == sig.NORMAL
assert event.trade_date == factors[20].trade_date
assert event.direction == "SILVER"
assert event.status == sig.STATUS_CONFIRMED
assert event.confirm_date == factors[21].trade_date
```

再构造候选次日立即满足修复条件的序列，断言事件保留但状态为
`INVALIDATED`，危险状态在次日回到 `NORMAL`。

- [x] **Step 3: 添加冲突优先级和残余危险测试**

直接守护 setup 仲裁：

```python
assert sig.candidate_setup(
    _structural_factor(day),
    reversal_gold=True,
    structural_breakdown=True,
) == ("SILVER", sig.SETUP_STRUCTURAL_BREAKDOWN_SILVER)

assert sig.candidate_setup(
    _structural_factor(day),
    reversal_gold=True,
    structural_breakdown=False,
) == ("GOLD", sig.SETUP_REVERSAL_GOLD)
```

端到端序列还要断言：危险状态尚未解除、但当日完整强破位条件已经消失时，
`REVERSAL_GOLD` 仍可生成；完整强破位条件重新成立时不重复生成结构性事件。

- [x] **Step 4: 添加缺失参与度和前缀稳定测试**

断言 `up_ratio=None` 不触发结构性 setup。先计算到候选日，再追加或污染未来
价格、因子和参与度，断言候选日及以前的结构性条件、事件存在性和
`danger_state` 完全不变，只允许候选状态在 `t+1` 更新：

```python
prefix_states = sig.build_danger_states(
    factors[:cut], closes[:cut], up_ratios[:cut]
)
polluted_states = sig.build_danger_states(
    polluted_factors, polluted_closes, polluted_up_ratios
)
assert polluted_states[:cut] == prefix_states
```

- [x] **Step 5: 运行目标测试并确认失败**

Run:

```bash
uv run pytest tests/alphaagent/services/quant/test_market_timing_no_lookahead.py -q -k "structural or danger"
```

Expected: 因缺少 setup 常量、危险状态函数和 `structural_breakdown` 参数而失败。

- [x] **Step 6: 实现固定常量和纯判断函数**

在 `signal.py` 增加：

```python
SETUP_STRUCTURAL_BREAKDOWN_SILVER = "STRUCTURAL_BREAKDOWN_SILVER"

NORMAL = "NORMAL"
DANGER = "DANGER"

STRUCTURAL_BEAR_MIN = 65.0
STRUCTURAL_BEAR_GAP_MIN = 15.0
STRUCTURAL_BREAKDOWN_MIN = 80.0
STRUCTURAL_MACD_TOP_MIN = 70.0
STRUCTURAL_UP_RATIO_MAX = 0.5
REPAIR_BEAR_MAX = 65.0
REPAIR_UP_RATIO_MIN = 0.5

def _sma_at(closes: list[float], index: int, window: int) -> float | None:
    if index < window - 1:
        return None
    return sum(closes[index - window + 1 : index + 1]) / window

def is_structural_breakdown(
    factor: MarketTimingFactors,
    closes: list[float],
    index: int,
    up_ratio: float | None,
) -> bool:
    ma20 = _sma_at(closes, index, 20)
    breakdown = float(factor.evidence.get("trend_breakdown") or 0.0)
    return bool(
        ma20 is not None
        and up_ratio is not None
        and factor.bear_force >= STRUCTURAL_BEAR_MIN
        and factor.bear_force - factor.bull_force >= STRUCTURAL_BEAR_GAP_MIN
        and breakdown >= STRUCTURAL_BREAKDOWN_MIN
        and closes[index] < ma20
        and factor.macd_top >= STRUCTURAL_MACD_TOP_MIN
        and up_ratio <= STRUCTURAL_UP_RATIO_MAX
    )
```

实现 `_is_danger_repaired`，只在 `MA5` 可用、`close>MA5`、
`up_ratio>=0.5`、`bear_force<65` 时返回真。`build_danger_states` 必须按索引顺序
更新状态；长度不对齐或参与度序列缺失时返回等长 `NORMAL`，不能猜测补齐。

- [x] **Step 7: 接入 setup 仲裁、事件去重和结构确认**

给 `candidate_setup` 增加关键字参数：

```python
def candidate_setup(
    factor: MarketTimingFactors,
    *,
    reversal_gold: bool = False,
    structural_breakdown: bool = False,
) -> tuple[str | None, str | None]:
    if structural_breakdown:
        return "SILVER", SETUP_STRUCTURAL_BREAKDOWN_SILVER
    if reversal_gold:
        return "GOLD", SETUP_REVERSAL_GOLD
    direction = candidate_direction(factor)
    if direction == "GOLD":
        return direction, SETUP_TREND_GOLD
    if direction == "SILVER":
        breakdown = float(factor.evidence.get("trend_breakdown") or 0.0)
        setup_type = (
            SETUP_BREAKDOWN_SILVER
            if breakdown >= SILVER_ENTER
            else SETUP_TOP_SILVER
        )
        return direction, setup_type
    return None, None
```

`detect_events` 预先计算结构 flags 和危险 states。只有当日 state 从 `NORMAL`
进入 `DANGER` 时生成结构性事件；危险阶段内强条件再次成立只影响当日方向，
不重复发结构事件，普通银 setup 也只显示当日银区而不重复计为同方向事件。
结构事件在序列末端为 `PENDING`，否则用下一日危险状态决定
`CONFIRMED / INVALIDATED`，并把下一交易日写入 `confirm_date`。

- [x] **Step 8: 运行全部信号守护测试**

Run:

```bash
uv run pytest tests/alphaagent/services/quant/test_market_timing_no_lookahead.py -q
```

Expected: PASS。

- [x] **Step 9: 提交纯信号层变更**

```bash
git add alphaagent/server/services/quant/market_timing/signal.py \
  tests/alphaagent/services/quant/test_market_timing_no_lookahead.py
git commit -m "feat(market-timing): add structural danger state"
```

### Task 2: 让面板输出一致的当前方向和逐日危险状态

**Files:**
- Modify: `alphaagent/server/services/quant/market_timing/panel.py`
- Modify: `tests/alphaagent/services/quant/test_market_timing_intraday.py`

- [x] **Step 1: 添加面板失败测试**

扩展 `_factor` helper 或增加结构 factor，测试 `_build_timing_series`：

```python
rows = mt_panel._build_timing_series(
    factors,
    events,
    closes,
    up_ratios,
)

assert rows[entry_index]["zone_direction"] == "SILVER"
assert rows[entry_index]["danger_state"] == sig.DANGER
assert all(
    row["danger_state"] == sig.DANGER
    for row in rows[entry_index:repair_index]
)
assert rows[repair_index]["danger_state"] == sig.NORMAL
```

增加当前方向测试：同日结构性条件与反转金重叠时为银；只有残余危险状态而完整
条件消失时，当前方向仍按当日反转金或普通 setup 计算。

- [x] **Step 2: 运行面板测试并确认失败**

Run:

```bash
uv run pytest tests/alphaagent/services/quant/test_market_timing_intraday.py -q -k "timing_series or current_direction"
```

Expected: `_build_timing_series` 不接收参与度且没有 `danger_state`。

- [x] **Step 3: 统一面板 setup 计算输入**

让 `_resolve_current_direction` 接收 `closes` 和 `up_ratios`，只用最后一个对齐
索引计算：

```python
structural = sig.is_structural_breakdown(
    latest,
    closes,
    len(closes) - 1,
    up_ratios[-1],
)
reversal = sig.is_reversal_gold(closes)
direction, _ = sig.candidate_setup(
    latest,
    reversal_gold=reversal,
    structural_breakdown=structural,
)
```

长度或参与度不对齐时结构 setup 必须关闭，但现有普通 setup 和反转金继续兼容。

- [x] **Step 4: 序列化每日和当前危险状态**

`_build_timing_series` 用 `sig.build_danger_states` 计算一次状态，并为每行输出：

```python
{
    "date": str(factor.trade_date),
    "bull_force": factor.bull_force,
    "bear_force": factor.bear_force,
    "zone_direction": zone_direction or "NEUTRAL",
    "danger_state": danger_states[index],
    "phase": factor.phase,
    "event": (
        {
            "direction": event.direction,
            "status": event.status,
            "grade": event.grade,
            "setup_type": event.setup_type,
            "confirm_date": (
                str(event.confirm_date) if event.confirm_date else None
            ),
        }
        if event is not None
        else None
    ),
}
```

`_build_overview` 增加 `danger_state`，值取最新逐日状态；`_compute_panel` 从
`factor_bars` 一次构造 `factor_closes / factor_up_ratios`，并传给事件、overview
和 timing series，避免三处日期错位。

- [x] **Step 5: 运行后端市场择时测试**

Run:

```bash
uv run pytest \
  tests/alphaagent/services/quant/test_market_timing_no_lookahead.py \
  tests/alphaagent/services/quant/test_market_timing_intraday.py \
  tests/alphaagent/services/quant/test_market_timing_backtest.py -q
```

Expected: PASS。

- [x] **Step 6: 提交面板变更**

```bash
git add alphaagent/server/services/quant/market_timing/panel.py \
  tests/alphaagent/services/quant/test_market_timing_intraday.py
git commit -m "feat(market-timing): expose structural danger state"
```

### Task 3: 在前端显示危险状态并保留 setup 审计

**Files:**
- Modify: `frontend/src/api/marketTiming.ts`
- Modify: `frontend/src/features/market-timing/timingPresentation.ts`
- Modify: `frontend/src/features/market-timing/timingPresentation.spec.ts`
- Modify: `frontend/src/features/market-timing/TimingHero.tsx`
- Modify: `frontend/src/features/market-timing/TimingRecentTable.tsx`

- [x] **Step 1: 添加类型和展示失败测试**

给测试 daily rows 增加 `danger_state`，并断言新 setup 文案：

```ts
expect(timingSetupLabel("STRUCTURAL_BREAKDOWN_SILVER")).toBe("结构性破位银手指");
expect(recentTimingRows(rows, 20).at(-1)?.danger_state).toBe("DANGER");
```

- [x] **Step 2: 运行前端测试并确认失败**

Run:

```bash
pnpm --dir frontend test -- timingPresentation.spec.ts
```

Expected: TypeScript setup 联合类型和文案映射缺少新值。

- [x] **Step 3: 扩展 API 类型**

在 `marketTiming.ts` 增加：

```ts
export type TimingDangerState = "NORMAL" | "DANGER";

export type TimingSetupType =
  | "TREND_GOLD"
  | "REVERSAL_GOLD"
  | "TOP_SILVER"
  | "BREAKDOWN_SILVER"
  | "STRUCTURAL_BREAKDOWN_SILVER";
```

`TimingOverview` 和 `TimingDailyState` 增加必填 `danger_state`；不把该字段加入量化
候选或下单类型。

- [x] **Step 4: 增加克制的状态展示**

`timingPresentation.ts` 增加 setup 标签。`TimingHero` 在阶段标签旁仅当
`danger_state === "DANGER"` 时显示 `结构风险：危险`，不显示仓位或操作建议。
`TimingRecentTable` 在“当日区域”前增加一行“结构风险”，单元格只显示“危险”或
“正常”，保持表格固定列宽和横向滚动。

```tsx
{overview.danger_state === "DANGER" && (
  <span className="rounded-md bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive">
    结构风险：危险
  </span>
)}
```

```tsx
<tr className="border-b border-border/50">
  <th className="px-2 py-2 text-left font-medium text-muted-foreground">结构风险</th>
  {rows.map((row) => (
    <td
      key={row.date}
      className={cn(
        "px-1 py-2 text-center font-medium",
        row.danger_state === "DANGER" ? "text-destructive" : "text-muted-foreground",
      )}
    >
      {row.danger_state === "DANGER" ? "危险" : "正常"}
    </td>
  ))}
</tr>
```

- [x] **Step 5: 运行前端测试与构建**

Run:

```bash
pnpm --dir frontend test -- timingPresentation.spec.ts
pnpm --dir frontend run build
```

Expected: PASS。

- [x] **Step 6: 提交前端变更**

```bash
git add frontend/src/api/marketTiming.ts \
  frontend/src/features/market-timing/timingPresentation.ts \
  frontend/src/features/market-timing/timingPresentation.spec.ts \
  frontend/src/features/market-timing/TimingHero.tsx \
  frontend/src/features/market-timing/TimingRecentTable.tsx
git commit -m "feat(market-timing): show structural danger state"
```

### Task 4: 固化真实数据证据和长期记忆

**Files:**
- Modify: `scripts/market_timing_eval.py`
- Modify: `memory/07_market_timing/market_timing_design.md`
- Modify: `requirements/alphaagent_market_timing_v7_structural_risk_design.md`
- Modify: `requirements/alphaagent_market_timing_v7_structural_risk_implementation_plan.md`

- [x] **Step 1: 扩展评估脚本的危险状态统计**

在已有 factor bars 对齐后调用：

```python
danger_states = sig.build_danger_states(
    factor_seq,
    [bar.close for bar in factor_bars],
    [bar.up_ratio for bar in factor_bars],
)
```

输出原始结构条件重入数、独立危险阶段数、危险/正常状态未来 5 日最大回撤
`<=-3%` 比例和未来 1 日平均收益。统计函数必须跳过未来窗口不足的尾部日期，
并明确日级状态存在序列相关。

- [x] **Step 2: 运行真实数据评估**

Run:

```bash
docker compose exec -T alphaagent-api python scripts/market_timing_eval.py
```

Expected: 固定 `2024-05-28..2026-07-13` 数据附近复现：10 次原始重入、5 个
可评估独立阶段、危险/正常状态未来 5 日最大回撤 `<=-3%` 约
`41.2% / 13.6%`。若数据库已新增交易日，报告新尾部并单独核对固定区间，不能
通过修改规则恢复旧数字。

- [x] **Step 3: 更新市场择时长期记忆**

在 `memory/07_market_timing/market_timing_design.md` 将当前状态更新为 v7：记录
新 setup、危险状态因果语义、`03-13 / 03-20 / 06-11` 回归、样本限制和验证
命令。替换过时 v6 当前状态，不追加聊天式流水；设计证据链接到两个 v7
requirements 文件。

- [x] **Step 4: 提交评估与记忆**

```bash
git add scripts/market_timing_eval.py \
  memory/07_market_timing/market_timing_design.md \
  requirements/alphaagent_market_timing_v7_structural_risk_design.md \
  requirements/alphaagent_market_timing_v7_structural_risk_implementation_plan.md
git commit -m "docs(market-timing): record structural risk evidence"
```

### Task 5: 全量验证、刷新缓存和真实页面验收

**Files:**
- No source changes expected

- [ ] **Step 1: 运行后端目标测试与编译**

```bash
uv run pytest \
  tests/alphaagent/services/quant/test_market_timing_no_lookahead.py \
  tests/alphaagent/services/quant/test_market_timing_intraday.py \
  tests/alphaagent/services/quant/test_market_timing_backtest.py -q
uv run python -m compileall alphaagent/server/services/quant/market_timing
```

Expected: 全部 PASS，compileall 无错误。

- [ ] **Step 2: 运行前端验证**

```bash
pnpm --dir frontend test -- timingPresentation.spec.ts
pnpm --dir frontend run build
```

Expected: PASS。

- [ ] **Step 3: 检查变更边界**

```bash
git diff --check HEAD~4..HEAD
git status --short
```

Expected: 市场择时提交不包含工作区已有的涨停、数据同步或其他量化修改；其他
用户变更可以继续留在工作区。

- [ ] **Step 4: 重建服务并强制刷新面板**

```bash
docker compose up --build -d alphaagent-api alphaagent-web
```

通过已登录本地网关调用 `POST /api/market-timing/refresh`。若命令行没有登录
cookie，使用浏览器登录态触发页面刷新，不绕过认证修改服务端安全配置。

- [ ] **Step 5: 核对真实面板合同**

检查 API/数据库 panel：

```text
2026-03-04 GOLD / REVERSAL_GOLD / CONFIRMED
2026-03-13 SILVER / STRUCTURAL_BREAKDOWN_SILVER / CONFIRMED(确认日 03-16)
2026-03-13..2026-03-23 danger_state=DANGER
2026-03-20 no REVERSAL_GOLD
2026-06-11 GOLD / REVERSAL_GOLD / CONFIRMED，允许残余 DANGER
2026-06-26 NEUTRAL，无反转金事件
2026-07-07 保持银手指行为
```

同时核对候选/确认表现起点、`factor_date / quote_date` 和事件日期完全对齐。

- [ ] **Step 6: 用 Playwright 验收桌面与移动端**

打开 `http://localhost:8080/market`，检查 `1920x1080` 与 `390x844`：当前风险
标签、最近交易日风险行、结构性 setup tooltip 正常；没有文字重叠、全页横向
溢出、控制台错误或网络 5xx。

- [ ] **Step 7: 报告提交和残余风险**

列出实现提交、设计提交 `39d828bf`、目标测试结果和真实日期回归。明确说明：
完整广度只有 516 日、独立危险阶段仅 5 个，且 `2026-03-13` 参与需求定义，
上线后必须冻结参数做前向观察。
