# Low-suction D+1 Winner/Loser Group Study

- Conclusion: `descriptive_groups_not_stable`
- Evidence: `event_recognition_outcome_group_d1_falsification` (proxy, not strict historical Top3)
- Formal metrics/rule: `null/false`
- Outer holdout/current members/limit-up strategy rows read: `0/0/0`
- Candidates: `1770` (main rise `1722`, control `48`)
- Entry signals/no-pullback: `1283/487`

完整机器报告：
`low_suction_outcome_group_study_20260717.json`\
JSON SHA256：
`e53f64e10dc5647438e0471be66c391494b87c46aa6aa40614062a24c0664f45`

## 结论

这次按预注册顺序完成了“先分赢亏，再看买入前特征”的诊断，但没有找到可继续变成
买入规则的高胜率组。1,770 个候选日中有 1,283 个出现低吸锚点并全部在计划 D+1
收盘卖出；费用后胜率仅 `39.6726%`、单笔均值 `-0.3436%`、利润因子 `0.8374`，
双倍成本均值为 `-0.6513%`。开发段和验证段分别为 `39.3750%/-0.2901%` 与
`40.5573%/-0.5027%`，负期望不是单一时间块造成的。

开发段唯一满足高组门槛的是“盘中正常量 + Rank1”：36 笔、25 日、胜率
`61.1111%`、均值 `+0.4920%`。同一组到验证段只有 13 笔、9 日，胜率降至
`46.1538%`、均值 `-1.4714%`、利润因子 `0.3490`，因此明确拒绝，不能把它解释为
龙头正常量低吸规律。验证段所有达到 30 笔和 20 日的类别中，最高胜率也只有
S+1 的 `52.9412%`，其双倍成本均值仍为 `-0.1587%`。

低胜率组的结果反而稳定：D-1 缩量、正常量、爆量，盘中缩量，Rank1、Rank2-3，
以及主升样本都在开发和验证保持低胜率或负期望。D-1 放量在验证均值短暂转正
`+0.1093%`，但胜率只有 `43.8356%`，双倍成本为 `-0.2011%`，也不是高组。
因此量能四档没有把这个买点从负期望中分离出来；“爆量更好”或“缩量更好”均不成立。

Rank1 比 Rank2-3 更差：验证胜率/均值分别是 `35.2113%/-1.4163%` 与
`42.0635%/-0.2453%`。主升样本验证为 `40.8027%/-0.4577%`；非主升对照只有
24 笔、7 日，虽然更差到 `37.5000%/-1.0626%`，但样本不足以定量证明主升优势。
它只能说明“只做主升”没有挽救当前买点，不能反向推出不做主升。

金/银不能在本样本上做同阶段验证：开发 57 日全部是 `GOLD/NORMAL`，而
`SILVER/NORMAL` 只出现在验证段 17 日。银行情的 148 笔均值虽为 `+0.6671%`、
双倍成本 `+0.3554%`，胜率仍只有 `49.3243%`，且少于 20 日并缺少开发期同类样本；
它与 block 5 完全重合，不能区分是银行情效应还是时间阶段效应。

赢亏画像也没有给出足够大的可交易差异：赢家/输家的 D-1 量比分别为
`1.3223/1.2911`，盘中量比分别为 `0.5218/0.5074`，主升占比分别为
`97.6424%/96.5116%`。这些差值远不足以形成高胜率分隔。赢家的买点相对前收中位深度
较浅（`-0.9912%` 对 `-1.2959%`），只能作为下一轮预注册假设，不能回头修改本轮规则。

另一个重要事实是，1,283 个信号中有 938 个在最早可判定的 09:50 出现，占
`73.1099%`。所以本轮实质上主要检验“早盘跌到前收以下即买”，而不是承接确认后的
精细低吸。结论固定为：该基准买点淘汰；保留低胜率归因证据，不选择任何高组或过滤器。

## Overall D+1 Results

| Segment | Signals | Closed | Days | Win | Mean | Median | PF | 2x mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all` | 1283 | 1283 | 93 | 39.6726% | -0.3436% | -1.0066% | 0.8374 | -0.6513% |
| `development` | 960 | 960 | 57 | 39.3750% | -0.2901% | -0.9035% | 0.8566 | -0.5975% |
| `validation` | 323 | 323 | 36 | 40.5573% | -0.5027% | -1.2608% | 0.7888 | -0.8112% |
| `block_1` | 324 | 324 | 19 | 35.4938% | -0.8029% | -1.2795% | 0.6560 | -1.1117% |
| `block_2` | 354 | 354 | 19 | 40.6780% | -0.0339% | -0.7654% | 0.9812 | -0.3404% |
| `block_3` | 282 | 282 | 19 | 42.1986% | -0.0226% | -0.8125% | 0.9884 | -0.3295% |
| `block_4` | 175 | 175 | 19 | 33.1429% | -1.4920% | -1.8684% | 0.4563 | -1.7978% |
| `block_5` | 148 | 148 | 17 | 49.3243% | 0.6671% | -0.5125% | 1.3420 | 0.3554% |

## Winner/Loser Profiles

| Segment | Outcome | Trades | Daily volume median | 5m volume median | Rank1 | Main rise | Gold normal | Silver normal |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all` | `loser` | 774 | 1.2911 | 0.5074 | 24.6770% | 96.5116% | 90.0517% | 9.6899% |
| `all` | `winner` | 509 | 1.3223 | 0.5218 | 22.3969% | 97.6424% | 85.2652% | 14.3418% |
| `development` | `loser` | 582 | 1.2767 | 0.5126 | 24.9141% | 97.9381% | 100.0000% | 0.0000% |
| `development` | `winner` | 378 | 1.3348 | 0.5335 | 23.5450% | 99.2063% | 100.0000% | 0.0000% |
| `validation` | `loser` | 192 | 1.3047 | 0.4970 | 23.9583% | 92.1875% | 59.8958% | 39.0625% |
| `validation` | `winner` | 131 | 1.2763 | 0.4663 | 19.0840% | 93.1298% | 42.7481% | 55.7252% |

## D-1 Daily Volume

| Cohort | Segment | Closed | Days | Win | Mean | PF | 2x mean | Dev class | Validation |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `daily_volume_class=contraction` | `development` | 185 | 47 | 41.0811% | -0.0960% | 0.9330 | -0.4053% | `low_candidate` | `low_confirmed` |
| `daily_volume_class=contraction` | `validation` | 66 | 26 | 36.3636% | -1.1101% | 0.4826 | -1.4165% | `low_candidate` | `low_confirmed` |
| `daily_volume_class=expansion` | `development` | 218 | 54 | 41.2844% | -0.1422% | 0.9295 | -0.4537% | `low_candidate` | `low_not_confirmed` |
| `daily_volume_class=expansion` | `validation` | 73 | 25 | 43.8356% | 0.1093% | 1.0481 | -0.2011% | `low_candidate` | `low_not_confirmed` |
| `daily_volume_class=explosion` | `development` | 186 | 48 | 36.5591% | -0.9021% | 0.6482 | -1.2059% | `low_candidate` | `low_confirmed` |
| `daily_volume_class=explosion` | `validation` | 45 | 23 | 42.2222% | -0.2883% | 0.8867 | -0.5955% | `low_candidate` | `low_confirmed` |
| `daily_volume_class=normal` | `development` | 371 | 57 | 38.8140% | -0.1670% | 0.9185 | -0.4728% | `low_candidate` | `low_confirmed` |
| `daily_volume_class=normal` | `validation` | 139 | 34 | 40.2878% | -0.6051% | 0.7575 | -0.9140% | `low_candidate` | `low_confirmed` |

## Signal 5m Volume

| Cohort | Segment | Closed | Days | Win | Mean | PF | 2x mean | Dev class | Validation |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `intraday_volume_class=contraction` | `development` | 707 | 57 | 38.1895% | -0.3527% | 0.8291 | -0.6598% | `low_candidate` | `low_confirmed` |
| `intraday_volume_class=contraction` | `validation` | 254 | 36 | 39.3701% | -0.5015% | 0.7979 | -0.8111% | `low_candidate` | `low_confirmed` |
| `intraday_volume_class=expansion` | `development` | 60 | 35 | 40.0000% | -0.3297% | 0.8493 | -0.6386% | `low_candidate` | `low_not_confirmed` |
| `intraday_volume_class=expansion` | `validation` | 17 | 13 | 52.9412% | -0.7772% | 0.5782 | -1.0829% | `low_candidate` | `low_not_confirmed` |
| `intraday_volume_class=explosion` | `development` | 19 | 17 | 36.8421% | -1.6635% | 0.4379 | -1.9647% | `neutral` | `not_applicable` |
| `intraday_volume_class=explosion` | `validation` | 8 | 7 | 37.5000% | 0.0206% | 1.0089 | -0.2702% | `neutral` | `not_applicable` |
| `intraday_volume_class=normal` | `development` | 174 | 48 | 44.2529% | 0.1277% | 1.0752 | -0.1809% | `neutral` | `not_applicable` |
| `intraday_volume_class=normal` | `validation` | 44 | 22 | 43.1818% | -0.4988% | 0.7530 | -0.8049% | `neutral` | `not_applicable` |

## Leader Rank

| Cohort | Segment | Closed | Days | Win | Mean | PF | 2x mean | Dev class | Validation |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `leader_rank_group=rank_1` | `development` | 234 | 52 | 38.0342% | -1.0078% | 0.6226 | -1.3125% | `low_candidate` | `low_confirmed` |
| `leader_rank_group=rank_1` | `validation` | 71 | 33 | 35.2113% | -1.4163% | 0.4575 | -1.7186% | `low_candidate` | `low_confirmed` |
| `leader_rank_group=rank_2_3` | `development` | 726 | 57 | 39.8072% | -0.0588% | 0.9676 | -0.3671% | `low_candidate` | `low_confirmed` |
| `leader_rank_group=rank_2_3` | `validation` | 252 | 35 | 42.0635% | -0.2453% | 0.8941 | -0.5555% | `low_candidate` | `low_confirmed` |

## Main-rise Status

| Cohort | Segment | Closed | Days | Win | Mean | PF | 2x mean | Dev class | Validation |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `main_rise_group=main_rise` | `development` | 945 | 57 | 39.6825% | -0.2544% | 0.8727 | -0.5621% | `low_candidate` | `low_confirmed` |
| `main_rise_group=main_rise` | `validation` | 299 | 36 | 40.8027% | -0.4577% | 0.8115 | -0.7662% | `low_candidate` | `low_confirmed` |
| `main_rise_group=non_main_rise` | `development` | 15 | 5 | 20.0000% | -2.5386% | 0.2841 | -2.8284% | `neutral` | `not_applicable` |
| `main_rise_group=non_main_rise` | `validation` | 24 | 7 | 37.5000% | -1.0626% | 0.4051 | -1.3713% | `neutral` | `not_applicable` |

## GOLD/SILVER Regime

| Cohort | Segment | Closed | Days | Win | Mean | PF | 2x mean | Dev class | Validation |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `market_regime=GOLD/DANGER` | `development` | 0 | 0 | - | - | - | - | `neutral` | `not_applicable` |
| `market_regime=GOLD/DANGER` | `validation` | 3 | 1 | 66.6667% | -0.9941% | 0.2337 | -1.2971% | `neutral` | `not_applicable` |
| `market_regime=GOLD/NORMAL` | `development` | 960 | 57 | 39.3750% | -0.2901% | 0.8566 | -0.5975% | `low_candidate` | `low_not_confirmed` |
| `market_regime=GOLD/NORMAL` | `validation` | 171 | 17 | 32.7485% | -1.4889% | 0.4615 | -1.7951% | `low_candidate` | `low_not_confirmed` |
| `market_regime=SILVER/DANGER` | `development` | 0 | 0 | - | - | - | - | `neutral` | `not_applicable` |
| `market_regime=SILVER/DANGER` | `validation` | 1 | 1 | 0.0000% | -3.5035% | 0.0000 | -3.7625% | `neutral` | `not_applicable` |
| `market_regime=SILVER/NORMAL` | `development` | 0 | 0 | - | - | - | - | `neutral` | `not_applicable` |
| `market_regime=SILVER/NORMAL` | `validation` | 148 | 17 | 49.3243% | 0.6671% | 1.3420 | 0.3554% | `neutral` | `not_applicable` |

## Classification

- Development high candidates: `1`
- Development low candidates: `28`
- Confirmed high cohorts: `0`
- Confirmed low cohorts: `15`
- Outcome labels are descriptive only and are never entry features.
- No cohort is promoted to a buy rule in this study.

## Reproduce

```bash
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-outcome-group-5m-manifest --format json

docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-outcome-group-study --format json
```
