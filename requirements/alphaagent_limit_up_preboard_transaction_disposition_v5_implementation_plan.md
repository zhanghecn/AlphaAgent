# 首板逐笔三态触发 v5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Repository policy forbids `git commit` unless the user explicitly asks, so each task ends with a focused verification checkpoint instead of a commit.

**Goal:** 在不查看 v4 验证标签或账户收益的前提下，把完整逐笔数据中的零分母分钟定义为显式 `causal_no_action`，完成同母池、同账户的 v5 历史反证，并且只有通过全部原收益门后才接入只读前向影子。

**Architecture:** v5 不修改 v4 的九项数值、Logistic、日期切分、阈值搜索、两分钟确认或两仓账户，只修正互相冲突的覆盖合同。每个原始分钟前缀必须唯一归入 `scoreable`、`causal_no_action`、`data_missing`：前者可评分，中者因完整交易带上的冻结公式零分母而禁止动作，后者使研究失败关闭。v4 保持历史拒绝；v5 是新的动作资格版本，不能覆盖或改写 v4 证据。

**Tech Stack:** Python 3.11+、PostgreSQL/SQLAlchemy、pandas、NumPy、scikit-learn、pytest、现有 TDX 不可变逐笔缓存与首板两仓回放。

---

## Frozen Success Contract

- 母池、首板 lane、同股历史质量、support、`>=3%`、尚未首次触板、二进三订单、D+1 官方收盘退出和费用全部复用 v3/v4。
- 特征仍是 v4 的 20 个核心特征加 9 个 `tx_*`；不得回填零值、增加特征、改窗口、改标签或根据验证段调参。
- `scoreable`：同股票日、同完成分钟存在九个有限逐笔值。
- `causal_no_action`：股票日 scope 为 `flow_ready`，但同完成分钟没有九特征行；该前缀保留在审计母板中，不参加拟合、校准或评分，也不得形成动作。
- `data_missing`：股票日不是 `flow_ready`、前缀身份不在冻结 scope、重复分钟、非法九特征或处置无法唯一确定；任一出现即 fail-closed。
- 处置覆盖必须为 `100%`，即 `scoreable + causal_no_action == prefix_count` 且 `data_missing == 0`；历史可评分覆盖预先固定为 `>=95%`。
- 模型仍为股票日等权 `StandardScaler + LogisticRegression(class_weight=None, max_iter=2000, random_state=0)`；拟合/校准/验证仍为 `44/15/30`。
- 验证账户门不降低：原账户身份精度 `>=70%`、可达召回 `>=30%`、胜率不低于同期触板基线 2 个百分点以上、正常与双倍成本复利为正、回撤不差于 `-10%`、PF `>=1.2`、五块至少三块盈利。
- 报告额外披露 `causal_no_action` 与正式触板账户身份的交集，但该交集只作归因，不得反馈修改规则。
- 历史失败归档 `historical_rejected_no_live_promotion`；历史通过也只能进入 `collecting_forward_transaction_overlay`，正式 v9/v15、公开推荐和自动动作保持不变。
- 可靠归档仍要求冻结后至少 60 个真实交易日、30 笔闭合行动、实时可评分覆盖 `>=95%`，以及全部收益、回撤、PF、胜率和五块稳定性门。

### Task 1: 正式归档 v4 覆盖反证

**Files:**
- Modify: `alphaagent/server/services/limit_up/preboard_transaction_trigger_study.py`
- Modify: `tests/alphaagent/test_limit_up_preboard_transaction_trigger_study.py`
- Modify: `memory/06_backtests/limit_up_preboard_transaction_trigger_v4_20260720.md`
- Modify: `memory/06_backtests/limit_up_preboard_transaction_trigger_v4_20260720.json`

- [x] **Step 1: 为缺失前缀输出精确身份和原因类别**

`join_transaction_features()` 必须输出 `missing_prefixes`、`missing_feature_minute_count` 和 `invalid_feature_value_count`，不得只报百分比。

- [x] **Step 2: 用冻结指纹复核 17 个缺口**

只读重取缺口涉及的 14 个股票日；接受归因的前提是所有新指纹等于缓存指纹且 scope 仍为 `flow_ready`。固定证据为 17/17 均是 `price_move_1m_zero + absolute_price_path_zero`。

- [x] **Step 3: 覆盖门失败归档为历史拒绝**

覆盖失败返回：

```python
{
    "status": "ready_historical_rejected",
    "decision": "historical_rejected_no_live_promotion",
    "model_evaluation_status": "not_run_fail_closed_coverage",
}
```

Markdown 不得把未运行模型显示为 0 信号或 0 笔成交。

- [x] **Step 4: 生成最终 v4 Markdown/JSON 并验证**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_transaction_trigger_study.py \
  tests/alphaagent/test_limit_up_preboard_transaction_trigger_model.py -q
docker compose run --rm -T --no-deps \
  -v "$PWD:/workspace:ro" \
  -v "$PWD/memory/06_backtests:/workspace/memory/06_backtests:rw" \
  -w /workspace -e PYTHONPATH=/workspace:/app/third_party/akshare \
  --entrypoint python alphaagent-api \
  -m alphaagent.server.services.limit_up.preboard_transaction_trigger_study \
  --sessions 89 --format both \
  --output memory/06_backtests/limit_up_preboard_transaction_trigger_v4_20260720
```

Expected: `ready_historical_rejected`，962/962 scope，22804/22821 可评分，17 个缺口，正式策略修改为 `False`。

### Task 2: 建立三态处置合同

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_transaction_disposition.py`
- Create: `tests/alphaagent/test_limit_up_preboard_transaction_disposition.py`

- [x] **Step 1: 写三态互斥与完备测试**

测试输入包含一个完整九特征分钟、一个 `flow_ready` 但无特征分钟、一个非完整 scope；断言分别得到 `scoreable`、`causal_no_action`、`data_missing`，且每个前缀只有一个状态。

```python
assert [row["transaction_disposition"] for row in rows] == [
    "scoreable",
    "causal_no_action",
    "data_missing",
]
```

- [x] **Step 2: 实现纯处置连接**

公开函数固定为：

```python
def classify_transaction_prefixes(
    prefix_rows: Sequence[Mapping[str, object]],
    feature_rows: Sequence[Mapping[str, object]],
    *,
    ready_pairs: set[tuple[str, date]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    ...
```

重复特征键抛出 `ValueError`；非法特征值只能为 `data_missing`，不能伪装成 `causal_no_action`。

- [x] **Step 3: 固定覆盖门**

验收函数要求 `disposition_coverage_pct == 100.0`、`data_missing_prefix_count == 0`、`scoreable_prefix_pct >= 95.0`；边界 `94.9999` 必须失败，`95.0` 必须通过。

- [x] **Step 4: 运行处置单测**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_transaction_disposition.py -q
```

Expected: 全部通过；v4 join 行为和报告不变。

### Task 3: 完成 v5 同账户历史反证

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_transaction_disposition_study.py`
- Create: `tests/alphaagent/test_limit_up_preboard_transaction_disposition_study.py`
- Create: `memory/06_backtests/limit_up_preboard_transaction_disposition_v5_20260720.md`
- Create: `memory/06_backtests/limit_up_preboard_transaction_disposition_v5_20260720.json`

- [ ] **Step 1: 写 v5 覆盖和验收测试**

断言 scope 不完整、处置不足 100%、存在 `data_missing`、可评分低于 95% 或任一原账户门失败时拒绝；`causal_no_action` 本身不能触发拒绝，也不能形成模型输入。

- [ ] **Step 2: 复用冻结 v4 模型而不改数值**

只把 `scoreable` 行传给现有 `fit_transaction_trigger_model()` 和 `score_transaction_trigger_rows()`；模型特征版本与九项顺序必须和 v4 相同。`causal_no_action` 行只进入母板与归因。

- [ ] **Step 3: 同源并列回放**

复用 v4 的正式订单、二进三订单、同刻竞争、两分钟确认、每日两次、保守成交和正常/双倍成本账户。报告并列触板基线、v3 和 v5，且复现 v3 指纹 `dad05e19169d9b24`、`0fa5bf1592cbe59c` 与阈值 `0.15`。

- [ ] **Step 4: 输出无动作归因**

至少输出：总 `causal_no_action` 数、验证段数量、与正式候选身份交集、与原两仓实际成交身份交集；不得依据交集结果修改合同。

- [ ] **Step 5: 连续运行两次并比较指纹**

Run:

```bash
docker compose run --rm -T --no-deps \
  -v "$PWD:/workspace:ro" \
  -v "$PWD/memory/06_backtests:/workspace/memory/06_backtests:rw" \
  -w /workspace -e PYTHONPATH=/workspace:/app/third_party/akshare \
  --entrypoint python alphaagent-api \
  -m alphaagent.server.services.limit_up.preboard_transaction_disposition_study \
  --sessions 89 --format both \
  --output memory/06_backtests/limit_up_preboard_transaction_disposition_v5_20260720
```

Expected: 两次日期、母池、处置、模型、阈值、信号和账户指纹相同；历史门失败则停止，历史门通过才执行 Task 4。

### Task 4: 历史通过后接入只读前向影子

**Files:**
- Modify only after historical PASS: `alphaagent/server/services/limit_up/radar_validation.py`
- Modify only after historical PASS: `alphaagent/server/services/limit_up/radar_observation_repository.py`
- Modify only after historical PASS: `tests/alphaagent/test_limit_up_radar_validation.py`
- Modify only after historical PASS: `tests/alphaagent/test_limit_up_radar_observation_repository.py`

- [ ] **Step 1: 保存三态和同源截止分钟**

雷达只增加 `transaction_disposition`、特征版本、源截止分钟、年龄、九特征与 v5 分数；`causal_no_action` 分数必须为 `None`。

- [ ] **Step 2: 保持正式隔离**

所有 v5 字段保持 `none_research_only`，不得进入 v15 正式得分、排序、公开推荐或自动动作；逐字段快照回归必须证明正式响应不变。

- [ ] **Step 3: 验证实时同源和失败关闭**

同一组截至完成分钟的逐笔经历史与实时归一化后九特征、处置完全相同；陈旧、跨日、分钟未结束和部分获取失败只关闭对应 v5 评分。

- [ ] **Step 4: 运行正式回归**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_radar_validation.py \
  tests/alphaagent/test_limit_up_radar_observation_repository.py \
  tests/alphaagent/test_limit_up_live.py -q
```

Expected: 全部通过，正式 v9/v15 行为和响应不变。

### Task 5: 可靠前向归档

**Files:**
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [ ] **Step 1: 建立冻结前向基线**

保存 v5 日期、数据、处置、模型、阈值与账户指纹；首次影子数据之前不得再改算法。

- [ ] **Step 2: 按 D+1 追加闭合结果**

未达到至少 60 个真实交易日和 30 笔闭合行动时，状态只能是 `collecting_forward_transaction_overlay`。

- [ ] **Step 3: 执行可靠门**

同时要求实时可评分覆盖 `>=95%`、正常和双倍成本正收益、回撤不差于 `-10%`、PF `>=1.2`、胜率不比同期触板基线低超过 2 个百分点、五个连续前向块至少三个盈利。

- [ ] **Step 4: 归档或拒绝**

全部通过才写 `reliable_forward_validated`；任一失败写前向拒绝并另立新版本，不得回改 v5。正式版本升级必须单独立项。

## Self-Review

- Spec coverage：v4 反证、三态定义、覆盖与评分分离、同账户历史反证、实时隔离和可靠前向门均有任务。
- Leakage control：v5 合同冻结于任何 v4/v5 标签、阈值、信号或账户收益被查看之前；已查看的只有无标签逐笔输入完整性与零分母原因。
- Type consistency：统一使用 `scoreable`、`causal_no_action`、`data_missing` 和 `collecting_forward_transaction_overlay`。
- Scope：不修改九特征数值、v3/v4 冻结模型、正式 v9/v15、`vnpy/` 或官方 examples；不 commit、不 push。
- Placeholder scan：无 TBD/TODO；历史失败、历史通过、前向收集和可靠归档均有明确终态。
