# AlphaAgent Research Frontend Development Brief

> This document is the **sole contract** for Claude Code to implement the research frontend.
> Do NOT modify any backend files or the `vnpy/` package.

## 1. Overview

Upgrade the existing frontend from a "data viewer" to an **investment research workbench** with two product surfaces:

1. **Sector Mainline Dashboard** (`/sectors`) — discover market mainlines, sector heat, leaders, and relations
2. **Stock Research Workbench** (`/stocks/:vtSymbol`) — comprehensive stock analysis with financials, sectors, chain, and events

## 2. New Dependencies

```bash
npm install @xyflow/react recharts
# Already available: lightweight-charts, shadcn/ui, tailwindcss, lucide-react
```

## 3. API Endpoints

All endpoints are on the existing API base (`http://localhost:8000/api`).

### 3.1 Sector Research API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/research/sectors/dashboard` | GET | Main dashboard with period scores |
| `/research/sectors/{sector_id}/overview` | GET | Sector detail overview |
| `/research/sectors/{sector_id}/relation-graph` | GET | Sector relation graph |
| `/research/industry-chain/graph` | GET | Dynamic industry chain graph |

#### Dashboard Query Parameters

```
period: "1d" | "3d" | "5d" | "10d" | "20d" | "60d" | "120d" | "250d" (default: "20d")
sector_type: "industry" | "concept" | "theme" | "region" | null
sort_by: "heat_score" | "return_pct" | "momentum_score" | "fund_score" | ... (default: "heat_score")
sort_order: "asc" | "desc" (default: "desc")
page: number (default: 1)
page_size: number (default: 30)
q: string (search query)
```

#### Dashboard Response Shape

```typescript
interface SectorDashboardData {
  items: SectorPeriodScore[];
  total: number;
  page: number;
  page_size: number;
  period: string;
  sort_by: string;
  sort_order: string;
  status: "ready" | "empty";
}

interface SectorPeriodScore {
  sector_id: string;
  sector_name?: string;          // joined from sectors table
  sector_type?: string;
  stock_count?: number;
  as_of_date: string;            // ISO date
  period: string;                // "1d", "5d", "20d", etc.
  return_pct: number | null;
  rank_return: number | null;
  momentum_score: number;        // 0-100
  breadth_score: number;         // 0-100
  fund_score: number;            // 0-100
  sentiment_score: number;       // 0-100
  leader_score: number;          // 0-100
  continuity_score: number;      // 0-100
  liquidity_score: number;       // 0-100
  risk_penalty: number;          // 0-30
  heat_score: number;            // composite 0-100
  trend_state: "MAINLINE_UP" | "FAST_UP" | "ROTATION" | "FADING" | "WEAK" | "UNKNOWN";
  confidence: number;            // 0-1
  evidence?: Record<string, unknown>;
}
```

#### Sector Overview Response

```typescript
interface SectorOverviewData {
  sector_id: string;
  status: "ready" | "empty";
  info: {                       // from sectors table
    id: string;
    name: string;
    type: string;
    stock_count: number | null;
    change_pct: number | null;
    leader_stock: string | null;
    // ... other sector fields
  };
  daily_metrics: {              // latest sector_daily_metrics row
    trade_date: string;
    stock_count: number;
    rise_count: number;
    fall_count: number;
    avg_change_pct: number;
    turnover: number | null;
    leader_vt_symbol: string | null;
    leader_change_pct: number | null;
  } | null;
  period_scores: SectorPeriodScore[];   // all periods
  top_members: SectorMember[];          // top 20 by change_pct
  recent_bars: Bar[];                   // last 60 sector bars
  fund_flows: SectorFundFlow[];         // recent fund flows
}

interface SectorMember {
  vt_symbol: string;
  symbol: string;
  exchange: string;
  name: string;
  change_pct: number | null;
  return_5d: number | null;
  turnover: number | null;
  market_cap: number | null;
}

interface SectorFundFlow {
  sector_id: string;
  trade_date: string;
  period: string;
  main_net_inflow: number | null;
  main_net_inflow_ratio: number | null;
}
```

#### Relation Graph Response

```typescript
interface SectorRelationGraphData {
  sector_id: string;
  nodes: { id: string; name: string; type: string; stock_count: number | null; change_pct: number | null }[];
  edges: {
    source: string;
    target: string;
    score: number;
    shared_stock_count: number;
    jaccard: number;
    price_correlation: number | null;
    fund_correlation: number | null;
    evidence: Record<string, unknown>;
    confidence: number;
  }[];
  period: string;
  status: "ready" | "no_edges";
}
```

### 3.2 Stock Research API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/research/stocks/{vt_symbol}/workbench` | GET | Complete workbench (all sections) |
| `/research/stocks/{vt_symbol}/finance/quarterly` | GET | Quarterly financial history |
| `/research/stocks/{vt_symbol}/finance/statements` | GET | Balance sheet / profit / cash flow |
| `/research/stocks/{vt_symbol}/business` | GET | Business segment history |
| `/research/stocks/{vt_symbol}/events` | GET | Events timeline |

#### Workbench Response Shape

```typescript
interface StockWorkbenchData {
  vt_symbol: string;
  symbol: string;
  exchange: string;
  as_of: string;               // ISO timestamp

  profile: {
    name: string | null;
    industry: string | null;
    last_price: number | null;
    change_pct: number | null;
    market_cap: number | null;
    pe: number | null;
    pb: number | null;
    turnover_rate: number | null;
    source: string;
  };

  technical: {
    bars: Bar[];
    bar_count: number;
    indicators: TechnicalIndicatorRow[];
    source: string;
  };

  financial: {
    quarterly: FinancialReportRow[];
    indicators: FinancialIndicatorRow[];
    statements: {
      balance_sheet: { items: unknown[]; source: string };
      profit_sheet: { items: unknown[]; source: string };
      cash_flow: { items: unknown[]; source: string };
    };
    source: string;
  };

  business: {
    items: BusinessSegmentRow[];
    by_report_date: Record<string, BusinessSegmentRow[]>;
    report_periods: string[];
    source: string;
  };

  sectors: {
    memberships: {
      sector_id: string;
      sector_name: string;
      sector_type: string;
      rank: number | null;
      confirmed: boolean | null;
    }[];
    sector_scores: SectorPeriodScore[];
    source: string;
  };

  chain: {
    nodes: ChainNode[];
    edges: ChainEdge[];
    source: string;
  };

  events: {
    timeline: EventRow[];
    hot_rank: { rank: number | null; keywords: string[] };
    fund_flows: unknown[];
    lhb: unknown[];
    source: string;
  };

  data_quality: {
    sections: Record<string, boolean>;
    available: number;
    total: number;
    completeness: number;
    missing_data_suggestions: string[];
  };
}

interface FinancialReportRow {
  vt_symbol?: string;
  report_date: string;
  period_type: string;
  revenue: number | null;
  revenue_yoy: number | null;
  net_profit: number | null;
  net_profit_yoy: number | null;
  gross_margin: number | null;
  net_margin: number | null;
  roe: number | null;
  debt_asset_ratio: number | null;
  source?: string;
  raw?: Record<string, unknown>;
}

interface BusinessSegmentRow {
  id?: number;
  vt_symbol?: string;
  segment_name: string;
  segment_type: string | null;
  report_date: string | null;
  revenue: number | null;
  revenue_ratio: number | null;
  gross_margin: number | null;
}

interface EventRow {
  id?: number;
  vt_symbol?: string;
  event_date: string;
  event_type: string;
  title: string | null;
  summary: string | null;
  url: string | null;
  keywords: string[] | null;
  sentiment: string | null;
}

interface ChainNode {
  id: string;
  name: string;
  node_type: "sector" | "segment" | "stock";
  stage: "upstream" | "midstream" | "downstream" | "service" | "application" | "unknown";
  sector_id: string | null;
  vt_symbol: string | null;
  keywords: string[];
  confidence: number;
}

interface ChainEdge {
  source: string;
  target: string;
  relation_type: string;
  score: number;
  evidence: Record<string, unknown>;
  confidence: number;
}
```

#### Industry Chain Graph Response

```typescript
interface IndustryChainGraphData {
  nodes: ChainNode[];
  edges: ChainEdge[];
  node_count: number;
  edge_count: number;
  status: "ready" | "empty";
}
```

### 3.3 Important: Response Wrapper

**NOTE:** The backend research API endpoints return **plain JSON** (not wrapped in `{ success, data }`). The existing `apiClient` in `frontend/src/api/client.ts` expects the wrapped format. For the new research endpoints, use **direct fetch** or create a new `researchClient`:

```typescript
// frontend/src/api/researchClient.ts
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api";

export async function researchGet<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(`${BASE_URL}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) url.searchParams.set(k, v);
    });
  }
  const res = await fetch(url.toString(), {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`Research API error: ${res.status}`);
  return res.json();
}
```

## 4. Pages to Create/Modify

### 4.1 `SectorsPage.tsx` — Rewrite as Mainline Dashboard

**Replace** the existing search-focused page with a mainline dashboard:

- **Top toolbar**: Period selector (1d/3d/5d/10d/20d/60d/120d/250d), sector type filter, sort dropdown, search input
- **Main content**: Sortable table showing heat_score, sector_name, return_pct, trend_state, momentum, fund, sentiment, leader
- **Sidebar/panel**: Click a sector row to show relation graph (`@xyflow/react`)
- **Default state**: Show dashboard immediately with period=20d, no "search first" empty state

### 4.2 `SectorDetailPage.tsx` — New Page

Route: `/sectors/:sectorId`

- **Header**: Sector name, type, change_pct, member count
- **Scores card**: Period scores across all periods with trend badges
- **K-line chart**: Sector daily bars using `lightweight-charts`
- **Members table**: Top 20 members sorted by change_pct
- **Fund flow chart**: Bar chart of fund flows using `recharts`
- **Relation graph**: `@xyflow/react` graph showing related sectors

### 4.3 `StockDetailPage.tsx` — Restructure as Research Workbench

**Refactor** the existing page into a tabbed research workbench:

- **Tab 1: Overview** — Quote header, key metrics, sector memberships, data quality
- **Tab 2: Technical** — K-line chart (lightweight-charts) with MA5/MA10/MA20, indicators below
- **Tab 3: Financials** — Quarterly chart (recharts line/bar), statement tables, financial indicators
- **Tab 4: Business** — Revenue segment pie/bar chart by report period, trend comparison
- **Tab 5: Sectors & Chain** — Sector positions panel, industry chain graph (@xyflow/react)
- **Tab 6: Events** — Timeline of notices, LHB records, hot rank, fund flows

## 5. New Files to Create

### API Layer

```
frontend/src/api/researchClient.ts     — Direct fetch client (no wrapper)
frontend/src/api/researchSectors.ts    — Sector research API functions
frontend/src/api/researchStocks.ts     — Stock research API functions
frontend/src/api/researchGraphs.ts     — Graph API functions
```

### Feature Components

```
frontend/src/features/research-sectors/
  SectorPeriodTabs.tsx          — Period selector (1d..250d)
  SectorHotTable.tsx            — Main sortable heat score table
  SectorTrendChart.tsx          — recharts line chart for sector trend
  SectorRelationGraph.tsx       — @xyflow/react sector relation graph
  SectorLeaderPanel.tsx         — Leader stock detail panel
  SectorConstituentTable.tsx    — Member stock table

frontend/src/features/research-stocks/
  StockResearchHeader.tsx       — Quote header with key metrics
  StockFinanceQuarterChart.tsx  — recharts quarterly financial chart
  StockFinanceStatementTable.tsx — Statement data table
  StockBusinessHistoryChart.tsx — recharts business segment history
  StockSectorPositionPanel.tsx  — Sector memberships + scores
  StockChainGraph.tsx           — @xyflow/react industry chain graph
  StockEventTimeline.tsx        — Event list with dates
  StockDataQualityPanel.tsx     — Data completeness + sync suggestions
```

## 6. Display Rules (Must Follow)

1. **No empty search states** — The sector page defaults to the mainline dashboard, never shows "search first"
2. **Sortable columns** — heat_score, return_pct, fund_score, turnover, etc. must be clickable to sort
3. **Full date format** — Charts show `YYYY-MM-DD`, never just month
4. **K-line defaults** — MA5/MA10/MA20 only; other MAs via toggle switch
5. **Indicators below K-line** — MACD, KDJ, RSI in separate sub-chart, never overlaid on candles
6. **Financial default = chart** — Show quarterly trend chart, not just latest numbers
7. **Chain graph evidence** — Every edge must show evidence type and confidence on hover/click
8. **Data quality transparency** — When data missing, show what's missing and which sync job can fix it (from `data_quality.missing_data_suggestions`)
9. **Trend state badges** — Color-coded: MAINLINE_UP=green, FAST_UP=orange, ROTATION=blue, FADING=yellow, WEAK=red, UNKNOWN=gray
10. **Confidence indicators** — Show confidence score as a small progress bar or percentage next to computed values

## 7. Color Scheme for Scores

```css
/* Heat score gradient */
--score-high: #22c55e;     /* green-500: 70-100 */
--score-medium: #eab308;   /* yellow-500: 40-69 */
--score-low: #ef4444;      /* red-500: 0-39 */

/* Trend state colors */
--trend-mainline: #22c55e;  /* MAINLINE_UP */
--trend-fast: #f97316;      /* FAST_UP */
--trend-rotation: #3b82f6;  /* ROTATION */
--trend-fading: #eab308;    /* FADING */
--trend-weak: #ef4444;      /* WEAK */
--trend-unknown: #6b7280;   /* UNKNOWN */
```

## 8. Existing Code to Reuse

- `frontend/src/components/ui/*` — All shadcn/ui components
- `frontend/src/components/LoadingState.tsx` — Loading spinner
- `frontend/src/components/EmptyState.tsx` — Empty data display
- `frontend/src/components/ErrorState.tsx` — Error display
- `frontend/src/components/AppShell.tsx` — Main layout shell
- `frontend/src/features/stocks/StockKlineChart.tsx` — Existing K-line chart (adapt)
- `frontend/src/features/stocks/StockQuoteHeader.tsx` — Quote display (adapt)
- `frontend/src/api/types.ts` — Existing type definitions (extend, don't break)

## 9. Route Configuration

Add to `App.tsx` router:

```tsx
// New routes
<Route path="/sectors/:sectorId" element={<SectorDetailPage />} />
// Modify existing
<Route path="/sectors" element={<SectorsPage />} />  // Already exists, rewrite content
<Route path="/stocks/:vtSymbol" element={<StockDetailPage />} />  // Already exists, restructure
```

## 10. Testing Checklist

- [ ] SectorsPage loads dashboard immediately without user action
- [ ] Period tabs switch data correctly
- [ ] Sort clicking changes table order
- [ ] Clicking a sector row navigates to detail page
- [ ] SectorDetailPage shows K-line, scores, members, relation graph
- [ ] StockDetailPage loads workbench data in single request
- [ ] Financial tab shows quarterly chart with multiple periods
- [ ] Business tab shows segment comparison across report dates
- [ ] Chain graph shows nodes with evidence on hover
- [ ] Data quality panel shows missing data suggestions
- [ ] All pages handle "unavailable" data gracefully (no crash)
