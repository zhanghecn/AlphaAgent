# Low-suction Forward Tradable Scope Evidence - 2026-07-16

## Conclusion

低吸前向概念成员已从“完整官方目录任一失败就永远为 0”改为可审计双 scope，且完成
首个真实源交易日捕获。同日 21:33 重试后结果保持不变，当前 scope 的观察时间为
`2026-07-16 21:33:52+08:00`：

- 共享完整目录作业仍失败，只失败 `BK1677/BK1678/BK1679`；打板和共享目录语义不变。
- `concept_catalog` 为 `498/495`、`complete=false`，没有把不完整目录称为成功。
- `concept_tradable` 为 `478/478`、`complete=true`，保存 67,403 行、5,608 只股票。
- 前向成员从 0 日变为 `accumulating=1` 个 source day；正式绩效仍为 `null`。

这不是低吸交易胜率，也不是三年历史。单一来源达到 720 个有效交易日和 1,095 个自然
日前，Top3 身份、分钟状态和锁定留出仍保持阻断。

## Scope Contract

- 官方全目录继续由共享 `sync_sector_members` 管理，任何板块失败仍让作业失败并阻断
  `sync_stock_sector_memberships`；没有放宽打板或共享快照完整性。
- 低吸专用表只接收本次运行中非空、去重、源端 `total` 闭合的完整分页，不读取数据库
  中上次成功的旧板块成员补洞。
- 排除只按 exact sector ID、manifest class 和 manifest version；板块名称不参与判断。
- 仅 `mechanical_event/style_universe/report_event/ambiguous` 可排除；`narrative_theme` 和
  `unlabeled` 都留在抓取分母，任一失败都会关闭 `concept_tradable`。
- 部分重试只更新非严格 `concept_catalog` 观察，不删除或降级既有严格交易 scope。
- 严格记录与双 scope 使用低吸专用表，避免共享快照中的排除板块混入聚合。

## Real Capture Audit

| Item | Value |
| --- | ---: |
| Source date | `2026-07-16` |
| Observed at | `2026-07-16 21:33:52.967922+08:00` |
| Source | `eastmoney.push2.board.forward` |
| Manifest | `low-suction-theme-manifest-seed-v1` |
| Catalog expected / returned | `498 / 495` |
| Tradable expected / returned | `478 / 478` |
| Tradable rows / symbols | `67,403 / 5,608` |
| Tradable sectors | `478` |
| Excluded rows leaked into strict table | `0` |

20 个 exact-ID 排除为：10 个 `mechanical_event`、4 个 `style_universe`、6 个
`report_event`。本次三个失败 ID 全部是 manifest 中的 `report_event`。严格记录仍包含
10 个已标 `narrative_theme` 板块的 3,342 行，以及 468 个 `unlabeled` 板块的 64,061
行；未分类板块没有因为抓取困难被自动排除。

21:13 首次捕获与 21:33 同日重试的目录数、交易 scope、行数和股票数完全一致；重试
仍只失败同三个 report IDs，并按同一源日原子替换，没有累加重复行。

修正版容器的 `v2-audit` 读取结果为：前向成员 `1日/67,403行`、前向证券
`1日/3,192行`；历史 strict 成员和证券仍均为 0 日，Top3 `selected_mode=null`，候选
分钟对为 0，`formal_metrics=null`，锁定留出访问次数为 0。

## Verification

```bash
uv run --group server pytest \
  tests/alphaagent/services/low_suction \
  tests/alphaagent/test_data_sync_schedule.py \
  tests/alphaagent/test_market_snapshot_repository.py -q
# 385 passed, 1 unrelated Starlette deprecation warning

uvx ruff check \
  alphaagent/server/services/low_suction/forward_membership.py \
  alphaagent/server/services/low_suction/forward_membership_repository.py \
  alphaagent/server/services/low_suction/data_quality_repository.py \
  alphaagent/server/services/low_suction/v2_audit.py \
  tests/alphaagent/services/low_suction/test_forward_membership.py \
  tests/alphaagent/services/low_suction/test_forward_membership_repository.py \
  tests/alphaagent/services/low_suction/test_data_quality.py \
  tests/alphaagent/services/low_suction/test_v2_audit.py
# All checks passed

uv run python -m compileall -q \
  alphaagent/server/services/low_suction \
  alphaagent/server/services/data_sync.py \
  alphaagent/server/db/schema.py

git diff --check
```

## Next Gate

下一步不是在 1 日样本上调买点，而是让相同合同自然累计，并为每个有效日生成严格的
点时 Top3 身份输入。只有成员和证券状态都达到协议历史门，才从全部 Top3 分钟状态中
发现最多两条件的入场转移；当前不得输出胜率或复利规律。
