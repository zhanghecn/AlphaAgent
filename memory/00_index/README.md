# Memory Map

`memory/` 是 AlphaAgent 的当前项目地图，不是聊天记录或实验流水。

## Read Order

1. `09_decisions/decisions.md`: 已确认的产品边界和研究约束。
2. `01_project/structure.md`、`01_project/installed_state.md`: 仓库和插件状态。
3. `02_source/core_entrypoints.md`: 当前源码入口。
4. `03_data/data_flow.md`: 当前真实数据路径和覆盖约束。
5. `05_runtime/run_debug.md`: 最短运行/验证命令。
6. `06_backtests/README.md`: 保留研究的当前结论和证据链接。
7. `07_market_timing/`: 金手指、银手指和大盘阶段研究。

需求合同位于 `requirements/`。低吸研究先读
`requirements/alphaagent_low_suction_research_reset_design.md`。

## Typed Folders

- `01_project/`: 项目结构、文档、插件和安装状态。
- `02_source/`: vn.py 与 AlphaAgent 核心入口。
- `03_data/`: Datafeed、数据库、同步和历史/实时数据路径。
- `04_a_share/`: A 股插件能力和限制。
- `05_runtime/`: 运行、调试和部署。
- `06_backtests/`: 打板/择时等保留产品的验证证据。
- `07_market_timing/`: 大盘择时设计和使用边界。
- `09_decisions/`: 当前决策和未解决风险。

## Maintenance

- 优先改写现有总览，保持“当前状态、验证入口、证据、风险”四段结构。
- 长表、原始输出和详细回放只放专门证据文件。
- 删除已经失去产品对象的规则、脚本和报告，不在总览保留兼容说明。
- 瞬时实验、失败命令和聊天过程不写入长期记忆。
