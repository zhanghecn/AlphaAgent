# AlphaAgent 首板概念增量买点修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not use subagents in this repository task.

**Goal:** 修正非连续涨停的首板归类，并把实时板块判断从“基线与概念同时通过”改为“行业基线或概念增量任一路径通过”，随后用新历史版本验证买点、胜率、复利和回撤。

**Architecture:** 市场、首板结构、距离、换手和个股风险作为共享硬门；旧行业基线与实时概念增量封装为两个独立板块路径，通过 OR 汇总成一个 `sector_route` 检查。连续板位只使用显式目标板位和前一日连续板数，近期涨停只用于回马板等形态。历史账本升级到新版本完整重建，实时概念收益继续只做点时前向验证。

**Tech Stack:** Python 3.13、FastAPI 服务层、pandas 历史回放、PostgreSQL、pytest、React/Vitest、Docker Compose。

---

### Task 1: 锁定板位归类和短周期回马形态

**Files:**
- Modify: `tests/alphaagent/test_limit_up_lanes.py`
- Modify: `alphaagent/server/services/limit_up/lane_research.py`

- [ ] **Step 1: 写板位失败测试**

新增三个测试：

```python
def test_recent_nonconsecutive_limit_stays_in_first_board_lane():
    candidate = _candidate(
        prior_streak=0,
        prior_limit_count_5=1,
        target_board=1,
        previous_limit_up=False,
    )
    assert classify_board_lane(candidate) == "first_board"


def test_explicit_nonconsecutive_third_board_keeps_two_to_three_lane():
    candidate = _candidate(prior_streak=0, prior_limit_count_5=2, target_board=3)
    assert classify_board_lane(candidate) == "two_to_three"


def test_short_cycle_deep_pullback_is_first_board_return_setup():
    result = evaluate_lane_candidate(
        _candidate(
            prior_streak=0,
            prior_limit_count_5=1,
            previous_limit_up=False,
            trade_days_since_prior_limit=3,
            pullback_from_prior_limit_pct=-9.42,
            prior_change_pct=-2.31,
            auction_gap_pct=2.04,
            prior_position_120=0.81,
        )
    )
    assert result["lane"] == "first_board"
    assert "return_board" in result["setup_tags"]
    assert "not_first_board_after_cooling" not in result["blockers"]
    assert "low_position_missing" not in result["blockers"]
```

- [ ] **Step 2: 运行测试并确认旧逻辑失败**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py -q -k "recent_nonconsecutive or explicit_nonconsecutive or short_cycle_deep"
```

Expected: 近期一板被错误归为 `one_to_two`，短周期回马仍有首板阻断。

- [ ] **Step 3: 实现最小板位和形态修复**

在 `lane_research.py`：

```python
def classify_board_lane(candidate: Mapping[str, object]) -> str:
    prior_streak = _integer(candidate.get("prior_streak"))
    target = max(_integer(candidate.get("target_board")), prior_streak + 1)
    if target >= 4:
        return "high_board"
    if target == 3:
        return "two_to_three"
    if target == 2:
        return "one_to_two"
    return "first_board"


def _short_cycle_return_board(candidate: Mapping[str, object]) -> bool:
    return bool(
        _integer(candidate.get("prior_streak")) == 0
        and candidate.get("previous_limit_up") is not True
        and _integer(candidate.get("prior_limit_count_5")) == 1
        and 2 <= (_number(candidate.get("trade_days_since_prior_limit")) or -1) <= 4
        and (_number(candidate.get("pullback_from_prior_limit_pct")) or 0) <= -8
        and (_number(candidate.get("prior_change_pct")) or 0) < 0
        and 1 <= (_number(candidate.get("auction_gap_pct")) or -99) <= 7
    )
```

`_first_board_rules()` 只在 `_short_cycle_return_board()` 为假时保留近期涨停阻断；
低位/充分回调判断把该形态作为第三种通过条件。`detect_setup_tags()` 为该形态附加
`return_board`，但不删除既有 `weak_to_strong_breakout`。

- [ ] **Step 4: 运行板位和形态测试**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_setup_tags.py -q
```

Expected: PASS；显式目标三板仍为 `two_to_three`。

### Task 2: 把行业与概念改为增量 OR 路径

**Files:**
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `alphaagent/server/services/limit_up/live_policy.py`

- [ ] **Step 1: 写两条路径的失败测试**

覆盖以下五种输入：

```python
def test_legacy_sector_route_survives_unavailable_concept():
    candidate = _candidate(
        sector_heat=72,
        sector_touch_count=4,
        sector_main_net_inflow=200_000_000,
        concept_state="unavailable",
        concept_trigger_allowed=False,
        concept_coverage_ratio=0,
        concept_snapshot_age_seconds=None,
    )
    assert live_policy._sweep_ready(candidate) is True


def test_concept_increment_bypasses_wrong_legacy_sector_group():
    candidate = _candidate(
        sector_heat=45,
        sector_touch_count=0,
        sector_main_net_inflow=-5_000_000_000,
        concept_state="launch",
        concept_trigger_allowed=True,
        concept_coverage_ratio=0.97,
        concept_snapshot_age_seconds=12,
        concept_strong_5_count=9,
        concept_leader_rank=2,
    )
    assert live_policy._sweep_ready(candidate) is True
```

另外验证：两条路径都失败时为假；概念陈旧且基线失败时为假；个股严重净流出时即使
概念路径通过也为假。每个结果必须包含一个 `sector_route` 检查，`observed` 分别为
`行业基线通过`、`概念增量通过` 或 `两条路径均未通过`。

- [ ] **Step 2: 运行定向测试并确认失败**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q -k "sector_route or concept_increment or unavailable_concept"
```

Expected: 旧实现因概念硬门或旧行业资金门错误阻断。

- [ ] **Step 3: 实现板块路径纯函数**

在 `live_policy.py` 增加三个小函数：

```python
def _route_passed(checks: Sequence[Mapping[str, object]]) -> bool:
    return bool(checks) and all(check.get("status") == "passed" for check in checks)


def _diagnostic_checks(checks: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [{**dict(check), "status": "informational"} for check in checks]


def _append_additive_sector_route_checks(
    checks: list[dict[str, object]],
    candidate: Mapping[str, object],
    *,
    heat_required: float,
    touch_required: int,
    require_expansion: bool,
) -> tuple[bool, bool]:
    baseline_checks = _legacy_sector_route_checks(
        candidate,
        heat_required=heat_required,
        touch_required=touch_required,
        require_expansion=require_expansion,
    )
    concept_checks = _realtime_concept_route_checks(candidate)
    baseline_passed = _route_passed(baseline_checks)
    concept_passed = _route_passed(concept_checks)
    checks.extend(_diagnostic_checks(baseline_checks))
    checks.extend(_diagnostic_checks(concept_checks))
    if baseline_passed:
        observed = "行业基线通过"
    elif concept_passed:
        observed = "概念增量通过"
    else:
        observed = "两条路径均未通过"
    failed_reasons = [
        str(check.get("reason") or check.get("label") or "板块条件未满足")
        for check in [*baseline_checks, *concept_checks]
        if check.get("status") != "passed"
    ]
    checks.append(
        {
            "code": "sector_route",
            "label": "板块路径",
            "status": "passed" if baseline_passed or concept_passed else "pending",
            "observed": observed,
            "required": "行业基线或概念增量任一路径通过",
            "reason": "；".join(failed_reasons[:4]) or "板块路径未通过",
        }
    )
    return baseline_passed, concept_passed
```

`_legacy_sector_route_checks()` 直接搬移现有 `sector_heat` 和 `sector_expansion` 检查；
`_realtime_concept_route_checks()` 创建局部列表并调用现有
`_append_realtime_concept_checks()`，不复制概念阈值。

两个路径的组件检查保留原 code 和观测值，但统一降为 `informational`；只有汇总的
`sector_route` 使用 `passed/pending/failed` 参与买点。若概念路径通过，旧行业资金
检查降为 `informational`；个股资金和换手继续使用原硬门。

- [ ] **Step 4: 运行实时策略回归**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_concept_live.py tests/alphaagent/test_limit_up_concept_resonance.py -q
```

Expected: PASS；全局概念质量失败仍阻断“仅概念增量”候选，但不删除已通过行业基线的候选。

### Task 3: 锁定东山精密式逐帧触发

**Files:**
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py` only if the integration test exposes a merge defect

- [ ] **Step 1: 添加集成夹具**

构造 `prior_streak=0`、`prior_limit_count_5=1`、三日回撤 9% 以上、D-1 收跌、
竞价 2%、半年基因和财报通过的首板候选；概念设置为 PCB `launch`、9 只涨超 5%、
概念龙 2、距板 0.2%。断言：

```python
assert candidate["board_lane"] == "first_board"
assert signal["action"] == "buy_now"
assert signal["signal_state"] == "trigger_ready"
assert signal["sector_route"] == "concept_increment"
assert "prior_board_evidence_missing" not in signal["blockers"]
```

- [ ] **Step 2: 运行集成测试**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q -k "short_cycle_return or pcb_increment"
```

Expected: PASS；若字段合并覆盖正确，不修改 `live_service.py`。

### Task 4: 升级历史合同并完整重建

**Files:**
- Modify: `alphaagent/server/services/limit_up/versions.py`
- Modify: `alphaagent/server/services/limit_up/scheduled_execution.py`
- Modify: `tests/alphaagent/test_limit_up_history.py`
- Modify: version assertions in touched limit-up tests only

- [ ] **Step 1: 更新版本断言测试**

```python
assert HISTORY_STRATEGY_VERSION == "limit-up-history-v12"
assert scheduled_execution.SCHEDULED_EXECUTION_VERSION == "limit-up-scheduled-v3"
assert scheduled_execution.RULE_FREEZE_DATE == date(2026, 7, 15)
```

- [ ] **Step 2: 升级版本常量**

历史版本升级为 v12，连续执行版本升级为 v3，规则冻结日更新为 2026-07-15；保留旧 v11
数据库记录用于对照，不覆盖旧报告。

- [ ] **Step 3: 运行历史和现金账户测试**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_history.py tests/alphaagent/test_limit_up_scheduled_execution.py tests/alphaagent/test_limit_up_cash_backtest.py -q
```

Expected: PASS。

- [ ] **Step 4: 重建 v12 历史账本**

Run:

```bash
docker compose up -d --build alphaagent-api
docker compose exec -T alphaagent-api python -c 'from alphaagent.server.services.limit_up.history_service import rebuild_history_sync; print(rebuild_history_sync())'
```

Expected: `status=ready`，可靠历史达到数据库最新完整交易日。

### Task 5: 冻结回测验收与新增交易归因

**Files:**
- Create: `memory/06_backtests/limit_up_additive_concept_entry_backtest_20260715.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/09_decisions/decisions.md`

- [ ] **Step 1: 运行 v12 双仓账户和压力测试**

从容器调用 `get_scheduled_history_backtest(None, None, trade_limit=None)`，保存：候选数、
闭合交易、买入日、胜率、复利、期末资金、最大回撤、利润因子、利用率、双倍成本和
只成交炸板压力。

- [ ] **Step 2: 对照 v11 并列出新增交易**

用 `(entry_date, vt_symbol, buy_time)` 比较 v11 和 v12 的
`lane_portfolio.candidate_pool.first_board`，对新增候选单独模拟同一双仓账户并记录逐笔
D、D+1、净收益和跳过原因。禁止根据赢家/输家修改 Task 1 的阈值。

- [ ] **Step 3: 执行冻结验收**

全部满足才保留短周期回马为历史执行：买点/买入日不减少、胜率不低于 55%、复利高于
`+123.5433%`、最大回撤不差于 `-10%`、双倍成本为正。失败时撤销短周期回马的执行
豁免并重新升级未发布的 v12 账本；保留板位正确归类、形态标签和概念 OR 路径。

- [ ] **Step 4: 写当前事实而非过程流水**

报告明确区分：历史板位/回马结果、实时概念工程可见性、真实概念前向 0 笔或当前闭合数。
更新 memory 的当前版本、运行命令、证据链接和未解决风险。

### Task 6: 全量验证与部署检查

**Files:**
- Modify only files required by failing tests

- [ ] **Step 1: 后端完整相关套件**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_*.py tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_akshare_adapter.py tests/alphaagent/test_api.py -q
```

- [ ] **Step 2: 前端与构建**

```bash
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
python -m compileall -q alphaagent/server/services/limit_up tests/alphaagent
git diff --check
```

- [ ] **Step 3: 服务健康**

```bash
docker compose up -d --build alphaagent-api alphaagent-web
docker compose ps
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8080/limit-up
```

Expected: API/Gateway/PostgreSQL/Redis healthy，页面 200。

- [ ] **Step 4: 最终工作区审计**

只保留本计划直接涉及的代码、测试、requirements 和 memory 变更。依据仓库规则，本任务
不自动提交；只有用户明确要求后才运行 `git commit`，且不执行 push。

### Task 7: 消费已入库分钟线并修复 6 月 15 日后伪空仓

**Files:**
- Modify: `tests/alphaagent/test_limit_up_lanes.py`
- Modify: `tests/alphaagent/test_limit_up_history.py`
- Modify: `alphaagent/server/services/limit_up/lane_features.py`
- Modify: `alphaagent/server/services/limit_up/lane_repository.py`
- Modify: `alphaagent/server/services/limit_up/history_engine.py`
- Modify: `alphaagent/server/services/limit_up/versions.py`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: 写分钟路径转换与优先级失败测试**

测试必须覆盖：1分钟行情按既有80点网格降采样；09:30/13:00使用首根分钟线开盘价；
价格路径只按D-1收盘换算涨跌幅；原始事件 `time_preview` 优先于分钟回退；信号后的分钟
数据不能改变 `path_prefix_features()`；有效分钟回退不再产生
`intraday_support_unavailable`。

- [x] **Step 2: 运行定向测试并确认旧实现失败**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_history.py -q -k "minute_path or minute_fallback"
```

Expected: 旧实现没有分钟价格路径转换和事件回退字段，测试失败。

- [x] **Step 3: 实现最小数据回退链路**

`lane_features.py` 提供两个纯函数：把1分钟bar降采样为80点价格路径，再用D-1收盘转换为
涨跌幅路径。`lane_repository.py` 只为缺少 `time_preview` 的事件分批查询
`stock_minute_bars`，至少6个有效网格点才附加 `minute_price_path`，并记录来源和覆盖。
`history_engine.py` 对当前首板事件优先使用 `time_preview`，缺失时才转换
`minute_price_path`；`path_prefix_features()` 仍只读取信号时点及之前的数据。

- [x] **Step 4: 升级并重建不可变历史版本**

把历史账本升级为 `limit-up-history-v13`，保留v12用于差异对照。构建并重启API后执行：

```bash
docker compose exec -T alphaagent-api python -c 'from alphaagent.server.services.limit_up.history_service import rebuild_history_sync; print(rebuild_history_sync())'
docker compose restart alphaagent-api
```

Expected: 可靠历史重建到最新完整交易日，分钟回退覆盖延伸到2026-07-14；独立 CLI
进程完成后重启服务进程，避免其继续持有重建前的内存缓存。正常产品操作优先使用
`POST /api/limit-up/history/rebuild`，该路径会在服务进程内清缓存并预热。

- [x] **Step 5: 运行同口径账户与防作弊验收**

固定100,000元、最多两仓、D日只使用信号时点前数据、D+1 14:30退出；对照v12/v13的
信号、成交、买入日、胜率、复利、回撤、利润因子、双倍成本及6月16日后的逐笔交割单。
额外验证修改信号时点后的分钟价格不会改变候选决策，禁止用最终封板或D+1结果反选。

- [x] **Step 6: 完整回归、部署与记忆卫生**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_*.py tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_akshare_adapter.py tests/alphaagent/test_api.py -q
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
python -m compileall -q alphaagent/server/services/limit_up tests/alphaagent
git diff --check
docker compose ps
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8080/limit-up
```

只把新v13结果和仍有效的限制更新到现有memory overview；不保留诊断脚本、raw JSON或
重复过程报告，不自动提交。

### Task 8: 禁止最终炸板结果进入产品回测

**Files:**
- Modify: `tests/alphaagent/test_limit_up_scheduled_execution.py`
- Modify: `tests/alphaagent/test_limit_up_lanes.py`
- Modify: `alphaagent/server/services/limit_up/history_service.py`
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: 固化无未来结果测试**

翻转候选的 `outcome.touched/outcome.sealed` 后，产品订单的股票、买入时间、排序分数和
池内排名必须完全相同；产品回测的 `stress_tests` 只能保留不读取未来结果的双倍成本。

- [x] **Step 2: 删除产品炸板反事实**

删除 `failed_board_only_fill` 的构建、API 类型和页面展示。最终封板/炸板只允许出现在
盘后交割结果标签，不进入候选、排序、成交或产品压力测试。

- [x] **Step 3: 全量验证并部署**

运行后端打板套件、前端测试/构建、Python 编译和 `git diff --check`；重启 API/Web 后
核对产品回测仍为 v13 同一主账户指标，且响应中不存在 `failed_board_only_fill`。
