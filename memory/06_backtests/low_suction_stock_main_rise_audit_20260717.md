# Low-suction Stock Main-rise Baseline Audit

- Conclusion: `no_stock_main_rise_baseline_in_proxy`
- Evidence: `event_recognition_stock_main_rise_hold_audit` (proxy, not strict historical Top3)
- Formal metrics/selected definition: `null/null`
- Outer holdout/current members/limit-up strategy rows read: `0/0/0`
- Candidate/low-suction signals: `1770/1283`
- Signals above MA5/MA10/MA20: `838/1176/1253`

完整机器报告：
`low_suction_stock_main_rise_audit_20260717.json`\
JSON SHA256：
`da50c50ef5e8a992b744d552cf311bfd473b7ca68d412196026de2f0a824c74c`

## 结论

用户指出的第一层问题成立：此前 `main_rise=True` 只证明概念指数仍在主升周期，没有
证明个股处于可持续主升。本审计增加 D-1 个股状态后，仍没有一层定义通过“直接持有”
基准，所以当前代理样本不能称为已经找到个股主升。

但“旧低吸大多已经跌破均线”与真实数据不符。1,283 笔旧信号中有 838 笔仍高于
MA5、1,176 笔高于 MA10、1,253 笔高于 MA20，占比分别为
`65.3157%/91.6602%/97.6617%`。在 MA5 上方的 763 笔有序多头信号胜率仍只有
`40.6291%`、均值 `-0.3606%`；MA5 到 MA10 为 `38.6905%/-0.1882%`，MA10 到
MA20 为 `35.8025%/-0.7720%`。回撤越深总体更差，但不跌破均线本身远不足以产生优势。

从 D-1 收盘识别、D 开盘买入、D+1 收盘卖出的费用后持有基准同样失败：

1,770 个请求中 1,727 个闭合，另 43 个全部因 D 日开盘已在涨停价而拒单；没有用
不可成交的涨停开盘价格制造收益。

- 概念主升：开发/验证胜率 `40.9163%/43.3414%`，均值
  `-0.2606%/-0.3903%`。
- 个股站上 MA5：开发/验证 `40.7747%/44.7531%`，均值
  `-0.2952%/-0.2534%`。
- `收盘 > MA5 > MA10 > MA20`：开发/验证 `40.7865%/46.3333%`，均值
  `-0.2967%/-0.0412%`。
- 均线同时向上、10 日收益为正且距 20 日高点不超过 5%：开发/验证
  `40.5128%/47.4820%`。验证普通成本均值仅 `+0.1043%`，双倍成本转为
  `-0.1974%`；开发均值为 `-0.5287%`，没有跨期稳定性。

最严格定义仍覆盖 1,095/1,770 个候选，占 `61.8644%`，说明它只是常见的均线多头
排列，不是稀缺的主升加速阶段。它在 block 5 达到 149 笔、胜率 `55.0336%`、均值
`+1.2864%`，但 block 1-4 均未稳定为正；block 5 又与此前银行情时间段重合，不能从
同一批数据反推一个“银手指 + 均线”规则。

跌破 MA20 的 10 笔表面胜率 `70%`、均值 `+3.2776%`，只有 9 日且开发段仅 3 笔，
属于反转小样本，不得用来否定趋势判断或生成抄底规则。

因此下一步的“个股主升”不能继续靠增加 MA 阈值定义，而要独立识别阶段：启动、加速、
高潮、衰退，并要求个股相对概念和市场的强度正在上升，而不只是仍位于均线上方。
用户提出的“情绪准备爆发、提前埋伏”也有研究价值，但它属于启动前轨道，必须使用
事前情绪扩散、强势股数量、概念加速和个股蓄势定义，不能与已经确认的主升混为一组。

当前结论固定为 `no_stock_main_rise_baseline_in_proxy`：没有选择个股主升定义，没有测试
新买点，也没有读取严格 Top3 或外层留出。

## Definition Prevalence

| Definition | Candidates | Share |
| --- | ---: | ---: |
| `concept_main_rise` | 1722 | 97.2881% |
| `stock_above_ma5` | 1346 | 76.0452% |
| `stock_trend_order` | 1227 | 69.3220% |
| `stock_strong_main_rise` | 1095 | 61.8644% |

## D-open To D+1-close Hold Baseline

| Definition | Segment | Closed | Days | Win | Mean | PF | 2x mean | Label | Stable |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `concept_main_rise` | `all` | 1679 | 94 | 41.5128% | -0.2925% | 0.8899 | -0.5953% | `not_positive_baseline` | `false` |
| `concept_main_rise` | `development` | 1266 | 57 | 40.9163% | -0.2606% | 0.8989 | -0.5641% | `not_positive_baseline` | `false` |
| `concept_main_rise` | `validation` | 413 | 37 | 43.3414% | -0.3903% | 0.8651 | -0.6909% | `not_positive_baseline` | `false` |
| `stock_above_ma5` | `all` | 1305 | 94 | 41.7625% | -0.2848% | 0.9006 | -0.5860% | `not_positive_baseline` | `false` |
| `stock_above_ma5` | `development` | 981 | 57 | 40.7747% | -0.2952% | 0.8955 | -0.5968% | `not_positive_baseline` | `false` |
| `stock_above_ma5` | `validation` | 324 | 37 | 44.7531% | -0.2534% | 0.9151 | -0.5535% | `not_positive_baseline` | `false` |
| `stock_strong_main_rise` | `all` | 1058 | 94 | 42.3440% | -0.3624% | 0.8741 | -0.6636% | `not_positive_baseline` | `false` |
| `stock_strong_main_rise` | `development` | 780 | 57 | 40.5128% | -0.5287% | 0.8165 | -0.8298% | `not_positive_baseline` | `false` |
| `stock_strong_main_rise` | `validation` | 278 | 37 | 47.4820% | 0.1043% | 1.0364 | -0.1974% | `not_positive_baseline` | `false` |
| `stock_trend_order` | `all` | 1190 | 94 | 42.1849% | -0.2323% | 0.9188 | -0.5335% | `not_positive_baseline` | `false` |
| `stock_trend_order` | `development` | 890 | 57 | 40.7865% | -0.2967% | 0.8959 | -0.5980% | `not_positive_baseline` | `false` |
| `stock_trend_order` | `validation` | 300 | 37 | 46.3333% | -0.0412% | 0.9857 | -0.3421% | `not_positive_baseline` | `false` |

## Existing Low-suction Entry MA Zones

| Table | Cohort | Segment | Closed | Days | Win | Mean | PF | 2x mean |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `d1_stock_definition` | `concept_main_rise` | `all` | 1244 | 93 | 39.9518% | -0.3033% | 0.8557 | -0.6112% |
| `d1_stock_definition` | `concept_main_rise` | `development` | 945 | 57 | 39.6825% | -0.2544% | 0.8727 | -0.5621% |
| `d1_stock_definition` | `concept_main_rise` | `validation` | 299 | 36 | 40.8027% | -0.4577% | 0.8115 | -0.7662% |
| `d1_stock_definition` | `stock_above_ma5` | `all` | 952 | 93 | 40.2311% | -0.2352% | 0.8959 | -0.5437% |
| `d1_stock_definition` | `stock_above_ma5` | `development` | 724 | 57 | 40.1934% | -0.2014% | 0.9068 | -0.5096% |
| `d1_stock_definition` | `stock_above_ma5` | `validation` | 228 | 36 | 40.3509% | -0.3427% | 0.8670 | -0.6521% |
| `d1_stock_definition` | `stock_strong_main_rise` | `all` | 775 | 92 | 41.0323% | -0.2464% | 0.8928 | -0.5537% |
| `d1_stock_definition` | `stock_strong_main_rise` | `development` | 584 | 56 | 40.5822% | -0.3054% | 0.8624 | -0.6119% |
| `d1_stock_definition` | `stock_strong_main_rise` | `validation` | 191 | 36 | 42.4084% | -0.0661% | 0.9740 | -0.3759% |
| `d1_stock_definition` | `stock_trend_order` | `all` | 876 | 92 | 40.5251% | -0.1879% | 0.9174 | -0.4952% |
| `d1_stock_definition` | `stock_trend_order` | `development` | 665 | 56 | 40.3008% | -0.1928% | 0.9118 | -0.4994% |
| `d1_stock_definition` | `stock_trend_order` | `validation` | 211 | 36 | 41.2322% | -0.1725% | 0.9324 | -0.4820% |
| `signal_ma_zone` | `above_ma5` | `all` | 763 | 90 | 40.6291% | -0.3606% | 0.8456 | -0.6673% |
| `signal_ma_zone` | `above_ma5` | `development` | 575 | 56 | 40.0000% | -0.4405% | 0.8075 | -0.7465% |
| `signal_ma_zone` | `above_ma5` | `validation` | 188 | 34 | 42.5532% | -0.1161% | 0.9532 | -0.4251% |
| `signal_ma_zone` | `below_ma20` | `all` | 10 | 9 | 70.0000% | 3.2776% | 11.2409 | 2.9629% |
| `signal_ma_zone` | `below_ma20` | `development` | 3 | 3 | 100.0000% | 6.6348% | - | 6.3147% |
| `signal_ma_zone` | `below_ma20` | `validation` | 7 | 6 | 57.1429% | 1.8388% | 5.0217 | 1.5264% |
| `signal_ma_zone` | `ma10_to_ma20` | `all` | 81 | 45 | 35.8025% | -0.7720% | 0.5241 | -1.0796% |
| `signal_ma_zone` | `ma10_to_ma20` | `development` | 51 | 27 | 31.3725% | -0.5972% | 0.6181 | -0.9043% |
| `signal_ma_zone` | `ma10_to_ma20` | `validation` | 30 | 18 | 43.3333% | -1.0692% | 0.3788 | -1.3776% |
| `signal_ma_zone` | `ma5_to_ma10` | `all` | 336 | 81 | 38.6905% | -0.1882% | 0.8968 | -0.4947% |
| `signal_ma_zone` | `ma5_to_ma10` | `development` | 264 | 53 | 39.0152% | 0.0219% | 1.0134 | -0.2844% |
| `signal_ma_zone` | `ma5_to_ma10` | `validation` | 72 | 28 | 37.5000% | -0.9583% | 0.6226 | -1.2660% |
| `signal_ma_zone` | `unordered_mas` | `all` | 93 | 55 | 35.4839% | -0.7826% | 0.6014 | -1.1010% |
| `signal_ma_zone` | `unordered_mas` | `development` | 67 | 41 | 38.8060% | -0.3050% | 0.8255 | -0.6284% |
| `signal_ma_zone` | `unordered_mas` | `validation` | 26 | 14 | 26.9231% | -2.0132% | 0.2005 | -2.3190% |

## Boundary

本报告只审计代理候选的个股主升基准和旧买点均线位置，不选择正式主升定义，
不测试新低吸触发，也不包含提前埋伏轨道。严格 Top3、正式绩效和外层留出保持关闭。

## Reproduce

```bash
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-stock-main-rise-audit --format json
```
