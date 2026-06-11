# AlphaAgent 严格分钟回测就绪状态

- 生成时间：2026-06-11
- 目标：完成 `minute_entry_required=true` 的真实严格尾盘分钟回测，并给出可审计回测表。
- 当前状态：未完成，原因是历史 1 分钟数据缺口未覆盖。

## 当前证据

- 严格回测入口：`POST /api/backtests/strict-minute-pipeline`
- 当前流水线状态：`blocked_by_minute_gaps`
- 缺口总数：794 个 symbol-date
- 已覆盖：2 个
- 缺失：792 个
- 覆盖率：0.2519%
- 股票数：194 只
- 交易日：101 天
- 缺口区间：2026-01-08 至 2026-06-11
- 需要窗口：14:30 至 14:57

## 已生成文件

- 严格缺口 CSV：`memory/06_backtests/alphaagent_minute_gap_backtest_10_2025-10-14_2026-06-11.csv`
- 供应商补数清单：`memory/06_backtests/alphaagent_minute_vendor_manifest_backtest_10_2025-10-14_2026-06-11.csv`
- 严格回测 10 结果：`memory/06_backtests/2026-06-11_backtest_10_strict_tail_report.md`
- 宽松回测 9 结果：`memory/06_backtests/2026-06-11_backtest_9_report.md`

## 补数要求

供应商或导出工具需要按 `alphaagent_minute_vendor_manifest_backtest_10_2025-10-14_2026-06-11.csv` 返回真实 1 分钟 K 线。

AlphaAgent 导入 CSV 必须包含：

```text
vt_symbol,bar_time,open,high,low,close,volume,turnover
```

每个缺口行至少需要覆盖该股票该交易日 `14:30` 至 `14:57` 的真实 1 分钟 K 线。可多给全天数据，但导入后仍会按目标日期和尾盘窗口审计。

## 已验证不可用路径

- EastMoney 公共分钟 K：请求 2026-01-08 返回 2026-06-11 附近数据。
- Sina 公共分钟 K：请求历史缺口样本返回 2026-06-10/11 近端数据。
- Sina 历史逐笔 JSON：2026-01-08 缺口样本返回 0 条；仅 2026-06-11 当日样本有数据。
- 当前 vn.py SQLite：`/root/.vntrader/database.db` 存在，但 `dbbardata`、`dbtickdata` 等表为 0 行。
- 当前 Tushare：未配置 `TUSHARE_TOKEN`，`/api/data-sync/imports/minute-bars/tushare-gaps` 返回 `unavailable`。

## 可用补数入口

- 外部 CSV 导入：`POST /api/data-sync/imports/minute-bars`
- 缺口审计：`POST /api/data-sync/imports/minute-bars/audit-gaps`
- Tushare Pro 补数：`POST /api/data-sync/imports/minute-bars/tushare-gaps`
- vn.py 数据库补数：`POST /api/vnpy/import-minute-bars/gaps`
- 严格最终流水线：`POST /api/backtests/strict-minute-pipeline`

## 闭环顺序

1. 使用供应商补数清单获取真实 1 分钟历史数据。
2. 将返回 CSV 放入 `data/imports/`。
3. 调用 `POST /api/data-sync/imports/minute-bars`，先 `dry_run=true`，再正式导入。
4. 调用 `POST /api/data-sync/imports/minute-bars/audit-gaps` 审计严格缺口。
5. 审计 `status=ready` 后调用 `POST /api/backtests/strict-minute-pipeline`。
6. 导出最终严格回测 CSV 和报告。

## 当前结论

当前不能声称真实严格尾盘回测完成。宽松回测 9 可作为日线近似模拟，严格回测 10 证明分钟数据不足；最终结论必须等真实 1 分钟数据覆盖后由严格流水线生成。
