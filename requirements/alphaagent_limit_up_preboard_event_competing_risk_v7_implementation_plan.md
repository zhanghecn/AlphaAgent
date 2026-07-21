# 首板事件竞争风险 v7 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Repository policy forbids `git commit` unless the user explicitly asks, so each task ends with a focused verification checkpoint instead of a commit.

**Goal:** 在完全复用正式首板母池与两仓账户的前提下，把“未来三分钟是否发生触板事件”和“同刻哪只候选最可能触板”分开建模，验证事件序列与横截面竞争能否产生可成交、可复现且可前向验收的触板前动作。

**Architecture:** v7 只读取 v5 已冻结的 962 个逐笔股票日和 22,821 个一分钟前缀，不使用覆盖不足的历史概念、板块资金或金银手指代理。第一层按交易日和完成分钟聚合候选池事件序列，用日期等权 Logistic 估计未来三分钟是否至少出现一个正式首板触板；第二层只在包含正负候选的事件风险集中，用确定性 LightGBM LambdaRank 学习同刻候选顺序。动作只允许选择每分钟排名第一的候选，并由第一层概率通过冻结校准门；历史结果仅是已查看开发样本，只有冻结后新增实时帧达到前向门槛才可称可靠。

**Tech Stack:** Python 3.11+、NumPy、scikit-learn、LightGBM、pytest、现有 TDX 一分钟/逐笔缓存、v5/v6 母池与两仓现金回放。

**Historical result (2026-07-20):** `historical_rejected_no_live_promotion`。三次 89 日完整回放除 `performance` 外逐字段一致；校准段满足至少 10 次选择时最好仅 `4/10=40%`，未达到 70% 硬门。Task 4 因历史失败未启动，正式 v9/v15 保持不变。

---

## Frozen Success Contract

- 数据母池、正式盈利质量门、support、涨幅 `>=3%`、尚未首次触板、二进三订单、D+1 官方收盘退出、费用和两仓现金账户全部保持不变。
- 历史输入继续要求 `scoreable + causal_no_action == prefix_count`、`data_missing == 0`、962/962 scope `flow_ready`、可评分覆盖 `>=95%`；不能删除最终未触板负样本。
- 历史点时概念强度只有 4 日、板块资金快照只有 6 日、3% 雷达有效观察只有 2 日，因此这些字段不得进入 v7 历史模型、阈值或验收。它们只登记为新前向扩展层。
- 市场事件特征只能由当前分钟和更早的合格候选前缀生成；候选事件特征只能由同股当前/更早前缀生成。未来行增删不得改变更早特征。
- 市场目标固定为同一完成分钟可见候选中是否存在 `formal_touch_within_3m=True`；候选排序标签仍为当前行自身的 `formal_touch_within_3m`，不得用同股当天稍后正例回填当前行。
- 市场模型固定为 `StandardScaler + LogisticRegression(class_weight=None, max_iter=2000, random_state=0)`；每个交易日的全部分钟总权重为 1。
- 候选模型固定为 `LGBMRanker(objective="lambdarank", n_estimators=80, learning_rate=0.03, num_leaves=7, max_depth=3, min_child_samples=20, reg_alpha=1, reg_lambda=5, colsample_bytree=0.8, random_state=0, deterministic=True, force_col_wise=True, n_jobs=1)`；训练只使用同时含正负候选的分钟风险集，按 `(signal_date, signal_time)` 排序并传入精确 group sizes。
- 每分钟只允许候选排名第一者进入动作校准；动作分数只使用市场三分钟事件概率。候选排名只解决“买谁”，不得反向改变“是否现在买”。
- 动作确认固定为 1 个完整分钟；同股票日只取首次动作；同分钟稳定排序依次使用候选 ranker 分数、正式基础 rank、股票代码；每日最多 2 个首板动作。
- 校准阈值固定为 `0.05..0.95`、步长 `0.05`。合法阈值必须在 15 日校准段至少选择 10 个股票日，当前行三分钟触板精度 `>=70%`；在合法阈值中依次最大化可达召回、精度、阈值。无合法阈值即历史拒绝，不生成验证首板动作。
- 验证账户硬门不降低：至少 30 个动作、正式候选身份精度 `>=70%`、原两仓身份精度 `>=70%`、可达召回 `>=30%`、D+1 胜率不低于触板基线 2 个百分点以上、正常/双倍成本复利为正、回撤不差于 `-10%`、PF `>=1.2`、五块至少三块盈利。
- 历史后 30 日已经被查看；即使历史通过，也只能冻结 `forward_shadow_candidate`。可靠归档还必须在冻结后新增的至少 60 个完整交易日、至少 60 个闭合动作和至少 40 个动作日上，通过胜率 `>=60%`、平均净收益 `>=1%`、PF `>=1.5`、双倍成本 PF `>=1.2`、回撤不差于 `-15%`、五块至少四块盈利，并保持原账户身份精度 `>=70%`。
- Oracle 仍只作理论上界，不能进入模型、阈值、特征选择或验收。正式 `limit-up-scheduled-v9 / limit-up-live-v15`、公开推荐、排序和自动动作保持不变。

### Task 1: 冻结事件序列特征合同

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_event_risk_model.py`
- Create: `tests/alphaagent/test_limit_up_preboard_event_risk_model.py`

- [x] **Step 1: 写因果事件特征测试**

构造两个交易日、三个分钟、三只候选，断言市场活跃数、新进入数、近板数、上涨动量比例和候选可见年龄只读取当前及过去行；追加未来分钟后，更早特征逐字段不变。

- [x] **Step 2: 写市场批次与日期权重测试**

断言每个 `(signal_date, signal_time)` 只产生一个市场训练样本，目标为该分钟任一当前行三分钟触板；同一交易日全部市场样本权重和为 1，缺少完整特征时显式排除并计数。

- [x] **Step 3: 写排名风险集测试**

断言只保留同分钟同时包含正负标签的风险集，行顺序与 group sizes 稳定；单候选、全正和全负分钟不能进入 LambdaRank 拟合，但仍可进入市场事件模型。

- [x] **Step 4: 实现冻结特征和双模型接口**

实现事件特征生成、市场 Logistic、候选 LambdaRank、模型报告、不可变参数指纹和冻结参数重放；所有特征名、训练日期、模型参数和 booster 文本均进入 SHA-256 指纹。

- [x] **Step 5: 运行模型单测**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_preboard_event_risk_model.py -q
```

Expected: 全部通过；重复拟合模型和分数指纹一致；未来行不改变过去特征。

### Task 2: 冻结动作选择与阈值门

**Files:**
- Modify: `alphaagent/server/services/limit_up/preboard_event_risk_model.py`
- Modify: `tests/alphaagent/test_limit_up_preboard_event_risk_model.py`

- [x] **Step 1: 写同分钟 Top1 选择测试**

同分钟两只候选都超过市场阈值时，只选择 ranker 分数最高者；分数相同按正式 rank 和股票代码稳定选择。下一分钟不得重复选择同股票日，每日总动作不超过 2。

- [x] **Step 2: 写 70% 校准硬门测试**

构造阈值 `0.30` 有 10 选 7、阈值 `0.35` 有 9 选 8，只能选择 `0.30`；若所有达到 10 个选择的阈值精度不足 70%，状态固定为 `calibration_precision_gate_failed`。

- [x] **Step 3: 写无模型/无阈值失败关闭测试**

市场模型或 ranker 未就绪时不得产生动作；校准失败时使用独立执行哨兵，不把哨兵写成合法冻结阈值。

- [x] **Step 4: 实现动作与校准**

动作行保存市场概率、候选 ranker 分数、同刻候选数、排名和事件特征版本；不得读取正式账户未来身份。

- [x] **Step 5: 运行模型与 v6 回归**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_event_risk_model.py \
  tests/alphaagent/test_limit_up_preboard_transaction_touch_model.py -q
```

Expected: 全部通过；v6 行为不变。

### Task 3: 完成 v7 同账户历史反证

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_event_risk_study.py`
- Create: `tests/alphaagent/test_limit_up_preboard_event_risk_study.py`
- Create after execution: `memory/06_backtests/limit_up_preboard_event_risk_v7_20260720.md`
- Create after execution: `memory/06_backtests/limit_up_preboard_event_risk_v7_20260720.json`

- [x] **Step 1: 写研究组装与泄漏隔离测试**

断言标签在特征冻结后附加；市场/候选模型只读取 fit 日期；阈值只读取 calibration 日期；validation 与 oracle 字段不能改变模型、阈值和动作政策指纹。

- [x] **Step 2: 复用 v6 数据和账户合同**

通过现有 candidate analysis builder 复用 pair manifest、逐笔三态、基线 parity、二进三订单、下一分钟开盘成交、保守成交、D+1 退出及费用；v7 仅替换首板动作来源。

- [x] **Step 3: 输出必要归因和消融**

报告市场事件 AUC/校准、排序 Top1/Top2 命中率、选择精度/召回、账户身份、matched/formal-only/false-positive 损益、遗漏原因，以及“仅市场门 + 原 rank”和“市场门 + LambdaRank”的冻结消融；消融只解释，不参与主模型阈值选择。

- [x] **Step 4: 执行两次确定性研究**

Run:

```bash
docker compose run --rm -T --no-deps \
  -v "$PWD:/workspace:ro" \
  -v "$PWD/memory/06_backtests:/workspace/memory/06_backtests:rw" \
  -w /workspace -e PYTHONPATH=/workspace:/app/third_party/akshare \
  --entrypoint python alphaagent-api \
  -m alphaagent.server.services.limit_up.preboard_event_risk_study \
  --sessions 89 --format both \
  --output memory/06_backtests/limit_up_preboard_event_risk_v7_20260720
```

Expected: 两次除 `performance` 外的整份 JSON 一致；历史门失败则归档拒绝，通过才进入 Task 4。

### Task 4: 历史通过后冻结前向只读合同

**Status:** 未进入。历史校准门失败，按冻结合同禁止创建 v7 前向接入或修改正式实时链路。

**Files:**
- Create only after historical PASS: `alphaagent/server/services/limit_up/preboard_event_risk_forward.py`
- Create only after historical PASS: `tests/alphaagent/test_limit_up_preboard_event_risk_forward.py`
- Modify only after historical PASS: `alphaagent/server/services/limit_up/radar_observation_repository.py`
- Modify only after historical PASS: `alphaagent/server/services/limit_up/live_service.py`

- [ ] **Step 1: 保存冻结模型身份与逐帧输入**

每个研究帧保存 v7 pipeline hash、特征版本、输入 cutoff、市场概率、候选 ranker 分数和排序；所有字段固定 `execution_effect=none_research_only`。

- [ ] **Step 2: 接入当日逐笔但保持失败关闭**

仅对当前合格候选调用已验证的 TDX `get_transaction_data(...)`，聚合完整分钟；逐笔过旧、分页不完整或报价时间不一致时只记录 `causal_no_action`，不得回填最近值。

- [ ] **Step 3: 验证正式隔离**

同一行情输入下，接入前后正式 v15 推荐列表、顺序、`action`、`portfolio_selected` 和自动动作逐字段相同；研究状态只能出现在内部前向账本。

- [ ] **Step 4: 启动冻结后前向累计**

冻结日期后的新交易日才能计入验收；冻结前 2 日雷达、已查看历史和补写帧全部排除。

### Task 5: 可靠归档与上线决定

**Files:**
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify if forward eligible: `memory/06_backtests/limit_up_preboard_event_risk_v7_20260720.md`

- [x] **Step 1: 跑完整回归和静态检查**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_preboard_event_risk_model.py tests/alphaagent/test_limit_up_preboard_event_risk_study.py -q
uv run python -m compileall -q alphaagent/server/services/limit_up
git diff --check
```

Expected: 全部通过，无格式错误。

- [x] **Step 2: 归档当前事实**

报告必须区分 `historical_rejected`、`forward_shadow_collecting`、`forward_rejected` 和 `forward_reliable`；不得把开发样本、oracle 或覆盖不足的概念代理写成正式成绩。

- [x] **Step 3: 只有前向硬门全通过才允许提出晋级**

达到冻结后 60 个完整交易日和全部可靠性门后，才可把状态改为 `forward_reliable_candidate_for_live_review`；正式推荐仍需单独用户决策，不自动上线。

本轮历史门已失败，状态保持 `not_promoted_historical_rejected`，未提出晋级。
