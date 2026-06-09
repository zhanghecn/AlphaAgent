# Decisions

## 2026-06-07

- 保留 `AGENTS.md` 作为 Codex/后续协作入口。
- 用户要求后续不要主动提交或推送；只有用户明确说“提交”或“push”时才执行 git commit/push。
- 删除之前生成的本地 A 股教程 md、临时 py、临时 CSV 数据，因为它们没有充分基于项目结构和源码梳理。
- 新建 `memory/` 作为长期上下文地图，按类型维护项目事实。
- 需求分析文档单独放在 `requirements/`，不混在 `memory/` 中。
- 新增 `requirements/alphaagent_functional_design.md` 作为功能模块与执行流程设计文档。
- 新增 `requirements/alphaagent_service_frontend_execution_plan.md` 作为 vn.py 服务化、前后端分工、API 草案和 MVP 执行计划。
- 项目外显名称改为 `AlphaAgent`，目标是基于 vn.py 做服务端化 A 股自动量化、Agent 智能选股和交易系统。
- 不重命名 `vnpy/` Python 包目录，也不修改 Python 发行包名 `vnpy`，避免破坏 vn.py 插件依赖和已有导入路径。
- 后续重写文档时，必须同时覆盖：
  - 项目整体结构。
  - 源码入口。
  - 数据接入链路。
  - A 股相关插件和能力边界。
  - 如何调试看数据。
  - 如何从选股/策略/回测/实盘逐步搭建系统。
