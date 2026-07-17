# AlphaAgent 低吸历史概念成员来源研究

研究日期：2026-07-16\
结论：`candidate_source_found_not_configured`\
正式指标：`null`

## Decision

Tushare Pro 的 `dc_member` 是当前第一个同时满足“东方财富同一 BK 代码体系”和
“可按交易日查询历史成分”的明确候选来源。它不能立即解除门禁：本地没有
`TUSHARE_TOKEN`，官方接口要求 6,000 积分，三年实际起点、返回完整性、修订行为和
D-1 盘后数据在下一交易日开盘前的可用性都还没有经过真实调用验证。

在完成小范围探测前：

- 不回填当前东方财富成员到历史。
- 不把 `dc_member` 标为 `strict`。
- 不生成新的全窗 Top3 候选。
- 不下载候选分钟线，也不发布胜率、复利或最优规则。

## Official Source Matrix

| Source | Historical date | Same index family | Current decision |
| --- | --- | --- | --- |
| Eastmoney `push2` current board members | 未发现经验证的历史日期接口 | `BKxxxx` | 仅 `membership_proxy` |
| Tushare `ths_member` | 官方明确“不能查历史成分” | `885xxx.TI` | 拒绝 |
| Tushare `dc_member` | 官方明确支持按代码和交易日取历史成分 | `BKxxxx.DC` | 候选，待 token 实测 |
| Tushare `tdx_member` | 支持按交易日 | `880xxx.TDX` | 不与现有东方财富指数混用 |
| JQData concept members | 可按日期查询 | 聚宽 `GN...` | 目录和删除概念无法与 BK 严格对齐 |
| Tushare `dc_concept_cons` | 从 2026-02-03 开始 | 题材事件数据 | 只能作近端辅助，不能满足三年 |

官方文档：

- `dc_index`: https://tushare.pro/document/2?doc_id=362
- `dc_member`: https://tushare.pro/document/2?doc_id=363
- `dc_daily`: https://tushare.pro/document/2?doc_id=382
- `ths_member`: https://tushare.pro/document/2?doc_id=261
- `tdx_member`: https://tushare.pro/document/2?doc_id=377
- `dc_concept_cons`: https://tushare.pro/document/2?doc_id=422

## Exact Code Mapping

官方示例与本地 PostgreSQL 精确对应：

| Tushare DC | Local sector | Name | Local canonical bars |
| --- | --- | --- | ---: |
| `BK0490.DC` | `BK0490` | 军工 | 800 |
| `BK1184.DC` | `BK1184` | 人形机器人 | 393 |
| `BK1185.DC` | `BK1185` | 冰雪经济 | 383 |
| `BK1186.DC` | `BK1186` | 首发经济 | 383 |

映射规则只能是严格移除 `.DC` 后缀。名称只用于冲突审计，不能用于模糊匹配、自动合并
或猜测改名板块。`dc_index` 的 `idx_type` 只允许“概念板块”；行业和地域不进入低吸
概念宇宙。

## Point-in-time Rule

研究交易日 D 的开盘前候选，只允许使用来源交易日 S 的成员，其中 S 是 D 前一个已完成
交易日。即使供应商把 S 日成员视为盘后数据，也不会解释 S 日盘中：

```text
source_trade_date = previous_complete_session(D)
effective_trade_date = D
feature_cutoff <= D 09:25 Asia/Shanghai
```

完整性必须按 `(effective_trade_date, sector_id)` 保存独立 scope。长区间查询若返回
5,000 行上限必须二分日期窗口；只有每个预期日期/板块都有响应、成员代码无重复、
响应未触顶并且精确 BK 映射无冲突，才允许原子写入。

## Three-day Taxonomy Check

现有 `2026-07-13..2026-07-15` 三个快照覆盖 498 个概念。连续两日成员集合的平均
Jaccard 结果证明事件板块会快速重构：

| Board | Mean Jaccard |
| --- | ---: |
| 昨日首板 | 0.0000 |
| 昨日打二板以上表现 | 0.0000 |
| 昨日触板 | 0.0119 |
| 昨日炸板 | 0.0147 |
| 昨日连板 | 0.0690 |
| 昨日涨停 | 0.0700 |
| 昨日涨停_含一字 | 0.0798 |

但高稳定性也不能直接代表真实题材：金融地产风格、大盘股、权重股和若干财报板块在
同一窗口的 Jaccard 都是 `1.0000`。因此合格题材不能只靠名称，也不能只靠成员稳定性；
必须同时使用官方 `idx_type`、机械事件/风格定义、成员动态和时间外验证。

三天数据只证明特征方向，不足以选择阈值。阈值必须在三年历史成员到位后，用前 60%
训练段选择，并在后续 20% 验证段和最后 20% 锁定留出段检验。无法同时压低事件/风格
误放行并保留真实题材时，结论应为 `no_qualified_taxonomy`。

## Next Gate

先执行 `requirements/alphaagent_low_suction_dc_membership_implementation_plan.md` 的
只读探测。只有真实 token 返回满足以下条件，才进入回补：

1. 能覆盖 `2023-03-27..2026-07-14` 所需来源日期。
2. `BKxxxx.DC -> BKxxxx` 无碰撞，且动态活跃概念精确映射率不低于 99%。
3. 响应窗口无 5,000 行截断，所有日期/板块 scope 完整。
4. 与三天现有东方财富快照的同日成员差异有明确解释。
5. D-1 滞后后至少覆盖 720 个交易日和 1,095 个自然日。

题材资格随后按
`requirements/alphaagent_low_suction_theme_eligibility_research_plan.md` 独立验证。
