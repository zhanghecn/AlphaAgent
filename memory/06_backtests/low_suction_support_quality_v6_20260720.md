# AlphaAgent 主升龙头支撑质量低吸 V6

规则版本：`causal-leader-support-quality-v6`
研究状态：`no_development_quality_leaf`
开发期冻结叶：`none`
历史代理门：`False`
正式策略：`false`

## 固定树合同

- 特征：`campaign_day, concept_gain_pct, leg_gain_pct, strong_days_since_ignition, turnover_expansion, volume_ratio_prior5, dynamic_rank, wave_number, peak_gap_pct, peak_drawdown_low_pct, close_location, daily_return_pct`
- 完整开发样本：`2251`
- 缺失特征样本：`0`
- 模型指纹：`sha256:8bf0ee99b43a265b10357417b2c7ee97556869901b94796fdc0e0b5445503785`

## 开发叶子

| 叶子 | 条件 | 成交 | 胜率 | 均值 | PF | 双成本均值 | 正向块 | 四仓复利 | 入围 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| support_quality_leaf_2 | peak_drawdown_low_pct <= -7.64487600327 & close_location <= 0.0184367028996 | 107 | 19.6262% | -3.0047% | 0.1879 | -3.2047% | 0 | -53.1807% | False |
| support_quality_leaf_3 | peak_drawdown_low_pct <= -7.64487600327 & close_location > 0.0184367028996 | 1334 | 36.7316% | -0.9876% | 0.5694 | -1.1876% | 0 | -77.5764% | False |
| support_quality_leaf_5 | peak_drawdown_low_pct > -7.64487600327 & daily_return_pct <= -2.03880548477 | 264 | 51.1364% | +0.2235% | 1.2026 | +0.0235% | 0 | +17.4141% | False |
| support_quality_leaf_6 | peak_drawdown_low_pct > -7.64487600327 & daily_return_pct > -2.03880548477 | 546 | 40.8425% | -0.4408% | 0.7038 | -0.6408% | 0 | -41.5392% | False |

## 冻结行情表

- 未冻结：开发期没有合格质量叶。

## 顺序样本外

- block 4：`未读取`
- block 5：`未读取`

## 最终四仓与资格

- 成交：`0`
- 胜率：`-`
- 单笔均值：`-`
- PF：`-`
- 四仓复利：`-`
- 四仓最大回撤：`-`
- 合格物质行情：`0`
- 失败门：`no_development_quality_leaf`
- 正式阻断：`strict_historical_membership_missing, executable_preclose_price_missing`

## 参考龙头

- 东山精密 `002384.SZSE`：精确支撑 `26`，质量叶匹配 `0`，可见成交 `0`；排除 `{"no_development_quality_leaf": 26}`。
- 金安国纪 `002636.SZSE`：精确支撑 `1`，质量叶匹配 `0`，可见成交 `0`；排除 `{"no_development_quality_leaf": 1}`。
- 亨通光电 `600487.SSE`：精确支撑 `36`，质量叶匹配 `0`，可见成交 `0`；排除 `{"no_development_quality_leaf": 36}`。

## 研究边界

- The V5 exact-support predicate, common calendar and D+1 close exit are unchanged.
- The tree and leaf nomination use blocks 1-3 only.
- Block 5 outcomes and trade rows stay absent unless block 4 passes.
- GOLD/SILVER and market phase cannot change the selected entry leaf.
- Named stocks are attribution only and cannot select a leaf.
- Current membership and the D close remain historical research proxies.

## Reproduce

```bash
docker compose --profile research run --rm -T --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace -e PYTHONPATH=/workspace:/app/third_party/akshare alphaagent-research python -m alphaagent.server.services.low_suction.cli v6-support-quality-study --format json
```
