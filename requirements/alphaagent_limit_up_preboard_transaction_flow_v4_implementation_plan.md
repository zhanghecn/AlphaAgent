# 首板逐笔资金流提前触发 v4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Repository policy forbids `git commit` unless the user explicitly asks, so each task ends with a focused verification checkpoint instead of a commit.

**Goal:** 在保持正式 `limit-up-scheduled-v9 / limit-up-live-v15` 不变的前提下，用可历史复算且可实时同源获取的 TDX 逐笔成交，验证能否在触板前区分真实上板资金与 v3 的假动能，并把通过历史门的固定算法接入只读前向雷达直至达到可靠归档门。

**Architecture:** TDX 原始逐笔先通过整日成交量、尾页和收盘价门禁，再按成交分钟映射到现有一分钟 K 线的区间结束标签；研究层只消费信号分钟结束时已经发生的成交。不可变数据库缓存保存每个股票日的质量指纹和每个完成分钟的九个预注册特征；v4 在 v3 二十个核心特征后追加九个逐笔特征，仍用股票日等权 Logistic、拟合/校准/验证隔离、同刻竞争和正式两仓现金回放。历史通过也只启用 `none_research_only` 前向影子，可靠归档必须再通过冻结后的真实前向门。

**Tech Stack:** Python 3.11+、PyTDX、PostgreSQL/SQLAlchemy、pandas、NumPy、scikit-learn、pytest、现有 AlphaAgent 雷达与现金账本。

---

## Success Contract

- 母池、首板 lane、同股历史质量门、support 门、`>=3%`、尚未首次触板、二进三通道、两仓和 D+1 官方收盘退出必须与 v3/正式基线一致。
- TDX `buyorsell` 缺少可信公开枚举说明，字段固定命名为 `direction_0/1/2`；代码和报告不得把它们宣传为主动买入或主动卖出。
- 正常连续竞价分钟的逐笔成交分钟 `m` 映射为一分钟 K 线结束标签 `m+1`。`09:31` 合并 `09:25` 竞价与 `09:30`，`11:30` 合并 `11:29` 与 `11:30`；研究动作最晚 `14:30`，不使用 `14:57` 后收盘集合竞价占位 K 线。
- 一个股票日只有同时满足完整分页结束、首笔不晚于 `09:25`、末笔为 `15:00`、逐笔总成交量与权威日线完全一致、收盘价误差不超过 `0.011` 时，才可标记 `flow_ready`。高低价差异单独审计，不得替代成交量完整性。
- 特征集合在首次完整模型运行前固定为：
  `tx_trade_count_acceleration_1m_5m`、
  `tx_max_print_turnover_share_1m`、
  `tx_large_print_turnover_share_1m`、
  `tx_large_print_turnover_share_3m`、
  `tx_direction_01_imbalance_1m`、
  `tx_direction_01_imbalance_3m`、
  `tx_price_move_turnover_imbalance_1m`、
  `tx_price_move_turnover_imbalance_3m`、
  `tx_path_efficiency_1m`。
- `large print` 固定为单笔成交额 `>=1,000,000` 元；所有份额/失衡范围固定在 `[-1,1]` 或 `[0,1]`，成交笔数加速度固定截断到 `[0,10]`，分母为零时该分钟前缀不可评分，不用零值回填。
- v4 模型固定为 v3 二十个核心特征加上述九个特征，`StandardScaler + LogisticRegression(class_weight=None, max_iter=2000, random_state=0)`，每股票日总权重为 1。不得在验证段挑特征、正负号、窗口或阈值。
- 首轮 89 日仍按 `44/15/30`：前 44 日拟合，中 15 日只校准阈值，后 30 日只作已经查看历史的反证。报告必须并列 v3 和 v4，同账户输出身份精度、3 分钟触板率、联合精度、胜率、复利、回撤、PF、双倍成本、保守成交和五个连续块。
- 历史门沿用 v3：原账户身份精度 `>=70%`、可达召回 `>=30%`、胜率不比触板基线低超过 2 个百分点、正常/双倍成本复利为正、最大回撤不差于 `-10%`、五块至少三块盈利；另要求逐笔特征覆盖 `100%` 且 v4 正常账户 PF `>=1.2`。
- 89 日历史未通过即归档 `historical_rejected_no_live_promotion`，不得为验证段改特征。通过也只能冻结前向影子；正式 v9/v15、公开推荐排序和自动动作不变。
- 可靠归档要求冻结后至少 60 个真实交易日、30 笔闭合 v4 行动、逐笔输入可评分覆盖不低于 `95%`，并同时通过正常/双倍成本正收益、回撤不差于 `-10%`、PF `>=1.2`、胜率不比同期间触板基线低超过 2 个百分点、五个连续前向块至少三块盈利。未满足时状态只能是 `collecting_forward_transaction_overlay`。

### Task 1: 固化逐笔分页、完整性与分钟对齐

**Files:**
- Modify: `alphaagent/server/services/data_providers/tdx_transaction_history.py`
- Modify: `tests/alphaagent/test_tdx_transaction_history.py`

- [x] **Step 1: 写分页终止和尾页测试**

构造两页 `2000 + 37` 行，断言 `_fetch_history_pages()` 在短页后停止；构造每页都满且达到上限的响应，质量状态必须是 `truncated`，不得标记 `flow_ready`。

- [x] **Step 2: 写完整日资金流质量测试**

测试分别覆盖：成交量和收盘完全一致为 `flow_ready`；成交量不一致、末笔不是 `15:00`、请求被最大页数截断均为 `invalid`；日线高低价轻微不一致只进入审计字段，不改变资金流完整性。

- [x] **Step 3: 写分钟结束标签测试**

输入 `09:25/09:30/09:31/11:29/11:30/13:00/14:29` 成交，断言输出结束标签依次归入 `09:31/09:32/11:30/11:30/13:01/14:30`；任何 `14:30` 信号不得读取 `14:30` 原始成交分钟。

- [x] **Step 4: 实现中性方向、价格移动和大单聚合**

每个结束分钟保存 OHLC、成交量/额、笔数、最大单笔额、百万大单额、`direction_0/1/2` 量额、相邻逐笔上涨/下跌/平盘成交额和绝对价格路径；不得根据 `buyorsell` 猜测买卖语义。

- [x] **Step 5: 运行数据源测试**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_tdx_transaction_history.py -q
```

Expected: 全部通过；现有一分钟数据源行为不变。

### Task 2: 建立不可变逐笔特征缓存

**Files:**
- Modify: `alphaagent/server/db/schema.py`
- Create: `alphaagent/server/services/limit_up/preboard_transaction_repository.py`
- Create: `tests/alphaagent/test_limit_up_preboard_transaction_repository.py`

- [x] **Step 1: 写原子保存和指纹冲突测试**

同一 `vt_symbol/trade_date/feature_version` 首次保存 scope 与分钟特征必须原子成功；相同输入指纹重放幂等；不同指纹不得静默覆盖，返回 `fingerprint_conflict`。

- [x] **Step 2: 增加 scope 与分钟特征表**

`limit_up_transaction_feature_scopes` 保存来源、页数、原始/有效笔数、首末时刻、逐笔/日线量价审计、输入 SHA-256、状态和特征行数；`limit_up_transaction_features` 以股票、日期、结束分钟、版本为联合主键，JSONB 保存九个有限数值及输入指纹。

- [x] **Step 3: 实现只读覆盖和批量加载**

提供 `load_transaction_feature_coverage(pairs, version)` 和 `load_transaction_features(pairs, version)`；覆盖必须按精确股票日集合计算，不能用日期范围内其他股票替代。

- [x] **Step 4: 运行仓储测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_transaction_repository.py \
  tests/alphaagent/test_tdx_transaction_history.py -q
```

Expected: 全部通过，`schema.ensure_schema_once()` 可在现有数据库幂等建表。

### Task 3: 构建九个因果逐笔特征和有界同步任务

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_transaction_features.py`
- Create: `alphaagent/server/services/limit_up/preboard_transaction_data.py`
- Create: `tests/alphaagent/test_limit_up_preboard_transaction_features.py`
- Create: `tests/alphaagent/test_limit_up_preboard_transaction_data.py`
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `tests/alphaagent/test_data_sync_schedule.py`

- [ ] **Step 1: 写九特征精确公式测试**

用三分钟手工成交构造断言每个份额、方向失衡、价格移动失衡、路径效率和五分钟笔数加速度；未来一分钟成交变化不得改变当前结束分钟特征。

- [ ] **Step 2: 实现固定特征函数**

`build_transaction_feature_rows(aligned_minutes)` 只返回 `10:00..11:30 / 13:01..14:30` 的完成分钟；滚动窗口均向后，特征缺分母时整行标为不可评分。

- [ ] **Step 3: 写单连接批量抓取测试**

模拟三个股票日，断言一次 `_connect_tdx()`、逐股票日分页、逐日质量门和逐对原子保存；一个失败不覆盖已成功股票日，重跑只请求缺口或失败 scope。

- [ ] **Step 4: 实现手动有界数据任务**

新增 `sync_limit_up_preboard_transaction_features`，只消费 v3 共用规则真实通过过的股票日，默认 `session_count=89`、每批最多 500 对；不加入 19:00/21:30 默认计划，不扫描全市场，不修改推荐。

- [ ] **Step 5: 运行特征与调度测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_transaction_features.py \
  tests/alphaagent/test_data_sync_schedule.py -q
```

Expected: 全部通过；任务仅在显式调用时写研究缓存。

### Task 4: 建立固定 v4 模型与严格隔离

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_transaction_trigger_model.py`
- Create: `tests/alphaagent/test_limit_up_preboard_transaction_trigger_model.py`

- [ ] **Step 1: 写特征顺序、缺失关闭和股票日等权测试**

断言特征顺序固定为 v3 二十项加九项；任一逐笔特征缺失或非有限即不评分；同股票日分钟前缀翻倍后总权重仍为 1。

- [ ] **Step 2: 写拟合/校准/验证隔离测试**

修改校准或验证日期的标签、收益、最终封板字段，模型指纹必须不变；修改验证日期概率不得改变只读校准日期冻结的阈值。

- [ ] **Step 3: 实现固定 Logistic 和模型指纹**

模型保存特征版本、九特征名称、缩放均值/尺度、系数、截距、拟合日期和 SHA-256；一次矩阵批量评分，禁止逐行调用 sklearn。

- [ ] **Step 4: 运行模型测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_transaction_trigger_model.py \
  tests/alphaagent/test_limit_up_preboard_joint_trigger_model.py -q
```

Expected: 全部通过；v3 指纹和行为不变。

### Task 5: 运行 89 日 v4 历史反证并归档

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_transaction_trigger_study.py`
- Create: `tests/alphaagent/test_limit_up_preboard_transaction_trigger_study.py`
- Create after deterministic evaluation: `memory/06_backtests/limit_up_preboard_transaction_trigger_v4_20260720.md`
- Create after deterministic evaluation: `memory/06_backtests/limit_up_preboard_transaction_trigger_v4_20260720.json`

- [ ] **Step 1: 写覆盖、基线一致和全部验收门测试**

逐笔覆盖不足 `100%`、任一 scope 非 `flow_ready`、基线不一致或任一收益/稳定性门失败都必须 fail-closed；候选级 AUC/精度不得替代两仓现金结果。

- [ ] **Step 2: 实现 v3/v4 同源并列回放**

同一个前缀面板、正式订单、二进三订单、日线和交易日历同时运行 v3 与 v4；只替换首板提前分数，账户到达顺序、两分钟确认、每日两次和费用不变。

- [ ] **Step 3: 输出逐笔增量归因**

报告逐类列出 v3 假动能被 v4 拦截、v3 原账户身份被保留/错杀、v4 新增误报；九个特征只按拟合/校准/验证分段报告分布，不据验证段改规则。

- [ ] **Step 4: 执行两次确定性研究**

Run:

```bash
docker compose run --rm -T --no-deps \
  -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONPATH=/workspace:/app/third_party/akshare \
  --entrypoint python alphaagent-research \
  -m alphaagent.server.services.limit_up.preboard_transaction_trigger_study \
  --sessions 89 --format both \
  --output memory/06_backtests/limit_up_preboard_transaction_trigger_v4_20260720
```

Expected: 两次日期、数据、模型、阈值和账户指纹相同。未通过写 `historical_rejected_no_live_promotion`；通过只写 `historical_pass_forward_shadow_only`。

### Task 6: 接入同源实时逐笔只读评分

**Files:**
- Modify: `alphaagent/server/services/data_providers/tdx_transaction_history.py`
- Modify: `alphaagent/server/services/limit_up/radar_validation.py`
- Modify: `alphaagent/server/services/limit_up/radar_observation_repository.py`
- Modify: `tests/alphaagent/test_limit_up_radar_validation.py`
- Modify: `tests/alphaagent/test_limit_up_radar_observation_repository.py`

- [ ] **Step 1: 写实时与历史同源特征测试**

同一组截至完成分钟的模拟逐笔，经历史接口和当前交易接口归一化后九特征必须逐字段相同；报价或逐笔晚于 60 秒、分钟未完成、日期不同均不得评分。

- [ ] **Step 2: 保存逐笔来源时刻和 v4 研究状态**

雷达观察只增加诊断字段：逐笔特征版本、源截止分钟、年龄、质量状态、九特征和 v4 分数；`research_prepare/research_action` 继续 `none_research_only`，不得进入正式推荐或账户。

- [ ] **Step 3: 保持失败关闭与扫描预算**

每个股票/完成分钟只获取一次并缓存；单次逐笔预算超时或部分股票失败时只关闭对应 v4 评分，不阻断 v15 正式扫描。报告输出可评分覆盖和延迟分布。

- [ ] **Step 4: 运行雷达与正式推荐回归**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_radar_validation.py \
  tests/alphaagent/test_limit_up_radar_observation_repository.py \
  tests/alphaagent/test_limit_up_live.py -q
```

Expected: 全部通过；正式响应、排序和自动动作不变。

### Task 7: 可靠性门、运行态验证与项目记忆

**Files:**
- Modify: `requirements/alphaagent_limit_up_preboard_joint_trigger_v3_implementation_plan.md`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [ ] **Step 1: 删除不可达的 300 笔前向快捷分支**

前向审查合同固定为至少 60 个交易日且至少 30 笔闭合；不保留在 90 日、每日两次上限下不可达的“300 笔可提前审查”描述。此修改不降低正常门槛。

- [ ] **Step 2: 运行全部打板回归和静态检查**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up*.py -q
uv run python -m compileall -q alphaagent/server/services/limit_up alphaagent/server/services/data_providers tests/alphaagent
git diff --check
```

Expected: 全部通过。

- [ ] **Step 3: 在真实交易时段核验采集**

连续核对至少一个完整交易日：雷达约 15 秒采样、报价和逐笔同交易日、逐笔截止分钟不晚于完成分钟、非陈旧比例、逐笔可评分覆盖，以及正式 v15 结果未变化。

- [ ] **Step 4: 按冻结前向门持续结算**

每个 D+1 日线到齐后只追加闭合结果；未达到 60 日/30 笔及收益稳定性门时维持 `collecting_forward_transaction_overlay`。达到全部门后才归档 `reliable_forward_validated`，并另立正式版本升级需求，不能就地改 v9/v15。

- [ ] **Step 5: 更新当前事实**

memory 只保留当前版本、复算命令、历史/前向证据链接、数据边界和未满足门禁；不复制长表，不把已查看历史称为新样本外。

## Self-Review

- Spec coverage：逐笔来源真实性、因果对齐、中性方向语义、不可变缓存、九特征、模型隔离、同账户回放、历史反证、实时同源、正式隔离和可靠前向门均有对应任务。
- Placeholder scan：无 TBD/TODO；历史失败和通过均有明确终态，前向可靠状态有精确门槛。
- Type consistency：统一使用 `flow_ready`、`limit-up-preboard-transaction-flow-v1`、九个 `tx_*` 字段和 `collecting_forward_transaction_overlay`；v4 只追加特征，不重命名 v3 标签或账户字段。
- Scope：不修改 `vnpy/`、官方 examples、正式 v9/v15 或公开推荐；不执行 commit/push。
