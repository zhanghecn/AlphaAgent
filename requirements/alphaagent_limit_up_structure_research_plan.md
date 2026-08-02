# 潜龙首板结构因子研究计划（案例核查 + 均线结构 + 量能梯形 + 盘前命中率）

> 主人原始笔记：`requirements/潜龙首板优化.md`（不改写）。本文件是研究执行计划。

## Context（为什么做）

主人对 2026 年 6-7 月 14 个 ≥2 连板首板案例做了人工复盘，提出两类首板前奏结构，
并要求**逐条核查**（「你来核查一下我说的对不对，以及有没有其他的发现」）：

- **低位收拢型**（情形最多）：MA10<MA20<MA30 空头排列约一个月 → MA10 极速收拢/
  金叉 MA20（或三线粘合近横盘）→ 企稳站上 MA10 → 首板。爱丽家居变体：刻意跌破
  但量能梯形规则。
- **波浪型**：MA10>MA20>MA30（与低位型相反），回调至摆动低点企稳 → 首板。
  行情好→波浪型多；行情差→低位型多（regime 切换假说）。
- **量能规律（主力控盘）**：放量梯形 / 萎缩梯形 / 平稳后突变；控盘小阳（涨幅~1% 贴 MA5）。
- **执行层（D 日，非 D-1）**：竞价涨幅 + 早盘 1/2/3/5 分钟涨幅确认（分钟数据本期不做，
  主人明确「不要受限于分钟数据，否则数据太少很容易过拟合」）。

主人的验收口径（来自笔记开头段）：

1. 输出「出现首板涨停的几率」与「每个交易日大概有多少只过过滤的股票」；
2. 覆盖率核对：每个交易日把 ≥2 连板票（**特别注意 >3 板的妖股**）拿出来，核对
   模型过滤在**首板日前一天**能否找到它们，算覆盖占比；漏掉的（尤其妖股）查明拒因；
3. 尽可能减少候选股票，同时候选质量足够高（大部分 ≥2 板票在候选里）；
4. MA20 门可以代入，只要无未来函数、不过拟合（主人反对「完全按 7 月调的门」）。

现有模型的痛点（主人原话）：白名单因子偏好「越高越好（热点板块）」，选出来的是
回踩反弹不是潜龙；观察池「低位」是价格口径（回撤≥25%），与主人的均线结构口径不符。

## 可复用资产（已逐条核实）

- 样本管线：`build_factor_samples(min_consecutive_boards=2, board_gap_mode="wave")`
  （deep:796）→ 11223 首板 / 2462 正样本（≥2 板，基线 21.94%）/ 968 妖股（≥3 板）；
  负样本 = 1 板夭折首板。`extract_first_board_samples`（consecutive:38）给出全量首板
  日集合（frame 2 打标用，含 eventual_peak）。
- 复用因子函数：`_daily_position_volume_features`（minute_backtest:358，直接给
  position_20d/bias_ma5_pct/bias_ma20_pct/turnover_1d_vs_20d 四键）、
  `_long_window_features`（deep:162，position_126d 等）、`_mid_window_features`
  （deep:101）、`_is_first_board_candidate`（minute_backtest:181）。
- 统计工具：`compare_numeric_factor`（consecutive:500）、`compare_categorical_factor`
  （consecutive:535）、`_categorical_outcomes`（deep:680）、`monthly_factor_stability`
  （stability:201，门槛 0.7）、`collinearity_matrix`/`_spearman_pairs`（stability:373/358）、
  `_month_of`（stability:184）。
- 数据：`load_limit_up_dataset` / `load_daily_bars_all`（含 open_price，竞价涨幅 =
  open/前收，**无需分钟数据**）/ `load_stock_names` / `load_sector_*`；窗口惯例
  2025-06-27..2026-07-31，日线 start-320 / end+15。指数行在 stock_daily_bars 内，
  `is_eligible_main_board`（services/a_share_universe.py:6）前缀规则已天然排除。
- 结构模板：`leader_first_board_prelude_pattern_research.py`（820 行，逐块镜像）。

## 新增因子（全部 D-1 收盘可观测，纯日线；`_structure_features` 共享纯函数）

**均线结构族**（MA5/10/20/30 主人指定，窗口固定不参数化；历史不足一律 None 不 False）：
`ma_bear_align`/`ma_bear_days`（空头排列连续天数，cap 30，59 根才满口径→
`ma_history_bars` 诊断键记删失）、`ma_bull_align`/`ma_bull_days`、
`ma_spread_10_20_pct`/`ma_spread_20_30_pct`（带号价差）、
`ma_converge_10_20_5d`（|spread(D-6)|−|spread(D-1)|，正=收拢）、
`ma10_slope_5d_pct`（MA10 方向，区分「MA10 上靠」vs「MA20 下压」）、
`ma10_cross20_up_5d`（5 日内金叉）、`ma_tightness_pct`（三线最大最小间距/收盘）、
`close_above_ma10`、`above_ma10_streak`（连续站稳 MA10 天数）、
`ma10_cross_count_20d`（MA10 缠绕次数，高争民爆/均瑶健康型）、
`ma_state`（bull/bear_converging/bear_diverging/tangled 四分类）。

**量能梯形族**（turnover 口径与既有因子一致；窗内必须全有效否则 None）：
`vol_spearman_5d`/`vol_spearman_10d`（量与日序 Spearman，+1=放量梯形/−1=萎缩梯形）、
`vol_up_streak`/`vol_down_streak`（严格递增/递减，cap 5）。

**控盘小阳/波浪/探索**：`small_gain_days_5d`（0<涨幅≤1.5% 天数，敏感性 1.0/2.0）、
`days_since_20d_low`（摆动低点距今，镜像 days_since_126d_low）、
`d1_shadow_balance`（上下影线匀称度，高争民爆单案例→标探索）。

**复用 4 键**：`position_20d`/`bias_ma5_pct`/`bias_ma20_pct`/`turnover_1d_vs_20d`
（import `_daily_position_volume_features`，测试锁口径）。

**D 日执行证据（明确标注非 D-1 因子）**：`auction_gap_pct` = open(D)/close(D-1)−1。
**regime 标签**：`index_above_ma20`（000001.SSE 收盘 vs MA20，研究口径严格——
不足 20 根返回 None，不用生产的 fail-open 版本）。

## 报告分析块

0. **模型说明**：因子族 + 预登记组合 + 验收口径（主人「先把模型说一遍」）。
1. **案例核查（第一优先，主人「核查我说的对不对」）**：14 锚点案例
   （哈药股份 7-10 / 立新能源 7-16 / 爱丽家居 7-21 / 传智教育 7-27 / 一鸣食品 7-28 /
   高争民爆 7-29 / 均瑶健康 7-29 / 华天酒店 7-27 / 顺钠股份 7-23 / 新亚制程 7-24 /
   大有能源 6-01 / 中重科技 6-03 / 金钼股份 6-11 / 诺德股份 6-15），
   按名字解析代码（load_stock_names 反查）→ 校验首板日完整性（bar 涨幅 +
   是否在首板集合 + eventual_peak）→ 逐条主人描述给数据裁决（符合/不符合/数据不足 +
   数值证据；引用区间用主人原话日期窗，如传智 7-15..7-24 缩量梯形用区间 spearman）。
2. **形态命中率**：P(形态|≥2板) vs P(形态|1板夭折) vs **P(形态|≥3板妖股)**。
3. **数值区分度**：compare_numeric_factor（AUC + 日期块 bootstrap CI + 五分位）。
4. **市况分型**：index_above_ma20 × 形态族命中率/组合妖股率；regime×月份计数表 +
   「单次崩盘 episode，只能给描述性结论」硬警示（主人的 regime 切换假说）。
5. **月度一致性 + 2026-06 vs 07 方向翻转**（MA20 教训）。
6. **预登记组合 vs 基线 21.94%**（含妖股率列）+ **漏网归因**（被组合卡掉的 ≥2 板票
   按子条件统计拒因；漏网妖股清单 top50）。
7. **盘前全市场框架（frame 2）**：全市场主板股票日扫描（is_eligible_main_board +
   历史≥130 根 + D-1 未涨停 + 尾部 5 日除外），同一组组合谓词：
   每组合给 候选股票日数 / **平均每交易日候选数** / 5 日内首板命中率 / lift /
   命中后≥2板率 / ≥3板命中数。**过滤 vs 排序裁决带（预声明）**：
   lift≥3 且候选日≥100 → 过滤级；1.5-3 → 排序级；<1.5 → 淘汰。
8. **竞价缺口**：成功 vs 失败首板的 auction_gap_pct 区分度（D 日证据，只能说明
   「已首板后谁延续」，不能预测「是否首板」——后者归 frame 2）。
9. **敏感性**（预声明，不网格）：converge_lag 3/5/8、spearman cut 0.6/0.7/0.8、
   紧凑度 2/3/5%、小阳上限 1.0/1.5/2.0。
10. **共线性**：新键 vs return_20d_pct/position_126d/drawdown/rebound/volume_ratio_5_60/
    turnover_ratio_3d_vs_prev7d/prelude_vol_cv_7d（|rho|≥0.7 标族）。

## 预登记组合（7 个，先验设定非事后搜索；低位统一 position_126d≤0.25）

| 组合 | 定义 |
|---|---|
| `lowpos_converge` | 低位 + ma_bear_days≥15 + (ma_converge_10_20_5d>0 或 ma10_cross20_up_5d) + close_above_ma10 |
| `lowpos_converge_strict` | 同上 + above_ma10_streak≥2 + ma10_slope_5d_pct>0（站稳+MA10 上靠） |
| `lowpos_tight` | 低位 + ma_tightness_pct≤3.0 + ma_bear_days≥10 + close_above_ma10（三线粘合） |
| `trap_up_lowpos` | 低位 + vol_spearman_5d≥0.7（放量梯形） |
| `trap_down_lowpos` | 低位 + vol_spearman_5d≤−0.7（萎缩梯形） |
| `wave_bull_pullback` | ma_bull_align + position_20d≤0.35 + days_since_20d_low≤3（波浪回调企稳） |
| `converge_trap_up` | lowpos_converge + vol_spearman_5d≥0.7（主力控盘签名） |

## 纪律（沿用 MA20 教训）

- 只读研究：不碰实时表/API/持仓；is_leader/eventual_peak/d1_* 是未来标签仅作对照。
- 月度一致率 <0.7 或 6/7 月翻转 → 无论全样本 AUC 多高都标「证据不足」。
- 阈值全部预声明标 in-sample；组合预登记，不做事后搜索。
- regime 只有 2026-07 一次崩盘 episode → 只给描述性结论。
- frame 2 候选股票日自相关（MA 条件连日成立）→ v1 只报计数+lift，不做 CI。
- 小样本（组合 <30）如实报 n 并标证据不足。

## 文件清单

- 新建 `alphaagent/server/services/limit_up/leader_first_board_structure_research.py`（只读）
- 新建 `tests/alphaagent/test_limit_up_structure_research.py`
- 产物 `memory/06_backtests/limit_up_leader_first_board_structure_20260802.{json,md}`
- 本计划归档（requirements/alphaagent_limit_up_structure_research_plan.md）

后续阶段（本期不做）：数据裁决后改造潜龙观察池条件；扫板→打板回测改造；
分钟回填后接入竞价/1/2/3/5 分钟涨幅确认层与实时榜排序。

## 验证

```bash
uv run pytest tests/alphaagent/test_limit_up_structure_research.py -v
docker compose --profile research run --rm --no-deps -v "$PWD:/app" alphaagent-research \
  python -m alphaagent.server.services.limit_up.leader_first_board_structure_research \
  --start 2025-06-27 --end 2026-07-31 \
  --json-output memory/06_backtests/limit_up_leader_first_board_structure_20260802.json \
  --markdown-output memory/06_backtests/limit_up_leader_first_board_structure_20260802.md
# 对账：11223 首板 / 2462 ≥2板（21.94%）/ 968 ≥3板
# 全量回归：uv run pytest tests/alphaagent -k "limit_up" 
```
