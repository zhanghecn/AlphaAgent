# AlphaAgent 启动前首次爆发研究

结论：`validated_prelaunch_label_edge`\
轨道：全主板股票日的启动前代理研究，不是认可后回调\
股票日/股票/核验正例：`217819/3016/576`\
读取 D 开盘到 D+1 收盘收益：`true`\
正式规则/正式绩效：`null/null`\
交易诊断（全体命中）：`42.8414%/0.0228%/-0.2860%`（胜率/普通成本均值/双倍成本均值）

## 数据覆盖

| Item | Value |
| --- | ---: |
| 目标事件日 | 96 |
| 目标范围 | `2025-06-27..2025-11-17` |
| 有原因事件 | 4945 |
| 精确概念关系 | 2947 |
| 主板日线 | 589160 |
| 日线范围 | `2025-01-23..2025-11-17` |
| 当前成员读取 | 0 |
| 历史证券状态读取 | 0 |

## 标签基线

| Segment | Rows | Positives | Days | Base rate |
| --- | ---: | ---: | ---: | ---: |
| `all` | 217819 | 576 | 96 | 0.2644% |
| `development` | 132601 | 451 | 58 | 0.3401% |
| `validation` | 85218 | 125 | 38 | 0.1467% |
| `block_1` | 47166 | 186 | 20 | 0.3944% |
| `block_2` | 44098 | 173 | 19 | 0.3923% |
| `block_3` | 41337 | 92 | 19 | 0.2226% |
| `block_4` | 42208 | 58 | 19 | 0.1374% |
| `block_5` | 43010 | 67 | 19 | 0.1558% |

## 开发叶子账本

| Leaf | Conditions | Status | Rows | Positives | Days | Precision | Recall | Lift | Coverage | Reasons |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2 | `distance_to_ma20_pct <= 1.758610 AND volatility_10d_pct <= 1.942363` | `rejected` | 74356 | 136 | 58 | 0.1829% | 30.1552% | 0.5378 | 56.0750% | `precision_lift_below_2,universe_coverage_above_10pct` |
| 3 | `distance_to_ma20_pct <= 1.758610 AND volatility_10d_pct > 1.942363` | `rejected` | 14145 | 62 | 58 | 0.4383% | 13.7472% | 1.2887 | 10.6673% | `precision_lift_below_2,universe_coverage_above_10pct` |
| 5 | `distance_to_ma20_pct > 1.758610 AND distance_to_ma20_pct <= 4.812109` | `rejected` | 33662 | 148 | 58 | 0.4397% | 32.8160% | 1.2927 | 25.3859% | `precision_lift_below_2,universe_coverage_above_10pct` |
| 6 | `distance_to_ma20_pct > 1.758610 AND distance_to_ma20_pct > 4.812109` | `selected` | 10438 | 105 | 58 | 1.0059% | 23.2816% | 2.9576 | 7.8717% | `-` |

## 后段标签验证

规则：`distance_to_ma20_pct > 1.758610 AND distance_to_ma20_pct > 4.812109`\
信号/正例/日期：`5228/32/38`\
精度/召回/提升/覆盖：`0.6121%/25.6000%/4.1729/6.1349%`\
失败门：`-`

## 条件交易诊断

状态：`completed_reused_history_diagnostic`

| Segment | Closed | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all` | 15394 | 95 | 42.8414% | 0.0228% | 1.0179 | -0.2860% | 11.1753% | -10.4272% |
| `development` | 10425 | 58 | 41.0552% | -0.0152% | 0.9882 | -0.3237% | 9.6391% | -9.6326% |
| `validation` | 4969 | 37 | 46.5889% | 0.1025% | 1.0827 | -0.2068% | 1.4012% | -6.8598% |
| `block_1` | 4083 | 20 | 42.9341% | 0.1459% | 1.1356 | -0.1639% | 5.1799% | -2.6608% |
| `block_2` | 3326 | 19 | 43.2351% | 0.2295% | 1.1905 | -0.0790% | 7.4490% | -3.7004% |
| `block_3` | 3016 | 19 | 36.1074% | -0.5031% | 0.6992 | -0.8100% | -2.9869% | -9.6326% |
| `block_4` | 1606 | 19 | 41.7808% | -0.3720% | 0.7946 | -0.6788% | -3.9086% | -6.8598% |
| `block_5` | 3363 | 18 | 48.8849% | 0.3291% | 1.3406 | 0.0186% | 5.5258% | -1.7363% |

复利和回撤按每个信号日全部闭合命中等权后逐日计算，只是复用历史的诊断曲线，不是现金账户或正式绩效。

## 金银与危险状态归因

| Segment | Regime | Universe | Base | Rule rows | Rule positives | Rule precision | Lift |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `development` | `GOLD/NORMAL` | 132601 | 0.3401% | 10438 | 105 | 1.0059% | 2.9576 |
| `validation` | `GOLD/DANGER` | 2236 | 0.0894% | 54 | 0 | 0.0000% | 0.0000 |
| `validation` | `GOLD/NORMAL` | 37761 | 0.1430% | 1477 | 11 | 0.7448% | 5.2079 |
| `validation` | `SILVER/DANGER` | 2211 | 0.0905% | 76 | 0 | 0.0000% | 0.0000 |
| `validation` | `SILVER/NORMAL` | 43010 | 0.1558% | 3621 | 21 | 0.5800% | 3.7229 |

## 输入指纹

| Input | Rows | SHA256 |
| --- | ---: | --- |
| `conditional_trade_ledger` | 15666 | `sha256:e82127d4b97beceba2967ac6cef0ca418743ed6317f646d08ffd227eee22eb44` |
| `exact_reason_relations` | 2947 | `sha256:149fece365a1b65a8571d2423c5a699657102f235e058f428baaccdf8f6e1dd4` |
| `prelaunch_features` | 217819 | `sha256:feafa0ad3680b4f8f4321a58134a0d41124a1e2a6bbe7572ab5956a3cf078b3a` |
| `prelaunch_labels` | 217819 | `sha256:f250e9282100749c514001f6f9929287d77d6ce02f083899d49843e8aec53868` |
| `stock_bars` | 589160 | `sha256:34697d60e44967ef1e0b1adaf9a5df83dae83d26b97f2e9f6582250c4389be05` |

## 边界

未核验行统一标记 `not_verified_by_available_event_evidence`，不代表已证明不会爆发。历史证券状态只使用当前名称重建，主升概念关系仅是 D 日后的结果标签，不能生成 D 日订单。
