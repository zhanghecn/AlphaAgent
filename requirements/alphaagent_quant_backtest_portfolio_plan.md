# AlphaAgent 量化选股、回测与持仓模块执行计划

状态：P0/P1/P2 主闭环已实现并测试；P3 已完成一个严格分钟真实模拟回测，长区间分钟线和官方 vn.py A 股插件仍待补齐。
日期：2026-06-10
目标：把用户关于“洗盘、试探、财报改善、弱市抗跌、尾盘 5 日线低吸”的投资想法，转成 AlphaAgent 可计算、可回测、可解释、可模拟持仓的系统模块。
边界：本计划不承诺识别真实“主力意图”，只识别可观测市场信号；不修改 `vnpy/` 核心包和官方 examples；实盘下单不进入本阶段。

## 0. 2026-06-11 执行状态

已实现：

- 后端 API：`/api/quant`、`/api/backtests`、`/api/portfolio`、`/api/simulation`、`/api/vnpy/status`。
- 量化信号：相对强弱、洗盘代理、趋势质量、板块主线、财务改善、资金流/热度/龙虎榜代理、流动性和风险评分。
- 回测：每日滚动选股、A 股整数手、手续费/印花税/滑点、止损/止盈/移动止盈/时间止损、订单/成交/净值落库、CSV 导出和扩展报告。
- 分钟线入场：`stock_minute_bars` 表、`sync_stock_minute_bars` 任务、D+1 尾盘窗口接近 MA5 的分钟成交尝试；缺分钟时明确标记为 `daily_next_open_fallback`，也可用 `minute_entry_required=true` 强制拒绝缺分钟成交。
- 历史分钟线导入：`GET /api/data-sync/imports/minute-bars/template.csv` 提供模板，`POST /api/data-sync/imports/minute-bars` 支持从 CSV 导入外部 1 分钟 K 线，参数为 `csv_text`、`interval`、`source`、`dry_run`，用于补严格尾盘回测缺口。
- 大文件导入：`POST /api/data-sync/imports/minute-bars` 也支持 `file_path`，只允许读取 `data/imports/` 或 `memory/06_backtests/` 下的 `.csv` 文件，并按批流式写入，适合 XT/RQData/券商导出的大型分钟线文件。
- 历史分钟线缺口审计：`POST /api/data-sync/imports/minute-bars/audit-gaps` 可检查缺口 CSV 在 `stock_minute_bars` 中的尾盘窗口覆盖；`POST /api/data-sync/imports/minute-bars/gap-template.csv` 可按缺口生成待填分钟线模板。
- 大文件缺口审计：`POST /api/data-sync/imports/minute-bars/audit-gaps` 支持 `file_path`，适合审计放在 `data/imports/` 下的外部缺口 CSV；旧回测原始 CSV 已合并到报告后从 `memory/06_backtests/` 移除。
- 持仓：默认分组、自选加入、量化候选自动入池、自动模拟持仓、持仓展示买入时间/买入价/成本/推荐 id/买入理由/卖出信息。
- 财报：利润表字段、披露日、扣非净利润、经营现金流和现金流质量字段映射/落库；回测只使用披露日已到的数据。
- 前端：`/quant` 工作台展示推荐、回测、报告、导出、持仓和 vn.py 状态；回测参数可切换宽松日线开盘回退或严格分钟尾盘成交模式。
- vn.py 适配：`/api/vnpy/local-bars` 可把 AlphaAgent 本地日线查询转换为 vn.py `HistoryRequest`/`BarData` 语义，供本地研究和后续策略适配使用。
- vn.py 数据库分钟线导入：`POST /api/vnpy/import-minute-bars` 可从当前 vn.py 数据库配置读取 `Interval.MINUTE` BarData 并写入 AlphaAgent `stock_minute_bars`，用于 DataManager/Datafeed 已下载分钟线后的严格尾盘回测。
- vn.py 缺口批量导入：`POST /api/vnpy/import-minute-bars/gaps` 可按严格尾盘缺口 CSV 批量从 vn.py 数据库读取对应 D+1 尾盘窗口 1 分钟 BarData，导入后返回覆盖审计；`/quant` 页面已提供按缺口预检查/导入按钮。
- Tushare Pro 缺口导入：`POST /api/data-sync/imports/minute-bars/tushare-gaps` 可在配置 `TUSHARE_TOKEN` 且账号有 `stk_mins` 分钟数据权限时，按严格缺口批量请求 D+1 尾盘窗口历史分钟线；返回行会按目标交易日强过滤，避免错期分钟线写入。
- TDX 公共行情缺口导入：`POST /api/data-sync/imports/minute-bars/tdx-gaps` 可按严格缺口从通达信公开行情服务器批量读取历史 1 分钟 K 线；公开源回溯范围有限，但已可补 2026-05 至 2026-06 的严格尾盘缺口。
- 严格分钟流水线：`POST /api/backtests/strict-minute-pipeline` 会先审计缺口覆盖，只有审计 `ready` 才强制 `minute_entry_required=true`、`persist=true` 运行严格回测并返回报告/CSV 文件名；缺口未覆盖时返回 `blocked_by_minute_gaps`，不会跑出伪严格回测。
- 严格缺口导出：`GET /api/backtests/{backtest_id}/minute-gaps.csv` 可把 `minute_entry_required=true` 回测中被 `tail_entry_not_triggered` 拒绝的买入订单导出为标准分钟缺口 CSV，供 TDX/Tushare/vn.py/外部 CSV 补数。
- 供应商补数清单：`POST /api/data-sync/imports/minute-bars/vendor-manifest` 和 `.csv` 可从严格缺口生成最小 symbol-date 补数清单，包含 `vt_symbol`、Tushare `ts_code`、交易日、14:30-14:57 窗口、AlphaAgent 导入列说明。

验证：

- `uv run pytest tests/alphaagent -q`：164 passed, 1 skipped, 1 warning。
- `npm run build`：通过，仅 Vite chunk 体积警告。
- `uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db`：通过。
- 服务烟测：筛选、推荐、自动模拟、持仓、回测报告、vn.py 状态可返回。
- vn.py 本地适配烟测：`/api/vnpy/local-bars` 对 `600000.SSE` 返回 `ALPHAAGENT_LOCAL` 日线 BarData 语义数据。

最新回测：

- 严格分钟真实模拟回测 12：`memory/06_backtests/2026-06-11_backtest_12_strict_tdx_minute_report.md`
- 原始回测 CSV 已合并清理；关键指标保留在 `memory/06_backtests/2026-06-11_backtest_12_strict_tdx_minute_report.md`。
- 区间：2026-02-02 至 2026-06-11。
- 补数：TDX 公开行情按回测 11 缺口导入 5376 根真实 1 分钟线；缺口审计 192/192 覆盖，覆盖率 100%。
- 指标：总收益 6.60%，最大回撤 -2.22%，胜率 62.96%，盈亏比 2.77，Sharpe 2.42。
- 成交真实性：买入 30 笔，30 笔均为 D+1 14:30-14:57 真实分钟尾盘 MA5 成交，日线开盘回退 0 笔。
- 严格参数网格：54 组合全部正收益，收益区间 6.08% 至 10.86%；默认参数排名 41/54，Walk-forward 只有 1 折，只能作为短区间初步检查。原始 CSV 已合并清理，结论保留在回测 12 报告。

- `memory/06_backtests/2026-06-11_backtest_9_report.md`
- 宽松回测 9 原始 CSV 已合并清理，结论保留在 `memory/06_backtests/2026-06-11_backtest_9_report.md`。
- 指标：总收益 44.64%，最大回撤 -6.87%，胜率 53.67%，盈亏比 1.87，Sharpe 3.04。

严格尾盘回测：

- 严格尾盘回测 10 原始 CSV 已合并清理，结论保留在 `memory/06_backtests/2026-06-11_backtest_10_strict_tail_report.md`。
- 参数：同区间、1500 标的、`minute_entry_required=true`，不允许 D+1 开盘回退。
- 指标：总收益 0%，平仓交易 0，分钟尾盘成交 0。
- 结论：当前分钟线覆盖不足，尾盘 MA5 低吸规则已实现并可强制验证，但还不能得到真实有效的历史胜率。
- 缺口清单：794 条缺口订单，覆盖 101 个交易日、194 只股票；原始 CSV 已合并清理，关键范围保留在严格分钟就绪报告。
- 缺口审计：当前数据库只覆盖 2/794 个严格尾盘缺口，覆盖率 0.2519%，仍缺 792 个订单窗口。
- vn.py SQLite 审计：当前 `/root/.vntrader/database.db` 的 `dbbardata`、`dbtickdata` 均为 0 行；按缺口从 vn.py 数据库 dry-run 只处理 10 个缺口时读取 0 行、写入 0 行、返回 `empty`，不能补齐严格尾盘回测。
- 公共分钟源复核：EastMoney 分钟 K、Sina 分钟 K 对 2026-01-08 缺口样本仍返回 2026-06-10/11 近端数据；Sina 历史逐笔 JSON 对 2026-01-08 返回 0 条，只对 2026-06-11 当日样本有数据。因此公共源不能补严格历史分钟缺口。
- Tushare 当前环境审计：未配置 `TUSHARE_TOKEN`，`tushare-gaps` dry-run 返回 `unavailable`，尚不能直接补数。
- 严格流水线当前实测：旧缺口样本返回 `blocked_by_minute_gaps`，缺口 794、覆盖 2、缺失 792、覆盖率 0.2519%；未运行新严格回测。原始缺口 CSV 已合并清理，需要时从接口重新导出。
- 供应商补数清单当前实测：同一缺口文件生成 794 条 symbol-date 请求，覆盖 194 只股票、101 个交易日，区间 2026-01-08 至 2026-06-11，窗口 14:30-14:57。
- TDX 当前环境实测：回测 11 缺口共 192 个 symbol-date，TDX dry-run 可取 5376 行，正式导入 5376 行，审计 ready 后严格流水线生成回测 12；原始缺口 CSV 已合并清理。

仍需补齐：

- 历史分钟线覆盖不足；宽松回测 9 有 0 笔真实分钟尾盘成交、181 笔买入回退到 D+1 开盘，严格回测 10 因不允许回退而 0 笔成交。
- 当前公共 EastMoney 1 分钟接口请求历史日期仍返回最近日期，不能用于补 2026-01 至 2026-06 历史分钟回测；代码已增加日期过滤，防止误写区间外数据。
- 已提供外部历史分钟 CSV 导入和缺口审计入口，但当前仓库尚未导入覆盖回测区间的真实历史分钟数据；严格尾盘胜率和收益仍需补数后重跑。
- 已提供按缺口从 vn.py 数据库批量导入的入口，但当前 vn.py SQLite 也没有历史分钟/ Tick 数据；需要先通过 DataManager/Datafeed/Gateway 或外部 CSV 把真实历史 1 分钟数据写入 vn.py/AlphaAgent。
- 已提供按缺口从 Tushare Pro `stk_mins` 导入的入口，但当前没有 token/分钟权限；配置后可先 dry-run 小批量缺口，确认 `rows_read > 0` 且审计覆盖提升后再正式导入。
- 财报现金流全量同步不稳定，当前只有部分 `publish_date` 和经营现金流覆盖。
- 1500 标的大样本 54 组合参数网格已完成并导出，54 组均为正收益，92.59% 跑赢样本等权，高摩擦组 100% 正收益；但当前参数不是网格最优，不能把单次回测指标当作稳健收益承诺。
- 官方 vn.py A 股数据/交易插件仍未安装配置，尚未完成 A 股券商实盘接入。
- `/api/vnpy/local-bars` 只是 AlphaAgent 本地数据到 vn.py 对象的适配，不替代 `vnpy_xt`、`vnpy_rqdata`、`vnpy_tushare` 或 A 股 Gateway。

## 1. 需求结论

这组需求方向是合适的，但必须拆成四层：

1. 数据层：全 A 行情、指数、板块、财报、资金流、交易日历和除权复权数据。
2. 信号层：把“主力洗盘”“偷偷试探”等主观描述转成可观测代理指标。
3. 回测层：按历史每个交易日重新选股和交易，统计真实可执行表现。
4. 持仓层：支持用户分组、自选加入、量化自动加入、实时展示和买卖触发条件。

不能直接做成：

- 系统断言“主力正在洗盘”。
- 先用今天选出的股票，再回头统计这些股票过去涨没涨。
- 只看胜率，不看盈亏比、回撤、交易次数、换手、样本量。
- 只用日线却声称已经验证了“尾盘低吸”。

## 2. 当前项目能力与缺口

### 2.1 已有基础

当前仓库已经具备：

- `alphaagent/` 后端包。
- PostgreSQL 表和 API 的基础骨架。
- 股票、日 K、板块、成分股、财报、主营构成、板块评分、产业链图谱相关表和服务。
- `vnpy_ctabacktester` 已安装，可用于单标的 CTA 风格策略回测。
- `vnpy/alpha` 本地模块存在，可用于因子研究和数据集管理，但不能把外部 Web 请求中的表达式直接交给它执行。
- DataManager、SQLite、CTA Strategy、CTA Backtester 已安装，可作为 vn.py 官方路径参考。

### 2.2 当前缺口

当前还缺：

- A 股官方 vn.py 数据插件：`vnpy_xt`、`vnpy_rqdata`、`vnpy_tushare` 未安装。
- A 股交易 Gateway：`vnpy_xtp`、`vnpy_tora`、`vnpy_ost`、`vnpy_emt` 未安装。
- 多标的组合策略插件：`vnpy_portfoliostrategy` 未安装。
- 本地仿真交易插件：`vnpy_paperaccount` 未安装。
- ScriptTrader 和 DataRecorder 未安装。
- 推荐、回测、模拟持仓、持仓分组的 AlphaAgent 业务表和 API 尚未实现。
- 财报数据必须确认是否有披露日期，回测不能用未来才披露的数据。
- “尾盘到 5 日线附近低吸”需要分钟级行情，日线只能做近似验证。

## 3. vn.py 在本模块中的角色

vn.py 不负责直接给用户推荐股票。AlphaAgent 应在 vn.py 之上做业务编排。

推荐使用方式：

- `Datafeed`：后续接入正规历史行情数据源。
- `Database`：保存历史 K 线/Tick，供回测和初始化使用。
- `HistoryRequest`、`BarData`：统一历史行情对象语义。
- `CtaBacktester`：验证单标的买卖规则、交易成本、成交撮合。
- `PortfolioStrategy`：后续安装后用于多股票组合调仓策略。
- `PaperAccount`：后续安装后用于接实时行情的本地仿真交易。
- `MainEngine` 和 Gateway：未来连接券商、订阅实时行情、实盘下单。

AlphaAgent 自建：

- 全 A 选股评分。
- 股票池和黑名单。
- 财报改善评分。
- 弱市抗跌评分。
- 洗盘/试探代理信号。
- 推荐解释。
- 组合级回测编排。
- Web 持仓分组和模拟账户。

## 4. 用户信号的量化定义

### 4.1 “主力在洗盘准备拉升”

不能当作事实，只能命名为 `washout_setup_signal`。

可观察代理条件：

- 前置趋势：近 20 日或 60 日相对指数/行业有明显超额收益。
- 回调形态：从近 N 日高点回撤不深，例如 5%-15%，未破关键中期趋势。
- 缩量：回调阶段成交量低于前期上涨阶段，例如 5 日均量低于 20 日均量。
- 均线支撑：收盘价靠近 MA5/MA10/MA20，且 MA20/MA60 不明显向下。
- 板块未退潮：所属主线板块热度和持续性没有大幅下降。
- 风险约束：不是连续一字板后高位巨量开板，不是跌停附近弱势反抽。

输出：

- `washout_score`: 0-100。
- `washout_status`: `candidate`、`weak`、`invalid`、`insufficient_data`。
- `evidence`: 缩量、回撤、均线、相对强度、板块状态。

### 4.2 “主力偷偷试探”

不能当作事实，只能命名为 `probe_signal`。

日线代理条件：

- 成交量异常放大，但收盘不大跌。
- 盘中突破近 20 日高点或关键压力位，收盘回落但没有破位。
- 上影线较长但换手和成交额明显增加。
- 次日或后续 3 日没有连续放量下跌。

分钟线增强条件：

- 盘中快速拉升后回落。
- 回落后价格仍在 VWAP 或关键均线附近。
- 尾盘资金没有明显砸盘。

输出：

- `probe_score`: 0-100。
- `probe_type`: `breakout_probe`、`volume_probe`、`intraday_probe`。
- `requires_minute_data`: 是否需要分钟数据才能确认。

### 4.3 财报累积、现金流逐步变好

这是优先级排序项，不作为强制过滤，命名为 `financial_improvement_score`。

指标：

- 营收同比、环比改善。
- 净利润同比、环比改善。
- 扣非净利润改善。
- 经营现金流连续改善。
- 经营现金流 / 净利润质量提升。
- 毛利率、净利率、ROE 稳定或改善。
- 资产负债率不过高。

回测要求：

- 必须按财报披露日生效，而不是按报告期末日期生效。
- 若缺披露日期，先把财务分标记为 `display_only`，不能进入真实回测。

### 4.4 近期 1-2 个月大盘弱，股票依旧坚挺

命名为 `relative_strength_score`。

指标：

- 20/40/60 日个股收益 - 指数收益。
- 20/40/60 日个股收益 - 所属行业/板块收益。
- 下跌日捕获率：指数下跌日里，个股平均跌幅更小或逆势上涨。
- 最大回撤小于指数/行业。
- 价格仍在 MA20/MA60 之上，或快速收复。

输出：

- `rs_20d`、`rs_40d`、`rs_60d`。
- `downside_capture`。
- `drawdown_vs_index`。
- `market_weak_resilience_score`。

### 4.5 趋势方向和季度利润大方向

命名为 `trend_quality_score`。

指标：

- 股价趋势：MA5、MA20、MA60 排列和斜率。
- 板块趋势：所属主线板块 20/60 日强度。
- 财务趋势：最近季度收入、利润、现金流同比明显改善。
- 估值风险：高估值但业绩没有跟上时扣分。

输出：

- `price_trend_score`。
- `sector_trend_score`。
- `fundamental_trend_score`。
- `trend_quality_score`。

### 4.6 尾盘到 5 日线附近低吸

命名为 `ma5_late_pullback_entry`。

真实分钟级规则：

- 时间窗口：14:30-14:57。
- 当前价距离 MA5 在可接受区间，例如 -0.5% 到 +1.5%。
- 当天不是高开低走放量大阴线。
- 当天没有跌停、临近跌停、异常停牌风险。
- 当天成交额满足流动性下限。
- 所属板块没有明显退潮。

日线 MVP 近似规则：

- 信号日收盘价接近 MA5。
- 信号只能在收盘后生成。
- 回测买入价使用下一交易日开盘价或带滑点的成交价。
- 不能声称已验证“尾盘买入”，只能称为“日线近似回测”。

## 5. 第一版评分模型

第一版先用透明加权模型，不做黑盒机器学习。

总分建议：

```text
total_score =
  0.25 * relative_strength_score
  0.20 * washout_score
  0.15 * trend_quality_score
  0.15 * sector_mainline_score
  0.10 * financial_improvement_score
  0.10 * liquidity_score
  0.05 * risk_adjustment_score
```

说明：

- 财务改善不是强制条件，但分高时提升排序。
- 风险不是加分项，实际实现时更适合做扣分和硬拦截。
- 所有权重必须版本化，写入 `strategy_version`，回测时不能随意漂移。

硬过滤：

- ST、退市整理、严重财务异常。
- 最近 N 日长期停牌或数据缺失。
- 成交额低于阈值。
- 上市时间太短，缺少足够历史数据。
- 当天涨停无法买入、跌停无法卖出的交易约束。
- 用户黑名单。

## 6. 买入和卖出规则

### 6.1 买入规则

MVP 日线规则：

1. 交易日 D 收盘后计算全 A 信号。
2. 选出 `total_score` 排名前 N，且满足风控。
3. 若触发 `ma5_pullback_entry_daily_proxy`，则在 D+1 用开盘价加滑点模拟买入。
4. 若 D+1 一字涨停或停牌，则记录为无法成交。

分钟线增强规则：

1. 交易日 D 盘中 14:30 后实时计算 MA5 距离和盘口约束。
2. 符合尾盘低吸条件后，用下一分钟或可成交价格模拟买入。
3. 成交记录必须保留触发时间、触发价格、滑点、数据延迟。

### 6.2 卖出规则

第一版卖出规则：

- 硬止损：买入后亏损达到 5%-8%，或跌破关键均线。
- 趋势失效：收盘跌破 MA10/MA20 且板块热度下降。
- 反弹止盈：盈利达到 12%-20% 后分批止盈。
- 移动止盈：从持仓最高价回撤 6%-10%。
- 时间止损：买入后 10-20 个交易日没有按预期上涨。
- 板块退潮：所属主线板块热度、宽度、资金和龙头强度明显下降。
- 财务/公告风险：重大负面公告或财报不及预期。

### 6.3 A 股交易约束

回测和模拟必须考虑：

- T+1。
- 100 股整数手。
- 涨跌停无法自由成交。
- 停牌不可交易。
- 手续费、印花税、过户费。
- 滑点。
- 前复权/后复权一致性。
- 成交额和换手不足时的容量限制。

## 7. 回测真实性要求

### 7.1 正确回测方式

必须按历史交易日滚动执行：

```text
for 每个交易日 D:
  只读取 D 当天收盘前已经可见的数据
  计算市场状态、板块状态、股票信号、财报状态
  生成候选池
  生成 D+1 或尾盘可执行订单
  按成交规则撮合
  更新持仓、止损、止盈、现金和净值
```

不能：

- 用今天的股票池回测过去。
- 用未来财报、未来板块成分、未来 ST 状态。
- 用收盘价触发后又按同一根 K 线低点买入。
- 优化几十个参数后只展示最优结果。

### 7.2 必须输出的指标

回测结果必须包含：

- 总收益率、年化收益。
- 最大回撤。
- 胜率。
- 盈亏比。
- Profit Factor。
- 平均盈利、平均亏损。
- 交易次数、样本量。
- 平均持仓天数。
- 换手率。
- 夏普比率或收益波动比。
- 与上证指数、沪深 300、中证 500/1000 对比。
- 牛市、熊市、震荡市、结构性行情分段表现。
- 最差 10 笔交易和失败原因。
- 未成交订单数量和原因。

### 7.3 防过拟合要求

第一版必须做：

- 固定默认参数，不先做大规模参数寻优。
- 按年份切分训练/验证/测试。
- 至少做 2020-2022、2023-2024、2025-至今分段对比。
- 做参数敏感性测试，例如 MA5 距离、止损幅度、持仓天数上下浮动。
- 做随机股票池或基准策略对照，确认不是市场整体上涨带来的假效果。
- 分行业/板块输出，避免只在某个热点阶段有效。

## 8. 持仓与分组设计

### 8.1 持仓分组

建议内置分组：

- `自选观察`：用户手动加入。
- `量化候选`：系统每日筛出的候选，不代表买入。
- `自动模拟持仓`：系统按策略模拟买入后的持仓。
- `短线低吸`：符合尾盘低吸/回踩均线逻辑。
- `趋势跟踪`：趋势持续但未到低吸点。
- `长期质量`：财务和现金流改善明显。
- `已卖出复盘`：卖出后保留复盘。
- `黑名单`：用户或风控禁止。

用户可以：

- 新建、改名、删除分组。
- 手动把股票加入任意分组。
- 给分组设置备注和风控偏好。
- 允许或禁止量化结果自动加入该分组。

### 8.2 量化自动持仓

默认不能直接进入真实账户，只能进入：

- 量化候选。
- 自动模拟持仓。
- 等待人工确认的计划订单。

自动加入规则：

- 每日筛选后，Top N 加入 `量化候选`。
- 符合买入规则时，加入 `自动模拟持仓` 并生成模拟交易。
- 若用户打开“自动模拟买入”，才实际生成模拟持仓。
- 若用户未来打开“实盘自动下单”，必须再加人工确认和交易风控。

### 8.3 持仓显示字段

持仓页至少显示：

- 股票代码、名称、交易所。
- 所属分组。
- 当前价、涨跌幅、更新时间。
- 持仓数量、可用数量。
- 成本价、现价、市值。
- 浮动盈亏、盈亏比例。
- 买入日期、买入原因、信号版本。
- 止损价、止盈价、移动止盈价。
- 距 MA5/MA10/MA20 的距离。
- 所属板块热度和是否退潮。
- 当前建议动作：持有、观察、减仓、止损、止盈、禁止加仓。
- 下一触发条件：例如“跌破 MA10 且板块热度低于 50 卖出”。

实时显示依赖：

- 有实时行情源时，使用最新 quote。
- 无实时行情源时，显示最近同步行情，并明确 `updated_at`。
- 不允许把旧行情伪装成实时行情。

## 9. 后端模块设计

建议新增目录：

```text
alphaagent/
  server/
    api/
      quant.py
      backtests.py
      portfolios.py
      simulation.py
    services/
      quant/
        universe.py
        factors.py
        signals.py
        scoring.py
        recommendation.py
      backtest/
        engine.py
        broker.py
        metrics.py
        regimes.py
      portfolio/
        groups.py
        holdings.py
        risk.py
      simulation/
        account.py
        orders.py
        fills.py
```

### 9.1 数据表草案

新增表：

- `quant_strategy_templates`
- `quant_signal_runs`
- `quant_stock_signals`
- `quant_recommendations`
- `backtest_runs`
- `backtest_daily_equity`
- `backtest_trades`
- `backtest_orders`
- `backtest_metrics`
- `portfolio_groups`
- `portfolio_group_items`
- `simulation_accounts`
- `simulation_orders`
- `simulation_trades`
- `simulation_positions`
- `risk_events`

字段原则：

- 所有信号必须有 `trade_date`、`vt_symbol`、`strategy_version`、`score`、`evidence`。
- 所有回测必须有 `data_as_of_policy`，说明如何处理财报和未来数据。
- 所有推荐必须保留 `reason` 和 `invalid_conditions`。
- 所有持仓必须保留 `source`: `manual`、`quant_auto`、`simulation`、`broker`。

### 9.2 API 草案

量化：

```http
POST /api/quant/screen-runs
GET /api/quant/screen-runs/{run_id}
GET /api/quant/signals?trade_date=YYYY-MM-DD
GET /api/quant/recommendations?trade_date=YYYY-MM-DD
GET /api/quant/recommendations/{id}
```

回测：

```http
POST /api/backtests
GET /api/backtests
GET /api/backtests/{backtest_id}
GET /api/backtests/{backtest_id}/metrics
GET /api/backtests/{backtest_id}/trades
GET /api/backtests/{backtest_id}/equity
```

持仓：

```http
GET /api/portfolio/groups
POST /api/portfolio/groups
PATCH /api/portfolio/groups/{group_id}
DELETE /api/portfolio/groups/{group_id}
GET /api/portfolio/groups/{group_id}/items
POST /api/portfolio/groups/{group_id}/items
DELETE /api/portfolio/groups/{group_id}/items/{vt_symbol}
GET /api/portfolio/holdings
GET /api/portfolio/holdings/{holding_id}
```

模拟交易：

```http
GET /api/simulation/accounts
POST /api/simulation/accounts
GET /api/simulation/accounts/{account_id}/positions
POST /api/simulation/accounts/{account_id}/orders
GET /api/simulation/accounts/{account_id}/trades
GET /api/simulation/accounts/{account_id}/risk-events
```

## 10. MVP 阶段划分

### P0：日线信号和真实回测闭环

目标：

- 不依赖分钟数据。
- 不做自动实盘。
- 先验证策略是否有统计价值。

产出：

- 股票池过滤。
- 相对强度、财务改善、趋势、板块主线、洗盘代理信号。
- 日线近似 MA5 低吸信号。
- 全 A 每日滚动选股。
- 日线组合回测。
- 回测指标、交易明细、失败案例。

验收：

- 能选择时间范围运行回测。
- 能看到胜率、收益、回撤、盈亏比和交易明细。
- 能解释每笔买入为什么发生。
- 能明确标注这是日线近似，不是尾盘分钟级低吸。

### P1：持仓分组和量化候选自动入池

产出：

- 持仓分组 API。
- 手动加入股票。
- 每日量化 Top N 自动加入 `量化候选`。
- 推荐详情页显示买入/卖出触发条件。

验收：

- 用户能自选加入分组。
- 量化候选不会覆盖用户手动分组。
- 每个自动加入的股票都能看到原因和过期时间。

### P2：模拟账户和自动模拟持仓

产出：

- 模拟账户。
- 模拟订单、成交、持仓。
- 成本价、盈亏、止损止盈展示。
- 策略触发后自动生成模拟买入/卖出。

验收：

- 能从推荐股票一键模拟买入。
- 系统能按规则自动卖出。
- 持仓页能实时或准实时显示行情和盈亏。

### P3：分钟级尾盘低吸和 vn.py 插件增强

前提：

- 有可靠分钟级 A 股行情。
- 或安装并配置支持分钟数据的正规 Datafeed/Gateway。

产出：

- 14:30-14:57 尾盘信号。
- 分钟级撮合回测。
- 接入 `vnpy_portfoliostrategy` 或自研组合回测与 vn.py 对齐。
- 可选接入 `vnpy_paperaccount` 做实时行情下本地仿真。

验收：

- 能验证“尾盘到 5 日线附近低吸”的真实可执行表现。
- 回测记录有分钟时间戳和成交价。
- 和日线近似结果分开展示。

## 11. 还需要补充或确认的问题

实现前需要确认：

- 首选数据源：继续用当前 AkShare 适配器做 MVP，还是先接 `vnpy_xt`、`vnpy_rqdata`、`vnpy_tushare`。
- 是否接受 P0 先只做日线近似。
- 回测时间范围：建议至少从 2020-01-01 到当前最近交易日。
- 交易成本默认值：佣金、印花税、滑点、最低手续费。
- 股票池范围：是否排除北交所、科创板、创业板、ST、新股。
- 单票最大仓位、总持仓数量、板块集中度。
- 财报缺披露日时，是否先不进入回测，只用于展示排序。
- 自动持仓默认只做模拟，不做真实下单。

## 12. 推荐执行顺序

下一步不应直接写“主力洗盘策略”实盘交易。

建议顺序：

1. 补齐数据质量检查：行情、指数、板块、财报披露日期、停牌/涨跌停。
2. 实现 P0 日线信号引擎。
3. 实现 P0 回测引擎和指标。
4. 用 2020 至今做分段回测，判断策略是否有统计价值。
5. 再做持仓分组和模拟账户。
6. 最后接分钟级尾盘低吸和 vn.py 组合/仿真插件。

这个顺序能最快回答核心问题：这套选股逻辑过去是否真的有效，在哪些行情里有效，在哪些行情里会亏。
