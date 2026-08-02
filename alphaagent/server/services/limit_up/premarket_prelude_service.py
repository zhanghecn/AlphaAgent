"""盘前首板前奏候选筛选（小阳爬升/阴跌蓄势形态 + 量能特征）。

场景（主人 2026-08-02）：开盘前按前奏形态因子筛出低位首板候选股，
生成候选清单 + txt 下载（每行 6 位代码），导入同花顺自定义板块后
早盘人工按因子条件核对涨幅、快速打板。

筛选条件（全部 D-1 收盘前可观测，无未来函数）：

- 主板非 ST/退/新（``is_eligible_main_board``）；
- D-1 未涨停（今天若涨停必为首板，``_is_first_board_candidate``）；
- **主人版低位**（``_is_owner_low_position``，2026-08-02 锚点校准：
  半年区间位置 ≤0.25 且距 126 日高点回撤 ≤-25%，或距 126 日低点反弹 ≤12%——
  立新能源/爱丽家居/传智教育三条件全满足、至纯科技全不满足）；
- 形态/量能特征（prelude_pattern / vol_cv_7d / vol_shift_ratio）**只展示不做硬滤**：
  低位组 72% 的 >=2 板票无前奏形态（锚点票全 none），形态过滤会丢掉主人要的票。

排序（精选优先级）：板块 20 日动量降序（低位组唯一有区分度的因子：
>=2 板 51.3% vs 非连板 39.9%，「低位+题材」是核心路径）→ 前奏量比升序
（缩量企稳优先）→ 量稳度升序。

注意（研究裁决）：低位首板作为**自动策略**是负期望（-4.9%/46.5%/PF 0.94，
安全垫厚但向上弹性不足）——本清单是**人工核对用观察池**（主人的交易风格：
贴底首板+人工题材判断），非自动交易信号。自动买入层保持深跌排除+白名单
打分（数据证明的路线），两层分离。

数据新鲜度：D-1 日线在前一晚 19:00/21:30 EOD 批已入库；每晚 22:00
`premarket_prelude_snapshot` 批次预算写快照表，API 读库毫秒返回
（低位条件需要 126 日窗口，实时全市场扫描在 0.25 核 api 容器跑不动）。
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
from alphaagent.server.services.limit_up.leader_first_board_prelude_pattern_research import (
    PRELUDE_MAX_CHANGE_PCT,
    _prelude_pattern_features,
)
from alphaagent.server.services.limit_up.leader_minute_backtest import (
    _is_first_board_candidate,
    _is_owner_low_position,
    build_sector_r20_lookup,
)
from alphaagent.server.services.limit_up.live_repository import (
    load_latest_daily_trade_date,
)
from alphaagent.server.services.limit_up.repository import (
    load_daily_bars_all,
    load_sector_daily_bars,
    load_sector_memberships_all,
    load_stock_names,
)

# 日线回看窗口：主人版低位需要 126 交易日窗口（_long_window_features），
# 200 自然日 ≈ 135+ 交易日（覆盖长假），75 万行级查询只在每晚批次跑
_LOOKBACK_DAYS = 200
_CACHE_SECONDS = 60
_candidates_cache: dict[str, object] = {"at": None, "key": None, "value": None}

_NOTES = (
    "主人版低位（锚点校准 2026-08-02）：半年位置≤0.25且距高点回撤≤-25%，或距低点反弹≤12%。",
    "研究裁决：低位首板自动策略负期望（安全垫厚但弹性不足）——本清单为人工核对观察池，非自动信号；自动买入层保持深跌排除+白名单打分。",
    "低位组 72% 的 >=2 板票无前奏形态，形态只展示不硬滤；排序=板块动量降序（低位+题材核心路径）→缩量→量稳。",
    "证据：memory/06_backtests/limit_up_leader_first_board_prelude_pattern_20260802.md（附低位口径回测）。",
)


def _load_sector_names() -> dict[str, str]:
    """sector_id → 板块名称（概念名展示用）。"""

    with session_scope() as session:
        rows = session.execute(select(schema.sectors.c.id, schema.sectors.c.name)).all()
    return {str(row[0]): str(row[1] or "") for row in rows}


def _screen_symbol(
    bars: Sequence[Mapping[str, object]],
    *,
    latest: str,
    pattern: str,
    max_change_pct: float,
    max_vol_cv: float | None,
    min_vol_shift: float | None,
    max_vol_shift: float | None,
) -> dict[str, object] | None:
    """单票筛选（纯函数）：通过则返回候选行，否则 None。"""

    if len(bars) < 11 or str(bars[-1].get("trade_date") or "") != latest:
        return None  # 数据不足/停牌/最新日期不符
    if not _is_first_board_candidate(bars):
        return None  # D-1 已涨停，今天不是首板
    if not _is_owner_low_position(bars):
        return None  # 非主人版低位（贴底首板）
    features = _prelude_pattern_features(bars, max_change_pct=max_change_pct)
    matched = str(features.get("prelude_pattern") or "none")
    # 形态可选过滤（默认 all 不滤——低位组 72% 成功票无形态，形态只展示）
    if pattern == "has_pattern" and matched not in ("small_yang", "small_yin"):
        return None
    if pattern in ("small_yang", "small_yin") and matched != pattern:
        return None
    vol_cv = features.get("prelude_vol_cv_7d")
    vol_shift = features.get("prelude_vol_shift_ratio")
    if max_vol_cv is not None and (vol_cv is None or float(vol_cv) > max_vol_cv):
        return None
    if min_vol_shift is not None and (vol_shift is None or float(vol_shift) < min_vol_shift):
        return None
    if max_vol_shift is not None and (vol_shift is None or float(vol_shift) > max_vol_shift):
        return None
    return {
        "prelude_pattern": matched,
        "streak": features.get("prelude_small_yang_streak")
        if matched == "small_yang"
        else features.get("prelude_small_yin_streak"),
        "vol_cv_7d": vol_cv,
        "vol_shift_ratio": vol_shift,
        "return_20d_pct": _return_20d(bars),
    }


def _return_20d(bars: Sequence[Mapping[str, object]]) -> float | None:
    """D-1 前 20 日累计涨幅（%）。"""

    if len(bars) < 21:
        return None
    last = bars[-1].get("close_price")
    base = bars[-21].get("close_price")
    try:
        last_f = float(last)  # type: ignore[arg-type]
        base_f = float(base)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if base_f <= 0:
        return None
    return round((last_f / base_f - 1) * 100, 4)


def build_premarket_prelude_candidates(
    *,
    pattern: str = "all",
    max_change_pct: float = PRELUDE_MAX_CHANGE_PCT,
    max_vol_cv: float | None = None,
    min_vol_shift: float | None = None,
    max_vol_shift: float | None = None,
    limit: int = 100,
) -> dict[str, object]:
    """盘前低位首板候选：全主板日线扫描 → 主人版低位+首板条件 → 板块动量排序。"""

    latest = load_latest_daily_trade_date()
    if latest is None:
        return {"status": "unavailable", "message": "日线数据为空", "candidates": []}

    cache_key = (
        f"{latest.isoformat()}|{pattern}|{max_change_pct}|{max_vol_cv}|"
        f"{min_vol_shift}|{max_vol_shift}|{limit}"
    )
    cached_at = _candidates_cache.get("at")
    if (
        _candidates_cache.get("key") == cache_key
        and cached_at is not None
        and time.time() - float(cached_at) < _CACHE_SECONDS
    ):
        return dict(_candidates_cache["value"])  # type: ignore[arg-type]

    latest_iso = latest.isoformat()
    daily_bars = load_daily_bars_all(latest - timedelta(days=_LOOKBACK_DAYS), latest)
    names = load_stock_names()
    memberships = load_sector_memberships_all()
    sector_names = _load_sector_names()
    concept_r20_lookup = build_sector_r20_lookup(
        memberships,
        load_sector_daily_bars(latest - timedelta(days=190), latest),
    )

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
        hit = _screen_symbol(
            rows,
            latest=latest_iso,
            pattern=pattern,
            max_change_pct=max_change_pct,
            max_vol_cv=max_vol_cv,
            min_vol_shift=min_vol_shift,
            max_vol_shift=max_vol_shift,
        )
        if hit is None:
            continue
        candidates.append(
            {
                "vt_symbol": symbol,
                "code": symbol.split(".", 1)[0],
                "name": name,
                **hit,
                "concept_r20": concept_r20_lookup(symbol, latest_iso),
                "concepts": concepts_by_symbol.get(symbol, [])[:3],
            }
        )

    # 确定性排序：板块动量降（低位+题材核心路径）→ 量比升（缩量企稳）→ 量稳升
    candidates.sort(
        key=lambda item: (
            -(float(item["concept_r20"]) if item["concept_r20"] is not None else -999.0),
            float(item["vol_shift_ratio"]) if item["vol_shift_ratio"] is not None else 999.0,
            float(item["vol_cv_7d"]) if item["vol_cv_7d"] is not None else 999.0,
            str(item["vt_symbol"]),
        )
    )
    total = len(candidates)
    if limit > 0:
        candidates = candidates[:limit]

    result: dict[str, object] = {
        "status": "ok",
        "trade_date": latest_iso,
        "params": {
            "pattern": pattern,
            "max_change_pct": max_change_pct,
            "max_vol_cv": max_vol_cv,
            "min_vol_shift": min_vol_shift,
            "max_vol_shift": max_vol_shift,
        },
        "count": len(candidates),
        "total": total,
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


def save_premarket_prelude_snapshot(result: Mapping[str, object]) -> int:
    """把 build 结果按 trade_date upsert 落库（同日重算覆盖）。返回写入行数。"""

    trade_date_raw = result.get("trade_date")
    if not trade_date_raw:
        return 0
    payload = dict(result)
    statement = postgresql_insert(schema.premarket_prelude_snapshots).values(
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


def load_premarket_prelude_snapshot() -> dict[str, object] | None:
    """读最新一个交易日的快照（EOD 批次预算结果）。"""

    statement = (
        select(schema.premarket_prelude_snapshots.c.payload)
        .order_by(schema.premarket_prelude_snapshots.c.trade_date.desc())
        .limit(1)
    )
    with session_scope() as session:
        row = session.execute(statement).scalar_one_or_none()
    return dict(row) if row else None


def _filter_by_pattern(
    result: Mapping[str, object], pattern: str, limit: int
) -> dict[str, object]:
    """快照（all 全量）按形态过滤 + 截断（快照已是板块动量排序，直接取前 N）。"""

    candidates = list(result.get("candidates") or [])
    if pattern == "has_pattern":
        candidates = [
            dict(item)
            for item in candidates
            if item.get("prelude_pattern") in ("small_yang", "small_yin")
        ]
    elif pattern in ("small_yang", "small_yin"):
        candidates = [
            dict(item) for item in candidates if item.get("prelude_pattern") == pattern
        ]
    total = len(candidates)
    if limit > 0:
        candidates = candidates[:limit]
    filtered = dict(result)
    filtered["candidates"] = candidates
    filtered["count"] = len(candidates)
    filtered["total"] = total
    params = dict(filtered.get("params") or {})
    params["pattern"] = pattern
    filtered["params"] = params
    return filtered


def get_premarket_prelude_candidates(
    *, pattern: str = "all", limit: int = 100
) -> dict[str, object]:
    """API 入口：优先读 EOD 预算快照（毫秒级），miss 则实时全市场扫描兜底。"""

    snapshot = load_premarket_prelude_snapshot()
    if snapshot and snapshot.get("status") == "ok":
        return _filter_by_pattern(snapshot, pattern, limit)
    return build_premarket_prelude_candidates(pattern=pattern, limit=limit)
