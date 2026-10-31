# 一接二 j12-v2.0 综合最终版重构实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 一接二只落地一套综合最终规则，统一日线严格突破+9%入场、开盘涨停剔除、失败板T+1和纯断板尾盘退出，不再把研究拆成高尾组、宽基组或多套并列结果。

**Architecture:** `contracts.py` 只保存 F1—F10 规则与文案；`execution.py` 统一入场价格；`pool.py` 负责实时候选及必要的开盘窗口复核；`backtest.py` 用同一套 hpr 静态字段回放。报告保留兼容字段并增加分年收益合计、trim3和收益结构。前端只展示这一套综合最终版。旧报告和研究文件保留，但不作为并列方案展示。

**Tech Stack:** Python 3.13、pandas、SQLAlchemy/PostgreSQL、pytest、React/TypeScript/Vite。

---

## 冻结研究口径

- 入场：昨日孤立首板，二板日开盘非涨停，日线最高价严格突破+9%即买；开盘已高于触发价则按开盘价。
- 退出：买入日未封则下一交易日退出；封住则持有至断板尾盘；一字跌停顺延；15个交易日兜底。
- 最终只使用以下十条规则的并集，同票同日去重：
  - F1：`pre5_pct < -15` × `foundation_body ∈ [-5,-3)`。
  - F2：`b1_turn ∈ [3,5)` × `foundation_amplitude ≥ 12`。
  - F3：`today_open ∈ [7.5,8.5)` × 阴地基 × `foundation_pose == 站线上`。
  - F4：`ma_state == '---'` × `foundation_body < -5` × `b1_gap ∈ [8,12)`。
  - F5：阴地基 × `b1_gap ∈ [5,8)` × `pre20_pct ≥ 30`。
  - F6：`today_open ∈ [8.5,9.5)` × `b1_open < 0` × `b1_break60 == False`。
  - F7：`foundation_body < -5` × `foundation_vol_rel5 ∈ [1.2,1.5)` × `b1_turn_change ∈ [0,2)`。
  - F8：`b1_turn ∈ [5,8)` × `b1_vol_rel5 ∈ [0.5,0.8)` × `pre3_pct ∈ [-15,-8)`。
  - F9：`ma_state == '---'` × `today_open ∈ [7.5,8.5)` × `b1_turn_change ∈ [0,2)`。
  - F10：`dist_h60 ∈ [-10,-8)` × `foundation_body ∈ [5,7)` × `pre3_pct ∈ [5,10)`。
- 研究账本：624笔、胜率64.1026%、均值+4.9280%、中位+2.2119%、trim3 +4.3113%。
- 2021—2026逐年收益均值：+4.1792/+4.6440/+8.2227/+4.6063/+7.2122/+3.3816；各年trim3均为正。
- 2021—2022回放171笔、胜率60.2339%、均值+4.4102%、trim3 +3.3658；月块CI约[+3.62,+6.66]，同月随机p=0.0002；42组邻窗扰动全部通过。
- 分年收益合计是等权逐笔收益求和，不冒充实际组合净值。2026截至10月23日。

### Task 1: 综合规则与入口函数

**Files:**
- Modify: `alphaagent/server/services/first_relay/contracts.py`
- Create: `alphaagent/server/services/first_relay/execution.py`
- Test: `tests/alphaagent/services/first_relay/test_open9_v2.py`

1. 先写失败测试，覆盖 F1—F10 的所有条件、边界和缺失字段；验证版本为 `j12-v2.0`。
2. 实现 `trigger_9pct()`、`open9_entry()`：严格高于+9%的第一个可报价，开盘涨停返回 None，跳空按开盘价，未触及返回 None。
3. `POINTS` 固定为 F1—F10；禁止套用旧贴顶、死水、顶格回避。仅 F3/F6/F9 含开盘窗口，其余规则不得额外添加开盘门槛。
4. 文案只描述综合最终版，不展示高尾组、宽基组或旧 G1/S1。
5. 运行新测试和既有研究测试，并从最终研究账本抽查规则归属。

### Task 2: 实时池与静态字段统一

**Files:**
- Modify: `alphaagent/server/services/first_relay/pool.py`
- Test: `tests/alphaagent/services/first_relay/test_open9_v2.py`

1. 用 `hpr_pool.make_ctx/static_fields` 提供地基、前波、均线和首板字段，避免研究与产品各写一套。
2. `tag_point` 改为综合十条规则的关键字参数；只在规则本身含开盘窗口时复核 `today_open`。
3. 修正 `limit_price` 必须使用首板收盘×1.10，新增 `trigger_price`，保留 `prev_close` 原语义。
4. 修正展示标签传参错位；删除旧 G1/S1 和无依据的旧回避标签。
5. 用合成日线覆盖字段计算、十条规则命中和未命中。

### Task 3: 回测执行与纯断板尾盘

**Files:**
- Modify: `alphaagent/server/services/first_relay/backtest.py`
- Test: `tests/alphaagent/services/first_relay/test_open9_v2.py`

1. 事件改为昨日孤立首板 × 当日最高价突破+9% × 开盘非涨停；不要求后来触板。
2. 买价用 `open9_entry`，失败板最早下一交易日退出，保留T+1和一字跌停顺延。
3. 新增 `_tail_exit`，不继承D+2深开竞价卖；旧 `_e3_exit` 保留供旧研究调用。
4. 回测主收益写入兼容字段 `E3%`，同时明确v2为纯断板尾盘，不与旧E3数字混用。
5. 合成测试覆盖仅过9未触板、封住后断板、炸板次日退出、开盘涨停剔除。

### Task 4: 报告、持久化与 API

**Files:**
- Modify: `alphaagent/server/services/first_relay/backtest.py`
- Modify: `alphaagent/server/services/first_relay/repository.py`
- Modify: `alphaagent/server/services/first_relay/service.py`（若有旧规则/字段依赖）
- Modify: `alphaagent/server/db/schema.py`（仅在确需新增持久字段时）
- Test: `tests/alphaagent/services/first_relay/test_open9_v2.py`

1. 报告分支改 F1—F10，新增 `trim3`、分年等权收益合计和收益结构；收益结构只用于解释，不拆成可选择的策略组。
2. 保持现有API字段兼容；旧 `info_layer` 标签不得冒充最终规则机制。
3. 持久化只保存执行所需新字段，沿用 `ensure_schema_once` 幂等迁移，不手工改生产库。
4. 检查 `j12_pool_entries` 写入与读取字段一致，验证v2规则版本隔离。

### Task 5: 前端规则与报告展示

**Files:**
- Modify: `frontend/src/features/firstRelay/*`
- Modify: `frontend/src/api/firstRelay.ts`（仅文案/类型需要时）

1. 删除 G1/S1、旧阴坑/阳坑、涨停价买入和D+2深开文案。
2. 只展示综合最终版：F1—F10、+9%入场、开盘涨停剔除、纯断板尾盘和统一分年结果。
3. 保持现有页面布局和接口兼容，不新增高尾/宽基切换或并列面板。
4. 运行前端类型检查和相关测试，确保没有旧规则残留。

### Task 6: 全量对账与前瞻验证准备

**Files:**
- Test: `tests/alphaagent/services/first_relay/test_open9_v2.py`
- Research: `量化因子研究/一接二/scripts/j12_final_composite.py`

1. 运行 `pytest tests/alphaagent/services/first_relay tests/alphaagent/test_j12_final_composite.py tests/alphaagent/test_j12_open9_research.py`。
2. 只读全量回放，核对综合最终624笔、胜率64.1026%、均值+4.9280%、trim3 +4.3113%及全部分年结果。
3. 运行独立逐票门禁，确认研究账本与产品回放一致。
4. 未经单独确认，不写生产物化表、不执行EOD、不提交git；上线后只做同一套规则的前瞻记录，不再并列切换研究方案。

---

## 完成判据

- 规则、入口、退出、报告、前端全部使用同一套 j12-v2.0 综合最终版语义。
- 测试全绿；综合最终624笔全量对账一致；最终研究链可复现，历史旧版由Git历史保留。
- 不展示多套并列研究结论，不在未确认时写生产物化表或提交代码。
