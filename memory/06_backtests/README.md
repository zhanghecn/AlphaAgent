# Research Evidence Index

## 打板续研入口

### Current state

- 唯一正式合同是 `limit-up-core-ab-v1`，历史、实时、调度和现金账本同源且没有旧规则
  回退。原正确财报、结构、lane、盘中支撑和同股盈利门通过后，统一要求
  `2 <= prior_limit_count_126 <= 6`；D-1 行业成交额相对前 5 日均值 `>=1.0` 为 A，
  其余为 B。A 优先，B 仍可交易，C 不属于正式合同。
- 806 个可靠交易日只是行情背景。真实事件覆盖 `2025-06-27..2026-07-24`，正式闭合
  推荐覆盖 `2025-07-10..2026-07-23`。A+B 共 78 笔，`56/78=71.7949%`，平均净收益
  `+2.2512%`，最大回撤 `-14.5416%`；A 为 `35/41=85.3659%`，B 为
  `21/37=56.7568%`。78 笔分布在 50 个交易日，同日可以有多笔。
- 最近旧保存快照的 A+B 反事实只有 `12/24=50%`、平均 `-0.2351%`。当前状态固定为
  `historical_pass_forward_not_passed`；历史结果不是实盘胜率承诺，也不允许恢复旧财报
  缺失筛选。
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
  但多概念重复归属仍有噪声。动态龙二龙三追涨率不足 50%；低位跟随和早期扩散交叉只保留
  为研究排序证据，不参与当前 A+B 准入或扩容。
- 静态概念成交额前 20% 在 3-7 月为 `33/42=78.5714%`，但发现期前独立历史仅
  `16/29=55.1724%`，状态为 `historical_proxy_rejected`。A+B+C 虽为
  `80/121=66.1157%`，新增 C 只有 `24/43=55.8140%` 且 2025 分段低于 60%，已否决。

### Evidence

- 当前正式方案：`limit_up_final_trading_scheme_20260726.md`。
- A+B 重建、交割单和最近快照：`limit_up_core_ab_formal_validation_20260726.md`。
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

### How to verify

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_*.py
uv run python -m compileall -q alphaagent/server/services/limit_up
npm --prefix frontend test -- --run
npm --prefix frontend run build
git diff --check
```

### Open risks and next work

- `limit-up-core-ab-v1` 必须从新合同实际保存快照起累计至少 60 个交易日、30 笔闭合全量
  买点和两个情绪阶段，再按全量胜率 `>=60%`、均值为正、回撤和硬亏决定自然前向是否通过。
- 3-6 月缺少历史点时概念成员，既有 3-7 月和 806 日历史均已查看，只能作假设生成或
  反例证据。新的资金扩散/集中、成交额持续/加速与市场风险容量交互只能用未见数据验证。
