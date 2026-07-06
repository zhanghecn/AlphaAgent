# Backtest Archive Index

旧实验报告已从工作区移除。这个文件只记录清理规则，不再维护 100+ 份过程日志清单。

## What Was Removed

已移除的主要是过程性报告：

- `2026-06-11..2026-06-14`: 早期分钟线、严格尾盘、回测引擎审计。
- `2026-06-16..2026-06-25`: 日线 D+1、龙回头基线、低吸/失败启动/买点路径/过拟合诊断。
- `2026-07-02..2026-07-03`: Top20 rerank、meta-feature、pairwise、entry-quality、bottom-reclaim 等实验过程。
- `2026-07-04..2026-07-06`: 金/银手指、压力窗口、warming 拒绝、pressure right-tail 等过程性报告。

保留在顶层的只有当前入口和新收益口径交接。

## Current Entrypoints

- `README.md`
- `strategy_optimization_ledger.md`
- `2026-07-06_tail_buy_next_day_rewrite_handoff.md`

## Cleanup Rule

- 后续不要再为每次试验写长报告。
- 失败方案写入 `strategy_optimization_ledger.md` 的 rejected 段。
- 只有生产合入、收益口径变更、不可逆决策才新增独立 markdown。
- raw/cache 只放 `cache/`，可再生成的 `*_rows_*.pkl` 不长期保留。
