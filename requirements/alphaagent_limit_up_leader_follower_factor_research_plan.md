# AlphaAgent 龙头到龙二龙三映射因子研究 Implementation Plan

> **归档结果：** 本计划已完成。正式收益口径报告为
> `memory/06_backtests/limit_up_leader_follower_factor_formal_discovery_2026_03_07.md`；
> 静态成交额承载规则的独立历史状态为 `historical_proxy_rejected`，不再维护空前向账本。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This repository forbids commits unless the user explicitly requests one, so tasks end with verification checkpoints.

**Goal:** 归档 2026 年 3-7 月动态概念龙头研究，并从相同五个月中归纳“可确认龙头 -> 同概念指数响应 -> 龙二/龙三接力 -> 正式打板 D+1 质量”的完整因子族，冻结后再进入完整 806 日历史和自然前向验证。

**Architecture:** 第一层把既有 100 日、22 个市场周期和 1,668 个概念周期固化为发现样本；第二层在每个概念周期内生成龙头确认事件和事后龙二/龙三映射标签；第三层只用决策日前已知的龙头、概念指数、成交额扩张、梯队和角色信息连接正式候选。事后映射只回答规律，点时特征才允许评价打板胜率；本计划不修改正式策略。

**Tech Stack:** Python 3.11、pandas、现有 PostgreSQL 只读数据、AlphaAgent 动态概念研究模块、pytest、Markdown 研究证据。

---

## 完成口径

1. 以后查询打板研究时，从 `memory/06_backtests/README.md` 的“打板续研入口”恢复当前事实、证据和下一步，不依赖聊天记录。
2. 对每个龙头确认事件分别记录点火日、确认日、概念指数/成交额/梯队响应、同概念龙二龙三及其 1/3/5 日涨幅。
3. 事后选出的龙二龙三只作 `realized` 标签；正式候选 D 日只能读取 D-1 及更早确认的映射特征。
4. 因子报告必须覆盖龙头质量、概念响应、资金承载、梯队扩散、跟随角色、映射时延、周期阶段和背离风险，不只搜索一个总分。
5. 本阶段只做 3-7 月因子发现与冻结。只有因子定义全部归纳完毕，才运行完整 806 日 expanding walk-forward 和新前向验证。
6. 主要质量口径为规则保留后的全部正式推荐，目标胜率 `>=60%`；样本数、月份覆盖和保留率作为独立可信度指标，不再以两仓结果作为验收条件。

## Task 0：归档第一阶段研究并建立固定续研入口

**Files:**
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `requirements/alphaagent_dynamic_concept_leader_cycle_research_plan.md`

- [x] **Step 1: 将 3-7 月第一阶段标记为已归档**

记录固定事实：100 个交易日、22 个市场周期、1,668 个动态概念周期、171 个 Top3 主线周期；D-1 主线和真实净流入没有形成稳定正向因子，`turnover>=0.80` 是待复核候选而非正式结论。

- [x] **Step 2: 写入新的当前研究问题**

长期记忆只保留以下续研链：

```text
已确认龙头 -> 同概念指数/成交额/梯队响应 -> 龙二龙三映射
-> 点时正式候选 -> 全量 D+1 胜率 -> 806 日与自然前向
```

- [x] **Step 3: 运行记忆一致性检查**

Run:

```bash
rg -n "打板续研入口|第一阶段归档|leader.follower|>=60" \
  memory/06_backtests/README.md memory/09_decisions/decisions.md \
  requirements/alphaagent_dynamic_concept_leader_cycle_research_plan.md
```

Expected: 三个入口都指向本计划；旧停止结论只否定上一组日级主线规则，不再写成整个研究终止。

## Task 1：锁定龙头确认与跟随映射合同

**Files:**
- Create: `alphaagent/server/services/limit_up/leader_follower_factor.py`
- Create: `tests/alphaagent/test_limit_up_leader_follower_factor.py`

- [x] **Step 1: 写确认时点失败测试**

```python
def test_confirmed_leader_becomes_tradeable_only_after_confirmation_close() -> None:
    events = build_leader_confirmation_events(_bundle(), _trade_dates())
    assert events.iloc[0]["ignition_date"] == date(2026, 7, 1)
    assert events.iloc[0]["confirmation_date"] == date(2026, 7, 2)
    assert events.iloc[0]["first_usable_date"] == date(2026, 7, 3)
```

- [x] **Step 2: 写未来标签隔离测试**

```python
def test_realized_follower_return_cannot_enter_candidate_features() -> None:
    with pytest.raises(ValueError, match="future feature"):
        validate_leader_follower_feature_names(["prior_leader_age", "realized_follower_3d_return"])
```

- [x] **Step 3: 实现固定事件合同**

公共函数固定为：

```python
build_leader_confirmation_events(bundle, trade_dates) -> pd.DataFrame
build_realized_follower_mappings(inputs, bundle, leader_events) -> pd.DataFrame
attach_leader_follower_features(candidate_frame, leader_events) -> pd.DataFrame
evaluate_leader_follower_factors(frame) -> dict[str, object]
```

确认事件必须由 D 日 `ignition_candidate` 在 D+1 完成有效二板生成；`first_usable_date` 固定为确认日后的下一市场交易日。

- [x] **Step 4: 运行合同测试**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_leader_follower_factor.py -k 'confirmation or future'`

Expected: 确认日收盘前不可使用；未来映射收益不能进入 `prior_*` 特征。

## Task 2：生成龙头到同概念龙二龙三的事后映射

**Files:**
- Modify: `alphaagent/server/services/limit_up/leader_follower_factor.py`
- Modify: `tests/alphaagent/test_limit_up_leader_follower_factor.py`

- [x] **Step 1: 写同周期和排除龙头测试**

构造一个概念周期内的确认龙、龙二、龙三和另一个概念的强势股。断言映射只保留相同 `concept_cycle_id`，排除龙头自身，并保留龙二/龙三并列。

- [x] **Step 2: 计算映射涨幅标签**

每条映射输出：

```text
leader_symbol / sector_id / concept_cycle_id
ignition_date / confirmation_date / follower_first_date / delay_sessions
follower_symbol / role_realized
response_day_change_pct
forward_1d_close_return_pct
forward_3d_close_return_pct
forward_5d_close_return_pct
membership_evidence_level
```

涨幅从跟随角色首次出现日收盘向后计算；数据不足保留 `None`，不得填 0。

- [x] **Step 3: 保存概念响应分量**

每个确认事件同时保存确认日前后的 `index_strength_delta`、`turnover_strength_delta`、`ladder_strength_delta`、`unique_follower_delta`、周期阶段和资金证据。概念名称不进入规则。

- [x] **Step 4: 运行映射测试**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_leader_follower_factor.py -k mapping`

Expected: 映射不跨概念周期、不包含龙头自身，并能区分缺失后续行情和真实 0% 涨幅。

## Task 3：把可交易映射特征连接到正式全量候选

**Files:**
- Modify: `alphaagent/server/services/limit_up/leader_follower_factor.py`
- Modify: `tests/alphaagent/test_limit_up_leader_follower_factor.py`

- [x] **Step 1: 写 D-1 边界测试**

正式候选 D 日只允许匹配 `first_usable_date <= D` 的龙头事件。修改 D 日收盘后的概念响应和龙二龙三最终收益，断言候选特征完全不变。

- [x] **Step 2: 生成五组独立因子**

```text
leader:       已确认龙数量、最近龙头板位、确认后年龄
concept:      指数强度及变化、周期阶段、非背离状态
capacity:     概念成交额扩张、真实资金可用/确认状态
diffusion:    梯队强度、排除龙头后的扩散及变化
follower:     候选上一日是否龙二/龙三/容量核心、映射时延
```

不先加权为一个总分；每组原始字段和缺失状态都保留。

- [x] **Step 3: 预注册组合切片**

至少评价：单独确认龙、确认龙+指数增强、确认龙+成交额扩张、确认龙+梯队扩散、确认龙+龙二龙三、确认龙+容量核心、确认龙+非背离，以及 `turnover>=0.80` 与上述映射的交集。

- [x] **Step 4: 运行候选测试**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_leader_follower_factor.py -k candidate`

Expected: 输出的是规则保留后的全部正式候选；无任何两仓字段参与因子评价。

## Task 4：归纳 3-7 月完整因子并生成发现报告

**Files:**
- Modify: `alphaagent/server/services/limit_up/leader_follower_factor.py`
- Create: `memory/06_backtests/limit_up_leader_follower_factor_formal_discovery_2026_03_07.md`
- Modify: `memory/06_backtests/README.md`

- [x] **Step 1: 增加研究 CLI**

```bash
docker compose --profile research run --rm -T --no-deps \
  -v "$PWD:/workspace" -w /workspace \
  alphaagent-research python -m \
  alphaagent.server.services.limit_up.leader_follower_factor \
  --start 2026-03-01 --end 2026-07-24 \
  --output memory/06_backtests/limit_up_leader_follower_factor_formal_discovery_2026_03_07.md
```

- [x] **Step 2: 报告事件映射**

逐个确认龙列出同概念指数响应、龙二龙三、映射时延和 1/3/5 日涨幅；分别汇总严格点时成员与 3-6 月幸存者代理。

- [x] **Step 3: 报告因子全集**

每个单因子和预注册组合报告全量候选数、胜率、均值、复利、回撤、硬亏、最大连亏、逐月结果及 3-5 月发现/6-7 月时间留出。达到 `>=60%` 但少于 30 笔或少于 3 个月时必须标记小样本。

- [x] **Step 4: 冻结待验证因子**

报告末尾只保留同时具备点时可用性、方向一致性和可解释机制的因子；未通过的龙头身份、主线排名和净流入规则继续归档为反例。

- [x] **Step 5: 运行定向和全量回归**

Run:

```bash
uv run --group server pytest -q \
  tests/alphaagent/test_limit_up_leader_follower_factor.py \
  tests/alphaagent/test_limit_up_capital_mainline_*.py
uv run python -m compileall -q alphaagent/server/services/limit_up
git diff --check
```

Expected: 全部通过；正式版本、页面和推荐动作没有变化。

## Task 5：因子冻结后验证完整 806 日和自然前向

**Files:**
- Modify: `alphaagent/server/services/limit_up/leader_follower_factor.py`
- Create: `memory/06_backtests/limit_up_leader_follower_factor_806d_validation.md`

- [x] **Step 1: 冻结因子名称、方向和阈值**

3-7 月报告生成 SHA256 指纹；完整历史不得新增因子、改变缺失值含义或按验证收益改阈值。

- [x] **Step 2: 运行完整历史 expanding walk-forward**

全量推荐目标为胜率 `>=60%`，并报告每段样本数、月份覆盖、均值、回撤和硬亏。概念成员为代理的区间必须单列证据等级。

- [ ] **Step 3: 启动严格自然前向**

使用完整点时成员和真实保存的资金证据，至少累计 60 个交易日、30 个闭合正式候选和两个情绪阶段。3-7 月发现结果不得写入前向特征。

状态：历史验证已经否决冻结规则，不再建立或维护 0 样本占位账本；如未来提出新的独立
假设，应由实际保存的未见快照生成新账本，不能复用本规则晋级。

- [x] **Step 4: 决定是否另写生产接入计划**

只有完整历史和自然前向均达到 `>=60%` 且收益/风险不反向，才允许新建历史实时同源接入计划；否则继续研究或拒绝，不修改正式策略。

决定：`historical_proxy_rejected`，不新建生产接入计划。完整 806 日为 71 笔、
`69.0141%`，但发现期前独立历史仅 29 笔、`55.1724%`，未通过样本数和胜率门。
