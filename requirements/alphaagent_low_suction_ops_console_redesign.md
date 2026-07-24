# 低吸研究页作战指挥台重设计（对齐打板体验）

- 日期：2026-07-22
- 状态：已完成（P0-P3 全部落地，端到端验证通过）
- 范围：UX 全面对齐打板研究 + 确认 Bug 修复 + 算法小改（幸存者偏差历史成分库单独立项，不在本次范围）
- 页面：`/short-term?research=low-suction`
- 实施偏差说明：原设计的「纸面账户条」与 2026-07-21 决策（前向验证不作一级入口、
  不展示账户权益/持仓面板）冲突，落地为安静边界行（前向账本 x/300 笔 · 执行方式 ·
  D+2 影子），如需完整账户条需主人另行确认。

## 背景与诊断结论

对照打板研究（`/short-term` 默认 tab）的成熟体验：OpsFlowRail 5 节点步进器、
门禁指挥条（4 tone 状态灯）、近期质量条、折叠轨迹、回测 01-06 编号章节、
规则说明手风琴步骤轨。低吸页当前为三 tab（实时推荐/回测分析/规则说明），
信息架构扁平，且存在已确认 Bug。

### 已确认 Bug（证据见下）

1. **【致命】实时信号管道静默死亡**
   - `swing_strategy_repository.py` `load_signal_static_context` 用
     `columns=schema.low_suction_paper_positions.c.keys()` 构造 `open_positions`
     帧，带上 `entry_*`/`exit_*` 全部持仓台账列（0 持仓也有列名）。
   - `swing_strategy.py` `_reject_future_or_outcome_columns` 按前缀拦截
     `entry_*`/`exit_*`/`future_*`/`mae_*`/`mfe_*`/`outcome_*`，永久抛
     `SwingSignalInputError("future_or_outcome_columns_prohibited")`。
   - DB 实证：`low_suction_strategy_runs` 中 2026-07-20 `signal_1450`、
     2026-07-22 `signal_preview` 均 blocked，reason 同上；`entry_1455` 连带
     `signal_capture_not_ready`。策略上线以来从未产出信号，UI 却显示
     "今日暂无买入推荐"（静默失败）。
   - 修复：repository 层将 `open_positions` 投影为信号真正使用的列
     （`vt_symbol`/`sector_id`/`status`），守护逻辑保持 fail-closed 不动。

2. **【中】英文枚举泄漏 UI**：`sessionStatusLabel` 缺 `awaiting_signal_window`
   与 `blocked` 键，fallback 显示原文；`pre_market`/`trading` 为死键。

3. **【小】D+2 影子硬编码 `/20`**：应用 API 返回的 `target_samples`。

4. **【代码健康】**：
   - `LowSuctionForwardLedger.tsx`（121 行）零引用，连带
     `fetchLowSuctionForwardLedger` 与相关类型全死。
   - `fetchLowSuctionSwingResearch` 拉取 `/low-suction/swing-research`
     整个 payload 仅作 loading 门闩，数据全部丢弃；实际只需要
     `/low-suction/cross-regime-validation`。
   - `formatPct`/`rateTone`/`phaseLabel`/`Metric`/`Definition` 在
     workspace 与 ledger 间复制粘贴。
   - 视图 tab 纯 `useState`，不同步 URL，无法深链。
   - 轮询 60s 硬编码，未使用后端 `session.auto_refresh_seconds`。

## 设计

### P0：后端 Bug 1 修复（最高优先级）

- `swing_strategy_repository.py`：`load_signal_static_context` 的
  `open_positions` 查询只 select 信号所需列（`vt_symbol`、`sector_id`、
  `status`），DataFrame 构造同步收窄。
- 回归测试：构造含全量持仓列的场景验证捕获不再被误杀；同时保留
  "特征帧带 `future_` 列必须被拒"的既有测试。
- 验收：本地跑 `capture_swing_preview`（preview 窗口内）不再出现
  `future_or_outcome_columns_prohibited`。

### P1：实时推荐 → 作战指挥台（前端，数据全部现成）

四层结构（对照打板 LiveView）：

1. **作战流程步进器**：新建 `features/lowSuction/lowSuctionFlow.ts` 纯函数
   构建器（仿 `features/limitUp/opsFlow.ts`），6 节点：
   早盘预警 09:30 → 上午跟踪 10:30/11:30 → 午间休市 → 下午跟踪 13:30/14:30
   → 尾盘确认 14:50 → 纸面买入 14:55。由 `session.phases`
   （`signal_preview`/`signal_1450`/`entry_1455`/`exit_open`）+
   `next_scan_at` + `status` 驱动 done/active/next/pending。
   配 `lowSuctionFlow.spec.ts`。
2. **状态指挥条**：tone 派生函数（仿 `gateStatus()`）：
   - `blocked`（红，必须显示翻译后的 blocking_reasons —— Bug 1 的 UX 保险）
   - `awaiting_signal_window`（琥珀，等待扫描窗口）
   - `preview_ready`（主色，盘中预警已更新）
   - `signal_frozen`（涨色，尾盘信号已确认）
   - `paper_account_active`（涨色，纸面买入已记录）
   - `market_closed`/`not_run`（muted）
   右侧：候选/推荐计数 + 数据新鲜度（`generated_at` 相对时间 +
   `auto_refresh_seconds`）。
   blocking_reason 翻译表（frontend 所有，仿 `blockerLabel()`）：
   `future_or_outcome_columns_prohibited` → 输入校验未通过（防未来函数守护）、
   `d_minus_one_top3_missing` → 缺少 D-1 龙头榜、
   `signal_capture_not_ready` → 尾盘信号未就绪、
   `intraday_*_quotes_missing/stale` → 行情快照缺失/过期 等，未知码回退原文。
3. **纸面账户条**：`forward_performance`（权益/闭合交易/胜率/复利/回撤）
   + `qualification` 进度（x/300 笔 · 前向收集中），打板"近期质量"条等价物。
4. **信号表格**（保留）+ **持仓面板**（`positions` 非空时显示浮动盈亏）。
- 轮询：`refetchInterval` 改用 `session.auto_refresh_seconds`（秒→毫秒），
  回退 60s。
- D+2 影子行：`target_samples` 替代硬编码 20。

### P2：回测章节化 + 规则手风琴 + 死代码清理

- **回测分析**：提取打板 `PanelHead`（LimitUpPage.tsx 内部组件）为共享组件
  `features/shared/PanelHead.tsx`（或 components/），低吸回测映射 6 章：
  01 口径 SETUP / 02 两仓真实账户 ACCOUNT(accent) / 03 推荐质量标尺 QUALITY /
  04 分行情结果 REGIME / 05 稳健性检查 ROBUSTNESS / 06 逐笔交割 TRADES。
  现有面板内容不变。权益曲线图暂缓（需后端暴露两仓现金曲线，另立项）。
- **规则说明**：8 步横排卡片 → 左侧编号手风琴轨 + 右侧详情
  （算法条件/使用数据/不通过 amber 框，仿 `RuleFlowDiagram`）；
  顶部加诚实声明卡（历史证据为 exploratory_survivorship_proxy，
  正式资格以前向 300 笔为准）。人话文案归前端，后端契约不动。
- **清理**：删除 `LowSuctionForwardLedger.tsx`、`fetchLowSuctionForwardLedger`
  及死类型；`fetchLowSuctionSwingResearch` 改为只取
  `/low-suction/cross-regime-validation`（新 fetcher），删除未用类型；
  提取 `formatPct`/`formatRate`/`rateTone`/`phaseLabel`/`Metric`/`Definition`
  到 `features/lowSuction/format.tsx`，workspace 与 ledger 复用。

### P3：收尾

- 视图 tab 同步 URL：`?research=low-suction&view=live|backtest|rules`
  （ShortTermResearchPage 的 `research` 参数处理保持不变，view 参数由
  workspace 读写 searchParams）。
- 复权状态验证（只验证不重建）：确认 `stock_daily_bars` 入库复权口径与
  回测假设一致，结论写入 `memory/03_data/data_flow.md` 或
  `memory/06_backtests/`。

## 不做（YAGNI）

- 幸存者偏差历史时点成分库建设（`historical_point_in_time_membership_missing`
  blocker）——大数据工程，单独立项。
- 回测权益曲线图 —— 依赖后端暴露两仓现金曲线，另立小任务。
- 信号表格卡片化 —— 表格已够用，不模仿打板卡片。
- 低吸专属漏斗轨迹面板 —— `leader_pullback_opportunity_funnel_study`
  尚未接入 API，接入后再议。

## 测试与验收

- 后端：`pytest tests/alphaagent/services/low_suction/test_swing_strategy*.py`
  全绿 + 新增回归测试。
- 前端：`vitest` lowSuction 相关 spec 全绿 + 新增 `lowSuctionFlow.spec.ts`；
  PanelHead 提取后打板页既有 spec 全绿。
- 端到端：playwright 截图验证三视图；盘中时段确认 blocked 状态有翻译后的
  可见提示。
