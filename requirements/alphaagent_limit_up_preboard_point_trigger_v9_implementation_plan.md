# 首板秒级点时触发 v9 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Repository policy forbids `git commit` unless the user explicitly asks, so each task ends with a focused verification checkpoint instead of a commit.

**Goal:** 在不修改正式 `limit-up-scheduled-v9 / limit-up-live-v15` 的前提下，使用新积累的 10 秒快速雷达、约 30 秒全市场补充行情、点时概念、资金和市场状态，预测当前合格 Top1 是否会在未来 60 秒进入正式首板触板路径，并在冻结后的 60 个完整交易日证明触板身份、D+1 胜率和两仓复利可靠。

**Architecture:** v9 是全新前向合同，不继承已被历史否证的 v8 阈值或动作。第一层预测未来 60 秒是否出现正式首板事件，第二层只在同刻合格候选中排序事件身份，第三层使用走步样本外 Top1 直接校准是否行动；所有模型只消费当帧及过去帧。原始雷达继续服务正式 v15，研究层只保存不可执行的特征、模型版本、评分、延迟成交代理和 D+1 结果。

**Tech Stack:** Python 3.11+、pandas、NumPy、scikit-learn、LightGBM、SQLAlchemy、PostgreSQL、现有亚分钟雷达/概念/资金仓储、pytest、专用 `alphaagent-research` Compose 运行时。

**Frozen start:** `eligible_after=2026-07-20`。2026-07-20 全日的 677 帧、204,425 条观察只用于采集和代码联调，不进入拟合、校准、阈值或验证；全日相邻帧 P50/P90 为 `18.2815/30.1340` 秒。正式窗口为 522 帧、165,064 条观察，边界计入后的扫描缺口 P50/P90/max 为 `18.1853/27.7388/105.8185` 秒，报价年龄 P50/P90 为 `11.9950/25.4601` 秒；P90 尚未通过 `<=20` 秒完整日硬门。

**Why a new contract:** v8 在 89 日完整一分钟历史中，满足至少 10 个校准动作时最好仅 `5/13=38.4615%`，没有合法 70% 阈值。历史已证明提前价格不是主要瓶颈，未解决的是点时事件时钟和股票身份；继续调整同一组分钟特征属于已查看样本过拟合。

---

## Frozen Success Contract

- `>=3%` 只表示进入观察分母，不是买入。候选必须仍为沪深主板首板、非 ST/退市风险、尚未正式触板、通过当时已经确定且不会在未来 60 秒改变的 lane 静态质量门、同股成熟 D+1 样本 `>=5`、联合率 `>=30%`。support、entry quality、正式市场门和动态 lane blocker 是待预测特征，不是提前母池硬门；允许的动态 lane blocker 必须与正式 v15 的 7 个动态代码逐项一致，任何静态 lane blocker 继续排除。
- 研究原始输入只来自保存时真实存在的 `limit_up_radar_frames`、`limit_up_radar_observations` 和其点时来源。禁止用日终资金、后来概念状态、未来触板、D+1 或正式账户结果覆盖旧帧。
- 一个完整研究日只统计正式买入窗口 `10:00:00..11:30:00`、`13:00:00..14:30:00`。上午和下午必须分别满足：非 stale 帧比例 `>=98%`、报价年龄 `0..60s` 比例 `>=98%`、扫描间隔 P90 `<=20s`、最大扫描缺口 `<=60s`、报价覆盖率 P10 `>=90%`、市场状态非空率 `>=98%`、合格候选概念加速度非空率 `>=95%`；日级指标取两个窗口中的较差值，禁止用稳定窗口稀释故障窗口。每帧还必须保存一个合法 `capture_runtime_fingerprint`，完整日内只能有一个非空值；缺失、非法或盘中实现漂移均不进入任何阶段。
- 资金字段必须保存点时来源交易日。只在 `flow_trade_date == frame.trade_date` 时使用数值；否则数值置缺失并增加 missing flag。资金非空率不作为删行门，避免把供应商缺失变成未来可用性筛选。
- 标签只在连续可观测的未来 `(t, t+60s]` 内附加。事件标签为是否首次出现正式 v15 首板 `buy_now`；身份标签为当前股票是否是该窗口内最早正式首板身份。物理触板、最终封板、原两仓身份和 D+1 只作独立诊断与收益验收。动作同帧冻结的正式 `portfolio/portfolio_selected` 最多两只只证明正式输入完整：已观察到的空名单是完整空输入，正式组合字段缺失则不得保存动作，但尚未触板的提前候选本来就不会在同帧成为正式 `buy_now`，因此不能用它判断原账户身份。每个完整日必须冻结随后真实到达的首板和二进三正式 `buy_now` 订单、到达顺序、涨停价、来源帧及指纹；正式账户和提前账户从空仓开始按同一两仓现金规则独立重放，原账户身份只认正式账户实际成交的首板股票日，禁止回读后来变化的历史推荐重建订单或改写标签。
- 当前帧已经 `formal_action=buy_now`、capture state 已触板、报价过期、`fill_followup`、非首板或存在静态 lane blocker 时不得生成待预测行。混合市场、动态执行和最终触发检查的 `blocker_codes` 不能作为提前母池的全空门。
- 候选特征固定为：当前涨幅/距板、lane rank、support/entry quality 及缺失标记、市场/动态/软结构阻断状态、成熟历史质量、观察年龄和持续帧数；20/60/180 秒涨幅斜率、加速度、最大回撤/收复；20/60 秒成交量与成交额增量率；rank 变化；独立研究行情的点时涨速、振幅、主力净流入率及 20/60 秒变化；概念强度/龙位/强 5% 数量及 1/3/5 分钟涨幅和成交额加速度；同日板块/个股主力净流入及缺失标记；金银状态 one-hot。
- 市场特征固定为：3-5/5-7/7-9.5% 候选数量、新进入数量、上行比例、涨幅最大/P75、近板数量；20/60/180 秒正式事件计数；概念集中度、正概念加速度比例、同日正资金比例。股票代码、名称、概念 ID、行业 ID 和原始时间字符串不得进入模型向量。
- 第一层固定 `LGBMClassifier(objective="binary", n_estimators=160, learning_rate=0.025, num_leaves=7, max_depth=3, min_child_samples=50, reg_alpha=2, reg_lambda=8, colsample_bytree=0.8, random_state=0, deterministic=True, force_col_wise=True, n_jobs=1)`，目标为未来 60 秒是否存在正式事件；每个交易日总权重 1，再做一次类别平衡。
- 第二层固定 `LGBMRanker(objective="lambdarank", metric="ndcg", n_estimators=120, learning_rate=0.03, num_leaves=7, max_depth=3, min_child_samples=20, reg_alpha=1, reg_lambda=5, colsample_bytree=0.8, random_state=0, deterministic=True, force_col_wise=True, n_jobs=1)`，只训练事件阳性帧；同帧 group 不可跨日期或跨时间。
- 每帧 Top1 依次按身份 rank 分数、现有 lane rank、股票代码稳定选择。第三层固定 `StandardScaler + LogisticRegression(class_weight=None, max_iter=2000, random_state=0)`，输入为 Top1 候选/市场特征、事件概率、身份分数、Top1 margin 和候选数，直接预测该 Top1 是否为未来 60 秒最早正式身份。
- 日期阶段只按完整日冻结：前 40 日 fit、随后 15 日 calibration、再后 60 日 validation。模型不得早于第 15 个 calibration 日收盘冻结；validation scope 必须在模型之后且在自身收盘后冻结，重复日期、模型冻结前已落库日期和第 61 日不得进入首批 60 日 cohort。fit 内第一/二层至少 20 日种子，之后每 5 日走步产生 OOF Top1；任何评分日的模型训练截止必须早于评分日。
- calibration 阈值只从 `0.05..0.95`、步长 `0.05` 选择。合法阈值至少产生 20 个不同股票日动作，正式 60 秒身份精度 `>=70%`；合法阈值中依次最大化可达召回、精度、阈值。无合法阈值即前向拒绝，不允许查看 validation 后重选。
- 同股票日只取第一次动作、同一帧最多一个、每日最多两个。每个动作必须冻结完整候选名单、动作时正式两仓证据、三层模型指纹、阈值和未触板新鲜报价，并保存覆盖全部决策字段的不可变指纹。成交代理为信号后 20..60 秒内首条新鲜报价且严格低于涨停价；已到涨停价或缺报价记为 `queue_unknown_without_l2`，不计成交。卖出固定 D+1 官方收盘和真实费用，另做双倍成本。
- 模型冻结前只保存数据和 `collecting` 状态，不生成研究动作。冻结后只保存 `research_action`，固定 `actionable=false`、`execution_effect=none_research_only`；不得改变正式 candidates、recommendations、portfolio、action 或 rank。
- validation 最终使用 `limit-up-preboard-point-trigger-reliability-v8`，全部门必须通过：唯一完整的 60 日 scope/标签 cohort、唯一模型记录、全部动作决策指纹及两仓选择约束完整、动作四阶段闭合；每个动作还必须保存不可变结算原始证据及 SHA-256 指纹，并从该证据独立重放延迟成交、正式身份和物理触板，D 日官方最高价/收盘价核对触板与最终封板；保存的 D+1 日期/价格/收益与可靠市场日历及原始官方日线独立重算一致，60 个官方闭合动作、40 个动作日、正式身份精度 `>=70%`、原两仓身份精度 `>=70%`、可达召回 `>=30%`、D+1 胜率 `>=60%`、平均净收益 `>=1%`。提前首板两仓账户和加入未改二进三的联合账户都必须在正常及双倍成本下复利为正、正常 PF `>=1.5`、双倍成本 PF `>=1.2`、最大回撤不差于 `-15%`，且各自五个连续 12 日块至少四块盈利；单日正利润贡献不超过 `15%`。联合产品账户还必须与同一 validation 日期、同一冻结正式订单重放的正式账户比较：正常和双倍成本胜率/复利差均 `>=0`，最大回撤差均 `>=-1pct`，PF 至少保留 `95%`。两项身份精度、可达召回和 D+1 胜率的双侧 95% Wilson 下界还必须达到同一阈值。归档器必须用指标重算完整门集合，缺门、伪造门、重复 validation 日期、同期正式指标缺失、结算证据漂移或任一重放不一致一律拒绝。
- 通过全部门后状态只能是 `forward_reliable_candidate_for_live_review`，仍不能自动修改正式 v9/v15；生产升级需要单独评审和用户决定。

### Task 1: 修复亚分钟雷达采集节奏

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `tests/alphaagent/test_data_sync_schedule.py`

- [x] **Step 1: 写概念扫描不阻塞实时扫描测试**

构造同时到期的 `limit_up_live_scan` 与 `limit_up_concept_scan`，用阻塞 Event 模拟概念刷新，断言调度主线程仍立即执行实时扫描；第二次 tick 不重复启动尚未结束的概念线程。

```python
def test_due_concept_scan_runs_in_bounded_background_slot(monkeypatch):
    submitted: list[str] = []
    live: list[str] = []
    monkeypatch.setattr(svc, "_start_concept_scan_schedule", lambda row: submitted.append(row["id"]) or True)
    monkeypatch.setattr(svc, "refresh_live_snapshot", lambda: live.append("live") or ready_snapshot())
    svc._run_scheduled_jobs()
    assert live == ["live"]
    assert submitted == ["limit_up_concept_scan"]
```

- [x] **Step 2: 实现单槽后台概念刷新**

增加 `_concept_schedule_lock`、`_concept_schedule_running`、`_start_concept_scan_schedule()` 和 `_run_concept_scan_schedule()`。只有自动 scheduler 的概念动作走 daemon 线程；手工“立即执行”继续同步返回。`finally` 必须释放 running 状态，异常仍由 `_run_schedule_action()` 写入 schedule 状态。

- [x] **Step 3: 验证调度回归**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py -k 'limit_up_live_scan or concept_scan' -q
```

Expected: 全部通过；实盘 10 秒快速扫描和概念约 30 秒刷新仍各自单实例。

### Task 2: 补齐资金点时来源合同

**Files:**
- Modify: `alphaagent/server/db/schema.py`
- Modify: `alphaagent/server/services/limit_up/radar_observation_repository.py`
- Modify: `tests/alphaagent/test_limit_up_radar_observation_repository.py`

- [x] **Step 1: 写 schema 与 projection 失败测试**

断言 observation schema 和 `project_observation()` 同时保留：

```python
{
    "sector_main_net_inflow_ratio",
    "sector_flow_trade_date",
    "stock_main_net_inflow_ratio",
    "stock_flow_trade_date",
}
```

输入日期必须规范成 `date`；非法日期失败关闭为 `None`，不得替换为帧日期。

- [x] **Step 2: 增加列和幂等迁移**

在 `limit_up_radar_observations` 增加两个 ratio Float 和两个 Date 列，并在兼容迁移列表增加四条 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`。不重写历史行。

- [x] **Step 3: 扩展投影并验证**

从 live candidate 的 `sector_main_net_inflow_ratio/sector_flow_trade_date/stock_main_net_inflow_ratio/stock_flow_trade_date` 原样投影。Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_radar_observation_repository.py -q
```

Expected: 全部通过；旧行允许四列为空。

### Task 3: 冻结秒级 canonical dataset

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_point_trigger_contract.py`
- Create: `alphaagent/server/services/limit_up/preboard_point_trigger_dataset.py`
- Create: `tests/alphaagent/test_limit_up_preboard_point_trigger_dataset.py`

- [x] **Step 1: 写完整日质量测试**

构造两段买入窗口帧，断言每段 P90 `20.0s` 通过、`20.001s` 失败；稳定下午不能稀释慢速上午，窗口边界和未观测缺口计入 gap；stale、过期报价、来源日期错误、概念覆盖不足分别按较差窗口失败且给出稳定 reason code。完整日还必须只有一个合法的采集运行实现指纹。

- [x] **Step 2: 写因果序列与未来隔离测试**

同股票生成 t-180..t 帧，断言 20/60/180 秒斜率、量额增量、回撤/收复、rank 变化、市场分桶和事件时钟只读取 `<=t`。修改 `>t` 的价格、正式动作、D+1 或资金不得改变 t 特征及 fingerprint。

- [x] **Step 3: 写 60 秒标签测试**

标签窗口必须是 `(t,t+60s]` 且不能跨午休或两个买入窗口。未来覆盖有超过 20 秒内部缺口时标签为 `unknown_incomplete_horizon`，不能记负例；同刻多只正式身份按正式 rank、股票代码稳定选最早身份。

- [x] **Step 4: 实现合同和 dataset builder**

公开接口固定为：

```python
def audit_point_trigger_day(frames, observations) -> PointTriggerDayAudit: ...
def build_point_trigger_rows(frames, observations) -> list[dict[str, object]]: ...
def attach_point_trigger_labels(rows, future_observations) -> list[dict[str, object]]: ...
def point_trigger_input_fingerprint(rows) -> str: ...
```

模型字段由两个 tuple 白名单导出：`FRAME_FEATURE_FIELDS`、`IDENTITY_FEATURE_FIELDS`。任何 source-only 或 label 字段进入白名单时测试失败。

- [x] **Step 5: 运行 dataset 合同测试**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_preboard_point_trigger_dataset.py -q
```

Expected: 完整日、因果性、标签窗口和字段白名单全部通过。

### Task 4: 保存不可变日级数据与动作账本

**Files:**
- Modify: `alphaagent/server/db/schema.py`
- Create: `alphaagent/server/services/limit_up/preboard_point_trigger_repository.py`
- Create: `alphaagent/server/services/limit_up/preboard_point_trigger_settlement.py`
- Create: `tests/alphaagent/test_limit_up_preboard_point_trigger_repository.py`

- [x] **Step 1: 写表合同测试**

新增：

```text
limit_up_preboard_point_day_scopes
limit_up_preboard_point_feature_rows
limit_up_preboard_point_model_versions
limit_up_preboard_point_actions
```

day scope 以 `(contract_version, trade_date)` 唯一；feature row 以 `(contract_version, frame_id, vt_symbol)` 唯一；model version 以 fingerprint 主键；action 以 `(model_fingerprint, captured_at, vt_symbol)` 唯一。
原始 frame 和冻结 day scope 同时保存 `capture_runtime_fingerprint`，且该字段进入不可变日级 cohort 指纹。

- [x] **Step 2: 实现原子冻结**

`freeze_point_trigger_day()` 只能把未冻结日期写成一次不可变 feature cohort；同指纹重跑幂等，不同指纹必须抛 `PointTriggerScopeConflict`。不完整日只保存审计 scope，不写训练行。

- [x] **Step 3: 实现模型和动作保存**

模型行保存日期 cohort、参数、字段白名单、训练输入指纹、校准阈值和 `frozen_at`。动作决策字段不可更新；只有 delayed fill、正式身份、物理触板和 D+1 结算字段可从 pending 单向闭合。每个动作先冻结结算原始证据及 SHA-256 指纹；同日证据必须等到 15:00 后，后续阶段只能从该证据或冻结 feature label 独立重放，不能信任可同步篡改的动作结果字段。

- [x] **Step 4: 运行仓储测试**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_preboard_point_trigger_repository.py -q
```

Expected: 幂等、冲突拒绝、不可变决策和单向结算全部通过。

### Task 5: 实现三层走步模型

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_point_trigger_model.py`
- Create: `tests/alphaagent/test_limit_up_preboard_point_trigger_model.py`

- [x] **Step 1: 写日期权重、group 和稳定 Top1 测试**

断言 frame event 每日总权重相等；rank group 不跨帧；分数相同时按 lane rank、代码选择；类别或 event group 不足时明确 `not_ready`。

- [x] **Step 2: 写走步隔离测试**

构造 40 个 fit 日，前 20 日种子、后四块各 5 日。修改后一块及未来标签不得改变前块模型指纹、分数或 Top1；每条 OOF 行保存训练截止日及两个上游模型指纹。

- [x] **Step 3: 写直接动作目标和校准测试**

第三层标签必须对应实际 Top1，而非帧内任意正例。20 个股票日中 14 个命中可合法；19 个中 19 个命中仍因样本不足拒绝。无合法阈值时 validation 动作必须为空。

- [x] **Step 4: 实现固定模型**

公开接口固定为：

```python
def fit_event_model(rows, fit_dates) -> PointEventModelFit: ...
def fit_identity_ranker(rows, fit_dates) -> PointIdentityModelFit: ...
def build_walk_forward_top1(rows, fit_dates) -> list[dict[str, object]]: ...
def fit_action_model(oof_top1) -> PointActionModelFit: ...
def calibrate_point_actions(rows, minimum_actions=20, minimum_precision=0.70) -> PointThresholdSelection: ...
```

- [x] **Step 5: 运行模型测试**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_preboard_point_trigger_model.py -q
```

Expected: 日期隔离、group、模型指纹、Top1 和阈值硬门全部通过。

### Task 6: 接入 EOD 冻结和只读实时评分

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_point_trigger_service.py`
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Create: `tests/alphaagent/test_limit_up_preboard_point_trigger_service.py`
- Modify: `tests/alphaagent/test_data_sync_schedule.py`
- Modify: `tests/alphaagent/test_limit_up_live.py`

- [x] **Step 1: 写冻结前零动作测试**

少于 40 fit + 15 calibration 完整日时，EOD 任务只能冻结 day scope/features，状态为 `collecting_fit` 或 `collecting_calibration`，model/action 表保持空。

- [x] **Step 2: 写正式隔离测试**

同一输入调用评分前后，正式 v15 的 `candidates/recommendations/portfolio/action/rank` 必须逐字段相等；研究异常只能写质量错误，不得使 live snapshot stale 或失败。

- [x] **Step 3: 实现 EOD 任务**

新增 `sync_limit_up_preboard_point_trigger`，在 21:30 可靠日线/分钟结算之后运行：审计前一交易日、冻结完整日、闭合 60 秒标签和既有动作 D+1；达到 40/15 日时只训练一次并保存冻结模型。不得 catch-up 到 `eligible_after` 之前。

- [x] **Step 4: 实现冻结后实时评分**

仅加载唯一 active frozen model；从当前及过去保存帧构造 Top1，达到阈值时保存不可执行 action。无模型、字段缺失、frame gap、quote age、指纹不一致或仓储异常全部 no-action。

- [x] **Step 5: 运行服务与隔离测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_point_trigger_service.py \
  tests/alphaagent/test_data_sync_schedule.py \
  tests/alphaagent/test_limit_up_live.py -q
```

Expected: 冻结前零动作、EOD 幂等、实时失败关闭和正式响应隔离全部通过。

### Task 7: 冻结前向验收报告

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_point_trigger_study.py`
- Create: `tests/alphaagent/test_limit_up_preboard_point_trigger_study.py`
- Create after data matures: `memory/06_backtests/limit_up_preboard_point_trigger_v9_forward.md`
- Create after data matures: `memory/06_backtests/limit_up_preboard_point_trigger_v9_forward.json`

- [x] **Step 1: 写阶段和冻结 cohort 测试**

阶段只能按首批完整日形成 40/15/60；后续补入更早日期、修改 excluded day 或追加第 61 个 validation 日不得改变已冻结 cohort ID。

- [x] **Step 2: 写同账户和压力测试**

复用正式两仓到达顺序、二进三、费用和 D+1 收盘；分别输出提前首板独立、联合、双倍成本和 queue-unknown 拒绝账户。禁止把未改二进三收益解释为 v9 提前收益。

- [x] **Step 3: 实现质量、身份和收益硬门**

报告必须逐门输出当前值、要求和 pass；任何 null 都失败。validation 未满 60 完整日时只输出 `forward_collecting`，不得发布胜率/复利通过结论。

- [x] **Step 4: 运行报告测试**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_preboard_point_trigger_study.py -q
```

Expected: cohort 冻结、同账户、未成熟隐藏和全部可靠门通过。

### Task 8: 完整回归和可靠归档

**Files:**
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `requirements/alphaagent_limit_up_preboard_point_trigger_v9_implementation_plan.md`

- [x] **Step 1: 跑完整定向回归**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_radar_observation_repository.py \
  tests/alphaagent/test_limit_up_preboard_point_trigger_dataset.py \
  tests/alphaagent/test_limit_up_preboard_point_trigger_repository.py \
  tests/alphaagent/test_limit_up_preboard_point_trigger_model.py \
  tests/alphaagent/test_limit_up_preboard_point_trigger_service.py \
  tests/alphaagent/test_limit_up_preboard_point_trigger_study.py -q
uv run python -m compileall -q alphaagent/server/services/limit_up
git diff --check
```

Expected: 全部通过，无语法和空白错误。

- [x] **Step 2: 只按证据归档状态**

允许状态只有 `collecting_fit`、`collecting_calibration`、`forward_rejected`、`forward_reliable_candidate_for_live_review`。没有 60 个冻结 validation 完整日及全部硬门前，不得写“可靠”、不得改正式 v9/v15。

- [x] **Step 3: 生产评审边界**

只有 `forward_reliable_candidate_for_live_review` 才能另立生产升级计划；本计划不修改公开推荐、自动下单或正式绩效口径。

## Self-Review

- Spec coverage：采集节奏、资金 known-at、秒级因果特征、60 秒标签、日级不可变 scope、三层走步模型、阈值、同账户、D+1、双成本、前向 60 日和生产隔离均有独立任务。
- Leakage control：2026-07-20 排除；标签在特征 fingerprint 后附加；资金只认同日保存值；fit OOF 截止早于评分日；calibration 只选一次阈值；validation 不重拟合。
- Type consistency：统一使用 `contract_version`、`model_fingerprint`、`captured_at`、`formal_identity_within_60s`、`research_action` 和 `none_research_only`。
- Failure behavior：质量日、特征、模型、阈值、延迟报价或结算任一缺失均 no-action；失败不能传播到正式 live snapshot。
- Resource boundary：所有回放和训练只从 `alphaagent-research` 运行，保持 `0.10` CPU、单数据库连接和关闭 PostgreSQL 查询并行；实时端只做冻结模型的轻量单帧评分。
- Placeholder scan：无 TBD/TODO；每个阶段均有文件、接口、命令、预期结果和终态。

## Current Forward Evidence

- 工程和运行接线已完成；候选门、池内标签、零正例 rank group、点时资金 schema 和
  冷启动有限数值合同修复后，当前首次事件标签测试为 `40 passed`，点触发及雷达仓储
  定向回归为 `184 passed`；加入 data-sync worker 后的打板与数据同步组合为
  `1207 passed`（1 条既有 Starlette 弃用警告）。冻结 artifact 与内存三层
  评分已在多帧、多候选和反转输入顺序下逐项同分；实时端重算覆盖完整模型记录的
  `record_fingerprint`，任何漂移均在动作前失败关闭。候选首次进入观察池或
  资金变化量没有历史锚点时固定编码为
  `0 + missing flag`，数据集和冻结仓储均拒绝任何非有限模型字段，不再由模型入口静默删行。
  API 容器健康，运行库
  独立研究行情字段和 `quote_flow_observed_at` 只存在于雷达观察表，四张前向表存在；
  持久化 `eod_finalize_2130` 已包含
  点触发任务且位于历史重建之后。正式 `limit-up-live-v15 / limit-up-scheduled-v9` 不变。
- 2026-07-20 固定为 shakedown/excluded。旧行没有后来新增的 `lane_blocker_codes` 和研究
  增强字段，禁止回填。仅用当帧已保存的混合 blocker 做只读重建审计时，宽 `>=3%`
  市场池为 126,418 行、519 帧、801 只股票，每帧 `117..465` 只、平均 `243.58`；静态质量
  身份池为 4,956 行、519 帧、29 只股票，market/dynamic 为 1,449/3,507 行，概念加速度
  完整 4,216 行，即 `85.0686% < 95%`。修复后全日只读重放的 `4,956/4,956` 行均为
  有限模型向量，指纹为
  `sha256:91c91d8e8cad424b3d18401e0fe75e4a339c959b27747ca56efbc39d155a3f03`；专用
  `0.10 CPU` 容器加载/构造/标签/总耗时为 `71.30/55.00/8.40/153.30s`，四账本前后均为
  `0/0/0/0`。该日仍因扫描 P90、最大缺口和概念覆盖失败，不能进入 cohort。
- 同日 20 个首次正式首板事件中，前 60 秒曾出现 `>=3%` 未触板观察的只有 8 个；保留 rank
  后仍为 8 个，成熟历史门后 4 个，静态 lane 门后 3 个。旧 `support>=55` 会把这 3 个
  全部排除。其余 12 个在当前帧间隔下从低于 3% 直接进入正式路径，属于本合同不可达事件，
  不能用未来信息补造。严格连续 `(t,t+60s]` 标签在身份池中只有华电辽能的 7 个阳性帧；
  其余反向可达事件不能绕过帧缺口变成训练标签。早期收盘后全市场快照 5,528 只中六个
  点时字段均有值，主板
  `>=3%` 的 370 只也全部覆盖；是否能在交易时段连续保存仍由下一完整日验收。
- 当前真实阶段是 `collecting_fit`，进度 `0/40 + 0/15 + 0/60`；模型、动作和前向归档
  均不存在。这是正确的失败关闭状态，不得改写为可靠。

- 2026-07-21 已在 15:03 冻结为唯一 `incomplete` scope，正式窗口为 `719` 帧、
  `225,918` 条观察、6 个冻结正式订单，四表为 `1/0/0/0`。原因码同时锁定上午 ready
  `95%`、扫描 P90/max `69.9095/98.4517s`、概念加速度覆盖 `68.3489%`、运行指纹覆盖
  `6.3978%` 和实现切换；下午自身 `459` 帧、ready `98.6928%`、扫描 P50/P90/max
  `11.0012/14.6813/57.8240s`，不能稀释上午。该 scope 不写训练行，也不能补洞。

- 同一排除日的完整原始轨迹为 970 帧、277,886 条观察；7,026 条持续首板 `buy_now`
  只对应 42 个首次首板股票日，其中 40 个首次事件落在买入窗口。旧标签把持续状态误算为
  65 个可达事件；按 `(trade_date, vt_symbol)` 只保留第一次正式事件后，601 个已知帧中
  只有 53 个正例帧、严格可达 `13/40` 个首次事件，领先 P50/P90 为
  `31.5565/52.0809s`。同帧不同股票的首次事件仍逐股计数。该只读诊断不进入训练、阈值或
  验证，证据见
  `memory/06_backtests/limit_up_preboard_point_trigger_v9_first_event_label_audit_20260721.md`。

- 排除日和阶段日期已在合同中单一定义：仓储拒绝 `trade_date <= 2026-07-20`，冻结模型
  必须恰好包含日期唯一有序的 40 个 fit 日及其后的 15 个 calibration 日，validation 日期
  必须为空；报告只读取正确合同且晚于排除日的 scope，实时评分再次校验同一 cohort。
  归档器只接受满 60 个 validation 日、绩效可见、正确合同和 gate 版本、
  `none_research_only`、正式策略未改变、状态为
  `forward_reliable_candidate_for_live_review` 且全部可靠门通过的报告；失败报告不能归档。

- 新冻结 scope 的 audit 还会保存正式事件经过原始 3%、帧质量、新鲜报价、成熟历史、
  lane 合同存在和静态门的 60 秒漏斗，以及标签已知/内部缺口/跨时段覆盖；这些字段只作
  采集与母池归因，不进入模型或可靠门。7 月 20 日原生回放为 `20/8/8/8/4/0/0`，旧混合
  blocker 重建的静态 3 个继续单列，不能混写为原生证据。

- 首个 fit 日前的采集修复已部署：快速涨幅榜固定并发读取前四页、每页 100 只，按
  `vt_symbol` 去重；任一空页或异常页显式降级，四页和涨停池同时失败时关闭。合并快照
  时间使用四页最早来源时间，每只股票另保存自身页/概念/涨停池的 known-at 时间；正常
  运行帧在输入加载完成后才落评价时间。扫描调度固定为 10 秒、scheduler tick 为 2 秒。
  正式新浪四页继续决定价格和排序；东方财富四页只向内部研究轨迹补充带独立时间戳的
  涨速、振幅和主力流。最终镜像两源均为 `400/400` 唯一股票，研究四项数值和来源时间
  `400/400`；公开 candidates/recommendations 不含研究字段。当前日冻结增加 15:00
  收盘门，更早未冻结日仍按最早日期恢复；正式历史默认入口固定为与页面一致的
  `portfolio / next_close`，不再落入旧 `dynamic` 500 或 sweep 代理。API、data-sync worker
  和 point-trigger worker 已统一为
  `sha256:53ee907c237a1d51e140ef39ea11b74810e66f8e5f1f7d1ee1d7484f3f11929b`；三者重启 0、
  OOM false，API healthy，当前采集运行指纹为
  `sha256:4ccbb7635e49ab257da20f991733848a47186ace91e7822be14b6edea5357462`，worker 为
  `not_ready_model_scope`。运行库已迁移
  `capture_runtime_fingerprint`、`settlement_evidence` 和
  `settlement_evidence_fingerprint` 所需列；冻结证据重放新增
  `settlement_evidence_integrity`、`delayed_fill_integrity`、`formal_identity_integrity`
  和 `physical_touch_integrity` 四个硬门并由 v8 保留。15:05 盘后公开投影没有点触发概率、
  身份分、研究行情增强值或运行指纹；21:30 批次 `succeeded`、unfinished job 为 0。盘后
  报告仍为 `collecting_fit`、
  `performance_visible=false`，绩效、账户和可靠门均为空；不能计入 40/15/60。

- [x] data-sync worker 增加轻量 Compose 健康门：盘前核对 `10s/2s/30s` 固定节拍，盘中
  核对实时/概念 schedule 心跳和当日已保存帧的唯一合法指纹；休市日不要求当日帧，盘后
  不因冻结坏日循环失败。Docker curl worker 暖进程内的本地 `/healthz`，不冷启动 Python；
  真实容器为 `21.5ms`，状态 `healthy`、失败计数 0。
- [ ] 积累首批 40 个完整 fit 日。
- [ ] 积累随后 15 个完整 calibration 日并冻结唯一模型/阈值决定。
- [ ] 积累随后 60 个完整 validation 日和闭合动作。
- [ ] 全部可靠性硬门通过后生成不可变 JSON/Markdown，并进入单独生产评审。
