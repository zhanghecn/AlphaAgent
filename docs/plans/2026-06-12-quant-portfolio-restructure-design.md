# 量化页面 & 持仓体系重构方案

> 日期：2026-06-12
> 状态：已执行
> 范围：PortfolioPage 重构 + QuantTradingPage 瘦身 + 分钟补数向导化

## 一、问题诊断

| # | 问题 | 严重度 | 位置 |
|---|------|--------|------|
| 1 | `QuantTradingPage.tsx` 3027 行巨型单文件，14 state / 13 mutation / 8 query 全堆顶层 | 🔴 | `pages/QuantTradingPage.tsx` |
| 2 | `MinuteDataPanel` 40+ props，CSV/文件/路径/vnpy/TDX/Tushare 六种入口混在一起 | 🔴 | 同上 L2295-2818 |
| 3 | 回测参数、分钟线参数、vnpy 参数、股票池选择散落各处，无统一入口 | 🟠 | `BacktestParamsForm` + `MinuteDataPanel` |
| 4 | `HoldingsPanel` 在 QuantTradingPage 和 PortfolioPage 各有一份，功能重复 | 🟠 | 两个页面各一份 |
| 5 | PortfolioPage 分组管理简陋：扁平列表、无搜索、无批量操作、无视觉区分 | 🟠 | `pages/PortfolioPage.tsx` |
| 6 | 模拟持仓的买卖时机只是纯文本，无图表、无操作按钮、无信号指示 | 🟠 | `HoldingsPanel` / `SimulationHoldingsPanel` |
| 7 | 持仓无 K 线/走势图，看不到成本线和买卖点标记 | 🟡 | 缺失功能 |
| 8 | 量化候选→持仓的联动只有"自动模拟建仓"一个按钮，缺少精细控制 | 🟡 | `autoBuyRecommendations` |

## 二、三阶段路线图

```
阶段 1 — 持仓体系重构（核心，最先执行）
  ├── P1.1  新建 features/portfolio/ 目录结构
  ├── P1.2  PortfolioSummary 资产总览条组件
  ├── P1.3  GroupNav 左侧分组导航组件
  ├── P1.4  HoldingCard 持仓卡片组件（含迷你K线+成本线+买卖标记）
  ├── P1.5  HoldingMiniChart 迷你K线组件（lightweight-charts）
  ├── P1.6  AddToGroupDialog 加入分组对话框
  ├── P1.7  PortfolioPage 主页面重写
  └── P1.8  QuantTradingPage 持仓部分精简为链接跳转

阶段 2 — 量化页面瘦身
  ├── P2.1  新建 features/quant/ 目录结构
  ├── P2.2  拆分 RecommendationsPanel
  ├── P2.3  拆分 BacktestPanel + BacktestParamsForm
  ├── P2.4  拆分 BacktestReport 系列（Summary/TradeTable/Validation/Robustness...）
  ├── P2.5  MinuteDataWizard 分步向导组件
  ├── P2.6  QuantTradingPage 主页面瘦身（~400行编排层）
  └── P2.7  删除旧代码、验证功能不变

阶段 3 — 增强功能
  ├── P3.1  持仓分组拖拽排序
  ├── P3.2  批量加入/移出分组
  ├── P3.3  买卖信号卡片化与通知
  └── P3.4  回测结果→持仓联动（一键加入分组）
```

## 三、阶段 1 详细设计 — 持仓体系重构

### 3.1 目标文件结构

```
frontend/src/
├── pages/
│   ├── QuantTradingPage.tsx       ← P1.8 修改：移除内联 HoldingsPanel
│   └── PortfolioPage.tsx          ← P1.7 重写：新持仓中心
├── features/
│   └── portfolio/                 ← 新建目录
│       ├── index.ts               ← 统一导出
│       ├── PortfolioSummary.tsx   ← P1.2 资产总览条
│       ├── GroupNav.tsx           ← P1.3 左侧分组导航
│       ├── HoldingCard.tsx        ← P1.4 持仓卡片
│       ├── HoldingMiniChart.tsx   ← P1.5 迷你K线
│       ├── SimulationSummary.tsx  ← 底部模拟持仓汇总
│       └── AddToGroupDialog.tsx   ← P1.6 加入分组弹窗
```

### 3.2 P1.2 PortfolioSummary — 资产总览条

**位置**：页面顶部，横向条状布局
**数据源**：`fetchSimulationAccounts` + `fetchHoldings`
**刷新策略**：staleTime 15s，refetchInterval 30s

```
┌─────────────────────────────────────────────────────┐
│ 持仓中心                                              │
│ 分组管理自选、量化候选和模拟持仓。量化负责把结果同步过来。    │
│                                                       │
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐       │
│ │总权益 │ │现金  │ │持仓市值│ │总收益 │ │持仓数 │       │
│ │103.5万│ │23.5万│ │80.1万 │ │+3.53%│ │5只   │       │
│ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘       │
└─────────────────────────────────────────────────────┘
```

**Props 接口**：
```typescript
interface PortfolioSummaryProps {
  cash?: number;
  initialCash?: number;
  positions: SimulationPosition[];
  accountCount: number;
  groupCount: number;
}
```

**计算逻辑**：
- `marketValue = positions.reduce((sum, p) => sum + (p.market_value ?? 0), 0)`
- `equity = cash + marketValue`
- `returnPct = (equity / initialCash - 1) * 100`
- `returnPct` 用 `priceColorClass` 渲染（红涨绿跌）

### 3.3 P1.3 GroupNav — 左侧分组导航

**位置**：页面左侧，固定宽度 280px（xl+屏幕）
**数据源**：`fetchPortfolioGroups`
**功能**：
- 列出所有分组，每项显示：分组名、股票数量、自动/手动标签
- 点击切换右侧内容
- 底部"新建分组"入口
- 区分分组类型（自动维护的量化候选分组用不同颜色/图标）

```
┌──────────────────┐
│ 持仓分组           │
│ ──────────────── │
│ ★ 我的自选    (3) │  ← 手动分组，星标图标
│ ◉ 量化候选   (12) │  ← 自动分组，带 [自动] 标签
│ ○ 低吸观察    (5) │  ← 手动分组
│ ○ 策略A组合   (0) │
│ ──────────────── │
│ + 新建分组        │
└──────────────────┘
```

**Props 接口**：
```typescript
interface GroupNavProps {
  groups: PortfolioGroup[];
  activeId: number | null;
  onSelect: (id: number) => void;
  itemCounts: Record<number, number>;  // groupId → 股票数量
  onCreateGroup: (name: string) => void;
  isCreating: boolean;
}
```

**交互**：
- 选中分组高亮（`bg-muted`）
- 自动分组显示 `[自动]` 小标签（复用现有 `group.auto_managed` 字段）
- 分组数量为 0 时灰色显示
- 新建分组用内联输入框（复用现有 `CreateGroupForm` 的模式）

### 3.4 P1.4 HoldingCard — 持仓卡片

**位置**：右侧主内容区，垂直排列的卡片列表
**数据来源**：分组股票列表（`fetchPortfolioGroupItems`）+ 模拟持仓数据（`fetchHoldings`）+ 股票日线

**卡片结构**：

```
┌────────────────────────────────────────┐
│ 浦发银行 600000.SSE [主板]    +3.44% ↑  │  ← 头部：名称+代码+涨跌
│ ┌──────────────────────────────────┐  │
│ │     [迷你K线 + 成本线 + 买卖标记]   │  │  ← HoldingMiniChart
│ └──────────────────────────────────┘  │
│                                        │
│ 现价 12.93   成本 12.50   盈亏 +430.00  │  ← 核心指标行
│ 持仓 1,000股  市值 12,930              │
│                                        │
│ 买入 06-10 12:30 · MA5低吸策略          │  ← 最近操作
│ 止损 11.85 / 止盈 13.75                │  ← 风控价位
│ 来源: 量化筛选                          │  ← 来源标记
│                                        │
│ [加入分组] [查看详情]                    │  ← 操作按钮
└────────────────────────────────────────┘
```

**两种模式**：
1. **有持仓**：显示完整卡片（迷你K线+指标+操作）
2. **仅观察（分组中但未持仓）**：精简卡片（名称+现价+涨跌+加入模拟/查看详情）

**数据关联逻辑**：
- 通过 `vt_symbol` 将 `PortfolioItem` 与 `SimulationPosition` 关联
- 有匹配的 SimulationPosition → 显示完整持仓卡片
- 无匹配 → 显示观察卡片（仅基本信息）

**Props 接口**：
```typescript
interface HoldingCardProps {
  item: PortfolioItem;                         // 分组中的股票条目
  position?: SimulationPosition | null;        // 对应的模拟持仓（可能没有）
  dailyBars?: DailyBar[];                      // 最近30日日线（迷你K线用）
  buySignals?: SignalMarker[];                 // 买入标记
  sellSignals?: SignalMarker[];                // 卖出标记
  onAddToGroup?: (vtSymbol: string) => void;
  onViewDetail?: (vtSymbol: string) => void;
}

interface SignalMarker {
  time: string;      // ISO date
  price: number;
  type: 'buy' | 'sell';
  reason?: string;
}
```

### 3.5 P1.5 HoldingMiniChart — 迷你K线

**位置**：HoldingCard 内嵌
**技术**：使用已有的 `lightweight-charts` 库（项目已安装 v4.2.1）
**参考**：`features/stocks/StockKlineChart.tsx` 中已有的 lightweight-charts 用法

**渲染内容**：
- 最近 30 个交易日的日K线（OHLC 蜡烛图）
- 成本价水平线（虚线，灰色 `--cost-price`）
- 买入标记（绿色三角形 ▲ 在 K 线下方）
- 卖出标记（红色三角形 ▼ 在 K 线上方）
- 止损线（红色虚线）
- 止盈线（绿色虚线）

**尺寸**：卡片内宽度 100%，高度固定 120px
**交互**：hover 显示十字线和价格，点击跳转 StockDetailPage

**实现要点**：
- 使用 `lightweight-charts` 的 `createChart` API
- K 线数据通过 `candlestickSeries.setData()` 设置
- 成本线通过 `priceLineSeries` 或自定义 `IPriceLineSource`
- 买卖标记通过 `setMarkers()` API
- 组件卸载时调用 `chart.remove()` 清理

**Props 接口**：
```typescript
interface HoldingMiniChartProps {
  bars: Array<{
    time: string;   // YYYY-MM-DD
    open: number;
    high: number;
    low: number;
    close: number;
    volume?: number;
  }>;
  costPrice?: number;
  stopLossPrice?: number;
  takeProfitPrice?: number;
  buySignals?: SignalMarker[];
  sellSignals?: SignalMarker[];
  height?: number;  // 默认 120
  onClick?: () => void;
}
```

**数据获取**：
- 持仓卡片的日线数据需要在卡片列表层统一获取
- 使用 `useQueries` 批量请求当前分组内所有股票的 30 日日线
- API: `GET /stocks/{vt_symbol}/daily-bars?limit=30`（如不存在则需新增）
- 买卖信号从 `SimulationPosition` 的 `last_buy_time`/`last_sell_time` 字段提取

### 3.6 P1.6 AddToGroupDialog — 加入分组对话框

**触发方式**：
- HoldingCard 上的"加入分组"按钮
- 搜索框输入股票代码后的快捷操作
- 量化推荐列表中的"加入分组"按钮

**功能**：
- 弹出对话框列出所有可选分组
- 输入股票代码（默认已填好）
- 填写加入原因
- 选择目标分组
- 确认后调用 `addPortfolioGroupItem` API

**Props 接口**：
```typescript
interface AddToGroupDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultSymbol?: string;
  groups: PortfolioGroup[];
  onAdd: (groupId: number, symbol: string, reason: string) => void;
  isAdding: boolean;
}
```

### 3.7 P1.7 PortfolioPage 主页面重写

**页面结构**：

```typescript
// PortfolioPage.tsx — 预计 ~200 行
export function PortfolioPage() {
  // 1. 所有 query hooks（groups, items, holdings, accounts）
  // 2. 所有 mutation hooks（createGroup, addItem, autoBuy）
  // 3. 数据关联计算（activeGroup, positionsBySymbol）
  // 4. 渲染三区域布局

  return (
    <div className="space-y-5">
      {/* 顶部：页面标题 + 操作按钮 */}
      <PageHeader />

      {/* 资产总览条 */}
      <PortfolioSummary ... />

      {/* 主体：左侧分组 + 右侧卡片 */}
      <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
        <GroupNav ... />
        <GroupContentPanel ... />
      </div>
    </div>
  );
}
```

**GroupContentPanel 内部**：
```typescript
function GroupContentPanel({ group, items, positions, ... }) {
  // 顶部：分组标题 + 搜索 + 加入分组 + 刷新
  // 内容：
  //   items.length === 0 → EmptyState
  //   items.length > 0 → 卡片列表
  //     每张卡片 = HoldingCard，关联 position 数据
  return (
    <section className="space-y-3">
      <GroupContentHeader ... />
      {items.length === 0 ? (
        <EmptyState ... />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {items.map(item => (
            <HoldingCard
              key={item.vt_symbol}
              item={item}
              position={positionsBySymbol[item.vt_symbol]}
              dailyBars={barsBySymbol[item.vt_symbol]}
              ...
            />
          ))}
        </div>
      )}
    </section>
  );
}
```

**数据流设计**：
```
PortfolioPage
  ├── useQuery("portfolioGroups")       → GroupNav + GroupContentPanel
  ├── useQuery("portfolioGroupItems")   → GroupContentPanel 的卡片列表
  ├── useQuery("portfolioHoldings")     → 与 PortfolioItem 关联
  ├── useQuery("simulationAccounts")    → PortfolioSummary
  ├── useQueries("dailyBars")           → 每只股票的30日日线 → HoldingMiniChart
  ├── useMutation("createGroup")        → GroupNav 的创建分组
  ├── useMutation("addItem")            → AddToGroupDialog
  └── useMutation("autoBuy")            → PageHeader 的量化模拟建仓
```

**`useQueries` 批量获取日线**：
```typescript
const dailyBarsQueries = useQueries({
  queries: items.map(item => ({
    queryKey: ["stockDailyBars", item.vt_symbol, 30],
    queryFn: () => fetchStockDailyBars(item.vt_symbol, 30),
    staleTime: 60_000,
    enabled: Boolean(activeGroup),
  })),
});
// 转为 Map<vt_symbol, DailyBar[]> 方便卡片查找
```

### 3.8 P1.8 QuantTradingPage 持仓部分精简

**改动范围**：
- 删除 `HoldingsPanel` 组件（L2181-2293）
- 在"候选"Tab 右侧面板替换为：

```typescript
// 替换原来的 HoldingsPanel
<section className="space-y-4">
  {/* 量化候选分组的快速预览 */}
  <QuantGroupPreview
    itemCount={quantGroupItemsQuery.data?.items.length ?? 0}
    holdingsCount={holdingsQuery.data?.items.length ?? 0}
    equity={equity}
    cash={accountsQuery.data?.items[0]?.cash}
    initialCash={accountsQuery.data?.items[0]?.initial_cash}
  />
</section>
```

**QuantGroupPreview 组件**（内联在 QuantTradingPage 或独立小组件）：
```
┌────────────────────────────────┐
│ 量化候选  12只                  │
│ ──────────────────────────    │
│ 模拟持仓 5只 · 现金 23.5万      │
│ 权益 103.5万 · 收益 +3.53%     │
│                                │
│ [打开持仓中心 →]  [自动模拟建仓]  │
└────────────────────────────────┘
```

**移除的 state/mutation**：
- `holdingsQuery` 的详细数据不再需要（只需要 count 做预览）
- `autoBuyMutation` 移到 PortfolioPage（QuantTradingPage 可保留引用用于顶栏按钮）

## 四、阶段 2 详细设计 — 量化页面瘦身

### 4.1 目标文件结构

```
frontend/src/
├── pages/
│   └── QuantTradingPage.tsx       ← 瘦身为 ~400 行编排层
├── features/
│   └── quant/                     ← 新建目录
│       ├── index.ts
│       ├── RecommendationsPanel.tsx  ← P2.2
│       ├── QuantWorkflowGuide.tsx
│       ├── QuantBoardSelector.tsx
│       ├── BacktestPanel.tsx         ← P2.3
│       ├── BacktestParamsForm.tsx
│       ├── BacktestReport.tsx        ← P2.4（聚合组件）
│       ├── BacktestSummary.tsx
│       ├── BacktestTradeTable.tsx
│       ├── BacktestValidation.tsx
│       ├── BacktestRobustness.tsx
│       ├── BacktestLogWorkspace.tsx
│       ├── MinuteDataWizard.tsx      ← P2.5
│       └── VnpyStatusPanel.tsx
```

### 4.2 拆分策略

**原则**：
- 每个组件文件 ≤ 300 行
- 组件通过 props 接收数据，不自己管理全局 query
- query/mutation 统一在 `QuantTradingPage` 编排层管理，通过 props 下发
- 共享的 helper 函数（`formatMetric`, `backtestTrustVerdict`, `compareVersions` 等）移到 `lib/backtest-utils.ts`

**组件拆分对应表**：

| 原始函数（QuantTradingPage 内部） | 目标文件 |
|---|---|
| `RecommendationsPanel` + `QuantEmptyState` | `features/quant/RecommendationsPanel.tsx` |
| `QuantWorkflowGuide` + `WorkflowStatus` | `features/quant/QuantWorkflowGuide.tsx` |
| `QuantBoardSelector` | `features/quant/QuantBoardSelector.tsx` |
| `BacktestPanel` | `features/quant/BacktestPanel.tsx` |
| `BacktestParamsForm` | `features/quant/BacktestParamsForm.tsx` |
| `BacktestSummary` + `BacktestTrustPanel` + `BacktestMethodPanel` | `features/quant/BacktestSummary.tsx` |
| `BacktestTradeTable` | `features/quant/BacktestTradeTable.tsx` |
| `BacktestValidationGridPanel` + `BacktestWalkForwardPanel` | `features/quant/BacktestValidation.tsx` |
| `BacktestRobustnessPanel` + `BacktestYearlyTable` + `BacktestBenchmarkTable` + `BacktestPeriodTable` + `BacktestRegimeTable` + `BacktestMonthlyTable` + `BacktestSymbolTable` + `BacktestWorstTrades` + `BacktestRealityStats` + `BacktestExecutionQualityPanel` + `BacktestOrderStatsPanel` | `features/quant/BacktestReport.tsx` |
| `BacktestLogWorkspace` + `BacktestAuditPanel` | `features/quant/BacktestLogWorkspace.tsx` |
| `MinuteDataPanel` + `MinuteStep` | `features/quant/MinuteDataWizard.tsx` |
| `VnpyStatusPanel` + `BacktestDataQuality` | `features/quant/VnpyStatusPanel.tsx` |
| `ActionStatus` | 内联保留（~15行） |
| `InfoCell` + `numberValue` + `formatNumber` + ... | `lib/backtest-utils.ts` |

### 4.3 P2.5 MinuteDataWizard — 分步向导

**核心改动**：将当前 40+ props 的 `MinuteDataPanel` 重构为 4 步向导。

```
┌──────────────────────────────────────────────────┐
│ 严格分钟补数                                       │
│ ━━━━━━━━━━  ──────────  ────────  ────────       │
│ ① 审计缺口   ② 选数据源   ③ 执行导入   ④ 验证结果   │
│                                                    │
│ [当前步骤内容]                                      │
│                                                    │
│ [← 上一步]                     [下一步 →]          │
└──────────────────────────────────────────────────┘
```

**向导状态管理**：

```typescript
type WizardStep = 'audit' | 'source' | 'import' | 'verify';

interface MinuteWizardState {
  step: WizardStep;
  // Step 1: 审计缺口
  gapSource: 'csv' | 'file' | '';
  gapCsv: string;
  gapFilePath: string;
  auditResult: MinuteGapAuditResult | null;
  // Step 2: 选数据源
  selectedSource: 'tdx' | 'tushare' | 'vnpy' | 'csv_import' | '';
  // Step 3: 执行导入
  importResult: ImportResult | null;
  // Step 4: 验证
  verifyResult: MinuteGapAuditResult | null;
}
```

**各步骤内容**：

**Step 1 — 审计缺口**：
- 选择输入方式：粘贴 CSV / 上传文件 / 服务器路径（三选一，Radio 切换）
- 点击"审计缺口"
- 显示结果：缺口数量、覆盖率、涉及股票/日期

**Step 2 — 选择数据源**：
- 4 个数据源卡片，点击选择：
  - 📡 **通达信 TDX**（公开源，免费，推荐）
  - 📊 **Tushare Pro**（需 API Token）
  - 🔌 **vn.py 数据库**（需本地 vn.py 环境）
  - 📄 **外部 CSV**（手动导入）
- 每个卡片显示：适用场景、前置条件、速度估计

**Step 3 — 执行导入**：
- 根据选择的数据源显示对应配置：
  - TDX：直接显示"预检查"和"导入"按钮（无需额外配置）
  - Tushare：同上
  - vn.py：显示股票代码/日期范围输入
  - CSV：显示粘贴区/上传/服务器路径
- 显示进度和结果

**Step 4 — 验证结果**：
- 自动重新审计
- 显示前后对比：覆盖率从 X% → Y%
- 显示"审计并运行严格回测"按钮

**Props 简化**：向导内部管理自己的步骤状态，只暴露必要的回调：

```typescript
interface MinuteDataWizardProps {
  backtestParams: {
    tail_entry_start: string;
    tail_entry_end: string;
    tail_entry_ma5_tolerance_pct: number;
    included_boards: string[];
  };
  // 回调：向导完成后的通知
  onImportComplete?: () => void;
  onPipelineComplete?: (result: StrictPipelineResult) => void;
  // 触发外部刷新
  invalidateQueries?: () => void;
}
```

向导内部自行管理所有 mutation hooks（audit, template, vendorManifest, import, vnpyImport, tdxImport, tushareImport, strictPipeline），不再由父组件传入 40+ 个 props。

### 4.4 BacktestParamsForm 优化

**分层折叠设计**：

```
┌────────────────────────────────────────────┐
│ 回测参数                                     │
│                                              │
│ [基础设置] — 默认展开                         │
│ 股票池: [主板] [创业板] [科创板] [北交所]       │
│ 开始日期: [2025-10-14]  初始资金: [1,000,000] │
│ 样本股票: [120]  最大持仓: [8]  最低分: [68]   │
│ [✓] 严格入场                                │
│                                              │
│ [▶ 高级设置] — 默认收起                       │
│   [✓] 尾盘分钟入场  [✓] 强制分钟成交           │
│   尾盘窗口: 14:30 ~ 14:57                    │
│   MA5 允许偏离: 1.5%                         │
│                                              │
│ [运行回测]  [严格分钟预设]                     │
└────────────────────────────────────────────┘
```

保持现有功能不变，只做视觉上的分层整理。把 `details` 标签改为更明显的折叠面板。

### 4.5 QuantTradingPage 编排层（瘦身后）

```typescript
// 目标：~400 行
export function QuantTradingPage() {
  // 1. 所有 query hooks（~8 个）
  // 2. 所有 mutation hooks（~5 个：screen, backtest, autoBuy, strictPipeline）
  // 3. 分钟补数向导的 mutation 全部移入 MinuteDataWizard 内部管理
  // 4. 派生状态计算

  return (
    <div className="space-y-5">
      <PageHeader actions={...} />

      <QuantWorkflowGuide ... />

      <Tabs defaultValue="candidates">
        <TabsList>
          <TabsTrigger value="candidates">候选</TabsTrigger>
          <TabsTrigger value="backtest">回测</TabsTrigger>
          <TabsTrigger value="logs">日志</TabsTrigger>
          <TabsTrigger value="data">数据</TabsTrigger>
        </TabsList>

        <TabsContent value="candidates">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <RecommendationsPanel ... />
            <QuantGroupPreview ... />   ← 替代原来的 HoldingsPanel
          </div>
        </TabsContent>

        <TabsContent value="backtest">
          <BacktestPanel ... />
        </TabsContent>

        <TabsContent value="logs">
          <BacktestLogWorkspace ... />
        </TabsContent>

        <TabsContent value="data">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <MinuteDataWizard ... />   ← 新向导组件
            <aside className="space-y-4">
              <VnpyStatusPanel ... />
              <BacktestDataQuality ... />
            </aside>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

**减少的 mutation（移入 MinuteDataWizard 内部）**：
- `minuteGapAuditMutation`
- `minuteGapTemplateMutation`
- `minuteVendorManifestMutation`
- `minuteVendorManifestCsvMutation`
- `minuteImportMutation`
- `vnpyMinuteImportMutation`
- `vnpyGapImportMutation`
- `tushareGapImportMutation`
- `tdxGapImportMutation`

QuantTradingPage 顶层只保留：
- `screenMutation`
- `backtestMutation`
- `autoBuyMutation`
- `strictPipelineMutation`（或移入向导）

## 五、需要新增/修改的后端 API

### 5.1 批量获取股票日线（新增）

**端点**：`GET /stocks/batch-daily-bars`

**请求参数**：
```json
{
  "symbols": ["600000.SSE", "600519.SSE"],
  "limit": 30
}
```

**响应**：
```json
{
  "status": "ok",
  "data": {
    "600000.SSE": [
      { "trade_date": "2026-06-01", "open": 12.50, "high": 12.80, "low": 12.40, "close": 12.75, "volume": 12345678 }
    ]
  }
}
```

**目的**：前端用 `useQueries` 并行获取时，如果每只股票单独请求，20 只股票 = 20 个并发请求。
批量接口减少为 1 个请求，减轻网络压力。

**备选方案**：如果暂时不加批量接口，前端用 `useQueries` 并行请求单只股票日线也可工作，
只是并发请求数较多。此时使用 `GET /stocks/{vt_symbol}/daily-bars?limit=30`。

### 5.2 分组股票数量（可复用现有）

现有的 `fetchPortfolioGroups` 响应可以扩展包含 `item_count` 字段，
避免前端为每个分组额外调用 `fetchPortfolioGroupItems`。

**非必须**，可在阶段 3 优化。

## 六、缺失/冗余功能分析

### 6.1 缺失功能（需新增）

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 持仓卡片内迷你 K 线图 | P1 | HoldingMiniChart 组件 |
| K 线上的买入/卖出标记 | P1 | lightweight-charts markers API |
| K 线上的成本线 | P1 | lightweight-charts priceLine API |
| 持仓卡片双列网格布局 | P1 | `grid-cols-2` |
| 分钟补数分步向导 | P2 | MinuteDataWizard 组件 |
| 批量日线 API | P2 | 减少并发请求数 |
| 持仓分组拖拽排序 | P3 | 需要 react-dnd 或类似库 |
| 买卖信号卡片化通知 | P3 | 信号强度可视化 |
| 回测结果→持仓联动 | P3 | 一键将回测标的加入分组 |

### 6.2 冗余功能（需清理）

| 功能 | 说明 | 处理方式 |
|------|------|---------|
| QuantTradingPage 内的 `HoldingsPanel` | 与 PortfolioPage 功能重复 | 替换为精简预览 + 跳转链接 |
| `MinuteDataPanel` 的 40+ props | 暴露了过多内部实现 | 重构为向导组件，内部管理状态 |
| 重复的 `InfoCell` 组件 | QuantTradingPage 和 PortfolioPage 各定义一份 | 抽取到 `components/InfoCell.tsx` |
| 重复的 `formatTime` 函数 | 两个页面各定义一份 | 已有 `lib/utils.ts`，统一放入 |
| `BacktestParamsForm` 内嵌 `QuantBoardSelector` | 股票池选择器出现两次 | 共享同一个组件实例 |

### 6.3 现有功能保持不变

以下功能重构时保持逻辑不变，只做代码组织优化：
- 量化筛选流程（`createScreenRun`）
- 回测执行流程（`createBacktest`）
- 回测报告展示（Summary/Trades/Validation/Robustness 全系列）
- 模拟账户管理（`fetchSimulationAccounts`）
- 自动模拟建仓（`autoBuyRecommendations`）
- 持仓分组 CRUD（`createPortfolioGroup` / `addPortfolioGroupItem`）
- 数据管理页面（`DataManagementPage`）不变

## 七、执行计划 — 工作量估算

### 阶段 1：持仓体系重构

| 步骤 | 任务 | 涉及文件 | 预估行数 |
|------|------|---------|---------|
| P1.1 | 创建 `features/portfolio/` 目录 + `index.ts` | 新建 | 20 |
| P1.2 | `PortfolioSummary` 组件（复用现有逻辑，重组布局） | 新建 ~80行 | 80 |
| P1.3 | `GroupNav` 组件（复用现有 `GroupList` + `CreateGroupForm`） | 新建 ~120行 | 120 |
| P1.4 | `HoldingCard` 组件（新设计） | 新建 ~150行 | 150 |
| P1.5 | `HoldingMiniChart` 组件（新开发，基于 lightweight-charts） | 新建 ~200行 | 200 |
| P1.6 | `AddToGroupDialog` 组件 | 新建 ~80行 | 80 |
| P1.7 | `PortfolioPage` 重写 | 重写 ~200行 | 200 |
| P1.8 | `QuantTradingPage` 持仓部分精简 | 修改 ~50行删除 + ~30行新增 | -20 |
| P1.9 | 抽取共享组件 `InfoCell` + helper 函数 | 新建 `lib/backtest-utils.ts` | 60 |
| | **阶段 1 小计** | | **~890 行新增，~50 行删除** |

### 阶段 2：量化页面瘦身

| 步骤 | 任务 | 涉及文件 | 预估行数 |
|------|------|---------|---------|
| P2.1 | 创建 `features/quant/` 目录 + `index.ts` | 新建 | 30 |
| P2.2 | 拆分 `RecommendationsPanel` + `QuantEmptyState` + `QuantBoardSelector` | 新建 ~250行 | 250 |
| P2.3 | 拆分 `BacktestPanel` + `BacktestParamsForm` | 新建 ~300行 | 300 |
| P2.4 | 拆分 `BacktestReport` 全系列（10+ 子组件） | 新建 ~800行 | 800 |
| P2.5 | `MinuteDataWizard` 分步向导 | 新建 ~400行 | 400 |
| P2.6 | `QuantTradingPage` 瘦身为编排层 | 重写 ~400行 | 400 |
| P2.7 | 删除旧代码、验证功能 | 删除 | -2600 |
| | **阶段 2 小计** | | **~2180 行新增，~2600 行删除** |

### 阶段 3：增强功能（可选，不在此方案执行范围内）

| 步骤 | 任务 | 依赖 |
|------|------|------|
| P3.1 | 持仓分组拖拽排序 | 需引入 `@dnd-kit/core` |
| P3.2 | 批量加入/移出分组 | 后端批量 API |
| P3.3 | 买卖信号卡片化与通知 | P1.4 + P1.5 完成 |
| P3.4 | 回测结果→持仓联动 | P1.6 + P2.3 完成 |

## 八、技术要点与风险

### 8.1 lightweight-charts 注意事项

- 项目已安装 `lightweight-charts@4.2.1`，可直接使用
- 参考 `features/stocks/StockKlineChart.tsx` 中的已有实现
- `setMarkers()` API 格式：
  ```typescript
  series.setMarkers([
    { time: '2026-06-10', position: 'belowBar', color: '#22c55e', shape: 'arrowUp', text: '买入' },
    { time: '2026-06-12', position: 'aboveBar', color: '#ef4444', shape: 'arrowDown', text: '卖出' },
  ]);
  ```
- 成本线使用 `series.createPriceLine({ price: 12.50, color: '#9ca3af', lineStyle: 2 })` （虚线）
- 迷你图高度 120px，禁用大部分 UI（legend, crosshair 可保留轻量版）
- **内存管理**：组件卸载时必须 `chart.remove()`，使用 `useEffect` cleanup

### 8.2 数据获取策略

- 持仓页面的日线数据：`useQueries` 并行获取每只股票 30 日日线
- 如果股票数量 > 20，考虑分批获取或使用批量 API（5.1 节）
- `staleTime: 60_000`（1 分钟内复用缓存），不设 `refetchInterval`（手动刷新即可）
- 模拟持仓的实时刷新：`refetchInterval: 30_000`（保持现有策略）

### 8.3 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| lightweight-charts 在小尺寸下渲染异常 | 卡片图表显示错误 | 设置最小高度、测试 120px 渲染效果 |
| 日线 API 批量请求过多 | 页面加载慢 | 优先使用批量 API，备选串行获取 |
| 组件拆分引入 props drilling | 维护成本 | 使用组合模式，避免过深传递 |
| 分钟补数向导重构可能影响现有功能 | 回测流程中断 | 分步重构，每步验证功能不变 |

## 九、验证清单

### 阶段 1 完成标准

- [ ] PortfolioPage 显示分组导航 + 卡片视图
- [ ] 点击分组切换右侧卡片列表
- [ ] 持仓卡片显示迷你 K 线 + 成本线 + 买卖标记
- [ ] 新建分组、加入股票功能正常
- [ ] 量化候选分组自动同步正常
- [ ] 模拟建仓功能正常
- [ ] QuantTradingPage 候选 Tab 旁的持仓预览正常
- [ ] 从量化页面跳转到持仓页面正常
- [ ] 现有测试通过：`pytest tests/alphaagent/`

### 阶段 2 完成标准

- [ ] QuantTradingPage ≤ 400 行
- [ ] 所有 features/quant/ 组件文件 ≤ 300 行
- [ ] 分钟补数分步向导可用：审计→选源→导入→验证
- [ ] 量化筛选、回测、报告功能不变
- [ ] 现有测试通过
