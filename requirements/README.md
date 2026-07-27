# AlphaAgent Requirements Index

这里保存当前仍存在且有验证价值的研究计划。源码、测试、`memory/09_decisions/decisions.md`
和 `memory/06_backtests/README.md` 是运行事实与研究结论的当前入口。

## Current files

- `alphaagent_limit_up_leader_cycle_factor_research_plan.md`：已归档的 Tasks 0-6 连板、市场
  情绪和覆盖审计；后续题材归因与分钟传播任务已停止。
- `alphaagent_dynamic_concept_leader_cycle_research_plan.md`：已归档的日级资金主线研究；
  2026-03..07 同窗状态为 `rejected_no_incremental_value`，不进入正式策略。
- `alphaagent_limit_up_leader_follower_factor_research_plan.md`：已归档的确认龙、概念响应和
  龙二龙三映射研究；静态成交额承载门在独立历史为 29 笔、55.17%，状态为
  `historical_proxy_rejected`。
- `alphaagent_limit_up_dynamic_wave_leader_research_plan.md`：已归档的可重启概念资金波段和
  动态趋势/容量/连板龙研究。固定龙头身份和静态概念成交额不能单独形成正式硬门。
- `alphaagent_limit_up_compound_repair_plan.md`：A+B+C 复利修复的正式实施结果、因果时序、
  分层时间门、账户容量和前向验收合同。

## Current decision

- 正式合同只有 `limit-up-core-abc-v1`，当前状态为
  `historical_proxy_pass_forward_unconfirmed`。正式闭合 `99/143=69.2308%`，单仓复利
  `+457.7327%`、两仓复利 `+226.6771%`。规则、交割和风险边界见
  `memory/06_backtests/limit_up_abc_formal_replay_20260727.md`。
- 旧需求、低吸计划和市场择时计划已由提交 `f99d4afc` 删除，不再保留失效文件链接；需要
  审计历史时使用 Git 读取删除前版本，不把它们恢复成当前合同。
