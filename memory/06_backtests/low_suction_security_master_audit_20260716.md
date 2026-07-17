# AlphaAgent 低吸证券主表幸存者偏差审计

数据观测日：2026-07-16\
研究版本：`low-suction-security-master-audit-v1`\
结论：`reconstructed_only`\
正式指标：`null`

## 结论

BaoStock 全量证券主表证明本地 `stocks` 缺少历史上市/退市有效期，但没有发现当前三年
研究窗内退市主板股日线被系统性删除：最近 1,095 个自然日内退市的 94 只主板股，
94 只都至少有一条本地日线。

因此，当前 `historical_security_status` 的主要阻断项是逐日 ST、停牌、上市和退市时点
均不可审计，而不是三年窗内退市股价格序列整体缺失。BaoStock 没有可核验的字段发布
时间承诺，只能提供 `reconstructed` 证据，不能解除严格研究门禁。

## Master Comparison

| 项目 | 数量 |
| --- | ---: |
| BaoStock 全量证券记录 | 8,845 |
| BaoStock `type=1` 股票 | 5,537 |
| BaoStock 沪深主板股票 | 3,483 |
| 其中当前上市主板 | 3,192 |
| 其中历史退市主板 | 291 |
| 本地 `stocks` | 5,878 |
| 本地有任意日线的股票 | 5,871 |
| 本地含可用上市日期 | 0 |
| 本地含可用退市日期 | 0 |

## Survivorship Findings

- BaoStock 3,483 只主板股票中，本地代码清单缺 2 只，均为历史退市股：
  `000022.SZSE` 深赤湾A、`000043.SZSE` 中航善达。
- 291 只历史退市主板股中，288 只有本地日线，3 只没有任何日线：
  `600849.SSE` 上药转换、`000022.SZSE` 深赤湾A、`000043.SZSE` 中航善达。
- 三年目标窗起点为 `2023-07-17`。该窗口内退市的主板股为 94 只，94 只都有本地
  日线；在这个维度上没有发现价格样本幸存者偏差。
- 上述结论不能证明日线逐日完整，也不能替代历史 ST/停牌/上市/退市状态覆盖审计。

## Software Boundary

- `historical_inputs.py` 已将概念成员和证券状态拆成独立原子批次。
- 证券作用域使用显式 `(trade_date, vt_symbol)`，不再使用会误判上市前/退市后的
  日期乘股票笛卡尔积。
- `reconstructed` 批次可以保存用于差异审计，但 `security_is_valid_at_open()` 永远
  返回 false；只有 `strict` 且 `known_at <= D 09:25 Asia/Shanghai` 才能进入正式覆盖。
- PostgreSQL 使用 `low_suction_security_history` 和
  `low_suction_security_history_scopes`；状态行和覆盖分母在同一事务中替换。
- 覆盖审计按供应商和证据等级独立选择，不把多个来源拼接成看似完整的数据集。

## Source Limitation

BaoStock `query_stock_basic` 提供 `ipoDate/outDate/type/status`，
`query_history_k_data_plus` 提供逐日 `tradestatus/isST`。截至本次核验，没有找到官方
承诺证明这些历史字段在对应交易日 09:25 前已发布且不会事后修订。因此所有 BaoStock
结果固定为 `reconstructed`。

## Reproduce

```bash
docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli security-master-audit --format json

docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli audit --format json
```

第二条命令当前仍返回 `blocked_by_data_quality`，包含
`historical_security_status`，且 `formal_metrics=null`。
