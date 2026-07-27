# Research Evidence Index

## 打板续研入口

### Current state

- 唯一正式合同是 `limit-up-core-abc-v1`，历史、实时、调度和现金账本同源。当前代码、
  查询和页面没有其他打板合同入口。A/B 基座要求正确财报、结构、lane、盘中支撑、同股
  盈利门及过去 126 日涨停 2-6 次；行业量能扩张为 A，否则为 B。C 只覆盖三个冻结拒绝
  原因，并交叉资金/回撤或触板前动态概念扩散。
- 806 个可靠交易日只是行情背景。真实事件覆盖 `2025-06-27..2026-07-24`，正式闭合
  推荐覆盖 `2025-07-10..2026-07-23`。A+B+C 共 143 笔，`99/143=69.2308%`，平均
  净收益 `+2.1203%`，独立信号复利 `+762.4136%`；A 为 `35/41=85.3659%`，C 为
  `46/72=63.8889%`，B 为 `18/30=60%`。143 笔分布在 108 个交易日，同日可以有多笔。
- 严格单仓成交 80 笔、胜率 71.25%、复利 `+457.7327%`、回撤 `-19.4234%`；两仓
  成交 96 笔、胜率 75%、复利 `+226.6771%`、回撤 `-8.8039%`。两仓在尚无 A 时只允许
  一个 B/C，34 条信号因给后续 A 保留仓位而跳过。
- 当前状态固定为 `historical_proxy_pass_forward_unconfirmed`；历史结果不是实盘胜率承诺。
  自然前向从 `2026-07-27` 起只累计当前合同新信号；数据库此前保存的原始帧不进入前向分母。
- A+B 亏损与漏选反向审计已覆盖核心门前 560 笔闭合事件：A+B 从 179 个有候选日保留
  50 日；129 个无买点日中 41 日存在事后 `>=5%` 漏选赢家。全天无 A+B 只能用于逆向
  发现，因为盘中不知道当天后来是否会出现 A+B。修正为“触板时此前尚无 A+B”后，
  资金/回撤/动态概念扩散形成 C。逆向定义阶段为 `46/71=64.7887%`；接入分层时间门和
  同秒因果顺序后的正式闭合为 `46/72=63.8889%`。2026-03..07 发现段偏弱且早期概念
  成员存在幸存者偏差，所以 C 虽进入正式排序，仍必须显式标记前向未确认。
- 修复前财报覆盖是按当前成交额和市值优先同步造成的非随机粘性白名单，隐含了持续资金
  关注和市场辨识度。正确财务同比本身仍有正边际；质量重建恢复的是旧覆盖的经济含义，
  不是错误数据缺失条件。

### Leader-cycle conclusions

- 3-7 月研究已归档：100 个交易日、22 个市场情绪周期、1,668 个动态概念周期。市场
  空间龙、概念资金龙和波段趋势/容量龙是不同角色，不能用固定概念名单或单日连板榜替代。
- 龙头到龙二龙三研究包含 449 个确认事件和 986 条唯一映射。映射后 1 日上涨率整体
  `52.8147%`，非分歧 `55.0318%`、分歧 `43.7500%`；“龙二/龙三身份”不是稳定的
  `>=60%` 正向硬门，分歧状态更适合作为风险解释。
- 动态波段算法已识别金安国纪、亨通光电、东山精密、德明利和深科技的趋势/容量领导力，
  但多概念重复归属仍有噪声。固定龙二/龙三追涨率不足 50%；新的有效代理不是固定名次，
  而是候选触板前细分概念已有 2-4 只成员封板且最高至少 2 板，并与 D-1 资金扩张、市场
  阶段和个股回撤交叉。它已进入 C，但不能脱离三个可覆盖拒绝原因单独放行。
- 静态概念成交额前 20% 在 3-7 月为 `33/42=78.5714%`，但发现期前独立历史仅
  `16/29=55.1724%`，状态为 `historical_proxy_rejected`。A+B+C 虽为
  `80/121=66.1157%`，新增 C 只有 `24/43=55.8140%` 且 2025 分段低于 60%，已否决。

### Evidence

- 当前正式方案和最终因果复核：`limit_up_abc_formal_replay_20260727.md`。
- 前一 A+B 方案（历史对照）：`limit_up_final_trading_scheme_20260726.md`。
- A+B 重建、交割单和最近快照：`limit_up_core_ab_formal_validation_20260726.md`。
- A+B 亏损票、41 个漏买日、点时分组和扩容反证：
  `limit_up_quality_opportunity_reverse_20260726.md`。
- 空仓日逆向分组、因果修正、严格账户和逐笔账本：
  `limit_up_no_trade_day_reverse_factor_20260727.md`、
  `limit_up_causal_rescue_ledger_20260727.csv`。
- 财报覆盖根因、质量消融和 A 级逐票账本：
  `limit_up_quality_reconstruction_20260726.md`、
  `limit_up_financial_coverage_reverse_reasoning_20260726.md`。
- 806 日日线代理边界：`limit_up_daily_proxy_quality_806d_20260726.md`。
- 正式涨停价入场语义：`limit_up_formal_entry_price_audit_20260725.md`。
- 市场周期、资金主线和消融：`limit_up_leader_cycle_2026_03_07.md`、
  `limit_up_capital_mainline_cycle_2026_03_07.md`、
  `limit_up_capital_mainline_fund_ablation.md`、
  `limit_up_capital_mainline_candidate_counterfactual.md`。
- 龙头映射和独立历史验证：
  `limit_up_leader_follower_factor_formal_discovery_2026_03_07.md`、
  `limit_up_leader_follower_factor_806d_validation.md`。
- 可重启动态波段与命名案例：`limit_up_dynamic_wave_leader_root_cause_20260726.md`、
  `limit_up_dynamic_wave_leader_discovery_2026_03_07.md`。
- 七月严格分钟传播覆盖失败：`limit_up_leader_propagation_intraday_202607.md`。
- 概念启动早期扩散自然前向：`limit_up_concept_diffusion_shadow_20260726.md`。

### How to verify

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_*.py
uv run python -m compileall -q alphaagent/server/services/limit_up
npm --prefix frontend test -- --run
npm --prefix frontend run build
git diff --check
```

### Open risks and next work

- `limit-up-core-abc-v1` 必须从新合同实际保存快照起累计至少 60 个交易日、30 笔闭合全量
  买点和两个情绪阶段，再按全量胜率 `>=60%`、均值为正、回撤和硬亏决定自然前向是否通过。
- C 从 `2026-07-27` 起单独收集，至少 15 笔并新增 10 个交易日
  后，才比较新增/合并胜率、合并复利和最大回撤；样本不足时不修改阈值。历史 3-7 月
  新增组只有 55%，是必须由自然前向回答的风险，不得隐藏在全历史合并成绩中。
- 3-6 月缺少历史点时概念成员，既有 3-7 月和 806 日历史均已查看，只能作假设生成或
  反例证据。新的资金扩散/集中、成交额持续/加速与市场风险容量交互只能用未见数据验证。
