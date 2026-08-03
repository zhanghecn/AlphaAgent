# 潜龙首板融合计分卡研究计划（低位分 + 波浪分 → Top-N 榜 + 最低分底线）

> 主人原始规则：`requirements/潜龙首板优化.md` 与 `首板研究.txt`（不改写）。
> 前一轮研究（`alphaagent_limit_up_structure_research_plan.md`）用「拆条 + 硬门槛」
> 测法裁决 R1-R7 全部淘汰；主人指出其规则是**融合打分**（剂量响应 + 阶段递进 +
> 加分项），不是独立门槛的 AND。本计划按主人原话把规则翻译成计分卡重测。

## Context（为什么做）

主人 2026-08-03 的融合规则描述（逐字要点）：

- 通用因子分**低位型**与**波浪型**两个，「通用是融合规则，而不是拆开规则一个个看」。
- 低位型：MA10<MA20<MA30 拉开距离**很长**、持续**也久**（约 1 个月+）→ 突然收敛，
  **收敛时间越长**越易首板 → MA10 上穿 MA20 概率更高 → MA20 再上穿 MA30 概率继续
  提高 → 期间**未出现过涨停** → 量能符合梯形规律是**加分项**。
- 按分数排序筛**前 N 个**，同时要排查**最低分底线**。
- 波浪型同理（多头形式相反 + 回调企稳）。

主人已裁决的两个设计岔路（2026-08-03 AskUserQuestion）：

1. **子分权重 = 等权**：每项 0-1 爬坡、封顶值预声明、不调参。
2. **「期间未出现涨停」= 加分项**（+1 分），不是硬门槛。

**v2 修正（2026-08-03 同日，主人 首板研究.txt:183 澄清 + v1 数据反证）**：

1. **L7 反向**：原文 183 行「期间未出现涨停 是扣分项」——v1 实现为纯度加分，方向与
   数据相反（v1 证据：`L7_purity` AUC 0.4737 lower、`L7_pure` 对照 lift 0.7741；
   主人的扣分口径与数据一致）。v2 改为「近 20 日有 zt/zbgc 触碰 +1 / 无触碰 0」
   （扣分项的等价平移，保 0-7 标度）。
2. **横盘波浪并入波浪门**（原文 :103「波浪要么是横盘波浪，要么是行情好的向上波浪」）：
   资格门 = 多头排列 ∨（ma_state=tangled 且 position_20d≤0.35 且 days_since_20d_low≤3，
   爱丽型）。v1 只认向上波浪。
3. STUDY_VERSION bump v2，产物 `limit_up_leader_first_board_fused_score_v2_20260803.{json,md}`，
   v1 证据保留不覆盖。

## 计分卡公式（全部 D-1 收盘可观测；阈值全部预声明 in-sample）

### 旅程特征（新算，`_journey_features` 纯函数）

| 键 | 定义 | 历史要求 |
|---|---|---|
| `bear_run_max_40d` | 过去 40 个交易日内最长连续 MA10<MA20<MA30 天数 | ≥69 根 |
| `bear_depth_peak_pct` | 窗口内空头日 max[(MA20−MA10)+(MA30−MA20)]/close×100 | 同上 |
| `spread_peak_abs_pct` | 窗口内 max \|(MA10−MA20)/close×100\| | 同上 |
| `conv_days` | 当前 \|spread\| ≤ 50%×峰值时，自峰值日到 D-1 的天数；未收窄一半 = 0 | 同上 |
| `cross_stage` | 0=MA10<MA20；1=MA10≥MA20 且 MA20<MA30；2=MA20 也≥MA30 | ≥30 根 |
| `pure_20d` | D-1 及前 19 根（共 20 根）无 zt/zbgc 触碰（炸板也算破纯度） | ≥20 根 + 触碰事件 |

纯度事件的**删失处理**：触碰事件从 start−45 自然日额外加载（覆盖 20 市场日回溯），
不用样本窗口内事件，避免窗口左缘虚假「纯净」。

### 低位分（0-7，等权）

**资格门（硬）**：`bear_run_max_40d ≥ 15`（主人的「约 1 个月及以上」；敏感性 10/20）。

| 子分 | 爬坡 | 主人原话 |
|---|---|---|
| L1 基底深度 | min(depth/8%, 1) | 拉开距离很长 |
| L2 基底时长 | min(run/30, 1) | 持续也久约 1 个月+ |
| L3 收敛时长 | min(conv_days/15, 1) | 收敛时间越长越易首板 |
| L4 穿越阶段 | stage/2（0/0.5/1） | 上穿 MA20 概率更高→再上穿 MA30 继续提高 |
| L5 企稳 | min(above_ma10_streak/5, 1) | 企稳站上 10 日线 |
| L6 量能加分 | \|vol_spearman_5d\|≥0.7→1；≥0.5→0.5；否则 0 | 符合梯形规律是加分项 |
| L7 纯度加分 | pure_20d=True→1 | 期间未出现过涨停（主人裁定加分项） |

子分输入为 None（历史不足）→ 该子分 0 分；`bear_run_max_40d` 为 None → 不合格。

### 波浪分（0-4，等权）

**资格门（硬）**：当前多头排列 MA10>MA20>MA30。**不加纯度门**——主人的波浪案例
（金钼 5-26 曾首板）本就带前次脉冲，波浪是「脉冲→回调→再启动」。

| 子分 | 爬坡 | 主人原话 |
|---|---|---|
| W1 多头时长 | min(ma_bull_days/20, 1) | 均线形式与低位相反 |
| W2 回调深度 | clamp((0.8−position_20d)/0.8, 0, 1) | 回落到摆动低点 |
| W3 企稳 | max(0, 1−days_since_20d_low/3) | 直到开始起稳 |
| W4 量能加分 | 同 L6 | 同低位 |

### 统一榜

`fused_score = max(低位分/7, 波浪分/4)`（归一 0-1），`fused_type` ∈
lowpos/wave/both/None；两资格门都不过 = 0 分不入榜。Top-N 同分按代码升序（确定性）。

## 验证输出（预声明，不再模糊）

1. **Frame-1 区分度**（11223 首板样本）：`fused_score` 的 AUC（≥2板 vs 夭折，全样本
   + 仅合格子集）+ 五分位 ≥2板率；对照：各子分单用 AUC + `bias_ma20_pct`。
2. **Frame-1 分数桶结局**：0 / 0-0.2 / … / 0.8-1.0 六桶 × ≥2板率/≥3板率；
   类型结局（lowpos/wave/both/none 四组）。
3. **漏网妖股**：score=0 的 ≥3 板票清单 top50 + 归因。
4. **Frame-2 分数桶**（全市场主板股票日 ~100 万）：六桶 × 5 日内首板率 + lift +
   ≥2板/≥3板 tallies；桶间单调性 spearman（合并榜 + 分类型各一张）。
5. **Top-N 榜**：每日按分数取前 5/10/20/50，报平均每日命中首板数、
   ≥2板/≥3板召回率。
6. **最低分底线**（主人点名）：细阈值 0.05 步长扫描，报 lift 首次跨过
   1.0/1.5/2.0/3.0 的最低分。
7. **月度一致性**：顶桶（≥0.6）逐月 lift 方向一致率 + 2026-06/07 翻转检查。
8. **Regime 拆分**：上证 MA20 上/下 × 分数桶（单 episode 描述性）。
9. **敏感性（预声明不网格）**：空头门 10/15/20、纯度窗 10/20/30、收敛封顶
   10/15/20 —— 每变体只报顶桶 lift + 单调性。
10. **对照组裁决**：融合分必须同时打败 ①最强子分单用 ②bias_ma20≥5%（momentum_ref，
    前一轮唯一过滤级条件），否则「融合」只是包装。

## 及格线（预声明）

融合成立 ⇔ 全部满足：

- Frame-2 六桶（含 0 桶）首板率单调性 spearman ≥ 0.8；
- 顶桶（0.8-1.0）lift ≥ 2 且候选日 ≥ 100；
- 顶桶 ≥2板召回 > 最强子分单用的召回；
- 月度一致率 ≥ 0.7 且 2026-06/07 顶桶方向不翻转。

达标 → 进排序级 + 改造盘前观察池候选；不达标 → 如实写「融合未能拯救分项」，
低位/波浪形态降级为主人手工清单 + 观察徽章（不硬筛）。

## 纪律（沿用）

- 只读研究；`hit_peak`/`eventual_peak`/`is_leader` 是未来标签仅作对照。
- 全部阈值预声明 in-sample；等权不调参（主人裁定）；敏感性只跑预声明档位。
- 月度一致 <0.7 或 6/7 翻转 → 无论全样本多好看都标证据不足。
- Frame-2 股票日自相关 → 只报计数+lift，不做 CI。
- regime 单 episode（2026-07 崩盘）→ 只给描述性结论。

## 文件清单

- 新建 `alphaagent/server/services/limit_up/leader_first_board_fused_score_research.py`
  （只读；复用老模块 `_structure_features`/`_build_touch_index`/统计工具，不改老模块）
- 新建 `tests/alphaagent/test_limit_up_fused_score_research.py`
- 产物 `memory/06_backtests/limit_up_leader_first_board_fused_score_20260803.{json,md}`
- 本计划归档（requirements/alphaagent_limit_up_fused_score_research_plan.md）

后续阶段（本期不做）：数据裁决后改造潜龙观察池为「融合分 Top-N 榜」；
扫板→打板回测叠加融合分排序；分钟回填后接竞价/分钟涨幅确认层。

## 验证

```bash
uv run pytest tests/alphaagent/test_limit_up_fused_score_research.py -v
docker compose --profile research run --rm --no-deps -v "$PWD:/app" alphaagent-research \
  python -m alphaagent.server.services.limit_up.leader_first_board_fused_score_research \
  --start 2025-06-27 --end 2026-07-31 \
  --json-output memory/06_backtests/limit_up_leader_first_board_fused_score_20260803.json \
  --markdown-output memory/06_backtests/limit_up_leader_first_board_fused_score_20260803.md
# 对账：11223 首板 / 2462 ≥2板（21.94%）/ 968 ≥3板
```
