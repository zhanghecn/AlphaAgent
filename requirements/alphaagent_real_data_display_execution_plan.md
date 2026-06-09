# AlphaAgent 真实数据展示与前后端分工执行计划

状态：可执行方案，待用户审查后进入实现。  
目标：先完成“打开前端即可查看真实 A 股数据并互动浏览”的阶段，不做选股、推荐、模拟交易和实盘交易。  
边界：vn.py 作为 Datafeed/Gateway/Database/MainEngine 服务能力支撑，不修改 vn.py Qt 界面；用户界面全部由独立前端实现。  

## 1. 用户需求重新确认

用户当前要的不是静态演示，也不是先做选股，而是：

- 项目基于 vn.py，但不修改 vn.py 界面。
- vn.py 作为底层服务能力：Datafeed、Gateway、Database、MainEngine、标准对象模型。
- 所有用户界面都走 Web 前端。
- 后端功能由 Codex 实现。
- 前端界面交给 Claude Code 实现。
- 前端技术栈固定：
  - React
  - TypeScript
  - Vite
  - Tailwind CSS
  - shadcn/ui
- 项目启动、测试、发布都通过 Docker Compose。
- 第一阶段先实现真实数据显示和互动：
  - 所有 A 股股票列表。
  - 点击股票能看到类似炒股软件的详情和指标。
  - 上证指数展示。
  - 个股主营业务：公司做什么。
  - 个股涉及哪些板块。
  - 板块对应产业链是什么。
  - 个股在产业链中的位置和收入/业务占比。

本阶段明确不做：

- 不做智能选股。
- 不做 Top 推荐。
- 不做自动交易。
- 不做模拟建仓。
- 不做回测。
- 不把临时静态页面当最终前端。

## 2. 对已有设计的评估

### 2.1 已有设计里正确的部分

`requirements/alphaagent_functional_design.md` 和 `requirements/alphaagent_service_frontend_execution_plan.md` 已经覆盖：

- AlphaAgent 是上层服务系统，vn.py 是底层能力。
- 不修改 vn.py Qt UI。
- 前端由 Claude Code 实现。
- 前端技术栈包括 React、TypeScript、Vite、Tailwind CSS、shadcn/ui。
- 需要 `/stocks`、`/stocks/:symbol`、`/indices/sh000001`、`/sectors` 等页面。
- 股票详情需要行情、指标、财务、主营业务、板块、产业链。
- 后端已有 REST API 草案。
- 已有部分数据表草案：`stocks`、`stock_daily_bars`、`stock_latest_quotes`、`company_profiles`、`business_segments`、`sectors`、`stock_sector_memberships`、`industry_chains`、`stock_chain_exposures`。

这些方向应保留。

### 2.2 需要补充或修正的部分

现有设计还不够执行，主要缺：

- 没有把“所有 A 股真实数据”拆成基础证券列表、实时行情、历史 K 线、财务指标、主营构成、板块/概念、产业链六类数据。
- 没有明确 PostgreSQL + Redis + Docker Compose 是本阶段默认运行方式。
- 没有明确后端容器如何连接现有 1Panel PostgreSQL/Redis。
- 没有明确前端是独立 Vite 服务，不由后端写静态页面替代。
- 没有给 Claude Code 一份足够具体的页面、组件、字段、API 契约。
- 没有区分“真实数据源”和“vn.py 服务能力”的职责：
  - vn.py 插件负责正规 Datafeed/Gateway/Database 路径。
  - 公共行情接口只能作为开发期真实数据显示适配器，不等同于 vn.py 官方交易能力。
- 没有规定数据落库和缓存策略，导致页面每次直接打外部接口，不稳定。
- 没有给出 Docker Compose 下的后端、前端、迁移、测试服务。
- 没有把“公司做什么、收入占比、板块、产业链、产业链位置”设计成可落地的数据模型和 API。
- 没有明确验收标准：前端打开后必须能看到多少股票、哪些指标、哪些详情页内容。

### 2.3 刚才临时实现的处理结论

之前的临时真实数据工作台验证了真实公开行情接口可用于展示指数、股票表、详情和 K 线，但它不符合最终分工：

- 前端不是 React + TypeScript + Vite + Tailwind + shadcn/ui。
- Docker 入口使用标准库 HTTP 服务，不是最终 FastAPI 后端。
- 没有 PostgreSQL 落库。
- 没有 Redis 缓存。
- 没有完整全 A 本地数据表。
- 没有主营业务、板块、产业链数据模型。

后续实现时应只保留数据源验证结论和可复用适配器思路，不应继续扩展任何后端托管的临时静态前端。

## 3. 最终架构

```text
Docker Compose
  alphaagent-api        FastAPI 后端，Codex 实现
  alphaagent-web        Vite + React + TypeScript + Tailwind + shadcn/ui，Claude Code 实现
  alphaagent-migrate    Alembic migration，一次性任务
  alphaagent-tests      后端/前端测试，可选分开

外部现有服务
  1Panel-postgresql-657K  PostgreSQL，宿主机 5432
  1Panel-redis-aeey       Redis，宿主机 6379

AlphaAgent 后端
  API 层
  数据同步任务
  PostgreSQL 业务库
  Redis 缓存
  vn.py Bridge
  数据源适配器

vn.py
  Datafeed / Gateway / Database / MainEngine / Object Model
```

### 3.1 Compose 服务

`docker-compose.yml` 后续应包含：

- `alphaagent-api`
  - FastAPI 后端。
  - 端口：`8000:8000`。
  - 连接 PostgreSQL/Redis。
  - 暴露 `/api/*`。
- `alphaagent-web`
  - Vite 前端。
  - 开发端口：`5173:5173`。
  - 生产阶段可构建静态文件并由 Nginx 或后端静态托管，后续再定。
- `alphaagent-migrate`
  - 运行 `alembic upgrade head`。
- `alphaagent-api-tests`
  - 运行后端 pytest。
- `alphaagent-web-tests`
  - 运行前端 build、lint、组件测试或 Playwright smoke。

不在 Compose 中新建：

- PostgreSQL 容器。
- Redis 容器。

需要：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

### 3.2 环境变量

`.env.example` 应包含：

```env
ALPHAAGENT_ENV=local
DATABASE_URL=postgresql+psycopg://root:${POSTGRES_PASSWORD}@host.docker.internal:5432/alphaagent
REDIS_URL=redis://host.docker.internal:6379/0
CORS_ORIGINS=http://localhost:5173
PUBLIC_API_BASE_URL=http://localhost:8000/api
```

规则：

- 真实密码只放 `.env`。
- `.env` 必须 git ignore。
- 文档和仓库不写真实密码。

## 4. 后端目录规划

正式后端保留 `alphaagent/` 上层包，不动 `vnpy/`。

```text
alphaagent/
  server/
    main.py                 FastAPI app factory
    api/
      router.py
      health.py
      data_status.py
      stocks.py
      indices.py
      sectors.py
      industry_chains.py
    core/
      config.py
      responses.py
      errors.py
      logging.py
    db/
      session.py
      models.py
      repositories/
        stocks.py
        market_data.py
        fundamentals.py
        sectors.py
        industry_chains.py
    cache/
      redis.py
    services/
      stocks.py
      indices.py
      indicators.py
      company_profile.py
      sectors.py
      industry_chains.py
      data_sync.py
    data_sources/
      base.py
      public_market.py
      public_fundamental.py
      vnpy_datafeed.py
    vnpy_bridge/
      datafeed.py
      gateway.py
      database.py
      objects.py
```

正式前端放独立目录：

```text
frontend/
  package.json
  index.html
  vite.config.ts
  src/
    main.tsx
    app/
    api/
    pages/
    components/
    features/
      market/
      stocks/
      sectors/
      industry-chains/
      data-status/
```

## 5. 数据范围拆分

### 5.1 第一阶段必须支持的数据

第一阶段只围绕“数据显示互动”，至少支持：

- 全 A 股票基础列表：
  - 代码、名称、交易所、上市状态、行业、市场板块。
- 实时/最近行情：
  - 最新价、涨跌幅、成交量、成交额、换手率、市值。
- 历史 K 线：
  - 日线至少 2 年。
  - 后续扩展周线/月线。
- 技术指标：
  - MA5、MA10、MA20、MA60。
  - 成交量均线。
  - 近 20 日涨跌幅。
  - 近 60 日涨跌幅。
  - 近 20/60 日波动率。
  - 近 60 日最大回撤。
- 上证指数：
  - 指数基础信息。
  - 最新行情。
  - 日 K 线。
  - 均线、成交额、涨跌幅。
- 公司主营业务：
  - 公司简介。
  - 主营产品/业务。
  - 收入占比。
  - 毛利占比，若数据源可得。
  - 报告期和来源。
- 板块/概念：
  - 行业板块。
  - 概念板块。
  - 地域板块。
  - 个股属于哪些板块。
- 产业链：
  - 产业链名称。
  - 上游/中游/下游节点。
  - 个股处于哪个环节。
  - 暴露比例或收入占比。
  - 依据说明。

### 5.2 数据源优先级

正式实现按以下优先级设计，避免把公共接口写死在业务层：

1. vn.py 官方/插件路径：
   - `vnpy.trader.datafeed.get_datafeed()`
   - `vnpy.trader.database.get_database()`
   - 未来 `vnpy_xt`、`vnpy_rqdata`、`vnpy_tushare`
2. AlphaAgent 数据源适配器：
   - 开发期公共行情适配器，用于真实数据显示。
   - 只承担展示和研究数据，不承担实盘交易。
3. 手工维护/半自动维护数据：
   - 产业链初始 taxonomy。
   - 个股主营业务和产业链映射的修正数据。

重要边界：

- 公共接口数据用于开发期真实展示，不声明为交易级实时行情。
- 只有安装并配置真实 A 股 vn.py Gateway/Datafeed 后，才能声明完整交易数据能力。

## 6. PostgreSQL 数据模型

### 6.1 股票基础

`stocks`

- `id`
- `symbol`
- `exchange`
- `vt_symbol`
- `name`
- `market`
- `list_date`
- `is_active`
- `is_st`
- `industry_code`
- `industry_name`
- `created_at`
- `updated_at`

唯一约束：

- `vt_symbol`

### 6.2 行情快照

`stock_latest_quotes`

- `vt_symbol`
- `trade_time`
- `last_price`
- `change`
- `change_pct`
- `open`
- `high`
- `low`
- `pre_close`
- `volume`
- `turnover`
- `turnover_rate`
- `market_cap`
- `pe`
- `pb`
- `source`
- `updated_at`

### 6.3 历史 K 线

`stock_daily_bars`

- `vt_symbol`
- `trade_date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `turnover`
- `adj_factor`
- `source`

唯一约束：

- `vt_symbol + trade_date`

### 6.4 技术指标

`stock_technical_indicators`

- `vt_symbol`
- `trade_date`
- `ma5`
- `ma10`
- `ma20`
- `ma60`
- `volume_ma5`
- `volume_ma20`
- `return_20d`
- `return_60d`
- `volatility_20d`
- `volatility_60d`
- `max_drawdown_60d`
- `source`

### 6.5 指数

`indices`

- `symbol`
- `exchange`
- `vt_symbol`
- `name`
- `category`

`index_daily_bars`

- `vt_symbol`
- `trade_date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `turnover`
- `source`

### 6.6 公司主营业务

`company_profiles`

- `vt_symbol`
- `company_name`
- `business_summary`
- `main_business`
- `competitive_advantage`
- `source`
- `updated_at`

`business_segments`

- `id`
- `vt_symbol`
- `report_period`
- `segment_name`
- `revenue`
- `revenue_ratio`
- `gross_profit`
- `gross_profit_ratio`
- `description`
- `source`

### 6.7 板块

`sectors`

- `sector_id`
- `name`
- `type`
  - `industry`
  - `concept`
  - `region`
  - `theme`
- `description`
- `source`

`stock_sector_memberships`

- `vt_symbol`
- `sector_id`
- `weight`
- `reason`
- `source`
- `updated_at`

### 6.8 产业链

`industry_chains`

- `chain_id`
- `name`
- `description`

`industry_chain_nodes`

- `node_id`
- `chain_id`
- `name`
- `stage`
  - `upstream`
  - `midstream`
  - `downstream`
- `description`

`stock_chain_exposures`

- `id`
- `vt_symbol`
- `chain_id`
- `node_id`
- `exposure_ratio`
- `basis`
  - `revenue_ratio`
  - `business_tag`
  - `manual_mapping`
  - `data_vendor`
- `explanation`
- `source`
- `updated_at`

## 7. 后端 API 契约

统一响应格式保留：

```json
{
  "success": true,
  "data": {},
  "error": null,
  "request_id": "req_xxx"
}
```

### 7.1 系统和数据状态

```http
GET /api/health
GET /api/ready
GET /api/data/status
POST /api/data/sync/full
POST /api/data/sync/quotes
POST /api/data/sync/fundamentals
GET /api/jobs/{job_id}
```

`GET /api/ready` 必须检查：

- PostgreSQL。
- Redis。
- 至少一个行情数据源。

`GET /api/data/status` 返回：

```json
{
  "database": "ok",
  "redis": "ok",
  "data_sources": [
    {"name": "vnpy_datafeed", "status": "missing_plugin"},
    {"name": "public_market", "status": "ok"}
  ],
  "tables": {
    "stocks": {"rows": 5300, "updated_at": "2026-06-07T15:00:00+08:00"},
    "stock_daily_bars": {"rows": 1200000, "updated_at": "2026-06-07T15:00:00+08:00"}
  }
}
```

### 7.2 全 A 股票

```http
GET /api/stocks?q=&industry=&sector=&market=&is_st=&page=1&page_size=50&sort=market_cap:desc
```

返回：

```json
{
  "items": [
    {
      "symbol": "600000",
      "exchange": "SSE",
      "vt_symbol": "600000.SSE",
      "name": "浦发银行",
      "industry_name": "银行",
      "market": "主板",
      "last_price": 9.34,
      "change_pct": 1.63,
      "turnover": 692089681,
      "turnover_rate": 0.22,
      "market_cap": 311076529722,
      "pe": 4.35,
      "pb": 0.41,
      "sectors": ["银行", "上海板块"],
      "updated_at": "2026-06-05T15:00:00+08:00"
    }
  ],
  "page": 1,
  "page_size": 50,
  "total": 5300
}
```

### 7.3 股票详情

```http
GET /api/stocks/{vt_symbol}
GET /api/stocks/{vt_symbol}/bars?interval=1d&start=2024-01-01&end=2026-06-07
GET /api/stocks/{vt_symbol}/indicators?trade_date=latest
GET /api/stocks/{vt_symbol}/business
GET /api/stocks/{vt_symbol}/sectors
GET /api/stocks/{vt_symbol}/industry-chain
```

详情页必须一次性可组合出炒股软件基础效果：

- 头部报价。
- K 线。
- 技术指标。
- 估值指标。
- 财务/主营摘要。
- 板块/概念。
- 产业链位置。

### 7.4 上证指数

```http
GET /api/indices
GET /api/indices/{vt_symbol}
GET /api/indices/{vt_symbol}/bars?interval=1d&start=2024-01-01&end=2026-06-07
GET /api/indices/{vt_symbol}/indicators
```

上证指数固定入口：

```http
GET /api/indices/000001.SSE
```

前端路由可用：

```text
/indices/sh000001
```

### 7.5 板块和产业链

```http
GET /api/sectors?type=industry|concept|region|theme
GET /api/sectors/{sector_id}
GET /api/sectors/{sector_id}/stocks?page=1&page_size=50
GET /api/industry-chains
GET /api/industry-chains/{chain_id}
GET /api/industry-chains/{chain_id}/stocks
```

### 7.6 给前端的一站式详情聚合接口

为了让前端简单，后端增加聚合接口：

```http
GET /api/stocks/{vt_symbol}/snapshot
```

返回：

```json
{
  "quote": {},
  "bars": [],
  "technical_indicators": {},
  "business": {},
  "sectors": [],
  "industry_chain": {},
  "data_quality": {
    "missing": ["gross_profit_ratio"],
    "sources": ["postgres", "public_market"]
  }
}
```

Claude Code 做前端时优先调用 `snapshot`，再按页面模块按需调用细分接口。

## 8. 前端交给 Claude Code 的明确任务

Claude Code 只做前端，不实现后端业务逻辑。

### 8.1 前端技术栈

- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui
- TanStack Query
- TanStack Table
- Lightweight Charts

### 8.2 前端目录

```text
frontend/
  src/
    api/
      client.ts
      types.ts
      stocks.ts
      indices.ts
      sectors.ts
    pages/
      MarketOverviewPage.tsx
      StocksPage.tsx
      StockDetailPage.tsx
      IndexDetailPage.tsx
      SectorsPage.tsx
      DataStatusPage.tsx
    features/
      stocks/
        StockTable.tsx
        StockQuoteHeader.tsx
        StockKlineChart.tsx
        StockIndicatorPanel.tsx
        StockBusinessPanel.tsx
        StockSectorPanel.tsx
        StockIndustryChainPanel.tsx
      market/
        IndexStrip.tsx
      sectors/
        SectorList.tsx
        IndustryChainGraph.tsx
```

### 8.3 前端页面

第一阶段只做：

- `/`
  - 市场概览。
  - 上证指数等指数条。
  - 数据更新时间。
  - 数据源状态入口。
- `/stocks`
  - 全 A 股票表。
  - 搜索、筛选、排序、分页。
  - 点击进入详情。
- `/stocks/:vtSymbol`
  - 报价头部。
  - K 线。
  - 指标。
  - 主营业务。
  - 板块。
  - 产业链。
- `/indices/sh000001`
  - 上证指数行情和 K 线。
- `/sectors`
  - 行业/概念/主题板块列表。
  - 点击板块看成员股。
- `/data`
  - 数据源状态、表行数、更新时间。

第一阶段不要做：

- 推荐页。
- 模拟交易页。
- 回测页。
- 营销 landing page。

### 8.4 前端设计要求

- 工作台风格，信息密度高。
- 不做 hero。
- 不做装饰性卡片堆叠。
- 表格是核心交互。
- K 线图用成熟库，不手写复杂图表。
- 每个模块有 loading/error/empty 状态。
- API base URL 从环境变量 `VITE_API_BASE_URL` 读取。
- 生产和开发都必须能通过 Docker Compose 启动。

## 9. 后端实现阶段

### 阶段 0：清理临时静态前端边界

目标：

- 明确后端托管的临时静态页面不是正式前端。
- 后续可以删除或保留为临时诊断页面，但不能作为产品 UI。

验收：

- 正式 Compose 中前端由 `alphaagent-web` 提供。
- `alphaagent-api` 不再承担产品前端页面职责。

### 阶段 1：FastAPI + 数据库基础

文件：

- `alphaagent/server/main.py`
- `alphaagent/server/core/config.py`
- `alphaagent/server/core/responses.py`
- `alphaagent/server/db/session.py`
- `alphaagent/server/cache/redis.py`
- `alembic/*`
- `Dockerfile.alphaagent-api`
- `docker-compose.yml`

产出：

- FastAPI 服务。
- `/api/health`
- `/api/ready`
- PostgreSQL 连接。
- Redis 连接。
- Alembic migration。
- Docker Compose 启动。

验收：

```bash
docker compose build
docker compose run --rm alphaagent-migrate
docker compose up -d alphaagent-api
curl http://localhost:8000/api/health
curl http://localhost:8000/api/ready
```

### 阶段 2：全 A 基础数据入库

目标：

- 拉取或导入全 A 股票基础列表。
- 写入 `stocks`。
- 能分页查询所有股票。

产出：

- `POST /api/data/sync/full`
- `GET /api/stocks`
- `GET /api/data/status`

验收：

- `stocks` 表行数达到真实全 A 规模，预期 5000+。
- `/api/stocks?page=1&page_size=50` 返回分页数据。
- 前端股票表能看到所有 A 股，不只是内置样例。

### 阶段 3：行情和 K 线

目标：

- 同步最近行情到 `stock_latest_quotes`。
- 同步日 K 到 `stock_daily_bars`。
- 计算基础技术指标。

产出：

- `GET /api/stocks/{vt_symbol}`
- `GET /api/stocks/{vt_symbol}/bars`
- `GET /api/stocks/{vt_symbol}/indicators`
- `GET /api/indices/000001.SSE`
- `GET /api/indices/000001.SSE/bars`

验收：

- 点击任意 A 股能看到报价和 K 线。
- 上证指数页面能显示行情和 K 线。
- 技术指标接口有 MA、涨跌幅、波动率、回撤。

### 阶段 4：主营业务、板块、产业链

目标：

- 建立“公司做什么”的数据。
- 建立板块和产业链映射。
- 支持股票详情页展示业务、板块、产业链。

产出：

- `company_profiles`
- `business_segments`
- `sectors`
- `stock_sector_memberships`
- `industry_chains`
- `industry_chain_nodes`
- `stock_chain_exposures`
- `GET /api/stocks/{vt_symbol}/business`
- `GET /api/stocks/{vt_symbol}/sectors`
- `GET /api/stocks/{vt_symbol}/industry-chain`
- `GET /api/sectors`
- `GET /api/industry-chains`

验收：

- 至少覆盖沪深 300 或首批 300 只核心股票的主营业务和板块。
- 股票详情页能看到：
  - 公司做什么。
  - 主营业务占比。
  - 所属行业/概念/地域板块。
  - 所属产业链。
  - 上中下游位置。
  - 暴露比例或依据说明。

### 阶段 5：Claude Code 前端接入

目标：

- Claude Code 按第 8 节实现前端。
- 前端通过 Docker Compose 与后端联调。

验收：

```bash
docker compose build
docker compose up -d
curl http://localhost:8000/api/ready
curl http://localhost:5173
```

浏览器验收：

- 打开 `http://localhost:5173`。
- 看到指数概览。
- 进入 `/stocks`，能翻页查看全 A。
- 点击任意股票进入详情。
- 看到 K 线、指标、主营业务、板块、产业链。
- 打开 `/indices/sh000001` 看到上证指数。

## 10. Docker Compose 目标形态

```yaml
services:
  alphaagent-api:
    build:
      context: .
      dockerfile: Dockerfile.alphaagent-api
    env_file:
      - .env
    ports:
      - "8000:8000"
    extra_hosts:
      - "host.docker.internal:host-gateway"

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

  alphaagent-migrate:
    build:
      context: .
      dockerfile: Dockerfile.alphaagent-api
    env_file:
      - .env
    command: alembic upgrade head
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

测试命令：

```bash
docker compose run --rm alphaagent-api-tests
docker compose run --rm alphaagent-web-tests
```

## 11. 给 Claude Code 的前端接口说明摘要

Claude Code 前端只依赖这些接口：

```http
GET /api/health
GET /api/ready
GET /api/data/status

GET /api/market/overview

GET /api/stocks
GET /api/stocks/{vt_symbol}
GET /api/stocks/{vt_symbol}/snapshot
GET /api/stocks/{vt_symbol}/bars
GET /api/stocks/{vt_symbol}/indicators
GET /api/stocks/{vt_symbol}/business
GET /api/stocks/{vt_symbol}/sectors
GET /api/stocks/{vt_symbol}/industry-chain

GET /api/indices
GET /api/indices/000001.SSE
GET /api/indices/000001.SSE/bars
GET /api/indices/000001.SSE/indicators

GET /api/sectors
GET /api/sectors/{sector_id}
GET /api/sectors/{sector_id}/stocks

GET /api/industry-chains
GET /api/industry-chains/{chain_id}
GET /api/industry-chains/{chain_id}/stocks
```

前端不要调用：

- 外部行情接口。
- vn.py Python 代码。
- 数据库。
- Redis。

## 12. 验收标准

第一阶段完成必须满足：

- 不修改 `vnpy/` 和官方 examples。
- Docker Compose 一条命令能启动后端和前端。
- 后端 `/api/ready` 同时验证 PostgreSQL、Redis、行情数据源。
- PostgreSQL 有全 A 股票基础表，行数为真实全 A 规模。
- `/api/stocks` 支持分页、搜索、排序、筛选。
- `/stocks` 前端页面显示全 A 表格。
- 点击股票进入详情页。
- 详情页展示报价、K 线、技术指标、主营业务、板块、产业链。
- `/indices/sh000001` 展示上证指数行情和 K 线。
- 所有页面有 loading/error/empty 状态。
- 后端测试通过。
- 前端 build 通过。
- Playwright smoke 至少覆盖：
  - 首页加载指数。
  - 股票列表加载。
  - 点击股票进入详情。
  - 详情页出现 K 线容器和主营业务模块。

## 13. 当前下一步

下一步不应继续扩展临时静态页面，而应：

1. 将后端恢复为正式 FastAPI 服务。
2. 补 PostgreSQL/Redis/Alembic。
3. 实现全 A 数据同步和落库。
4. 实现股票/指数/业务/板块/产业链 API。
5. 生成给 Claude Code 的前端任务包。
6. 让 Claude Code 创建 `frontend/`。
7. 用 Docker Compose 联调、测试、截图验收。

如果要保留当前临时页面，只能作为 `/debug` 或开发诊断页面，不作为 AlphaAgent 正式前端。
