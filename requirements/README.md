# AlphaAgent Requirements Index

这里保存当前产品设计和仍有验证价值的实施证据。源码和测试是运行事实的最终依据。

## Current Contracts

- `alphaagent_requirement_map.md`: 当前用户目标、产品边界和优先级。
- `alphaagent_limit_up_leader_cycle_factor_research_plan.md`: 从首板点火、连续/反包二进三、
  空间妖股和容量中军出发，分日级周期与严格分钟传播研究龙头带动板块，并只在正式打板
  质量池内验证 D+1 排序增量。
- `alphaagent_functional_design.md`: 当前模块、数据流和隔离规则。
- `alphaagent_service_frontend_execution_plan.md`: 当前后端/前端运行形态与接口边界。
- `alphaagent_low_suction_research_reset_design.md`: v2 唯一设计基线；从无预设分钟状态面板
  发现规则，依次冻结主升、Top3、入场、退出和仓位。
- `../docs/superpowers/plans/2026-07-16-low-suction-research-direction-v2.md`: v2 逐任务实施计划、
  测试合同、滚动验证和一次性锁定留出门禁。
- `../docs/superpowers/plans/2026-07-17-low-suction-forward-top3-ledger.md`: 免费严格前向
  Top3 的同源日门禁、不可变排名账本、真实下一交易时段绑定、无收益身份评估和 EOD
  自动积累合同。
- `alphaagent_low_suction_security_history_implementation_plan.md`: 证券历史完整性合同、
  原子作用域、BaoStock 重建证据和严格覆盖隔离。
- `alphaagent_low_suction_concept_history_implementation_plan.md`: 复用共享东方财富概念
  指数、800 日回补、动态横截面审计，以及指数与点时成员的隔离边界。
- `alphaagent_low_suction_stock_history_implementation_plan.md`: 共享股票日线 750 日目标、
  800 根全市场自举和盘中完成时点保护。
- `alphaagent_low_suction_dc_membership_implementation_plan.md`: Tushare DC 同 BK 体系历史成员
  的只读探测、D-1 滞后、完整性 scope 和原子回补；工程已完成，真实 pilot 因 token
  和 6,000 积分阻塞。
- `alphaagent_low_suction_theme_eligibility_research_plan.md`: 真实题材与事件/风格板块的
  成员动态、训练/留出和失败关闭研究框架；真实全目录分类和阈值等待严格成员。
- `alphaagent_free_forward_evidence_implementation_plan.md`: 免费东方财富成员和 BaoStock
  证券状态的原子完整性 scope、19:00/21:30 重试、D-1 有效日和三年积累门禁。
- `alphaagent_legacy_quant_removal_implementation_plan.md`: 旧量化、通用回测、持仓和模拟账户的受控删除清单。

## Preserved Research

- `alphaagent_low_suction_research_implementation_plan.md`: 已完成但不再执行的 v1 家族代理
  工程记录；不能作为当前研究方向。
- `alphaagent_limit_up_*.md`: 打板研究的设计、历史回放、现金账本、实时执行和前向验证证据。
- `alphaagent_market_timing_*.md`: 金手指、银手指和大盘阶段研究。
- `alphaagent_data_sync_management_plan.md`、`alphaagent_unified_*.md`: 原始行情与定时同步的历史实施依据。
- `alphaagent_sector_stock_research_dashboard_plan.md`: 概念主线和个股研究工作台。

## Product Boundary

- 当前入口包括今日市场、大盘择时、概念主线、短线研究、全 A 股票和数据管理。
- `/short-term` 当前承载独立的打板研究；旧 `/limit-up` 仅重定向到该入口。
- 低吸 v1 家族先验方向已经废止。V2 协议与主升周期阶段已执行，`breakout_trend` 在
  5/5 滚动折胜出并冻结；该结果只描述概念状态持续性。Top3、分钟入场和正式绩效仍被
  严格历史成员/证券状态阻断，结论为 `blocked_by_data_quality`，页面不增加低吸 Tab。
- V2 最终资格按用户目标固定为锁定留出胜率和现金复利均严格大于 60%，并至少在两个
  物质市场环境中分别达到胜率大于 60%；当前所有正式交易指标仍为 `null`。
- 首个 `2026-07-16` 严格前向 Top3 源日已冻结，三模式仍为
  `selected_mode=null`；身份选择至少等待 60 个已绑定源交易时段，且不读取低吸收益。
  三年历史成员/证券门禁仍未解除，前向工程进展不能冒充历史正式回测。
- 历史研究不再等待前向样本：现已将历史事件 Top3 代理的真实 5 分钟低吸成交与 D-1
  个股阶段、四条承接确认合并。25 个充分样本组没有高胜率确认；唯一两段正期望组受
  GOLD/SILVER 时间分布混淆，仍不生成正式规则。证据见
  `memory/06_backtests/low_suction_historical_phase_entry_study_20260717.md`。
- DC 历史成员与题材资格工程验证见
  `memory/06_backtests/low_suction_dc_membership_theme_framework_20260716.md`。
- 免费前向采集工程和首轮真实失败关闭证据见
  `memory/06_backtests/low_suction_free_forward_capture_20260716.md`。
- 旧 `/quant`、`/portfolio`、通用回测和模拟账户已删除，不再作为需求来源。
