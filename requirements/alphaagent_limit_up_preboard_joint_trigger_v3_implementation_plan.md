# 首板提前联合触发 v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Repository policy forbids `git commit` unless the user explicitly asks, so each task ends with a focused verification checkpoint instead of a commit.

**Goal:** 在不修改正式 `limit-up-scheduled-v9 / limit-up-live-v15` 的前提下，建立可复算、因果、直接面向“短时触板且提前价 D+1 盈利”的首板提前触发研究合同，并接入只读前向雷达验证。

**Architecture:** 先把现有一分钟前缀构建从平方级重复计算改为单次线性扫描，保留逐字段行为一致。v3 不再相乘两个嵌套事件的未校准概率，而用一个自然基准率、股票日等权的 Logistic 直接预测联合行动标签；同刻竞争、两分钟确认、每日最多两次行动和正式两仓现金回放保持不变。历史 89 日只作已查看历史反证，任何历史通过都只允许研究影子；可靠性只能由冻结后的新前向数据门证明。

**Tech Stack:** Python 3.11、pandas、NumPy、scikit-learn、SQLAlchemy、pytest、现有 AlphaAgent 打板现金账本与雷达观察表。

---

## Success Contract

- 研究母池仍是所有涨幅 `>=3%`、尚未首次触板、通过当前首板 lane、成熟同股 D+1/联合率及 support 门的主板股票分钟前缀。
- 准备标签只表示未来 5 分钟是否进入正式首板触板候选，不下单。
- 行动标签固定为：未来 3 分钟进入正式首板触板候选，且按该前缀下一分钟可成交价到 D+1 官方收盘的完整费用净收益 `>0`。
- 行动模型直接拟合上述联合标签，不再计算 `P(identity) * P(touch within 3m)`。
- 模型只读拟合日期；阈值只读校准日期；验证日期的标签、D+1 收益或最终封板字段发生变化时，模型指纹和阈值必须不变。
- 历史报告必须同时给出：联合标签精度、3 分钟真实触板率、正式候选身份精度、原两仓账户身份精度、两仓胜率/复利/回撤/PF、双倍成本和保守成交。
- 历史验收至少要求：原账户身份精度 `>=70%`、可达召回 `>=30%`、两仓 D+1 胜率不低于触板基线 2 个百分点以上、正常/双倍成本复利为正、回撤不差于 `-10%`、五个验证块至少三个为正。
- 即使历史门通过，正式策略仍不改变；前向审查前保持 `execution_effect=none_research_only`。
- 前向输入必须是同交易日、新鲜、非陈旧雷达帧；动态概念、资金流、并发冲板和报价新鲜度只做前向分层，禁止回填历史核心模型。
- 可靠结论需要冻结后的前向门达到既有合同，并通过账户收益、稳定性、成本与执行覆盖检查；未达到时只能标记 collecting 或 historical rejected。

### Task 1: 线性化一分钟 lane 前缀构建

**Files:**
- Modify: `alphaagent/server/services/limit_up/preboard_strategy_replay.py`
- Modify: `tests/alphaagent/test_limit_up_preboard_strategy_replay.py`

- [x] **Step 1: 写失败测试，证明同一股票日只构建一次完整 lane 前缀序列**

```python
def test_strategy_prefix_builds_lane_path_once(monkeypatch) -> None:
    calls = 0
    original = replay_module._build_lane_prefixes

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(replay_module, "_build_lane_prefixes", counted)
    rows = build_strategy_prefix_rows(
        _manifest(touched=False, sealed=False, d1_close=10.5),
        _feature_row(),
        _bars(),
        financial_index={},
    )

    assert rows
    assert calls == 1
```

- [x] **Step 2: 运行测试确认旧实现失败**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_strategy_replay.py::test_strategy_prefix_builds_lane_path_once -q
```

Expected: FAIL，旧实现对多个前缀重复调用 `_build_lane_prefixes`。

- [x] **Step 3: 一次构建完整 lane 序列并按当前 index 读取**

在 `build_strategy_prefix_rows()` 完成 `previous_close` 校验后增加：

```python
lane_prefixes = _build_lane_prefixes(
    ordered,
    previous_close=previous_close,
    bar_minutes=bar_minutes,
)
```

把循环内的：

```python
lane_prefix = build_lane_prefix(
    ordered,
    index,
    previous_close=previous_close,
    bar_minutes=bar_minutes,
)
```

替换为：

```python
lane_prefix = lane_prefixes[index]
```

- [x] **Step 4: 验证行为与因果测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_strategy_replay.py \
  tests/alphaagent/test_limit_up_preboard_hazard_model.py -q
```

Expected: 全部通过；未来栏变更仍不能改变当前 lane 前缀。

### Task 2: 建立直接联合标签和自然基准率模型

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_joint_trigger_model.py`
- Create: `tests/alphaagent/test_limit_up_preboard_joint_trigger_model.py`

- [x] **Step 1: 写联合标签测试**

测试必须覆盖四种情况：3 分钟内正式触板且净收益为正为行动正例；触板但亏损、盈利但不触板、3 分钟外触板均为负例；5 分钟准备标签与行动标签相互独立。

```python
assert labeled[0][ACTION_TARGET_FIELD] is True
assert labeled[1][ACTION_TARGET_FIELD] is False
assert labeled[2][ACTION_TARGET_FIELD] is False
assert labeled[3][ACTION_TARGET_FIELD] is False
```

- [x] **Step 2: 实现固定字段和标签函数**

```python
PREPARE_TARGET_FIELD = "formal_touch_within_5m"
ACTION_TARGET_FIELD = "profitable_formal_touch_within_3m"
ACTION_SCORE_FIELD = "joint_action_probability"

def attach_joint_trigger_targets(rows, formal_orders):
    labeled = attach_hazard_targets(rows, formal_orders, horizons=(3, 5))
    return [
        {
            **row,
            ACTION_TARGET_FIELD: bool(
                row.get("formal_touch_within_3m") is True
                and _number(row.get("net_return_pct")) is not None
                and float(row["net_return_pct"]) > 0
            ),
        }
        for row in labeled
    ]
```

- [x] **Step 3: 写拟合隔离、股票日等权和批量评分测试**

测试要求：验证日期标签变化不改变模型指纹；同一股票日一分钟行数翻倍不改变该股票日总权重；`score_joint_trigger_rows()` 只调用一次 pipeline 的批量 `predict_proba`。

- [x] **Step 4: 实现自然基准率 Logistic**

使用现有 `COMPETING_FEATURE_NAMES`，避免在已查看验证段继续挖特征。Pipeline 固定为 `StandardScaler()` 加 `LogisticRegression(class_weight=None, max_iter=2000, random_state=0)`；样本权重仍令每个股票日总权重为 1。模型报告保存缩放参数、系数、截距、拟合日期和 SHA-256 指纹。

- [x] **Step 5: 实现批量评分**

一次构造全部有限特征矩阵，一次调用 `predict_proba`，再把概率按原行顺序写回；不得在逐行循环中调用 sklearn。

- [x] **Step 6: 运行模型测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_joint_trigger_model.py -q
```

Expected: 全部通过。

### Task 3: 冻结联合阈值和同刻账户选择

**Files:**
- Modify: `alphaagent/server/services/limit_up/preboard_joint_trigger_model.py`
- Modify: `tests/alphaagent/test_limit_up_preboard_joint_trigger_model.py`

- [x] **Step 1: 写校准隔离测试**

阈值只允许读取校准日期；修改验证日期概率、标签和净收益后，阈值、校准选择数和校准指标必须完全一致。

- [x] **Step 2: 实现固定阈值网格与两分钟确认**

阈值网格固定为 `0.05..0.95`，步长 `0.05`。每个阈值继续复用同分钟横截面排序、连续两分钟确认、同股同日首次行动和每日最多两只。至少 10 个校准行动才可选；按联合标签 `F0.5`、联合精度、阈值依次降序冻结。

- [x] **Step 3: 报告概率校准而不伪称置信度**

校准段和验证段分别输出 Brier score、按预测概率十分位的实际联合发生率，以及 action score 的 P25/中位/P75。自然基准率 Logistic 输出可称 `estimated_probability`，但只有前向校准通过后页面才允许显示百分比；历史页面继续显示“研究分数”。

- [x] **Step 4: 运行模型与选择测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_joint_trigger_model.py \
  tests/alphaagent/test_limit_up_preboard_competing_risk_model.py -q
```

Expected: 全部通过，v2 指纹和行为不变。

### Task 4: 构建 v3 历史反证与同账户报告

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_joint_trigger_study.py`
- Create: `tests/alphaagent/test_limit_up_preboard_joint_trigger_study.py`
- Create after deterministic evaluation: `memory/06_backtests/limit_up_preboard_joint_trigger_v3_20260720.md`
- Create after deterministic evaluation: `memory/06_backtests/limit_up_preboard_joint_trigger_v3_20260720.json`

- [x] **Step 1: 写基线一致性和账户合同测试**

测试构造首板行动加未变二进三，确认两仓、费用、D+1 官方收盘、双倍成本和保守成交均复用正式现金账本。基线任一字段不一致时报告必须 fail-closed。

- [x] **Step 2: 写完整验收门测试**

验收门逐项覆盖 Success Contract，尤其不能用候选身份精度替代原账户身份精度，也不能用全推荐日等权复利替代两仓现金复利。

- [x] **Step 3: 实现 44/15/30 冻结时间切分**

复用 v2 的 89 日范围和完整一分钟覆盖。模型拟合只用前 44 日，阈值只用中间 15 日，后 30 日固定分成 5 个连续 6 日块；报告明确标记后 30 日已经查看，只能作历史反证。

- [x] **Step 4: 输出逐笔错误账本**

每个提前成交标记为：与原触板账户相同、正式候选但原账户未买、正式身份误报。漏掉的原账户首板按无合格前缀、分数未过阈值、未连续确认、同刻竞争失败、每日行动槽已满、账户仓位阻断分类。

- [x] **Step 5: 加入性能和数据指纹**

报告保存母池股票日数、前缀数、日期指纹、模型指纹、阈值、分钟/日线一致性、面板构建秒数和模型评分秒数。相同数据库输入连续运行两次时，日期/模型/阈值/账户摘要必须一致。

- [x] **Step 6: 运行历史评估并归档**

Run:

```bash
docker compose run --rm -T --no-deps \
  -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace:/app/third_party/akshare \
  --entrypoint python alphaagent-research \
  -m alphaagent.server.services.limit_up.preboard_joint_trigger_study \
  --sessions 89 --format both \
  --output memory/06_backtests/limit_up_preboard_joint_trigger_v3_20260720
```

Expected: Markdown/JSON 内容同源，正式 v9/v15 未改变；未通过任一收益门则状态为 `historical_rejected_no_live_promotion`。

### Task 5: 接入只读前向雷达评分

**Files:**
- Modify: `alphaagent/server/services/limit_up/preboard_joint_trigger_study.py`
- Modify: `alphaagent/server/services/limit_up/radar_validation.py`
- Modify: `tests/alphaagent/test_limit_up_preboard_joint_trigger_study.py`
- Modify: `tests/alphaagent/test_limit_up_radar_validation.py`

- [x] **Step 1: 写新鲜度与同源日失败测试**

陈旧帧、报价时间缺失、`source_trade_date` 非当日、分钟路径未完成到当前时点时均不得评分。动态概念或资金字段为空不得删除基础观察，只在 overlay 覆盖中记缺失。

- [x] **Step 2: 实现冻结模型前向重放**

读取 `limit_up_radar_frames/observations`，每个股票/完成分钟只保留第一条新鲜帧；补齐当日前缀后用 v3 冻结参数批量评分，按同一分钟候选重新计算横截面特征，再执行同一确认和每日行动上限。

- [x] **Step 3: 分离准备与行动状态**

5 分钟准备分数只产生 `research_prepare`；联合 3 分钟行动过冻结阈值才产生 `research_action`。二者都固定 `execution_effect=none_research_only`，不得进入 `actionable_recommendations`、正式两仓或公开推荐排序。

- [x] **Step 4: 输出前向动态分层**

按概念 1/3/5 分钟加速度、个股/板块资金、同刻冲板数量、报价年龄和金银手指状态分层，只报告覆盖与结果，不依据当前样本改核心模型或阈值。

- [x] **Step 5: 运行前向测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_joint_trigger_study.py \
  tests/alphaagent/test_limit_up_radar_validation.py \
  tests/alphaagent/test_limit_up_radar_observation_repository.py \
  tests/alphaagent/test_limit_up_live.py -q
```

Expected: 全部通过；正式推荐响应不新增 v3 买入项。

### Task 6: 完整验证与项目记忆更新

**Files:**
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/09_decisions/decisions.md`

- [ ] **Step 1: 运行全部打板相关回归**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up*.py -q
```

- [ ] **Step 2: 运行编译和差异检查**

```bash
uv run python -m compileall -q alphaagent/server/services/limit_up tests/alphaagent
git diff --check
```

- [ ] **Step 3: 验证运行态采集**

在首个真实交易时段后确认雷达帧增长、`quote_observed_at` 非空、源交易日为当日、非陈旧帧约 15 秒采样；概念字段缺失不能阻断基础帧。

- [ ] **Step 4: 更新当前结论**

三个 memory 文件只保留当前状态、复算命令、归档链接和未满足的前向门。若历史拒绝，明确写明具体失败位置；若历史通过，也只能写 `forward_shadow_collecting`，不得宣称可靠或修改正式 v9/v15。

## Self-Review

- Spec coverage：性能、联合标签、目标隔离、同刻竞争、账户回放、历史反证、前向雷达、正式隔离和归档均有对应任务。
- Placeholder scan：无 TBD/TODO；每项修改均有确切文件、函数、规则和验证命令。
- Type consistency：统一使用 `signal_date`、`formal_touch_within_3m/5m`、`profitable_formal_touch_within_3m`、`joint_action_probability`；报告账户字段沿用现有 cash ledger 输出。
- Scope：不修改 `vnpy/`、官方 examples、正式 v9/v15 或公开推荐合同；不执行 commit/push。
