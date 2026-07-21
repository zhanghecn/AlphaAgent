# 首板雷达原生序列触发 v8 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Repository policy forbids `git commit` unless the user explicitly asks, so each task ends with a focused verification checkpoint instead of a commit.

**Goal:** 在不修改正式 `limit-up-scheduled-v9 / limit-up-live-v15` 的前提下，建立历史与实时同源的 `>=3%` 首板雷达序列模型，直接预测当前算法选出的 Top1 是否会在未来三分钟进入正式触板，并用原两仓账户验证提前买入的胜率、复利和回撤。

**Architecture:** v8 不读取 TDX 逐笔、动态概念、当日板块资金或任何只在实时端存在的字段。历史端从严格质量母池及完整一分钟栏重建雷达行，实时端从持久化雷达帧及对应完成分钟重建同一 canonical row；二者共享一个规范化和因果序列特征实现。第一层确定性 LightGBM 二分类模型在每分钟全部候选中选择 Top1；第二层 Logistic 动作模型只使用扩展窗口产生的第一层样本外 Top1 身份和分数训练，避免用拟合内排名分数学习“现在是否行动”。

**Tech Stack:** Python 3.11+、pandas、NumPy、scikit-learn、LightGBM、SQLAlchemy、PostgreSQL、pytest、现有一分钟行情、雷达观察仓储和两仓现金回放。

**Current evidence (2026-07-20):** v7 的条件事件分钟 Top1 命中为 `81.7568%`，但动作校准最好仅 `4/10=40%`，因此已拒绝。曾探测的 95 日严格母池有 16,613 个股票日，16,474 个完整、139 个缺失；139/139 缺口经现有同步链路请求并扫描 1,726,624 行后仍写入 0 行，证明公共 TDX 在这六个早期日期没有可用回溯。主研究冻结为 `2026-03-09..2026-07-16` 连续完整 89 日、15,921/15,921 个股票日，阶段为 44/15/30；manifest、分钟覆盖和历史质量指纹分别为 `sha256:d86e12e566bbeadfaeb6be9e9c54aa43442d1b9587cc2993b0c292a930d0d595`、`sha256:9bebae80352950062ef90b47e30fe471cf593866233e405d279fff6371eba25f`、`sha256:00a9f00c03e45443bbc49a09d6713388c66dce1069c8974303455f9517f111ff`。六日扩展以 `excluded_training_extension_provider_unavailable` 单独列账，不能称为 95 日完整研究。7 月 20 日雷达有 403 个有效帧，7 月 10/14 日各仅一帧，因此全部现有雷达日只作开发联调，不进入冻结后的前向验收。

**Historical result (2026-07-20):** 首轮完整回放状态为 `ready_historical_rejected`。两层模型均正常训练，但校准段满足至少 10 个股票日动作时最好仅 `5/13=38.4615%`；`3/3=100%` 的高阈值因样本不足无效，因此阈值为空、验证段提前首板动作固定为 0。正式触板基线精确复现为 `23笔/73.9130%/+36.7279%/-4.4374%/PF 4.2555`，联合账户 `+9.2700%` 全部来自未改二进三。Task 5 不启动，正式 v9/v15 不变。完整确定性复跑尚待专用 `alphaagent-research` 运行时完成，不能声称三次复跑已经通过。

---

## Frozen Success Contract

- `>=3%` 只表示进入动态跟踪分母，不是买入条件。候选仍必须是沪深主板首板、非 ST/退市风险、通过当前 lane、同股成熟 D+1 样本数 `>=5`、联合率 `>=30%` 及当时可见的首板质量门。
- 历史候选分母来自所有当日曾达到 `>=3%` 的严格主板股票日；只有完成分钟前缀达到 `>=3%`、尚未首次物理触板且当时通过共用策略的行可评分。最终未触板股票和不行动分钟不得删除。
- 历史主窗口固定为 89 个完整日期：44 日拟合、15 日校准和后 30 日反证。此前尝试扩展的最早 6 日不进入任何模型、阈值、分母或绩效；其 139 个缺口必须保留为 `excluded_training_extension_provider_unavailable` 审计证据。不得把排除缺口描述成删除坏样本或 95 日完整研究；未来若取得合法同源数据，也不能移动本轮校准/验证边界。
- canonical row 必须只包含双方可重建字段：`gain_pct`、`rank_score`、历史样本数、历史联合率、同分钟 gain/rank 相对强度、首次可见年龄、近三分钟可见次数、gain/rank 的一/三分钟因果变化，以及活跃数、新进入数、近板数、gain 最大值/P75、上行动量比例及其变化。
- `support_score` 和 `entry_quality_score` 只参与当前共用候选资格，不进入 v8 模型向量；实时缺失时必须失败关闭，不能插值或读取后来帧。动态概念、板块/个股资金、金银手指、逐笔方向和委托队列均排除在历史模型、阈值和验收之外。
- 历史和实时规范化必须输出同一字段集合、单位、缺失规则、分钟键和排序键。合成同源输入的双向 parity 测试必须逐字段相等；任何 source-only 字段进入模型向量时测试失败。
- 目标在特征冻结后附加。候选标签固定为该行股票是否在未来三个连续交易分钟内进入正式首板触板；同时保留物理触板、正式候选身份、原两仓成交身份和 D+1 结果用于独立归因，不能进入特征。
- 第一层固定为 `LGBMClassifier(objective="binary", n_estimators=120, learning_rate=0.03, num_leaves=7, max_depth=3, min_child_samples=20, reg_alpha=1, reg_lambda=5, colsample_bytree=0.8, random_state=0, deterministic=True, force_col_wise=True, n_jobs=1)`。样本总权重按交易日等权，再对 fit 段正负类作一次冻结平衡。
- 每分钟 Top1 依次按第一层触板分数、现有 `rank_score`、股票代码稳定选择。模型还必须保存 Top1 与第二名的分差、候选数和第一层模型指纹。
- 第二层训练样本只能来自 fit 段扩展窗口第一层样本外预测：最少 20 个种子交易日，之后按 5 日块预测，直到 fit 段结束。某日期的 Top1 身份和第一层分数必须由完全不含该日期及未来日期的模型产生。
- 第二层固定为 `StandardScaler + LogisticRegression(class_weight=None, max_iter=2000, random_state=0)`，训练行仅为每个完成分钟的样本外 Top1；目标直接是该 Top1 当前行的三分钟正式触板标签。动作向量由 canonical Top1/市场特征、第一层概率和同刻分差组成。
- 最终第一层模型只拟合全部 fit 日期；最终第二层模型只拟合 fit 段走步 Top1。calibration 和 validation 只评分，不重拟合、不选择特征。
- 动作阈值只在 15 日 calibration 段从 `0.05..0.95`、步长 `0.05` 中选择。合法阈值至少产生 10 个不同股票日动作，三分钟正式触板精度 `>=70%`；合法阈值中依次最大化可达召回、精度、阈值。没有合法阈值即历史拒绝且验证段首板动作必须为 0。
- 同股票日只取第一次动作；同一分钟最多一个 Top1；每日最多两个首板动作。买价为信号后的下一根一分钟开盘且严格低于涨停价，保守成交另取 `max(下一分钟开盘, 信号价 * 1.001)` 并再次检查涨停价。
- 二进三、两仓各 50%、费用、到达顺序、D+1 官方收盘退出保持不变。主报告必须分开输出提前首板独立账户和“首板 + 未改二进三”联合账户，禁止把二进三收益解释成 v8 收益。
- 历史硬门不降低：baseline parity、双模型就绪、阈值就绪、验证动作 `>=30`、正式身份精度 `>=70%`、原账户身份精度 `>=70%`、可达召回 `>=30%`、D+1 胜率不低于触板基线 2 个百分点以上、正常和双倍成本复利为正、回撤不差于 `-10%`、PF `>=1.2`、五块至少三块盈利。
- 后 30 日已经被多轮查看，只能作历史反证。即使历史全门通过，也只能冻结为 `forward_shadow_candidate`；7 月 20 日及之前雷达帧全部排除。
- 可靠归档必须在冻结时间后累计至少 60 个完整交易日、60 个闭合动作、40 个动作日，并通过：触板精度 `>=70%`、原账户身份精度 `>=70%`、D+1 胜率 `>=60%`、平均净收益 `>=1%`、PF `>=1.5`、双倍成本 PF `>=1.2`、最大回撤不差于 `-15%`、五块至少四块盈利。
- 正式推荐、排序、公开 API 和自动动作始终保持不变；前向层固定 `execution_effect=none_research_only`。只有可靠归档后才能另行提出生产评审，不能自动晋级。

### Task 1: 冻结完整主窗口和供应商不可用扩展

**Files:**
- Reuse: `alphaagent/server/services/limit_up/preboard_hazard_data.py`
- Test: `tests/alphaagent/test_limit_up_preboard_radar_sequence_study.py`

- [x] **Step 1: 写 89 日覆盖和六日排除审计测试**

构造 44/15/30 主日期及部分缺口，断言主窗口任何 fit/calibration/validation 缺口都必须失败关闭；另构造六日供应商不可用扩展，断言其状态固定且不进入主研究，禁止静默删股票日或把六日称为完整。

- [x] **Step 2: 尝试回填现有 139 个一分钟缺口并保留反证**

Run:

```bash
docker compose exec -T alphaagent-api python -c \
  'from alphaagent.server.services.limit_up.preboard_hazard_data import backfill_preboard_hazard_minutes; print(backfill_preboard_hazard_minutes(session_count=95, max_gaps=200, dry_run=False))'
```

Actual: 139/139 缺口均已请求，扫描 1,726,624 行、写入 0 行，最终 `partial`、剩余 139。该结果不阻断已有完整 89 日主研究，但六日固定排除并列账；不得缩小六日自身母池后称其完整。

- [x] **Step 3: 冻结 44/15/30 日期清单、排除清单和输入指纹**

报告保存主窗口每一日期的股票日数、分钟数、缺口数以及 manifest/minute/history-quality 指纹；另保存六日排除日期、139 个缺口和供应商状态。最后 30 日仍标记 `viewed_historical_counterexample`。

- [x] **Step 4: 运行覆盖测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_radar_sequence_study.py \
  -k coverage -q
```

Expected: 全部通过；缺口不能被删除或归入无动作样本。

### Task 2: 建立历史/实时统一 canonical row

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_radar_sequence_model.py`
- Create: `tests/alphaagent/test_limit_up_preboard_radar_sequence_model.py`
- Create: `tests/alphaagent/test_limit_up_preboard_radar_sequence_study.py`

- [x] **Step 1: 写双向 row parity 测试**

使用同一组一分钟栏、历史质量字段和候选排名分别构造 historical source 与 live observation source，断言规范化结果逐字段相等；追加概念、资金或逐笔字段不得改变 canonical row。

- [x] **Step 2: 写实时新鲜度与缺失失败关闭测试**

断言 stale frame、错误 source date、报价超过 60 秒、非首板、`fill_followup`、有 blocker、缺历史样本/联合率/rank 的观察均不进入可评分行；不得用前一帧值回填。

- [x] **Step 3: 写因果序列特征测试**

断言首次可见年龄、近三分钟出现次数、一/三分钟 gain/rank 变化、同分钟相对强度和市场扩散只读取当前与过去；追加或修改未来行后过去特征逐字段不变。

- [x] **Step 4: 实现 canonical row 与特征向量**

实现 historical/live adapter、共同规范化、稳定去重、序列特征、模型字段白名单和输入指纹；不复制 v7 的 transaction vector。

- [x] **Step 5: 运行模型合同测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_radar_sequence_model.py -q
```

Expected: parity、未来隔离、缺失失败关闭和确定性指纹全部通过。

### Task 3: 实现走步 Top1 与直接动作模型

**Files:**
- Modify: `alphaagent/server/services/limit_up/preboard_radar_sequence_model.py`
- Modify: `tests/alphaagent/test_limit_up_preboard_radar_sequence_model.py`

- [x] **Step 1: 写第一层候选模型与稳定 Top1 测试**

断言模型只读取允许日期和白名单特征；同一分钟只产生一个 Top1，分数相同按现有 rank 和代码稳定选择；训练日期、参数和模型文本进入指纹。

- [x] **Step 2: 写扩展窗口 OOF 隔离测试**

构造 30 个 fit 日期，前 20 日为种子、后两块各 5 日；修改第二块及未来标签不得改变第一块模型指纹、分数或 Top1 身份。任何 OOF 行的训练截止日必须早于该行日期。

- [x] **Step 3: 写第二层目标身份测试**

同一分钟包含一个真触板和多个未触板候选时，第二层标签必须对应第一层实际选中的 Top1，而不是“本分钟任意股票触板”；选错股票时标签必须为 0。

- [x] **Step 4: 写校准硬门和动作容量测试**

阈值有 10 选 7 时可合法，9 选 8 不满足最少样本；所有支持阈值低于 70% 时状态固定为 `calibration_precision_gate_failed`。同股票日只取首次、同分钟一个、每日最多两个。

- [x] **Step 5: 实现两层模型、OOF 和校准**

实现第一层 LightGBM、扩展窗口评分、Top1 训练账本、第二层 Logistic、最终评分、阈值选择及所有模型/策略指纹。

- [x] **Step 6: 运行模型测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_radar_sequence_model.py -q
```

Expected: 全部通过；重复拟合和选择逐字段一致。

### Task 4: 完成 v8 历史反证和同账户回放

**Files:**
- Create: `alphaagent/server/services/limit_up/preboard_radar_sequence_study.py`
- Modify: `tests/alphaagent/test_limit_up_preboard_radar_sequence_study.py`
- Create after execution: `memory/06_backtests/limit_up_preboard_radar_sequence_v8_20260720.md`
- Create after execution: `memory/06_backtests/limit_up_preboard_radar_sequence_v8_20260720.json`

- [x] **Step 1: 写 baseline、标签和 validation 隔离测试**

断言正式 v9 账户必须逐项 parity；目标只在特征冻结后附加；修改 validation/oracle/D+1 标签不得改变 fit 模型、OOF 账本、校准阈值或 validation 动作身份。

- [x] **Step 2: 实现完整历史评估**

加载 89 日完整严格母池、六日排除审计、完整一分钟栏、D-1/成熟历史质量、正式首板与二进三订单、日线退出和交易日历；输出候选模型、OOF 动作模型、校准、正式/物理触板、身份、提前时间、可成交性和五个验证块。

- [x] **Step 3: 复用原两仓现金账户**

主、双倍成本、保守成交均保持二进三和两仓顺序；另输出首板独立账户、matched/formal-only/false-positive 损益和未命中原因。

- [ ] **Step 4: 执行三次确定性研究**

Run:

```bash
docker compose --profile research run --rm -T --no-deps \
  -v "$PWD:/workspace:ro" \
  -v "$PWD/memory/06_backtests:/workspace/memory/06_backtests:rw" \
  -w /workspace -e PYTHONPATH=/workspace:/app/third_party/akshare \
  --entrypoint python alphaagent-research \
  -m alphaagent.server.services.limit_up.preboard_radar_sequence_study \
  --sessions 89 --format both \
  --output memory/06_backtests/limit_up_preboard_radar_sequence_v8_20260720
```

Expected: 除 `performance` 外三份 JSON 逐字段一致。历史门失败则归档具体反证并禁止前向晋级；通过才进入 Task 5。

Actual: 首轮完整报告已生成并因校准精度门失败关闭；剩余两次完整复跑尚未完成，不能把
模型级确定性测试替代为全链路复现性。历史失败已经禁止 Task 5，复跑只用于封存输入、
模型、动作和报告的逐字段确定性。

### Task 5: 历史通过后接只读前向账本（未启动：历史失败）

**Files:**
- Create only after historical PASS: `alphaagent/server/services/limit_up/preboard_radar_sequence_forward.py`
- Create only after historical PASS: `tests/alphaagent/test_limit_up_preboard_radar_sequence_forward.py`
- Modify only after historical PASS: `alphaagent/server/services/limit_up/radar_observation_repository.py`
- Modify only after historical PASS: `alphaagent/server/services/limit_up/live_service.py`

- [ ] **Step 1: 冻结模型和前向起点**

保存 canonical contract、第一/第二层模型、阈值、训练输入指纹和 `frozen_at`；`eligible_after` 必须晚于 2026-07-20，旧帧全部登记为 excluded shakedown。

- [ ] **Step 2: 保存逐帧只读评分**

每个完整分钟保存输入 cutoff、Top1、两层分数、阈值、模型指纹、quote age、可成交跟踪和 `execution_effect=none_research_only`；不得改变正式推荐对象。

- [ ] **Step 3: 写正式隔离测试**

同一 snapshot 输入下，接入前后 v15 `candidates/recommendations/portfolio/action/rank` 逐字段相同；研究异常必须失败关闭且不能中断正式雷达。

- [ ] **Step 4: 累计闭合动作并分块验收**

只统计 `eligible_after` 之后的完整交易日和 D+1 已闭合动作；每日覆盖、扫描间隔、报价新鲜度、信号、成交代理和结算都进入不可变账本。

### Task 6: 可靠归档与生产评审边界

**Files:**
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `memory/06_backtests/limit_up_preboard_radar_sequence_v8_20260720.md`

- [ ] **Step 1: 跑完整回归和静态检查**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_preboard_radar_sequence_model.py \
  tests/alphaagent/test_limit_up_preboard_radar_sequence_study.py -q
uv run python -m compileall -q alphaagent/server/services/limit_up
git diff --check
```

Expected: 全部通过，无空白或语法错误。

- [ ] **Step 2: 归档状态而非愿望**

状态只能是 `historical_rejected`、`forward_shadow_collecting`、`forward_rejected` 或 `forward_reliable_candidate_for_live_review`；报告显式区分历史反证和冻结后前向证据。

- [ ] **Step 3: 只在全部前向硬门通过后标记可靠**

达到 60 个完整交易日、60 个闭合动作、40 个动作日及全部质量/收益门后，才能归档为可靠候选。正式 v9/v15 是否升级仍需单独评审和用户决定。

## Self-Review

- Spec coverage：数据缺口、历史/实时 row parity、因果序列、Top1 身份、走步二层模型、校准硬门、同账户回放、只读前向和可靠归档均有独立任务。
- Leakage control：第一层 OOF 的训练截止严格早于评分日期；第二层不接触拟合内 Top1；目标、正式身份、账户身份、物理触板和 D+1 结果均在特征冻结后附加。
- Type consistency：统一使用 canonical candidate row、`candidate_touch_3m_probability`、`top1_touch_3m_probability`、`formal_touch_within_3m` 和 `execution_effect=none_research_only`。
- Historical/live scope：support/entry quality 只作资格门，模型字段全部可由历史完成分钟和实时雷达重建；逐笔、动态资金和概念只允许后续前向分层。
- Failure behavior：训练覆盖、parity、模型、校准或账户任一硬门失败即关闭 v8 动作，不缩小母池、不借用 oracle、不修改正式 v9/v15。
- Placeholder scan：无 TBD/TODO；每一阶段都有明确命令、预期结果和终态。
