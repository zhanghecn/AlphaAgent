# AlphaAgent 动态龙头主升低吸算法

算法：`causal-leader-pullback-close-v1`；状态：`historical_proxy_algorithm_complete`；正式策略：`false`。

## 最终算法

1. 概念指数以 20 日突破、相对强度和成交额扩张点火，连续三日从峰值回撤 5% 后结束。
2. 在完整当前成员分母中，按点火以来涨幅、强势日、概念超额和成交额扩张逐日计算 Top3。
3. 个股必须先出现涨幅至少 5%、收盘越前 20 日高点、成交量至少 1.5 倍的点火。
4. 第一轮回调先测试 MA5；创新高后的第二轮及以后先测试 MA10；测试日不能直接买。
5. 测试后的完成日线守住支撑，且收盘高于前收或位于日内上半区，D 收盘作为低吸代理。
6. D+1 扣 0.2% 成本后不盈利直接收盘退出；盈利则持有到越前高、结构破坏或概念结束。
7. 同一浪止损后，只有更深支撑且支撑测试日晚于止损日才允许再入。

## Coverage

- 概念 `446`；campaign `2997`；当前成员关系 `34622`；主板日线 `2386226`。
- 展开成员日 `4750764`；动态 Top3 日 `194757`；逐股 campaign `23745`；波段 `44488`。
- 分钟线、资金流、金银过滤和旧低吸结果读取均为 0。

## Overall

| Variant | Closed | Win rate | Mean | PF | Signal compound | Max DD | Cash compound | Cash DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| base_confirmation | 4048 | 31.8429% | -0.2468% | 0.8787 | -100.0000% | -100.0000% | -75.1779% | -84.7839% |
| non_contraction_confirmation | 2558 | 34.0500% | -0.2212% | 0.8934 | -99.9884% | -99.9991% | -63.7174% | -80.1892% |

## Five Time Blocks

| Variant | Block | Closed | Win rate | Mean | PF | Compound | Max DD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| base_confirmation | block_1 | 638 | 26.0188% | -0.7773% | 0.6323 | -99.6618% | -99.7169% |
| base_confirmation | block_2 | 505 | 30.6931% | -0.4073% | 0.7904 | -92.4655% | -98.0110% |
| base_confirmation | block_3 | 838 | 31.5036% | -0.3797% | 0.8321 | -98.7767% | -99.4981% |
| base_confirmation | block_4 | 1252 | 31.7891% | -0.1271% | 0.9341 | -95.5539% | -98.7742% |
| base_confirmation | block_5 | 815 | 37.5460% | 0.2210% | 1.1130 | 89.8585% | -91.2634% |
| non_contraction_confirmation | block_1 | 380 | 29.7368% | -0.5652% | 0.7316 | -92.6473% | -95.8079% |
| non_contraction_confirmation | block_2 | 314 | 32.4841% | -0.4223% | 0.7885 | -81.1302% | -91.3650% |
| non_contraction_confirmation | block_3 | 532 | 32.8947% | -0.6319% | 0.7368 | -98.3909% | -99.0169% |
| non_contraction_confirmation | block_4 | 781 | 33.2907% | -0.1733% | 0.9140 | -90.6653% | -96.0476% |
| non_contraction_confirmation | block_5 | 551 | 40.1089% | 0.4594% | 1.2462 | 458.8998% | -76.3929% |

## Decision

- `base_confirmation`：`not_qualified`；失败门：`win_rate<=60pct, mean_return<=0, profit_factor<1.2, stable_time_blocks<4, cash_compound<=60pct, cash_drawdown<-10pct, two_independent_market_environments_not_tested, strict_historical_membership_missing`。
- `non_contraction_confirmation`：`not_qualified`；失败门：`win_rate<=60pct, mean_return<=0, profit_factor<1.2, stable_time_blocks<4, cash_compound<=60pct, cash_drawdown<-10pct, two_independent_market_environments_not_tested, strict_historical_membership_missing`。

## Named Cases

- `002384.SZSE` 东山精密：龙头=`true`，campaign `32`，波段 `116`，信号 `25`，执行 `12`。
- `002636.SZSE` 金安国纪：龙头=`true`，campaign `5`，波段 `19`，信号 `0`，执行 `0`。
- `600487.SSE` 亨通光电：龙头=`true`，campaign `26`，波段 `75`，信号 `10`，执行 `6`。

## Data Boundary

本轮 Top3 分母比旧涨停原因候选更完整，但仍是当前成员幸存者代理，不是历史点时成员。
因此历史指标可以评价算法形状，不能升级为正式可交易胜率；正式指标继续为 `null`。

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-causal-leader-pullback-study --format markdown
```
