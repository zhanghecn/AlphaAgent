# AlphaAgent 金银手指悬停与方向语义实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让市场择时 K 线按 A 股软件习惯显示中文日期和行情数据，并把 6 月 11 日后的用户结果持续显示为金手指，直到银手指确认反转。

**Architecture:** 纯展示映射模块把 `chart.bars` 与 `timing_series` 按日期合并，并将最近非中性的 `active_direction` 延续到后续实时报价日；`TimingChart` 只展示金手指或银手指延续，不展示内部候选区。主摘要和最近交易日表使用相同的“手指状态”语义。

**Tech Stack:** React 18、TypeScript、Lightweight Charts 4.2、Vitest、Vite、Playwright CLI、Docker Compose。

---

### Task 1: 建立可测试的悬停日期与状态映射

**Files:**
- Create: `frontend/src/features/market-timing/timingChartPresentation.ts`
- Create: `frontend/src/features/market-timing/timingChartPresentation.spec.ts`

- [ ] **Step 1: 写 7 月 2 日展示事实的失败测试**

测试 fixture 包含 7 月 1 日被否决的金候选和 7 月 2 日中性区域：

```ts
const bars: TimingBar[] = [
  { date: "2026-06-30", open: 100, high: 102, low: 99, close: 100, volume: 1, turnover: 1 },
  { date: "2026-07-01", open: 100, high: 104, low: 99, close: 102, volume: 1, turnover: 1 },
  { date: "2026-07-02", open: 102, high: 103, low: 98, close: 99, volume: 1, turnover: 1 },
];

const series: TimingDailyState[] = [
  {
    date: "2026-07-01",
    bull_force: 67.0164,
    bear_force: 43.9,
    active_direction: "GOLD",
    zone_direction: "GOLD",
    danger_state: "NORMAL",
    phase: "retreat",
    event: {
      direction: "GOLD",
      status: "INVALIDATED",
      grade: "MEDIUM",
      setup_type: "TREND_GOLD",
      confirm_date: "2026-07-02",
    },
  },
  {
    date: "2026-07-02",
    bull_force: 53.6375,
    bear_force: 55.4,
    active_direction: "GOLD",
    zone_direction: "NEUTRAL",
    danger_state: "NORMAL",
    phase: "retreat",
    event: null,
  },
];
```

断言：

```ts
const summary = buildTimingHoverSummaries(bars, series).get("2026-07-02");

expect(summary?.date).toBe("2026-07-02");
expect(summary?.changePct).toBeCloseTo(-2.9412, 4);
expect(summary?.state?.zone_direction).toBe("NEUTRAL");
expect(summary?.activeDirection).toBe("GOLD");
expect(timingActiveLabel(summary?.activeDirection ?? null)).toBe("金手指延续");
```

日期格式测试：

```ts
expect(formatTimingCrosshairDate("2026-07-02")).toBe("2026-07-02");
expect(formatTimingCrosshairDate({ year: 2026, month: 7, day: 2 })).toBe("2026-07-02");
expect(formatTimingAxisTick("2026-07-02")).toBe("07-02");
```

- [ ] **Step 2: 运行测试并确认模块不存在**

Run:

```bash
pnpm --dir frontend exec vitest run src/features/market-timing/timingChartPresentation.spec.ts
```

Expected: FAIL，错误为无法导入 `timingChartPresentation`。

- [ ] **Step 3: 实现纯映射与标签函数**

创建以下公开接口：

```ts
export interface TimingHoverSummary {
  date: string;
  bar: TimingBar;
  changePct: number | null;
  state: TimingDailyState | null;
  activeDirection: TimingDirection;
}

export function formatTimingCrosshairDate(time: Time): string;
export function formatTimingAxisTick(time: Time): string;
export function buildTimingHoverSummaries(
  bars: TimingBar[],
  series: TimingDailyState[],
): Map<string, TimingHoverSummary>;
export function timingActiveLabel(direction: TimingDirection | null): string;
export function timingEventLabel(event: TimingDailyEvent | null): string;
```

规则实现：

```ts
export function timingActiveLabel(direction: TimingDirection | null): string {
  if (direction === "GOLD") return "金手指延续";
  if (direction === "SILVER") return "银手指延续";
  return "尚无手指";
}
```

`timingEventLabel` 对 `INVALIDATED` 返回“无”，只把 `CONFIRMED/PENDING` 显示为
当日新手指，避免同方向失败候选干扰持续状态。

`buildTimingHoverSummaries` 必须：

1. 用 `series[].date` 建立当日状态索引。
2. 按 K 线日期顺序维护最近非中性的 `active_direction`。
3. 用前一根 K 线收盘计算涨跌幅。
4. 实时 K 线没有同日因子行时，内部 `state=null`，但用户金银状态继续沿用。

日期函数对字符串、Unix 秒和 `BusinessDay` 都输出稳定数字格式；日 K 轴刻度只输出
`MM-DD`，十字线标签输出 `YYYY-MM-DD`。

- [ ] **Step 4: 运行纯展示测试**

Run:

```bash
pnpm --dir frontend exec vitest run src/features/market-timing/timingChartPresentation.spec.ts
```

Expected: PASS。

- [ ] **Step 5: 提交纯展示层**

```bash
git add -- frontend/src/features/market-timing/timingChartPresentation.ts frontend/src/features/market-timing/timingChartPresentation.spec.ts
git commit -m "test(market-timing): define hover audit semantics"
```

### Task 2: 接入同花顺式悬停摘要并修正页面术语

**Files:**
- Modify: `frontend/src/features/market-timing/TimingChart.tsx`
- Modify: `frontend/src/pages/MarketTimingPage.tsx`
- Modify: `frontend/src/features/market-timing/TimingHero.tsx`
- Modify: `frontend/src/features/market-timing/TimingHero.spec.tsx`
- Modify: `frontend/src/features/market-timing/TimingRecentTable.tsx`
- Modify: `frontend/src/features/market-timing/TimingRecentTable.spec.tsx`

- [ ] **Step 1: 先修改组件测试为正确术语**

`TimingHero.spec.tsx` 的金方向断言改为：

```ts
expect(gold).toContain("手指状态");
expect(gold).toContain("金手指");
expect(gold).toContain("2026-06-12 起");
expect(gold).toContain("等待银手指反转");
expect(gold).not.toContain("当前行情");
```

银方向断言改为包含“尚无金手指反转”。

`TimingRecentTable.spec.tsx` 改为：

```ts
expect(html).toContain("手指状态");
expect(html).toContain("金延续");
expect(html).toContain("银延续");
expect(html).not.toContain("候选区域");
expect(html).not.toContain("中性");
```

- [ ] **Step 2: 运行组件测试并确认旧文案失败**

Run:

```bash
pnpm --dir frontend exec vitest run \
  src/features/market-timing/TimingHero.spec.tsx \
  src/features/market-timing/TimingRecentTable.spec.tsx
```

Expected: FAIL，旧组件仍显示“最近确认 / 金未反转 / 候选区域”。

- [ ] **Step 3: 修正主摘要和最近交易日表术语**

`TimingHero.tsx`：

- 指环小标题改为“手指状态”。
- 说明改为三个可换行单元：“金手指延续”、“· 2026-06-12 起”、
  “· 等待银手指反转”。
- 首个确认事件之前显示“尚无手指”。

`TimingRecentTable.tsx`：

- 状态行标题改为“手指状态”。
- `GOLD/SILVER/NEUTRAL` 分别显示“金延续 / 银延续 / 尚无手指”。
- 删除“候选区域”行；被否决候选不在用户表格中渲染。

- [ ] **Step 4: 在 K 线接入固定悬停摘要条**

`TimingChart` props 增加：

```ts
series: TimingDailyState[];
```

组件使用 `useMemo` 构建摘要映射，使用 `useState<string | null>` 保存悬停日期。
默认摘要为最后一根 K 线；十字线离开后恢复默认：

```ts
const handleCrosshairMove = (param: MouseEventParams<Time>) => {
  setHoveredDate(param.time ? formatTimingCrosshairDate(param.time) : null);
};
c.subscribeCrosshairMove(handleCrosshairMove);
```

图表选项增加：

```ts
timeScale: {
  borderColor: palette.axis,
  barSpacing: 6,
  tickMarkFormatter: formatTimingAxisTick,
},
localization: {
  locale: "zh-CN",
  timeFormatter: formatTimingCrosshairDate,
},
```

在图表 canvas 上方渲染固定高度摘要，字段为：

```text
日期 | 开 | 高 | 低 | 收 | 涨跌
手指状态 | 当日新手指
```

日期元素加 `data-testid="timing-hover-date"`，手指状态加
`data-testid="timing-hover-finger"`，用于真实画布悬停验收。颜色仅复用现有
涨跌、金银和 muted 类，不增加卡片、徽章或装饰。

- [ ] **Step 5: 页面把逐日序列传给图表**

`MarketTimingPage.tsx` 改为：

```tsx
<TimingChart
  chart={data?.chart ?? null}
  series={data?.timing_series ?? []}
  loading={isLoading}
/>
```

- [ ] **Step 6: 运行完整前端测试与生产构建**

Run:

```bash
pnpm --dir frontend test
pnpm --dir frontend run build
```

Expected: 全部测试 PASS，TypeScript 与 Vite 构建成功。

- [ ] **Step 7: 提交组件变更**

```bash
git add -- \
  frontend/src/features/market-timing/TimingChart.tsx \
  frontend/src/pages/MarketTimingPage.tsx \
  frontend/src/features/market-timing/TimingHero.tsx \
  frontend/src/features/market-timing/TimingHero.spec.tsx \
  frontend/src/features/market-timing/TimingRecentTable.tsx \
  frontend/src/features/market-timing/TimingRecentTable.spec.tsx
git commit -m "fix(market-timing): distinguish hover zone from confirmed direction"
```

### Task 3: 部署并验证 7 月 2 日真实悬停

**Files:**
- Modify: `memory/07_market_timing/market_timing_design.md`

- [ ] **Step 1: 重建 Web 并检查服务**

Run:

```bash
docker compose up --build -d alphaagent-web
docker compose ps alphaagent-api alphaagent-web alphaagent-gateway
```

Expected: 三个服务均 running/healthy，`http://localhost:8080/market` 返回 200。

- [ ] **Step 2: 用浏览器寻找并悬停 2026-07-02**

在 `1440x1000` 打开 `/market`，在 K 线画布横向移动鼠标，直到
`[data-testid="timing-hover-date"]` 为 `2026-07-02`，然后断言：

```text
timing-hover-finger = 金手指延续
页面不包含中性或候选区域
图表没有在 7 月 2 日新增金手指箭头
```

截图保存到 `.playwright-cli/market-timing-hover-2026-07-02.png` 并目视检查日期、
OHLC、涨跌幅和状态词组无重叠。

- [ ] **Step 3: 验证手机与浏览器状态**

在 `390x844` 重新加载页面，检查：

- 摘要字段可换行且无孤立单字。
- 页面整体 `scrollWidth === innerWidth`。
- 控制台 `0 error / 0 warning`。
- 日期轴和十字线不出现英文月份。

- [ ] **Step 4: 更新持久记忆**

在 `memory/07_market_timing/market_timing_design.md` 当前展示语义中记录：

```markdown
- `active_direction` 在界面固定称为“手指状态”，显示“金手指延续 / 银手指延续”。
  K 线悬停按日期展示 OHLC、涨跌幅和持续金银状态，不展示中性候选诊断。
- 2026-07-02 验证：用户结果为“金手指延续”；它承接 2026-06-12 已确认金手指，
  不代表 7 月 2 日新增一个金手指事件。
```

- [ ] **Step 5: 提交记忆更新并检查边界**

```bash
git add -- memory/07_market_timing/market_timing_design.md
git commit -m "docs(market-timing): clarify hover and confirmed direction"
git diff --check
git status --short
```

Expected: 本任务文件全部提交；用户同时进行的其他需求文件保持原样，未被暂存或提交。
