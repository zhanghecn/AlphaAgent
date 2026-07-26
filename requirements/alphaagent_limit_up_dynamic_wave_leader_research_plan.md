# AlphaAgent 动态资金波段龙头研究 Implementation Plan

> **归档结果：** 波段、动态席位和质量重建任务已完成。唯一正式合同现为
> `limit-up-core-ab-v1`（A+B）；A+B+C 已否决，动态扩散只保留研究证据。正文中“正式
> v15/v9/v5 未变化”和“双版本等待前向”是执行当时的检查点，不代表当前状态。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This repository forbids commits unless the user explicitly requests one, so tasks end with verification checkpoints.

**Goal:** 在 2026 年 3-7 月动态概念中识别可重启的资金波段，并在每个波段内按当时已知的点火、趋势、成交额承载、连板和扩散证据动态计算龙一、龙二、龙三，验证其对同概念后续涨幅和正式打板质量的增量。

**Architecture:** 复用现有动态概念日面板和正式账户收益，但不复用现有超长 `concept_cycle_id` 或单日涨停 `role_order` 作为最终龙头。第一层用概念指数、成交额和梯队共同转弱/再点火切分资金波段；第二层对波段成员逐日累计相对收益、成交额、点火时序、有效板和已发生扩散，生成会随时间迁移的龙一/龙二/龙三；第三层只把 D-1 已成立的角色连接 D 日正式推荐，未来 1/3/5 日收益只作标签。财报反推单列审计，不用“本地财报有无”作为新因子。

**Tech Stack:** Python 3.11+、pandas、SQLAlchemy/PostgreSQL 只读数据、现有 AlphaAgent 正式账户模拟、pytest、Markdown 研究证据。

---

## 完成口径

1. 概念和股票名称不得进入波段切分或角色排序；金安国纪、亨通光电、东山精密、德明利、深科技只作命名案例审计。
2. 波段不得像旧 PCB 周期一样把 4 月 7 日到 7 月 2 日多轮行情粘成一个周期；共同转弱后再增强必须生成新的 `wave_id`。
3. 龙头不要求连续二板。连板龙、趋势龙和容量龙保留独立分量，最终龙一/龙二/龙三是波段内的动态席位，不是永久身份。
4. D 日候选只能读取 D-1 收盘前已经发生的波段和席位；未来板块涨幅、未来跟随者数量、波段终点不得进入特征。
5. 主要评价仍为规则保留后的全部正式推荐 D+1 胜率，目标 `>=60%`；不使用两仓结果晋级。
6. 3-6 月当前概念成员只能标记 `current_membership_survivorship_proxy`；严格点时结果必须单列。
7. 旧财报高胜率原因只允许从旧覆盖机制、点时财务值和同一候选反事实推断，禁止恢复“财报缺失即拒绝”的错误硬门。

## Task 0：固定旧算法漏判证据

**Files:**
- Create: `memory/06_backtests/limit_up_dynamic_wave_leader_root_cause_20260726.md`
- Modify: `memory/06_backtests/README.md`

- [x] **Step 1: 记录五个命名案例的原始事实**

从 `stock_daily_bars` 记录 2026-03-01..07-24 的涨停日、3/5/10 日收益和成交额；明确“金安国际”按数据库名称核实为金安国纪 `002636.SZSE`。

- [x] **Step 2: 记录旧算法四个结构缺口**

必须写明：股票宇宙受涨停事件限制、确认龙要求一进二、概念周期结束门过宽、龙二龙三是单日排序而非波段席位。

- [x] **Step 3: 记录财报反推边界**

引用已验证事实：旧财报覆盖由当前成交额/市值排序的每日 100 只同步塑造；正确同比仍有正边际，补齐后下降来自隐性样本筛选消失，不是财报质量因子反向。

## Task 1：实现可重启的概念资金波段合同

**Files:**
- Create: `alphaagent/server/services/limit_up/dynamic_wave_leader.py`
- Create: `tests/alphaagent/test_limit_up_dynamic_wave_leader.py`

- [x] **Step 1: 写共同转弱后重新点火测试**

```python
def test_segment_concept_waves_splits_reignition_after_joint_weakness() -> None:
    waves = segment_concept_waves(_concept_panel())
    assert waves["wave_id"].nunique() == 2
    assert waves.groupby("wave_id")["trade_date"].min().tolist() == [D1, D7]
```

- [x] **Step 2: 写趋势点火不要求首板测试**

```python
def test_segment_concept_waves_accepts_index_turnover_trend_ignition() -> None:
    waves = segment_concept_waves(_trend_only_panel())
    assert waves.iloc[0]["wave_start_reason"] == "index_turnover_trend_ignition"
```

- [x] **Step 3: 实现波段状态机**

公共 API 固定为
`segment_concept_waves(concept_panel: pd.DataFrame) -> pd.DataFrame`。

点火允许“涨停梯队点火”或“指数和成交额共同进入横截面强区”；连续两日指数、成交额、梯队三者至少两项低于中位区后结束。结束后新的共同增强必须使用新 `wave_id`，不得复用旧波段。

- [x] **Step 4: 运行波段测试**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_dynamic_wave_leader.py -k wave`

Expected: 波段可重启，且不要求固定概念名称或连续二板。

## Task 2：计算波段成员的点时领导力分量

**Files:**
- Modify: `alphaagent/server/services/limit_up/dynamic_wave_leader.py`
- Modify: `tests/alphaagent/test_limit_up_dynamic_wave_leader.py`

- [x] **Step 1: 写未来隔离测试**

```python
def test_leadership_asof_is_unchanged_by_future_stock_bars() -> None:
    before = build_wave_member_features(_inputs(end=D4), _waves())
    after = build_wave_member_features(_inputs(end=D8), _waves())
    assert_frame_equal(_at(before, D4), _at(after, D4))
```

- [x] **Step 2: 写趋势/容量龙可超过单日二板龙测试**

```python
def test_dynamic_rank_can_select_trend_capacity_leader_without_second_board() -> None:
    ranks = rank_dynamic_wave_leaders(_member_features())
    row = ranks.loc[ranks["trade_date"].eq(D4) & ranks["leader_rank"].eq(1)].iloc[0]
    assert row["vt_symbol"] == "600001.SSE"
    assert {"trend_leader", "capacity_leader"}.issubset(row["leader_roles"])
```

- [x] **Step 3: 实现分量表**

公共 API 固定为
`build_wave_member_features(inputs: CapitalMainlineInputs, waves: pd.DataFrame,
membership_contexts: Mapping[date, MembershipContext]) -> pd.DataFrame` 和
`rank_dynamic_wave_leaders(features: pd.DataFrame) -> pd.DataFrame`。

逐日保留：首次强势日、波段累计/3日/5日相对收益、成交额横截面分位、波段累计涨停数、有效最高板、截至当日已响应的其他成员数和角色任期。排序分量全部输出；席位只在至少两个独立分量进入波段前三时成立，避免单一成交额或单一涨幅决定龙头。

- [x] **Step 4: 运行角色测试**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_dynamic_wave_leader.py -k 'leadership or rank or future'`

Expected: 趋势/容量龙不需要二板，且未来行情不改变历史席位。

## Task 3：生成动态龙一到龙二龙三的映射标签

**Files:**
- Modify: `alphaagent/server/services/limit_up/dynamic_wave_leader.py`
- Modify: `tests/alphaagent/test_limit_up_dynamic_wave_leader.py`

- [x] **Step 1: 写同波段和席位迁移测试**

```python
def test_follower_mapping_stays_in_wave_and_preserves_rank_migration() -> None:
    mappings = build_dynamic_leader_mappings(_ranks(), _stock_bars(), _trade_dates())
    assert set(mappings["wave_id"]) == {"BK001:2026-07-01:1"}
    assert mappings.loc[mappings["follower_symbol"].eq("600003.SSE"), "rank_at_response"].tolist() == [3, 2]
```

- [x] **Step 2: 实现事后标签**

公共 API 固定为
`build_dynamic_leader_mappings(ranks: pd.DataFrame, stock_bars: pd.DataFrame,
trade_dates: Sequence[date]) -> pd.DataFrame`。

输出龙一首次成立日、龙二龙三首次响应日、响应时排名、延迟交易日及 1/3/5 日收盘涨幅；数据不足保留空值，不填零。上述字段全部以 `realized_` 命名，禁止进入候选特征。

- [x] **Step 3: 运行映射测试**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_dynamic_wave_leader.py -k mapping`

Expected: 映射不跨波段，席位迁移被保留，未来收益只存在于 realized 标签。

## Task 4：连接正式全量候选并评价增量

**Files:**
- Modify: `alphaagent/server/services/limit_up/dynamic_wave_leader.py`
- Modify: `tests/alphaagent/test_limit_up_dynamic_wave_leader.py`

- [x] **Step 1: 写 D-1 边界测试**

```python
def test_candidate_uses_previous_session_dynamic_rank_only() -> None:
    result = attach_dynamic_wave_features(_candidates(), _ranks(), _trade_dates())
    assert result.loc[0, "prior_dynamic_leader_rank"] == 2
    assert result.loc[0, "prior_wave_id"] == "BK001:2026-07-01:1"
```

- [x] **Step 2: 实现候选连接与预注册切片**

公共 API 固定为
`attach_dynamic_wave_features(candidate_frame: pd.DataFrame, ranks: pd.DataFrame,
trade_dates: Sequence[date]) -> pd.DataFrame` 和
`evaluate_dynamic_wave_factors(frame: pd.DataFrame) -> dict[str, object]`。

至少评价：动态龙一、动态龙二龙三、趋势龙、容量龙、连板龙、两类以上角色共振、龙一成立后 1/2/3 个交易日、波段扩散和波段分歧。每组报告全量闭合数、胜率、均值、复利、回撤、硬亏、月份覆盖和 3-5/6-7 时间拆分。

- [x] **Step 3: 运行候选测试**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_dynamic_wave_leader.py -k candidate`

Expected: 只使用 D-1 动态席位，评价对象为全部正式推荐而非两仓。

## Task 5：运行 3-7 月发现并回答命名案例

**Files:**
- Modify: `alphaagent/server/services/limit_up/dynamic_wave_leader.py`
- Create: `memory/06_backtests/limit_up_dynamic_wave_leader_discovery_2026_03_07.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: 增加只读研究 CLI**

```bash
docker compose --profile research run --rm -T --no-deps \
  -v "$PWD:/workspace" -w /workspace \
  alphaagent-research python -u -m \
  alphaagent.server.services.limit_up.dynamic_wave_leader \
  --start 2026-03-01 --end 2026-07-24 \
  --output memory/06_backtests/limit_up_dynamic_wave_leader_discovery_2026_03_07.md
```

- [x] **Step 2: 报告动态波段和席位**

报告每个资金波段的开始/结束、概念、龙一/龙二/龙三迁移、角色分量和同概念响应；单列金安国纪、亨通光电、东山精密、德明利、深科技是否识别、何时成立、为何旧算法漏掉。

- [x] **Step 3: 报告正式打板增量**

严格区分事后映射上涨率和 D-1 点时正式候选胜率。任何 `>=60%` 但少于 30 笔或少于 3 个月的切片标记 `small_sample`；不得当场调权重追胜率。

## Task 6：归档财报反向推理和验证边界

**Files:**
- Create: `memory/06_backtests/limit_up_financial_coverage_reverse_reasoning_20260726.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: 写入同候选财报消融事实**

归档正确同比通过/不通过、旧覆盖/新补覆盖及 locked holdout 的样本、胜率和均值，明确旧覆盖是当前成交额与市值造成的非随机缺失。

- [x] **Step 2: 与动态波段角色交叉解释**

只回答“旧覆盖可能代理了哪些资金承载和风格状态”，不把历史当前快照混入新点时因子。若缺少旧逐笔覆盖身份，则标记无法做逐笔交叉，不伪造结果。

- [x] **Step 3: 固定后续验证边界**

3-7 月与既有 806 日均已查看，只能生成假设；任何新动态波段因子只能冻结后进入 2026-07-27 起的自然前向，不得继续复用历史调参晋级。

## Task 7：最终回归

**Files:**
- Test: `tests/alphaagent/test_limit_up_dynamic_wave_leader.py`
- Test: `tests/alphaagent/test_limit_up_leader_follower_factor.py`
- Test: `tests/alphaagent/test_limit_up_capital_mainline_*.py`

- [x] **Step 1: 运行定向测试**

```bash
uv run --group server pytest -q \
  tests/alphaagent/test_limit_up_dynamic_wave_leader.py \
  tests/alphaagent/test_limit_up_leader_follower_factor.py \
  tests/alphaagent/test_limit_up_capital_mainline_contract.py \
  tests/alphaagent/test_limit_up_capital_mainline_repository.py \
  tests/alphaagent/test_limit_up_capital_mainline_research.py \
  tests/alphaagent/test_limit_up_capital_mainline_evaluation.py
```

Expected: 全部通过。

- [x] **Step 2: 运行静态检查**

```bash
uv run python -m compileall -q alphaagent/server/services/limit_up
git diff --check
```

Expected: 无错误；正式 v15/v9/v5、页面和下单链没有变化。

## Task 8：重建旧覆盖质量并识别扩散早期

**Files:**
- Create: `alphaagent/server/services/limit_up/quality_reconstruction.py`
- Create: `tests/alphaagent/test_limit_up_quality_reconstruction.py`
- Modify: `alphaagent/server/services/limit_up/dynamic_wave_leader.py`
- Create: `memory/06_backtests/limit_up_quality_reconstruction_20260726.md`

- [x] **Step 1: 固定质量重建硬门**

只在修复后的正式质量推荐之上读取两个 D-1 字段：过去 126 日涨停次数 `2-6`，且所属
行业 D-1 成交额不低于更早 5 日均值。旧 v14 身份只用于根因审计，筛选函数禁止读取。

- [x] **Step 2: 计算扩散的一阶变化**

在每个可重启波段内记录扩散首日、扩散年龄、首板/封板/梯队宽度变化和量能变化。候选只
连接 D-1 状态；扩散首日、前两日和宽度量能同步脉冲分别消融，不根据收益调年龄阈值。

- [x] **Step 3: 动态选择主传播概念**

候选多概念归属时，不再无条件使用旧主概念。按扩散脉冲、前两日、宽度抬升、扩散/加速、
主线和量能选择当时传播上下文；旧主概念与覆盖模式保留审计字段。

- [x] **Step 4: 固定最终研究合同**

核心质量版为正式盈利门后过去 126 日涨停 2-6 次，`56/78=71.7949%`；行业量能扩张
的 A 级为 `35/41=85.3659%`，B 级为 `21/37=56.7568%`。按用户整体 `>=60%` 的覆盖
目标，再并入动态概念成交承载 `>=0.80` 且不满足 2-6 次的 C 级，A+B+C 为
`80/121=66.1157%`，C 级单独为 `24/43=55.8140%`。3-7 月 A 级质量底座为
`24/28=85.7143%`；早期扩散交叉为 `14/15=93.3333%`。因此冻结核心质量版和覆盖版两种
宽度，不恢复缺财报拒绝；早期扩散只排序，不再新增第四类交易。

- [x] **Step 5: 固定验证边界**

两版规则均为 `candidate_for_natural_forward`，从 2026-07-27 起至少积累 60 个交易日、
30 笔闭合、3 个月和两个情绪阶段；覆盖版全量 A+B+C 胜率 `>=60%`，并单列核心 A+B、
C 级增量和时间分段后才能讨论生产。正式 v15/v9/v5、页面和下单链保持不变。
