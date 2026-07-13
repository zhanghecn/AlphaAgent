# 首板双通道影子系统实施计划

## 1. 固化纯研究规则

- 新建 `alphaagent/server/services/limit_up/first_board_dual_lane.py`。
- 实现快照包络校验、轮动候选分类、同日首次触发提取和前向覆盖统计。
- 只接受真实 `live_snapshot`；明确禁止历史代理输入。

## 2. 完善概念组点时字段

- 在 `live_repository._concept_group_contexts()` 中保留概念组资金日期。
- 在 `sector_warmup` 中传递概念趋势、资金日期并计算概念组动态龙头和触板扩散数。
- 在 `live_service` 稳定性字段生成后附加轮动影子分类。
- 在 `live_policy._signal()` 中序列化影子字段，不读取它们决定动作。

## 3. 接入真实四仓账户

- 让 `sector_warmup_research` 提供未截断的分组交易选择结果，并保留现金撮合所需价格、日期和结果字段。
- 在 `history_service` 缓存静态历史研究和静态账户输入。
- 从真实前向快照提取轮动触发，只把已有 D+1 日线的触发标为闭合。
- 分别撮合基线、原预热门、延续质量门和双通道账户，返回执行摘要。

## 4. 扩展产品界面

- 扩展 `frontend/src/api/limitUp.ts` 的轮动字段、现金账户和前向状态类型。
- 在 `SectorWarmupResearchPanel` 增加紧凑的真实四仓对比和轮动验证状态。
- 在实时首板行展示轮动影子状态；不增加操作入口。

## 5. 验证

- 先补后端失败测试，再实现规则和账户编排。
- 补前端静态渲染测试，确认关键信息和零样本提示。
- 运行定向测试、后端全量测试、前端全量测试、TypeScript/Vite 生产构建和 `git diff --check`。
- 重建本地 Compose 服务，核对真实接口数值，并用桌面/移动端浏览器截图验证。
- 将当前结果、数据边界和下一步前向门槛更新到 `memory/06_backtests/limit_up_sector_warmup_first_board.md`。
