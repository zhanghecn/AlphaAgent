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
- `alphaagent_limit_up_recognition_gate_robustness_research_plan.md`：针对半年涨停超过 6 次
  候选的只读稳健性研究计划；冻结高频分组、时间盲测、负对照和自然前向晋级门，未改变
  当前正式 A+B+C 合同。
- `alphaagent_limit_up_recognition_gate_reverse_daily_winner_research_plan.md`：已执行的半年触板
  次数门移除反向审计；逐日高收益赢家、次数分桶和时间批次均为只读证据，不改变正式合同。
- `alphaagent_limit_up_recognition_gate_window_grid_research_plan.md`：已执行的 42/63/126 交易日、
  `1..10` 连续区间网格研究；严格时序样本不足，不能由样本内首位替换当前 `126:2-6`。

## Current decision

- 当前正式合同只有 `limit-up-core-abc-v2`，状态为
  `historical_proxy_pass_forward_unconfirmed`。全量正式闭合 `96/140=68.5714%`，平均净收益
  `+2.0988%`；两仓实际成交 `69/94=73.4043%`、复利 `+195.3585%`。规则、交割和风险边界见
  `memory/06_backtests/limit_up_abc_formal_replay_20260727.md`。
- 次数识别门的 165 组网格已验证 560/560 个重算计数一致，但固定严格验证缺少 246 个候选
  交易日；当前维持 `prior_limit_count_126` 的 `2-6`，没有上线参数变更。
- 旧需求、低吸计划和市场择时计划已由提交 `f99d4afc` 删除，不再保留失效文件链接；需要
  审计历史时使用 Git 读取删除前版本，不把它们恢复成当前合同。
