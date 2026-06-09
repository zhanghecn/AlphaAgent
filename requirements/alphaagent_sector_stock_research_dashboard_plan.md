# AlphaAgent 板块主线与个股投研工作台执行计划

状态：可执行方案，待用户审查后进入实现。  
目标：把当前“能看到真实数据”的 MVP 升级为面向投资用户的 A 股投研工作台：打开板块页能直接发现最近主线、龙头、持续性和关联产业链；打开个股详情能系统看到行情、技术、财务季度历史、主营构成、板块位置、产业链关系和事件证据。  
边界：本计划仍不做智能选股、推荐、交易、回测；不修改 `vnpy/` 和 vn.py Qt 界面；启动、同步、测试、验收全部通过 Docker Compose 完成；不提交、不推送，除非用户明确要求。

## 1. 当前问题

当前 AlphaAgent 已完成真实数据接入的基础闭环，但用户侧体验还不是一个投研平台：

- 板块页偏“搜索工具”，用户不知道有哪些板块时无法直接发现最近 5 日、1 个月、半年、1 年的主线。
- 板块展示缺少主线仪表盘：没有统一的热度、持续性、扩散、资金、涨停情绪、龙头强度和风险指标。
- 板块关系图已有雏形，但主要基于成分股交集，缺少周期强弱、资金共振、涨停共振、新闻/公告关键词和产业链语义证据。
- 产业链不能写死，且当前链路不够直观，用户无法清楚看到上游、中游、下游和每条边的证据。
- 个股详情内容分散，像多个数据块拼在一起，不像一个可连续阅读的投研页。
- 财报没有细化到季度历史，没有趋势图、同比/环比、利润率、资产负债、现金流质量等图表。
- 主营构成没有历史化，无法看到收入结构和毛利结构随报告期变化。
- 新闻、公告、龙虎榜、资金流、热度、板块归属没有和价格、财务、产业链串成证据链。

结论：下一阶段不是继续堆接口，而是重构为两个产品面：

- `板块主线仪表盘`：给用户快速判断“现在市场主线在哪里、强到什么程度、哪些板块相关、龙头是谁、是否扩散或退潮”。
- `个股投研工作台`：给用户快速判断“这家公司做什么、财务趋势如何、属于哪些主线、在产业链哪里、近期有什么事件和资金行为”。

## 2. 强约束

- 不写死任何板块、产业链、股票归属、上中下游模板。
- 不把静态兜底数据伪装成真实数据；数据不足时显示 `unknown`、`partial`、`unavailable` 和缺失原因。
- PostgreSQL 本地库作为历史数据、财报、板块计算、图谱计算的主来源；实时行情可以用 Redis/内存短缓存。
- 所有计算结果必须保留 `source`、`as_of_date`、`computed_at`、`evidence`、`confidence`。
- 产业链关系是“算法推断 + 证据解释”，不是宣称绝对真实供应链。没有供应商/客户证据时，边类型标为 `related_by_membership`、`related_by_keyword`、`related_by_market_comovement`。
- 页面默认给用户答案，不要求用户先搜索。搜索是辅助能力，不是板块页入口的核心。
- Claude Code 只写前端；Codex 负责后端、数据、算法、Docker Compose 验证，并给 Claude Code 足够接口契约。

## 3. 已有基础

当前仓库已有：

- 后端目录：`alphaagent/`
- 前端目录：`frontend/`
- Compose：`docker-compose.yml`
- API：`http://localhost:8000/api`
- Web：`http://localhost:5173`
- 本地 PostgreSQL/Redis 访问方式已在现有配置中使用 `host.docker.internal`。
- 已有表：
  - `stocks`
  - `stock_daily_bars`
  - `sectors`
  - `sector_memberships`
  - `stock_sector_memberships`
  - `stock_business_segments`
  - `sync_sources`
  - `sync_job_definitions`
  - `sync_job_runs`
- 已有接口：
  - `/api/stocks`
  - `/api/stocks/{vt_symbol}`
  - `/api/stocks/{vt_symbol}/bars`
  - `/api/stocks/{vt_symbol}/indicators`
  - `/api/stocks/{vt_symbol}/business`
  - `/api/stocks/{vt_symbol}/sectors`
  - `/api/stocks/{vt_symbol}/industry-chain`
  - `/api/stocks/{vt_symbol}/snapshot`
  - `/api/sectors`
  - `/api/sectors/search`
  - `/api/sectors/{sector_id}/stocks`
  - `/api/sectors/{sector_id}/trend`
  - `/api/industry-chains/graph`
  - `/api/industry-chains/{chain_id}/map`
  - `/api/data-sync/*`

当前不足是：这些数据没有形成“主线发现”和“投研阅读”的产品结构。

## 4. AkShare 本地源码可用数据

已集成源码目录：`third_party/akshare/akshare/`。本阶段优先使用这些真实接口，不新增写死数据。

### 4.1 板块和成分股

- `stock/stock_board_industry_em.py`
  - `stock_board_industry_name_em`
  - `stock_board_industry_spot_em`
  - `stock_board_industry_hist_em`
  - `stock_board_industry_hist_min_em`
  - `stock_board_industry_cons_em`
- `stock/stock_board_concept_em.py`
  - `stock_board_concept_name_em`
  - `stock_board_concept_spot_em`
  - `stock_board_concept_hist_em`
  - `stock_board_concept_hist_min_em`
  - `stock_board_concept_cons_em`

### 4.2 资金、情绪、热度

- `stock_feature/stock_fund_flow.py`
  - `stock_fund_flow_concept`
  - `stock_fund_flow_industry`
  - `stock_fund_flow_individual`
  - `stock_fund_flow_big_deal`
- `stock_feature/stock_ztb_em.py`
  - `stock_zt_pool_em`
  - `stock_zt_pool_previous_em`
  - `stock_zt_pool_strong_em`
  - `stock_zt_pool_zbgc_em`
  - `stock_zt_pool_dtgc_em`
- `stock/stock_hot_rank_em.py`
  - `stock_hot_rank_em`
  - `stock_hot_rank_detail_em`
  - `stock_hot_rank_detail_realtime_em`
  - `stock_hot_keyword_em`
  - `stock_hot_rank_latest_em`
  - `stock_hot_rank_relate_em`
- `stock_feature/stock_lhb_em.py`
  - `stock_lhb_detail_em`
  - `stock_lhb_stock_statistic_em`
  - `stock_lhb_stock_detail_em`
  - `stock_lhb_yybph_em`
  - `stock_lhb_traderstatistic_em`

### 4.3 财报、主营、公告、新闻

- `stock_feature/stock_three_report_em.py`
  - `stock_balance_sheet_by_report_em`
  - `stock_profit_sheet_by_report_em`
  - `stock_profit_sheet_by_quarterly_em`
  - `stock_cash_flow_sheet_by_report_em`
  - `stock_cash_flow_sheet_by_quarterly_em`
- `stock_feature/stock_report_em.py`
  - `stock_zcfz_em`
  - `stock_lrb_em`
  - `stock_xjll_em`
- `stock_feature/stock_yjbb_em.py`
  - `stock_yjbb_em`
- `stock_fundamental/stock_finance_ths.py`
  - `stock_financial_abstract_ths`
  - `stock_financial_abstract_new_ths`
  - `stock_financial_debt_new_ths`
  - `stock_financial_benefit_new_ths`
  - `stock_financial_cash_new_ths`
- `stock_fundamental/stock_finance_sina.py`
  - `stock_financial_abstract`
  - `stock_financial_analysis_indicator`
  - `stock_financial_analysis_indicator_em`
- `stock_fundamental/stock_notice.py`
  - `stock_notice_report`
  - `stock_individual_notice_report`
- `news/news_stock.py`
  - `stock_news_em`

## 5. 产品设计

## 5.1 板块主线仪表盘

路径建议：`/sectors` 保留，但默认内容改为主线仪表盘，不再要求用户先搜索。

默认顶部必须包含：

- 时间周期切换：
  - 今日
  - 3 日
  - 5 日
  - 10 日
  - 20 日
  - 60 日
  - 半年
  - 1 年
- 板块范围切换：
  - 全部
  - 行业
  - 概念
  - 主题
  - 地域
- 排序：
  - 热度
  - 涨幅
  - 成交额
  - 资金净流入
  - 持续性
  - 涨停强度
  - 风险
- 搜索：
  - 支持板块名、概念名、股票代码、股票名。
  - 搜索结果应显示所属板块数量和来源。

默认主体必须包含：

- 主线榜：
  - 板块名
  - 类型
  - 区间涨幅
  - 今日涨幅
  - 成交额
  - 成交额变化
  - 主力净流入
  - 上涨家数 / 下跌家数
  - 涨停家数
  - 龙头股
  - 龙头涨幅
  - 持续天数
  - 热度分
  - 风险标签
  - 成分股总数
- 主线雷达：
  - 动量
  - 宽度
  - 资金
  - 情绪
  - 龙头
  - 持续性
- 热力矩阵：
  - 横轴：区间涨幅
  - 纵轴：成交额/资金强度
  - 点大小：成分股数量或成交额
  - 点颜色：热度分
- 板块关系图：
  - 节点：真实板块。
  - 边：成分股交集、行情共振、资金共振、涨停共振、新闻/公告关键词共现。
  - 点击节点进入板块详情。
  - 点击边显示证据。
- 产业链链路图：
  - 上游 / 中游 / 下游分栏。
  - 每个节点显示相关板块、代表个股、成交额占比、涨幅。
  - 边显示置信度和证据类型。

### 5.1.1 板块详情

路径建议：`/sectors/{sector_id}`。

必须展示：

- 板块摘要：
  - 板块名、类型、成分股数量、数据更新时间。
  - 今日、5 日、10 日、20 日、60 日、半年、1 年涨跌幅。
  - 热度分、持续性、风险状态。
- 历史趋势：
  - 板块 K 线或用成分股加权合成的净值曲线。
  - 成交额趋势。
  - 上涨家数比例趋势。
  - 涨停家数趋势。
  - 资金净流入趋势。
- 成分股表：
  - 股票代码、名称、最新价、今日涨幅、5/10/20/60 日涨幅、成交额、换手率、市值、板块内角色。
  - 可点击涨幅、成交额、换手率排序。
  - 显示总数和当前筛选数量。
  - 搜索能找到该板块内股票，例如后续必须能验证 `亨通光电`、`法拉电子` 的真实板块归属。
- 龙头识别：
  - 涨幅龙头
  - 成交额龙头
  - 持续性龙头
  - 涨停龙头
  - 资金龙头
  - 这些不能写死，用指标计算。
- 相关板块：
  - 强关联、弱关联。
  - 每条关系的原因：共同成分股、共同龙头、资金同步、涨停同步、关键词共现。

## 5.2 个股投研工作台

路径建议：`/stocks/{vt_symbol}` 继续保留，但重构为投研页。

顶部固定摘要：

- 股票名称、代码、交易所。
- 最新价、涨跌幅、成交额、换手率、市值、PE、PB。
- 所属主线标签：
  - 行业
  - 概念
  - 主题
  - 地域
  - 当前最强关联板块
- 风险摘要：
  - 价格偏离
  - 近期涨幅过大
  - 财务恶化
  - 资金流出
  - 数据缺失
- 数据来源状态：
  - 本地库 / 实时源 / fallback / 更新时间。

页面结构建议：

1. `行情与技术`
   - K 线主图。
   - 年份完整显示，不再只显示月份。
   - 均线默认只显示 MA5、MA10、MA20；MA60、MA120、MA250 通过开关显示。
   - 技术指标放在主图下方独立区域：
     - 成交量
     - MACD
     - KDJ
     - RSI
     - BOLL
   - 指标可切换，不把所有线压在主图上。

2. `财务季度趋势`
   - 默认按季度展示最近 12-20 个报告期。
   - 支持季度 / 年度切换。
   - 图表：
     - 营业收入
     - 归母净利润
     - 扣非净利润
     - 毛利率
     - 净利率
     - ROE
     - 资产负债率
     - 经营现金流净额
   - 表格：
     - 报告期
     - 披露日期
     - 收入
     - 净利润
     - 同比
     - 环比
     - 毛利率
     - 净利率
     - ROE
     - 资产负债率
     - 现金流质量

3. `主营构成`
   - 按报告期展示产品/业务/地区构成。
   - 图表：
     - 收入占比堆叠图。
     - 毛利占比堆叠图。
     - Top 业务收入趋势。
   - 显示 `report_date`，不能只显示当前一次。

4. `板块与主线位置`
   - 个股所属真实板块列表。
   - 每个板块显示：
     - 板块热度排名
     - 5/10/20/60 日涨幅
     - 个股在板块内涨幅排名
     - 是否龙头、跟涨、补涨、拖累。
   - 点击板块进入板块详情。

5. `产业链关系图`
   - 显示公司业务线索、所属板块、相关上下游节点。
   - 节点分为：
     - 公司
     - 板块
     - 业务关键词
     - 产业链阶段
   - 边必须有证据：
     - 主营业务文本
     - 主营收入构成
     - 板块成分交集
     - 新闻/公告关键词
     - 市场共振
   - 没有足够证据时显示低置信度，不画成确定链路。

6. `事件与资金`
   - 新闻时间线。
   - 公告时间线。
   - 财报披露。
   - 龙虎榜记录。
   - 资金流。
   - 热度排名。
   - 与 K 线日期联动，点击事件定位到图表附近。

7. `数据可信`
   - 显示每个模块的数据源、同步时间、覆盖率、缺失项。
   - 显示算法解释，不显示工程调试日志。

## 5.3 短线/游资视角必须补齐的资料与功能

板块主线页不能只是财务投研，也要覆盖 A 股短线用户真正关心的市场结构。这里不是做“买入推荐”，而是把主线、情绪、龙头、资金和风险透明展示出来。

### 5.3.1 市场情绪周期

页面应显示：

- 今日涨停数量。
- 今日跌停数量。
- 炸板数量。
- 连板高度。
- 最高连板股。
- 首板数量。
- 二板、三板、四板及以上数量。
- 昨日涨停今日表现。
- 昨日连板今日晋级率。
- 强势股断板后的回撤情况。

用途：

- 判断市场是启动、发酵、高潮、分歧、退潮还是修复。
- 辅助解释板块热度分，而不是只看涨幅。

### 5.3.2 主线强度

每条主线至少要展示：

- 主线板块热度排名。
- 主线内涨停股数量。
- 主线内连板股数量。
- 主线内成交额 Top 股票。
- 主线内涨幅 Top 股票。
- 主线内断板/跌停风险。
- 龙头和补涨梯队。
- 是否从单点龙头扩散到板块多股。

主线状态：

- `seed`：刚出现苗头，少数股异动。
- `emerging`：开始扩散，有明显领涨。
- `mainline`：多股共振，资金和涨停强度都高。
- `climax`：高度一致，短线风险上升。
- `divergence`：分歧，强弱分化。
- `fading`：退潮，宽度下降或资金流出。

### 5.3.3 龙头识别和梯队

龙头不是只按涨幅最大判断。需要把龙头拆成：

- 空间龙头：连板高度最高。
- 趋势龙头：区间涨幅、成交额、趋势持续性最强。
- 容量龙头：成交额足够大，能承接主线资金。
- 情绪龙头：涨停、连板、热度排名、龙虎榜关注度突出。
- 补涨龙头：主线扩散后低位强势股。

每个板块详情页应展示梯队：

- 首板池。
- 二板池。
- 三板及以上。
- 趋势股。
- 大成交额核心股。
- 掉队股。

### 5.3.4 龙虎榜和席位证据

个股详情和板块详情都应接入龙虎榜：

- 个股上榜日期。
- 上榜原因。
- 买入金额、卖出金额、净买入。
- 机构席位、营业部席位。
- 近 1 月/3 月活跃营业部。
- 同一席位在同板块多股出现的情况。

注意：这只作为资金行为证据，不直接推断买卖建议。

### 5.3.5 热度和事件催化

主线和个股都应显示：

- 热度排行。
- 热门关键词。
- 新闻数量趋势。
- 公告事件。
- 财报披露。
- 是否出现同一关键词在多个板块/多只股票共振。

事件需要和价格图、板块热度图联动，用户能看到“这天为什么动”。

### 5.3.6 风险提示

短线强势不等于可靠。必须展示风险，不做单向热度渲染：

- 连续大涨后高位拥挤。
- 板块上涨但宽度下降。
- 龙头继续涨但跟风股退潮。
- 资金净流出但价格上涨。
- 炸板率上升。
- 跌停股增加。
- 财报或公告负面。
- 数据源覆盖不足。

## 6. 数据模型

修改：`alphaagent/server/db/schema.py`。

保留已有表，新增以下表。所有表都要 `source`、`raw`、`created_at`、`updated_at`。

### 6.1 板块历史和评分

`sector_daily_bars`

- `sector_id`
- `trade_date`
- `open_price`
- `close_price`
- `high_price`
- `low_price`
- `volume`
- `turnover`
- `change_pct`
- `source`
- 唯一键：`sector_id + trade_date`

`sector_daily_metrics`

- `sector_id`
- `trade_date`
- `stock_count`
- `rise_count`
- `fall_count`
- `flat_count`
- `limit_up_count`
- `limit_down_count`
- `avg_change_pct`
- `median_change_pct`
- `turnover_weighted_change_pct`
- `market_cap_weighted_change_pct`
- `turnover`
- `main_net_inflow`
- `main_net_inflow_ratio`
- `leader_vt_symbol`
- `leader_name`
- `leader_change_pct`
- `leader_reason`
- 唯一键：`sector_id + trade_date`

`sector_period_scores`

- `sector_id`
- `as_of_date`
- `period`
- `sector_type`
- `return_pct`
- `rank_return`
- `momentum_score`
- `breadth_score`
- `fund_score`
- `sentiment_score`
- `leader_score`
- `continuity_score`
- `risk_penalty`
- `heat_score`
- `trend_state`
- `confidence`
- `evidence`
- 唯一键：`sector_id + as_of_date + period`

### 6.2 关系图和产业链

`sector_relation_edges`

- `as_of_date`
- `period`
- `source_sector_id`
- `target_sector_id`
- `score`
- `shared_stock_count`
- `shared_stock_ratio`
- `jaccard`
- `price_correlation`
- `fund_correlation`
- `limit_up_cooccurrence`
- `keyword_similarity`
- `leader_overlap`
- `evidence`
- `confidence`
- 唯一键：`as_of_date + period + source_sector_id + target_sector_id`

`industry_chain_nodes`

- `id`
- `as_of_date`
- `name`
- `node_type`
- `stage`
- `sector_id`
- `vt_symbol`
- `keywords`
- `metrics`
- `evidence`
- `confidence`

`industry_chain_edges`

- `as_of_date`
- `period`
- `source_node_id`
- `target_node_id`
- `relation_type`
- `score`
- `evidence`
- `confidence`
- 唯一键：`as_of_date + period + source_node_id + target_node_id + relation_type`

### 6.3 财报和主营历史

`stock_financial_reports`

- `vt_symbol`
- `report_date`
- `period_type`
- `publish_date`
- `revenue`
- `revenue_yoy`
- `revenue_qoq`
- `net_profit`
- `net_profit_yoy`
- `net_profit_qoq`
- `deducted_net_profit`
- `gross_margin`
- `net_margin`
- `roe`
- `debt_asset_ratio`
- `operating_cash_flow`
- `cash_flow_quality`
- `source`
- 唯一键：`vt_symbol + report_date + period_type`

`stock_financial_statement_items`

- `vt_symbol`
- `report_date`
- `statement_type`
- `item_code`
- `item_name`
- `value`
- `source`
- 唯一键：`vt_symbol + report_date + statement_type + item_name`

扩展 `stock_business_segments`

- 当前已有 `report_date`，后续必须按报告期保留历史。
- 新增或规范字段：
  - `segment_type`：product/business/region/other
  - `revenue_yoy`
  - `gross_margin`
  - `confidence`

### 6.4 事件、资金和热度

`stock_events`

- `id`
- `vt_symbol`
- `event_date`
- `event_type`
- `title`
- `summary`
- `url`
- `keywords`
- `sentiment`
- `importance`
- `source`
- `raw`

`stock_fund_flows`

- `vt_symbol`
- `trade_date`
- `period`
- `main_net_inflow`
- `main_net_inflow_ratio`
- `super_large_net_inflow`
- `large_net_inflow`
- `medium_net_inflow`
- `small_net_inflow`
- `source`
- 唯一键：`vt_symbol + trade_date + period`

`sector_fund_flows`

- `sector_id`
- `trade_date`
- `period`
- `main_net_inflow`
- `main_net_inflow_ratio`
- `rank`
- `source`
- 唯一键：`sector_id + trade_date + period`

`stock_hot_ranks`

- `vt_symbol`
- `rank_time`
- `rank`
- `rank_change`
- `keywords`
- `source`
- 唯一键：`vt_symbol + rank_time + source`

`stock_lhb_records`

- `vt_symbol`
- `trade_date`
- `reason`
- `buy_amount`
- `sell_amount`
- `net_amount`
- `departments`
- `source`
- 唯一键：`vt_symbol + trade_date + reason`

## 7. 算法设计

## 7.1 板块热度分

输出表：`sector_period_scores`。

周期：`1d`、`3d`、`5d`、`10d`、`20d`、`60d`、`120d`、`250d`。

建议公式：

```text
heat_score =
  0.25 * momentum_score
+ 0.15 * continuity_score
+ 0.15 * breadth_score
+ 0.15 * fund_score
+ 0.12 * sentiment_score
+ 0.13 * leader_score
+ 0.05 * liquidity_score
- risk_penalty
```

各项含义：

- `momentum_score`：板块区间涨幅、相对全 A 和指数的超额收益。
- `continuity_score`：近 N 日上涨天数、回撤幅度、趋势斜率。
- `breadth_score`：上涨家数占比、创新高家数、成分股扩散程度。
- `fund_score`：主力净流入、净流入占成交额、资金排名。
- `sentiment_score`：涨停家数、连板股、炸板率、跌停数反向扣分。
- `leader_score`：龙头涨幅、成交额、市值适配、是否带动成分股扩散。
- `liquidity_score`：成交额和成交额变化，避免小样本板块误判。
- `risk_penalty`：短期涨幅过大、宽度下降、资金背离、龙头断板、样本过少。

趋势状态：

- `MAINLINE_UP`：高热度、高持续、宽度扩散。
- `FAST_UP`：短期急涨，风险较高。
- `ROTATION`：热度中等，关联板块轮动。
- `FADING`：涨幅仍高但宽度/资金下降。
- `WEAK`：弱势。
- `UNKNOWN`：数据不足。

## 7.2 龙头识别

输出在板块详情和个股板块位置中。

单股在板块内的角色：

- `leader`：涨幅、成交额、热度、涨停或持续性排名靠前，且带动板块。
- `volume_leader`：成交额主导。
- `momentum_leader`：区间涨幅主导。
- `limit_up_leader`：涨停/连板主导。
- `follower`：跟随上涨。
- `laggard`：弱于板块。
- `drag`：拖累板块。
- `unknown`：数据不足。

计算因子：

- 个股区间涨幅相对板块均值。
- 个股成交额占板块比例。
- 个股涨停/连板情况。
- 个股资金流。
- 个股热度排行。
- 个股与板块日收益相关性。

## 7.3 板块关系图

输出表：`sector_relation_edges`。

边分数：

```text
relation_score =
  0.35 * constituent_overlap
+ 0.20 * price_correlation
+ 0.15 * fund_correlation
+ 0.10 * limit_up_cooccurrence
+ 0.10 * keyword_similarity
+ 0.10 * leader_overlap
```

证据：

- `shared_stocks`：共同成分股。
- `co_movement`：同周期涨跌相关。
- `fund_sync`：资金流方向同步。
- `limit_up_sync`：同日涨停或连板共振。
- `keyword_match`：板块名、主营、新闻、公告关键词相似。
- `leader_overlap`：同一只股票是多个板块龙头。

注意：

- 新板块出现后，只要同步进入 `sectors` 和 `sector_memberships`，算法自动参与计算。
- 没有任何写死的“半导体包含什么”或“光通信包含什么”。
- 关系图展示的是市场和数据证据下的动态关联，不把弱证据边画成确定产业链。

## 7.4 动态产业链图

产业链图不能靠静态模板，采用“实体抽取 + 关系打分 + 证据解释”。

节点来源：

- 板块名和板块类型。
- 个股主营业务摘要。
- 主营业务分部名称。
- 新闻/公告关键词。
- 热门关键词。
- 成分股共同归属。

阶段推断：

- `upstream`
- `midstream`
- `downstream`
- `service`
- `application`
- `unknown`

阶段不是写死词典决定，而是由以下证据共同推断：

- 主营业务中产品/服务词。
- 板块名称语义。
- 公司所属多个板块的共现结构。
- 新闻公告上下文。
- 价格/资金共振链路。

MVP 可先输出 `stage=unknown` 或低置信度，等证据足够再归类。错误地画确定链路比显示未知更差。

## 8. 后端接口契约

新增路由建议放在：

- `alphaagent/server/api/research_sectors.py`
- `alphaagent/server/api/research_stocks.py`
- `alphaagent/server/api/research_graphs.py`

并在 `alphaagent/server/api/router.py` 注册。

### 8.1 板块主线仪表盘

`GET /api/research/sectors/dashboard?period=5d&type=all&sort=heat&page=1&page_size=50`

返回：

```json
{
  "period": "5d",
  "as_of_date": "2026-06-08",
  "items": [
    {
      "sector_id": "BK1036",
      "name": "示例板块",
      "type": "concept",
      "stock_count": 83,
      "return_pct": 12.31,
      "today_change_pct": 2.18,
      "turnover": 12345678900,
      "main_net_inflow": 123456000,
      "rise_count": 62,
      "fall_count": 18,
      "limit_up_count": 5,
      "leader": {
        "vt_symbol": "600000.SSE",
        "name": "示例股票",
        "change_pct": 10.0,
        "role": "leader"
      },
      "heat_score": 86.4,
      "trend_state": "MAINLINE_UP",
      "risk_tags": ["短期涨幅偏高"],
      "confidence": 0.82,
      "source": "postgresql.sector_period_scores"
    }
  ],
  "summary": {
    "total": 1001,
    "mainline_count": 12,
    "fading_count": 8,
    "data_origin": "local_db"
  },
  "source": "postgresql,alphaagent_sector_scoring",
  "updated_at": "2026-06-08T15:20:00+08:00"
}
```

### 8.2 板块详情

`GET /api/research/sectors/{sector_id}/overview?period=20d`

必须返回：

- 板块基础信息。
- 多周期收益。
- 热度分拆。
- 龙头列表。
- 成分股统计。
- 数据质量。

`GET /api/research/sectors/{sector_id}/timeline?period=60d`

必须返回：

- 板块历史 K 线或合成净值。
- 上涨家数比例。
- 成交额。
- 资金流。
- 涨停家数。
- 热度分时间序列。

`GET /api/research/sectors/{sector_id}/stocks?period=20d&sort=return_pct&q=`

必须返回：

- 成分股列表。
- `total`。
- 角色识别。
- 5/10/20/60 日涨幅。

### 8.3 板块关系图

`GET /api/research/sectors/{sector_id}/relation-graph?period=20d&depth=2`

返回：

```json
{
  "center_sector_id": "BK1036",
  "period": "20d",
  "nodes": [
    {
      "id": "BK1036",
      "name": "示例板块",
      "type": "concept",
      "heat_score": 86.4,
      "return_pct": 12.31,
      "stock_count": 83,
      "stage": "unknown"
    }
  ],
  "edges": [
    {
      "source": "BK1036",
      "target": "BK2048",
      "score": 72.5,
      "relation_types": ["shared_stocks", "co_movement", "fund_sync"],
      "confidence": 0.76,
      "evidence": [
        {"type": "shared_stocks", "value": 18},
        {"type": "price_correlation", "value": 0.82}
      ]
    }
  ],
  "source": "postgresql.sector_relation_edges"
}
```

### 8.4 动态产业链图

`GET /api/research/industry-chain/graph?seed_sector_id=BK1036&period=20d`

返回：

- `nodes`
- `edges`
- `stages`
- `evidence`
- `confidence`
- `unknown_nodes`

如果证据不足，必须返回 `status=partial`，而不是用写死产业链补齐。

### 8.5 个股投研工作台

`GET /api/research/stocks/{vt_symbol}/workbench`

用于页面首屏聚合，避免前端散打多个慢接口。

必须返回：

- `quote`
- `technical_summary`
- `financial_summary`
- `business_summary`
- `sector_position`
- `chain_summary`
- `event_summary`
- `data_quality`

`GET /api/research/stocks/{vt_symbol}/finance/quarterly?limit=20`

返回季度历史：

```json
{
  "vt_symbol": "600000.SSE",
  "period_type": "quarterly",
  "items": [
    {
      "report_date": "2026-03-31",
      "publish_date": "2026-04-29",
      "revenue": 1234567890,
      "revenue_yoy": 12.3,
      "revenue_qoq": -3.2,
      "net_profit": 123456789,
      "net_profit_yoy": 8.1,
      "net_profit_qoq": 2.2,
      "gross_margin": 31.2,
      "net_margin": 9.8,
      "roe": 3.1,
      "debt_asset_ratio": 42.5,
      "operating_cash_flow": 100000000,
      "cash_flow_quality": 0.81
    }
  ],
  "source": "postgresql.stock_financial_reports"
}
```

`GET /api/research/stocks/{vt_symbol}/finance/statements?report_date=2026-03-31`

返回三张表的明细项：

- `balance_sheet`
- `income_statement`
- `cash_flow_statement`

`GET /api/research/stocks/{vt_symbol}/business/history`

返回主营构成历史：

- 按报告期。
- 按 segment_type。
- 收入、收入占比、毛利、毛利率。

`GET /api/research/stocks/{vt_symbol}/sector-position?period=20d`

返回该股在所属板块中的位置：

- 所属板块。
- 板块热度。
- 个股板块内排名。
- 个股角色。
- 对板块贡献。

`GET /api/research/stocks/{vt_symbol}/chain-graph?period=20d`

返回个股产业链关系图。

`GET /api/research/stocks/{vt_symbol}/events?types=news,notice,lhb,fund,hot&limit=100`

返回事件时间线。

## 9. 数据同步任务

修改：

- `alphaagent/server/services/data_sync.py`
- `alphaagent/data_sources/akshare_adapter.py`
- `alphaagent/server/api/data_sync.py`
- `alphaagent/server/db/schema.py`

新增任务定义：

### 9.1 P0：板块主线必需

- `sync_sector_daily_bars`
  - 拉取行业/概念板块历史 K 线。
  - 默认最近 250 个交易日。
- `sync_sector_fund_flows`
  - 拉取行业/概念资金流。
  - 周期：即时、3 日、5 日、10 日、20 日。
- `sync_limit_up_pools`
  - 拉取涨停、强势、炸板、跌停池。
  - 用于情绪指标。
- `compute_sector_daily_metrics`
  - 基于 `sector_memberships`、`stock_daily_bars`、涨停池、资金流计算每日指标。
- `compute_sector_period_scores`
  - 计算 1/3/5/10/20/60/120/250 日主线评分。
- `compute_sector_relation_edges`
  - 计算板块关系图。

### 9.2 P1：个股投研必需

- `sync_stock_financial_quarterly`
  - 拉取利润表/资产负债表/现金流季度数据。
- `sync_stock_financial_indicators`
  - 拉取 ROE、毛利率、净利率、资产负债率等指标。
- `sync_stock_business_segments_history`
  - 拉取主营构成历史，不只最新一期。
- `sync_stock_news`
  - 拉取个股新闻。
- `sync_stock_notices`
  - 拉取个股公告。
- `sync_stock_fund_flows`
  - 拉取个股资金流。
- `sync_stock_hot_ranks`
  - 拉取个股热度。
- `sync_stock_lhb_records`
  - 拉取龙虎榜。
- `compute_stock_sector_positions`
  - 计算个股在板块内的角色和排名。
- `compute_stock_chain_graph`
  - 计算个股产业链证据图。

### 9.3 调度建议

- 交易时段：
  - 行情快照：实时源短缓存 10-30 秒。
  - 板块 spot 和成分股：1-3 分钟。
  - 资金、热度：3-10 分钟。
- 收盘后：
  - 全量日 K、板块 K、板块评分、关系图：每日一次。
- 夜间：
  - 财报、主营、公告、新闻、龙虎榜：每日一次。
- 首次初始化：
  - 全 A 股票清单。
  - 全板块清单。
  - 全板块成分。
  - 全 A 最近 2 年日 K。
  - 板块最近 1 年历史。
  - 财报先同步核心股票池，再扩展到全 A。

公网免费源存在限速和失败，首次全量不能假设几分钟完成。估算：

- 全 A 近 2 年日 K：约 5000+ 只股票、每只约 480 条，约 240 万行，保守需要数小时。
- 财报和主营：个股级接口多，建议先同步全部股票最近 8-12 个季度，再后台补齐更久历史。
- 页面必须优先使用本地已有数据，缺口异步补齐，不能让用户等待全量完成才可打开。

## 10. 前端给 Claude Code 的开发契约

Claude Code 应修改 `frontend/`，不改后端，不改 `vnpy/`。

建议新增依赖：

- `@xyflow/react`：关系图和产业链图。
- `recharts`：财务、热度、趋势图。
- 保留 `lightweight-charts`：K 线。
- 保留 `shadcn/ui`、`Tailwind CSS`、`lucide-react`。

### 10.1 页面

新增或重构：

- `frontend/src/pages/SectorsPage.tsx`
  - 改成主线仪表盘入口。
- `frontend/src/pages/SectorDetailPage.tsx`
  - 新增板块详情。
- `frontend/src/pages/StockDetailPage.tsx`
  - 重构为投研工作台。

新增 API 文件：

- `frontend/src/api/researchSectors.ts`
- `frontend/src/api/researchStocks.ts`
- `frontend/src/api/researchGraphs.ts`

新增功能组件：

```text
frontend/src/features/research-sectors/
  SectorPeriodTabs.tsx
  SectorHotTable.tsx
  SectorHeatMap.tsx
  SectorMomentumRadar.tsx
  SectorTrendChart.tsx
  SectorRelationGraph.tsx
  SectorLeaderPanel.tsx
  SectorConstituentTable.tsx

frontend/src/features/research-stocks/
  StockResearchHeader.tsx
  StockTechnicalWorkspace.tsx
  StockFinanceQuarterChart.tsx
  StockFinanceStatementTable.tsx
  StockBusinessHistoryChart.tsx
  StockSectorPositionPanel.tsx
  StockChainGraph.tsx
  StockEventTimeline.tsx
  StockDataQualityPanel.tsx
```

### 10.2 前端展示规则

- 板块页默认展示主线榜，不显示“先搜索”空态。
- 所有表格必须显示 `total`、当前筛选数量、排序状态。
- 涨幅、热度、资金、成交额字段必须可排序。
- 图表必须显示完整年份日期，不能只有月份。
- K 线主图不能堆太多均线，默认 MA5/MA10/MA20，其他由开关控制。
- 技术指标必须在下方分区，不放进主 K 线造成拥挤。
- 财报默认季度图，不是只显示最新一期文字。
- 产业链图边上必须能看到证据和置信度。
- 数据不足时显示“缺少什么数据、哪个任务可补齐”，不能显示假内容。

## 11. 实施任务

### Task 1：补齐 AkShare adapter

文件：

- 修改：`alphaagent/data_sources/akshare_adapter.py`
- 测试：`tests/alphaagent/test_akshare_adapter.py`

内容：

- 增加板块历史 K 线方法。
- 增加板块资金流方法。
- 增加涨停池方法。
- 增加个股新闻、公告、资金流、热度、龙虎榜方法。
- 增加季度财报和三张表方法。
- 每个方法都返回统一字段，不让 API 直接依赖中文列名。
- 所有方法设置 timeout、缓存和异常包装。

验收：

- `python -m pytest tests/alphaagent/test_akshare_adapter.py -q`
- fake DataFrame 能通过字段映射测试。
- 源接口失败时抛出明确的 `AkShareSourceError` 或返回 `status=unavailable`，不吞错成空真实数据。

### Task 2：新增 PostgreSQL 表

文件：

- 修改：`alphaagent/server/db/schema.py`
- 测试：`tests/alphaagent/test_config.py` 或新增 `tests/alphaagent/test_schema.py`

内容：

- 新增第 6 节表。
- 增加必要索引：
  - `sector_id + trade_date`
  - `as_of_date + period + heat_score`
  - `vt_symbol + report_date`
  - `vt_symbol + event_date`
- `create_schema(engine)` 必须幂等。

验收：

- Docker Compose 后端启动后自动创建表。
- 重复启动不报错。

### Task 3：同步任务扩展

文件：

- 修改：`alphaagent/server/services/data_sync.py`
- 修改：`alphaagent/server/api/data_sync.py`
- 测试：`tests/alphaagent/test_api.py`

内容：

- 注册第 9 节新增任务。
- 任务支持 `stock_limit`、`sector_limit`、`date_range`、`periods`、`symbols` 参数。
- 任务必须幂等 upsert。
- 任务运行记录必须显示 `rows_read`、`rows_written`、`message`。

验收：

- `POST /api/data-sync/jobs/{job_id}/run` 能触发。
- `/api/data-sync/runs` 能看到运行结果。
- `/api/data-sync/coverage` 或 `/api/data-sync/usage` 显示新表覆盖率。

### Task 4：板块评分算法

文件：

- 新建：`alphaagent/server/services/research_sector_scores.py`
- 测试：`tests/alphaagent/test_sector_scores.py`

内容：

- 输入板块历史、成分股行情、资金流、涨停池。
- 输出 `sector_daily_metrics` 和 `sector_period_scores`。
- 实现热度分、趋势状态、风险标签、龙头识别。
- 单元测试使用小样本固定数据验证排名和扣分逻辑。

验收：

- 强势板块样本得分高于弱势板块。
- 资金背离样本有风险标签。
- 样本不足返回 `UNKNOWN`，不伪造分数。

### Task 5：板块关系图算法

文件：

- 新建：`alphaagent/server/services/research_sector_graph.py`
- 测试：`tests/alphaagent/test_sector_graph.py`

内容：

- 基于本地库计算板块边。
- 支持按周期计算。
- 支持解释 evidence。
- 和现有 `/api/industry-chains/graph` 的成分股交集算法合并或复用，但新增资金、涨停、价格相关、关键词证据。

验收：

- 两个共同成分股多、走势相关高的板块边分数更高。
- 没有共同证据的板块不强行连边。
- 新增板块只要入库即可参与计算。

### Task 6：动态产业链图算法

文件：

- 新建：`alphaagent/server/services/research_chain_graph.py`
- 测试：`tests/alphaagent/test_chain_graph.py`

内容：

- 从主营、板块、新闻公告、成分关系抽取节点。
- 输出上游/中游/下游/未知阶段。
- 给每条边 evidence 和 confidence。
- 证据不足时不画确定链路。

验收：

- 对只有板块证据的数据返回 `partial`。
- 对有主营分部和板块共现的数据能生成公司-业务-板块链路。
- 不包含任何固定行业模板。

### Task 7：个股财报和投研服务

文件：

- 新建：`alphaagent/server/services/research_stock_profile.py`
- 新建：`alphaagent/server/api/research_stocks.py`
- 测试：`tests/alphaagent/test_stock_research_api.py`

内容：

- 聚合个股行情、技术、财务、主营、板块、产业链、事件。
- 提供季度财务 API。
- 提供三张表 API。
- 提供主营历史 API。
- 提供事件时间线 API。

验收：

- `/api/research/stocks/{vt_symbol}/workbench` 1 次请求可支撑首屏。
- `/finance/quarterly` 返回多季度历史。
- 财报缺失时返回空数组和缺失说明，不报 503。

### Task 8：板块研究 API

文件：

- 新建：`alphaagent/server/api/research_sectors.py`
- 新建：`alphaagent/server/api/research_graphs.py`
- 修改：`alphaagent/server/api/router.py`
- 测试：`tests/alphaagent/test_sector_research_api.py`

内容：

- 实现第 8 节接口。
- API 优先读本地库。
- 不直接在请求中跑重型计算；缺计算结果时返回 `status=stale` 或触发后台任务。

验收：

- `/api/research/sectors/dashboard?period=5d` 返回板块列表。
- `/api/research/sectors/{sector_id}/relation-graph` 返回 nodes/edges/evidence。
- `/api/research/industry-chain/graph` 返回动态图。

### Task 9：Claude Code 前端开发文档

文件：

- 修改：`requirements/claude_frontend_brief.md`

内容：

- 增加本计划第 10 节的页面和组件契约。
- 增加第 8 节 API TypeScript 类型。
- 明确不要自行调用 AkShare 或外部网站。
- 明确 shadcn/ui + Tailwind + React + TypeScript + Vite。

验收：

- Claude Code 可以只读文档和接口契约完成页面。

### Task 10：前端实现与 Playwright 验收

文件：

- 修改：`frontend/src/pages/SectorsPage.tsx`
- 新建：`frontend/src/pages/SectorDetailPage.tsx`
- 修改：`frontend/src/pages/StockDetailPage.tsx`
- 新增第 10 节组件。

验收命令：

```bash
npm run build --prefix frontend
docker compose up --build
```

Playwright 有头测试：

- 打开 `http://localhost:5173/sectors`。
- 默认看到主线榜、周期切换、热力图、关系图入口。
- 点击 5 日、20 日、半年、1 年能切换数据。
- 点击涨幅、热度、资金列能排序。
- 搜索 `亨通光电` 能看到真实所属板块入口。
- 搜索 `法拉电子` 能看到真实所属板块入口。
- 打开任意个股详情，能看到季度财报图、主营历史图、板块位置、产业链关系图、事件时间线。
- 浏览器 console 无错误。

## 12. Docker Compose 验收

必须由 Codex 自己完成，不让用户参与调试。

后端测试：

```bash
python -m pytest tests/alphaagent -q
```

前端构建：

```bash
npm run build --prefix frontend
```

Compose 启动：

```bash
docker compose up --build
```

API smoke：

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/ready
curl "http://localhost:8000/api/research/sectors/dashboard?period=5d"
curl "http://localhost:8000/api/research/stocks/600000.SSE/workbench"
```

数据任务 smoke：

```bash
curl -X POST http://localhost:8000/api/data-sync/jobs/sync_sector_daily_bars/run
curl -X POST http://localhost:8000/api/data-sync/jobs/compute_sector_period_scores/run
curl -X POST http://localhost:8000/api/data-sync/jobs/sync_stock_financial_quarterly/run
curl http://localhost:8000/api/data-sync/runs
```

性能目标：

- 本地库已有数据时，板块仪表盘 API P95 小于 1 秒。
- 个股 workbench 首屏聚合 API P95 小于 1.5 秒。
- 重型同步和关系图全量计算不在用户请求线程执行。

## 13. 最终验收标准

本阶段完成后，用户打开系统应能做到：

- 不知道板块名，也能直接看到最近 5 日、1 个月、半年、1 年的强势板块。
- 能看出一个板块是短期急涨、持续主线、轮动、退潮还是弱势。
- 能看到板块龙头是谁、为什么是龙头、板块内有多少成分股。
- 能搜索股票并看到它属于哪些真实板块，以及这些板块当前强不强。
- 能在板块关系图里看到哪些板块联动，边的证据是什么。
- 能在产业链图里看到上游、中游、下游或未知阶段，且知道每条关系的证据和置信度。
- 能打开个股详情看到季度财报历史图，不只是最新一期文字。
- 能看到主营构成历史和收入/毛利占比变化。
- 能把价格、技术、财务、业务、板块、产业链、事件串起来阅读。
- 没有任何写死板块、写死产业链或写死股票归属。
- 数据不足时系统明确告诉用户缺什么、来自哪个同步任务，而不是展示假内容。
