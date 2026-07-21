# AlphaAgent Leader MA5 Low-suction Scheme

Research status: `forward_shadow_candidate_partial_historical_minute_coverage`.
Formal strategy/metrics: `false/null`.

## Concrete Contract

- Recognition: `strong_days_ge_9_5pct >= 1`.
- Pullback: first stabilized MA5 reclaim after a visible 5% pullback and two confirmed higher highs.
- Feature cutoff: `D 14:50 completed 5m bar`.
- Entry: `D 14:55 5m bar open`.
- Holding style: `multi-session swing; no fixed D+1 exit`.
- Primary exit: `after either the first later daily high above the reference peak or the second consecutive close below MA20, sell at the next stock-session open`.
- Portfolio: max `4` positions; `current equity / 4, 100-share lots, no leverage`.

## Coverage

- Parent/scheme rows: `57/35`.
- Minute complete/required pairs: `46/70`.
- 14:50 causal stock gate passed/audited: `23/23`.

## Non-causal Parent Daily Comparator

| Segment | Signals | Closed | Win | Mean | PF | Compound | Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all` | 35 | 35 | 71.4286% | 3.0466% | 2.1875 | - | - |
| `block_1` | 3 | 3 | 66.6667% | 2.0717% | 1.7065 | - | - |
| `block_2` | 7 | 7 | 85.7143% | 5.8895% | 4.7542 | - | - |
| `block_3` | 5 | 5 | 60.0000% | 3.7019% | 2.3922 | - | - |
| `block_4` | 13 | 13 | 76.9231% | 2.7109% | 2.1917 | - | - |
| `block_5` | 7 | 7 | 57.1429% | 0.7770% | 1.2004 | - | - |

## Causal D+1-open To Next-open Structural Cash Account

- Initial cash: `100000.00 CNY`.
- Entry is D+1 open; a daily structural trigger executes at the next stock-session open. All four fixed capacities are shown without choosing a historical return winner.

| Capacity | Accepted | Skipped | Rejected | Final equity | Compound | Drawdown | Closed | Win | Fees |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | 22 | 13 | 0 | 156166.59 | 56.1666% | -28.6195% | 22 | 68.1818% | 2874.92 |
| `2` | 31 | 4 | 0 | 120098.73 | 20.0987% | -28.5282% | 31 | 61.2903% | 1930.59 |
| `3` | 34 | 1 | 0 | 120331.55 | 20.3315% | -18.5936% | 34 | 64.7059% | 1387.12 |
| `4` | 35 | 0 | 0 | 116469.56 | 16.4696% | -14.0657% | 35 | 65.7143% | 1046.85 |

## D 14:55 Entry To Structural Exit Cash Account

- Executable 14:55 entries: `23/35`.
- Initial cash: `100000.00 CNY`.
- A prior-peak rebreak or second consecutive close below MA20 triggers an exit at the next stock-session open; unavailable 5-minute entries are not fabricated.

| Capacity | Accepted | Skipped | Rejected | Final equity | Compound | Drawdown | Closed | Win | Fees |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | 11 | 12 | 0 | 170410.42 | 70.4104% | -30.6512% | 11 | 72.7273% | 1867.66 |
| `2` | 19 | 4 | 0 | 117182.71 | 17.1827% | -29.8337% | 19 | 57.8947% | 1214.58 |
| `3` | 22 | 1 | 0 | 117582.85 | 17.5828% | -19.0627% | 22 | 63.6364% | 924.86 |
| `4` | 23 | 0 | 0 | 114062.81 | 14.0628% | -14.4580% | 23 | 65.2174% | 702.79 |

### Hybrid Trade Stability

| Segment | Signals | Closed | Win | Mean | PF | Compound | Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all` | 23 | 23 | 65.2174% | 2.7261% | 1.9278 | - | - |
| `block_1` | 0 | 0 | - | - | - | - | - |
| `block_2` | 0 | 0 | - | - | - | - | - |
| `block_3` | 3 | 3 | 100.0000% | 13.1768% | - | - | - |
| `block_4` | 13 | 13 | 61.5385% | 1.3508% | 1.4562 | - | - |
| `block_5` | 7 | 7 | 57.1429% | 0.8012% | 1.1928 | - | - |

## Hybrid Winner/Loser Diagnostics

These fields are descriptive only and do not change the frozen candidate set.

- Closed/winners/losers: `23/15/8`.

| Numeric feature | Winner mean | Loser mean | Difference |
| --- | ---: | ---: | ---: |
| `volume_ratio_prior5` | 1.0693 | 1.3838 | -0.3145 |
| `stock_ma5_ma10_gap_pct` | 9.4668 | 7.1788 | 2.2879 |
| `tail_return_from_previous_close_pct` | 2.8625 | 2.0467 | 0.8158 |
| `tail_drawdown_from_session_high_pct` | -2.9973 | -3.1865 | 0.1892 |
| `tail_vs_vwap_pct` | 1.1317 | 0.4603 | 0.6714 |
| `last_15m_volume_ratio` | 1.8227 | 1.3775 | 0.4452 |
| `support_break_count` | 0.1333 | 0.5000 | -0.3667 |

| Active direction | Trades | Win | Mean |
| --- | ---: | ---: | ---: |
| `GOLD` | 23 | 65.2174% | 2.7261% |

## Cases

| Date | Stock | Concept | Block | Parent close | Swing | Status |
| --- | --- | --- | --- | ---: | ---: | --- |
| 2023-06-14 | 特发信息 `000070.SZSE` | F5G概念 | block_1 | -8.7968% | - | unavailable |
| 2023-07-27 | 中华企业 `600675.SSE` | 土地流转 | block_1 | 4.3326% | - | unavailable |
| 2023-08-09 | 首创证券 `601136.SSE` | 互联网金融 | block_1 | 10.6792% | - | unavailable |
| 2023-10-12 | 上海沿浦 `605128.SSE` | 华为汽车 | block_2 | 2.1622% | - | unavailable |
| 2023-11-01 | 利通电子 `603629.SSE` | 毫米波概念 | block_2 | 11.6797% | - | unavailable |
| 2023-11-10 | 中科金财 `002657.SZSE` | 移动支付 | block_2 | 21.0181% | - | unavailable |
| 2023-11-17 | 北特科技 `603009.SSE` | 汽车热管理 | block_2 | 5.7505% | - | unavailable |
| 2023-12-11 | 力盛体育 `002858.SZSE` | Web3.0 | block_2 | 4.1350% | - | unavailable |
| 2024-03-07 | 工业富联 `601138.SSE` | HS300_ | block_2 | 7.4623% | - | unavailable |
| 2024-03-25 | 中科金财 `002657.SZSE` | Web3.0 | block_2 | -10.9815% | - | unavailable |
| 2024-05-22 | 津滨发展 `000897.SZSE` | 京津冀 | block_3 | -7.3970% | - | unavailable |
| 2024-06-14 | 盛剑科技 `603324.SSE` | 光刻机(胶) | block_3 | -5.8982% | - | unavailable |
| 2024-08-01 | 金龙汽车 `600686.SSE` | 汽车整车 | block_3 | 10.2332% | 6.8612% | closed |
| 2024-09-25 | 拓维信息 `002261.SZSE` | 在线教育 | block_4 | 5.7197% | 10.0698% | closed |
| 2024-10-11 | 梦网科技 `002123.SZSE` | 云计算 | block_4 | 15.2900% | 22.1130% | closed |
| 2024-10-14 | 金固股份 `002488.SZSE` | 阿里概念 | block_4 | 0.0959% | -2.5463% | closed |
| 2024-10-15 | 中光学 `002189.SZSE` | 3D摄像头 | block_3 | 7.0588% | 6.4655% | closed |
| 2024-10-24 | 欧菲光 `002456.SZSE` | 3D摄像头 | block_3 | 14.5128% | 26.2039% | closed |
| 2024-10-24 | 泰豪科技 `600590.SSE` | 北斗导航 | block_4 | 7.3540% | 6.0291% | closed |
| 2024-10-25 | 智度股份 `000676.SZSE` | Web3.0 | block_4 | 9.4774% | 3.7482% | closed |
| 2024-10-25 | 苏豪汇鸿 `600981.SSE` | 参股新三板 | block_4 | 8.7552% | 3.7649% | closed |
| 2024-10-31 | 泰达股份 `000652.SZSE` | 滨海新区 | block_4 | 0.0083% | 1.3430% | closed |
| 2024-11-07 | 五矿资本 `600390.SSE` | 券商概念 | block_4 | -19.8850% | -19.9353% | closed |
| 2024-11-07 | 剑桥科技 `603083.SSE` | 边缘计算 | block_4 | 4.8868% | 7.0720% | closed |
| 2024-12-10 | 信雅达 `600571.SSE` | IPO受益 | block_4 | -8.7390% | -11.8388% | closed |
| 2024-12-24 | 精达股份 `600577.SSE` | 超导概念 | block_4 | 2.3316% | -0.5633% | closed |
| 2025-02-21 | 南兴股份 `002757.SZSE` | VPN | block_4 | 10.8960% | 1.9136% | closed |
| 2025-02-21 | XD华胜天 `600410.SSE` | 新型工业化 | block_4 | -0.9491% | -3.6094% | closed |
| 2025-05-20 | 金达威 `002626.SZSE` | 长寿药 | block_5 | -3.8683% | -5.7718% | closed |
| 2025-06-30 | 海联金汇 `002537.SZSE` | 跨境支付 | block_5 | -6.5636% | -6.9092% | closed |
| 2025-07-08 | 中京电子 `002579.SZSE` | 无线耳机 | block_5 | -16.7155% | -16.4071% | closed |
| 2025-07-29 | 盛新锂能 `002240.SZSE` | 锂矿概念 | block_5 | 12.6519% | 15.2379% | closed |
| 2025-08-04 | 长飞光纤 `601869.SSE` | 碳化硅 | block_5 | 6.7418% | 5.1699% | closed |
| 2025-08-11 | 夏厦精密 `001306.SZSE` | 机器人执行器 | block_5 | 10.3700% | 12.0446% | closed |
| 2025-08-19 | 世运电路 `603920.SSE` | 英伟达概念 | block_5 | 2.8229% | 2.2439% | closed |

## Rejected Experiment: Fixed D+1 Exit

The D+1 10:35 exit is retained only as rejected evidence and is not part of the current swing contract.

| Segment | Signals | Closed | Win | Mean | PF | Compound | Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all` | 35 | 23 | 56.5217% | 0.8175% | 1.5994 | 2.0904% | -9.0004% |
| `block_1` | 3 | 0 | - | - | - | - | - |
| `block_2` | 7 | 0 | - | - | - | - | - |
| `block_3` | 5 | 3 | 66.6667% | 1.2545% | 1.8586 | 3.5634% | -4.3834% |
| `block_4` | 13 | 13 | 61.5385% | 1.2239% | 1.8584 | 1.9987% | -7.9916% |
| `block_5` | 7 | 7 | 42.8571% | -0.1246% | 0.8968 | -1.1578% | -4.3056% |

## Boundaries

- all five historical blocks were already viewed
- current concept memberships remain a survivorship proxy
- causal Top3 did not pass the prior absolute historical identity gate
- historical concept main-rise state is a completed-daily-bar proxy; live shadow must recalculate it at 14:50
- the 9.5 percent recognition threshold is a natural A-share strong-day boundary
- volume, MA gap, GOLD/SILVER and future continuation never select candidates
- fixed capacities 1/2/3/4 are all reported; reused history does not select one
- capacity 4 is frozen now as the forward 25 percent risk cap and must not be retuned on these reused rows
- formal win rate, return and compounding remain null

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-leader-ma5-scheme-study --format markdown
```
