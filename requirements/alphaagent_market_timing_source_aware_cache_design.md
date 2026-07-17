# Market Timing Source-Aware Cache Design

**Status:** Awaiting written-spec review
**Date:** 2026-07-14

## Problem

`/market` 的正式日线已更新，但面板仍可能显示前一交易日。

2026-07-14 的真实证据：

- `stock_daily_bars` 已有 `2026-07-14` 的 5531 个标的。
- 择时所用的 7 个指数都已更新到 `2026-07-14`。
- `eod_1900` 和 `eod_finalize_2130` 都已成功完成。
- `market_timing_panel` 仍是 18:04 生成的 `2026-07-13` 面板。

根因是 `_base_panel` 只用“内存 TTL + 库缓存 24 小时”判断新鲜度，
没有将面板的数据日期与当前正式数据水位对比。强制刷新可以临时恢复，
但无法防止下一个交易日再次发生。

## Goals

- 7 大指数的新正式交易日入库后，下一次 `GET /api/market-timing/panel`
  自动放弃旧面板并重算。
- 同时守住内存缓存和数据库缓存，不依赖手工 refresh。
- 盘中临时因子在同日正式日线入库后自动失效，不把盘中近似值
  继续当作正式收盘因子。
- 保持金/银手指、危险状态和无未来函数语义不变。

## Non-Goals

- 不改金/银手指阈值和结构危险算法。
- 不用虚构的当日行填补缺失因子。
- 不修改数据同步调度器，不把择时模块与特定同步任务耦合。
- 不改前端布局或日期展示合同。

## Considered Approaches

### 1. Source-aware watermark (selected)

每次读取面板缓存前，用一条轻量 SQL 查询 7 大指数全部存在的最新
交易日，并与面板生成时记录的正式数据水位对比。

优点：对定时同步、手工导入和服务重启都生效，失效时机精确。
代价：每次面板请求多一条只扫描 7 个指数的小查询。

### 2. Shorter TTL

将 24 小时缩短为 5-30 分钟。

优点：代码最少。
缺点：仍存在可见滞后，并会在数据没变时反复执行约 10-20 秒的全量重算。

### 3. Invalidate from the sync scheduler

在日线同步成功后主动清除择时缓存。

优点：同步流程内可立即触发。
缺点：与 `data_sync.py` 紧耦合，容易漏掉手工导入、其他数据源或任务中断后
的恢复场景。

## Selected Design

### Formal source watermark

在 `panel.py` 增加 `_latest_formal_composite_date(session, schema)`：

- 只查询 `INDEX_SYMBOLS` 对应的 7 个 `vt_symbol`。
- 按 `trade_date` 分组。
- 只保留 `count(distinct vt_symbol) == 7` 的日期。
- 返回最新日期。

这与 `load_composite_series` 只使用 7 指数共同日期的语义一致，避免单个指数先到就
误判为正式数据完整。

### Persisted freshness metadata

每个新面板增加顶层元数据：

```json
{
  "data_freshness": {
    "cache_version": 2,
    "basis": "EOD",
    "formal_source_date": "2026-07-14"
  }
}
```

- `cache_version`：修改缓存合同时递增。缺少该字段的旧面板一次性失效。
- `basis=EOD`：面板完全由数据库正式日线生成。
- `basis=INTRADAY`：序列末尾追加了当日实时近似 bar。
- `formal_source_date`：追加盘中 bar **之前**的 7 指数最新正式共同日期。

因此，盘中面板即使 `sample_range` 已到今天，仍能在同日正式日线到达时通过
`formal_source_date` 变化被正确失效。

### Cache validity rules

内存缓存和数据库缓存都必须同时满足 TTL 和数据水位规则：

1. `cache_version == PANEL_CACHE_VERSION`。
2. 已记录的 `formal_source_date` 等于当前最新正式共同日期。
3. `EOD` 面板在前两项成立时可用。
4. `INTRADAY` 面板只在实时 overlay 窗口内可用；正式日线到达或 overlay 窗口结束后
   必须重算。

数据水位在进入 `_base_panel` 时查询一次，依次用于内存缓存和库缓存判断。
如果数据在重算期间再次变化，下一次请求会再次检测，不需要跨模块锁。

### Request behavior

- `force_refresh=true` 和 `POST /refresh` 仍无条件重算。
- 普通 `GET /panel` 在源水位更新时自动重算并覆盖库缓存。
- 前端无需新的手动操作。
- `factor_date` 和 `timing_series[-1].date` 只能跟随已经真实计算的因子日，
  不为了“看起来最新”而伪造行。

## Failure Handling

- 数据库无法查询水位时，保持现有 API 错误语义，不把未验证缓存冒充新数据。
- 找不到 7 指数共同日期时，走现有空面板/计算失败路径。
- 不修改事件确认规则；新日期仅会使前一日 `PENDING` 按现有 `t+1`
  规则转为 `CONFIRMED/INVALIDATED`。

## Tests

后端增加以下守护：

- 旧版本或缺失 freshness 元数据的面板失效。
- `EOD` 面板与当前正式水位相同时命中缓存。
- 正式水位从 `07-13` 升到 `07-14` 时，内存和库缓存都失效。
- `INTRADAY` 面板在盘中可用，在同日正式数据到达后失效。
- `INTRADAY` 面板在 overlay 窗口结束后失效。
- 重算后 `factor_date`、`quote_date`、`timing_series[-1].date` 和 `sample_range[-1]`
  全部对齐到最新正式交易日。

同时重跑现有市场择时、no-lookahead 和前端相关测试。

## Acceptance Criteria

- 在不调用手动 refresh 的情况下，将正式数据水位从 `D-1` 推进到 `D`，
  下一次 `GET /panel` 返回 `factor_date=D` 和 `timing_series[-1].date=D`。
- 当前真实数据回归返回 `2026-07-14`，页面最近交易日包含 `07-14`。
- 金/银事件数、历史关键日期和危险状态回归不变，除了原本待确认事件可因
  新的真实 `t+1` 数据正常转状态。
- 服务重建后无需人工清理 `market_timing_panel`。

## Files In Scope

- `alphaagent/server/services/market_timing/panel.py`
- `tests/alphaagent/services/market_timing/test_market_timing_intraday.py`
- `memory/07_market_timing/market_timing_design.md`

前端预计无源码变更，仅执行真实页面验收。

## Residual Risks

- 每次面板读取多一条小查询；查询范围仅 7 个指数且主键以
  `vt_symbol` 开头，预期远小于面板重算成本。
- 7 指数完整只证明综合价格序列可用；市场广度的质量仍由现有
  `compute_market_contexts` 和数据同步健康检查负责。
- 这次修复只保证“已入库的新日期不被旧缓存遮住”，不保证外部数据源
  永远按时到达。
