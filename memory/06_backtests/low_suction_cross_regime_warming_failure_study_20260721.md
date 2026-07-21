# 低吸 warming 失败归因与支撑相关性研究

- 研究状态：`warming_failure_attributed_candidate_reused_history`
- 正式策略：`false`
- 原 V3 全历史：`107` 笔，胜率 `+67.2897%`，均值 `+2.3158%`，PF `2.8683`
- 候选全历史：`86` 笔，胜率 `+72.0930%`，均值 `+2.4288%`，PF `3.1133`
- 候选顺序验证：`41` 笔，胜率 `+75.6098%`，均值 `+2.8270%`，PF `4.3646`
- 四仓现金：`84` 笔，胜率 `+71.4286%`，复利 `+65.7643%`，回撤 `-4.0879%`
- 历史数字门：`true`

## 候选规则

rotation 保持 V3；warming 要求确认日最低价没有跌破支撑，且最多高于支撑 8%。
8% 复用既有强收复阈值，没有在 blocks 4-5 搜索新数字。

## 验证段 warming 个股

| 信号 | 日期 | 股票 | 概念 | 波次 | 排名 | 支撑 | 最低价距支撑 | 收益 | 结果 |
| --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| `causal-leader-pullback-close-v2:a1f07b13a90671922eac9ac20d4a5e2f4d256a99:603335.SSE:2025-09-15:ma20` | 2025-09-15 | 迪生力 `603335.SSE` | 汽车一体化压铸 | 1 | 3 | ma20 | +0.5226% | +2.5444% | winner |
| `causal-leader-pullback-close-v2:797b35808e9ba957908ca993de64cf812000b186:002562.SZSE:2025-09-24:ma20` | 2025-09-24 | 兄弟科技 `002562.SZSE` | 中俄贸易概念 | 1 | 3 | ma20 | +0.2946% | +1.3979% | winner |
| `causal-leader-pullback-close-v2:fe35e7b1c1cd912ece3b9bd703e62b6ca8e1657b:603283.SSE:2025-10-09:ma10` | 2025-10-09 | 赛腾股份 `603283.SSE` | 高带宽内存 | 1 | 2 | ma10 | +3.1637% | -2.1371% | loser |
| `causal-leader-pullback-close-v2:c715bcc59dcb164babd6c2505939214d1039c088:600391.SSE:2025-12-31:ma10` | 2025-12-31 | 航发科技 `600391.SSE` | 航母概念 | 2 | 2 | ma10 | -0.9198% | -3.2997% | loser |
| `causal-leader-pullback-close-v2:c5d1bebba40bdb4ec98694b39389272e8e974a78:605358.SSE:2026-01-05:ma20` | 2026-01-05 | 立昂微 `605358.SSE` | 氮化镓 | 1 | 1 | ma20 | +2.4101% | +9.8000% | winner |
| `causal-leader-pullback-close-v2:94947fe6b6e756df5c917835d54019102514ac5d:002865.SZSE:2026-01-06:ma10` | 2026-01-06 | 钧达股份 `002865.SZSE` | TOPCon电池 | 1 | 1 | ma10 | +0.3011% | +7.2694% | winner |
| `causal-leader-pullback-close-v2:38a69aa41555da75efb9a4a0ca0880f6922da493:000917.SZSE:2026-01-09:ma10` | 2026-01-09 | 电广传媒 `000917.SZSE` | 网络游戏 | 1 | 2 | ma10 | +5.5861% | +9.8332% | winner |
| `causal-leader-pullback-close-v2:913e2861469c3880f56ed052113532cac80e9955:600133.SSE:2026-01-14:ma10` | 2026-01-14 | 东湖高新 `600133.SSE` | 湖北自贸 | 1 | 3 | ma10 | +0.0207% | +2.0599% | winner |
| `causal-leader-pullback-close-v2:2edff480b4a13b7d60244e059ce92b2a00358e3d:002721.SZSE:2026-01-28:ma5` | 2026-01-28 | 金一文化 `002721.SZSE` | 移动支付 | 1 | 3 | ma5 | -0.9928% | -2.4785% | loser |
| `causal-leader-pullback-close-v2:3c3f2e9bed020aec9caa13de1fbe0158ff8de5ee:002160.SZSE:2026-01-28:ma10` | 2026-01-28 | 常铝股份 `002160.SZSE` | 汽车热管理 | 2 | 2 | ma10 | -0.6827% | +6.8901% | winner |
| `causal-leader-pullback-close-v2:62a15648cd5f978830d9c6c3213129ff1cfe1855:600170.SSE:2026-01-28:ma20` | 2026-01-28 | 上海建工 `600170.SSE` | 房屋检测 | 1 | 3 | ma20 | -0.4352% | -3.0302% | loser |
| `causal-leader-pullback-close-v2:a037560f0c45cf37ddc29e3feb75e19fd0e6a71c:603031.SSE:2026-02-09:ma20` | 2026-02-09 | 安孚科技 `603031.SSE` | 跨境电商 | 1 | 2 | ma20 | +4.4151% | -1.7488% | loser |
| `causal-leader-pullback-close-v2:afd7015f1c50084ba2e210d49cc9c250ef24617c:002830.SZSE:2026-02-09:ma10` | 2026-02-09 | 名雕股份 `002830.SZSE` | 网红经济 | 1 | 3 | ma10 | +22.2809% | -8.8595% | loser |
| `causal-leader-pullback-close-v2:e0ba5c7bcd30f2faad88bd0198633ab06c3c3c5c:600590.SSE:2026-02-09:ma20` | 2026-02-09 | 泰豪科技 `600590.SSE` | 发电机概念 | 2 | 2 | ma20 | +6.0725% | +0.5098% | winner |
| `causal-leader-pullback-close-v2:70399ba410d8828f67ca885316aa125874bffb68:000962.SZSE:2026-02-11:ma20` | 2026-02-11 | 东方钽业 `000962.SZSE` | 超导概念 | 7 | 3 | ma20 | +0.0398% | +9.7910% | winner |
| `causal-leader-pullback-close-v2:3a160ebaab0b6d0d39c460ee14a42838be7a168f:600330.SSE:2026-02-24:ma10` | 2026-02-24 | 天通股份 `600330.SSE` | MicroLED | 2 | 1 | ma10 | +2.3552% | -4.9046% | loser |
| `causal-leader-pullback-close-v2:6394963232344e96db692a301245e1ffcb02162f:600487.SSE:2026-02-24:ma10` | 2026-02-24 | 亨通光电 `600487.SSE` | 液冷概念 | 3 | 1 | ma10 | +3.8978% | -4.7702% | loser |
| `causal-leader-pullback-close-v2:bcda8146700b0256354072007727949188c51533:002491.SZSE:2026-02-24:ma10` | 2026-02-24 | 通鼎互联 `002491.SZSE` | 北交所概念 | 3 | 1 | ma10 | +1.0344% | -6.6769% | loser |
| `causal-leader-pullback-close-v2:c0bfd3fabee91be7eca7a54aea9021dc11496d36:603618.SSE:2026-02-26:ma10` | 2026-02-26 | 杭电股份 `603618.SSE` | 锂电池概念 | 1 | 1 | ma10 | +0.2138% | +9.8000% | winner |
| `causal-leader-pullback-close-v2:6394963232344e96db692a301245e1ffcb02162f:600498.SSE:2026-03-10:ma20` | 2026-03-10 | 烽火通信 `600498.SSE` | 液冷概念 | 1 | 2 | ma20 | +10.7446% | -0.4972% | loser |
| `causal-leader-pullback-close-v2:f3880d7a6560b0698f6afa0cab70884a3f96cb9e:000833.SZSE:2026-03-11:ma10` | 2026-03-11 | 粤桂股份 `000833.SZSE` | 磷化工 | 2 | 2 | ma10 | -0.3110% | -0.0183% | loser |
| `causal-leader-pullback-close-v2:09f3a60443f9ce2b8505e013b61cf7b8b30d5d07:600664.SSE:2026-04-14:ma20` | 2026-04-14 | 哈药股份 `600664.SSE` | 肝炎概念 | 1 | 1 | ma20 | +1.6568% | +9.7010% | winner |
| `causal-leader-pullback-close-v2:5514dfaf23d77e70e286054cdc774fa5139b3007:002107.SZSE:2026-04-14:ma10` | 2026-04-14 | 沃华医药 `002107.SZSE` | 流感 | 1 | 3 | ma10 | +0.2246% | +1.3326% | winner |
| `causal-leader-pullback-close-v2:59f26af99275d9db116f4cd1451af48641c7e945:002975.SZSE:2026-05-06:ma10` | 2026-05-06 | 博杰股份 `002975.SZSE` | 5G概念 | 2 | 2 | ma10 | +3.5630% | +3.0708% | winner |
| `causal-leader-pullback-close-v2:7be5c7fcdb13f7ee658a671c32b0a9783d8449c4:600770.SSE:2026-05-06:ma5` | 2026-05-06 | 综艺股份 `600770.SSE` | 电商概念 | 1 | 2 | ma5 | +2.1813% | -2.7060% | loser |
| `causal-leader-pullback-close-v2:e982a229569b69fcbb521f8a1bd0d0cb7c025317:002787.SZSE:2026-05-06:ma10` | 2026-05-06 | 华源控股 `002787.SZSE` | 锂电池概念 | 2 | 2 | ma10 | +4.7943% | +7.7194% | winner |
| `causal-leader-pullback-close-v2:104083f0044e5e3f74f711316c08991e604460af:600172.SSE:2026-05-25:ma10` | 2026-05-25 | 黄河旋风 `600172.SSE` | 培育钻石 | 1 | 1 | ma10 | +0.4320% | +9.8083% | winner |
| `causal-leader-pullback-close-v2:7663d5ce9799298bc93f61da116304ffc8b6b964:002552.SZSE:2026-06-15:ma10` | 2026-06-15 | 宝鼎科技 `002552.SZSE` | PCB | 6 | 1 | ma10 | +0.5242% | +9.8031% | winner |

## 未解除边界

- The frozen V3 source report is read-only and its trade identities are unchanged.
- Candidate selection receives causal feature mappings with outcome fields prohibited.
- Blocks 4-5 were previously inspected and are rejection evidence, not a fresh holdout.
- No API, paper strategy, or formal metrics are changed by this report.

## 失败门
