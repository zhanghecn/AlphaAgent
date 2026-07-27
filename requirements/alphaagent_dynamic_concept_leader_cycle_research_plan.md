# AlphaAgent 日级资金主线与动态概念龙头周期研究 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This repository forbids commits unless the user explicitly requests one, so every task ends with a verification checkpoint instead of a commit step.

**Goal:** 在不依赖分钟行情、不预设概念名称、不使用事后最高板作为决策特征的前提下，重建 2026 年 3-7 月每个市场情绪周期和动态概念资金周期，找出每个周期的点火龙、确认龙、龙二、龙三、容量核心、补涨和反包角色，并验证这些角色是否真正提高现有首板/二进三打板候选的 D+1 收益质量。

**Architecture:** 研究分成“市场情绪周期 -> 动态概念资金周期 -> 周期内个股角色 -> 正式候选反事实”四层。概念集合每日从数据库读取，官方概念指数负责识别板块强弱和周期边界，日级板块/个股资金流负责确认或否定资金主线，涨停梯队负责识别点火、接力和扩散；3-6 月缺少历史点时成员时只生成明确标记的幸存者代理，7 月完整成员快照之后才生成严格点时归属。研究执行时不直接修改当时的 `limit-up-core-ab-v1`，只有同日反事实、滚动验证和自然前向均通过后，才另写正式接入计划。

**Tech Stack:** Python 3.11、pandas、SQLAlchemy/PostgreSQL、现有 AlphaAgent 日线/涨停事件/正式回放、pytest、Markdown 研究报告。

**Archived result (2026-07-25):** 第一阶段 `rejected_no_incremental_value`。Tasks 0-8 已完成；
D-1 主线/资金角色没有形成稳定增量，正式策略、页面和版本均未修改。本计划的 3-7 月
周期账本和反例已经归档；后续不再调旧主线权重，转入
`requirements/alphaagent_limit_up_leader_follower_factor_research_plan.md`，研究“确认龙头到
同概念龙二龙三”的独立因子族，再决定是否启动完整历史和自然前向。

> **当前状态：** 后续逆向研究形成的 C 补位已进入 `limit-up-core-abc-v1`；以下 A+B
> 表述仅记录本计划执行时的基线。

---

## 一、研究方向已经改变

### 新的核心假设

高胜率打板不应被简化为“财报好”“成交额大”或“当前最高板”。需要验证的新假设是：

> 当低位首板率先启动，随后板块指数、资金流和排除该股票后的成员扩散共同确认，并出现
> 一进二、连续二进三或二板后反包三板时，该股票及同周期龙二、龙三、低位补涨的 D+1
> 质量显著高于同日、同板型、同市场环境的普通打板候选；资金与指数/梯队背离时胜率和
> 收益下降。

这个假设包含三个不同对象，不能再混成一个“龙头分数”：

1. **市场情绪周期**：全市场什么时候从冰点修复、扩散、加速、分歧、回流到退潮。
2. **概念资金周期**：哪个动态概念正在点火、确认、扩散或退潮，主线何时切换。
3. **个股角色周期**：谁先点火，谁完成一进二确认，谁是龙二/龙三，谁是容量核心、补涨或独立空间龙。

自然月只用于报告分组。周期边界必须由交易日状态转移生成，一个周期可以跨月，同一天也
可以有多个并行概念周期。

### 为什么旧 Tasks 0-6 没有回答这个问题

旧日级账本可保留“有效连板、市场最高板任期、情绪分数”这些基础事实，但其题材归因不能
继续作为龙头结论，原因已经从源码定位：

1. `leader_cycle_research.build_daily_cycle_ledger()` 没有把
   `sector_daily_bars` 和日级 `sector_fund_flows` 作为主线输入，无法回答概念指数和资金
   是否同步走强。
2. `_select_main_group()` 先按“覆盖涨停股数量最多”选板块，天然偏向成员很多的大筐概念。
3. `_group_for_symbol()` 在股票属于多个概念时直接选择 `member_count` 最大的组，导致
   “央国企改革”等宽泛标签反复覆盖医药、电力、半导体等更具体的交易主线。
4. `group_concepts()` 使用成员重叠的传递闭包，全局合并后可能形成过大的概念连通分量；
   新研究不得把这个分组结果直接当主归属。
5. 3-6 月没有历史点时概念成员，旧报告使用当前成员回看历史；它只能描述，不能证明当时
   某股票属于某概念。
6. 角色按多日汇总后会让同一股票同时出现点火龙、龙二、龙三、普通跟风等互相冲突标签；
   新研究必须以 `market_cycle_id + concept_cycle_id + as_of_date` 为角色主键。

因此，本计划不是在旧龙头分数上继续调权重，而是重建“周期、概念归属和资金确认”三个
基础对象。

## 二、最终要回答什么

### 3-7 月逐周期问题

研究完成后，必须能逐个回答以下问题，而不是只给一张股票总排名：

1. 这轮市场情绪周期从哪一天开始、在哪一天加速、何时第一次分歧、是否回流、何时结束？
2. 该周期内哪些概念先后成为主线、次主线和轮动分支？
3. 每个概念周期的第一个低位首板候选是谁？如果同日有多只，必须保留并列候选。
4. 谁在下一交易日完成一进二并确认点火，谁连续二进三，谁走出二板后反包三板？
5. 龙二、龙三是在主线确认前共同启动，还是确认后才补涨？
6. 概念指数、成交额、板块资金流、个股资金流和涨停扩散在每个阶段是否同向？
7. 哪些高板只是独立空间龙，没有带动板块；哪些低位股虽然高度不高，却是资金容量核心？
8. 主线切换日，旧龙头、旧龙二龙三和新周期首板的风险收益发生了什么变化？
9. 把这些信息放回现有正式候选后，究竟改善了多少 D+1 胜率、均值、复利、回撤、硬亏和连亏？

### 最终逐周期表

每个 `concept_cycle_id` 至少输出以下字段：

| 字段 | 含义 |
|---|---|
| `market_cycle_id` | 所属市场情绪周期，不按自然月切分 |
| `concept_cycle_id` | 概念自身周期 ID |
| `sector_id/name` | 当日动态概念，不来自预设名单 |
| `start/confirm/peak/divergence/reflux/end_date` | 周期关键日期 |
| `capital_evidence` | `real_flow_confirmed / turnover_proxy_only / divergent / unavailable` |
| `ignition_candidates` | 首个低位首板候选，可并列 |
| `confirmed_ignition_leader` | 后续完成资金/扩散和接力确认的点火龙标签 |
| `leader_2/leader_3` | 当日点时排序及其后续实现标签，二者分开保存 |
| `continuous_two_to_three` | 连续二进三路径 |
| `short_cycle_reboard_three` | 二板后短周期反包三板路径 |
| `capacity_core/replenishment` | 容量核心和低位补涨 |
| `unique_follower_diffusion` | 排除点火龙且扣除重叠概念后的扩散 |
| `formal_candidate_results` | 与正式首板/二进三候选连接后的 D+1 结果 |
| `membership_evidence_level` | 严格点时、当前成员代理或不可用 |

股票总榜只能作为索引，不能替代逐周期表。

## 三、研究合同

### 不使用分钟行情

- 不读取 `stock_minute_bars`、概念分钟强度或分钟雷达来定义本研究因子。
- 历史周期只使用收盘后完整的日线、日级资金、涨停事件和点时成员。
- 盘中实时资金快照可以在未来前向阶段按 `captured_at <= decision_at` 使用，但它不是本计划
  3-7 月历史结论的必要条件，也不能回填缺失历史。
- “最早”只表示最早交易日启动；同一天多只首板没有分钟先后时必须并列，不得伪造日内先后。

### 概念完全动态

- 每个交易日从 `sectors(type='concept')` 和官方
  `sector_daily_bars(source='eastmoney.board_kline')` 读取当时存在的全部概念。
- 半导体、存储、算力、医药、中药、电力只是报告中可能出现的结果，不出现在概念白名单、
  固定权重或分支代码中。
- 可复用 `concept_resonance.is_execution_concept()` 排除指数、风格和事后事件标签；这是
  通用过滤规则，不是主线概念白名单。
- 新概念进入数据库后自动参与横截面排名，消失或缺行情的概念按当日动态分母处理。

### 不再让大筐概念自动胜出

概念强度使用比例、横截面排名和相对市场增量，不能按成员绝对数直接排序：

- 概念涨停宽度使用 `sealed_members / eligible_members` 和相对全市场的超额值。
- 扩散必须排除点火龙自身，并计算去重后的 `unique_follower_count/ratio`。
- 大概念不会因成员多自动获胜；但如果指数、资金和广泛成员确实同时走强，它仍可成为主线。
- 高度重叠概念只做**当日成对别名抑制**，保留各自成员，不使用传递闭包把整个概念网络
  合成一个大组。
- 股票同时属于多个概念时，对每条 `stock -> concept` 关系分别计分；只有第一名证据明显
  优于第二名才给主归属，否则保留 `multi_theme_unresolved`，不能强行选成员最多的概念。

### 点时角色和事后标签分离

所有角色保留两列：

- `role_asof`：截至 D 日收盘或买点前已知信息得到的可交易角色。
- `role_realized`：用后续一进二、二进三、反包和最终扩散得到的研究标签。

最终高度、周期峰值、D+1 收益、未来扩散和最终龙头身份只能进入 `role_realized`。未来数据
变动不得改写更早日期的 `role_asof`。

### 首板交易的时点边界

日级数据可以在 D 日收盘后确认 D 日首板是不是点火候选，因此：

1. D 日首板的“最终点火龙”身份只用于复盘标签，不能冒充 D 日盘中可见因子。
2. D+1 的一进二、龙二龙三接力和低位补涨，可以使用 D 日收盘已确认的概念状态。
3. 若未来要提升 D 日同日首板，只能使用 D-1 已确认周期状态或买点前真实保存的资金快照；
   该前向验证单列，不能用 D 日收盘值回测 D 日触板。

### 执行当时正式策略保持不变

研究期间继续保持：

- 本研究执行期间，历史、实时、调度和现金执行统一使用 `limit-up-core-ab-v1`。
- 正式首板/二进三候选母池、财报点时门、费用、涨停价入场代理和 D+1 官方收盘退出不变。
- 新因子只能先做同日反事实和研究影子；不得直接新增买点、删除正式推荐或改变两仓顺序。
- 全量推荐与两仓账户分别报告，不得用 Top2 或实际占仓子集代表规则质量。

## 四、三层周期定义

### 1. 市场情绪周期

输入为全市场涨停数、首板数、炸板率、跌停数、最高有效板、一进二率、二进三率以及现有
`sentiment_score/phase`。周期状态为：

```text
ice -> repair -> launch -> acceleration -> divergence -> reflux -> ebb
                  |              |              |
                  +-----------> divergence <----+
```

- 从冰点/退潮后的首次持续修复开始新 `market_cycle_id`。
- 分歧后指标重新改善进入 `reflux`，不是新周期；出现新低位梯队且旧梯队退出后才切新周期。
- 周期可跨 3 月末或 4 月初，月界不得强制截断。

### 2. 概念资金周期

每个概念每日计算三组相互独立的证据：

1. **指数强度**：1/3/5/10 日超额收益、20 日突破、回撤、成交额放大、横截面百分位。
2. **资金强度**：主力净流入、净流入占比、资金排名及排名变化、5 日/10 日持续性；缺失保留
   `null`，不填 0。
3. **梯队扩散**：首板、一进二、二进三、反包三板、排除龙头后的涨停宽度和失败率。

状态为：

```text
watch -> ignition_candidate -> confirmation -> diffusion -> acceleration
                              -> divergence -> reflux -> diffusion/acceleration
                              -> ebb -> ended
```

候选启动门只用滚动值和当日横截面分位，不依赖概念名称。周期定义先按无收益标签的稳定性
选择并冻结，再连接 D+1 收益，防止用交易结果反向挑周期。

### 3. 个股角色周期

- `ignition_candidate`：概念尚未确认前最早交易日出现的低位首板，可并列。
- `confirmed_ignition_leader`：点火候选随后完成一进二或反包确认，且排除自身后板块扩散成立。
- `leader_2` / `leader_3`：同一概念周期内按当日可见的启动时序、板位、相对强度、资金承载
  和独立扩散贡献排列的第二、第三角色；每天可换位。
- `continuous_two_to_three`：连续三个相邻市场交易日有效封板。
- `short_cycle_reboard_three`：最近五个市场交易日含当日恰有三次有效封板，且前一日未封板。
- `capacity_core`：概念内成交承载和资金持续性居前，但不要求是最高板。
- `replenishment`：概念确认后才首次启动的低位补涨。
- `independent_space_leader`：市场高度高但独立扩散贡献不足，不能冒充题材点火龙。

角色主键固定为 `(market_cycle_id, concept_cycle_id, trade_date, vt_symbol)`。

## 五、当前真实数据边界（2026-07-25 只读核验）

| 数据 | 当前覆盖 | 本研究用途 |
|---|---|---|
| 官方概念指数日线 | `2022-12-26..2026-07-24`，866 日、495 概念、337,253 行 | 3-7 月周期的严格板块指数证据 |
| 2026-03 概念指数 | 22 日、463 概念、10,037 行 | 3 月动态概念周期 |
| 2026-04 概念指数 | 21 日、483 概念、10,006 行 | 4 月动态概念周期 |
| 2026-05 概念指数 | 18 日、483 概念、8,694 行 | 5 月动态概念周期 |
| 2026-06 概念指数 | 21 日、491 概念、10,271 行 | 6 月动态概念周期 |
| 2026-07 概念指数 | 18 日、495 概念、8,890 行 | 7 月动态概念周期 |
| 概念资金流 | `2026-06-18..2026-07-24`，26 日；即时/5日/10日各 12,822 行 | 日终值只在 `source_updated_at` 通过已知时点门后用于 D+1；否则仅作佐证 |
| 个股资金流 | `2026-06-12..2026-07-24`，32 日、4,052 只、10,588 行 | 近期容量核心佐证，缺失不判负 |
| 完整概念成员 scope | `2026-07-16..2026-07-24` 共 7 个完整快照日 | 交易日使用决策前最近完整快照，严格验证从后续日开始 |
| 历史概念成员 | `low_suction_concept_membership_history=0` | 3-6 月只能作当前成员幸存者代理 |
| 板块日级指标 | `sector_daily_metrics=0` | 在研究内按证据级别动态计算，不伪造现成历史 |
| 既有板块评分 | `2026-03-13..2026-07-24`，47 日 | 含当前成员回算字段，不作为严格真值 |
| 全市场股票日线/涨停事件 | 3-7 月 100 个交易日 | 情绪、板位、收益和角色路径 |

关键结论：概念指数历史已足够，不需要再等待分钟补数；真正限制严格历史结论的是 3-6 月
成员和 3 月至 6 月中旬净资金流。报告必须把“官方指数严格证据”“成交额代理”“当前成员
代理”“严格点时成员”分列。

## 六、必须验证的五个假设

| 假设 | 处理组 | 同日对照 | 主要结果 |
|---|---|---|---|
| H1 点火确认 | D-1 概念处于点火/确认且资金同向的首板/一进二 | 同日同板型但概念未确认 | D+1 净收益、胜率、硬亏 |
| H2 龙头梯队 | 点火龙、龙二、龙三 | 同概念普通跟风、同日其他候选 | D+1 与后续晋级率 |
| H3 接力形态 | 连续二进三、短周期反包三板 | 同日其他二板/三板候选 | D+1、炸板和回撤 |
| H4 资金背离 | 指数/梯队强但净流入转弱或排名下滑 | 资金与指数/梯队同向 | 失败率、硬亏、连亏 |
| H5 主线切换 | 新周期低位点火，旧周期分歧/退潮 | 继续追旧龙头 | 相对收益和最大回撤 |

财报、成交额、市值、市场情绪和正式原评分作为控制变量，不恢复旧财报缺失 Bug，也不先验
认定资金一定有效。若同日匹配后资金主线没有稳定增益，结论必须是拒绝该假设。

## 七、文件边界

### 新建

- `alphaagent/server/services/limit_up/capital_mainline_contract.py`：证据等级、市场/概念周期状态、点时角色与事后标签合同。
- `alphaagent/server/services/limit_up/capital_mainline_repository.py`：只读加载官方概念指数、日级资金、点时/代理成员、股票日线、涨停事件和正式候选，并生成覆盖与指纹。
- `alphaagent/server/services/limit_up/capital_mainline_research.py`：构造动态概念面板、市场周期、概念周期、主归属和龙头梯队。
- `alphaagent/server/services/limit_up/capital_mainline_evaluation.py`：同日匹配、资金消融、正式候选反事实和负对照。
- `tests/alphaagent/test_limit_up_capital_mainline_contract.py`：无未来、状态机和证据等级测试。
- `tests/alphaagent/test_limit_up_capital_mainline_repository.py`：来源、覆盖、缺失值和点时成员测试。
- `tests/alphaagent/test_limit_up_capital_mainline_research.py`：动态概念、重叠归属、周期和角色测试。
- `tests/alphaagent/test_limit_up_capital_mainline_evaluation.py`：同日反事实、全量/两仓隔离和负对照测试。
- `memory/06_backtests/limit_up_capital_mainline_cycle_2026_03_07.md`：3-7 月逐市场周期、逐概念周期和龙头梯队总表。
- `memory/06_backtests/limit_up_capital_mainline_fund_ablation.md`：资金确认、成交额代理和背离消融。
- `memory/06_backtests/limit_up_capital_mainline_candidate_counterfactual.md`：正式候选同窗结果与研究决定。

### 复用但不修改

- `leader_cycle_contract.py`：有效板路径和无未来字段守卫。
- `sentiment.py`：全市场日级情绪输入。
- `lane_repository.py`：涨停事件和正式质量候选来源。
- `history_repository.py`：冻结历史回放。
- `concept_resonance.py`：通用风格/事后概念过滤。
- `sector_daily_bars`、`sector_fund_flows`、`stock_fund_flows`：共享原始证据表。

### 明确不修改

- `vnpy/`、`examples/`。
- 正式 `history_service.py`、`live_service.py`、`scheduled_execution.py` 和版本常量。
- 前端页面和正式 API。研究通过后另开生产接入计划。

## 八、执行任务

### Task 0：冻结研究合同，停止旧题材归因继续扩散

**Files:**
- Create: `alphaagent/server/services/limit_up/capital_mainline_contract.py`
- Create: `tests/alphaagent/test_limit_up_capital_mainline_contract.py`

- [x] **Step 1: 定义证据、周期和角色枚举**

至少固定以下枚举，不允许用自由字符串在模块间漂移：

```python
class EvidenceLevel(StrEnum):
    POINT_IN_TIME = "point_in_time"
    DAILY_CLOSE_OBSERVED = "daily_close_observed"
    TURNOVER_PROXY = "turnover_proxy_only"
    CURRENT_MEMBERSHIP_PROXY = "current_membership_survivorship_proxy"
    UNAVAILABLE = "unavailable"

class ConceptCyclePhase(StrEnum):
    WATCH = "watch"
    IGNITION = "ignition_candidate"
    CONFIRMATION = "confirmation"
    DIFFUSION = "diffusion"
    ACCELERATION = "acceleration"
    DIVERGENCE = "divergence"
    REFLUX = "reflux"
    EBB = "ebb"
    ENDED = "ended"
```

- [x] **Step 2: 固定点时与事后字段隔离**

`CapitalRoleRow` 分别保存 `role_asof` 和 `role_realized`。点时字段守卫必须拒绝
`future_max_board_height`、`final_role`、`cycle_end_date`、`d1_return`、
`future_follower_count`。

- [x] **Step 3: 写未来数据翻转测试**

```python
def test_future_outcomes_cannot_enter_asof_role_features() -> None:
    with pytest.raises(ValueError, match="future feature"):
        validate_asof_fields(["capital_rank", "final_role", "d1_return"])
```

- [x] **Step 4: 运行合同测试**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_capital_mainline_contract.py`

Expected: PASS；所有非法未来字段被拒绝，证据缺失是 `UNAVAILABLE` 而不是数值 0。

### Task 1：建立只读数据集和证据覆盖账本

**Files:**
- Create: `alphaagent/server/services/limit_up/capital_mainline_repository.py`
- Create: `tests/alphaagent/test_limit_up_capital_mainline_repository.py`

- [x] **Step 1: 写来源和区间失败测试**

测试只接受 `sectors.type='concept'`、`sector_daily_bars.source='eastmoney.board_kline'`；
加载区间前至少读取 25 个交易日作为滚动特征预热，但输出严格裁剪为请求区间。

- [x] **Step 2: 实现统一加载结果**

```python
@dataclass(frozen=True, slots=True)
class CapitalMainlineInputs:
    trade_dates: tuple[date, ...]
    concept_bars: tuple[dict[str, object], ...]
    sector_fund_flows: tuple[dict[str, object], ...]
    stock_fund_flows: tuple[dict[str, object], ...]
    memberships: tuple[dict[str, object], ...]
    membership_scopes: tuple[dict[str, object], ...]
    current_memberships: tuple[dict[str, object], ...]
    stock_bars: tuple[dict[str, object], ...]
    limit_up_events: tuple[dict[str, object], ...]
    formal_candidate_days: tuple[dict[str, object], ...]
    coverage: dict[str, object]
    fingerprints: dict[str, object]
```

公共加载入口固定为
`load_capital_mainline_inputs(start: date, end: date) -> CapitalMainlineInputs`。

- [x] **Step 3: 锁定点时成员选择**

D 日角色只允许读取 `snapshot_date < D` 且 scope 完整的最近概念快照。没有快照时加载当前
成员代理，但证据必须标为 `CURRENT_MEMBERSHIP_PROXY`；不得把代理行改名为 strict。

- [x] **Step 4: 锁定资金缺失语义**

3-5 月没有 `sector_fund_flows` 时，`main_net_inflow`、`flow_rank` 和变化字段保持 `None`；
仅概念成交额可标记 `TURNOVER_PROXY`。测试断言缺失行不会被补成 0 或横截面末位。

- [x] **Step 5: 锁定日级资金的已知时点**

`sector_fund_flows` 是会被日内/日终 upsert 的最新行，不是天然不可变快照。加载器优先读取
`raw.source_updated_at`，其次读取可证明的本地保存时间；只有 `known_at <= D+1 decision_at`
的 D 日终值能进入 D+1 特征。同日触板只能读取 `sector_fund_flow_snapshots` 中买点前保存的
帧；没有帧时状态为不可用。测试必须覆盖“行最早创建于盘中、但当前值来自盘后更新”的情况。

- [x] **Step 6: 运行覆盖命令**

Run:

```bash
docker compose --profile research run --rm -T --no-deps \
  -v "$PWD:/workspace" -w /workspace \
  alphaagent-research python -m \
  alphaagent.server.services.limit_up.capital_mainline_research \
  --coverage-only --start 2026-03-01 --end 2026-07-24
```

Expected: 100 个股票市场交易日；概念指数逐月覆盖与本计划快照一致；资金覆盖从 6 月 18 日
开始；完整成员快照只有 7 月 16 日以后，报告不读分钟表。

### Task 2：构造动态概念横截面，解决大筐和重叠归属

**Files:**
- Create: `alphaagent/server/services/limit_up/capital_mainline_research.py`
- Create: `tests/alphaagent/test_limit_up_capital_mainline_research.py`

- [x] **Step 1: 写“成员多不能自动获胜”失败测试**

构造任意名称的概念 A（1000 成员、20 个涨停、占比 2%）和概念 B（40 成员、6 个涨停、
占比 15%、指数和资金更强）。断言 B 的主线排序高于 A；测试中不出现真实行业名称。

- [x] **Step 2: 计算滚动和横截面特征**

实现 `build_dynamic_concept_panel(inputs)`，至少输出：

- `return_1d/3d/5d/10d_pct`、相对全概念中位数的超额收益。
- `turnover_expansion_1_20/5_20` 和当日横截面百分位。
- `main_net_inflow/ratio/rank`、1/3 日排名变化和可用性。
- `first_board_count/ratio`、`one_to_two_count`、`two_to_three_count`、
  `reboard_three_count`、排除候选后的 `unique_follower_count/ratio`。
- `eligible_member_count`、`membership_evidence_level` 和动态当日概念分母。

- [x] **Step 3: 实现成对别名抑制而不是传递闭包**

只有成员 Jaccard 和过去 20 日指数收益相关性同时足够高的概念才标记当日别名；A≈B、B≈C
不自动推出 A/B/C 合成一个成员并集。测试断言桥接概念不会制造巨型组。

- [x] **Step 4: 运行动态概念测试**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_capital_mainline_research.py -k 'concept or alias or broad'`

Expected: 任意新增概念自动进入；大筐不靠绝对数量胜出；重叠概念仍保留独立 ID 和证据。

### Task 3：按状态转移生成市场情绪周期

**Files:**
- Modify: `alphaagent/server/services/limit_up/capital_mainline_research.py`
- Modify: `tests/alphaagent/test_limit_up_capital_mainline_research.py`

- [x] **Step 1: 写跨月和回流失败测试**

构造 3 月 30 日开始修复、4 月 2 日加速的交易日序列，断言只有一个
`market_cycle_id`；分歧后重新改善进入 `reflux`，不会因日期跨月新建周期。

- [x] **Step 2: 实现 `discover_market_cycles()`**

状态输入只取当前和过去交易日的首板数、炸板率、跌停数、最高板、晋级率和现有情绪分数。
每个输出日保存触发该状态的原始分量，不只保存总分。

- [x] **Step 3: 锁定未来不变性**

把某周期结束后的涨停数乘 10，断言结束日前所有 `market_cycle_id/phase` 完全不变。

- [x] **Step 4: 运行状态机测试**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_capital_mainline_research.py -k market_cycle`

Expected: 跨月连续、分歧可回流、真正切换才生成新周期。

### Task 4：识别概念资金周期和主线切换

**Files:**
- Modify: `alphaagent/server/services/limit_up/capital_mainline_research.py`
- Modify: `tests/alphaagent/test_limit_up_capital_mainline_research.py`

- [x] **Step 1: 预注册无收益周期候选**

只比较以下结构候选，不读取 D+1 股票收益：启动横截面分位 `0.80/0.90`，确认要求
`1/2` 个后续交易日，退潮确认要求 `2/3` 个交易日。选择标准是跨时间块的周期稳定性、
错误重启率、右删失率和对已知指数趋势的覆盖，不是候选收益最高。

- [x] **Step 2: 实现 `discover_concept_cycles()`**

概念可并行运行；同一概念在旧周期结束后重新点火必须生成新 ID。真实资金存在时输出
`real_flow_confirmed/divergent`，缺失时只能输出 `turnover_proxy_only`，两者不能混合成一个
无来源总分。确认、分歧和结束状态只从首次满足条件的当日开始生效，不能在后续结果出现后
回写更早日期的点时阶段。

- [x] **Step 3: 实现每日主线/次主线排序**

排序依次比较证据完整度、资金确认、指数相对强度、独立扩散、梯队完整度和拥挤/退潮风险；
原始分量全部保留。允许“无可信主线”和并列主线，不强迫每天选第一名。

- [x] **Step 4: 写资金背离和主线切换测试**

断言价格强但净流入排名连续下降时进入 `divergence`；新概念低位首板、指数和资金共同增强
时，新旧概念分别保留周期状态，而不是事后覆盖旧周期。

- [x] **Step 5: 运行概念周期测试**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_capital_mainline_research.py -k concept_cycle`

Expected: 周期不按月切割，资金缺失不判流出，主线切换有可复核的逐分量原因。

### Task 5：动态归属股票并生成龙头梯队

**Files:**
- Modify: `alphaagent/server/services/limit_up/capital_mainline_research.py`
- Modify: `tests/alphaagent/test_limit_up_capital_mainline_research.py`

- [x] **Step 1: 写多概念主归属失败测试**

同一股票属于三个任意概念：一个大筐弱概念、一个资金/指数/独立扩散更强的具体概念、一个
证据相近概念。断言强概念获得主归属；第一、第二证据接近时返回
`multi_theme_unresolved`，不能按成员数或名称兜底。

- [x] **Step 2: 实现 `attribute_stock_to_cycles()`**

每条股票概念边保存：概念周期阶段、资金证据、指数强度、股票启动相对周期日、独立跟随者
贡献、成员证据和别名关系。主归属使用点时证据；代理成员只允许生成代理归属。

- [x] **Step 3: 实现 `rank_cycle_roles()`**

当日先生成 `ignition_candidate/leader_2/leader_3/capacity_core/replenishment` 的
`role_asof`，随后在标签阶段生成一进二、连续二进三、反包三板、最终扩散和独立空间龙的
`role_realized`。同日无分钟先后时点火候选并列。

- [x] **Step 4: 写角色未来翻转测试**

修改 D+1 之后的最终高度和扩散，断言 D 日 `role_asof`、主归属和顺序不变，但
`role_realized` 允许变化。

- [x] **Step 5: 运行角色测试**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_capital_mainline_research.py -k 'attribution or role or reboard'`

Expected: 每个角色都限定在具体周期；不再出现跨多个周期合并出的矛盾角色总榜。

### Task 6：生成 2026 年 3-7 月逐周期真实名单

**Files:**
- Modify: `alphaagent/server/services/limit_up/capital_mainline_research.py`
- Create: `memory/06_backtests/limit_up_capital_mainline_cycle_2026_03_07.md`

- [x] **Step 1: 增加 CLI 和报告渲染**

CLI 固定支持 `--start`、`--end`、`--output`，报告按市场周期组织，而不是按股票总高度排序。
每个市场周期先列动态概念轮换，再列每个概念的点火龙、龙二、龙三和接力路径。

- [x] **Step 2: 生成五个月报告**

Run:

```bash
docker compose --profile research run --rm -T --no-deps \
  -v "$PWD:/workspace" -w /workspace \
  -e PYTHONPATH=/workspace:/app/third_party/akshare \
  alphaagent-research python -m \
  alphaagent.server.services.limit_up.capital_mainline_research \
  --start 2026-03-01 --end 2026-07-24 \
  --output memory/06_backtests/limit_up_capital_mainline_cycle_2026_03_07.md
```

- [x] **Step 3: 做四类人工复核**

从报告中各抽取至少 3 个：真正板块点火龙、独立空间龙、资金/高度背离、主线切换案例。
逐日核对原始概念指数、资金行、涨停事件和成员证据。案例名称只用于验收算法结果，不写回
规则或测试白名单。

- [x] **Step 4: 验收报告完整度**

Expected:

- 100 个交易日全部属于明确市场状态或显式 `unavailable`。
- 每个入选概念周期都有开始、阶段变化、结束/右删失、资金证据和成员证据。
- 3-5 月及 6 月 18 日以前不出现“真实净流入确认”字样。
- 3-6 月个股概念归属明确标记幸存者代理，不冒充严格历史真值。
- 报告实际列出各周期龙头、龙二、龙三和板位路径，不只给方法说明。

### Task 7：隔离资金流是否真的有增量价值

**Files:**
- Create: `alphaagent/server/services/limit_up/capital_mainline_evaluation.py`
- Create: `tests/alphaagent/test_limit_up_capital_mainline_evaluation.py`
- Create: `memory/06_backtests/limit_up_capital_mainline_fund_ablation.md`

- [x] **Step 1: 固定三个不可混算的证据轨道**

```text
A: index_ladder_only       官方概念指数 + 涨停梯队，覆盖 3-7 月
B: turnover_proxy          A + 概念成交额放大，覆盖 3-7 月
C: real_fund_confirmed     B + 日级板块/个股净流入，只覆盖 6/12 或 6/18 以后
```

C 的短历史只用于方向验证和前向阈值冻结，不能反过来替 A/B 的三个月历史调参。
若日终资金的 `known_at` 门不通过，C 固定为 `corroboration_only`，不能进入历史选股特征。

- [x] **Step 2: 实现同日期同板型匹配**

处理组和对照组必须同交易日、同首板/一进二/二进三形态，并在市场周期、D-1 成交额分位、
财报门状态和原正式分数上匹配。没有同日对照的样本单列，不进入平均处理效应。

- [x] **Step 3: 固定输出指标**

每轨报告样本数、保留率、D+1 胜率、平均/中位净收益、逐日等权复利、最大回撤、硬亏率、
最大连亏、分市场阶段结果和置信区间。资金背离单独作为风险组。

- [x] **Step 4: 加入负对照**

随机打乱概念归属、把概念状态错位一日、只用大概念成员数、使用最终最高板身份四种负对照。
前三种应失去稳定增益；第四种必须被未来字段守卫拒绝。

- [x] **Step 5: 生成资金消融报告**

Run:

```bash
docker compose --profile research run --rm -T --no-deps \
  -v "$PWD:/workspace" -w /workspace \
  alphaagent-research python -m \
  alphaagent.server.services.limit_up.capital_mainline_evaluation \
  --study fund-ablation --start 2026-03-01 --end 2026-07-24 \
  --output memory/06_backtests/limit_up_capital_mainline_fund_ablation.md
```

Expected: 明确回答“真实资金确认是否优于指数/成交额代理”，而不是把资金缺失日期混入负样本。

### Task 8：连接正式候选，检验能否解释胜率下降

**Files:**
- Modify: `alphaagent/server/services/limit_up/capital_mainline_evaluation.py`
- Modify: `tests/alphaagent/test_limit_up_capital_mainline_evaluation.py`
- Create: `memory/06_backtests/limit_up_capital_mainline_candidate_counterfactual.md`

- [x] **Step 1: 冻结同窗基线**

从归档完整候选池读取相同日期、相同费用、相同涨停价入场和 D+1 收盘
退出结果。不能重新生成一个候选更少的母池后再称为基线。

- [x] **Step 2: 定义不改正式动作的反事实切片**

至少比较：

- 当前正式全量基线。
- 概念处于点火/确认且 D-1 已知。
- 点火候选、龙二、龙三。
- 连续二进三和反包三板。
- 资金与指数/梯队同向。
- 资金背离、概念退潮、旧主线切换风险。
- 财报门相同但资金角色不同的候选。

- [x] **Step 3: 锁定首板无未来测试**

D 日首板反事实只能读 D-1 概念闭合状态；D 日收盘确认只允许评估 D+1 一进二/补涨。测试
把 D 日收盘板块指标改掉，断言 D 日首板买点前特征不变。

- [x] **Step 4: 分别计算全量和两仓结果**

全量推荐用于判断规则质量；两仓账户仍按原到达顺序和占仓执行。禁止只报告龙头 Top2，
也禁止用两仓跳过的后排票提高全量胜率。

- [x] **Step 5: 生成反事实报告**

Expected: 报告逐项说明当前正确财报基线的亏损是否集中在“非主线、跟风、资金背离、退潮”
候选；若不能解释，明确写“资金主线不是主要缺失因子”。

### Task 9：滚动验证、严格前向和停止门

**Files:**
- Modify: `alphaagent/server/services/limit_up/capital_mainline_evaluation.py`
- Modify: `tests/alphaagent/test_limit_up_capital_mainline_evaluation.py`

- [x] **Step 1: 冻结 3-7 月用途**

3-7 月已经被人工查看，只用于定义、案例复核和反例攻击，不承担最终正式晋级结论。更早
概念指数可做 expanding walk-forward，但历史成员代理结果始终标为 exploratory。

- [ ] **Step 2: 建立自然前向账本**

从完整概念成员快照和真实资金开始，逐日不可变保存周期状态、角色、正式候选连接和 D+1
结算。最低门为 60 个完整新前向交易日、30 个闭合正式候选，且至少覆盖两个市场情绪阶段。

本轮旧主线规则已触发停止门；用户随后提出了不同且预注册的新因子方向。新方向先按
`alphaagent_limit_up_leader_follower_factor_research_plan.md` 完成 3-7 月因子归纳，冻结后才
允许启动本步骤要求的完整历史和自然前向账本。

- [x] **Step 3: 固定研究通过门**

同时满足以下条件才可进入单独的生产接入计划：

1. 全量推荐胜率、平均净收益、逐日等权复利同时优于当前同窗正确基线。
2. 最大回撤、硬亏率和最大连亏至少两项改善，另一项不得明显恶化。
3. 新规则保留的闭合样本不少于当前基线的 80%。
4. expanding walk-forward、锁定后段和两个市场阶段均不反向。
5. 严格前向达到 60 日/30 笔门，历史代理与严格前向方向一致。
6. 负对照无同等增益，未来字段翻转测试通过。

- [x] **Step 4: 固定停止门**

出现任一情况即停止，不调更多权重：真实资金轨道不优于成交额代理、只在单一月份有效、
只靠删除超过 20% 样本改善、严格成员结果与代理方向相反、负对照同样有效。

### Task 10：研究决策和后续边界

**Files:**
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `requirements/README.md`

- [x] **Step 1: 只记录一个最终研究状态**

状态只能是：

- `rejected_no_incremental_value`
- `research_only_insufficient_point_in_time_coverage`
- `forward_collecting`
- `eligible_for_separate_production_plan`

- [x] **Step 2: 更新长期记忆**

总览只保留当前结论、最短验证命令、三份报告链接和未解决风险；详细逐周期表留在报告，
不复制到 `decisions.md`。

- [x] **Step 3: 守住产品边界**

即使研究通过，本计划也不修改正式策略和页面。下一步必须先生成单独的历史/实时同源接入
计划，明确版本、回滚和前向门，用户确认后再实施。

## 九、计划完成标准

“研究方向完成”不是写完代码或列出几个熟悉股票名称，而是同时得到：

1. 2026 年 3-7 月所有市场情绪周期和动态概念周期的可复核边界。
2. 每个概念周期的点火候选、确认龙、龙二、龙三、连续二进三、反包三板、容量核心和补涨。
3. 官方概念指数、真实资金、成交额代理、成员证据和涨停扩散的逐字段来源。
4. 一份证明或否定“资金主线角色能提高正式打板质量”的同日反事实。
5. 清晰的停止结论；证据不足时保持研究，不用报告完成冒充策略有效。

这份计划的第一交付是**找到 3-7 月每个真实周期及其龙头梯队**，第二交付才是判断它是否
解释了当前胜率和收益下降。两者都完成之前，不再讨论正式上线。
