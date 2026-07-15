# AlphaAgent 打板概念绝对共振 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` inline. This repository task must not dispatch subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用板块内部绝对共振替换概念全市场前 3% 启动门，保持页面合同简单，并验证全部历史打板胜率和收益不受越界影响。

**Architecture:** 只修改 `concept_resonance.concept_state()` 的纯函数判定和实时版本号；概念评分、排序、候选附加、实时门禁、前端字段和历史账本结构均不变。先冻结数据库中的当前回测基线，再用测试驱动实现，最后重建 v14 账本并运行组合、四战法、代理入口和压力回测。

**Tech Stack:** Python 3.13、pytest、SQLAlchemy/PostgreSQL、FastAPI、React 18、TypeScript、Vitest、Docker Compose。

---

### Task 1: 冻结当前回测与运行基线

**Files:**
- Read: `alphaagent/server/services/limit_up/history_service.py`
- Read: `alphaagent/server/services/limit_up/versions.py`
- Read: `memory/06_backtests/README.md`

- [x] **Step 1: 核对工作区和服务健康**

```bash
git status --short
docker compose ps
```

Expected: 只包含本任务新增的 requirements 文件；API、Gateway、PostgreSQL 和 Redis healthy。

- [x] **Step 2: 读取当前产品组合基线**

```bash
docker compose exec -T alphaagent-api python - <<'PY'
import json
from alphaagent.server.services.limit_up.history_service import get_lane_history_backtest

report = get_lane_history_backtest(None, None, lane="portfolio", exit_mode="dynamic")
summary = report["summary"]
print(json.dumps({
    "history_strategy_version": report["history_strategy_version"],
    "signal_count": summary["signal_count"],
    "buy_count": summary["buy_count"],
    "closed_trade_count": summary["trade_count"],
    "win_rate": summary["win_rate"],
    "total_return_pct": summary["total_return_pct"],
    "max_drawdown_pct": summary["max_drawdown_pct"],
    "profit_factor": summary["profit_factor"],
    "average_utilization_pct": summary["average_utilization_pct"],
    "double_cost": report["stress_tests"]["double_cost"],
    "phase_summaries": report["phase_summaries"],
}, ensure_ascii=False, indent=2, default=str))
PY
```

Expected: `limit-up-history-v14`，当前概要与 memory 一致：290 个候选信号、139 笔买入、137 笔闭合、胜率 62.0438%、复利 204.8622%、最大回撤 -7.9408%、平均资金利用率 26.8794%。若数据库已新增完整历史日，只把日期推进造成的变化单独记录，不归因于本任务。

- [x] **Step 3: 读取四战法和旧代理入口基线**

```bash
docker compose exec -T alphaagent-api python - <<'PY'
import json
from alphaagent.server.services.limit_up.history_service import (
    get_history_backtest,
    get_lane_history_backtest,
)

reports = {}
for lane in ("first_board", "one_to_two", "two_to_three", "high_board"):
    report = get_lane_history_backtest(None, None, lane=lane, exit_mode="dynamic")
    reports[f"lane:{lane}"] = report.get("summary") or report.get("execution_summary")
for entry_mode in ("auction", "sweep", "tail", "next_auction"):
    for exit_mode in ("next_open", "next_close"):
        report = get_history_backtest(None, None, entry_mode, exit_mode)
        reports[f"proxy:{entry_mode}:{exit_mode}"] = report.get("summary")
print(json.dumps(reports, ensure_ascii=False, indent=2, default=str))
PY
```

Expected: 所有报告返回 `ready` 数据；保存每组 `signal_count/trade_count/win_rate/total_return_pct/max_drawdown_pct/profit_factor` 供 Task 5 逐项比较。

### Task 2: 用失败测试定义绝对共振状态

**Files:**
- Modify: `tests/alphaagent/test_limit_up_concept_resonance.py`
- Read: `requirements/alphaagent_limit_up_absolute_concept_launch_design.md`

- [x] **Step 1: 导入纯状态函数**

在现有 import 中增加：

```python
from alphaagent.server.services.limit_up.concept_resonance import concept_state
```

- [x] **Step 2: 添加板块整体启动测试**

```python
def test_concept_launch_uses_absolute_internal_breadth_not_market_percentile() -> None:
    row = _concept(
        "BK0896",
        observed_count=43,
        rise_ratio=41 / 43,
        median_change_pct=2.73,
        strong_5_count=4,
        strong_7_count=2,
        near_limit_count=2,
        strength_percentile=0.50,
    )

    assert concept_state(row) == "launch"
```

- [x] **Step 3: 添加规模化扩散边界测试**

```python
def test_concept_launch_scales_strong_stock_requirement_with_member_count() -> None:
    below = _concept(
        "LARGE",
        observed_count=101,
        rise_ratio=0.90,
        median_change_pct=3.0,
        strong_5_count=5,
        strong_7_count=2,
        near_limit_count=1,
    )
    passed = {**below, "strong_5_count": 6}

    assert concept_state(below) != "launch"
    assert concept_state(passed) == "launch"
```

- [x] **Step 4: 添加预热和优先级测试**

```python
def test_concept_warming_uses_absolute_internal_acceleration() -> None:
    row = _concept(
        "WARM",
        observed_count=30,
        rise_ratio=0.65,
        median_change_pct=1.0,
        strong_5_count=2,
        change_acceleration_3m=0.01,
        strength_percentile=1.0,
    )

    assert concept_state(row) == "warming"


def test_concept_state_keeps_coverage_and_ebb_ahead_of_launch() -> None:
    launch = _concept(
        "RISK",
        observed_count=20,
        rise_ratio=0.90,
        median_change_pct=4.0,
        strong_5_count=5,
        strong_7_count=3,
        near_limit_count=2,
        touched_count=3,
        failed_count=2,
    )

    assert concept_state({**launch, "coverage_ratio": 0.899}) == "unavailable"
    assert concept_state(launch) == "ebb"
```

- [x] **Step 5: 添加启动阈值和末端扩散边界测试**

覆盖以下反例和二选一正例，确保公式不是只对目标样本生效：

```python
def test_concept_launch_requires_rise_ratio_and_median_change_thresholds() -> None:
    launch = _concept(
        "BOUNDARY",
        observed_count=20,
        rise_ratio=0.80,
        median_change_pct=2.5,
        strong_5_count=3,
        near_limit_count=1,
    )

    assert concept_state({**launch, "rise_ratio": 0.799}) != "launch"
    assert concept_state({**launch, "median_change_pct": 2.499}) != "launch"
    assert concept_state(launch) == "launch"


def test_concept_launch_accepts_near_limit_or_two_strong_7_members() -> None:
    launch = _concept(
        "EVIDENCE",
        observed_count=20,
        rise_ratio=0.80,
        median_change_pct=2.5,
        strong_5_count=3,
    )

    assert concept_state(launch) != "launch"
    assert concept_state({**launch, "near_limit_count": 1}) == "launch"
    assert concept_state({**launch, "strong_7_count": 2}) == "launch"
```

- [x] **Step 6: 运行测试确认旧公式失败**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_concept_resonance.py -q
```

Expected: 新增的绝对启动和绝对预热测试 FAIL，因为旧实现仍要求全市场前 3%/5%。

### Task 3: 最小实现状态公式并提升实时版本

**Files:**
- Modify: `alphaagent/server/services/limit_up/concept_resonance.py`
- Modify: `alphaagent/server/services/limit_up/versions.py`
- Modify: `tests/alphaagent/test_limit_up_history.py`
- Modify: `tests/alphaagent/test_limit_up_forward_validation.py`

- [x] **Step 1: 定义内部阈值并删除百分位状态门**

在 `concept_resonance.py` 中引入 `ceil` 并替换两个百分位常量：

```python
from math import ceil

CONCEPT_LAUNCH_MIN_RISE_RATIO = 0.80
CONCEPT_LAUNCH_MIN_MEDIAN_CHANGE_PCT = 2.5
CONCEPT_LAUNCH_MIN_STRONG_5_COUNT = 3
CONCEPT_LAUNCH_MIN_STRONG_5_RATIO = 0.05
CONCEPT_WARMING_MIN_RISE_RATIO = 0.65
CONCEPT_WARMING_MIN_MEDIAN_CHANGE_PCT = 1.0
CONCEPT_WARMING_MIN_STRONG_5_COUNT = 2
```

删除 `CONCEPT_WARMING_MAX_PERCENTILE` 和 `CONCEPT_LAUNCH_MAX_PERCENTILE`；概念评分和 `strength_percentile` 字段继续保留用于排序。

- [x] **Step 2: 实现绝对共振纯函数**

用以下实现替换 `concept_state()` 的启动和预热分支：

```python
def concept_state(row: Mapping[str, object]) -> str:
    if _float(row.get("coverage_ratio")) < CONCEPT_MIN_COVERAGE_RATIO:
        return "unavailable"
    touched = int(row.get("touched_count") or 0)
    failed_rate = _float(row.get("failed_count")) / max(touched, 1)
    if touched >= 3 and failed_rate > CONCEPT_EBB_FAILED_RATE:
        return "ebb"

    observed = max(int(row.get("observed_count") or 0), 0)
    strong_5_required = max(
        CONCEPT_LAUNCH_MIN_STRONG_5_COUNT,
        ceil(observed * CONCEPT_LAUNCH_MIN_STRONG_5_RATIO),
    )
    if (
        _float(row.get("rise_ratio")) >= CONCEPT_LAUNCH_MIN_RISE_RATIO
        and _float(row.get("median_change_pct"))
        >= CONCEPT_LAUNCH_MIN_MEDIAN_CHANGE_PCT
        and int(row.get("strong_5_count") or 0) >= strong_5_required
        and (
            int(row.get("near_limit_count") or 0) >= 1
            or int(row.get("strong_7_count") or 0) >= 2
        )
    ):
        return "launch"
    if (
        _float(row.get("rise_ratio")) >= CONCEPT_WARMING_MIN_RISE_RATIO
        and _float(row.get("median_change_pct"))
        >= CONCEPT_WARMING_MIN_MEDIAN_CHANGE_PCT
        and int(row.get("strong_5_count") or 0)
        >= CONCEPT_WARMING_MIN_STRONG_5_COUNT
        and _float(row.get("change_acceleration_3m")) > 0
    ):
        return "warming"
    return "observe"
```

- [x] **Step 3: 提升实时证据版本**

```python
LIVE_STRATEGY_VERSION = "limit-up-live-v5"
```

保持 `HISTORY_STRATEGY_VERSION = "limit-up-history-v14"` 和已经存在的
`WALK_FORWARD_MODEL_VERSION = "limit-up-walk-forward-v5"` 不变。在
`tests/alphaagent/test_limit_up_history.py` 同步断言：

```python
assert versions.LIVE_STRATEGY_VERSION == "limit-up-live-v5"
```

同时把 `test_limit_up_forward_validation.py` 中验证快照查询版本的固定断言同步为
`limit-up-live-v5`。

- [x] **Step 4: 运行定向测试**

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_concept_resonance.py \
  tests/alphaagent/test_limit_up_history.py \
  tests/alphaagent/test_limit_up_forward_validation.py -q
```

Expected: 全部 PASS；已有强度排名测试继续证明排名字段未被删除。

### Task 4: 重放真实概念截面并检查影响范围

**Files:**
- Read: `alphaagent/server/services/limit_up/concept_snapshot_repository.py`
- Read: `requirements/alphaagent_limit_up_absolute_concept_launch_design.md`

- [x] **Step 1: 用实现后的纯函数重放保存截面**

```bash
docker compose run --rm --no-deps alphaagent-api python - <<'PY'
from collections import defaultdict
from datetime import date
from sqlalchemy import select
from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.limit_up.concept_resonance import concept_state

with session_scope() as session:
    rows = session.execute(
        select(schema.limit_up_concept_strength_snapshots)
        .where(schema.limit_up_concept_strength_snapshots.c.trade_date == date(2026, 7, 15))
        .order_by(schema.limit_up_concept_strength_snapshots.c.captured_at)
    ).mappings().all()

by_minute = defaultdict(int)
by_concept = defaultdict(list)
for raw in rows:
    row = {**dict(raw), **dict(raw.get("metrics") or {})}
    state = concept_state(row)
    by_minute[raw["captured_minute"]] += int(state == "launch")
    by_concept[str(raw["concept_name"])].append((raw["captured_at"], state))

counts = sorted(by_minute.values())
print({
    "row_count": len(rows),
    "minute_count": len(counts),
    "average_launch": round(sum(counts) / len(counts), 2),
    "p90_launch": counts[int((len(counts) - 1) * 0.90)],
    "max_launch": max(counts),
})
for name in ("白酒", "酿酒概念", "文娱消费", "网络游戏"):
    launches = [captured_at for captured_at, state in by_concept[name] if state == "launch"]
    print(name, min(launches) if launches else None)
PY
```

Expected: 75,748 行、251 个分钟截面；平均启动约 14.30、P90 约 28、最大约 38。金种子酒和巨人网络相关概念不再因强度百分位略低而停留在预热/观察。

- [x] **Step 2: 核对没有未来数据和合同扩张**

```bash
rg -n "CONCEPT_(WARMING|LAUNCH)_MAX_PERCENTILE" alphaagent tests
git diff -- alphaagent/server/services/limit_up/concept_resonance.py alphaagent/server/services/limit_up/versions.py tests/alphaagent/test_limit_up_concept_resonance.py tests/alphaagent/test_limit_up_history.py
```

Expected: 旧百分位状态常量无引用；diff 只包含纯公式、测试和实时版本，未增加 API/前端字段。

### Task 5: 全部测试、账本重建和全回测

**Files:**
- Modify: `requirements/alphaagent_limit_up_absolute_concept_launch_design.md`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Create: `memory/06_backtests/limit_up_absolute_concept_launch_verification.md`

- [x] **Step 1: 运行全部打板后端回归**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_*.py tests/alphaagent/test_data_sync_schedule.py -q
```

Result: 当前测试集合 `545 passed`；旧 memory 中的 614 是此前测试集合数量。

- [x] **Step 2: 运行前端、编译和格式验证**

```bash
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
uv run python -m compileall -q alphaagent/server/services/limit_up tests/alphaagent
git diff --check
```

Result: 前端 15 个文件、`67 passed`；生产构建、Python 编译和 diff check 通过。

- [x] **Step 3: 收盘后构建 API 并重建 v14 账本**

```bash
docker compose up -d --build alphaagent-api
docker compose exec -T alphaagent-api python - <<'PY'
import json
import time
import urllib.request

base = "http://127.0.0.1:8000/api/limit-up"
request = urllib.request.Request(f"{base}/history/rebuild", method="POST")
print(json.load(urllib.request.urlopen(request)))
while True:
    status = json.load(urllib.request.urlopen(f"{base}/history/status"))["data"]
    coverage = status.get("coverage") or {}
    print(status.get("status"), coverage.get("persisted_days"), coverage.get("persisted_end"))
    if status.get("status") not in {"building", "running", "queued"}:
        break
    time.sleep(5)
PY
```

Result: `ready`，覆盖自然推进为 `2024-01-15..2026-07-15` 的 603 个可靠交易日。

- [x] **Step 4: 重跑并逐项比较全部回测**

重复 Task 1 Step 2 和 Step 3 的组合、四战法和八组代理入口命令，逐项比较：

```text
signal_count
buy_count / trade_count（闭合交易）
win_rate
total_return_pct
max_drawdown_pct
profit_factor
average_utilization_pct
double_cost.total_return_pct / win_rate / max_drawdown_pct
phase_summaries
```

Result: 历史代码路径不引用 `concept_state()`。重建时 2026-07-15 日线和两笔 D+1 退出结果
自然补齐，组合由 137 笔闭合、2 笔待退出变为 139 笔全部闭合；当前胜率 62.5899%、
复利 +224.0076%、最大回撤 -7.9408%。完整因果边界和各组结果见验证报告，不把输入日期
推进归因于实时公式。

- [x] **Step 5: 记录证据并更新当前事实**

在验证报告中写入：公式、真实截面重放数字、测试数、重建覆盖、组合和四战法对照、压力结果、数据边界。同步更新现有 memory overview：

```text
limit-up-live-v5
概念启动使用内部绝对共振；全市场强度仅排序
历史 v14 账户指标是否完全不变
2026-07-15 是设计样本，不是收益验证
```

不得把 2026-07-15 的功能重放称为样本外收益。

- [x] **Step 6: 运行态验收**

```bash
docker compose up -d --build alphaagent-api alphaagent-web
docker compose ps
docker compose exec -T alphaagent-api python -c "from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION, LIVE_STRATEGY_VERSION; print(HISTORY_STRATEGY_VERSION, LIVE_STRATEGY_VERSION)"
curl -fsS http://localhost:8080/health
git diff --check
```

Expected: 服务健康，容器输出 `limit-up-history-v14 limit-up-live-v5`，`/limit-up` 经 Gateway 正常返回；不执行 `git commit` 或 `git push`。
