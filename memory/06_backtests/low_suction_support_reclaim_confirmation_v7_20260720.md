# AlphaAgent 主升龙头支撑后首次弱转强 V7

规则版本：`causal-leader-support-reclaim-confirmation-v7`
研究状态：`no_development_confirmation_rule`
开发期规则：`none`
历史代理门：`False`
正式策略：`false`

## 固定入场合同

- 精确 MA5/MA10 支撑日不买；只保留同 campaign、同 wave 的最新有效支撑锚。
- 首次收盘越过支撑日最高价和前收、仍低于可见前高、当日涨幅小于 8% 时买入。
- D 收盘买入代理，D+1 收盘卖出；金银和市场阶段不能改变入场条件。

## 开发期

- 成交：`227`
- 胜率：`40.0881%`
- 均值：`-0.3465%`
- PF：`0.8105`
- 稳定块：`0`
- 四仓复利：`-16.2654%`
- 失败门：`development_win_rate<=60pct, development_mean_return<=0, development_profit_factor<1.2, development_double_cost_mean<=0, development_stable_blocks<2, development_cash_compound<=0`

## 顺序样本外

- block 4：`未读取`
- block 5：`未读取`

## 最终资格

- 失败门：`no_development_confirmation_rule`
- 正式阻断：`strict_historical_membership_missing, executable_preclose_price_missing`

## 参考龙头

- 东山精密 `002384.SZSE`：精确支撑 `26`，首次弱转强 `6`，可见成交 `0`。
- 金安国纪 `002636.SZSE`：精确支撑 `1`，首次弱转强 `0`，可见成交 `0`。
- 亨通光电 `600487.SSE`：精确支撑 `36`，首次弱转强 `0`，可见成交 `0`。

## 开发期归因

- 只读取 `block_1, block_2, block_3`，闭合 `227` 笔；所有分组仅供下一独立假设。

## 研究边界

- The V5 common support-event calendar is frozen before V7 confirmations are selected.
- Only blocks 1-3 can nominate the sole V7 entry rule and environment table.
- Block 5 outcomes and trade rows remain absent unless block 4 passes.
- GOLD/SILVER and market phase can route cash only after the entry rule passes development.
- Development diagnostics are attribution and cannot alter the V7 contract.
- Current membership and the completed D close remain historical research proxies.

## Reproduce

```bash
docker compose --profile research run --rm -T --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace -e PYTHONPATH=/workspace:/app/third_party/akshare alphaagent-research python -m alphaagent.server.services.low_suction.cli v7-support-reclaim-confirmation-study --format json
```
