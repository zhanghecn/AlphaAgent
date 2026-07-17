# AlphaAgent 低吸历史成员与题材资格工程验证

验证日期：2026-07-16\
工程状态：`engineering_complete_external_data_blocked`\
研究状态：`blocked_by_data_quality`\
正式策略指标：`null`

## Current State

Tushare DC 历史成员和题材资格研究框架已经实现并通过本地、容器和浏览器回归。
当前不能完成真实三年回补：环境没有 `TUSHARE_TOKEN`，官方 `dc_index/dc_member`
要求 6,000 积分。系统因此保持失败关闭，没有把当前东方财富成员复制成历史，也没有
生成题材阈值、低吸胜率或复利结论。

已实现：

- `BKxxxx.DC <-> BKxxxx` 精确映射和 Tushare 响应校验。
- 研究日 D 只使用上一完整交易日 S 的成员，按 D-1 交易日滞后规范化。
- `.SH/.SZ/.BJ` 精确交易所转换、连续交易日区间压缩和重现拆段。
- 独立历史成员表和完整性 scope 表，按 provider 原子替换。
- 5,000 行触顶自动拆分、单日触顶拒绝、重复/缺日期/错代码失败关闭。
- strict provider 与 `current_proxy` 独立统计，不混合覆盖分子或来源。
- 20 日成员动态特征、60/20/20 时间拆分、固定阈值网格和验证稳定性门禁。
- 30 个精确 ID 参考种子、名称模糊继承拒绝和全活跃目录完整性校验。
- 题材资格在 Top3 排名前过滤；冻结版本进入事件 ID。

## Runtime Evidence

| Check | Result |
| --- | --- |
| API health | HTTP 200, `status=ok` |
| Membership source | `unconfigured`, `configured=false`, `strict_ready=false` |
| Required provider points | 6,000 |
| Probe/dry-run writes | 0 |
| Historical membership rows | 0 |
| Historical membership scope rows | 0 |
| Audit blockers | `historical_concept_membership`, `historical_security_status`, `candidate_minute_paths` |
| Membership audit mode | `current_proxy` |
| Formal metrics | `null` |
| Theme research | `blocked_by_historical_membership`, `qualified=false`, `rule=null` |
| Active/seed-classified concepts | 498 / 30 |
| Remaining exact-ID classifications | 468 |

新历史表为空时，审计仍能读取三天东方财富当前快照并明确标为 `current_proxy`；它不会
被 strict provider 的分子、分母或来源列表吸收。`membership-backfill --dry-run` 在未配置
凭证时返回 `rows_written=0`，表行数保持为 0。

## Verification

```text
low-suction suite:       179 passed
backend non-browser:   1,057 passed
frontend unit tests:      71 passed
browser end-to-end:       27 passed
frontend production build: passed
scoped Ruff: passed
Python compileall: passed
git diff --check: passed
Docker API health: passed
```

浏览器回归现在按真实产品鉴权模型写入专用测试 token，并验证旧 `/explore`、`/chain`
都进入合并后的 `/mainline` 工作区；没有恢复已经废弃的页面。

## Reproduce

```bash
docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli membership-source-status

docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli membership-probe \
  --start 2026-07-09 --end 2026-07-15 --format json

docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli membership-backfill \
  --start 2023-03-28 --end 2026-07-15 --dry-run --format json

docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli audit --format json

docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli theme-eligibility-research \
  --start 2023-03-28 --end 2026-07-15 --format json
```

## Open Gates

1. 配置具备 6,000 积分的 Tushare token，执行五个哨兵日期探测和三日来源对照。
2. 只有探测通过才运行全窗 dry-run 和原子 write，并重新审计至少 720 个严格交易日、
   1,095 个自然日。
3. 用严格成员动态为剩余 468 个活跃 BK 代码建立逐个证据分类，再冻结题材阈值。
4. 继续取得严格历史证券状态，重建候选后定向补齐分钟路径。
5. 只有所有门禁通过且锁定留出至少 300 笔，才计算正式胜率、复利、利润因子和回撤。

在这些门禁完成前，当前唯一合法结论仍是 `blocked_by_data_quality`。
