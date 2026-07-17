# AlphaAgent 低吸共享股票历史回补证据

数据截止日：2026-07-15\
结论：`stock_daily_history_ready`\
行情路径：`AkShareAdapter -> tencent.stock_kline_full`

## Result

- 低吸复用共享 `stock_daily_bars`，没有建立第二套股票日线，也没有改动打板候选、
  策略版本、成交账本或绩效。
- 全市场股票池为 5,878 只；自动自举读取并写入 4,523,557 行。
- 可靠横截面从 603 个交易日增加到 800 个交易日，超过 750 日目标，
  `target_achieved=true`。
- 实际耗时 1,397.684 秒，约 23.3 分钟；结果没有报告超时股票。
- 严格低吸审计最终识别 799 个已收盘可靠交易日，范围
  `2023-03-28..2026-07-15`，自然日跨度 1,205 天。
- `stock_daily_history` 已从低吸阻塞项移除；正式指标仍因其他点时数据缺口保持
  `null`。

## Bootstrap Contract

普通增量同步仍默认请求 250 根日线。只有同时满足以下条件时才自动切换到 800 根：

- 全市场、非定向同步；
- `incremental=true`；
- 股票池不少于完整横截面下限；
- 当前可靠历史少于 750 个交易日。

固定边界：

```python
STOCK_DAILY_HISTORY_TARGET_DAYS = 750
STOCK_DAILY_HISTORY_BOOTSTRAP_LIMIT = 800
MIN_COMPLETE_DAILY_SYMBOL_COUNT = 3_000
```

本地交易日历中，720 个交易日只有 1,086 个自然日，不能通过 1,095 日门槛；
727 个交易日才首次同时满足两个门槛。750 日目标为供应商缺口和停牌横截面保留了
23 个交易日缓冲。

## Real Run

```json
{
  "rows_read": 4523557,
  "rows_written": 4523557,
  "history_bootstrap": {
    "performed": true,
    "reliable_trade_days_before": 603,
    "reliable_trade_days_after": 800,
    "target_trade_days": 750,
    "request_limit": 800,
    "target_achieved": true
  },
  "elapsed_seconds": 1397.684
}
```

## Strict Coverage

严格审计只统计每日至少 3,000 只不同股票、且不晚于已收盘截止日的横截面：

| Item | Value |
| --- | ---: |
| reliable trade days | 799 |
| reliable range | 2023-03-28..2026-07-15 |
| calendar span | 1,205 days |
| rows on reliable dates | 4,288,952 |
| entities | 5,675 |
| minimum reliable cross-section | 5,101 |
| maximum reliable cross-section | 5,532 |
| audit coverage | 92.2090% |

回补发生在 2026-07-16 午间，原始表中当天已有 5,531 只股票的盘中日 K。
共享覆盖查询将其标记为 `latest_trade_date_is_complete=false`，研究截止日仍为
`2026-07-15`。盘中行保留供实时界面使用，不进入历史研究覆盖，也不因数量超过
3,000 而冒充完整收盘日。

## Remaining Boundary

严格审计仍为 `blocked_by_data_quality`，剩余阻塞项只有：

```text
historical_concept_membership
historical_security_status
candidate_minute_paths
```

当前概念成员只有 3 个盘后原始快照、2 个次日可用代理日。当前成员不能回填 799 日；
Tushare 未配置 token，现有运行代码只有申万行业区间导入。官方 `dc_member` 已确认是
同 BK 体系的历史成员候选，但真实日期和完整性尚未实测。因此下一步先探测该来源并
验证合格题材口径，再重建 Top3 候选；不能先扩展分钟下载或发布代理胜率。

## Verification

```bash
docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli audit --format json
uv run --group server pytest tests/alphaagent/test_completed_session.py -q
uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py -k "stock_daily" -q
uv run --group server pytest tests/alphaagent/services/low_suction -q
```
