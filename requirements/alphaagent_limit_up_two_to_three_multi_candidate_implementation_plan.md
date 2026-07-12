# AlphaAgent 二进三竞价与多候选组合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将二进三竞价质量分层和每日最多四只的多候选等权组合落实到历史账本、实时观察、交割单和回测页面。

**Architecture:** `lane_research.py` 继续作为唯一战法资格和组合选择边界，新增纯函数生成二进三质量字段，并用两阶段选择器输出确定性多候选组合。`history_service.py` 只负责基于已选择交易计算组合规模指标；`live_service.py` 只透传同一套质量字段。历史版本升级到 v10，旧 v9 数据不改写。

**Tech Stack:** Python 3.13、pandas、SQLAlchemy、pytest、FastAPI、React 18、TypeScript、TanStack Query、Vitest、Vite。

---

## 文件结构

- Modify: `alphaagent/server/services/limit_up/lane_research.py`：二进三质量字段、风险否决、排名和每日多候选选择。
- Modify: `alphaagent/server/services/limit_up/history_service.py`：多笔组合规模与行业集中度统计、交割字段。
- Modify: `alphaagent/server/services/limit_up/live_service.py`：实时候选透传质量层级与风险。
- Modify: `alphaagent/server/services/limit_up/versions.py`：历史账本版本升级为 v10。
- Modify: `frontend/src/api/limitUp.ts`：新增质量和组合规模类型。
- Modify: `frontend/src/pages/LimitUpPage.tsx`：紧凑显示交易日规模和二进三质量。
- Modify: `tests/alphaagent/test_limit_up_lanes.py`：规则、排序、多候选、交割和组合统计回归。
- Modify: `tests/alphaagent/test_limit_up_history.py`：v10 历史账本多候选持久化回归。
- Modify: `tests/alphaagent/test_limit_up_live.py`：实时质量字段透传和风险否决回归。
- Modify: `memory/06_backtests/limit_up_short_term_factor_research.md`：v10 真实重建结果。
- Modify: `memory/06_backtests/README.md`：当前打板基线索引。

### Task 1: 二进三质量分层和风险否决

**Files:**
- Modify: `tests/alphaagent/test_limit_up_lanes.py`
- Modify: `alphaagent/server/services/limit_up/lane_research.py`

- [ ] **Step 1: 写失败测试覆盖 A/B 层和风险栈**

在 `_candidate()` 现有默认值基础上增加以下测试：

```python
def test_two_to_three_marks_core_auction_quality() -> None:
    result = evaluate_lane_candidate(_candidate(
        prior_streak=2,
        target_board=3,
        auction_gap_pct=3.2,
        prior_turnover_rate=14.0,
        prior_amount_ratio_5d=1.6,
        prior_low_change_pct=0.5,
        prior_market_failed_rate=0.30,
        prior_market_two_to_three_rate=0.35,
        prior_board={
            "is_sealed": True,
            "first_limit_time": "10:08:00",
            "last_limit_time": "14:20:00",
            "open_times": 4,
        },
    ))

    assert result["decision"] == "eligible"
    assert result["two_to_three_quality_tier"] == "A"
    assert result["two_to_three_risk_count"] == 0
    assert result["two_to_three_risk_flags"] == []


def test_two_to_three_blocks_four_visible_risks() -> None:
    result = evaluate_lane_candidate(_candidate(
        prior_streak=2,
        target_board=3,
        auction_gap_pct=5.5,
        prior_turnover_rate=8.0,
        prior_amount_ratio_5d=1.0,
        financial_snapshot=None,
        prior_low_change_pct=-1.0,
        prior_market_failed_rate=0.40,
        prior_market_two_to_three_rate=0.35,
        prior_board={
            "is_sealed": True,
            "first_limit_time": "10:08:00",
            "last_limit_time": "14:20:00",
            "open_times": 4,
        },
    ))

    assert result["decision"] == "blocked"
    assert result["two_to_three_risk_count"] == 6
    assert "two_to_three_risk_stack" in result["blockers"]
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py -q -k "core_auction_quality or four_visible_risks"
```

Expected: FAIL，候选尚无 `two_to_three_quality_tier` 和风险字段。

- [ ] **Step 3: 实现纯质量函数并接入资格评估**

在 `lane_research.py` 新增：

```python
TWO_TO_THREE_RISK_LIMIT = 4


def _two_to_three_quality(candidate: Mapping[str, object]) -> dict[str, object]:
    gap = _number(candidate.get("auction_gap_pct"))
    turnover = _number(candidate.get("prior_turnover_rate"))
    amount = _number(candidate.get("prior_amount_ratio_5d"))
    prior_low = _number(candidate.get("prior_low_change_pct"))
    failed_rate = _number(candidate.get("prior_market_failed_rate"))
    financial = candidate.get("financial_snapshot")
    risks = [
        code
        for code, passed in (
            ("auction_gap_outside_core", gap is not None and 2 <= gap < 5),
            ("prior_turnover_outside_core", turnover is not None and 10 <= turnover < 20),
            ("prior_amount_ratio_outside_core", amount is not None and 1.2 <= amount < 2),
            ("financial_snapshot_missing", isinstance(financial, Mapping)),
            ("prior_low_below_zero", prior_low is not None and prior_low >= 0),
            ("prior_market_failed_rate_high", failed_rate is not None and failed_rate < 0.35),
        )
        if not passed
    ]
    return {
        "two_to_three_quality_tier": (
            "A"
            if gap is not None and 2 <= gap < 5
            and turnover is not None and 10 <= turnover < 20
            else "B"
        ),
        "two_to_three_risk_count": len(risks),
        "two_to_three_risk_flags": risks,
    }
```

`evaluate_lane_candidate()` 在二进三分支合并质量字段；风险数大于等于 4 时追加 `two_to_three_risk_stack`。非二进三候选返回 `two_to_three_quality_tier=None`、风险数 `0`、空风险列表，保持 API 类型稳定。

- [ ] **Step 4: 加入冻结的增强因子和排名分数**

在 `_two_to_three_rules()` 中为以下条件追加稳定代码：

```python
if open_times is not None and 3 <= open_times <= 6:
    favorable.append("prior_board_full_turnover_reseal")
if amount is not None and 1.2 <= amount < 2:
    favorable.append("prior_amount_ratio_balanced")
if isinstance(candidate.get("financial_snapshot"), Mapping):
    favorable.append("financial_snapshot_available")
if prior_low is not None and prior_low >= 0:
    favorable.append("prior_low_held_positive")
if failed_rate is not None and failed_rate < 0.35:
    favorable.append("prior_market_failed_rate_controlled")
if promotion is not None and promotion >= 0.30:
    favorable.append("prior_market_two_to_three_active")
```

`_lane_rank_score()` 调用以下固定加分函数，不根据新回测结果再调整：

```python
def _two_to_three_rank_adjustment(candidate: Mapping[str, object]) -> float:
    quality = _two_to_three_quality(candidate)
    board = candidate.get("prior_board")
    board = board if isinstance(board, Mapping) else {}
    open_times = _number(board.get("open_times"))
    amount = _number(candidate.get("prior_amount_ratio_5d"))
    prior_low = _number(candidate.get("prior_low_change_pct"))
    failed_rate = _number(candidate.get("prior_market_failed_rate"))
    promotion = _number(candidate.get("prior_market_two_to_three_rate"))
    score = 30.0 if quality["two_to_three_quality_tier"] == "A" else 0.0
    score += 12.0 if open_times is not None and 3 <= open_times <= 6 else 0.0
    score += 8.0 if amount is not None and 1.2 <= amount < 2 else 0.0
    score += 6.0 if isinstance(candidate.get("financial_snapshot"), Mapping) else 0.0
    score += 6.0 if prior_low is not None and prior_low >= 0 else 0.0
    score += 6.0 if failed_rate is not None and failed_rate < 0.35 else 0.0
    score += 6.0 if promotion is not None and promotion >= 0.30 else 0.0
    score -= float(quality["two_to_three_risk_count"]) * 8.0
    return score
```

- [ ] **Step 5: 运行二进三规则测试**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py -q -k "two_to_three or one_to_two or high_board"
```

Expected: PASS。

### Task 2: 每日最多四只的两阶段组合选择

**Files:**
- Modify: `tests/alphaagent/test_limit_up_lanes.py`
- Modify: `alphaagent/server/services/limit_up/lane_research.py`

- [ ] **Step 1: 写失败测试覆盖多选、行业上限和战法多样化**

```python
def _pre_evaluated_candidate(
    symbol: str,
    lane: str,
    *,
    industry_id: str,
    rank_score: float,
    quality_tier: str | None = None,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "name": symbol,
        "lane": lane,
        "decision": "eligible",
        "industry_id": industry_id,
        "industry_name": industry_id,
        "rank_score": rank_score,
        "two_to_three_quality_tier": quality_tier,
    }


def test_daily_portfolio_selects_multiple_candidates_from_one_lane() -> None:
    candidates = [
        _pre_evaluated_candidate(
            f"60000{index}.SSE",
            "two_to_three",
            industry_id=f"BK{index % 3}",
            rank_score=100 - index,
            quality_tier="A",
        )
        for index in range(1, 6)
    ]
    with patch(
        "alphaagent.server.services.limit_up.lane_research.evaluate_lane_candidate",
        side_effect=lambda candidate: dict(candidate),
    ):
        result = select_daily_lane_portfolio(candidates)

    assert len(result["selected"]) == 4
    assert {row["lane"] for row in result["selected"]} == {"two_to_three"}
    assert result["selected_counts_by_lane"] == {"two_to_three": 4}


def test_daily_portfolio_diversifies_before_filling_extra_slots() -> None:
    candidates = [
        _pre_evaluated_candidate("600001.SSE", "first_board", industry_id="BK1", rank_score=80),
        _pre_evaluated_candidate("600002.SSE", "one_to_two", industry_id="BK2", rank_score=80),
        _pre_evaluated_candidate("600003.SSE", "two_to_three", industry_id="BK3", rank_score=100, quality_tier="A"),
        _pre_evaluated_candidate("600004.SSE", "two_to_three", industry_id="BK4", rank_score=90, quality_tier="A"),
        _pre_evaluated_candidate("600005.SSE", "two_to_three", industry_id="BK5", rank_score=85, quality_tier="A"),
    ]
    with patch(
        "alphaagent.server.services.limit_up.lane_research.evaluate_lane_candidate",
        side_effect=lambda candidate: dict(candidate),
    ):
        result = select_daily_lane_portfolio(candidates)

    assert [row["vt_symbol"] for row in result["selected"][:3]] == [
        "600001.SSE",
        "600002.SSE",
        "600003.SSE",
    ]
    assert len(result["selected"]) == 4
```

补充同行业超过两只、重复股票和 `max_total=0` 测试。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py -q -k "multiple_candidates or diversifies or industry_limit or max_total"
```

Expected: FAIL，当前 `max_per_lane=1`。

- [ ] **Step 3: 实现确定性的两阶段选择**

删除 `max_per_lane` 参数。每条 lane 保留最多 `max_total` 个展示候选；使用 `_append_if_allowed()` 统一检查总数、行业数和同股去重：

```python
def _append_if_allowed(
    selected: list[dict[str, object]],
    candidate: Mapping[str, object],
    *,
    max_total: int,
    max_per_industry: int,
    industry_counts: dict[str, int],
    selected_symbols: set[str],
) -> bool:
    if len(selected) >= max_total or candidate.get("decision") != "eligible":
        return False
    symbol = str(candidate.get("vt_symbol") or "")
    industry = str(candidate.get("industry_id") or candidate.get("industry_name") or "")
    if not symbol or symbol in selected_symbols:
        return False
    if industry and industry_counts[industry] >= max_per_industry:
        return False
    selected.append(dict(candidate))
    selected_symbols.add(symbol)
    if industry:
        industry_counts[industry] += 1
    return True
```

第一阶段对每条 lane 顺序扫描到首个可加入候选；第二阶段将剩余候选按 A 级、standard、`rank_score`、lane rank、symbol 排序补位。返回 selection policy 和按 lane/industry 计数。

- [ ] **Step 4: 运行完整 lane 测试**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交规则和选择器**

```bash
git add alphaagent/server/services/limit_up/lane_research.py tests/alphaagent/test_limit_up_lanes.py
git commit -m "feat(limit-up): rank and select multiple auction candidates"
```

### Task 3: 多候选回测统计和交割字段

**Files:**
- Modify: `tests/alphaagent/test_limit_up_lanes.py`
- Modify: `tests/alphaagent/test_limit_up_history.py`
- Modify: `alphaagent/server/services/limit_up/history_service.py`

- [ ] **Step 1: 写失败测试覆盖等权、规模和集中度**

构造同一 entry date 两笔收益 `+10%/-2%`、不同行业的闭合交易，断言：

```python
assert report["daily_results"][0]["daily_return_pct"] == 4.0
assert report["summary"]["trade_day_count"] == 1
assert report["summary"]["average_trades_per_day"] == 2.0
assert report["summary"]["max_trades_per_day"] == 2
assert report["summary"]["max_industry_concentration_pct"] == 50.0
```

再构造同一行业两笔，断言集中度为 `100.0`；历史日 payload 包含同 lane 两个 selected 时，ledger 和 backtest 均返回两笔。

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_history.py -q -k "multiple or concentration or average_trades"
```

Expected: FAIL，summary 尚无组合规模字段。

- [ ] **Step 3: 实现组合规模统计**

在 `history_service.py` 新增 `_portfolio_scale_summary(trades)`，按 `entry_date` 分组；每日行业集中度为当天最大行业计数除以当天交易数。`_summary()` 合并该结果，空交易返回 `trade_day_count=0`、`average_trades_per_day=0.0`、`max_trades_per_day=0`、`max_industry_concentration_pct=None`。

- [ ] **Step 4: 透传二进三质量字段到交割单**

`_ledger_trade()` 增加：

```python
"two_to_three_quality_tier": candidate.get("two_to_three_quality_tier"),
"two_to_three_risk_count": candidate.get("two_to_three_risk_count"),
"two_to_three_risk_flags": candidate.get("two_to_three_risk_flags") or [],
```

- [ ] **Step 5: 运行历史和 lane 测试**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_history.py -q
```

Expected: PASS。

### Task 4: 实时字段、前端紧凑展示和版本升级

**Files:**
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `alphaagent/server/services/limit_up/versions.py`
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`

- [ ] **Step 1: 写实时失败测试**

构造 lane feature ready 的二进三竞价候选，断言 `_attach_lane_decisions()` 之后包含：

```python
assert candidate["lane_quality_tier"] == "A"
assert candidate["lane_risk_count"] == 0
assert candidate["lane_risk_flags"] == []
```

构造四项风险，断言 `lane_decision == "blocked"`。

- [ ] **Step 2: 实现实时透传并运行测试**

`live_service.py` 从 `evaluate_lane_candidate()` 复制质量层、风险数和风险列表到实时候选，不在实时层复制规则。

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q -k "lane_quality or lane_decision"
```

Expected: PASS。

- [ ] **Step 3: 升级历史版本**

`versions.py`：

```python
HISTORY_STRATEGY_VERSION = "limit-up-history-v10"
```

保留 live 和 walk-forward 版本不变；它们的缓存键已经包含 history version。

- [ ] **Step 4: 更新前端类型和紧凑显示**

`LimitUpEntrySummary` 增加四个组合规模字段；`LimitUpLaneLedgerTrade` 增加质量层和风险字段。回测“交易”单元显示总笔数，下一行显示 `交易日 / 日均 / 单日最多`。二进三交易的买点单元追加 `A级` 或 `B级 · 风险N`，不新增卡片或页面区域。

- [ ] **Step 5: 运行前端测试和构建**

Run:

```bash
pnpm --dir frontend test
pnpm --dir frontend run build
```

Expected: Vitest、TypeScript 和 Vite 全部通过，仅允许现有 chunk size warning。

- [ ] **Step 6: 提交服务和界面**

```bash
git add alphaagent/server/services/limit_up/history_service.py alphaagent/server/services/limit_up/live_service.py alphaagent/server/services/limit_up/versions.py tests/alphaagent/test_limit_up_history.py tests/alphaagent/test_limit_up_live.py frontend/src/api/limitUp.ts frontend/src/pages/LimitUpPage.tsx
git commit -m "feat(limit-up): expose multi-candidate portfolio results"
```

### Task 5: 重建 v10、全历史对照和最终验证

**Files:**
- Modify: `memory/06_backtests/limit_up_short_term_factor_research.md`
- Modify: `memory/06_backtests/README.md`

- [ ] **Step 1: 在运行容器中重建 v10 账本**

先重建 API 镜像，再调用同步重建入口：

```bash
docker compose up -d --build alphaagent-api alphaagent-web
docker compose exec -T alphaagent-api python -c 'from alphaagent.server.services.limit_up.history_service import rebuild_history_sync; print(rebuild_history_sync())'
```

Expected: `strategy_version=limit-up-history-v10`、`persisted_days=600`、结束日达到最新完整日线。

- [ ] **Step 2: 导出 v10 四战法双卖点报告**

调用 `get_lane_history_backtest()`，至少保存和核对：

- 二进三 D+1 开盘、D+1 收盘。
- 全样本、expanding OOS、locked holdout、post-freeze forward。
- 总笔数、交易日数、日均笔数、单日最多、胜率、平均收益、复利、回撤、硬亏损和行业集中度。
- 每日 0/1/2/3/4 只的日期分布。

Expected: 报告明确 v10 是多候选且 `simulation_eligible=false`，不得因历史改善自动通过。

- [ ] **Step 3: 更新长期回测证据**

在 `limit_up_short_term_factor_research.md` 用当前结果替换 v9 当前基线，保留 v9 对照表；在 `README.md` 只更新 `/limit-up` 段，不改普通量化版本记录。

- [ ] **Step 4: 运行完整相关验证**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_*.py tests/alphaagent/test_market_snapshot_repository.py -q
uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_akshare_adapter.py tests/alphaagent/test_quant_backtest_portfolio.py -q -k "tdx or limit_up or auction or live_scan"
python -m compileall -q alphaagent/server/services/limit_up
pnpm --dir frontend test
pnpm --dir frontend run build
git diff --check
```

Expected: 所有测试、编译、构建和差异检查通过。

- [ ] **Step 5: 审计提交范围并提交证据**

确认暂存文件不包含 `alphaagent/market/boards.py`、主线、普通量化、D2 事件研究或 19:00 调度重构。

```bash
git add memory/06_backtests/limit_up_short_term_factor_research.md memory/06_backtests/README.md
git commit -m "docs(limit-up): record v10 multi-candidate replay"
```

- [ ] **Step 6: 最终状态检查**

```bash
git log -4 --oneline
git status --short
```

Expected: 新提交存在；索引为空；用户原有无关工作区改动仍保留；不执行 push。
