# AlphaAgent 当前金银信号展示设计

## 问题

市场择时 API 已区分两个概念：

- `overview.current_direction`：最新交易日是否处于金区、银区或中性区。
- `overview.latest_signal`：历史上最近一次已确认事件，不代表当前方向仍有效。

`TimingHero` 的指环正确使用 `current_direction`，但下方无条件展示
`latest_signal`。当 `2026-07-15` 当前方向为 `NEUTRAL` 时，页面仍突出显示
`2026-06-11 金手指`，容易让用户把历史事件误读为当前金手指。

## 目标

- 当前摘要只表达最新交易日的金、银或无信号状态。
- 当前中性时明确显示“当前无金银信号”，不出现历史金银标签。
- 历史金银事件继续保留在 K 线、日期表和准确率记录中。
- 不修改金银算法、事件日期、确认状态、API 数据或仓位逻辑。

## 方案

只修改 `frontend/src/features/market-timing/TimingHero.tsx`：

1. 指环继续读取 `overview.current_direction`。
2. 中心的 `NEUTRAL` 文案由“观望”改为“无信号”。
3. 删除主摘要中无条件渲染的“最近信号”行。
4. 当 `current_direction === "NEUTRAL"` 时，在合力条下显示
   “当前无金银信号”，并附最新因子日期。
5. 合力条标签改为“多头合力 bull / 空头合力 bear”，不在中性摘要中写
   “金手指区 / 银手指区”。
6. 金区或银区只由当前指环显示方向，不从历史 `latest_signal` 补标签。

后端继续返回 `latest_signal` 以保持接口兼容；本次不删除字段，也不影响其他历史视图。

## 验收

- `current_direction=NEUTRAL` 且 `latest_signal=GOLD` 时，主摘要显示
  “无信号 / 当前无金银信号”，不渲染“最近信号”、历史日期或“金手指”文本。
- `current_direction=GOLD` 时，指环仍显示“金手指”。
- `current_direction=SILVER` 时，指环仍显示“银手指”。
- K 线和历史日期表仍能读取并展示历史事件。
- 前端测试、类型检查和生产构建通过。
- 重建 Web 后，真实 `/market` 最新日不再把 `2026-06-11` 金手指显示在当前摘要。
