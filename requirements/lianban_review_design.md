# 连板复盘（每日归档）设计文档

日期：2026-08-13
状态：一期已上线（2026-08-14 验收通过）
参考：https://lianban.net/days/2026-08-13.html（已抓取完整页面存档分析）

## 1. 目标与范围

对标 lianban.net 每日复盘页，建设 AlphaAgent 的「连板复盘」产品：

- **每日一页**：每个交易日一份复盘，长期归档留存，日期可自由切换回看
- **今日实时**：交易日盘中滚动更新（live 涨停池），盘后落库定版
- **功能界面对齐**：统计卡、连板天梯、梯队接力、炸板、热点题材、人气龙头、情绪周期、归档导航

### 范围确认（2026-08-13 与用户确认）

- 对齐边界：`days` 每日复盘页 + 独立连板天梯历史页（二期）
- 一期：数据基建（涨停池落库 + 日线重建梯队 + 晋级率统计）+ 复盘页核心模块
- 二期：连板天梯历史页（跨日期演变/晋级率矩阵）、明日推演（同景统计）、竞价雷达
- 三期（可选）：AI 助手、实时快讯、驱动逻辑 AI 文案、信号面
- 页面位置：新顶层路由 `/lianban`，侧栏「连板复盘」入口

## 2. 已验证的关键事实（2026-08-13 实测）

### 数据源铁证

- 东财涨停池五接口（akshare `stock_ztb_em`）已接入适配器：涨停池 zt、昨日涨停
  zt_previous、强势股 strong、炸板池 zbgc、跌停池 dtgc
- 实测 08-13 东财：涨停 59 / 炸板 36 / 跌停 4 / 连板 22 / 最高 5 板，
  与 lianban 页面五项**完全一致** → lianban 数据源即东财涨停池口径（非 ST）
- 涨停池字段齐全：首次/最后封板时间、连板数、封板资金、炸板次数、
  涨停统计（"13/9"=13天9板）、所属行业

### 约束

- 东财涨停池只保留约 **3 周**历史（实测 07-27 有 111 行，07-13 为空）
  → 「近一年晋级率」必须由自有日线重建
- 涨停池当前只走实时缓存，**每日盘后没落库**（关键缺口）

### 日线涨停判定对账（08-12，东财 92 只）

- 东财池**不收录 ST**（92 只中 0 只 ST）→ 默认口径排除 ST，可开关
- 开开实业（close=high=17.27, pct=10.00，铁定涨停）东财漏收 → 日线口径更全
- ST 规则实证修正：创业板/科创板 ST = 20%（非 5%）；存在 ST 股当日按 10%
  交易的切换日（ST金鸿 pct=9.89%）
- 修正后判定规则（精确命中原则）：收盘价**恰好等于**某档理论涨停价才算涨停；
  超过 5% 档价自动升 10% 档判定。对账准确率 ≥98%，残余差异可解释、可监控
- **2026-08-14 追加（北交所舍入实证）**：主板/创业板/科创板涨停价 round 四舍五入
  （半值进位实证：2.205→2.21、1.785→1.79）；北交所分位向下截断
  （浩淼科技 11.49×1.3=14.937→实盘 14.93，round 得 14.94 会越 30% 限制）。
  修正后 08-12 对账 92/92 平。

### 现有数据资产（全部已入库并持续更新）

| 资产 | 覆盖 | 用途 |
|---|---|---|
| stock_daily_bars | 1993→今 460 万行 | 涨停重建/涨跌家数/新高新低/成交额 |
| stock_minute_bars | 35M 行 | 封板时间交叉验证（备用） |
| sectors + memberships | 1003 板块 / 8.7 万成员 | 题材归类 |
| stock_fund_flows / sector_fund_flows | 2 个月起累积 | 主线资金强度、主力动向 |
| stock_auction_snapshots | 07-13 起累积 | 竞价雷达（二期） |
| stock_hot_ranks | 06-11 起累积 | 人气龙头榜 |
| stock_lhb_records | 05-13 起累积 | 龙虎榜（页面复用） |
| mainline_sentiment_history | 每日预计算 | 情绪周期阶段 + 温度 |

## 3. 数据层设计（一期核心）

### 3.1 新表 `limit_up_pool_snapshots`（东财五池每日归档）

```
trade_date date, pool_type text(zt/zbgc/dtgc/zt_previous/strong),
vt_symbol text, name, close_price, change_pct, turnover_rate, volume_ratio,
limit_amount(封板资金), first_limit_time, last_limit_time,
break_count(炸板次数), limit_stat_days int, limit_stat_boards int  -- "13/9"解析
limit_up_count int(连板数), industry(东财所属行业), amount(成交额), raw jsonb,
source, updated_at
PK: (trade_date, pool_type, vt_symbol)
```

### 3.2 新表 `stock_limit_up_daily`（日线重建全历史连板序列）

```
trade_date date, vt_symbol text,
is_limit_up bool, limit_up_count int,      -- 连板递推
is_one_word bool,                           -- 一字板 open=high=low
is_st bool, board text,                     -- 板块档 main/cyb/kcb/bse
limit_price float, prev_close float,
close_price float, change_pct float,
touched_limit bool                          -- 盘中摸板未封(炸板候选)
PK: (trade_date, vt_symbol)
索引: (trade_date), (vt_symbol, trade_date)
```

- 全历史一次性重建（460 万行日线递推，实测 ~8 分钟，103,963 行）
- 每日增量：日线同步后只算当日（读昨状态续推；完整日闸门 count>=3000 防部分覆盖）
- 晋级率统计直接 SQL：近 250 交易日分板位晋级频率

### 3.3 涨停判定器规则（实证定稿）

```
幅度档: 创业板(300/301) 20% (2020-08-24 前 10%) | 科创板(688/689) 20%
        北交所(8/4/920) 30% | 主板 10% | 主板 ST 5%
判定:   close 精确命中理论涨停价(容差 1e-6)
舍入:   主板/创业/科创 round;北交所分位截断(见 §2 实证)
升档:   主板 ST 候选 (5%,10%),close 超 5% 档价未命中 10% 档价 → 不涨停
一字板: open == high == low == close
排除:   新股无昨收日;默认统计口径排除 ST(对齐东财/lianban),保留 is_st 开关
```

### 3.4 同步任务（挂统一批量档 eod_1900）

| 任务 | 位置 | 说明 |
|---|---|---|
| `rebuild_stock_limit_up_daily` | sync_stock_daily_bars 之后 | 增量重建当日连板状态 |
| `sync_limit_up_pool_snapshots` | rebuild 之后 | 当天五池落库，幂等；池不可用跳过保留旧数据 |
| `sync_margin_balance` | 链尾部 | 融资余额（akshare macro_china 批量接口） |
| `backfill_limit_up_pool_snapshots` | 手动 | 东财窗口内回补（近 3 周） |

对账：`parity_report`（东财 vs 日线名单 diff）挂数据健康，major_diff → warning。

## 4. 服务与 API

服务包 `alphaagent/server/services/lianban/`：
`detector.py`(判定)/`rebuild.py`(重建)/`archive.py`(落库)/`backfill.py`(回补)/
`parity.py`(对账)/`margin.py`(融资)/`ladder.py`(梯队)/`promotion.py`(晋级率)/
`review.py`(聚合)/`review_cache.py`(版本戳缓存)/`known_streaks.py`(妖股验证)

API：
- `GET /api/lianban/review?date=` — 单页全量 payload
  - 历史日/已定版今日 → 归档(final)；历史超东财窗口 → 日线口径(rebuild)
  - 今日未定版且北京时间 09:25-15:30 → live（实时池，两道闸：时间闸+快照指纹闸）
  - 缺省日期：工作日优先今日（归档→live→回落最近日标 fallback_from）；周末直接最近日
- `GET /api/lianban/dates` — 可复盘日期列表（归档∪重建，降序 limit 400）
- 进程缓存：历史日期 payload 按「日期+两表 max(updated_at) 版本戳」缓存，
  跨进程数据变更自动失效；live/今日 final 不缓存

关键口径：
- **封板率** = zt/(zt+zbgc)（实测 59/95=62.1% 与 lianban 一致）
- **题材分组**：一期用归档行 `industry`（东财二级行业）；龙头 = 组内连板最高，
  同板位首封最早，标 ★
- **「反·N天M板」** = `limit_stat_boards > limit_up_count`（lianban 6 案例反推验证）
- **昨涨停今表现**：zt_previous 名单 × 今日日线 change_pct → 均值/中位/翻红率；
  逐只状态 = 今日在 zt（晋级）/ zbgc（炸板）/ 其他（断板）
- **情绪周期**：读 mainline_sentiment_history 当日 point（phase_label + score）

## 5. 前端 `/lianban` 页面（一期模块，对齐 lianban days 页）

1. 页头：日期+星期、模式徽标（live 盘中滚动/final 已收盘定版/rebuild 历史归档）、
   日期导航（←前一天 / 日期下拉 / 已是最新）、六指数条
2. 统计卡 ×12：涨停(昨)/连板(昨)/最高板(昨)/跌停(昨)/封板率(昨)/炸板(昨)/
   昨涨停今表现(均值·中位·翻红)/情绪周期(阶段·温度)/涨跌家数(红盘比)/
   63日新高新低/两市成交/融资余额(T-1)
3. 连板天梯：五日接力矩阵 + 板位分档（家数、今日 X进Y 实际、明日晋级率≈近250日频率）；
   个股：首封时间（早盘红）、名称链接、反·N天M板、一字徽标、题材标签；1板档折叠
4. 梯队接力：昨日各板位个股今日表现（晋N板/炸板/涨幅）；首板晋级率+历史均值
5. 炸板列表：首封时间+炸板次数，流式
6. 热点题材：分组卡（编号+名称+家数+★龙头+个股按首封时间），8 组折叠
7. 人气龙头榜：热榜 Top10（as_of+排名+连板徽标+涨幅+关键词）
8. FAQ 7 条（当日数据直答）+ 归档导航
9. 设计系统 v3.1 终端蓝；零动画；tabular-nums 数字；涨跌红绿语义色

## 6. 实时 / 历史双模式与性能

- **live 模式**：交易日 09:25-15:30，实时池（适配器 TTL 缓存），前端 30s 轮询；
  两道闸防「昨日快照冒充今日 live」：时间闸 + 名单指纹闸（与最近归档日完全一致→回落）
- **整理中**：收盘后~19:00 归档前，live 口径（指纹闸通过=当日完整数据）
- **定版模式**：读归档；历史页目标 P95 < 100ms（缓存命中实测 70-95ms）
- 晋级率统计随 rebuild 后版本戳自动刷新

## 7. 准确性保障

1. 判定器 19 个单测（分档/精确命中/ST 切换日/一字板/新股/四舍五入边界/北交所截断）
2. 08-12 对账用例固化；每日 parity 对账进数据健康
3. 妖股抽查：天普股份 15 连板/ST中迪 22 连板/秦安股份 5 连板容器一键验证全过
4. 完整日闸门（count>=3000）防日线部分失败烧入错误 streak
5. 涨停池 unavailable 保留旧数据；归档免截断（per_pool_limit=None）+ 截断告警

## 8. 二期

连板天梯历史页（跨日期演变、晋级率矩阵、分板位统计曲线）；明日推演（情绪阶段+
年线同景统计）；竞价雷达（四因子）；📅N天标记口径对齐；题材粒度归并（东财二级行业
→ lianban 式行业+概念混合题材）评估

## 9. 三期（可选）

AI 助手（走 newapi 网关）、实时快讯（财联社电报评估）、题材驱动逻辑 AI 文案、自研信号面

## 10. 验收记录（2026-08-14 主控执行）

### lianban.net 08-13 逐项对账结果

**精确一致（硬指标，16 项）**：涨停 59/连板 22/最高 5板/跌停 4/封板率 62.1%/炸板 36
及全部昨日对比；天梯五档家数 1/6/2/13/37；炸板名单逐只（安通控股 09:25封炸2 等）；
人气榜首位（太极实业）；首板晋级当日 16%(12/75)；反包徽标（一鸣食品反·13天9板、
惠天热电反·6天3板、誉衡药业反·5天4板、江河集团反·4天3板、德龙汇能反·10天6板）；
FAQ 数据直答。

**微差项（口径差异，可解释）**：
- 炸板(昨)：13 vs 12 → 封板率(昨) 87.6% vs 88.5%（同源，差 1 只炸板口径）
- 昨涨停表现 +0.9%/-1.6%/42.9% vs +1.2%/-1.5%/44%（供应商口径差）
- 情绪：冰点期 39° vs 退潮期 40°（各自自研模型；温度同弱市区间）
- 涨跌家数 1136/4319 vs 1100/4091（含 ST/北交所范围差）
- 63日新高新低 49/8 vs 110/17（收盘口径 vs 疑似盘中 high 触线口径）
- 成交 2.57 vs 2.55 万亿；融资 2.64万亿+94亿 vs 2.65万亿+95亿（变化量几乎一致）
- 明日晋级率：近 250 日无条件 vs lianban「同阶段」口径，差 1-9 点、方向一致
- 4板档今日晋级 83%(5/6) vs lianban 85%：分母差 1 只（蓝盾光电本地日线缺口）

### 部署事故与根治（重要教训）

`docker cp` 补丁在 `docker compose up`（依赖重建）后丢失——更糟的是 recreate 回旧镜像后，
**旧镜像代码启动时 ensure_sync_schema → create_schema → drop_legacy_product_tables
把 limit_up_pool_snapshots DROP 了两次**（旧 LEGACY_TABLES 含同名旧表）。
根治：正式重建镜像（`docker compose build alphaagent-api alphaagent-web`），
任何后续 compose 操作不再有旧代码炸弹。**部署清单：改后端后必须重建 api 镜像，
不能只 cp。**

### 数据资产现状

- limit_up_pool_snapshots：15 个交易日五池归档（东财窗口内全量），eod_1900 每日续
- stock_limit_up_daily：1993-2026 全历史 103,963 行（涨停 62k+摸板 40k+）
- 妖股验证：天普 15/ST中迪 22/秦安 5 全部精确复现
- 双口径对账 parity 已挂数据健康（major_diff → warning）

### 遗留项（二期/跟进）

1. ~30 只股票日线同步停更（蓝盾光电 07-24、兆日科技 07-29 等，疑逐股拉取持续失败）
   —— 既有 sync 健康问题，parity 会持续暴露
2. 上证50/北证50 指数未同步（INDEX_SYMBOLS 不含）→ 指数条这两格 "--"
3. 题材粒度归并（东财二级行业 → lianban 式混合题材）二期评估
4. 盘中实时演练待交易日实际观察（live 路径已有时间闸+指纹闸，6 项单测覆盖；
   首板页同通道 30s 轮询已验证）
5. 炸板(昨) 差 1 只的口径（12 vs 13）可在二期对齐
