# Overfit Validation Baseline (CPCV / PBO / Deflated Sharpe)

## Current state

首次实际运行 `overfit_validation.py`（CPCV/PBO/DSR，之前只有单测、从未被调用）验证主线
`mainline_dragon_pullback / 0.1.21` 是否过拟合，并对比"放宽门控"是否值得。

- 范围：`2025-03-26 .. 2026-06-18`，299 交易日，`max_symbols=5000`（全市场，必须保持，子集会破坏策略）。
- 配置：`n_groups=3, n_test_groups=1`（OOS 窗口 ~99 天 ≥ run_backtest 的 80 天 ready 阈值），variant=core（baseline vs loose）。
- 耗时：~62 分钟（12 次回测，每次 ~168s；瓶颈在 `_load_all_bars` 数据加载，`reuse_signal_cache=True` 无加速）。

## 结果

| 指标 | 值 | 解读 |
| --- | --- | --- |
| PBO | `1.0` | IS 最优 variant 在 OOS 全部排最差（3/3 路径一致） |
| Deflated Sharpe | `0.958` | 接近 0.95，多重检验后**勉强显著**（策略有真实 alpha，但边际） |
| OOS 年化 Sharpe 均值 | `2.11` | 接近全样本 baseline #194 的 2.38，策略在 OOS 正常工作 |

每条路径 IS 最优都是 `loose`（`strict_entry=False`，放宽买更多形态信号点），但 OOS 全部输给 `baseline`（`strict_entry=True`）：

| 路径 | IS 最优 | IS Sharpe | 该变体 OOS Sharpe | OOS 排名 |
| --- | --- | ---: | ---: | --- |
| 0 | loose | 2.99 | 1.258 | 0/1（输 baseline） |
| 1 | loose | 2.71 | 3.049 | 0/1（输 baseline） |
| 2 | loose | 2.66 | 2.034 | 0/1（输 baseline） |

## 结论

1. **策略本身有效**：OOS Sharpe 2.11、DSR 0.958 接近显著，主线 0.1.21 不是纯噪声，有真实 alpha。
2. **放宽门控（loose）过拟合**：样本内最优，样本外输给严格入场。这是**第二次**数据证明"放宽门控不值"（第一次是 memory `2026-06-19_candidate_marker...md` 的 #198，放宽让收益 +83%→+34%）。
3. **主人"想买更多点"的直觉不成立**：东山6-12/金安1-14 这类 `entry_signal=true` 但 `executable_entry_signal=false` 的点，策略**故意不买**是对的——`executable_entry_signal`（要求 `low_suction_launch_confirmed`）是抗过拟合的正确设计，不应放宽。

## How to verify / reproduce

```bash
# overfit_validation 纯函数无回归
uv run pytest tests/alphaagent/test_overfit_validation.py -q   # 17 passed

# 在 api 容器跑诊断（容器有 DATABASE_URL + alphaagent 环境；overfit_validation.py 是 untracked 新文件，需 cp 进容器）
docker cp alphaagent/server/services/backtest/overfit_validation.py vnpy-alphaagent-api-1:/app/alphaagent/server/services/backtest/overfit_validation.py
docker cp scripts/diagnose_overfit.py vnpy-alphaagent-api-1:/app/scripts/diagnose_overfit.py
docker exec vnpy-alphaagent-api-1 python scripts/diagnose_overfit.py --dry-run          # 验证数据/变体
docker exec vnpy-alphaagent-api-1 python scripts/diagnose_overfit.py --n-groups 3 --n-test-groups 1   # ~62 分钟
# 结果落盘容器内 /tmp/overfit_result.json
```

诊断脚本：`scripts/diagnose_overfit.py`（一次性，不入正式包；支持 `--max-symbols` / `--variants core|all` / `--n-groups`）。

## Open risks / next work

- **样本少**：3 条 CPCV 路径，PBO 统计弱。但 3 路径一致（loose IS 最优→OOS 输 baseline）是强信号。可加大 `n_groups=4, n_test_groups=2`（6 路径，~2.8h）复核。
- **未测 `strict_launch`（收紧方向）**：本次只比 baseline vs loose。收紧（`require_low_suction_launch_confirmation=True`）样本外是否更稳，待 `--variants all` 验证。
- **DSR 0.958 边际**：刚过 0.95，不够稳健。结合胜率 32%，说明策略 alpha 真实但波动大，杠杆点在**卖出/止损端**（baseline #194 审计：`support_stop` 125 笔亏 -88 万），不在买入端。
- **第二阶段方向**：基于"放宽不值"的结论，不应放宽门控；应优化卖出/止损（治胜率 32% 本）+ 展示增强（让主人理解策略边界）。
- **踩坑记录**：`max_symbols` 缩小到 400 会破坏策略（IS Sharpe 变负 -0.30），过拟合验证必须保持全市场 5000。
