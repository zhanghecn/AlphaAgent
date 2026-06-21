# Requirements

这里存放 AlphaAgent 的需求分析、产品设计和执行流程文档。

## 文档

- `alphaagent_requirement_map.md`: 原始需求和需求地图，整理用户想法。
- `alphaagent_functional_design.md`: 功能模块与执行流程设计，说明系统要做什么、如何结合 vn.py、用户最终看到什么。
- `alphaagent_service_frontend_execution_plan.md`: 服务端与前端执行方案，说明 vn.py 服务化边界、前端页面、API 契约、数据模型和 MVP 阶段。
- `alphaagent_data_sync_management_plan.md`: 数据同步管理模块执行计划，说明数据源管理、定时同步、立即执行、任务状态、失败重试和稳定性设计。
- `alphaagent_sector_stock_research_dashboard_plan.md`: 板块主线仪表盘与个股投研工作台执行计划，说明主线热度、板块关系图、动态产业链、季度财报、主营历史和前后端接口契约。
- `alphaagent_quant_backtest_portfolio_plan.md`: 量化选股、回测与持仓模块执行计划，说明洗盘/试探代理信号、弱市抗跌、财报改善、MA5 低吸、真实回测和持仓分组。
- `alphaagent_pullback_low_suction_strategy_research.md`: 回踩低吸/龙回头策略优化研究，审计六只样本股、现有策略缺陷、游资打法量化映射和新状态机方案。
- `alphaagent_dragon_pullback_implementation_plan.md`: `mainline_dragon_pullback` 第一版实现计划，说明新增策略、卖出逻辑、测试和验证范围。
- `alphaagent_strategy_drawdown_optimization_plan.md`: 下一阶段回撤、卖出和候选排序优化计划，要求先补 MAE/MFE/卖后反弹诊断，再做全局回测验证后决定是否保留策略改动。
- `alphaagent_low_suction_factor_validation_plan.md`: 低吸/龙回头因子验证执行计划，说明内部双入场引擎、候选特征表、固定持有后验表、因子分桶胜率、统一策略时间线和默认关闭实验晋升标准。
- `alphaagent_quant_strategy_next_execution_plan.md`: 下一阶段量化策略验证执行计划，先修正产品基线选择，再补细粒度特征表、买卖问题归因、股票详情统一时间线和默认关闭实验门槛。
- `alphaagent_quant_feature_validation_execution_plan.md`: 量化策略特征表校验执行计划，说明除全局回测外如何用候选特征、固定持有后验、真实组合归因、市场/主线环境、低吸生命周期和替换交易质量判断收益提升或亏损降低的真实来源。
- `alphaagent_quant_feature_drilldown_next_execution_plan.md`: 后续细粒度特征校验执行计划，明确候选信号日特征、固定持有后验、真实组合归因、卖点/替换质量、动态大盘/主线画像、低吸/龙回头生命周期、前端整合和默认关闭实验晋升门槛。
- `alphaagent_quant_next_experiment_execution_plan.md`: 下一轮默认关闭实验执行计划，在已有特征审计之后继续拆 `candidate_not_planned`、重点股票逐日证据、支撑止损延迟确认、高浮盈回撤保护、低吸假启动观察/降权和满仓换仓质量，要求用统一报告证明收益提升或亏损降低来源。
- `alphaagent_quant_feature_table_execution_plan.md`: 下一轮特征表校验与默认关闭实验总入口，明确除全局回测外要用哪些候选、生命周期、固定后验、真实执行、卖点替换、市场主线和机会成本表做细致比对，以及实验晋升门槛。
- 当前量化策略状态和后续方向不再维护零散阶段计划；统一看 `memory/06_backtests/README.md`、`memory/06_backtests/strategy_optimization_ledger.md` 和 `memory/09_decisions/decisions.md`。

## 维护规则

- 需求和产品设计放在本目录。
- 已验证的项目事实、源码入口、数据链路放在 `memory/`。
- 实现代码不要放在本目录。
