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

## 最终候选赢家/输家特征

以下仅描述最终候选，不增加规则阈值。

| 特征 | 开发赢家中位数 | 开发输家中位数 | 验证赢家中位数 | 验证输家中位数 | 跨段方向一致 |
| --- | ---: | ---: | ---: | ---: | --- |
| `signal_daily_return_pct` | 10.0000 | 10.0088 | 10.0000 | 9.9986 | `false` |
| `volume_ratio_prior5` | 0.8038 | 1.1268 | 1.0454 | 0.8938 | `false` |
| `peak_gap_pct` | -2.0426 | -3.8215 | -2.1250 | -1.9882 | `false` |
| `low_support_gap_pct` | 1.4395 | 1.1507 | 0.4321 | 2.2682 | `false` |
| `close_support_gap_pct` | 10.7370 | 11.2056 | 9.9102 | 8.6923 | `false` |
| `turnover_expansion` | 2.1343 | 3.3645 | 1.7471 | 1.4259 | `false` |
| `close_location` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | `true` |
| `sessions_since_ignition` | 5.0000 | 6.5000 | 7.0000 | 6.5000 | `false` |
| `signal_ma5_gap_pct` | 5.9184 | 7.3592 | 5.4674 | 5.3842 | `false` |
| `signal_ma10_gap_pct` | 10.4756 | 11.4744 | 8.8013 | 9.4885 | `true` |
| `signal_ma20_gap_pct` | 15.7138 | 22.0060 | 16.7534 | 22.0372 | `true` |
| `support_day_daily_return_pct` | -2.1792 | -1.2037 | -3.0638 | -2.3661 | `true` |
| `support_day_volume_ratio_prior5` | 0.7025 | 0.8702 | 0.8735 | 0.7875 | `false` |
| `support_day_close_location` | 0.3562 | 0.4115 | 0.2857 | 0.2201 | `false` |
| `campaign_day` | 10.5000 | 10.0000 | 18.0000 | 42.5000 | `false` |
| `concept_gain_pct` | 2.8756 | 1.0577 | 7.1058 | 13.5739 | `false` |

## 最终候选逐笔

| 信号 | 日期 | 股票 | 概念 | 波次 | 排名 | 支撑 | 最低价距支撑 | 收益 | 结果 |
| --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| `causal-leader-pullback-close-v2:970a240798d82002aa3926cb8247f159c947b708:000572.SZSE:2024-08-01:ma10` | 2024-08-01 | 海马汽车 `000572.SZSE` | 共享经济 | 1 | 2 | ma10 | +1.2448% | -4.6444% | loser |
| `causal-leader-pullback-close-v2:57d6c1e6a0f93b15e63aa92b292d9c09e902d4a8:000158.SZSE:2024-09-30:ma5` | 2024-09-30 | 常山北明 `000158.SZSE` | 智慧城市 | 1 | 1 | ma5 | +1.0068% | +9.8076% | winner |
| `causal-leader-pullback-close-v2:6cb5462aadae45957a43abfd70bc4908720e88b9:600316.SSE:2024-11-05:ma10` | 2024-11-05 | 洪都航空 `600316.SSE` | 航天航空 | 3 | 1 | ma10 | +2.3792% | +1.2394% | winner |
| `causal-leader-pullback-close-v2:daa23ab393b3767d77481ec2254b31c8afdb7980:002348.SZSE:2024-11-06:ma20` | 2024-11-06 | 高乐股份 `002348.SZSE` | 股权转让 | 1 | 2 | ma20 | +5.1010% | +9.8592% | winner |
| `causal-leader-pullback-close-v2:6609b2b4f5aeb228ce6a5fb5d446bdbef40019ee:600327.SSE:2024-11-18:ma20` | 2024-11-18 | 大东方 `600327.SSE` | 社区团购 | 2 | 3 | ma20 | +0.7607% | +2.2775% | winner |
| `causal-leader-pullback-close-v2:f47f0a1a64dd890ddf5a499e2f90b4cc3062b342:000812.SZSE:2024-11-19:ma10` | 2024-11-19 | 陕西金叶 `000812.SZSE` | 在线教育 | 1 | 1 | ma10 | +0.6514% | +4.3541% | winner |
| `causal-leader-pullback-close-v2:69c81a656ada1dac3a54bdbc93833bcb81cb5a5a:002400.SZSE:2024-11-29:ma20` | 2024-11-29 | 省广集团 `002400.SZSE` | 体育产业 | 5 | 1 | ma20 | +1.8781% | +9.8467% | winner |
| `causal-leader-pullback-close-v2:3fb9951676063825c0e1dd1424a703223bfcdee3:603009.SSE:2024-12-10:ma10` | 2024-12-10 | 北特科技 `603009.SSE` | 上海自贸 | 2 | 1 | ma10 | +1.6456% | -5.2552% | loser |
| `causal-leader-pullback-close-v2:9334ea247062bb696ee74925604b692fd1c5ec83:000659.SZSE:2024-12-12:ma10` | 2024-12-12 | 珠海中富 `000659.SZSE` | 包装材料 | 1 | 3 | ma10 | +0.8429% | +4.1597% | winner |
| `causal-leader-pullback-close-v2:7383884cef6b14796f940584b2f8b9e92a344d9e:002419.SZSE:2024-12-18:ma20` | 2024-12-18 | 天虹股份 `002419.SZSE` | 白酒 | 1 | 3 | ma20 | +1.6242% | -1.1804% | loser |
| `causal-leader-pullback-close-v2:38240a4fa4ceb9b8c9d233ef8296f101c225271c:002429.SZSE:2024-12-26:ma5` | 2024-12-26 | 兆驰股份 `002429.SZSE` | 汽车芯片 | 1 | 1 | ma5 | -2.3967% | -0.8462% | loser |
| `causal-leader-pullback-close-v2:e1bf068218e06222bf4f80a8e813f74fb8093c4d:600255.SSE:2024-12-26:ma10` | 2024-12-26 | 鑫科材料 `600255.SSE` | 铜缆高速连接 | 1 | 1 | ma10 | +1.0566% | -3.2374% | loser |
| `causal-leader-pullback-close-v2:f86a67cefcf0164de4d51e70aa919386761422cc:002449.SZSE:2024-12-27:ma5` | 2024-12-27 | 国星光电 `002449.SZSE` | AI眼镜 | 1 | 1 | ma5 | -4.2389% | +2.3244% | winner |
| `causal-leader-pullback-close-v2:1a31f72e6549016a2facedd548dfe0d0f8968ccf:600797.SSE:2025-02-20:ma10` | 2025-02-20 | 浙大网新 `600797.SSE` | 数据安全 | 1 | 2 | ma10 | +0.6014% | +2.3121% | winner |
| `causal-leader-pullback-close-v2:a95c33a064e9fed80d7e70b23a54618bed7f9e21:600845.SSE:2025-02-21:ma10` | 2025-02-21 | 宝信软件 `600845.SSE` | PLC概念 | 1 | 1 | ma10 | +3.9964% | +0.6637% | winner |
| `causal-leader-pullback-close-v2:4e6fdf2c3b9da3cea267a2367a1426e9e8f177d6:600592.SSE:2025-03-04:ma10` | 2025-03-04 | 龙溪股份 `600592.SSE` | 大飞机 | 1 | 1 | ma10 | +1.3693% | +9.8252% | winner |
| `causal-leader-pullback-close-v2:13ecf03b405265018231e770d83ea3b5d780d788:002048.SZSE:2025-03-05:ma10` | 2025-03-05 | 宁波华翔 `002048.SZSE` | PEEK材料概念 | 1 | 2 | ma10 | +5.2441% | +9.7749% | winner |
| `causal-leader-pullback-close-v2:8acfed9652b21fc8c4fe9e5b75a5ee0b90cbcc7d:002824.SZSE:2025-03-05:ma10` | 2025-03-05 | 和胜股份 `002824.SZSE` | 刀片电池 | 1 | 1 | ma10 | -1.7446% | +0.2873% | winner |
| `causal-leader-pullback-close-v2:226a286bf4b4de7e38fd4215ad60666f6889be87:605100.SSE:2025-03-06:ma5` | 2025-03-06 | 华丰股份 `605100.SSE` | 固态电池 | 1 | 1 | ma5 | -2.3188% | -10.1820% | loser |
| `causal-leader-pullback-close-v2:c725317d08d663d2bbb6438bb7ba7aa6118288db:000536.SZSE:2025-03-06:ma20` | 2025-03-06 | 华映科技 `000536.SZSE` | 玻璃基板 | 2 | 1 | ma20 | +2.0020% | -5.5968% | loser |
| `causal-leader-pullback-close-v2:59763e523127a76c3ada4c90b397fa815e3559a8:002162.SZSE:2025-03-07:ma10` | 2025-03-07 | 悦心健康 `002162.SZSE` | 辅助生殖 | 1 | 3 | ma10 | +0.5872% | +9.9149% | winner |
| `causal-leader-pullback-close-v2:cfee6095547c3a16739777165f53289b30f9538b:600619.SSE:2025-03-10:ma10` | 2025-03-10 | 海立股份 `600619.SSE` | 空气能热泵 | 1 | 3 | ma10 | +1.6102% | +3.0468% | winner |
| `causal-leader-pullback-close-v2:1d640e165902668607a4cea96ac85afb7cea4104:000409.SZSE:2025-03-18:ma10` | 2025-03-18 | 云鼎科技 `000409.SZSE` | 工业互联 | 2 | 1 | ma10 | +1.3142% | -3.1338% | loser |
| `causal-leader-pullback-close-v2:4b3c5970b7a1a8a93f37eff505904dfebd0a42bf:002819.SZSE:2025-05-16:ma10` | 2025-05-16 | 东方中科 `002819.SZSE` | 鸿蒙概念 | 1 | 1 | ma10 | +4.9148% | +9.8059% | winner |
| `causal-leader-pullback-close-v2:6fbe18bebbb8ca199bc241ff58247b6708b856fa:002471.SZSE:2025-05-19:ma10` | 2025-05-19 | 中超控股 `002471.SZSE` | 机器人概念 | 1 | 3 | ma10 | -0.7220% | -5.4874% | loser |
| `causal-leader-pullback-close-v2:a616bfff7ee61de9eb41c6355ce5dfca20b257a0:002161.SZSE:2025-05-26:ma20` | 2025-05-26 | 远 望 谷 `002161.SZSE` | 宠物经济 | 1 | 2 | ma20 | +10.3100% | +1.4340% | winner |
| `causal-leader-pullback-close-v2:58f38ba0255029ab2a48284b1de35a623623032c:002286.SZSE:2025-05-27:ma10` | 2025-05-27 | 保龄宝 `002286.SZSE` | 合成生物 | 1 | 1 | ma10 | +2.4515% | +4.0174% | winner |
| `causal-leader-pullback-close-v2:5f57db308e0a4fb3cd76329f4b031cc3dc9dfc39:600530.SSE:2025-05-27:ma10` | 2025-05-27 | 交大昂立 `600530.SSE` | IPO受益 | 2 | 1 | ma10 | -0.2232% | -1.6002% | loser |
| `causal-leader-pullback-close-v2:6fbe18bebbb8ca199bc241ff58247b6708b856fa:002682.SZSE:2025-06-03:ma10` | 2025-06-03 | 龙洲股份 `002682.SZSE` | 机器人概念 | 3 | 3 | ma10 | -0.7049% | -4.2293% | loser |
| `causal-leader-pullback-close-v2:05274d03099287ed9714de2f2229a37314dd5baf:000533.SZSE:2025-06-04:ma10` | 2025-06-04 | 顺钠股份 `000533.SZSE` | 核能核电 | 1 | 2 | ma10 | +0.1513% | +9.7719% | winner |
| `causal-leader-pullback-close-v2:91b1612e257eaf7ba9b7fca6fc418560e11793a4:603680.SSE:2025-06-06:ma10` | 2025-06-06 | 今创集团 `603680.SSE` | 交运设备 | 1 | 1 | ma10 | +2.3042% | +5.7948% | winner |
| `causal-leader-pullback-close-v2:6ef8bc8c4f97826d76e3ed789a4dd41c5719451b:002537.SZSE:2025-06-23:ma20` | 2025-06-23 | 海联金汇 `002537.SZSE` | 互联网金融 | 1 | 2 | ma20 | +6.6070% | +9.8317% | winner |
| `causal-leader-pullback-close-v2:6ef8bc8c4f97826d76e3ed789a4dd41c5719451b:002657.SZSE:2025-06-23:ma20` | 2025-06-23 | 中科金财 `002657.SZSE` | 互联网金融 | 1 | 3 | ma20 | +0.2415% | +1.9116% | winner |
| `causal-leader-pullback-close-v2:f1d43be20e88ff69c5b77cda450ddf98e1d1eb19:000554.SZSE:2025-06-23:ma10` | 2025-06-23 | 泰山石油 `000554.SZSE` | 内贸流通 | 1 | 2 | ma10 | +4.7529% | -10.2363% | loser |
| `causal-leader-pullback-close-v2:33e9ecc77a3e27168d478dc7fc1a0d272f766d50:002724.SZSE:2025-07-02:ma5` | 2025-07-02 | 海洋王 `002724.SZSE` | 石墨烯 | 1 | 1 | ma5 | +2.1907% | +0.7259% | winner |
| `causal-leader-pullback-close-v2:86e38ec394a3203ece4c614a7401f7c1e404aaeb:001269.SZSE:2025-07-08:ma10` | 2025-07-08 | 欧晶科技 `001269.SZSE` | 半导体概念 | 1 | 3 | ma10 | +0.8546% | +0.8562% | winner |
| `causal-leader-pullback-close-v2:3e6665a2ab5b29cc53d8bb933933d7b9e63aaf76:605058.SSE:2025-07-09:ma10` | 2025-07-09 | 澳弘电子 `605058.SSE` | 卫星互联网 | 1 | 2 | ma10 | +1.6186% | -5.2629% | loser |
| `causal-leader-pullback-close-v2:bda9acf958b503b71483fec5a9f0b94848855931:000758.SZSE:2025-07-18:ma10` | 2025-07-18 | 中色股份 `000758.SZSE` | 稀缺资源 | 1 | 3 | ma10 | +1.1524% | +4.5697% | winner |
| `causal-leader-pullback-close-v2:1257e60b46ae12c17a1da77507ee6dbf413bf149:600774.SSE:2025-07-31:ma10` | 2025-07-31 | 汉商集团 `600774.SSE` | 免疫治疗 | 2 | 1 | ma10 | +5.6607% | +9.7735% | winner |
| `causal-leader-pullback-close-v2:2561f1abc191f93d3814da610262dd36ca93951c:003017.SZSE:2025-08-12:ma10` | 2025-08-12 | 大洋生物 `003017.SZSE` | 合成生物 | 1 | 2 | ma10 | +0.6214% | -3.4980% | loser |
| `causal-leader-pullback-close-v2:5b9648ee16e78e57de9064b2bf8139e692d300ae:002317.SZSE:2025-08-15:ma10` | 2025-08-15 | 众生药业 `002317.SZSE` | 辅助生殖 | 3 | 1 | ma10 | +1.0995% | +1.7086% | winner |
| `causal-leader-pullback-close-v2:affac8cb8acb6f80fa6772938ee96c00aad75425:002164.SZSE:2025-08-18:ma10` | 2025-08-18 | 宁波东力 `002164.SZSE` | 机器人执行器 | 1 | 3 | ma10 | +1.4395% | +4.6908% | winner |
| `causal-leader-pullback-close-v2:05274d03099287ed9714de2f2229a37314dd5baf:600651.SSE:2025-08-28:ma10` | 2025-08-28 | 飞乐音响 `600651.SSE` | 核能核电 | 1 | 1 | ma10 | +3.2508% | +3.8682% | winner |
| `causal-leader-pullback-close-v2:47a9efce93ffdfadd9fd82193f13f9ae00062308:601579.SSE:2025-08-29:ma10` | 2025-08-29 | 会稽山 `601579.SSE` | 白酒 | 2 | 1 | ma10 | +2.1176% | +4.1372% | winner |
| `causal-leader-pullback-close-v2:32efd87a544aaf9f30e565caed721030ec91a236:000962.SZSE:2025-09-05:ma20` | 2025-09-05 | 东方钽业 `000962.SZSE` | 超导概念 | 3 | 2 | ma20 | -1.0298% | +4.7667% | winner |
| `causal-leader-pullback-close-v2:58e75b21365b4c498e833feede8cc3c9111c0cc5:000796.SZSE:2025-09-10:ma10` | 2025-09-10 | 凯撒旅业 `000796.SZSE` | 免税概念 | 2 | 1 | ma10 | -3.2691% | +0.4299% | winner |
| `causal-leader-pullback-close-v2:8dcb4c5f34e2e8d5de71445ac52eb6d834bae0be:600601.SSE:2025-09-10:ma10` | 2025-09-10 | 方正科技 `600601.SSE` | PCB | 5 | 2 | ma10 | -5.4099% | +9.7572% | winner |
| `causal-leader-pullback-close-v2:a1f07b13a90671922eac9ac20d4a5e2f4d256a99:603335.SSE:2025-09-15:ma20` | 2025-09-15 | 迪生力 `603335.SSE` | 汽车一体化压铸 | 1 | 3 | ma20 | +0.5226% | +2.5444% | winner |
| `causal-leader-pullback-close-v2:b61aac53dceb0363ca7bfb3d59d210c40426c992:600509.SSE:2025-09-19:ma10` | 2025-09-19 | 天富能源 `600509.SSE` | 碳化硅 | 2 | 2 | ma10 | +2.1852% | +0.2614% | winner |
| `causal-leader-pullback-close-v2:affac8cb8acb6f80fa6772938ee96c00aad75425:002472.SZSE:2025-09-22:ma5` | 2025-09-22 | 双环传动 `002472.SZSE` | 机器人执行器 | 1 | 2 | ma5 | -3.4070% | +2.1970% | winner |
| `causal-leader-pullback-close-v2:c5ec37cadd25c8cdbb71079a52957280272bc613:603019.SSE:2025-09-22:ma5` | 2025-09-22 | 中科曙光 `603019.SSE` | 液冷概念 | 1 | 2 | ma5 | -4.3718% | -2.5658% | loser |
| `causal-leader-pullback-close-v2:d9b1bf1abee90a5fdde03a529d0ee080336229c5:000603.SZSE:2025-09-22:ma10` | 2025-09-22 | 盛达资源 `000603.SZSE` | 黄金概念 | 2 | 3 | ma10 | +0.8597% | +4.4188% | winner |
| `causal-leader-pullback-close-v2:797b35808e9ba957908ca993de64cf812000b186:002562.SZSE:2025-09-24:ma20` | 2025-09-24 | 兄弟科技 `002562.SZSE` | 中俄贸易概念 | 1 | 3 | ma20 | +0.2946% | +1.3979% | winner |
| `causal-leader-pullback-close-v2:fe35e7b1c1cd912ece3b9bd703e62b6ca8e1657b:603283.SSE:2025-10-09:ma10` | 2025-10-09 | 赛腾股份 `603283.SSE` | 高带宽内存 | 1 | 2 | ma10 | +3.1637% | -2.1371% | loser |
| `causal-leader-pullback-close-v2:073a7da8645456c5c3a4576382ff6c9652939cc6:603516.SSE:2025-10-13:ma20` | 2025-10-13 | 淳中科技 `603516.SSE` | 虚拟现实 | 1 | 1 | ma20 | -0.2473% | -4.2093% | loser |
| `causal-leader-pullback-close-v2:187eb37c6fcdb17e90a2095576f35de3beaeb8de:002549.SZSE:2025-10-13:ma10` | 2025-10-13 | 凯美特气 `002549.SZSE` | 工业气体 | 1 | 1 | ma10 | +3.1784% | +4.1924% | winner |
| `causal-leader-pullback-close-v2:035f6203ecd0734f2b01081df26136c1e074fe2f:002121.SZSE:2025-10-15:ma10` | 2025-10-15 | 科陆电子 `002121.SZSE` | 虚拟电厂 | 1 | 1 | ma10 | -2.2614% | -1.2173% | loser |
| `causal-leader-pullback-close-v2:c5d1bebba40bdb4ec98694b39389272e8e974a78:605358.SSE:2026-01-05:ma20` | 2026-01-05 | 立昂微 `605358.SSE` | 氮化镓 | 1 | 1 | ma20 | +2.4101% | +9.8000% | winner |
| `causal-leader-pullback-close-v2:94947fe6b6e756df5c917835d54019102514ac5d:002865.SZSE:2026-01-06:ma10` | 2026-01-06 | 钧达股份 `002865.SZSE` | TOPCon电池 | 1 | 1 | ma10 | +0.3011% | +7.2694% | winner |
| `causal-leader-pullback-close-v2:38a69aa41555da75efb9a4a0ca0880f6922da493:000917.SZSE:2026-01-09:ma10` | 2026-01-09 | 电广传媒 `000917.SZSE` | 网络游戏 | 1 | 2 | ma10 | +5.5861% | +9.8332% | winner |
| `causal-leader-pullback-close-v2:913e2861469c3880f56ed052113532cac80e9955:600133.SSE:2026-01-14:ma10` | 2026-01-14 | 东湖高新 `600133.SSE` | 湖北自贸 | 1 | 3 | ma10 | +0.0207% | +2.0599% | winner |
| `causal-leader-pullback-close-v2:0d17cd26b0b14acca73d7481265c99d7dd1d77c6:002009.SZSE:2026-01-30:ma10` | 2026-01-30 | 天奇股份 `002009.SZSE` | 动力电池回收 | 1 | 1 | ma10 | +1.7417% | +4.5569% | winner |
| `causal-leader-pullback-close-v2:409a37248c3b60d547df97acd346a5d3b710bb00:603806.SSE:2026-02-03:ma10` | 2026-02-03 | 福斯特 `603806.SSE` | 转债标的 | 2 | 3 | ma10 | -0.2824% | +6.7519% | winner |
| `causal-leader-pullback-close-v2:5668ec6f1e358562f760ef903ab4a21ca6a6b0f8:603920.SSE:2026-02-03:ma20` | 2026-02-03 | 世运电路 `603920.SSE` | AI眼镜 | 4 | 3 | ma20 | +6.7686% | +0.6850% | winner |
| `causal-leader-pullback-close-v2:70399ba410d8828f67ca885316aa125874bffb68:000962.SZSE:2026-02-03:ma20` | 2026-02-03 | 东方钽业 `000962.SZSE` | 超导概念 | 6 | 3 | ma20 | +3.8253% | +3.7111% | winner |
| `causal-leader-pullback-close-v2:8549eb12687b582d3fdb1c40092cf2e16f9bd258:600331.SSE:2026-02-03:ma10` | 2026-02-03 | 宏达股份 `600331.SSE` | 磷化工 | 2 | 1 | ma10 | -1.6669% | +2.6804% | winner |
| `causal-leader-pullback-close-v2:bcda8146700b0256354072007727949188c51533:002339.SZSE:2026-02-06:ma10` | 2026-02-06 | 积成电子 `002339.SZSE` | 北交所概念 | 3 | 1 | ma10 | -2.0216% | +1.2890% | winner |
| `causal-leader-pullback-close-v2:a037560f0c45cf37ddc29e3feb75e19fd0e6a71c:603031.SSE:2026-02-09:ma20` | 2026-02-09 | 安孚科技 `603031.SSE` | 跨境电商 | 1 | 2 | ma20 | +4.4151% | -1.7488% | loser |
| `causal-leader-pullback-close-v2:e0ba5c7bcd30f2faad88bd0198633ab06c3c3c5c:600590.SSE:2026-02-09:ma20` | 2026-02-09 | 泰豪科技 `600590.SSE` | 发电机概念 | 2 | 2 | ma20 | +6.0725% | +0.5098% | winner |
| `causal-leader-pullback-close-v2:70399ba410d8828f67ca885316aa125874bffb68:000962.SZSE:2026-02-11:ma20` | 2026-02-11 | 东方钽业 `000962.SZSE` | 超导概念 | 7 | 3 | ma20 | +0.0398% | +9.7910% | winner |
| `causal-leader-pullback-close-v2:9adba39fc23a4403084002a6d9ad962658a8c358:002355.SZSE:2026-02-13:ma20` | 2026-02-13 | 兴民智通 `002355.SZSE` | EDR概念 | 1 | 3 | ma20 | +0.4321% | +0.8710% | winner |
| `causal-leader-pullback-close-v2:3a160ebaab0b6d0d39c460ee14a42838be7a168f:600330.SSE:2026-02-24:ma10` | 2026-02-24 | 天通股份 `600330.SSE` | MicroLED | 2 | 1 | ma10 | +2.3552% | -4.9046% | loser |
| `causal-leader-pullback-close-v2:6394963232344e96db692a301245e1ffcb02162f:600487.SSE:2026-02-24:ma10` | 2026-02-24 | 亨通光电 `600487.SSE` | 液冷概念 | 3 | 1 | ma10 | +3.8978% | -4.7702% | loser |
| `causal-leader-pullback-close-v2:bcda8146700b0256354072007727949188c51533:002491.SZSE:2026-02-24:ma10` | 2026-02-24 | 通鼎互联 `002491.SZSE` | 北交所概念 | 3 | 1 | ma10 | +1.0344% | -6.6769% | loser |
| `causal-leader-pullback-close-v2:c0bfd3fabee91be7eca7a54aea9021dc11496d36:603618.SSE:2026-02-26:ma10` | 2026-02-26 | 杭电股份 `603618.SSE` | 锂电池概念 | 1 | 1 | ma10 | +0.2138% | +9.8000% | winner |
| `causal-leader-pullback-close-v2:f3880d7a6560b0698f6afa0cab70884a3f96cb9e:000833.SZSE:2026-03-06:ma10` | 2026-03-06 | 粤桂股份 `000833.SZSE` | 磷化工 | 1 | 2 | ma10 | -3.4112% | +1.0918% | winner |
| `causal-leader-pullback-close-v2:f3880d7a6560b0698f6afa0cab70884a3f96cb9e:600470.SSE:2026-03-06:ma10` | 2026-03-06 | 六国化工 `600470.SSE` | 磷化工 | 1 | 1 | ma10 | -4.4280% | +3.1453% | winner |
| `causal-leader-pullback-close-v2:09f3a60443f9ce2b8505e013b61cf7b8b30d5d07:600664.SSE:2026-04-14:ma20` | 2026-04-14 | 哈药股份 `600664.SSE` | 肝炎概念 | 1 | 1 | ma20 | +1.6568% | +9.7010% | winner |
| `causal-leader-pullback-close-v2:5514dfaf23d77e70e286054cdc774fa5139b3007:002107.SZSE:2026-04-14:ma10` | 2026-04-14 | 沃华医药 `002107.SZSE` | 流感 | 1 | 3 | ma10 | +0.2246% | +1.3326% | winner |
| `causal-leader-pullback-close-v2:32f865bb9dfd83fc864281c5ca8bbe780a0c00bd:002081.SZSE:2026-04-29:ma10` | 2026-04-29 | 金 螳 螂 `002081.SZSE` | 商业航天 | 1 | 1 | ma10 | +5.3325% | +9.8746% | winner |
| `causal-leader-pullback-close-v2:3e42564259e6ea4a88a642c23444e1ac1c8d95ea:600156.SSE:2026-04-29:ma10` | 2026-04-29 | 华升股份 `600156.SSE` | 液冷概念 | 1 | 3 | ma10 | +4.2352% | -3.5124% | loser |
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
