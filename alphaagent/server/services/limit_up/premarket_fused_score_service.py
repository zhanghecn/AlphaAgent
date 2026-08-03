"""盘前融合计分候选（低位分/波浪分 + Top-N + 子分分解，人工复核观察池）。

场景（主人 2026-08-03「先把功能做完」）：把三轮研究产出的通用因子计分卡做成
每日盘后可见的盘前功能——全主板打分、按融合分排序取 Top-N、子分全透明展示，
主人早盘人工复核清单打板，并在使用中迭代因子定义。

计分卡公式（v2，与 ``leader_first_board_fused_score_research`` 同源）：

- **低位分（0-7）**：资格门=40 日内最长空头排列≥15 日；L1 基底深度/L2 基底时长/
  L3 收敛时长/L4 穿越阶段/L5 企稳/L6 量能梯形/L7 近 20 日有触碰加分。
- **波浪分（0-4）**：资格门=向上波浪（多头排列）或横盘波浪（缠绕+回前低）；
  W1 多头时长/W2 回调深度/W3 企稳/W4 量能。
- **融合分** = max(低位分/7, 波浪分/4)，类型 lowpos/wave/both。

研究裁决（必须告知使用者）：计分卡整体未过过滤级（v2 报告 0/4，顶桶 lift 1.65），
L7_recent_touch 单条件才是三轮最强（lift 2.51）——本清单定位**人工复核观察池**，
非自动交易信号；分数只是排序参考，最终判断在主人。

数据新鲜度：D-1 日线在前一晚 19:00/21:30 EOD 批入库；每晚 22:00
``premarket_fused_score_snapshot`` 批次预算写快照表，API 读库毫秒返回
（全市场结构+旅程特征计算在 0.25 核 api 容器跑不动）。
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.a_share_universe import is_eligible_main_board
from alphaagent.server.services.limit_up.leader_first_board_fused_score_research import (
    _fused_score,
    _journey_features,
    _touch_dates_by_symbol,
)
from alphaagent.server.services.limit_up.leader_first_board_structure_research import (
    _structure_features,
)
from alphaagent.server.services.limit_up.leader_minute_backtest import (
    _is_first_board_candidate,
)
from alphaagent.server.services.limit_up.live_repository import (
    load_latest_daily_trade_date,
)
from alphaagent.server.services.limit_up.repository import (
    load_daily_bars_all,
    load_limit_up_dataset,
    load_sector_memberships_all,
    load_stock_names,
)

# 日线回看：旅程特征需要 69 根（40 日窗+MA30），150 自然日 ≈ 100+ 交易日（覆盖长假）
_LOOKBACK_DAYS = 150
_EVENTS_LOOKBACK_DAYS = 45  # 触碰事件回溯（覆盖 L7 的 20 市场日记忆窗）
_MIN_BARS = 69
_CACHE_SECONDS = 60
_candidates_cache: dict[str, object] = {"at": None, "key": None, "value": None}

SCORE_TYPES = ("all", "lowpos", "wave", "both")

_NOTES = (
    "计分卡=低位分(0-7)+波浪分(0-4)等权融合（公式 v2：L7=近20日有触碰加分、波浪门含横盘波浪）。",
    "研究裁决：计分卡整体未达过滤级（v2 报告 0/4、顶桶 lift 1.65）；「近20日有触碰」单条件才是三轮最强（lift 2.51）——本清单是人工复核观察池，非自动信号。",
    "排序=融合分降序（同分按代码升序）；子分全透明展示供人工迭代因子。",
    "证据：memory/06_backtests/limit_up_leader_first_board_fused_score_v2_20260803.md。",
)


def _load_sector_names() -> dict[str, str]:
    with session_scope() as session:
        rows = session.execute(select(schema.sectors.c.id, schema.sectors.c.name)).all()
    return {str(row[0]): str(row[1] or "") for row in rows}


def _screen_symbol(
    rows: Sequence[Mapping[str, object]],
    touch_dates: set[str] | None,
    *,
    latest: str,
) -> dict[str, object] | None:
    """单票打分（纯函数）：入榜（融合分>0）则返回候选行，否则 None。"""

    if len(rows) < _MIN_BARS or str(rows[-1].get("trade_date") or "") != latest:
        return None  # 数据不足/停牌/最新日期不符
    if not _is_first_board_candidate(rows):
        return None  # D-1 已涨停，今天不是首板
    features = _structure_features(rows)
    features.update(_journey_features(rows, touch_dates))
    fused = _fused_score(features)
    if float(fused["fused_score"]) <= 0:
        return None
    return {
        "fused_score": fused["fused_score"],
        "fused_type": fused["fused_type"],
        "lowpos_score": fused["lowpos_score"],
        "wave_score": fused["wave_score"],
        "lowpos_subs": fused["lowpos_subs"],
        "wave_subs": fused["wave_subs"],
        "bear_run_max_40d": features.get("bear_run_max_40d"),
        "conv_days": features.get("conv_days"),
        "cross_stage": features.get("cross_stage"),
        "pure_20d": features.get("pure_20d"),
        "bias_ma20_pct": features.get("bias_ma20_pct"),
        "ma_state": features.get("ma_state"),
    }


def build_premarket_fused_score_candidates(
    *,
    score_type: str = "all",
    min_score: float = 0.0,
    limit: int = 100,
) -> dict[str, object]:
    """盘前融合计分候选：全主板打分 → 入榜（>0）→ 融合分降序取 Top-N。"""

    latest = load_latest_daily_trade_date()
    if latest is None:
        return {"status": "unavailable", "message": "日线数据为空", "candidates": []}

    cache_key = f"{latest.isoformat()}|{score_type}|{min_score}|{limit}"
    cached_at = _candidates_cache.get("at")
    if (
        _candidates_cache.get("key") == cache_key
        and cached_at is not None
        and time.time() - float(cached_at) < _CACHE_SECONDS
    ):
        return dict(_candidates_cache["value"])  # type: ignore[arg-type]

    latest_iso = latest.isoformat()
    daily_bars = load_daily_bars_all(latest - timedelta(days=_LOOKBACK_DAYS), latest)
    events = load_limit_up_dataset(latest - timedelta(days=_EVENTS_LOOKBACK_DAYS), latest)[
        "events"
    ]
    touch_by_symbol = _touch_dates_by_symbol(events)
    names = load_stock_names()
    memberships = load_sector_memberships_all()
    sector_names = _load_sector_names()
    concepts_by_symbol: dict[str, list[str]] = defaultdict(list)
    for row in memberships:
        if str(row.get("sector_type") or "") != "concept":
            continue
        name = sector_names.get(str(row.get("sector_id") or ""))
        if name:
            concepts_by_symbol[str(row.get("vt_symbol") or "")].append(name)

    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in daily_bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)

    candidates: list[dict[str, object]] = []
    for symbol, rows in bars_by_symbol.items():
        name = names.get(symbol, "")
        if not is_eligible_main_board(symbol, name):
            continue
        rows.sort(key=lambda row: str(row.get("trade_date") or ""))
        hit = _screen_symbol(rows, touch_by_symbol.get(symbol), latest=latest_iso)
        if hit is None:
            continue
        candidates.append(
            {
                "vt_symbol": symbol,
                "code": symbol.split(".", 1)[0],
                "name": name,
                **hit,
                "concepts": concepts_by_symbol.get(symbol, [])[:3],
            }
        )

    # 确定性排序：融合分降序 → 代码升序
    candidates.sort(
        key=lambda item: (-float(item["fused_score"]), str(item["vt_symbol"]))
    )
    qualified_total = len(candidates)
    if score_type != "all":
        candidates = [
            item for item in candidates if str(item.get("fused_type")) == score_type
        ]
    if min_score > 0:
        candidates = [
            item for item in candidates if float(item["fused_score"]) >= min_score
        ]
    total = len(candidates)
    if limit > 0:
        candidates = candidates[:limit]

    result: dict[str, object] = {
        "status": "ok",
        "trade_date": latest_iso,
        "params": {"score_type": score_type, "min_score": min_score},
        "count": len(candidates),
        "total": total,
        "qualified_total": qualified_total,
        "candidates": candidates,
        "notes": list(_NOTES),
    }
    _candidates_cache["at"] = time.time()
    _candidates_cache["key"] = cache_key
    _candidates_cache["value"] = result
    return dict(result)


def render_candidates_txt(result: Mapping[str, object]) -> str:
    """候选清单 → 同花顺自定义板块导入格式（每行一个 6 位代码）。"""

    lines = [
        str(item.get("code") or "")
        for item in (result.get("candidates") or [])
        if str(item.get("code") or "").isdigit()
    ]
    return "\n".join(lines) + ("\n" if lines else "")


# ── 快照读写（EOD 批次预算 → API 读库，盘前免实时全市场扫描）──────────────────


def save_premarket_fused_score_snapshot(result: Mapping[str, object]) -> int:
    """把 build 结果按 trade_date upsert 落库（同日重算覆盖）。返回写入行数。"""

    trade_date_raw = result.get("trade_date")
    if not trade_date_raw:
        return 0
    payload = dict(result)
    statement = postgresql_insert(schema.premarket_fused_score_snapshots).values(
        trade_date=date.fromisoformat(str(trade_date_raw)),
        candidate_count=int(result.get("count") or 0),
        payload=payload,
    )
    statement = statement.on_conflict_do_update(
        index_elements=["trade_date"],
        set_={
            "candidate_count": statement.excluded.candidate_count,
            "payload": statement.excluded.payload,
        },
    )
    with session_scope() as session:
        session.execute(statement)
    return 1


def load_premarket_fused_score_snapshot() -> dict[str, object] | None:
    """读最新一个交易日的快照（EOD 批次预算结果）。"""

    statement = (
        select(schema.premarket_fused_score_snapshots.c.payload)
        .order_by(schema.premarket_fused_score_snapshots.c.trade_date.desc())
        .limit(1)
    )
    with session_scope() as session:
        row = session.execute(statement).scalar_one_or_none()
    return dict(row) if row else None


def _filter_snapshot(
    result: Mapping[str, object], score_type: str, min_score: float, limit: int
) -> dict[str, object]:
    """快照（all 全量）按类型/最低分过滤 + 截断（快照已是融合分降序）。"""

    candidates = list(result.get("candidates") or [])
    if score_type != "all":
        candidates = [
            dict(item) for item in candidates if str(item.get("fused_type")) == score_type
        ]
    if min_score > 0:
        candidates = [
            dict(item) for item in candidates if float(item.get("fused_score") or 0) >= min_score
        ]
    total = len(candidates)
    if limit > 0:
        candidates = candidates[:limit]
    filtered = dict(result)
    filtered["candidates"] = candidates
    filtered["count"] = len(candidates)
    filtered["total"] = total
    params = dict(filtered.get("params") or {})
    params["score_type"] = score_type
    params["min_score"] = min_score
    filtered["params"] = params
    return filtered


def get_premarket_fused_score_candidates(
    *, score_type: str = "all", min_score: float = 0.0, limit: int = 100
) -> dict[str, object]:
    """API 入口：优先读 EOD 预算快照（毫秒级），miss 则实时全市场扫描兜底。"""

    snapshot = load_premarket_fused_score_snapshot()
    if snapshot and snapshot.get("status") == "ok":
        return _filter_snapshot(snapshot, score_type, min_score, limit)
    return build_premarket_fused_score_candidates(
        score_type=score_type, min_score=min_score, limit=limit
    )
