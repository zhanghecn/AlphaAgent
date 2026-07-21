# 首板逐笔触板时序 v6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Repository policy forbids `git commit` unless the user explicitly asks, so each task ends with a focused verification checkpoint instead of a commit.

**Goal:** 复用正式首板高质量过滤，只用逐笔与分钟因果特征预测候选在 3 分钟内触板的时序，替代被 v3/v5 反证的稀疏“触板且 D+1 盈利”联合模型，并检验能否在同一两仓账户中复现触板基线身份、胜率和复利。

**Architecture:** v6 保留 v5 三态数据合同和 29 个冻结特征。5 分钟模型只产生提前观察状态；动作模型标签改为 `formal_touch_within_3m`，因为 D+1 质量已由正式母池过滤承担。动作允许单个完整分钟确认以覆盖十秒级拉升；阈值只能从 15 日校准段中选择满足至少 10 个信号且 3 分钟触板精度不低于 70% 的候选，随后在已经查看的 30 日上做开发期反证。另用未来身份 oracle 计算当前母池、买点和账户合同的可达上界，但 oracle 不参与验收或实时评分。

**Tech Stack:** Python 3.11+、NumPy、scikit-learn、pytest、现有 TDX 逐笔缓存、v3/v5 母池与两仓现金回放。

---

## Frozen Success Contract

- 数据必须为 v5 三态：`scoreable + causal_no_action == prefix_count`、`data_missing == 0`、scope `100% flow_ready`、可评分覆盖 `>=95%`。
- 母池、正式盈利质量门、support、`>=3%`、尚未首次触板、二进三订单、D+1 官方收盘退出和费用不变。
- 特征固定为 v4/v5 的 20 个核心特征加 9 个逐笔特征，不增删、不回填、不按验证结果调符号或窗口。
- 准备标签固定为 `formal_touch_within_5m`；动作标签固定为 `formal_touch_within_3m`，不得包含 D+1 收益或原账户是否成交。
- 两个模型仍为股票日等权 `StandardScaler + LogisticRegression(class_weight=None, max_iter=2000, random_state=0)`。
- 动作确认固定为 1 个完成分钟；同股票日只取首次合格动作，同分钟按动作概率、正式基础排序、股票代码稳定排序；每日最多 2 个首板动作。
- 校准阈值候选仍为 `0.05..0.95`、步长 `0.05`；合格阈值必须在 15 日校准段至少选择 10 个股票日且 `formal_touch_within_3m` 精度 `>=70%`。在合格阈值中依次最大化可达召回、精度、阈值；没有合格阈值即拒绝。
- 验证账户门不降低：至少 30 个动作、正式候选身份精度 `>=70%`、原两仓身份精度 `>=70%`、可达召回 `>=30%`、胜率不低于触板基线 2 个百分点以上、正常/双倍成本复利为正、回撤不差于 `-10%`、PF `>=1.2`、五块至少三块盈利。
- 最近 30 日已被 v3/v5 查看，v6 只能称 `viewed_development_counterexample`；即使历史通过也只能冻结前向影子，不能称可靠。
- 正式 `limit-up-scheduled-v9 / limit-up-live-v15`、公开推荐、排序和自动动作不变。

### Task 1: 完成 v5 重复性归档

**Files:**
- Modify: `memory/06_backtests/limit_up_preboard_transaction_disposition_v5_20260720.md`
- Modify: `memory/06_backtests/limit_up_preboard_transaction_disposition_v5_20260720.json`

- [x] **Step 1: 连续复跑并比较核心指纹**

必须比较 `pair_manifest`、`transaction_inputs`、`transaction_dispositions`、日期切分、v3/v5 动作策略和 v3/v5 验证账户指纹；性能耗时不参与一致性。

- [x] **Step 2: 固定 v5 拒绝结论**

Expected: 30 个验证动作，原账户身份精度 `30%`，21 笔成交，胜率 `42.8571%`，复利 `-16.7762%`，回撤 `-22.675%`，PF `0.6607`，状态 `historical_rejected_no_live_promotion`。

### Task 2: 固定触板时序模型与阈值

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_transaction_touch_model.py`
- Create: `tests/alphaagent/test_limit_up_preboard_transaction_touch_model.py`

- [x] **Step 1: 写动作标签与单帧选择测试**

断言动作模型只读取 `formal_touch_within_3m`；连续两分钟不是必要条件；同股票日多次越线只选择第一次；同分钟竞争按概率降序稳定选择。

- [x] **Step 2: 写校准精度硬门测试**

构造阈值 `0.30` 有 10 选 7、阈值 `0.35` 有 9 选 8；只能选择 `0.30`。若所有达到 10 个选择的阈值精度低于 70%，状态必须为 `calibration_precision_gate_failed`。

- [x] **Step 3: 实现冻结模型接口**

复用 `fit_transaction_trigger_model()` 和 `score_transaction_trigger_rows()`，动作分数字段固定为 `transaction_touch_3m_probability`，准备分数字段固定为 `transaction_prepare_5m_probability`。

- [x] **Step 4: 运行模型测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_transaction_touch_model.py \
  tests/alphaagent/test_limit_up_preboard_transaction_trigger_model.py -q
```

Expected: 全部通过，v4/v5 模型指纹不变。

### Task 3: 建立可达 oracle 与 v6 同账户回放

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_transaction_touch_study.py`
- Create: `tests/alphaagent/test_limit_up_preboard_transaction_touch_study.py`
- Create: `memory/06_backtests/limit_up_preboard_transaction_touch_v6_20260720.md`
- Create: `memory/06_backtests/limit_up_preboard_transaction_touch_v6_20260720.json`

- [x] **Step 1: 写 oracle 不进入验收测试**

oracle 只选择验证段原账户成交身份中存在 `formal_touch_within_3m` 可评分前缀的股票日；报告可达召回和账户上界，但 `acceptance` 不得读取任何 `oracle_*` 字段。

- [x] **Step 2: 实现准备与动作并列评分**

准备模型拟合 `formal_touch_within_5m`，动作模型拟合 `formal_touch_within_3m`；实际动作只使用动作模型与校准阈值，准备模型只进入报告和后续只读预警。

- [x] **Step 3: 实现单帧动作订单**

复用 `_joint_order()` 的下一分钟开盘成交和保守成交定义，二进三订单原样合并；动作选择 `confirmation_minutes=1`、每日最多 2 个。

- [x] **Step 4: 输出时序与账户归因**

报告 3 分钟触板精度/召回、触板领先分钟、最终封板率、D+1 结果、matched/formal-only/false-positive 三类账户损益、遗漏原账户原因和 oracle 上界。

- [x] **Step 5: 执行两次确定性研究**

Run:

```bash
docker compose run --rm -T --no-deps \
  -v "$PWD:/workspace:ro" \
  -v "$PWD/memory/06_backtests:/workspace/memory/06_backtests:rw" \
  -w /workspace -e PYTHONPATH=/workspace:/app/third_party/akshare \
  --entrypoint python alphaagent-api \
  -m alphaagent.server.services.limit_up.preboard_transaction_touch_study \
  --sessions 89 --format both \
  --output memory/06_backtests/limit_up_preboard_transaction_touch_v6_20260720
```

Expected: 两次数据、模型、阈值、动作、oracle 和账户指纹完全相同；历史门失败即归档拒绝，通过才进入 Task 4。

Result: 两次复跑除耗时外整份 JSON 一致；校准精度门失败，状态固定为
`historical_rejected_no_live_promotion`，因此按计划不进入 Task 4/5。

### Task 4: 历史通过后冻结前向双层状态

**Files:**
- Modify only after historical PASS: `alphaagent/server/services/limit_up/radar_validation.py`
- Modify only after historical PASS: `alphaagent/server/services/limit_up/radar_observation_repository.py`
- Modify only after historical PASS: `tests/alphaagent/test_limit_up_radar_validation.py`
- Modify only after historical PASS: `tests/alphaagent/test_limit_up_radar_observation_repository.py`

- [ ] **Step 1: 保存只读准备状态**

5 分钟准备分数只改变 `research_prepare` 诊断字段，不进入正式排序或动作。

- [ ] **Step 2: 保存只读动作状态**

3 分钟动作分数、阈值、完成分钟和逐笔年龄写入研究观察；`execution_effect` 固定 `none_research_only`。

- [ ] **Step 3: 验证正式隔离与实时同源**

同一完成分钟历史/实时九特征和两层分数一致；陈旧、跨日、未完成分钟或数据错误只关闭 v6，正式 v15 响应逐字段不变。

- [ ] **Step 4: 运行雷达回归**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_radar_validation.py \
  tests/alphaagent/test_limit_up_radar_observation_repository.py \
  tests/alphaagent/test_limit_up_live.py -q
```

### Task 5: 可靠前向归档

**Files:**
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [ ] **Step 1: 冻结首次真实观察前的全部指纹**

保存数据、三态、模型、阈值、动作政策与账户指纹，之后不得原位修改 v6。

- [ ] **Step 2: 累计至少 60 个真实交易日和 30 笔闭合动作**

不足时状态只能是 `collecting_forward_transaction_overlay`，不得用历史 oracle 或已查看 30 日补足。

- [ ] **Step 3: 执行全部可靠门**

要求实时可评分覆盖 `>=95%`、正常与双倍成本正收益、回撤不差于 `-10%`、PF `>=1.2`、胜率不低于同期触板基线 2 个百分点以上、五个连续前向块至少三个盈利。

- [ ] **Step 4: 归档或拒绝**

全部通过才写 `reliable_forward_validated`；否则归档前向拒绝并另立新版本，正式版本升级另行评审。

## Self-Review

- Spec coverage：v5 重复性、触板标签、单帧动作、校准硬门、oracle、同账户回放、实时隔离和可靠前向门均有任务。
- Leakage control：v6 参数在 v6 模型或账户结果生成前冻结；已查看 v5 结果只用于更换被证伪的目标与确认机制。最近 30 日明确不再宣称样本外。
- Type consistency：统一使用 `transaction_prepare_5m_probability`、`transaction_touch_3m_probability`、`formal_touch_within_3m` 和 `confirmation_minutes=1`。
- Scope：不修改正式 v9/v15、公开推荐、自动动作、`vnpy/` 或官方 examples；不 commit、不 push。
- Placeholder scan：无 TBD/TODO，阈值失败、历史失败、历史通过和前向可靠均有明确终态。
