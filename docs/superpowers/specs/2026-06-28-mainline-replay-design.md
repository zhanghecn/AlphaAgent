# 主线回放（Mainline Replay）设计文档

- 日期：2026-06-28
- 状态：已与用户确认设计决策，进入实现（阶段1）
- 关联：合并并替代现有 `/explore`（主线探索）与 `/chain`（产业链）

## 1. 背景与目标

### 1.1 现状问题
- **产业链页 `/chain`**：基于成分股重叠做关联（`industry_chains.py` 的 `build_sector_relation_graph`，权重为 成分股重叠`72%` + Jaccard`18%` + 名称相似`7%` + 共振`3%`），本质是"概念相关性图谱"，与行情脱节、不存历史、点进去看不到"为什么相关"。用户反馈"一点用没有"。
- **主线探索 `/explore`**：后端 `sync_sector_period_scores` 每个工作日 18:00 EOD 已计算并持久化板块多维评分到 `sector_period_scores` 表（`heat_score`/`fund_score`/`trend_state` 等，覆盖自 2025-03-26），但前端只展示当日实时排名，**历史评分未被利用**。

### 1.2 目标
做一个"主线历史回放 + 资金流向 + 大盘行情 + 产业关联反推"的复盘/监控页面：
- 拖时间轴回到任意交易日，看那天主线板块排名、大盘走势、资金强弱。
- 点板块弹出"从行情反推"的关联板块，解释关联原因。
- 选区间 [T1,T2] 精准计算这段的涨跌 / 成交额 / 热度 / 资金强弱变化。

## 2. 设计决策（已与用户确认）

| 决策点 | 选择 |
|---|---|
| 主战场 | 双视图（今日实时 tab + 历史回放 tab） |
| 主线维度 | 板块即主线，产业链→关联叠加层 |
| 关联交互 | 侧滑关联面板（列表模式为主）+ 网络图探索模式 |
| 页面布局 | 经典三栏（左主线榜 / 中大盘+资金 / 右详情） |
| 落地策略 | 渐进式 MVP（方案 A），分阶段交付 |
| 算法硬指标 | 能精准计算区间 [T1,T2] 的流入流出 / 涨跌 / 热度变化 |

## 3. 架构总览

### 3.1 新页面 `/replay`
```
/replay
├─ 顶部  [①今日实时 | ②历史回放] 双视图 tab
│        历史回放 tab → 时间轴（可拖单日 + 可框选区间 T1→T2 算 delta）
├─ 左栏  主线板块榜（按选中日期取 heat_score 排序，显示涨跌/资金热度）
├─ 中栏  大盘·那天 K 线 + 资金流（单日柱 / 区间 delta 双模式）
├─ 右栏  板块详情（成分股/龙头）+ 🔗关联面板（行情反推，点板块弹）
└─ 关联面板  [列表模式 | 网络图模式] 可切换
```

### 3.2 后端新增 API（复用现有数据，不新增采集）
- `GET /api/replay/timeline` → 可回放的交易日列表（`sector_period_scores` 中存在的 `as_of_date` 去重降序）
- `GET /api/replay/snapshot?date=&t1=&t2=` → 单日快照（仅 `date`）或区间 delta（`t1`+`t2`）
- `GET /api/replay/relation?sector_id=&date=` → 行情反推的关联板块 TOP-N

路由注册于 `alphaagent/server/api/router.py`，逻辑置于 `alphaagent/server/api/replay.py`（新增）。

### 3.3 页面整合
`/explore` 与 `/chain` 的功能收进 `/replay`；旧路由重定向到 `/replay` 对应视图。

## 4. 核心算法（用户重点关注）

### 4.1 区间变化（delta）计算

> 记号：下文 `norm(x)` 表示对该指标在当日全市场所有板块上做 **min-max 归一化到 `[0,1]`**（消除量纲，使指标可跨板块比较）。

对选定区间 `[T1, T2]`（交易日，T1<T2；T1=T2 时退化为单日快照）和板块 `s`：

**A. 行情维度（数据源 `sector_daily_bars`，历史约 2 年，全程精准）**
- 区间涨跌幅：`return_pct = close(T2)/close(T1) - 1`
- 区间累计成交额：`sum(turnover for d in [T1,T2])`
- 放量比：`avg(turnover[T1,T2]) / avg(turnover[T0,T1])`，`T0` 为前等长区间
- 资金聚集度：`sum(turnover_s) / sum(turnover_全市场)`

**B. 热度维度（数据源 `sector_period_scores`，自 2025-03-26，全程精准）**
- 热度变化：`delta_heat = heat_score(T2) - heat_score(T1)`
- 资金热度变化：`delta_fund = fund_score(T2) - fund_score(T1)`
- 趋势状态迁移：`trend_state(T1) → trend_state(T2)`
- 排名变化：`rank(T2) - rank(T1)`

**C. 主力净流入维度（数据源 `sector_fund_flows`，仅近端）**
- 若 `[T1,T2]` 全段落入近端逐日数据：`累计主力净流入 = sum(main_net_inflow)`
- 否则：标记 `fund_inflow_available=False`，**不输出虚构数值**

**D. 综合"资金强弱信号"（核心输出，全程可用，不依赖拉不到的净流入历史）**
```
fund_strength = 0.30*norm(return_pct) + 0.30*norm(放量比) + 0.25*norm(delta_fund) + 0.15*norm(delta_heat)
```
> 论据：成交额（真实成交量×价格）+ 涨跌幅 + 热度分变化历史齐全且真实，比"主力净流入"（数据有水分、且远端拉不到）更稳健。主力净流入降级为近端辅助。

### 4.2 关联反推算法（"从行情反推"）

对板块 `s` 在日期 `d`，找最关联板块：
1. **候选集**：与 `s` 有成分股重叠的板块（`sector_memberships`）∪ 当日热度 TOP 板块。
2. **逐候选 `c` 计算特征**（窗口 `[d-20, d]`）：
   - 涨跌共振：`corr = pearson(daily_return_s, daily_return_c)`，数据 `sector_daily_bars.change_pct` —— 主权重
   - 资金共振：`fund_corr = corr(fund_score_s, fund_score_c)`，数据 `sector_period_scores`
   - 成分股重叠：`overlap = |members(s)∩members(c)| / |members(s)∪members(c)|`（Jaccard）
3. **综合关联度**：
```
relation_score = 0.55*norm(corr) + 0.25*norm(fund_corr) + 0.20*overlap
```
4. **输出** TOP-N 关联板块，每个带 `relation_score` + 关联原因（共振系数 / 重叠股数）。
5. **历史化**：关联基于"日期 `d` 前 20 日"行情实时算，回放到任意 `d` 都能得到"那天的关联"，无需预存快照。

> 对比旧算法：去掉不可靠的"名称相似"，把"涨跌共振"提为主权重（`3%→55%`），真正实现"从行情反推"。

## 5. 数据流

```
sector_period_scores ─┐
sector_daily_bars ────┼─→ replay.py 算法层 ─→ 3 个 API ─→ /replay 前端
大盘指数(stock_daily_bars)┤      (delta + relation)
sector_memberships ───┘
sector_fund_flows(近端) ─→ 仅近端精确净流入，远端 fund_score 代理
```

资金流分级展示策略（前端）：近端日期显示真实主力净流入柱；远端日期显示 `fund_score` 热度代理曲线并标注"资金热度代理（非精确净流入）"。

## 6. 可测试流程（用户强调"保证正确"）

### 6.1 后端算法单元测试（pytest，TDD：先写测试）
- **delta 计算**：构造已知 `sector_daily_bars`/`sector_period_scores` 固定夹具，断言 `return_pct`、`累计成交额`、`fund_strength` 数值；断言远端区间 `fund_inflow_available=False`。
- **关联反推**：构造两个高共振板块，断言 `relation_score` 高且排序靠前；构造不相关板块，断言 `relation_score` 低；断言 `relation_score ∈ [0,1]`。
- **边界**：T1=T2（单日退化为快照）、空数据、窗口不足 20 日、成分股为空。
- **数据真实性**：snapshot/relation 返回值必须来自真实表查询，断言无硬编码常量、无随机值（用固定随机种子或确定性输入）。

### 6.2 API 契约测试
- `timeline`/`snapshot`/`relation` 请求参数与响应 schema 校验；非法日期、越界、空库的优雅降级。

### 6.3 端到端验证（真实数据）
- 启动服务，取库中一个已知有 `sector_period_scores` 的真实日期，curl 三个 API，人工核对主线榜/大盘/资金/关联合理性。

### 6.4 前端验证
- Playwright 或手动：拖时间轴→数据随日期变化；点板块→关联面板弹出且含关联原因；切区间→中栏切 delta 模式。

## 7. 错误处理与降级
- 空库 / 无评分数据：timeline 返回空列表，前端显示"暂无回放数据，请先同步 `sync_sector_period_scores`"引导（复用 `/data` 空库引导模式）。
- 单板块缺日线/缺评分：snapshot 对该板块返回 `null` 字段并标注，不阻断整体。
- 远端资金流缺失：`fund_inflow_available=False`，前端切换代理展示。
- 关联窗口不足：退化为可用长度，`relation_score` 标注置信度。

## 8. 分阶段交付计划

- **阶段1（本次实现，可演示）**
  - 后端：3 个 API + delta 计算 + 关联反推算法 + pytest 单元测试。
  - 前端：`/replay` 历史回放 tab + 时间轴 + 三栏 + 关联面板（列表模式）+ 区间 delta 中栏模式。
  - 数据：复用现有表，不新增采集。
  - 验证：pytest 全绿 + 真实日期端到端 curl + 前端可交互。
- **阶段2**：今日实时 tab（复用 `/explore` 现有实时 ranking API，套同一三栏）。
- **阶段3**：关联网络图探索模式（复用项目已有 `@xyflow/react`）+ 时间轴区间框选 UI + 主线轮动带状图。
- **整合**：`/explore`、`/chain` 旧路由重定向到 `/replay`。

## 9. 不做的事（YAGNI）
- 不新增任何数据采集任务（资金流历史回填受外部接口限制，不在本期解决）。
- 不预存关联快照（实时算即可）。
- 不做跨板块"主线聚合"实体（板块即主线，关联作叠加层）。
- 不做分钟级回放（日线粒度足够覆盖复盘/监控诉求）。
