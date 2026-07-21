# AlphaAgent 动态龙头主升低吸算法

算法：`causal-leader-pullback-close-v2`；状态：`historical_proxy_algorithm_complete`；正式策略：`false`。

## 最终算法

1. 概念指数以 20 日突破、相对强度和成交额扩张点火，连续三日从峰值回撤 5% 后结束。
2. 在完整当前成员分母中，按点火以来涨幅、强势日、概念超额和成交额扩张逐日计算 Top3。
3. 个股必须先出现涨幅至少 5%、收盘越前 20 日高点、成交量至少 1.5 倍的点火。
4. 第一轮回调先测试 MA5；创新高后的第二轮及以后先测试 MA10；测试日不能直接买。
5. 测试后的完成日线守住支撑，且收盘高于前收或位于日内上半区，D 收盘作为低吸代理。
6. 只在 GOLD/NORMAL 中交易：确认日涨幅至少 8%，收盘距可见前高不超过 5%，且距支撑测试 1-2 个交易日。
7. SILVER、任意 DANGER 和 UNKNOWN 当前空仓，不为凑覆盖另设买点。
8. D+1 扣 0.2% 成本后不盈利直接收盘退出；盈利则持有到越前高、结构破坏或概念结束。
9. 同一浪止损后，只有更深支撑且支撑测试日晚于止损日才允许再入。

## Coverage

- 概念 `446`；campaign `2997`；当前成员关系 `34622`；主板日线 `2386226`。
- 展开成员日 `4750764`；动态 Top3 日 `194757`；逐股 campaign `23745`；波段 `44488`。
- 行情状态 `520` 日；信号同日命中 `6183`；分钟线、资金流和旧低吸结果读取均为 0。

## Environment Policy

| Environment | Action |
| --- | --- |
| `GOLD/NORMAL` | `gold_strong_reclaim_confirmation` |
| `SILVER/NORMAL` | `cash` |
| `NEUTRAL/NORMAL` | `cash` |
| `GOLD/DANGER` | `cash` |
| `SILVER/DANGER` | `cash` |
| `UNKNOWN` | `cash` |

## Overall

| Variant | Closed | Win rate | Mean | PF | Signal compound | Max DD | Cash compound | Cash DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| base_confirmation | 4048 | 31.8429% | -0.2468% | 0.8787 | -100.0000% | -100.0000% | -75.1779% | -84.7839% |
| non_contraction_confirmation | 2558 | 34.0500% | -0.2212% | 0.8934 | -99.9884% | -99.9991% | -63.7174% | -80.1892% |
| gold_strong_reclaim_confirmation | 169 | 62.7219% | 1.8968% | 2.2715 | 1752.3009% | -26.0342% | 117.8555% | -7.0410% |

## Five Time Blocks

| Variant | Block | Closed | Win rate | Mean | PF | Compound | Max DD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| base_confirmation | block_1 | 638 | 26.0188% | -0.7773% | 0.6323 | -99.6618% | -99.7169% |
| base_confirmation | block_2 | 505 | 30.6931% | -0.4073% | 0.7904 | -92.4655% | -98.0110% |
| base_confirmation | block_3 | 832 | 31.3702% | -0.3913% | 0.8272 | -98.8528% | -99.4904% |
| base_confirmation | block_4 | 1258 | 31.8760% | -0.1206% | 0.9375 | -95.2590% | -98.7742% |
| base_confirmation | block_5 | 815 | 37.5460% | 0.2210% | 1.1130 | 89.8585% | -91.2634% |
| non_contraction_confirmation | block_1 | 380 | 29.7368% | -0.5652% | 0.7316 | -92.6473% | -95.8079% |
| non_contraction_confirmation | block_2 | 364 | 33.5165% | -0.2952% | 0.8575 | -78.3810% | -91.3650% |
| non_contraction_confirmation | block_3 | 513 | 31.9688% | -0.8059% | 0.6685 | -99.2079% | -99.2079% |
| non_contraction_confirmation | block_4 | 745 | 33.5570% | -0.1095% | 0.9445 | -83.1083% | -96.0476% |
| non_contraction_confirmation | block_5 | 556 | 39.9281% | 0.4522% | 1.2427 | 447.6821% | -76.3929% |
| gold_strong_reclaim_confirmation | block_1 | 36 | 66.6667% | 2.8120% | 2.7954 | 153.3042% | -23.1046% |
| gold_strong_reclaim_confirmation | block_2 | 31 | 61.2903% | 1.9516% | 2.3076 | 73.5766% | -15.2090% |
| gold_strong_reclaim_confirmation | block_3 | 29 | 62.0690% | 1.3490% | 1.8598 | 41.4445% | -10.8964% |
| gold_strong_reclaim_confirmation | block_4 | 32 | 65.6250% | 1.9942% | 3.2026 | 83.1114% | -6.8359% |
| gold_strong_reclaim_confirmation | block_5 | 41 | 58.5366% | 1.3632% | 1.7454 | 62.6583% | -26.0342% |

## Decision

- `base_confirmation`：历史代理门=`false`；正式状态=`not_qualified`；失败门：`win_rate<=60pct, mean_return<=0, profit_factor<1.2, stable_time_blocks<3, cash_compound<=60pct, cash_drawdown<-10pct, strict_historical_membership_missing`。
- `non_contraction_confirmation`：历史代理门=`false`；正式状态=`not_qualified`；失败门：`win_rate<=60pct, mean_return<=0, profit_factor<1.2, stable_time_blocks<3, cash_compound<=60pct, cash_drawdown<-10pct, strict_historical_membership_missing`。
- `gold_strong_reclaim_confirmation`：历史代理门=`true`；正式状态=`not_qualified`；失败门：`strict_historical_membership_missing`。

## Named Cases

- `002384.SZSE` 东山精密：龙头=`true`，campaign `32`，波段 `116`，信号 `25`，执行 `12`；回调确认状态：`no_new_support_information=22, not_dynamic_top3=57, price_action_not_confirmed=10, required_support_not_tested=165, signal_emitted=25, support_not_held=1, support_test_day=185`。
- `002636.SZSE` 金安国纪：龙头=`true`，campaign `5`，波段 `19`，信号 `0`，执行 `0`；回调确认状态：`not_dynamic_top3=10, required_support_not_tested=15, support_test_day=41`。
- `600487.SSE` 亨通光电：龙头=`true`，campaign `26`，波段 `75`，信号 `10`，执行 `7`；回调确认状态：`no_new_support_information=10, not_dynamic_top3=40, required_support_not_tested=66, signal_emitted=10, support_test_day=170`。

## Data Boundary

本轮 Top3 分母比旧涨停原因候选更完整，但仍是当前成员幸存者代理，不是历史点时成员。
因此历史指标可以评价算法形状，不能升级为正式可交易胜率；正式指标继续为 `null`。

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-research python -m alphaagent.server.services.low_suction.cli v2-causal-leader-pullback-study --format markdown
```
