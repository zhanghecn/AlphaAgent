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
  动态趋势/容量/连板龙研究。质量重建发现已由唯一正式合同
  `limit-up-core-ab-v1` 接收：A+B 为 `56/78=71.79%`，A 优先、B 可交易；C 级扩容已否决。

## Current decision

- 正式合同只有 `limit-up-core-ab-v1`，当前状态为
  `historical_pass_forward_not_passed`。规则、交割和风险边界见
  `memory/06_backtests/limit_up_final_trading_scheme_20260726.md` 与
  `memory/06_backtests/limit_up_core_ab_formal_validation_20260726.md`。
- 旧需求、低吸计划和市场择时计划已由提交 `f99d4afc` 删除，不再保留失效文件链接；需要
  审计历史时使用 Git 读取删除前版本，不把它们恢复成当前合同。
