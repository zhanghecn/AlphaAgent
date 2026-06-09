# AlphaAgent 服务端与前端执行方案

状态：草案，待用户审查。  
原则：本文件是执行计划，不是最终实现。

## 1. 本次补充的关键边界

已有设计已经说明了 AlphaAgent 要做“选股、解释、模拟建仓、回测、风控”。但还缺少以下可执行内容：

- vn.py 在系统中到底作为哪些服务能力，不再使用和修改 vn.py Qt 界面。
- 前端由 Claude Code 负责时，需要给它哪些页面、接口、字段和交互说明。
- 后端如何组织模块，如何把 vn.py 的 Datafeed/Gateway/Database 能力封装成 API。
- “所有 A 股列表”和“股票详情像炒股软件一样”的具体数据结构。
- 个股主营业务、板块、产业链、收入占比/业务占比如何建模。
- 上证指数等指数数据如何展示。
- 用户少配置的原则如何落实到 API 和页面。

本文件补齐这些内容。

## 2. 架构结论

### 2.1 vn.py 的角色

vn.py 作为 AlphaAgent 的底层服务支撑，不作为用户直接操作界面。

使用 vn.py：

- `Datafeed`: 查询历史 K 线/Tick。
- `Gateway`: 后续接券商、实时行情、下单/撤单。
- `Database`: 保存历史数据。
- `MainEngine`: 后续统一管理 Gateway 和交易能力。
- `Object`: 复用 `BarData`、`TickData`、`ContractData`、`HistoryRequest` 等对象。
- `AlphaLab`: 因子研究、信号和本地研究数据管理候选。

不做：

- 不修改 vn.py Qt 界面。
- 不让用户直接使用 VeighNa Trader 界面。
- 不把 AlphaAgent 业务代码直接混入 `vnpy/` 核心包。

### 2.2 AlphaAgent 的角色

AlphaAgent 是上层业务系统：

- 提供后端 API。
- 提供数据标准化。
- 提供股票池、板块、产业链、评分、推荐、模拟交易、回测编排。
- 给前端返回用户能看懂的结论和解释。

建议未来新增：

```text
alphaagent/
  server/           FastAPI 服务入口
  shared/           配置、日志、错误、数据库
  vnpy_bridge/      vn.py 适配层
  data/             A 股数据接入和标准化
  market/           指数、行情、市场状态
  stocks/           股票列表和详情
  sectors/          板块、概念、产业链
  scoring/          量化评分
  recommendation/   推荐和解释
  simulation/       模拟建仓/模拟交易
  backtest/         回测编排
  review/           复盘和教训
```

### 2.3 前端角色

前端交给 Claude Code 实现。

技术栈：

- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui

前端不负责：

- 复杂选股逻辑。
- 数据源连接。
- vn.py 调用。
- 回测计算。
- Agent 研究。

前端负责：

- 页面、表格、图表、交互。
- 调用后端 API。
- 展示加载、错误、空状态。
- 让用户少配置、重点看结论。

## 3. 技术决策

### 3.1 后端框架

建议：FastAPI + Pydantic。

原因：

- Python 项目，便于直接调用 vn.py。
- 自动生成 OpenAPI，方便 Claude Code 根据 API 写前端。
- Pydantic 适合定义清晰的接口模型。

### 3.2 API 形式

建议：REST API + OpenAPI。

初期使用 REST 足够。未来实时行情、任务进度、模拟持仓刷新，可加 SSE。

### 3.3 数据库

开发期：

- SQLite：简单、适合本地快速验证。
- Parquet/DuckDB：适合较大行情和分析数据，后续可引入。

生产期：

- PostgreSQL：主业务数据。
- Redis：缓存和任务状态。
- 对行情大表可考虑 ClickHouse/DuckDB/Parquet。

### 3.4 实时能力

MVP：

- 前端轮询。
- `/api/jobs/{job_id}` 查询任务状态。

后续：

- SSE 推送行情、数据更新进度、回测进度。

### 3.5 认证

MVP：

- 本地单用户，不做复杂登录。

后续：

- JWT 或 Session。
- 交易相关操作必须二次确认。
- 实盘下单前必须有人工确认开关。

## 4. 用户页面设计给 Claude Code

### 4.1 总览页 `/`

目的：用户一打开就知道今天看什么。

展示：

- 当前市场状态：牛市/熊市/震荡/结构性行情。
- 上证指数、深证成指、创业板指、科创指数概览。
- 今日主线板块。
- 最近 30 天板块资金流入 Top 10。
- 今日推荐股票 Top 5。
- 系统风险提示。

前端组件建议：

- 顶部市场状态条。
- 指数行情卡片。
- 板块资金表。
- 推荐股票表。
- 风险提示面板。

### 4.2 全 A 股票页 `/stocks`

目的：像炒股软件一样看到所有 A 股，并可搜索、筛选、排序。

表格字段：

- 股票代码。
- 股票名称。
- 交易所。
- 最新价。
- 涨跌幅。
- 成交额。
- 换手率。
- 市值。
- 行业。
- 概念/板块。
- 量化总分。
- 风险等级。
- 是否入选候选池。

筛选：

- 搜索名称/代码。
- 行业。
- 板块/概念。
- 市值区间。
- 涨跌幅区间。
- 风险等级。
- 是否黑名单。
- 是否推荐。

操作：

- 点击股票进入详情。
- 加入观察。
- 拉黑。
- 查看推荐理由。

### 4.3 股票详情页 `/stocks/:symbol`

目的：用户点开股票后，看到“炒股软件基础信息 + AlphaAgent 解释”。

模块：

- 股票头部：名称、代码、最新价、涨跌幅、市值、行业、风险等级。
- K 线图：日线/周线/月线，后续支持分钟。
- 技术指标：均线、成交量、换手、波动率、回撤、趋势评分。
- 财务指标：收入、利润、现金流、毛利率、净利率、ROE、负债率。
- 估值指标：PE、PB、PS、股息率、历史分位。
- 资金指标：个股资金流、板块资金流、龙虎榜线索。
- 主营业务：公司做什么、主要产品、收入占比、毛利占比。
- 所属板块：行业、概念、主题、是否主线。
- 产业链：上游、当前环节、下游、公司位置、受益逻辑。
- AlphaAgent 推荐解释：为什么选/不选。
- 风控建议：能否模拟建仓、建议仓位、止损、止盈、失效条件。
- 相关新闻/公告/政策。

关键要求：

- 每个“推荐理由”都要能展开看到对应指标或消息来源。
- 不要只给分数，要解释分数为什么高/低。

### 4.4 上证指数页 `/indices/sh000001`

目的：展示上证指数和市场环境判断。

展示：

- 上证指数 K 线。
- 指数涨跌幅。
- 成交额。
- 均线趋势。
- 波动率。
- 上涨/下跌家数。
- 创新高/新低数量。
- 当前市场状态判断。
- 判断依据。

后续扩展：

- 深证成指。
- 创业板指。
- 科创指数。
- 沪深 300。
- 中证 500/1000。

### 4.5 板块页 `/sectors`

目的：看资金往哪里流，市场主线在哪里。

展示：

- 最近 30 天板块资金流。
- 板块涨跌幅。
- 板块成交额。
- 板块强度评分。
- 板块内龙头 1-4。
- 板块产业链说明。

点击板块进入 `/sectors/:sector_id`。

### 4.6 板块详情页 `/sectors/:sector_id`

展示：

- 板块介绍。
- 产业链图谱。
- 上游/中游/下游。
- 龙头股票 1-4。
- 成员股列表。
- 资金流趋势。
- 政策/新闻催化。
- 推荐候选。

### 4.7 推荐页 `/recommendations`

展示：

- 今日 Top 5。
- 候选池 Top 20。
- 每只股票的量化分、Agent 分、风险等级。
- 推荐周期：长期/波段/短线。
- 建议动作：观察/模拟建仓/暂不买。

### 4.8 模拟建仓页 `/simulation`

展示：

- 模拟账户资金。
- 当前持仓。
- 盈亏。
- 风控触发。
- 交易日志。
- 可模拟建仓的推荐股。

操作：

- 一键模拟买入。
- 模拟卖出。
- 查看建仓理由。
- 查看止损/止盈规则。

### 4.9 回测页 `/backtests`

展示：

- 策略列表。
- 回测任务列表。
- 回测结果。
- 收益曲线。
- 最大回撤。
- 胜率。
- 牛熊震荡分段表现。
- 失败案例。

### 4.10 数据状态页 `/data`

展示：

- 股票基础数据是否完整。
- 行情数据更新时间。
- 财务数据更新时间。
- 板块资金更新时间。
- 新闻/公告更新时间。
- vn.py 插件状态。
- 缺失数据提示。

这个页面面向开发/管理员，不是普通用户主入口。

## 5. 后端 API 设计

统一响应格式：

```json
{
  "success": true,
  "data": {},
  "error": null,
  "request_id": "req_xxx"
}
```

错误格式：

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "DATA_SOURCE_NOT_READY",
    "message": "A 股行情数据源未配置",
    "detail": {}
  },
  "request_id": "req_xxx"
}
```

### 5.1 系统状态

```http
GET /api/health
GET /api/ready
GET /api/data/status
POST /api/data/sync
GET /api/jobs/{job_id}
```

### 5.2 市场总览

```http
GET /api/market/overview
GET /api/market/state
GET /api/indices
GET /api/indices/{index_symbol}
GET /api/indices/{index_symbol}/bars?interval=1d&start=2024-01-01&end=2026-06-07
```

`/api/market/overview` 返回：

```json
{
  "trade_date": "2026-06-07",
  "market_state": "STRUCTURAL",
  "risk_level": "MEDIUM",
  "indices": [
    {
      "symbol": "000001",
      "exchange": "SSE",
      "name": "上证指数",
      "last_price": 0,
      "change_pct": 0,
      "turnover": 0
    }
  ],
  "top_sectors": [],
  "recommendation_count": 0,
  "warnings": []
}
```

### 5.3 股票列表

```http
GET /api/stocks
```

查询参数：

- `q`: 股票代码/名称搜索。
- `industry`: 行业。
- `sector`: 板块/概念。
- `risk_level`: 风险等级。
- `recommended`: 是否推荐。
- `blacklisted`: 是否黑名单。
- `page`: 页码。
- `page_size`: 每页数量。
- `sort`: 排序字段。

返回核心字段：

```json
{
  "items": [
    {
      "symbol": "600000",
      "exchange": "SSE",
      "vt_symbol": "600000.SSE",
      "name": "浦发银行",
      "industry": "银行",
      "sectors": ["银行", "沪股通"],
      "last_price": 0,
      "change_pct": 0,
      "turnover": 0,
      "market_cap": 0,
      "score": 72.5,
      "risk_level": "LOW",
      "is_recommended": false,
      "is_blacklisted": false
    }
  ],
  "page": 1,
  "page_size": 50,
  "total": 0
}
```

### 5.4 股票详情

```http
GET /api/stocks/{vt_symbol}
GET /api/stocks/{vt_symbol}/bars?interval=1d&start=2024-01-01&end=2026-06-07
GET /api/stocks/{vt_symbol}/indicators
GET /api/stocks/{vt_symbol}/financials
GET /api/stocks/{vt_symbol}/business
GET /api/stocks/{vt_symbol}/sectors
GET /api/stocks/{vt_symbol}/industry-chain
GET /api/stocks/{vt_symbol}/money-flow?window=30
GET /api/stocks/{vt_symbol}/news
GET /api/stocks/{vt_symbol}/recommendation
```

`/api/stocks/{vt_symbol}/business` 返回：

```json
{
  "summary": "公司主营业务摘要",
  "main_products": [
    {
      "name": "产品A",
      "revenue_ratio": 0.62,
      "gross_profit_ratio": 0.71,
      "description": "产品说明"
    }
  ],
  "business_tags": ["算力", "PCB"],
  "source": "annual_report",
  "updated_at": "2026-06-07T00:00:00+08:00"
}
```

`/api/stocks/{vt_symbol}/industry-chain` 返回：

```json
{
  "chain_name": "算力产业链",
  "position": "中游设备/材料",
  "upstream": ["原材料", "设备"],
  "midstream": ["制造", "封装"],
  "downstream": ["数据中心", "云厂商"],
  "exposure": [
    {
      "sector": "PCB",
      "ratio": 0.45,
      "basis": "收入占比"
    }
  ],
  "explanation": "公司在产业链中的位置和受益逻辑"
}
```

### 5.5 板块和产业链

```http
GET /api/sectors
GET /api/sectors/{sector_id}
GET /api/sectors/{sector_id}/stocks
GET /api/sectors/{sector_id}/leaders
GET /api/sectors/{sector_id}/money-flow?window=30
GET /api/industry-chains
GET /api/industry-chains/{chain_id}
```

板块龙头返回：

```json
{
  "sector_id": "pcb",
  "sector_name": "PCB",
  "leaders": [
    {
      "rank": 1,
      "vt_symbol": "xxxx.SSE",
      "name": "公司名",
      "leader_type": "FUNDAMENTAL_AND_MONEY",
      "reason": "收入规模、资金强度、板块地位综合第一",
      "score": 88.2
    }
  ]
}
```

### 5.6 推荐和解释

```http
GET /api/recommendations/today
GET /api/recommendations/{recommendation_id}
POST /api/recommendations/run
```

推荐返回：

```json
{
  "trade_date": "2026-06-07",
  "market_state": "STRUCTURAL",
  "items": [
    {
      "rank": 1,
      "vt_symbol": "xxxx.SSE",
      "name": "公司名",
      "action": "WATCH",
      "horizon": "SWING",
      "confidence": 0.72,
      "total_score": 86.5,
      "quant_reasons": ["板块资金连续流入", "趋势评分高"],
      "agent_reasons": ["政策催化明确", "产业链位置受益"],
      "risks": ["估值偏高", "板块退潮风险"],
      "risk_control": {
        "max_position_pct": 0.1,
        "stop_loss_pct": 0.06,
        "take_profit_pct": 0.15,
        "invalidation": "跌破关键支撑且资金持续流出"
      }
    }
  ]
}
```

### 5.7 模拟交易

```http
GET /api/simulation/accounts
POST /api/simulation/accounts
GET /api/simulation/accounts/{account_id}/positions
GET /api/simulation/accounts/{account_id}/orders
POST /api/simulation/accounts/{account_id}/orders
GET /api/simulation/accounts/{account_id}/risk-events
```

模拟下单请求：

```json
{
  "vt_symbol": "xxxx.SSE",
  "side": "BUY",
  "amount": 10000,
  "reason": "来自今日推荐",
  "recommendation_id": "rec_xxx"
}
```

### 5.8 回测

```http
GET /api/backtests
POST /api/backtests
GET /api/backtests/{backtest_id}
GET /api/backtests/{backtest_id}/trades
GET /api/backtests/{backtest_id}/metrics
```

回测请求：

```json
{
  "strategy": "mainline_leader_pullback",
  "scope": {
    "type": "RECOMMENDATION_POOL",
    "symbols": ["xxxx.SSE"]
  },
  "start": "2020-01-01",
  "end": "2026-06-07",
  "market_regime_split": true
}
```

## 6. 后端数据模型草案

### 6.1 股票基础

`stocks`

- id
- symbol
- exchange
- vt_symbol
- name
- list_date
- industry
- market
- is_active
- is_st
- is_blacklisted

### 6.2 股票行情

`stock_daily_bars`

- vt_symbol
- trade_date
- open
- high
- low
- close
- volume
- turnover
- adj_factor

`stock_latest_quotes`

- vt_symbol
- trade_time
- last_price
- change
- change_pct
- volume
- turnover
- bid_price_1
- ask_price_1

### 6.3 股票指标

`stock_indicators`

- vt_symbol
- trade_date
- ma5
- ma10
- ma20
- ma60
- turnover_rate
- volatility
- max_drawdown
- trend_score
- fund_score
- risk_score

### 6.4 公司业务

`company_profiles`

- vt_symbol
- business_summary
- main_products
- competitive_advantage
- updated_at
- source

`business_segments`

- vt_symbol
- report_period
- segment_name
- revenue
- revenue_ratio
- gross_profit
- gross_profit_ratio
- source

### 6.5 板块和产业链

`sectors`

- sector_id
- name
- type
- description

`stock_sector_memberships`

- vt_symbol
- sector_id
- weight
- reason
- source

`industry_chains`

- chain_id
- name
- description

`industry_chain_nodes`

- node_id
- chain_id
- name
- stage: upstream/midstream/downstream
- description

`stock_chain_exposures`

- vt_symbol
- chain_id
- node_id
- exposure_ratio
- basis
- explanation

### 6.6 板块资金

`sector_money_flow`

- sector_id
- trade_date
- net_inflow
- main_net_inflow
- turnover
- change_pct
- strength_score
- rank

### 6.7 推荐与解释

`recommendations`

- recommendation_id
- trade_date
- vt_symbol
- rank
- action
- horizon
- total_score
- confidence
- status

`recommendation_reasons`

- recommendation_id
- reason_type: quant/agent/risk/news/policy
- title
- detail
- evidence
- source_url

## 7. 后端执行流程

### 7.1 数据初始化

```text
1. 检查 vn.py 和数据插件状态
2. 获取全 A 股票列表
3. 获取上证指数等指数列表
4. 获取行业/概念/板块映射
5. 获取历史日线
6. 获取财务和主营业务
7. 生成股票基础表、行情表、业务表、板块表
```

### 7.2 每日更新

```text
1. 更新行情
2. 更新指数
3. 更新板块资金
4. 更新新闻/公告/政策
5. 更新技术指标
6. 更新市场状态
7. 更新量化评分
8. 生成推荐候选
9. Agent 生成解释
10. 写入推荐结果
```

### 7.3 用户浏览股票

```text
前端 /stocks
  -> GET /api/stocks
  -> 后端读取 stocks + latest_quotes + scores
  -> 返回分页表格
```

### 7.4 用户查看股票详情

```text
前端 /stocks/:symbol
  -> GET /api/stocks/:symbol
  -> GET /api/stocks/:symbol/bars
  -> GET /api/stocks/:symbol/indicators
  -> GET /api/stocks/:symbol/business
  -> GET /api/stocks/:symbol/industry-chain
  -> GET /api/stocks/:symbol/recommendation
```

### 7.5 用户模拟建仓

```text
前端点击模拟建仓
  -> POST /api/simulation/accounts/:id/orders
  -> 后端检查推荐状态和风控
  -> 生成模拟订单
  -> 更新模拟持仓
  -> 返回成交和风控结果
```

## 8. 给 Claude Code 的前端实现说明

Claude Code 应按以下要求写前端：

技术栈：

- React + TypeScript + Vite。
- Tailwind CSS。
- shadcn/ui。
- React Query 或 TanStack Query 调 API。
- TanStack Table 做股票列表。
- K 线图可用 Lightweight Charts 或其他成熟图表库。

页面：

- `/`: 今日决策面板。
- `/stocks`: 全 A 股票列表。
- `/stocks/:symbol`: 股票详情。
- `/indices/sh000001`: 上证指数。
- `/sectors`: 板块资金。
- `/sectors/:sector_id`: 板块详情。
- `/recommendations`: 推荐列表。
- `/simulation`: 模拟交易。
- `/backtests`: 回测。
- `/data`: 数据状态。

前端原则：

- 不做 landing page。
- 首屏就是决策面板。
- 风格像专业炒股/投研工作台：信息密度高、可扫描、少装饰。
- 用户不需要配置复杂参数。
- 所有 API base URL 从环境变量读取。
- 所有请求处理 loading/error/empty 状态。
- 表格必须支持排序、筛选、分页。
- 股票详情要像炒股软件一样能看行情、指标、财务、板块、产业链。
- 推荐理由必须分层展示：量化理由、Agent 理由、风险理由、消息来源。

前端不要实现：

- 选股算法。
- 回测算法。
- vn.py 调用。
- 数据源配置细节。

## 9. MVP 可执行阶段

### 阶段 0：方案审查

产出：

- 本文件审查通过。
- 确认后端技术栈。
- 确认前端由 Claude Code 实现。
- 确认不修改 vn.py UI。

### 阶段 1：后端骨架

产出：

- `alphaagent/server` FastAPI 服务。
- `/api/health`
- `/api/ready`
- 统一错误格式。
- 配置文件和 `.env.example`。
- OpenAPI 可访问。

验收：

- `uv run ...` 能启动后端。
- `curl /api/health` 正常。

### 阶段 2：股票和指数基础 API

产出：

- 股票基础表。
- 上证指数基础表。
- `/api/stocks`
- `/api/stocks/{vt_symbol}`
- `/api/indices`
- `/api/indices/sh000001`

验收：

- 前端能展示所有 A 股表格。
- 点击股票能进入详情。
- 能看到上证指数基本信息。

### 阶段 3：行情、指标、业务和板块

产出：

- K 线 API。
- 指标 API。
- 主营业务 API。
- 板块和产业链 API。

验收：

- 股票详情页能展示行情、指标、公司做什么、涉及哪些板块、产业链位置、占比。

### 阶段 4：推荐与解释

产出：

- 量化评分。
- Top 20 候选池。
- Top 5 推荐。
- 推荐理由 API。

验收：

- 用户能看到选了哪些股票。
- 能看到为什么选。
- 能看到指标、消息、风险。

### 阶段 5：模拟建仓

产出：

- 模拟账户。
- 模拟订单。
- 模拟持仓。
- 风控检查。

验收：

- 用户能对推荐股票模拟建仓。
- 能看到仓位、盈亏、止损、止盈、风控触发。

### 阶段 6：策略测试

产出：

- 回测任务 API。
- 回测结果 API。
- 结果展示给前端。

验收：

- 用户能对股票/候选池/板块做策略测试。
- 能看到收益、回撤、胜率、市场环境分段结果。

## 10. 当前需要先确认的点

- 后端是否确定使用 FastAPI。
- 开发期数据库是否先用 SQLite，后续再迁移 PostgreSQL。
- K 线图前端是否接受 Lightweight Charts。
- MVP 是否允许先使用可替换的数据适配器，等数据源确定后再接真实数据。
- 是否需要一开始就做登录，还是先本地单用户。

## 11. 现有设计需要补充的结论

现有 `alphaagent_functional_design.md` 方向正确，但偏产品模块。要真正执行，需要本文件补充的内容：

- 前端页面清单。
- 后端 API 契约。
- vn.py 服务化边界。
- 数据库表草案。
- Claude Code 前端交付说明。
- MVP 分阶段验收标准。

下一步不应该直接写前端，也不应该先做自动交易。下一步应先做后端骨架和股票/指数基础 API，因为“所有 A 股 + 上证指数 + 股票详情”是后续所有能力的地基。
