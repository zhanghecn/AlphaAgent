# 方向②：低吸盘中提前扫描弱转强 — 分钟回填设计（2026-07-23）

## 研究目标

转强是过程不是瞬间。一只收盘 +9.8% 收复前高的股，盘中突破前高那一刻往往在
+5~7%（可成交、不在涨停）。用分钟线定位"盘中转强成型点"，在那里买——既拿到
确认 alpha，又避开收盘封涨停的成交死结。这是真正的"扫描出低吸点"。

## 前置：分钟数据现状

- 低吸转强信号宇宙（`select_gold_strong_reclaim_signals`）约 356 信号日 × ~100 股
  ≈ **35,600 个股票日**（2024-08..2026-07）。
- **当前低吸历史分钟线为空**：`sync_low_suction_forward_ma5_minutes` 只补前向账本
  `signal_eligible=true` 的股，而前向账本今天才修复、0 信号。需新建回填。
- 共享表 `stock_minute_bars`（PK=`vt_symbol,bar_time,interval`），所有策略共用，
  仅靠 `interval`(1m/5m) + `source`("tdx_public_hq") 区分，逻辑 scope 是返回串非列。

## 回填设计（复用现有 TDX 基建，镜像 `forward_ma5_minutes.py`）

新模块 `alphaagent/server/services/low_suction/reclaim_minutes.py`（~150 行）：

1. **宇宙源**：`build_dynamic_leader_paths → prepare_dynamic_leader_paths →
   select_gold_strong_reclaim_signals` 取 `(vt_symbol, signal_date)` 对
   （Explore 确认无持久化表，须重算；如需审计可另建 `low_suction_reclaim_candidates`
   表镜像 `low_suction_forward_ma5_candidates` 结构）。
2. **粒度选 5m**：5m × 48 根/日 ≈ **1.7M 根**；1m 要 8.5M 根太重。
   5m 足以定位"首次站回前高/MA5"的成型时刻。
3. **覆盖契约**：09:35–15:00 共 48 根 5m，复用
   `event_recognition_minutes.build_event_5m_manifest` 的 complete/incomplete/missing 校验。
4. **抓取**：`import_tdx_minute_bars_for_gaps(interval="5m", tail_entry_start="09:35",
   tail_entry_end="15:00", max_pages_per_symbol=81, timeout_seconds=3.0)`，category=0。
5. **调度**：先 **manual-only**（同 hazard/forward-MA5），稳定后再进 21:30 finalize 批次。
   `MAX_BACKFILL_GAPS=500`/批 ≈ 71 批，跨会话跑。
6. **data_sync.py 接线**：JobDefinition + JobCadence(EOD_DAILY) + runner 三处，~10 行。

**净工作量**：1 新模块 + 10 行接线，无 schema 改动。打板侧已有同款基建实测可用。

## 成型后研究方向（分钟线到位后）

- 定义"盘中转强成型点"候选（预登记，防过拟合）：
  ①首次 5m 收盘 > 可见前高；②首次 5m 收盘站回 MA5；③突破早盘最高点。
- 入场价 = 成型那一刻的 5m 收盘（盘中、非涨停、可成交）。
- 对照：盘中成型点入场 vs 收盘入场，收益差 + 成交可行性（成型时是否已涨停）。
- 开发段(block1-3)发现规则 → 验证段(block4-5)确认 → 前向账本裁决，绝不直接上线。

## 与方向①的关系

- 方向①（放宽阈值）是日线快速验证：能否直接把非涨停可成交池撑大。
- 方向②（盘中扫描）是分钟线主力：解决"确认日收盘封涨停"的根本矛盾。
- 两者正交：①可能让②的宇宙更大（更多非涨停信号可提前扫到成型点）。
