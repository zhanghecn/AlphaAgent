# AlphaAgent 低吸共享概念指数回补证据

数据截止日：2026-07-15\
结论：`concept_index_history_ready`\
证据来源：`eastmoney.board_kline`

## Result

- 低吸复用共享 `sector_daily_bars`，没有新建低吸指数表，也没有导入打板候选或绩效。
- 严格审计得到 799 个完整交易日，范围 `2023-03-28..2026-07-15`，
  自然日跨度 1,205 天，已通过 720 个交易日和 1,095 个自然日门槛。
- 当日有效概念数动态为 371..495，最低横截面覆盖为 `99.7567%`。
- `concept_index_history` 已从低吸数据质量阻塞项移除。
- 指数不能证明历史成员；`historical_concept_membership` 仍然阻塞正式 Top3 回测。

## Root Cause And Backfill

原共享同步任务默认只请求 250 根板块 K 线，审计又用当前 498 个概念作为所有历史日的
固定分母，因此只识别出 72 个完整日。对 `BK0490` 的只读请求证明东方财富可返回
800 根官方板块 K 线，范围 `2023-03-28..2026-07-16`。

同步实现已改为：

- 默认 800 根、最多 1,000 根。
- 可显式只同步 `concept/theme`。
- 每个板块一次 PostgreSQL bulk upsert，重复日期保留最后一条。
- 非 `eastmoney.board_kline` 回退结果不能进入正式板块日线。

全量 800 日回补结果：

| Item | Value |
| --- | ---: |
| rows_read | 334,283 |
| rows_written | 334,283 |
| covered boards | 495 |
| failed boards | 0 |
| empty boards | 3 |
| fallback boards | 0 |

## Dynamic Coverage

每个交易日 D 的期望分母只包含满足
`first_bar_date <= D <= last_bar_date` 的官方概念指数。D 日至少要有 300 个有效概念，
且 `actual / expected >= 90%` 才计为完整日。重复日期、重复概念边界和
`actual > expected` 都会失败关闭。

审计上限固定为股票可靠截止日 `2026-07-15`。数据库中 7 月 16 日的盘中板块 K 线
可以保留供实时界面使用，但不计入历史完整性：

| Item | Value |
| --- | ---: |
| raw observed dates through cutoff | 859 |
| dynamically complete dates | 799 |
| complete range | 2023-03-28..2026-07-15 |
| canonical rows on complete dates | 333,871 |
| indexed concepts | 498 |
| expected active concepts | 371..495 |
| minimum complete coverage | 99.7567% |

## Dynamic Main-rise Check

`main_rise.py` 对 333,871 条官方日线、498 个板块和 799 个交易日完成无未来函数计算：

- 主升状态行 94,503 条。
- 772 个日期至少有一个主升板块。
- 首个可计算主升日为 `2023-05-05`。
- `2026-07-15` 有 44 个主升板块。

东方财富目录把 CRO、创新药等真实题材和“昨日连板”“昨日打二板以上表现”等事件风格
板块都标为 `concept`，且没有更细的 `category`。因此覆盖审计保留官方全目录，产品
候选层后续必须建立可验证的题材资格规则；不能仅按名称临时删除，也不能把事件风格
板块直接当作低吸题材。

## Remaining Boundary

- 共享股票日线也已达到 799 个可靠交易日，范围 `2023-03-28..2026-07-15`；
  股票和概念指数历史均不再阻塞。
- 当前东方财富成员快照只能用于其采集后的交易日，不能回填 799 日历史。
- 正式 Top3 需要 D 日开盘前已知的点时成员、主板/ST/停牌状态和候选分钟路径。
- 当前总研究结论仍是 `blocked_by_data_quality`，正式胜率和复利仍为 `null`。

## Verification

```bash
uv run --group server pytest tests/alphaagent/services/low_suction -q
uv run --group server pytest tests/alphaagent/test_akshare_adapter.py tests/alphaagent/test_data_sync_schedule.py -q
docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli audit --format json
```
