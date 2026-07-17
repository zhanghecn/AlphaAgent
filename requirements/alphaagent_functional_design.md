# AlphaAgent Functional Design

## Architecture

AlphaAgent 业务代码位于 `alphaagent/`，React 前端位于 `frontend/`，vn.py 兼容核心保持在 `vnpy/`。PostgreSQL 保存原始/派生研究数据，Redis 用于运行缓存。

## Functional Modules

### Market Data

- 股票清单、日线、分钟线、竞价、资金流、财务和事件同步。
- 概念/行业清单、成员、日线、资金流和点时成员快照。
- 数据健康检查区分空表、局部发布、历史深度不足和正常增量。
- 新部署从空库通过供应商和调度任务自主同步，不复制数据库作为初始化流程。
- 分钟线产品入口只同步系统源近端数据；历史缺口由数据库覆盖审计自动生成并在服务端补偿，不接受 CSV、文件路径、缺口清单或旧回测 ID。
- 供应商不可用、空响应或覆盖不足时不写库，并保持相应质量门禁关闭。

### Mainline Research

- `/api/mainline-replay/*` 提供概念主线时间线、快照、关系、成分龙头和情绪周期。
- 历史查询只使用查询日及以前可见数据；盘中投影不写回历史评分。
- 个股页展示概念身份和概念内综合龙头排名，不触发策略回测。

### Market Timing

- `services/market_timing/` 负责金手指、银手指、阶段、面板和历史验证。
- `services/market_context.py` 提供点时市场上下文。
- 市场择时与未来低吸可以共享只读市场上下文，但不共享策略绩效。

### Short-term Research

- `/short-term` 是统一入口，当前渲染打板研究。
- 打板使用 `services/limit_up/`、独立历史账本、现金账本和前向证据。
- 低吸产品化前必须建立独立命名空间、独立版本、独立成交账本和独立绩效。
- 两类研究以后用 Tab 导航，禁止把候选或收益合并成一个回测。

### Data Scheduling

允许的 schedule action 只有：

- `sync`
- `limit_up_live_scan`
- `limit_up_concept_scan`

默认链路保留竞价、盘中资金、打板扫描、概念扫描、19:00 更新、21:30 证据补偿和历史账本刷新。旧 `quant_research`、`tail_preview` schedule 在启动对账时删除。

自动计划可在数据管理页手动“立即执行”，对应 `POST /api/data-sync/schedules/{schedule_id}/run`；手动执行复用同一供应商、审计和门禁规则。

## Removed Modules

旧 `services/quant`、`services/backtest`、`services/portfolio` 和 `services/simulation` 已删除。通用回测、持仓和模拟表不属于当前 metadata，并由固定清单做一次性物理清理。

## Quality Gates

- Python 编译和聚焦 pytest。
- 前端 Vitest、TypeScript 和 Vite 生产构建。
- 打板现金账本/历史指纹不得变化。
- 数据库清理前后对比保留表数量和覆盖日期。
- 桌面与 390x844 浏览器验证、无控制台错误。
