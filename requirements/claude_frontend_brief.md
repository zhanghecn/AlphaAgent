# Claude Code 前端开发上下文：AlphaAgent 真实 A 股数据工作台

> 给 Claude Code：请只实现前端页面，不改 `vnpy/`，不实现后端业务逻辑。后端 API 已由 Codex 提供，前端通过 HTTP 调用 `/api/*`。

## 1. 项目目标

AlphaAgent 是基于 vn.py 的 A 股量化交易和智能投研系统。本阶段只做“真实数据显示和互动浏览”，还不到选股、推荐、模拟交易、回测阶段。

用户要的第一阶段效果：

- 打开 Web 前端就能看到真实 A 股市场数据。
- 能看到上证指数等指数概览。
- 能查看所有 A 股股票列表。
- 点击股票进入详情页，像炒股软件一样看到报价、K 线和基础指标。
- 股票详情页需要预留并展示主营业务、板块、产业链模块；当前后端这些模块部分是 pending，但前端必须有完整 UI 状态。
- 前端必须使用 React + TypeScript + Vite + Tailwind CSS + shadcn/ui。
- 项目启动、测试、验收通过 Docker Compose。

## 2. 架构边界

- `vnpy/` 是官方 vn.py 核心包，不要修改。
- 不修改 vn.py Qt 界面。
- 用户界面全部放在独立前端目录 `frontend/`。
- 后端由 Codex 维护，位于 `alphaagent/`。
- 前端不要调用外部行情接口，不要直接访问数据库，不要 import Python。
- 前端只调用后端 API。

## 3. 当前仓库状态

已有后端文件：

```text
alphaagent/server/main.py
alphaagent/server/api/router.py
alphaagent/server/api/health.py
alphaagent/server/api/market.py
alphaagent/server/api/stocks.py
alphaagent/server/api/indices.py
alphaagent/server/api/sectors.py
alphaagent/server/api/industry_chains.py
alphaagent/server/api/data_status.py
alphaagent/market/providers.py
alphaagent/market/models.py
alphaagent/market/symbols.py
```

当前 Docker Compose：

- `alphaagent-api` 已存在。
- 后端端口：`http://localhost:8000`
- API base URL：`http://localhost:8000/api`
- `alphaagent-web` 还没创建，请你创建 `frontend/` 并补 Compose 前端服务。

当前有一个临时静态页面：

```text
alphaagent/server/web/*
```

不要继续扩展它。正式前端必须在 `frontend/`。

## 4. 前端技术栈

必须使用：

- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui
- TanStack Query
- TanStack Table
- Lightweight Charts

建议工具：

- `lucide-react` 用于图标。
- `zod` 可用于 API 类型校验，但不是强制。

## 5. 前端目录要求

请创建：

```text
frontend/
  Dockerfile
  package.json
  index.html
  vite.config.ts
  tsconfig.json
  tailwind.config.ts
  postcss.config.js
  src/
    main.tsx
    App.tsx
    styles.css
    api/
      client.ts
      types.ts
      market.ts
      stocks.ts
      indices.ts
      sectors.ts
      dataStatus.ts
    pages/
      MarketOverviewPage.tsx
      StocksPage.tsx
      StockDetailPage.tsx
      IndexDetailPage.tsx
      SectorsPage.tsx
      DataStatusPage.tsx
    components/
      AppShell.tsx
      LoadingState.tsx
      ErrorState.tsx
      EmptyState.tsx
    features/
      market/
        IndexStrip.tsx
      stocks/
        StockTable.tsx
        StockQuoteHeader.tsx
        StockKlineChart.tsx
        StockIndicatorPanel.tsx
        StockBusinessPanel.tsx
        StockSectorPanel.tsx
        StockIndustryChainPanel.tsx
      sectors/
        SectorList.tsx
        IndustryChainPanel.tsx
      data-status/
        DataSourceStatusTable.tsx
```

可以按需要调整组件拆分，但页面和功能必须覆盖。

## 6. 页面范围

第一阶段只做这些页面：

### `/`

市场概览页。

展示：

- 上证指数、深证成指、创业板指、科创 50。
- 指数最新价、涨跌幅、成交额。
- 市场状态：后端返回 `RISK_ON` / `RISK_OFF` / `RANGE` / `UNKNOWN`。
- 数据更新时间。
- 数据状态入口。

### `/stocks`

全 A 股票列表。

展示：

- 表格字段：
  - 代码
  - 名称
  - 交易所
  - 最新价
  - 涨跌幅
  - 成交额
  - 换手率
  - 市值
  - PE
  - PB
  - 数据源
- 搜索：代码/名称。
- 排序：
  - 市值
  - 成交额
  - 涨跌幅
  - 换手率
- 分页 UI。
- 点击行进入 `/stocks/:vtSymbol`。

注意：当前后端列表接口已能返回真实行情，但全 A 本地落库还在下一阶段，所以 `total` 可能为 `null`。

### `/stocks/:vtSymbol`

股票详情页。

展示：

- 报价头部：名称、代码、最新价、涨跌幅、市值、成交额、换手率、PE、PB。
- K 线图：日 K，使用 Lightweight Charts。
- 指标面板：
  - 当前后端返回 pending 时显示“等待 K 线落库计算”，不要报错。
- 主营业务：
  - 当前可能 pending，必须展示空状态。
  - 后续字段包括 summary、main_products、revenue_ratio、gross_profit_ratio。
- 板块：
  - 当前可能为空，必须展示空状态。
- 产业链：
  - 当前可能 pending，必须展示上游/中游/下游空状态。
- 数据质量：
  - 使用 `/snapshot` 的 `data_quality.missing` 显示哪些数据缺失。

### `/indices/sh000001`

上证指数页。

展示：

- 上证指数报价。
- 日 K 图。
- 指标 pending 状态。

### `/sectors`

板块页。

当前后端返回 pending/空列表。前端仍要做好：

- 行业/概念/地域/主题 tabs。
- 空状态。
- 后续成员股列表入口。

### `/data`

数据状态页。

展示：

- `/api/ready`
- `/api/data/status`
- 数据源状态。
- database/redis 当前 pending 也要正常显示。

## 7. API 统一响应格式

所有后端 API 返回：

```ts
type ApiResponse<T> = {
  success: boolean
  data: T | null
  error: null | {
    code: string
    message: string
    detail: Record<string, unknown>
  }
  request_id: string
}
```

前端 `api/client.ts` 必须：

- 从 `import.meta.env.VITE_API_BASE_URL` 读取 base URL。
- 默认值可为 `http://localhost:8000/api`。
- 如果 HTTP 非 2xx 或 `success === false`，抛出可展示错误。
- 不在组件里重复写 fetch 细节。

## 8. 当前已实现 API

### 系统

```http
GET /api/health
GET /api/ready
GET /api/data/status
```

`GET /api/ready` 当前返回：

```json
{
  "status": "ready",
  "postgres": "pending",
  "redis": "pending",
  "market_data": [
    {"name": "tencent_realtime", "ok": true, "message": "ok"},
    {"name": "sina_market_center", "ok": true, "message": "ok"},
    {"name": "eastmoney_stock_detail", "ok": true, "message": "ok"},
    {"name": "kline", "ok": true, "message": "ok"}
  ]
}
```

### 市场概览

```http
GET /api/market/overview
```

返回 data 示例：

```json
{
  "trade_date": "2026-06-07",
  "indices": [
    {
      "symbol": "000001",
      "exchange": "SSE",
      "vt_symbol": "000001.SSE",
      "name": "上证指数",
      "last_price": 4027.74,
      "change": -30.04,
      "change_pct": -0.74,
      "turnover": 1363887870000,
      "source": "tencent_realtime"
    }
  ],
  "active_stocks": [],
  "market_state": "RISK_OFF",
  "source": "sina_market_center,tencent_realtime",
  "updated_at": "2026-06-07T07:15:09+00:00"
}
```

### 股票列表

```http
GET /api/stocks?q=&industry=&sector=&market=&page=1&page_size=50&sort=mktcap
```

可用 sort：

- `mktcap`
- `amount`
- `changepercent`
- `turnoverratio`

返回 data：

```ts
type StockListData = {
  items: StockQuote[]
  page: number
  page_size: number
  total: number | null
  source: string
  updated_at?: string
}
```

### 股票详情

```http
GET /api/stocks/{vt_symbol}
GET /api/stocks/{vt_symbol}/bars?interval=1d&limit=120
GET /api/stocks/{vt_symbol}/indicators
GET /api/stocks/{vt_symbol}/business
GET /api/stocks/{vt_symbol}/sectors
GET /api/stocks/{vt_symbol}/industry-chain
GET /api/stocks/{vt_symbol}/snapshot
```

`StockQuote` 字段：

```ts
type StockQuote = {
  symbol: string
  exchange: string
  vt_symbol: string
  name: string
  last_price: number | null
  change: number | null
  change_pct: number | null
  open_price: number | null
  high_price: number | null
  low_price: number | null
  previous_close: number | null
  volume: number | null
  turnover: number | null
  market_cap: number | null
  pe: number | null
  pb: number | null
  turnover_rate: number | null
  industry: string | null
  area: string | null
  trade_time: string | null
  source: string
}
```

K 线字段：

```ts
type Bar = {
  trade_date: string
  open: number
  close: number
  high: number
  low: number
  volume: number
  turnover: number | null
  change_pct: number | null
}
```

### 指数

```http
GET /api/indices
GET /api/indices/sh000001
GET /api/indices/000001.SSE
GET /api/indices/sh000001/bars?limit=120
GET /api/indices/sh000001/indicators
```

### 板块

```http
GET /api/sectors?type=industry
GET /api/sectors/{sector_id}
GET /api/sectors/{sector_id}/stocks
```

当前可能返回空/pending，前端必须正常展示。

### 产业链

```http
GET /api/industry-chains
GET /api/industry-chains/{chain_id}
GET /api/industry-chains/{chain_id}/stocks
```

当前可能返回空/pending，前端必须正常展示。

## 9. UI 设计要求

这是投研/交易工作台，不是营销页。

必须：

- 首屏就是数据工作台。
- 使用正常应用布局：侧边栏 + 顶部工具区 + 主内容。
- 信息密度高、可扫描。
- 表格优先，不要堆装饰性卡片。
- shadcn/ui 用于 button、input、select、tabs、table、badge、skeleton、alert。
- K 线图用 Lightweight Charts。
- 涨用红色，跌用绿色，符合 A 股习惯。
- 所有页面有 loading/error/empty。
- 移动端可用，但桌面优先。

不要：

- 不做 landing page。
- 不做大 hero。
- 不做渐变背景、玻璃拟态、装饰性光斑。
- 不写“功能介绍式”页面文案。
- 不把 pending 后端数据写成假数据。

## 10. Docker Compose 要求

请修改根目录 `docker-compose.yml`，启用前端服务：

```yaml
alphaagent-web:
  build:
    context: ./frontend
    dockerfile: Dockerfile
  environment:
    VITE_API_BASE_URL: http://localhost:8000/api
  ports:
    - "5173:5173"
  depends_on:
    - alphaagent-api
```

前端 Dockerfile 可用 Node 22。

开发启动：

```bash
docker compose up --build alphaagent-api alphaagent-web
```

前端容器里应运行：

```bash
npm run dev -- --host 0.0.0.0
```

## 11. 验收命令

你完成后必须运行：

```bash
docker compose build alphaagent-web
docker compose up -d alphaagent-api alphaagent-web
curl http://localhost:8000/api/health
curl http://localhost:8000/api/ready
curl http://localhost:5173
```

前端本地检查：

```bash
docker compose run --rm alphaagent-web npm run build
```

如果你添加 lint/test，也运行对应命令。

浏览器验收：

- 打开 `http://localhost:5173`。
- 首页出现上证指数。
- `/stocks` 出现股票表格。
- 搜索 `600000` 或 `浦发` 能看到浦发银行。
- 点击一只股票进入详情。
- 详情页出现 K 线图。
- 详情页出现主营业务、板块、产业链模块，即使当前是 pending/empty。
- `/indices/sh000001` 出现上证指数 K 线。
- `/data` 出现数据源状态。

## 12. 禁止事项

- 不要修改 `vnpy/`。
- 不要修改官方 examples。
- 不要删除后端接口。
- 不要把真实密钥、数据库密码写入仓库。
- 不要 git commit。
- 不要实现选股、推荐、模拟交易、回测页面。
- 不要继续扩展 `alphaagent/server/web/*` 作为正式 UI。

## 13. 你可以读取的上下文文档

请优先读取：

- `AGENTS.md`
- `requirements/alphaagent_real_data_display_execution_plan.md`
- `requirements/alphaagent_service_frontend_execution_plan.md`
- `requirements/alphaagent_functional_design.md`
- `alphaagent/server/api/*.py`
- `alphaagent/market/models.py`
- `alphaagent/market/providers.py`
- `docker-compose.yml`

## 14. 完成后的交付说明

完成后请说明：

- 创建了哪些前端文件。
- 实现了哪些页面。
- 调用了哪些 API。
- Docker Compose 如何启动。
- 运行了哪些验证命令。
- 哪些模块仍是 pending，因为后端还没落库实现。
