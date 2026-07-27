# A+B 资金与概念扩散补位自然前向影子

## Archived state (2026-07-26)

- 本报告生成时正式合同为 `limit-up-core-ab-v1`，影子不生成正式买点、不占正式仓位；
  后续因果回放已将该补位收敛为 C，并进入当前唯一正式合同 `limit-up-core-abc-v1`。
- 自然前向起点固定为 `2026-07-27`；此前雷达帧不重标版本，也不进入前向分母。
- 冻结影子版本为 `limit-up-no-prior-ab-rescue-shadow-v2`，对应历史候选规则
  `no-prior-ab-capital-diffusion-rescue-v2`。
- 历史因果代理新增 `46/71=64.7887%`，严格单仓 `+499.4995%`、两仓
  `+205.3783%`；2026 年 3-7 月新增组仅 `11/20=55%`，所以当前状态只能是
  `historical_proxy_pass_forward_unconfirmed`。

## Frozen rule

1. 每只股票每天只认第一次 `sealed/resealed`；触板时若当天已经出现正式 A+B，则拒绝。
2. 候选必须处于首板/二进三正式窗口、数据就绪、非 stale、无 lane blocker，并且只是被
   核心质量门的“同股样本不足、同股联合率不足或半年涨停超过 6 次”排除。
3. 静态补位包括：混合期低位回撤首次触板；或行业 D-1 成交额扩张且同股联合率低于
   30%。普涨期行业覆盖还必须是个股 5 日回撤。
4. 动态补位使用候选全部严格 D-1 概念成员，按先行封板密度和宽度选细分概念。候选触板
   前已有 2-4 只成员封板、最高至少 2 板，并满足混合期首次触板或非普涨回撤。
5. 每天只取第一笔影子补位，后续容量留给可能稍后出现的正式 A+B。
6. D+1 使用官方收盘和正式费用结算；D 日最终状态、当天后续 A+B 和 D+1 收益都不参与
   当时选择。必要字段缺失时失败关闭。

旧的 `warming -> launch`、固定动态龙二/龙三、成交额三分钟加速，以及“必须先通过 A+B
核心门”已经被逆向结果反证，不属于本报告冻结的影子规则。

## Acceptance gate

- 新增组至少 15 笔闭合交易、至少新增 10 个交易日。
- 新增组与合并组胜率均 `>=60%`。
- 合并日等权复利高于同一自然前向窗口的 A+B 基线。
- 合并最大回撤不差于同一自然前向窗口的 A+B 基线。
- 通过后仍为 `research_only`，不能由回放自动改写正式合同。

## Data contract

雷达观察从 2026-07-27 起保存 `board_level`、全部有界概念候选及成员数、成员快照日期、
概念触发可用性、D-1 五日收益和 D-1 市场阶段。`signal_kind` 可由 `capture_state` 无损
恢复，不重复持久化。

## How to verify

```bash
docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.limit_up.concept_diffusion_shadow_replay

uv run pytest -q \
  tests/alphaagent/test_limit_up_concept_diffusion_shadow.py \
  tests/alphaagent/test_limit_up_radar_observation_repository.py
```

回放必须分别报告 A+B 基线、影子新增、合并、增加交易日、复利、回撤和每条验收门。
`collecting_forward` 只表示样本不足，不允许据此调整阈值。

## Open risks

- 早期历史概念成员绝大多数是当前成员幸存者代理；历史达标不能替代自然前向。
- 聚合行情不能证明涨停价排队真实成交；影子收益仍是价格代理，不是券商交割结果。
- 3-7 月已经参与规则研究，而且新增组自身低于 60%；不得再称为独立盲测。
