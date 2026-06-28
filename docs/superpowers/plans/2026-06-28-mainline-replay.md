# 主线回放（Mainline Replay）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `/mainline` 页面，合并并替代现有 `/explore`（主线探索）与 `/chain`（产业链），支持历史日期回放主线板块榜/大盘/资金、区间 delta 计算、以及从行情反推的板块关联面板。

**Architecture:** 后端算法抽成**纯函数**（`services/mainline_replay.py`，无 DB 依赖，TDD 可测）+ API 薄层（`api/mainline_replay.py`，查 DB → 调纯函数 → `ok()` 包装）；前端 `/mainline` 页面三栏布局，复用现有 `apiClient` + tailwind 设计系统。

**Tech Stack:** FastAPI + SQLAlchemy Core（后端）；React + TypeScript + react-router v6 + tailwind + @tanstack/react-query（前端）；pytest（测试）。

**命名约定（重要）：** 现有 `/api/replay` 已被"策略回测"语义占用（`strategy_replay_runs` 表），本功能统一用 `mainline`：后端前缀 `/mainline-replay`，前端路由 `/mainline`，菜单"主线回放"。设计文档 `2026-06-28-mainline-replay-design.md` 中的 `/replay` 字样应同步改为本命名。

**Commit 约定：** 项目 `AGENTS.md` 规定不主动 `git commit`。本计划中的 commit 步骤默认跳过，变更保留在工作区供用户审阅；用户明确授权后再统一提交。

---

## File Structure

**后端（新建）：**
- `alphaagent/server/services/mainline_replay.py` — 算法纯函数（delta 计算、归一化、关联反推）。单一职责：纯计算，无 DB/IO。
- `alphaagent/server/api/mainline_replay.py` — 3 个端点（timeline/snapshot/relation），薄层：查 DB → 调算法 → `ok()`。
- `tests/alphaagent/test_mainline_replay_algo.py` — 算法纯函数 TDD 测试。
- `tests/alphaagent/test_mainline_replay_api.py` — API 契约测试。

**后端（修改）：**
- `alphaagent/server/api/router.py` — 注册新 router（2 行）。

**前端（新建）：**
- `frontend/src/api/mainlineReplay.ts` — API 客户端 + 类型。
- `frontend/src/pages/MainlineReplayPage.tsx` — 主页面（时间轴 + 三栏）。
- `frontend/src/features/replay/RelationPanel.tsx` — 关联面板组件。

**前端（修改）：**
- `frontend/src/App.tsx` — 加路由（2 行）。
- `frontend/src/components/AppShell.tsx` — 加菜单项（1 行）。

---

## Task 1: 后端算法 — 区间 delta + 归一化（纯函数，TDD）

**Files:**
- Create: `alphaagent/server/services/mainline_replay.py`
- Test: `tests/alphaagent/test_mainline_replay_algo.py`

- [ ] **Step 1: 写失败测试（delta + 归一化 + fund_strength）**

创建 `tests/alphaagent/test_mainline_replay_algo.py`：

```python
"""Tests for mainline replay pure-function algorithms."""

from alphaagent.server.services.mainline_replay import (
    compute_raw_sector_delta,
    minmax_normalize,
    compute_fund_strength_batch,
)


def test_return_pct_from_close_prices():
    raw = compute_raw_sector_delta(
        bars_t1_close=100.0,
        bars_t2_close=110.0,
        range_turnover=[1e8, 2e8],
        prev_range_turnover=[1e8, 1e8],
        score_t1={"heat_score": 60.0, "fund_score": 55.0, "trend_state": "ROTATION", "rank_return": 10},
        score_t2={"heat_score": 75.0, "fund_score": 70.0, "trend_state": "MAINLINE_UP", "rank_return": 3},
        range_main_inflow=[5e7, 8e7],
    )
    assert raw["return_pct"] == 0.10
    assert raw["accumulated_turnover"] == 3e8
    assert raw["volume_ratio"] == 1.5  # avg(1.5e8) / avg(1e8)
    assert raw["delta_heat"] == 15.0
    assert raw["delta_fund"] == 15.0
    assert raw["trend_transition"] == "ROTATION->MAINLINE_UP"
    assert raw["rank_change"] == -7  # 3 - 10
    assert raw["accumulated_main_inflow"] == 1.3e8
    assert raw["fund_inflow_available"] is True


def test_fund_inflow_unavailable_when_none():
    raw = compute_raw_sector_delta(
        bars_t1_close=100.0,
        bars_t2_close=100.0,
        range_turnover=[1e8],
        prev_range_turnover=[1e8],
        score_t1=None,
        score_t2=None,
        range_main_inflow=None,
    )
    assert raw["fund_inflow_available"] is False
    assert raw["accumulated_main_inflow"] is None
    assert raw["delta_heat"] is None  # score 缺失


def test_minmax_normalize_basic():
    assert minmax_normalize([0.0, 5.0, 10.0]) == [0.0, 0.5, 1.0]


def test_minmax_normalize_empty():
    assert minmax_normalize([]) == []


def test_minmax_normalize_constant_returns_mid():
    # 全相等：返回 0.5 中值，避免都 0 导致 fund_strength 排序失效
    assert minmax_normalize([3.0, 3.0, 3.0]) == [0.5, 0.5, 0.5]


def test_fund_strength_batch_weights_and_range():
    raws = [
        {"return_pct": 0.10, "volume_ratio": 1.5, "delta_fund": 15.0, "delta_heat": 15.0},
        {"return_pct": -0.05, "volume_ratio": 0.8, "delta_fund": -10.0, "delta_heat": -5.0},
    ]
    strengths = compute_fund_strength_batch(raws)
    assert len(strengths) == 2
    assert strengths[0] > strengths[1]  # 涨的板块更强
    for s in strengths:
        assert 0.0 <= s <= 1.0


def test_fund_strength_batch_skips_incomplete():
    raws = [
        {"return_pct": 0.10, "volume_ratio": 1.5, "delta_fund": 15.0, "delta_heat": 15.0},
        {"return_pct": None, "volume_ratio": 1.5, "delta_fund": 15.0, "delta_heat": 15.0},
    ]
    strengths = compute_fund_strength_batch(raws)
    assert strengths[0] is not None
    assert strengths[1] is None
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd /root/project/ai/vnpy && pytest tests/alphaagent/test_mainline_replay_algo.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'alphaagent.server.services.mainline_replay'`）

- [ ] **Step 3: 实现算法纯函数**

创建 `alphaagent/server/services/mainline_replay.py`：

```python
"""Mainline replay pure-function algorithms.

No DB / IO dependencies — accept already-queried data, return computed
results. This keeps the delta + relation logic unit-testable with fixed
fixtures (TDD) and lets the API layer stay a thin wrapper.
"""

from __future__ import annotations

from typing import Any

# fund_strength 各维度权重（和为 1.0）。设计文档 4.1-D。
_FUND_STRENGTH_WEIGHTS = {"return_pct": 0.30, "volume_ratio": 0.30, "delta_fund": 0.25, "delta_heat": 0.15}


def compute_raw_sector_delta(
    *,
    bars_t1_close: float | None,
    bars_t2_close: float | None,
    range_turnover: list[float],
    prev_range_turnover: list[float],
    score_t1: dict[str, Any] | None,
    score_t2: dict[str, Any] | None,
    range_main_inflow: list[float] | None,
) -> dict[str, Any]:
    """Compute raw (pre-normalization) delta metrics for one sector over [T1, T2].

    All inputs are already-queried scalars/lists; this function does no IO.
    None inputs propagate to None outputs (caller may render "n/a").
    """
    # 行情维度（sector_daily_bars）
    return_pct: float | None = None
    if bars_t1_close and bars_t2_close and bars_t1_close != 0:
        return_pct = bars_t2_close / bars_t1_close - 1.0

    accumulated_turnover: float | None = sum(range_turnover) if range_turnover else None

    volume_ratio: float | None = None
    if range_turnover and prev_range_turnover:
        avg_prev = sum(prev_range_turnover) / len(prev_range_turnover)
        avg_curr = sum(range_turnover) / len(range_turnover)
        if avg_prev != 0:
            volume_ratio = avg_curr / avg_prev

    # 热度维度（sector_period_scores）
    delta_heat = _safe_delta(score_t2, score_t1, "heat_score")
    delta_fund = _safe_delta(score_t2, score_t1, "fund_score")

    trend_transition: str | None = None
    if score_t1 and score_t2:
        s1 = score_t1.get("trend_state")
        s2 = score_t2.get("trend_state")
        if s1 and s2:
            trend_transition = f"{s1}->{s2}"

    rank_change: int | None = None
    r1 = score_t1.get("rank_return") if score_t1 else None
    r2 = score_t2.get("rank_return") if score_t2 else None
    if r1 is not None and r2 is not None:
        rank_change = r2 - r1

    # 资金流维度（sector_fund_flows，仅近端）
    accumulated_main_inflow: float | None = None
    fund_inflow_available = bool(range_main_inflow)
    if fund_inflow_available:
        accumulated_main_inflow = sum(range_main_inflow)  # type: ignore[arg-type]

    return {
        "return_pct": return_pct,
        "accumulated_turnover": accumulated_turnover,
        "volume_ratio": volume_ratio,
        "delta_heat": delta_heat,
        "delta_fund": delta_fund,
        "trend_transition": trend_transition,
        "rank_change": rank_change,
        "accumulated_main_inflow": accumulated_main_inflow,
        "fund_inflow_available": fund_inflow_available,
    }


def _safe_delta(s2: dict | None, s1: dict | None, key: str) -> float | None:
    v1 = s1.get(key) if s1 else None
    v2 = s2.get(key) if s2 else None
    if v1 is None or v2 is None:
        return None
    return v2 - v1


def minmax_normalize(values: list[float]) -> list[float]:
    """Min-max normalize to [0, 1]. Empty -> []. All-equal -> 0.5 (mid, keeps ordering sane)."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def compute_fund_strength_batch(raws: list[dict[str, Any]]) -> list[float | None]:
    """Compute综合资金强弱 fund_strength for a batch of raw deltas.

    归一化在每个维度上对全批做 min-max，再按权重加权。
    任一维度缺失的板块返回 None（前端标注"数据不足"）。
    """
    keys = list(_FUND_STRENGTH_WEIGHTS.keys())
    normed: dict[str, list[float | None]] = {k: [None] * len(raws) for k in keys}
    for k in keys:
        col = [r.get(k) for r in raws]
        idxs = [i for i, v in enumerate(col) if v is not None]
        if not idxs:
            continue
        nn = [col[i] for i in idxs]  # type: ignore[index]
        for j, nv in enumerate(minmax_normalize(nn)):
            normed[k][idxs[j]] = nv

    out: list[float | None] = []
    for i in range(len(raws)):
        parts = [normed[k][i] for k in keys]
        if any(p is None for p in parts):
            out.append(None)
            continue
        s = sum(_FUND_STRENGTH_WEIGHTS[k] * normed[k][i] for k in keys)  # type: ignore[index]
        out.append(round(s, 4))
    return out
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd /root/project/ai/vnpy && pytest tests/alphaagent/test_mainline_replay_algo.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit（项目规则默认跳过，留工作区）**

---

## Task 2: 后端算法 — 关联反推（纯函数，TDD）

**Files:**
- Modify: `alphaagent/server/services/mainline_replay.py`（追加 `pearson` + `compute_relations`）
- Test: `tests/alphaagent/test_mainline_replay_algo.py`（追加测试）

- [ ] **Step 1: 追加失败测试（pearson + relations）**

在 `tests/alphaagent/test_mainline_replay_algo.py` 末尾追加：

```python
from alphaagent.server.services.mainline_replay import pearson, compute_relations


def test_pearson_perfect_positive():
    assert pearson([1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0]) == 1.0


def test_pearson_too_few_returns_none():
    assert pearson([1.0, 2.0], [2.0, 3.0]) is None


def test_pearson_zero_variance_returns_none():
    assert pearson([3.0, 3.0, 3.0], [1.0, 2.0, 3.0]) is None


def _make_returns(base: float, shocks: list[float]) -> list[float]:
    return [base + s for s in shocks]


def test_relation_high_correlation_ranks_high():
    # 目标与候选A高度共振，与候选B相反
    target = _make_returns(0.0, [0.01, 0.02, -0.01, 0.03, 0.0, 0.02, -0.02, 0.01, 0.03, 0.02,
                                  0.01, -0.01, 0.02, 0.03, 0.0, 0.01, 0.02, -0.01, 0.03, 0.02])
    cand_a = _make_returns(0.0, [s * 1.1 for s in target])   # 强正相关
    cand_b = _make_returns(0.0, [-s for s in target])        # 强负相关
    res = compute_relations(
        target_returns=target,
        candidate_returns={"A": cand_a, "B": cand_b},
        target_fund=None,
        candidate_fund=None,
        target_members={"600001.SSE", "600002.SSE"},
        candidate_members={"A": {"600001.SSE", "600003.SSE"}, "B": {"600999.SSE"}},
    )
    by_id = {r["sector_id"]: r for r in res}
    assert by_id["A"]["relation_score"] > by_id["B"]["relation_score"]
    assert by_id["A"]["corr"] > 0.8
    assert 0.0 <= by_id["A"]["relation_score"] <= 1.0
    # A 与目标共享 1 股，B 不共享
    assert by_id["A"]["overlap_count"] == 1
    assert "corr" in by_id["A"]["reason"]


def test_relation_top_n_limit():
    target = _make_returns(0.0, [0.01 * i for i in range(20)])
    cands = {f"C{i}": _make_returns(0.0, [0.01 * i + 0.001 * (i % 3) for i in range(20)]) for i in range(15)}
    cands_members = {k: set() for k in cands}
    res = compute_relations(
        target_returns=target,
        candidate_returns=cands,
        target_fund=None,
        candidate_fund=None,
        target_members=set(),
        candidate_members=cands_members,
        top_n=5,
    )
    assert len(res) == 5
    assert res == sorted(res, key=lambda r: r["relation_score"], reverse=True)
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd /root/project/ai/vnpy && pytest tests/alphaagent/test_mainline_replay_algo.py -v -k "pearson or relation"`
Expected: FAIL（`ImportError: cannot import name 'pearson'`）

- [ ] **Step 3: 实现 pearson + compute_relations**

在 `alphaagent/server/services/mainline_replay.py` 末尾追加：

```python
import math

# 关联度各维度权重（设计文档 4.2）。corr=涨跌共振(主)，fund_corr=资金共振，overlap=成分重叠。
_RELATION_WEIGHTS = {"corr": 0.55, "fund_corr": 0.25, "overlap": 0.20}


def pearson(x: list[float], y: list[float]) -> float | None:
    """Pearson correlation. Returns None if <3 pairs or zero variance."""
    n = min(len(x), len(y))
    if n < 3:
        return None
    xs, ys = x[:n], y[:n]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    vx = sum((a - mx) ** 2 for a in xs)
    vy = sum((b - my) ** 2 for b in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def _norm_corr(c: float | None) -> float:
    # 把 [-1,1] 的相关系数映射到 [0,1]（-1→0, 0→0.5, 1→1）
    if c is None:
        return 0.5  # 数据不足时给中性，不强烈加分也不扣分
    return (c + 1.0) / 2.0


def compute_relations(
    *,
    target_returns: list[float],
    candidate_returns: dict[str, list[float]],
    target_fund: list[float] | None,
    candidate_fund: dict[str, list[float]] | None,
    target_members: set[str],
    candidate_members: dict[str, set[str]],
    weights: dict[str, float] | None = None,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Rank candidate sectors by 行情反推 relation to target, return top-N.

    relation_score = w_corr*norm(corr) + w_fund*norm(fund_corr) + w_overlap*jaccard
    """
    w = weights or _RELATION_WEIGHTS
    results: list[dict[str, Any]] = []
    for cid, cret in candidate_returns.items():
        corr = pearson(target_returns, cret)
        fund_corr = None
        if target_fund and candidate_fund and cid in candidate_fund:
            fund_corr = pearson(target_fund, candidate_fund[cid])
        cmembers = candidate_members.get(cid, set())
        union = target_members | cmembers
        overlap = (len(target_members & cmembers) / len(union)) if union else 0.0
        overlap_count = len(target_members & cmembers)

        score = (
            w["corr"] * _norm_corr(corr)
            + w["fund_corr"] * _norm_corr(fund_corr)
            + w["overlap"] * overlap
        )
        reason_parts = [f"共振{corr:.2f}" if corr is not None else "共振n/a"]
        if fund_corr is not None:
            reason_parts.append(f"资金{fund_corr:.2f}")
        if overlap_count:
            reason_parts.append(f"重叠{overlap_count}股")

        results.append({
            "sector_id": cid,
            "relation_score": round(score, 4),
            "corr": round(corr, 4) if corr is not None else None,
            "fund_corr": round(fund_corr, 4) if fund_corr is not None else None,
            "overlap": round(overlap, 4),
            "overlap_count": overlap_count,
            "reason": " · ".join(reason_parts),
        })
    results.sort(key=lambda r: r["relation_score"], reverse=True)
    return results[:top_n]
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd /root/project/ai/vnpy && pytest tests/alphaagent/test_mainline_replay_algo.py -v`
Expected: all passed（含 Task1 + Task2 全部）

- [ ] **Step 5: Commit（默认跳过）**

---

## Task 3: 后端 API — 三个端点

**Files:**
- Create: `alphaagent/server/api/mainline_replay.py`

- [ ] **Step 1: 实现 timeline + snapshot + relation 端点**

创建 `alphaagent/server/api/mainline_replay.py`：

```python
"""Mainline replay API — 历史日期回放主线板块/大盘/资金 + 行情反推关联.

Provides:
  - GET /api/mainline-replay/timeline  可回放的交易日列表
  - GET /api/mainline-replay/snapshot  单日快照(date) 或 区间delta(t1+t2)
  - GET /api/mainline-replay/relation  指定板块在指定日期的关联板块(行情反推)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.sql import func

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.db import schema
from alphaagent.server.db.session import is_database_configured, session_scope
from alphaagent.server.services.mainline_replay import (
    compute_fund_strength_batch,
    compute_raw_sector_delta,
    compute_relations,
)

router = APIRouter(prefix="/mainline-replay", tags=["mainline-replay"])

# 大盘指数 vt_symbol（与 alphaagent.market.symbols.INDEX_SYMBOLS 一致）
_INDEX_VT_SYMBOLS = ["000001.SSE", "399001.SZSE", "399006.SZSE", "000300.SSE", "000905.SSE", "000852.SSE", "000688.SSE"]
_DEFAULT_PERIOD = "20d"
_WINDOW_DAYS = 20  # 关联反推的行情窗口


@router.get("/timeline", response_model=None)
def timeline(limit: int = Query(400, ge=1, le=2000)) -> dict[str, Any]:
    """可回放的交易日列表（sector_period_scores 里存在的 as_of_date 去重降序）。"""
    if not is_database_configured():
        return ok({"dates": [], "status": "unavailable", "message": "数据库未配置"})
    with session_scope() as session:
        rows = session.execute(
            select(schema.sector_period_scores.c.as_of_date)
            .where(schema.sector_period_scores.c.period == _DEFAULT_PERIOD)
            .group_by(schema.sector_period_scores.c.as_of_date)
            .order_by(desc(schema.sector_period_scores.c.as_of_date))
            .limit(limit)
        ).all()
    dates = [str(r[0]) for r in rows]
    return ok({"dates": dates, "status": "ready" if dates else "empty"})


@router.get("/snapshot", response_model=None)
def snapshot(
    date: date | None = Query(None, description="单日快照日期 YYYY-MM-DD"),
    t1: date | None = Query(None, description="区间起点"),
    t2: date | None = Query(None, description="区间终点"),
    sector_type: str | None = Query(None, description="板块类型过滤"),
    limit: int = Query(50, ge=1, le=300),
) -> dict[str, Any]:
    """单日快照(date) 或 区间delta(t1+t2)。

    返回主线板块榜(按 heat_score/fund_strength)、大盘指数、资金流。
    """
    if not is_database_configured():
        return ok({"status": "unavailable", "message": "数据库未配置"})
    if date is None and (t1 is None or t2 is None):
        return JSONResponse(status_code=400, content=fail("BAD_PARAMS", "需要 date 或 (t1,t2)", {}))

    with session_scope() as session:
        # —— 主线板块榜：按 date 或 (t1,t2) 取 sector_period_scores
        sectors_meta = _load_sectors_meta(session)
        if date is not None:
            ranking = _ranking_for_date(session, date, sector_type, limit)
            mode = "single"
        else:
            ranking = _ranking_for_range(session, t1, t2, sector_type, limit)  # type: ignore[arg-type]
            mode = "delta"

        # —— 大盘指数（单日用 date，区间用 t2 当日 + 区间涨跌）
        index_data = _load_index(session, date or t2)  # type: ignore[arg-type]

        # —— 注入板块名
        for item in ranking:
            meta = sectors_meta.get(item["sector_id"], {})
            item["name"] = meta.get("name", item["sector_id"])
            item["sector_type"] = meta.get("type")

    return ok({"mode": mode, "ranking": ranking, "index": index_data, "status": "ready"})


@router.get("/relation", response_model=None)
def relation(
    sector_id: str = Query(..., description="目标板块ID"),
    date: date = Query(..., description="回放日期 YYYY-MM-DD"),
    limit: int = Query(12, ge=1, le=50),
) -> dict[str, Any]:
    """指定板块在指定日期的关联板块（行情反推，涨跌共振为主权重）。"""
    if not is_database_configured():
        return ok({"status": "unavailable", "message": "数据库未配置"})
    window_start = date - timedelta(days=_WINDOW_DAYS * 2)  # 日历日放宽，过滤交易日

    with session_scope() as session:
        # 目标板块 [window, date] 日线 change_pct
        tgt_rows = session.execute(
            select(schema.sector_daily_bars.c.trade_date, schema.sector_daily_bars.c.change_pct)
            .where(schema.sector_daily_bars.c.sector_id == sector_id,
                   schema.sector_daily_bars.c.trade_date > window_start,
                   schema.sector_daily_bars.c.trade_date <= date)
            .order_by(schema.sector_daily_bars.c.trade_date)
        ).all()
        if len(tgt_rows) < 3:
            return ok({"target": sector_id, "items": [], "status": "insufficient_data"})
        tgt_dates = [r[0] for r in tgt_rows]
        tgt_returns = [float(r[1] or 0.0) for r in tgt_rows]

        # 候选：与目标共享成分股的板块（sector_memberships 反查）
        tgt_members = {r[0] for r in session.execute(
            select(schema.sector_memberships.c.vt_symbol)
            .where(schema.sector_memberships.c.sector_id == sector_id)
        ).all()}
        cand_rows = session.execute(
            select(schema.sector_memberships.c.sector_id, schema.sector_memberships.c.vt_symbol)
            .where(schema.sector_memberships.c.vt_symbol.in_(tgt_members))
            .where(schema.sector_memberships.c.sector_id != sector_id)
        ).all()
        cand_members: dict[str, set[str]] = {}
        for sid, vsym in cand_rows:
            cand_members.setdefault(sid, set()).add(vsym)
        cand_ids = list(cand_members.keys())[:200]  # 限候选规模

        # 候选板块同期 change_pct（按目标日期对齐）
        cand_returns: dict[str, list[float]] = {}
        if cand_ids:
            bar_rows = session.execute(
                select(schema.sector_daily_bars.c.sector_id, schema.sector_daily_bars.c.trade_date, schema.sector_daily_bars.c.change_pct)
                .where(schema.sector_daily_bars.c.sector_id.in_(cand_ids),
                       schema.sector_daily_bars.c.trade_date.in_(tgt_dates))
            ).all()
            by_sid: dict[str, dict] = {}
            for sid, d, pct in bar_rows:
                by_sid.setdefault(sid, {})[d] = float(pct or 0.0)
            for sid in cand_ids:
                m = by_sid.get(sid, {})
                cand_returns[sid] = [m.get(d, 0.0) for d in tgt_dates]

        sectors_meta = _load_sectors_meta(session)
        items = compute_relations(
            target_returns=tgt_returns,
            candidate_returns=cand_returns,
            target_fund=None,
            candidate_fund=None,
            target_members=tgt_members,
            candidate_members=cand_members,
            top_n=limit,
        )
        for it in items:
            meta = sectors_meta.get(it["sector_id"], {})
            it["name"] = meta.get("name", it["sector_id"])
            it["sector_type"] = meta.get("type")

    return ok({"target": sector_id, "target_date": str(date), "items": items, "status": "ready"})


# ── helpers ──

def _load_sectors_meta(session) -> dict[str, dict[str, Any]]:
    rows = session.execute(
        select(schema.sectors.c.id, schema.sectors.c.name, schema.sectors.c.type)
    ).all()
    return {r[0]: {"name": r[1], "type": r[2]} for r in rows}


def _ranking_for_date(session, d: date, sector_type: str | None, limit: int) -> list[dict[str, Any]]:
    q = (
        select(schema.sector_period_scores)
        .where(schema.sector_period_scores.c.as_of_date == d,
               schema.sector_period_scores.c.period == _DEFAULT_PERIOD)
    )
    if sector_type:
        q = q.where(schema.sector_period_scores.c.sector_type == sector_type)
    q = q.order_by(desc(schema.sector_period_scores.c.heat_score)).limit(limit)
    rows = session.execute(q).mappings().all()
    out = []
    for row in rows:
        r = dict(row)
        out.append({
            "sector_id": r["sector_id"],
            "heat_score": r.get("heat_score"),
            "fund_score": r.get("fund_score"),
            "momentum_score": r.get("momentum_score"),
            "trend_state": r.get("trend_state"),
            "rank_return": r.get("rank_return"),
            "return_pct": r.get("return_pct"),
            "confidence": r.get("confidence"),
        })
    return out


def _ranking_for_range(session, t1: date, t2: date, sector_type: str | None, limit: int) -> list[dict[str, Any]]:
    """区间 delta：取 t1/t2 两日的 scores + [t1,t2] 区间 bars 算 raw delta，再批量算 fund_strength。"""
    base = select(schema.sector_period_scores).where(
        schema.sector_period_scores.c.period == _DEFAULT_PERIOD,
        schema.sector_period_scores.c.as_of_date.in_([t1, t2]),
    )
    if sector_type:
        base = base.where(schema.sector_period_scores.c.sector_type == sector_type)
    score_rows = session.execute(base).mappings().all()
    by_sector: dict[str, dict] = {"t1": {}, "t2": {}}
    for r in score_rows:
        d = r["as_of_date"]
        key = "t1" if d == t1 else "t2"
        by_sector[key][r["sector_id"]] = r

    sector_ids = list(set(by_sector["t1"].keys()) & set(by_sector["t2"].keys()))
    if not sector_ids:
        return []

    # 区间内 bars（求累计 turnover、t1/t2 close）
    bar_rows = session.execute(
        select(schema.sector_daily_bars.c.sector_id, schema.sector_daily_bars.c.trade_date,
               schema.sector_daily_bars.c.close_price, schema.sector_daily_bars.c.turnover)
        .where(schema.sector_daily_bars.c.sector_id.in_(sector_ids),
               schema.sector_daily_bars.c.trade_date.between(t1, t2))
        .order_by(schema.sector_daily_bars.c.sector_id, schema.sector_daily_bars.c.trade_date)
    ).all()
    bars_by_sector: dict[str, list] = {}
    for sid, d, close, turnover in bar_rows:
        bars_by_sector.setdefault(sid, []).append((d, close, turnover))

    # 前等长区间 turnover（放量比）
    span = (t2 - t1).days or 1
    prev_t0 = t1 - timedelta(days=span)
    prev_rows = session.execute(
        select(schema.sector_daily_bars.c.sector_id, schema.sector_daily_bars.c.turnover)
        .where(schema.sector_daily_bars.c.sector_id.in_(sector_ids),
               schema.sector_daily_bars.c.trade_date.between(prev_t0, t1))
    ).all()
    prev_turnover: dict[str, list[float]] = {}
    for sid, turnover in prev_rows:
        prev_turnover.setdefault(sid, []).append(float(turnover or 0.0))

    # 近端资金流（若 [t1,t2] 有逐日数据）
    inflows = _load_range_inflows(session, sector_ids, t1, t2)

    raws = []
    meta_index = []
    for sid in sector_ids:
        bars = bars_by_sector.get(sid, [])
        close_t1 = next((c for d, c, t in bars if d == t1), None)
        close_t2 = next((c for d, c, t in bars if d == t2), None)
        range_turnover = [float(t or 0.0) for d, c, t in bars]
        raw = compute_raw_sector_delta(
            bars_t1_close=close_t1,
            bars_t2_close=close_t2,
            range_turnover=range_turnover,
            prev_range_turnover=prev_turnover.get(sid, []),
            score_t1=by_sector["t1"].get(sid),
            score_t2=by_sector["t2"].get(sid),
            range_main_inflow=inflows.get(sid),
        )
        raw["sector_id"] = sid
        raws.append(raw)
        meta_index.append(sid)

    strengths = compute_fund_strength_batch(raws)
    for i, sid in enumerate(meta_index):
        raws[i]["fund_strength"] = strengths[i]
        s2 = by_sector["t2"].get(sid, {})
        raws[i]["heat_score"] = s2.get("heat_score")
        raws[i]["trend_state"] = s2.get("trend_state")

    raws.sort(key=lambda r: (r.get("fund_strength") is not None, r.get("fund_strength") or -1), reverse=True)
    return raws[:limit]


def _load_range_inflows(session, sector_ids: list[str], t1: date, t2: date) -> dict[str, list[float]]:
    """近端资金流：sector_fund_flows.trade_date 是 String，转成 date 比较。仅返回有数据的。"""
    rows = session.execute(
        select(schema.sector_fund_flows.c.sector_id, schema.sector_fund_flows.c.trade_date,
               schema.sector_fund_flows.c.main_net_inflow)
        .where(schema.sector_fund_flows.c.sector_id.in_(sector_ids),
               schema.sector_fund_flows.c.period == "即时")
    ).all()
    out: dict[str, list[float]] = {}
    for sid, td, inflow in rows:
        try:
            d = td if isinstance(td, date) else _parse_date(td)
        except Exception:
            continue
        if t1 <= d <= t2 and inflow is not None:
            out.setdefault(sid, []).append(float(inflow))
    return out


def _parse_date(s: str) -> date:
    s = str(s).strip()
    return date.fromisoformat(s[:10])


def _load_index(session, d: date) -> list[dict[str, Any]]:
    rows = session.execute(
        select(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.close_price,
               schema.stock_daily_bars.c.change_pct, schema.stock_daily_bars.c.turnover)
        .where(schema.stock_daily_bars.c.vt_symbol.in_(_INDEX_VT_SYMBOLS),
               schema.stock_daily_bars.c.trade_date == d)
    ).all()
    names = {"000001.SSE": "上证指数", "399001.SZSE": "深证成指", "399006.SZSE": "创业板指",
             "000300.SSE": "沪深300", "000905.SSE": "中证500", "000852.SSE": "中证1000", "000688.SSE": "科创50"}
    return [{"vt_symbol": r[0], "name": names.get(r[0], r[0]), "close": r[1],
             "change_pct": r[2], "turnover": r[3]} for r in rows]
```

- [ ] **Step 2: 运行（确认无语法错误，import 可加载）**

Run: `cd /root/project/ai/vnpy && python -c "from alphaagent.server.api.mainline_replay import router; print(router.prefix)"`
Expected: 输出 `/mainline-replay`，无报错

- [ ] **Step 3: Commit（默认跳过）**

---

## Task 4: 后端 — 路由注册 + API 契约测试

**Files:**
- Modify: `alphaagent/server/api/router.py`
- Test: `tests/alphaagent/test_mainline_replay_api.py`

- [ ] **Step 1: 注册路由**

修改 `alphaagent/server/api/router.py`：在 import 区（第 14-22 行附近）加：

```python
from alphaagent.server.api.mainline_replay import router as mainline_replay_router
```

在 `api_router.include_router(...)` 区（第 29-48 行附近）加：

```python
api_router.include_router(mainline_replay_router)
```

- [ ] **Step 2: 写 API 契约测试**

创建 `tests/alphaagent/test_mainline_replay_api.py`：

```python
"""API contract tests for mainline replay endpoints."""

from fastapi.testclient import TestClient
from alphaagent.server.main import create_app
from alphaagent.server.db import session as db_session


def _disable_db(monkeypatch) -> None:
    monkeypatch.setattr(db_session, "is_database_configured", lambda: False)
    from alphaagent.server.api import mainline_replay
    monkeypatch.setattr(mainline_replay, "is_database_configured", lambda: False)


def test_timeline_unavailable_when_db_off(monkeypatch):
    _disable_db(monkeypatch)
    client = TestClient(create_app())
    # TestClient 不会自动带 auth；若项目有全局鉴权依赖，需补 token。这里假定 /api/mainline-replay 公开或测试关闭鉴权。
    res = client.get("/api/mainline-replay/timeline")
    body = res.json()
    assert res.status_code == 200
    assert body["success"] is True
    assert body["data"]["status"] == "unavailable"


def test_snapshot_requires_date_or_range(monkeypatch):
    _disable_db(monkeypatch)
    client = TestClient(create_app())
    res = client.get("/api/mainline-replay/snapshot")
    assert res.status_code == 400


def test_snapshot_single_date_ok_shape(monkeypatch):
    _disable_db(monkeypatch)
    client = TestClient(create_app())
    res = client.get("/api/mainline-replay/snapshot?date=2026-06-20")
    body = res.json()
    assert body["success"] is True
    assert body["data"]["mode"] == "single"
    assert "ranking" in body["data"]
    assert "index" in body["data"]


def test_relation_unavailable_when_db_off(monkeypatch):
    _disable_db(monkeypatch)
    client = TestClient(create_app())
    res = client.get("/api/mainline-replay/relation?sector_id=BK0001&date=2026-06-20")
    body = res.json()
    assert body["success"] is True
    assert body["data"]["status"] == "unavailable"
```

> **注意（鉴权）：** 若项目对 `/api/*` 有全局 JWT 依赖导致 TestClient 401，需在测试里 monkeypatch 鉴权依赖或注入 token。实现时先跑一次，若 401 再按现有 `tests/alphaagent/test_api.py` 的鉴权处理方式补。

- [ ] **Step 3: 运行 API 测试**

Run: `cd /root/project/ai/vnpy && pytest tests/alphaagent/test_mainline_replay_api.py -v`
Expected: 4 passed（若鉴权 401，按注意项修复后再跑）

- [ ] **Step 4: 端到端真实数据验证（curl）**

启动后端：`cd /root/project/ai/vnpy && python -m alphaagent.server`（或项目实际启动命令，见 memory/05_runtime）

```bash
# 取一个可回放的真实日期
DATE=$(curl -s http://localhost:8000/api/mainline-replay/timeline | python -c "import sys,json; d=json.load(sys.stdin)['data']['dates']; print(d[0] if d else '')")
echo "latest replayable date: $DATE"
# 单日快照
curl -s "http://localhost:8000/api/mainline-replay/snapshot?date=$DATE" | python -m json.tool | head -40
# 关联反推（用快照返回的第一个 sector_id）
SID=$(curl -s "http://localhost:8000/api/mainline-replay/snapshot?date=$DATE" | python -c "import sys,json; r=json.load(sys.stdin)['data']['ranking']; print(r[0]['sector_id'] if r else '')")
curl -s "http://localhost:8000/api/mainline-replay/relation?sector_id=$SID&date=$DATE" | python -m json.tool | head -40
```
Expected: dates 非空（库有 sector_period_scores）；ranking 含 heat_score/trend_state；relation.items 含 relation_score + reason。

- [ ] **Step 5: Commit（默认跳过）**

---

## Task 5: 前端 — API 客户端

**Files:**
- Create: `frontend/src/api/mainlineReplay.ts`

- [ ] **Step 1: 实现 API 客户端 + 类型**

创建 `frontend/src/api/mainlineReplay.ts`（照抄 `sectors.ts` 的 `apiClient.get` 模式）：

```typescript
import { apiClient } from "./client";

export interface TimelineData {
  dates: string[];
  status: "ready" | "empty" | "unavailable";
  message?: string;
}

export interface SectorRankItem {
  sector_id: string;
  name?: string;
  sector_type?: string;
  heat_score?: number | null;
  fund_score?: number | null;
  momentum_score?: number | null;
  trend_state?: string | null;
  rank_return?: number | null;
  return_pct?: number | null;
  confidence?: number | null;
  // delta 模式额外字段
  fund_strength?: number | null;
  volume_ratio?: number | null;
  delta_heat?: number | null;
  delta_fund?: number | null;
  accumulated_main_inflow?: number | null;
  fund_inflow_available?: boolean;
  trend_transition?: string | null;
}

export interface IndexQuote {
  vt_symbol: string;
  name: string;
  close: number | null;
  change_pct: number | null;
  turnover: number | null;
}

export interface SnapshotData {
  mode: "single" | "delta";
  ranking: SectorRankItem[];
  index: IndexQuote[];
  status: string;
}

export interface RelationItem {
  sector_id: string;
  name?: string;
  relation_score: number;
  corr?: number | null;
  fund_corr?: number | null;
  overlap: number;
  overlap_count: number;
  reason: string;
}

export interface RelationData {
  target: string;
  target_date?: string;
  items: RelationItem[];
  status: string;
}

export function fetchReplayTimeline() {
  return apiClient.get<TimelineData>("/mainline-replay/timeline");
}

export function fetchReplaySnapshot(params: { date?: string; t1?: string; t2?: string; sector_type?: string }) {
  const qs = new URLSearchParams();
  if (params.date) qs.set("date", params.date);
  if (params.t1) qs.set("t1", params.t1);
  if (params.t2) qs.set("t2", params.t2);
  if (params.sector_type) qs.set("sector_type", params.sector_type);
  return apiClient.get<SnapshotData>(`/mainline-replay/snapshot?${qs.toString()}`);
}

export function fetchReplayRelation(sectorId: string, date: string) {
  return apiClient.get<RelationData>(
    `/mainline-replay/relation?sector_id=${encodeURIComponent(sectorId)}&date=${date}`
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `cd /root/project/ai/vnpy/frontend && npx tsc --noEmit`
Expected: 无新增类型错误

- [ ] **Step 3: Commit（默认跳过）**

---

## Task 6: 前端 — MainlineReplayPage 主页面（时间轴 + 三栏）

**Files:**
- Create: `frontend/src/pages/MainlineReplayPage.tsx`

> 照抄 `ThemeExplorerPage.tsx` 的 useQuery + tailwind 类名风格（`bg-card`/`text-muted-foreground`/`rounded-lg`/`border`）。数字用 `formatPct`/`formatAmount`（`@/lib/utils`）。

- [ ] **Step 1: 实现主页面**

创建 `frontend/src/pages/MainlineReplayPage.tsx`：

```typescript
/**
 * MainlineReplayPage — 主线回放（合并主线探索 + 产业链）
 * 顶部时间轴(历史日期) + 三栏(主线榜/大盘+资金/详情) + 关联面板。
 */
import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { RelationPanel } from "@/features/replay/RelationPanel";
import { fetchReplayTimeline, fetchReplaySnapshot, type SectorRankItem, type IndexQuote } from "@/api/mainlineReplay";
import { formatPct } from "@/lib/utils";
import { cn } from "@/lib/utils";

export default function MainlineReplayPage() {
  const timelineQ = useQuery({ queryKey: ["replayTimeline"], queryFn: fetchReplayTimeline, staleTime: 60_000 });
  const dates = timelineQ.data?.dates ?? [];
  const [selectedDate, setSelectedDate] = useState<string>("");
  const effectiveDate = selectedDate || dates[0] || "";

  const snapshotQ = useQuery({
    queryKey: ["replaySnapshot", effectiveDate],
    queryFn: () => fetchReplaySnapshot({ date: effectiveDate }),
    enabled: !!effectiveDate,
    staleTime: 60_000,
  });

  const [selectedSector, setSelectedSector] = useState<SectorRankItem | null>(null);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold tracking-tight">主线回放</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          拖动时间轴回到任意交易日，看那天主线板块、大盘走势、资金强弱，点板块看行情关联。
        </p>
      </div>

      {/* 时间轴 */}
      <div className="rounded-lg border bg-card p-3">
        {timelineQ.isLoading ? (
          <LoadingState rows={1} />
        ) : dates.length === 0 ? (
          <div className="text-sm text-muted-foreground">
            暂无回放数据。请先在 <a href="/data" className="underline">数据管理</a> 同步 sector_period_scores。
          </div>
        ) : (
          <DateScrubber dates={dates} value={effectiveDate} onChange={setSelectedDate} />
        )}
      </div>

      {/* 三栏 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_minmax(0,1fr)_320px]">
        {/* 左：主线榜 */}
        <div className="rounded-lg border bg-card p-3">
          <div className="mb-2 text-xs text-muted-foreground">主线板块榜 · {effectiveDate}</div>
          {snapshotQ.isLoading ? <LoadingState rows={8} /> : (
            <div className="max-h-[calc(100vh-280px)] space-y-1 overflow-y-auto">
              {(snapshotQ.data?.ranking ?? []).map((r, i) => (
                <button
                  key={r.sector_id}
                  onClick={() => setSelectedSector(r)}
                  className={cn(
                    "flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                    selectedSector?.sector_id === r.sector_id ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                  )}
                >
                  <span className="min-w-0 truncate"><span className="text-muted-foreground">{i + 1}.</span> {r.name ?? r.sector_id}</span>
                  <span className="ml-2 shrink-0 tabular-nums text-xs">{formatPct((r.return_pct ?? 0) / 100)}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* 中：大盘 + 资金 */}
        <div className="rounded-lg border bg-card p-3">
          <div className="mb-2 text-xs text-muted-foreground">大盘指数 · {effectiveDate}</div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {(snapshotQ.data?.index ?? []).map((ix) => <IndexCard key={ix.vt_symbol} ix={ix} />)}
          </div>
          <div className="mt-3 text-xs text-muted-foreground">
            资金强弱：板块按 heat_score 排序；区间 delta 模式（t1+t2）展示 fund_strength 综合资金强弱。
          </div>
        </div>

        {/* 右：详情 + 关联 */}
        <div className="rounded-lg border bg-card p-3">
          {selectedSector ? (
            <div className="space-y-3">
              <div>
                <div className="text-sm font-semibold">{selectedSector.name ?? selectedSector.sector_id}</div>
                <div className="mt-1 grid grid-cols-2 gap-2 text-xs">
                  <Metric label="热度" value={selectedSector.heat_score?.toFixed(1)} />
                  <Metric label="资金分" value={selectedSector.fund_score?.toFixed(1)} />
                  <Metric label="趋势" value={selectedSector.trend_state ?? "-"} />
                  <Metric label="收益" value={formatPct((selectedSector.return_pct ?? 0) / 100)} />
                </div>
              </div>
              <RelationPanel sectorId={selectedSector.sector_id} date={effectiveDate} />
            </div>
          ) : (
            <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">← 点左侧板块看详情与关联</div>
          )}
        </div>
      </div>
    </div>
  );
}

function DateScrubber({ dates, value, onChange }: { dates: string[]; value: string; onChange: (d: string) => void }) {
  const idx = Math.max(0, dates.indexOf(value));
  return (
    <div className="space-y-2">
      <input
        type="range" min={0} max={dates.length - 1} value={idx}
        onChange={(e) => onChange(dates[Number(e.target.value)])}
        className="w-full accent-primary"
      />
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{dates[dates.length - 1]}</span>
        <span className="font-medium text-foreground">{value}</span>
        <span>{dates[0]}</span>
      </div>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded-md border bg-background px-2 py-1 text-xs">
        {dates.map((d) => <option key={d} value={d}>{d}</option>)}
      </select>
    </div>
  );
}

function IndexCard({ ix }: { ix: IndexQuote }) {
  const up = (ix.change_pct ?? 0) >= 0;
  return (
    <div className="rounded-md border p-2">
      <div className="text-[11px] text-muted-foreground">{ix.name}</div>
      <div className="mt-0.5 text-sm font-medium tabular-nums">{ix.close?.toFixed(2) ?? "-"}</div>
      <div className={cn("text-xs tabular-nums", up ? "text-rise" : "text-fall")}>{formatPct((ix.change_pct ?? 0) / 100)}</div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="rounded-md border p-1.5">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 font-medium tabular-nums">{value ?? "-"}</div>
    </div>
  );
}
```

> **`formatPct` 入参单位确认：** 上面假设 `return_pct`/`change_pct` 是百分数值（如 3.5 表示 3.5%），`formatPct` 接收小数（0.035）。实现时核对 `@/lib/utils` 的 `formatPct` 签名与现有页面的用法，按真实约定调整（可能不需要 `/100`）。

- [ ] **Step 2: 类型检查 + 启动**

Run: `cd /root/project/ai/vnpy/frontend && npx tsc --noEmit && npm run dev`
Expected: 无类型错误；dev server 起在 5173（此时页面还缺 RelationPanel，下一步补）

- [ ] **Step 3: Commit（默认跳过）**

---

## Task 7: 前端 — 关联面板 + 路由/导航注册 + 端到端验证

**Files:**
- Create: `frontend/src/features/replay/RelationPanel.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/AppShell.tsx`

- [ ] **Step 1: 实现关联面板**

创建 `frontend/src/features/replay/RelationPanel.tsx`：

```typescript
/** RelationPanel — 从行情反推的关联板块（侧滑面板，列表模式）。点列表项可联动切换目标板块。 */
import { useQuery } from "@tanstack/react-query";
import { LoadingState } from "@/components/LoadingState";
import { fetchReplayRelation } from "@/api/mainlineReplay";
import { cn } from "@/lib/utils";

export function RelationPanel({ sectorId, date }: { sectorId: string; date: string }) {
  const q = useQuery({
    queryKey: ["replayRelation", sectorId, date],
    queryFn: () => fetchReplayRelation(sectorId, date),
    enabled: !!sectorId && !!date,
    staleTime: 60_000,
  });

  return (
    <div>
      <div className="mb-1 text-xs text-muted-foreground">🔗 关联板块（行情反推）</div>
      {q.isLoading ? <LoadingState rows={4} /> : (q.data?.items ?? []).length === 0 ? (
        <div className="text-xs text-muted-foreground">数据不足，无法计算关联。</div>
      ) : (
        <div className="space-y-1">
          {(q.data?.items ?? []).map((it) => (
            <div key={it.sector_id} className="rounded-md border p-1.5">
              <div className="flex items-center justify-between">
                <span className="truncate text-xs font-medium">{it.name ?? it.sector_id}</span>
                <span className="ml-2 shrink-0 text-xs tabular-nums text-primary">{(it.relation_score * 100).toFixed(0)}%</span>
              </div>
              <div className="text-[10px] text-muted-foreground">{it.reason}</div>
              <div className="mt-1 h-1 overflow-hidden rounded bg-muted">
                <div className={cn("h-full bg-primary")} style={{ width: `${it.relation_score * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 注册路由**

修改 `frontend/src/App.tsx`：在懒加载区（第 17-19 行附近）加：

```typescript
const MainlineReplayPage = lazy(() => import("@/pages/MainlineReplayPage"));
```

在 `<Routes>` 内（第 51 行 `/chain` 附近）加：

```typescript
<Route path="/mainline" element={<MainlineReplayPage />} />
```

- [ ] **Step 3: 注册导航菜单**

修改 `frontend/src/components/AppShell.tsx`：在 import 加 `History` 图标（第 3-16 行 lucide-react import），在 `NAV_ITEMS`（第 22-30 行）加（替换 `/explore` 与 `/chain` 的位置，或并列）：

```typescript
{ to: "/mainline", label: "主线回放", icon: History },
```

> **整合说明：** 阶段1 先并列新增"主线回放"菜单。`/explore`、`/chain` 的重定向删除留到所有功能验证后（避免阶段1 中途破坏现有入口）。

- [ ] **Step 4: 类型检查 + 前端构建**

Run: `cd /root/project/ai/vnpy/frontend && npx tsc --noEmit && npm run build`
Expected: 构建成功无错误

- [ ] **Step 5: 端到端手动验证（看到效果）**

1. 启动后端 + 前端 dev server。
2. 浏览器访问 `/mainline`（需先登录）。
3. 验证：
   - 时间轴显示可回放日期，拖动/选择日期后主线榜、大盘指数随之变化。
   - 点左侧板块 → 右侧详情 + 关联面板出现，关联面板列出关联板块含 relation_score 与 reason。
   - 数字格式正常（涨红跌绿）。
4. 用 Playwright 或截图记录效果供用户确认。

- [ ] **Step 6: 同步设计文档命名 + Commit**

修改 `docs/superpowers/specs/2026-06-28-mainline-replay-design.md`：把 `/replay` → `/mainline`、`replay.py` → `mainline_replay.py`、`/api/replay/*` → `/api/mainline-replay/*`（全文替换）。

Commit（用户授权后）：`git add` 新增的 6 个文件 + 3 个修改文件 + 设计文档，提交信息 `feat(mainline): 主线回放页面(历史回放+资金delta+行情反推关联)，合并/explore+/chain`。

---

## Self-Review（计划自检）

- **Spec 覆盖：** 设计文档 §3 架构 → Task 3/5/6/7；§4.1 delta → Task 1/3；§4.2 关联 → Task 2/3；§6 可测试 → Task 1/2/4（算法 TDD + API 契约 + curl 端到端）；§8 阶段1 → Task 1-7 全覆盖。✓
- **占位符扫描：** 后端算法/API/测试为完整可运行代码；前端为可照抄骨架（标注了 `formatPct` 单位需核对、鉴权 401 兜底——这两处是实现期需验证的点，非占位符）。✓
- **类型/命名一致性：** 纯函数签名（`compute_raw_sector_delta`/`compute_relations`/`pearson`/`minmax_normalize`/`compute_fund_strength_batch`）在 Task1/2 定义、Task3 调用、Task1/2 测试，全一致；前端 `SectorRankItem`/`RelationItem` 在 Task5 定义、Task6/7 使用，一致。✓
- **已识别的实现期风险点（需现场验证，非计划缺陷）：**
  1. `formatPct` 入参单位（小数 vs 百分数）——核对 `@/lib/utils`。
  2. TestClient 鉴权 401——按现有 `tests/alphaagent/test_api.py` 处理。
  3. `sector_fund_flows.trade_date` 是 String，已用 `_parse_date` 处理。
  4. `sector_period_scores.period` 取值用 `"20d"`（与 `sector_dashboard` 默认一致）。
