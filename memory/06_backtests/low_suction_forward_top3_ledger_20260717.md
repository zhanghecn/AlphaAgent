# AlphaAgent 低吸真实前向 Top3 身份账本

ranking_version: `low-suction-forward-top3-v1`\
latest_source_trade_date: `2026-07-16`\
source_sessions: `1`\
bound_sessions: `0`\
selection_status: `accumulating_forward_identity`\
selected_mode: `null`\
formal_metrics: `null`\
low_suction_outcomes_read: `false`

本账本只比较龙头身份留存、后续强势事件领先和容量；不读取低吸买卖收益，
也不输出胜率、复利、利润因子或生产买点。目标日期只在真实完整交易时段出现后绑定。

## Latest Frozen Scope

| Mode | Active concepts | Main-board rows | Security eligible | Ranked | Top3 | Excluded | Capacity |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `cycle_relative_strength` | 36 | 1158 | 1098 | 1098 | 108 | 60 | 0.7500 |
| `market_recognition_lexicographic` | 36 | 1158 | 1098 | 1098 | 108 | 60 | 0.7685 |
| `recognition_consensus` | 36 | 1158 | 1098 | 119 | 98 | 1039 | 0.7449 |

## Mode Metrics

| Mode | Bound sessions | Top3 obs | Retention obs | Retention | Strong obs | Strong lead | Capacity |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `cycle_relative_strength` | 0 | 0 | 0 | - | 0 | - | - |
| `market_recognition_lexicographic` | 0 | 0 | 0 | - | 0 | - | - |
| `recognition_consensus` | 0 | 0 | 0 | - | 0 | - | - |

## Latest Frozen Top3

| Mode | Concept | Stock | Rank | Capacity | Target |
| --- | --- | --- | ---: | --- | --- |
| `cycle_relative_strength` | 生物疫苗 (`BK0548`) | 海南海药 (`000566.SZSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 生物疫苗 (`BK0548`) | 贤丰控股 (`002141.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 生物疫苗 (`BK0548`) | 昭衍新药 (`603127.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 央视50_ (`BK0610`) | 信立泰 (`002294.SZSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 央视50_ (`BK0610`) | 古井贡酒 (`000596.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 央视50_ (`BK0610`) | 天士力 (`600535.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 中药概念 (`BK0615`) | 哈药股份 (`600664.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 中药概念 (`BK0615`) | 人民同泰 (`600829.SSE`) | 2 | below | next_trading_session |
| `cycle_relative_strength` | 中药概念 (`BK0615`) | 海南海药 (`000566.SZSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 病毒防治 (`BK0675`) | 哈三联 (`002900.SZSE`) | 1 | below | next_trading_session |
| `cycle_relative_strength` | 病毒防治 (`BK0675`) | 莱茵生物 (`002166.SZSE`) | 2 | below | next_trading_session |
| `cycle_relative_strength` | 病毒防治 (`BK0675`) | 天康生物 (`002100.SZSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 独家药品 (`BK0676`) | 中恒集团 (`600252.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 独家药品 (`BK0676`) | 珍宝岛 (`603567.SSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 独家药品 (`BK0676`) | 同仁堂 (`600085.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 基因测序 (`BK0693`) | 美年健康 (`002044.SZSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 基因测序 (`BK0693`) | 贝瑞基因 (`000710.SZSE`) | 2 | below | next_trading_session |
| `cycle_relative_strength` | 基因测序 (`BK0693`) | 南京新百 (`600682.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 免疫治疗 (`BK0698`) | 南华生物 (`000504.SZSE`) | 1 | below | next_trading_session |
| `cycle_relative_strength` | 免疫治疗 (`BK0698`) | 九芝堂 (`000989.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 免疫治疗 (`BK0698`) | 济民健康 (`603222.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 精准医疗 (`BK0806`) | 塞力医疗 (`603716.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 精准医疗 (`BK0806`) | 基蛋生物 (`603387.SSE`) | 2 | below | next_trading_session |
| `cycle_relative_strength` | 精准医疗 (`BK0806`) | 澳洋健康 (`002172.SZSE`) | 3 | below | next_trading_session |
| `cycle_relative_strength` | 体外诊断概念 (`BK0841`) | 九安医疗 (`002432.SZSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 体外诊断概念 (`BK0841`) | 华盛昌 (`002980.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 体外诊断概念 (`BK0841`) | 塞力医疗 (`603716.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 工业大麻 (`BK0856`) | 塞力医疗 (`603716.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 工业大麻 (`BK0856`) | 莱茵生物 (`002166.SZSE`) | 2 | below | next_trading_session |
| `cycle_relative_strength` | 工业大麻 (`BK0856`) | 天士力 (`600535.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 单抗概念 (`BK0870`) | 康辰药业 (`603590.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 单抗概念 (`BK0870`) | 华海药业 (`600521.SSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 单抗概念 (`BK0870`) | 天士力 (`600535.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 青蒿素 (`BK0872`) | 凯莱英 (`002821.SZSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 青蒿素 (`BK0872`) | 海正药业 (`600267.SSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 青蒿素 (`BK0872`) | 润都股份 (`002923.SZSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 猪肉概念 (`BK0882`) | 天康生物 (`002100.SZSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 猪肉概念 (`BK0882`) | 华统股份 (`002840.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 猪肉概念 (`BK0882`) | 顺鑫农业 (`000860.SZSE`) | 3 | below | next_trading_session |
| `cycle_relative_strength` | 鸡肉概念 (`BK0887`) | 天康生物 (`002100.SZSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 鸡肉概念 (`BK0887`) | 华统股份 (`002840.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 鸡肉概念 (`BK0887`) | 春雪食品 (`605567.SSE`) | 3 | below | next_trading_session |
| `cycle_relative_strength` | 医美概念 (`BK0889`) | 南华生物 (`000504.SZSE`) | 1 | below | next_trading_session |
| `cycle_relative_strength` | 医美概念 (`BK0889`) | 哈三联 (`002900.SZSE`) | 2 | below | next_trading_session |
| `cycle_relative_strength` | 医美概念 (`BK0889`) | 拉芳家化 (`603630.SSE`) | 3 | below | next_trading_session |
| `cycle_relative_strength` | 阿兹海默 (`BK0894`) | 赤天化 (`600227.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 阿兹海默 (`BK0894`) | 通化金马 (`000766.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 阿兹海默 (`BK0894`) | 恩华药业 (`002262.SZSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 维生素 (`BK0895`) | 众生药业 (`002317.SZSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 维生素 (`BK0895`) | 华北制药 (`600812.SSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 维生素 (`BK0895`) | 亿帆医药 (`002019.SZSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | CRO (`BK0899`) | 昭衍新药 (`603127.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | CRO (`BK0899`) | 普洛药业 (`000739.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | CRO (`BK0899`) | 百花医药 (`600721.SSE`) | 3 | below | next_trading_session |
| `cycle_relative_strength` | 流感 (`BK0906`) | 哈药股份 (`600664.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 流感 (`BK0906`) | 九安医疗 (`002432.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 流感 (`BK0906`) | 百花医药 (`600721.SSE`) | 3 | below | next_trading_session |
| `cycle_relative_strength` | 长寿药 (`BK0936`) | 金达威 (`002626.SZSE`) | 1 | below | next_trading_session |
| `cycle_relative_strength` | 长寿药 (`BK0936`) | 兄弟科技 (`002562.SZSE`) | 2 | below | next_trading_session |
| `cycle_relative_strength` | 长寿药 (`BK0936`) | 华润双鹤 (`600062.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 辅助生殖 (`BK0939`) | 澳洋健康 (`002172.SZSE`) | 1 | below | next_trading_session |
| `cycle_relative_strength` | 辅助生殖 (`BK0939`) | 美诺华 (`603538.SSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 辅助生殖 (`BK0939`) | 长春高新 (`000661.SZSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 肝素概念 (`BK0944`) | 辰欣药业 (`603367.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 肝素概念 (`BK0944`) | 健友股份 (`603707.SSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 肝素概念 (`BK0944`) | 华北制药 (`600812.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | CAR-T细胞疗法 (`BK0986`) | 海南海药 (`000566.SZSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | CAR-T细胞疗法 (`BK0986`) | 姚记科技 (`002605.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | CAR-T细胞疗法 (`BK0986`) | 中源协和 (`600645.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 毛发医疗 (`BK0996`) | 澳洋健康 (`002172.SZSE`) | 1 | below | next_trading_session |
| `cycle_relative_strength` | 毛发医疗 (`BK0996`) | 朗姿股份 (`002612.SZSE`) | 2 | below | next_trading_session |
| `cycle_relative_strength` | 毛发医疗 (`BK0996`) | 康缘药业 (`600557.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 茅指数 (`BK0999`) | 片仔癀 (`600436.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 茅指数 (`BK0999`) | 科沃斯 (`603486.SSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 茅指数 (`BK0999`) | 泸州老窖 (`000568.SZSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 幽门螺杆菌概念 (`BK1056`) | 基蛋生物 (`603387.SSE`) | 1 | below | next_trading_session |
| `cycle_relative_strength` | 幽门螺杆菌概念 (`BK1056`) | 汉森制药 (`002412.SZSE`) | 2 | below | next_trading_session |
| `cycle_relative_strength` | 幽门螺杆菌概念 (`BK1056`) | 润都股份 (`002923.SZSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 重组蛋白 (`BK1063`) | 中源协和 (`600645.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 重组蛋白 (`BK1063`) | 丽珠集团 (`000513.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 重组蛋白 (`BK1063`) | 通化东宝 (`600867.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 肝炎概念 (`BK1078`) | 哈药股份 (`600664.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 肝炎概念 (`BK1078`) | 百花医药 (`600721.SSE`) | 2 | below | next_trading_session |
| `cycle_relative_strength` | 肝炎概念 (`BK1078`) | 海南海药 (`000566.SZSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 创新药 (`BK1106`) | 昭衍新药 (`603127.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 创新药 (`BK1106`) | 哈三联 (`002900.SZSE`) | 2 | below | next_trading_session |
| `cycle_relative_strength` | 创新药 (`BK1106`) | 立方制药 (`003020.SZSE`) | 3 | below | next_trading_session |
| `cycle_relative_strength` | 减肥药 (`BK1146`) | 甘李药业 (`603087.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 减肥药 (`BK1146`) | 普洛药业 (`000739.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 减肥药 (`BK1146`) | 凯莱英 (`002821.SZSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | AI制药（医疗） (`BK1170`) | 塞力医疗 (`603716.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | AI制药（医疗） (`BK1170`) | 润达医疗 (`603108.SSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | AI制药（医疗） (`BK1170`) | 美年健康 (`002044.SZSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 特色药 (`BK1656`) | 中恒集团 (`600252.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 特色药 (`BK1656`) | 珍宝岛 (`603567.SSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 特色药 (`BK1656`) | 辰欣药业 (`603367.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 病原体防治 (`BK1657`) | 哈药股份 (`600664.SSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 病原体防治 (`BK1657`) | 九安医疗 (`002432.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 病原体防治 (`BK1657`) | 哈三联 (`002900.SZSE`) | 3 | below | next_trading_session |
| `cycle_relative_strength` | 创新医疗服务 (`BK1658`) | 九安医疗 (`002432.SZSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 创新医疗服务 (`BK1658`) | 昭衍新药 (`603127.SSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 创新医疗服务 (`BK1658`) | 百花医药 (`600721.SSE`) | 3 | below | next_trading_session |
| `cycle_relative_strength` | 精准诊断 (`BK1659`) | 九安医疗 (`002432.SZSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 精准诊断 (`BK1659`) | 华盛昌 (`002980.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 精准诊断 (`BK1659`) | 塞力医疗 (`603716.SSE`) | 3 | pass | next_trading_session |
| `cycle_relative_strength` | 医药医疗风格 (`BK1712`) | 九安医疗 (`002432.SZSE`) | 1 | pass | next_trading_session |
| `cycle_relative_strength` | 医药医疗风格 (`BK1712`) | 海思科 (`002653.SZSE`) | 2 | pass | next_trading_session |
| `cycle_relative_strength` | 医药医疗风格 (`BK1712`) | 昭衍新药 (`603127.SSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 生物疫苗 (`BK0548`) | 海南海药 (`000566.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 生物疫苗 (`BK0548`) | 贤丰控股 (`002141.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 生物疫苗 (`BK0548`) | 昭衍新药 (`603127.SSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 央视50_ (`BK0610`) | 信立泰 (`002294.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 央视50_ (`BK0610`) | 同仁堂 (`600085.SSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 央视50_ (`BK0610`) | 古井贡酒 (`000596.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 中药概念 (`BK0615`) | 哈药股份 (`600664.SSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 中药概念 (`BK0615`) | 人民同泰 (`600829.SSE`) | 2 | below | next_trading_session |
| `market_recognition_lexicographic` | 中药概念 (`BK0615`) | 海南海药 (`000566.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 病毒防治 (`BK0675`) | 哈三联 (`002900.SZSE`) | 1 | below | next_trading_session |
| `market_recognition_lexicographic` | 病毒防治 (`BK0675`) | 莱茵生物 (`002166.SZSE`) | 2 | below | next_trading_session |
| `market_recognition_lexicographic` | 病毒防治 (`BK0675`) | 天康生物 (`002100.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 独家药品 (`BK0676`) | 立方制药 (`003020.SZSE`) | 1 | below | next_trading_session |
| `market_recognition_lexicographic` | 独家药品 (`BK0676`) | 珍宝岛 (`603567.SSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 独家药品 (`BK0676`) | 同仁堂 (`600085.SSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 基因测序 (`BK0693`) | 双鹭药业 (`002038.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 基因测序 (`BK0693`) | 贝瑞基因 (`000710.SZSE`) | 2 | below | next_trading_session |
| `market_recognition_lexicographic` | 基因测序 (`BK0693`) | 金域医学 (`603882.SSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 免疫治疗 (`BK0698`) | 济民健康 (`603222.SSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 免疫治疗 (`BK0698`) | 九芝堂 (`000989.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 免疫治疗 (`BK0698`) | 双鹭药业 (`002038.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 精准医疗 (`BK0806`) | 塞力医疗 (`603716.SSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 精准医疗 (`BK0806`) | 基蛋生物 (`603387.SSE`) | 2 | below | next_trading_session |
| `market_recognition_lexicographic` | 精准医疗 (`BK0806`) | 澳洋健康 (`002172.SZSE`) | 3 | below | next_trading_session |
| `market_recognition_lexicographic` | 体外诊断概念 (`BK0841`) | 九安医疗 (`002432.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 体外诊断概念 (`BK0841`) | 华盛昌 (`002980.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 体外诊断概念 (`BK0841`) | 塞力医疗 (`603716.SSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 工业大麻 (`BK0856`) | 塞力医疗 (`603716.SSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 工业大麻 (`BK0856`) | 莱茵生物 (`002166.SZSE`) | 2 | below | next_trading_session |
| `market_recognition_lexicographic` | 工业大麻 (`BK0856`) | 美盈森 (`002303.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 单抗概念 (`BK0870`) | 信立泰 (`002294.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 单抗概念 (`BK0870`) | 双鹭药业 (`002038.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 单抗概念 (`BK0870`) | 长春高新 (`000661.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 青蒿素 (`BK0872`) | 凯莱英 (`002821.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 青蒿素 (`BK0872`) | 德龙汇能 (`000593.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 青蒿素 (`BK0872`) | 润都股份 (`002923.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 猪肉概念 (`BK0882`) | 天康生物 (`002100.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 猪肉概念 (`BK0882`) | 顺鑫农业 (`000860.SZSE`) | 2 | below | next_trading_session |
| `market_recognition_lexicographic` | 猪肉概念 (`BK0882`) | 金字火腿 (`002515.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 鸡肉概念 (`BK0887`) | 天康生物 (`002100.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 鸡肉概念 (`BK0887`) | 益生股份 (`002458.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 鸡肉概念 (`BK0887`) | 仙坛股份 (`002746.SZSE`) | 3 | below | next_trading_session |
| `market_recognition_lexicographic` | 医美概念 (`BK0889`) | 南华生物 (`000504.SZSE`) | 1 | below | next_trading_session |
| `market_recognition_lexicographic` | 医美概念 (`BK0889`) | 哈三联 (`002900.SZSE`) | 2 | below | next_trading_session |
| `market_recognition_lexicographic` | 医美概念 (`BK0889`) | 拉芳家化 (`603630.SSE`) | 3 | below | next_trading_session |
| `market_recognition_lexicographic` | 阿兹海默 (`BK0894`) | 赤天化 (`600227.SSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 阿兹海默 (`BK0894`) | 沃华医药 (`002107.SZSE`) | 2 | below | next_trading_session |
| `market_recognition_lexicographic` | 阿兹海默 (`BK0894`) | 通化金马 (`000766.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 维生素 (`BK0895`) | 众生药业 (`002317.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 维生素 (`BK0895`) | 海南海药 (`000566.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 维生素 (`BK0895`) | 振华股份 (`603067.SSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | CRO (`BK0899`) | 昭衍新药 (`603127.SSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | CRO (`BK0899`) | 凯莱英 (`002821.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | CRO (`BK0899`) | 联化科技 (`002250.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 流感 (`BK0906`) | 哈药股份 (`600664.SSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 流感 (`BK0906`) | 九安医疗 (`002432.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 流感 (`BK0906`) | 百花医药 (`600721.SSE`) | 3 | below | next_trading_session |
| `market_recognition_lexicographic` | 长寿药 (`BK0936`) | 友阿股份 (`002277.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 长寿药 (`BK0936`) | 众生药业 (`002317.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 长寿药 (`BK0936`) | 特一药业 (`002728.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 辅助生殖 (`BK0939`) | 长春高新 (`000661.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 辅助生殖 (`BK0939`) | 澳洋健康 (`002172.SZSE`) | 2 | below | next_trading_session |
| `market_recognition_lexicographic` | 辅助生殖 (`BK0939`) | 美诺华 (`603538.SSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 肝素概念 (`BK0944`) | 辰欣药业 (`603367.SSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 肝素概念 (`BK0944`) | 双鹭药业 (`002038.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 肝素概念 (`BK0944`) | 千红制药 (`002550.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | CAR-T细胞疗法 (`BK0986`) | 海南海药 (`000566.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | CAR-T细胞疗法 (`BK0986`) | 药明康德 (`603259.SSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | CAR-T细胞疗法 (`BK0986`) | 姚记科技 (`002605.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 毛发医疗 (`BK0996`) | 澳洋健康 (`002172.SZSE`) | 1 | below | next_trading_session |
| `market_recognition_lexicographic` | 毛发医疗 (`BK0996`) | 九芝堂 (`000989.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 毛发医疗 (`BK0996`) | 益盛药业 (`002566.SZSE`) | 3 | below | next_trading_session |
| `market_recognition_lexicographic` | 茅指数 (`BK0999`) | 片仔癀 (`600436.SSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 茅指数 (`BK0999`) | 科沃斯 (`603486.SSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 茅指数 (`BK0999`) | 泸州老窖 (`000568.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 幽门螺杆菌概念 (`BK1056`) | 基蛋生物 (`603387.SSE`) | 1 | below | next_trading_session |
| `market_recognition_lexicographic` | 幽门螺杆菌概念 (`BK1056`) | 汉森制药 (`002412.SZSE`) | 2 | below | next_trading_session |
| `market_recognition_lexicographic` | 幽门螺杆菌概念 (`BK1056`) | 润都股份 (`002923.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 重组蛋白 (`BK1063`) | 丽珠集团 (`000513.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 重组蛋白 (`BK1063`) | 通化东宝 (`600867.SSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 重组蛋白 (`BK1063`) | 中源协和 (`600645.SSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 肝炎概念 (`BK1078`) | 哈药股份 (`600664.SSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 肝炎概念 (`BK1078`) | 百花医药 (`600721.SSE`) | 2 | below | next_trading_session |
| `market_recognition_lexicographic` | 肝炎概念 (`BK1078`) | 海南海药 (`000566.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 创新药 (`BK1106`) | 昭衍新药 (`603127.SSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 创新药 (`BK1106`) | 信立泰 (`002294.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 创新药 (`BK1106`) | 立方制药 (`003020.SZSE`) | 3 | below | next_trading_session |
| `market_recognition_lexicographic` | 减肥药 (`BK1146`) | 美诺华 (`603538.SSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 减肥药 (`BK1146`) | 信立泰 (`002294.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 减肥药 (`BK1146`) | 凯莱英 (`002821.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | AI制药（医疗） (`BK1170`) | 塞力医疗 (`603716.SSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | AI制药（医疗） (`BK1170`) | 润达医疗 (`603108.SSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | AI制药（医疗） (`BK1170`) | 长春高新 (`000661.SZSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 特色药 (`BK1656`) | 立方制药 (`003020.SZSE`) | 1 | below | next_trading_session |
| `market_recognition_lexicographic` | 特色药 (`BK1656`) | 珍宝岛 (`603567.SSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 特色药 (`BK1656`) | 同仁堂 (`600085.SSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 病原体防治 (`BK1657`) | 哈药股份 (`600664.SSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 病原体防治 (`BK1657`) | 九安医疗 (`002432.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 病原体防治 (`BK1657`) | 哈三联 (`002900.SZSE`) | 3 | below | next_trading_session |
| `market_recognition_lexicographic` | 创新医疗服务 (`BK1658`) | 九安医疗 (`002432.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 创新医疗服务 (`BK1658`) | 昭衍新药 (`603127.SSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 创新医疗服务 (`BK1658`) | 百花医药 (`600721.SSE`) | 3 | below | next_trading_session |
| `market_recognition_lexicographic` | 精准诊断 (`BK1659`) | 九安医疗 (`002432.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 精准诊断 (`BK1659`) | 华盛昌 (`002980.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 精准诊断 (`BK1659`) | 塞力医疗 (`603716.SSE`) | 3 | pass | next_trading_session |
| `market_recognition_lexicographic` | 医药医疗风格 (`BK1712`) | 九安医疗 (`002432.SZSE`) | 1 | pass | next_trading_session |
| `market_recognition_lexicographic` | 医药医疗风格 (`BK1712`) | 海思科 (`002653.SZSE`) | 2 | pass | next_trading_session |
| `market_recognition_lexicographic` | 医药医疗风格 (`BK1712`) | 昭衍新药 (`603127.SSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 生物疫苗 (`BK0548`) | 海南海药 (`000566.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 生物疫苗 (`BK0548`) | 贤丰控股 (`002141.SZSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 生物疫苗 (`BK0548`) | 昭衍新药 (`603127.SSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 央视50_ (`BK0610`) | 信立泰 (`002294.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 央视50_ (`BK0610`) | 同仁堂 (`600085.SSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 央视50_ (`BK0610`) | 古井贡酒 (`000596.SZSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 中药概念 (`BK0615`) | 哈药股份 (`600664.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 中药概念 (`BK0615`) | 人民同泰 (`600829.SSE`) | 2 | below | next_trading_session |
| `recognition_consensus` | 中药概念 (`BK0615`) | 海南海药 (`000566.SZSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 病毒防治 (`BK0675`) | 哈三联 (`002900.SZSE`) | 1 | below | next_trading_session |
| `recognition_consensus` | 病毒防治 (`BK0675`) | 莱茵生物 (`002166.SZSE`) | 2 | below | next_trading_session |
| `recognition_consensus` | 病毒防治 (`BK0675`) | 天康生物 (`002100.SZSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 独家药品 (`BK0676`) | 珍宝岛 (`603567.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 独家药品 (`BK0676`) | 同仁堂 (`600085.SSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 独家药品 (`BK0676`) | 中恒集团 (`600252.SSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 基因测序 (`BK0693`) | 贝瑞基因 (`000710.SZSE`) | 1 | below | next_trading_session |
| `recognition_consensus` | 免疫治疗 (`BK0698`) | 济民健康 (`603222.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 免疫治疗 (`BK0698`) | 九芝堂 (`000989.SZSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 免疫治疗 (`BK0698`) | 南华生物 (`000504.SZSE`) | 3 | below | next_trading_session |
| `recognition_consensus` | 精准医疗 (`BK0806`) | 塞力医疗 (`603716.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 精准医疗 (`BK0806`) | 基蛋生物 (`603387.SSE`) | 2 | below | next_trading_session |
| `recognition_consensus` | 精准医疗 (`BK0806`) | 澳洋健康 (`002172.SZSE`) | 3 | below | next_trading_session |
| `recognition_consensus` | 体外诊断概念 (`BK0841`) | 九安医疗 (`002432.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 体外诊断概念 (`BK0841`) | 华盛昌 (`002980.SZSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 体外诊断概念 (`BK0841`) | 塞力医疗 (`603716.SSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 工业大麻 (`BK0856`) | 塞力医疗 (`603716.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 工业大麻 (`BK0856`) | 莱茵生物 (`002166.SZSE`) | 2 | below | next_trading_session |
| `recognition_consensus` | 单抗概念 (`BK0870`) | 信立泰 (`002294.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 青蒿素 (`BK0872`) | 凯莱英 (`002821.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 青蒿素 (`BK0872`) | 润都股份 (`002923.SZSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 青蒿素 (`BK0872`) | 海正药业 (`600267.SSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 猪肉概念 (`BK0882`) | 天康生物 (`002100.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 猪肉概念 (`BK0882`) | 顺鑫农业 (`000860.SZSE`) | 2 | below | next_trading_session |
| `recognition_consensus` | 猪肉概念 (`BK0882`) | 邦基科技 (`603151.SSE`) | 3 | below | next_trading_session |
| `recognition_consensus` | 鸡肉概念 (`BK0887`) | 天康生物 (`002100.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 鸡肉概念 (`BK0887`) | 仙坛股份 (`002746.SZSE`) | 2 | below | next_trading_session |
| `recognition_consensus` | 医美概念 (`BK0889`) | 南华生物 (`000504.SZSE`) | 1 | below | next_trading_session |
| `recognition_consensus` | 医美概念 (`BK0889`) | 哈三联 (`002900.SZSE`) | 2 | below | next_trading_session |
| `recognition_consensus` | 医美概念 (`BK0889`) | 拉芳家化 (`603630.SSE`) | 3 | below | next_trading_session |
| `recognition_consensus` | 阿兹海默 (`BK0894`) | 赤天化 (`600227.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 阿兹海默 (`BK0894`) | 通化金马 (`000766.SZSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 阿兹海默 (`BK0894`) | 京新药业 (`002020.SZSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 维生素 (`BK0895`) | 众生药业 (`002317.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 维生素 (`BK0895`) | 梅花生物 (`600873.SSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | CRO (`BK0899`) | 昭衍新药 (`603127.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | CRO (`BK0899`) | 联化科技 (`002250.SZSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | CRO (`BK0899`) | 百花医药 (`600721.SSE`) | 3 | below | next_trading_session |
| `recognition_consensus` | 流感 (`BK0906`) | 哈药股份 (`600664.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 流感 (`BK0906`) | 九安医疗 (`002432.SZSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 流感 (`BK0906`) | 百花医药 (`600721.SSE`) | 3 | below | next_trading_session |
| `recognition_consensus` | 长寿药 (`BK0936`) | 友阿股份 (`002277.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 长寿药 (`BK0936`) | 金达威 (`002626.SZSE`) | 2 | below | next_trading_session |
| `recognition_consensus` | 辅助生殖 (`BK0939`) | 长春高新 (`000661.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 辅助生殖 (`BK0939`) | 澳洋健康 (`002172.SZSE`) | 2 | below | next_trading_session |
| `recognition_consensus` | 辅助生殖 (`BK0939`) | 美诺华 (`603538.SSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 肝素概念 (`BK0944`) | 辰欣药业 (`603367.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 肝素概念 (`BK0944`) | 健友股份 (`603707.SSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 肝素概念 (`BK0944`) | 华北制药 (`600812.SSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | CAR-T细胞疗法 (`BK0986`) | 海南海药 (`000566.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | CAR-T细胞疗法 (`BK0986`) | 姚记科技 (`002605.SZSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | CAR-T细胞疗法 (`BK0986`) | 复星医药 (`600196.SSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 毛发医疗 (`BK0996`) | 澳洋健康 (`002172.SZSE`) | 1 | below | next_trading_session |
| `recognition_consensus` | 毛发医疗 (`BK0996`) | 康缘药业 (`600557.SSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 茅指数 (`BK0999`) | 片仔癀 (`600436.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 茅指数 (`BK0999`) | 科沃斯 (`603486.SSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 茅指数 (`BK0999`) | 泸州老窖 (`000568.SZSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 幽门螺杆菌概念 (`BK1056`) | 基蛋生物 (`603387.SSE`) | 1 | below | next_trading_session |
| `recognition_consensus` | 幽门螺杆菌概念 (`BK1056`) | 汉森制药 (`002412.SZSE`) | 2 | below | next_trading_session |
| `recognition_consensus` | 幽门螺杆菌概念 (`BK1056`) | 润都股份 (`002923.SZSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 重组蛋白 (`BK1063`) | 丽珠集团 (`000513.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 重组蛋白 (`BK1063`) | 通化东宝 (`600867.SSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 重组蛋白 (`BK1063`) | 中源协和 (`600645.SSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 肝炎概念 (`BK1078`) | 哈药股份 (`600664.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 肝炎概念 (`BK1078`) | 百花医药 (`600721.SSE`) | 2 | below | next_trading_session |
| `recognition_consensus` | 肝炎概念 (`BK1078`) | 海南海药 (`000566.SZSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 创新药 (`BK1106`) | 昭衍新药 (`603127.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 创新药 (`BK1106`) | 立方制药 (`003020.SZSE`) | 2 | below | next_trading_session |
| `recognition_consensus` | 减肥药 (`BK1146`) | 信立泰 (`002294.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 减肥药 (`BK1146`) | 凯莱英 (`002821.SZSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 减肥药 (`BK1146`) | 甘李药业 (`603087.SSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | AI制药（医疗） (`BK1170`) | 塞力医疗 (`603716.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | AI制药（医疗） (`BK1170`) | 润达医疗 (`603108.SSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | AI制药（医疗） (`BK1170`) | 长春高新 (`000661.SZSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 特色药 (`BK1656`) | 珍宝岛 (`603567.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 特色药 (`BK1656`) | 同仁堂 (`600085.SSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 特色药 (`BK1656`) | 中恒集团 (`600252.SSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 病原体防治 (`BK1657`) | 哈药股份 (`600664.SSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 病原体防治 (`BK1657`) | 九安医疗 (`002432.SZSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 病原体防治 (`BK1657`) | 哈三联 (`002900.SZSE`) | 3 | below | next_trading_session |
| `recognition_consensus` | 创新医疗服务 (`BK1658`) | 九安医疗 (`002432.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 创新医疗服务 (`BK1658`) | 昭衍新药 (`603127.SSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 创新医疗服务 (`BK1658`) | 百花医药 (`600721.SSE`) | 3 | below | next_trading_session |
| `recognition_consensus` | 精准诊断 (`BK1659`) | 九安医疗 (`002432.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 精准诊断 (`BK1659`) | 华盛昌 (`002980.SZSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 精准诊断 (`BK1659`) | 塞力医疗 (`603716.SSE`) | 3 | pass | next_trading_session |
| `recognition_consensus` | 医药医疗风格 (`BK1712`) | 九安医疗 (`002432.SZSE`) | 1 | pass | next_trading_session |
| `recognition_consensus` | 医药医疗风格 (`BK1712`) | 海思科 (`002653.SZSE`) | 2 | pass | next_trading_session |
| `recognition_consensus` | 医药医疗风格 (`BK1712`) | 昭衍新药 (`603127.SSE`) | 3 | pass | next_trading_session |

## Boundary

样本未达到预注册的 60 个已绑定源交易时段前，`selected_mode` 必须保持 `null`。
身份模式不能用低吸收益选择；分钟低吸研究也不会由本报告自动启动。
