# AlphaAgent Leader MA5 Daily-close Low-suction Study

Research status: `historical_same_close_proxy_not_formal_validation`.
Formal strategy/metrics: `false/null`.

## Contract

- Bar interval: `1d`.
- Recognition: `strong_days_ge_9_5pct >= 1`.
- Entry: `signal_day_close`.
- Entry assumption: `same_close_research_proxy`.
- Exit: `structural_trigger_day_close` after the fixed structural trigger.
- Fund-cycle rows read: `0`.
- Minute rows read: `0`.
- This is not a point-in-time executable fill.

## Coverage

- Frozen candidates: `35`.
- Daily-close entries: `35`.
- Closed four-position trades: `35`.

## Fixed-capacity Cash Accounts

| Capacity | Accepted | Skipped | Final equity | Compound | Drawdown | Win | Fees |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | 22 | 13 | 145488.32 | 45.4883% | -27.9994% | 63.6364% | 3000.05 |
| `2` | 31 | 4 | 121793.41 | 21.7934% | -26.8289% | 61.2903% | 1989.86 |
| `3` | 34 | 1 | 121193.76 | 21.1938% | -16.7521% | 64.7059% | 1409.80 |
| `4` | 35 | 0 | 117903.65 | 17.9037% | -12.6576% | 65.7143% | 1059.26 |

## Four-position Result

- Closed/winning: `35/23`.
- Win rate: `65.7143%`.
- Compound return: `17.9037%`.
- Maximum drawdown: `-12.6576%`.

## Time-block Stability

| Block | Signals | Closed | Win | Mean | PF |
| --- | ---: | ---: | ---: | ---: | ---: |
| `all` | 35 | 35 | 65.7143% | 2.2422% | 1.7671 |
| `block_1` | 3 | 3 | 66.6667% | 1.5711% | 1.5151 |
| `block_2` | 7 | 7 | 85.7143% | 4.9579% | 3.4869 |
| `block_3` | 5 | 5 | 60.0000% | 2.1367% | 1.6684 |
| `block_4` | 13 | 13 | 61.5385% | 1.7955% | 1.7063 |
| `block_5` | 7 | 7 | 57.1429% | 0.7193% | 1.1669 |

## Cases

| Date | Stock | Concept | Rank | Entry close | Exit close | Net |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 2023-06-14 | 特发信息 `000070.SZSE` | F5G概念 | 3 | 10.15 | 9.25 | -9.1509% |
| 2023-07-27 | 中华企业 `600675.SSE` | 土地流转 | 2 | 3.53 | 3.69 | 4.2069% |
| 2023-08-09 | 首创证券 `601136.SSE` | 互联网金融 | 1 | 22.70 | 24.97 | 9.6573% |
| 2023-10-12 | 上海沿浦 `605128.SSE` | 华为汽车 | 3 | 56.40 | 57.20 | 1.1025% |
| 2023-11-01 | 利通电子 `603629.SSE` | 毫米波概念 | 2 | 33.70 | 37.20 | 10.0419% |
| 2023-11-10 | 中科金财 `002657.SZSE` | 移动支付 | 3 | 20.90 | 24.68 | 17.7182% |
| 2023-11-17 | 北特科技 `603009.SSE` | 汽车热管理 | 3 | 12.94 | 13.71 | 5.6205% |
| 2023-12-11 | 力盛体育 `002858.SZSE` | Web3.0 | 3 | 20.20 | 21.18 | 4.5248% |
| 2024-03-07 | 工业富联 `601138.SSE` | HS300_ | 1 | 22.61 | 24.87 | 9.6529% |
| 2024-03-25 | 中科金财 `002657.SZSE` | Web3.0 | 2 | 18.12 | 15.64 | -13.9554% |
| 2024-05-22 | 津滨发展 `000897.SZSE` | 京津冀 | 2 | 2.69 | 2.45 | -9.2057% |
| 2024-06-14 | 盛剑科技 `603324.SSE` | 光刻机(胶) | 3 | 28.67 | 26.81 | -6.7789% |
| 2024-08-01 | 金龙汽车 `600686.SSE` | 汽车整车 | 3 | 16.71 | 18.10 | 7.9809% |
| 2024-09-25 | 拓维信息 `002261.SZSE` | 在线教育 | 1 | 14.52 | 15.03 | 3.1899% |
| 2024-10-11 | 梦网科技 `002123.SZSE` | 云计算 | 3 | 9.49 | 10.96 | 15.1302% |
| 2024-10-14 | 金固股份 `002488.SZSE` | 阿里概念 | 3 | 10.26 | 10.17 | -1.1860% |
| 2024-10-15 | 中光学 `002189.SZSE` | 3D摄像头 | 3 | 22.83 | 23.79 | 3.8804% |
| 2024-10-24 | 欧菲光 `002456.SZSE` | 3D摄像头 | 1 | 12.66 | 14.58 | 14.8071% |
| 2024-10-24 | 泰豪科技 `600590.SSE` | 北斗导航 | 2 | 5.68 | 5.98 | 4.9537% |
| 2024-10-25 | 苏豪汇鸿 `600981.SSE` | 参股新三板 | 1 | 2.69 | 2.92 | 8.2120% |
| 2024-10-25 | 智度股份 `000676.SZSE` | Web3.0 | 3 | 10.96 | 11.90 | 8.2384% |
| 2024-10-31 | 泰达股份 `000652.SZSE` | 滨海新区 | 1 | 4.83 | 4.81 | -0.7243% |
| 2024-11-07 | 五矿资本 `600390.SSE` | 券商概念 | 2 | 8.81 | 7.14 | -19.2082% |
| 2024-11-07 | 剑桥科技 `603083.SSE` | 边缘计算 | 2 | 48.64 | 52.06 | 6.6978% |
| 2024-12-10 | 信雅达 `600571.SSE` | IPO受益 | 1 | 15.48 | 13.71 | -11.7100% |
| 2024-12-24 | 精达股份 `600577.SSE` | 超导概念 | 1 | 8.05 | 8.10 | 0.3076% |
| 2025-02-21 | 南兴股份 `002757.SZSE` | VPN | 2 | 22.30 | 24.53 | 9.6573% |
| 2025-02-21 | XD华胜天 `600410.SSE` | 新型工业化 | 3 | 10.59 | 10.60 | -0.2174% |
| 2025-05-20 | 金达威 `002626.SZSE` | 长寿药 | 2 | 19.13 | 18.12 | -5.5748% |
| 2025-06-30 | 海联金汇 `002537.SZSE` | 跨境支付 | 2 | 11.08 | 10.30 | -7.3293% |
| 2025-07-08 | 中京电子 `002579.SZSE` | 无线耳机 | 1 | 15.53 | 12.89 | -17.2579% |
| 2025-07-29 | 盛新锂能 `002240.SZSE` | 锂矿概念 | 3 | 16.22 | 18.44 | 13.3326% |
| 2025-08-04 | 长飞光纤 `601869.SSE` | 碳化硅 | 2 | 51.82 | 57.00 | 9.6535% |
| 2025-08-11 | 夏厦精密 `001306.SZSE` | 机器人执行器 | 3 | 100.10 | 110.57 | 10.1154% |
| 2025-08-19 | 世运电路 `603920.SSE` | 英伟达概念 | 3 | 37.27 | 38.17 | 2.0957% |

## Boundaries

- all 35 historical candidates and all five time blocks were already viewed
- same_close_research_proxy uses the completed D close both to confirm the signal and to price the entry
- the same-close convention is not a point-in-time executable fill and must not be presented as broker execution
- current concept memberships remain a survivorship proxy
- causal Top3 did not pass the prior absolute historical identity gate
- minute bars, fund cycles, GOLD/SILVER and volume do not select candidates
- formal win rate, return and compounding remain null

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-leader-ma5-close-study --format markdown
```
