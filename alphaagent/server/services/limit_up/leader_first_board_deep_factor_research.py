"""连板龙头首板深度因子挖掘（v2）：前3天/前10天/近半年/板块共振/时间段×D+1。

在 ``consecutive_leader_first_board_factor_research``（v1）基础上回答五个更深问题：

1. 首板前 3 天（D-3..D-1）走势形状（复用 v1）。
2. 前 3 天之前（D-10..D-4）的走势：蓄势 / 已大涨 / 持续趴着。
3. 近半年（D-126..D-1）大周期：区间位置、距高低点、振幅、长期量能。
4. 首板当天概念/行业板块共振：板块涨幅、涨幅排名、板块内涨停家数、
   是否板块内最早封板、板块 5/20 日动量。
5. 首板涨停时间段 × 触板数/封板率/成龙率/D+1 收益（打板可执行口径）。

样本提取与连板段去重完全复用 v1（每段连板只留 ``limit_times==1`` 的首板，
``eventual_peak >= min_consecutive_boards`` 为正样本）。所有因子仅用 D 日及之前
可观测数据；``eventual_peak`` 与 ``d1_*`` 是未来标签，仅用于对照分组，绝不作为
可交易因子。

研究脚本只读 PostgreSQL，只写 ``memory/06_backtests`` 证据文件，绝不触碰
实时表、API、portfolio 或 ``actionable_recommendations``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

from alphaagent.server.services.limit_up.consecutive_leader_first_board_factor_research import (
    _prior_3d_shape,
    _seal_quality,
    compare_categorical_factor,
    compare_numeric_factor,
    compute_prior_limit_counts,
    extract_first_board_samples,
)
from alphaagent.server.services.limit_up.domain import normalize_limit_time
from alphaagent.server.services.limit_up.features import prior_stock_features
from alphaagent.server.services.limit_up.repository import (
    load_daily_bars_all,
    load_limit_up_dataset,
    load_sector_daily_bars,
    load_sector_memberships_all,
)
from alphaagent.server.services.limit_up.time_bucket_research import (
    TIME_BUCKETS,
    classify_first_limit_time,
)

STUDY_VERSION = "leader-first-board-deep-factor-v2"
DEFAULT_MIN_CONSECUTIVE_BOARDS = 3
DEFAULT_BOARD_GAP_MODE = "wave"  # wave = 允许断板日的连板浪（provider 连板数语义）
DAILY_LOOKBACK_DAYS = 320  # 覆盖 126 个交易日回看 + 节假日余量
DAILY_FORWARD_DAYS = 15  # 覆盖 D+1 标签（含长假）
SECTOR_LOOKBACK_DAYS = 70  # 板块 20 日动量 + 余量
COMPARE_DRAWS = 2000
COMPARE_SEED = 20260801


def _bool(value: object) -> bool:
    return bool(value)


def _integer(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


# ── 板块归属 / 板型 ────────────────────────────────────────────────────


def _board_type(vt_symbol: str) -> str:
    code = vt_symbol.split(".")[0]
    if code.startswith(("60", "00")):
        return "main"
    if code.startswith("30"):
        return "chinext"
    if code.startswith("68"):
        return "star"
    return "other"


def _is_st_name(name: object) -> bool:
    return "ST" in str(name or "").upper()


# ── 走势窗口因子（D-10..D-4 / 近半年）──────────────────────────────────

_MID_KEYS = (
    "prior_4_10d_return_pct",
    "prior_4_10d_max_change_pct",
    "prior_4_10d_up_days",
    "prior_10d_amplitude_pct",
    "turnover_ratio_3d_vs_prev7d",
)


def _mid_window_features(bars_before: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """D-10..D-4（前 3 天之前）走势与前 3 天相对量能。"""

    out: dict[str, object] = {key: None for key in _MID_KEYS}
    if len(bars_before) < 11:
        return out
    w7 = list(bars_before[-10:-3])  # D-10..D-4
    w10 = list(bars_before[-10:])  # D-10..D-1
    w3 = list(bars_before[-3:])  # D-3..D-1
    base_close = _number(bars_before[-11].get("close_price"))
    w7_last_close = _number(w7[-1].get("close_price"))
    if base_close and w7_last_close:
        out["prior_4_10d_return_pct"] = round((w7_last_close / base_close - 1) * 100, 4)
    changes = [
        value
        for value in (_number(row.get("change_pct")) for row in w7)
        if value is not None
    ]
    if changes:
        out["prior_4_10d_max_change_pct"] = round(max(changes), 4)
        out["prior_4_10d_up_days"] = sum(1 for value in changes if value > 0)
    highs = [v for v in (_number(row.get("high_price")) for row in w10) if v is not None]
    lows = [v for v in (_number(row.get("low_price")) for row in w10) if v]
    if highs and lows and min(lows) > 0:
        out["prior_10d_amplitude_pct"] = round(
            (max(highs) - min(lows)) / min(lows) * 100, 4
        )
    turnover_3d = [
        v for v in (_number(row.get("turnover")) for row in w3) if v is not None
    ]
    turnover_7d = [
        v for v in (_number(row.get("turnover")) for row in w7) if v is not None
    ]
    if turnover_3d and turnover_7d and mean(turnover_7d) > 0:
        out["turnover_ratio_3d_vs_prev7d"] = round(mean(turnover_3d) / mean(turnover_7d), 4)
    return out


_LONG_KEYS = (
    "return_20d_pct",
    "return_60d_pct",
    "return_126d_pct",
    "position_126d",
    "drawdown_from_126d_high_pct",
    "rebound_from_126d_low_pct",
    "amplitude_126d_pct",
    "volume_ratio_5_60",
    "days_since_126d_high",
    "days_since_126d_low",
)


def _long_window_features(bars_before: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """近半年（D-126..D-1）大周期位置与长期量能。"""

    out: dict[str, object] = {key: None for key in _LONG_KEYS}
    closes = [_number(row.get("close_price")) for row in bars_before]
    last_close = closes[-1] if closes else None
    if last_close is None:
        return out
    if len(bars_before) >= 21 and closes[-21]:
        out["return_20d_pct"] = round((last_close / closes[-21] - 1) * 100, 4)
    if len(bars_before) >= 61 and closes[-61]:
        out["return_60d_pct"] = round((last_close / closes[-61] - 1) * 100, 4)
    if len(bars_before) >= 127 and closes[-127]:
        out["return_126d_pct"] = round((last_close / closes[-127] - 1) * 100, 4)
    if len(bars_before) < 126:
        return out
    w126 = list(bars_before[-126:])
    highs_raw = [_number(row.get("high_price")) for row in w126]
    lows_raw = [_number(row.get("low_price")) for row in w126]
    if any(value is None for value in highs_raw + lows_raw):
        return out
    highs = [float(value) for value in highs_raw if value is not None]
    lows = [float(value) for value in lows_raw if value is not None]
    high_126 = max(highs)
    low_126 = min(lows)
    if low_126 <= 0 or high_126 <= low_126:
        return out
    out["position_126d"] = round((last_close - low_126) / (high_126 - low_126), 4)
    out["drawdown_from_126d_high_pct"] = round((last_close / high_126 - 1) * 100, 4)
    out["rebound_from_126d_low_pct"] = round((last_close / low_126 - 1) * 100, 4)
    out["amplitude_126d_pct"] = round((high_126 - low_126) / low_126 * 100, 4)
    out["days_since_126d_high"] = len(w126) - 1 - max(
        range(len(w126)), key=lambda index: highs[index]
    )
    out["days_since_126d_low"] = len(w126) - 1 - min(
        range(len(w126)), key=lambda index: lows[index]
    )
    turnover_5 = [
        v for v in (_number(row.get("turnover")) for row in w126[-5:]) if v is not None
    ]
    turnover_60 = [
        v for v in (_number(row.get("turnover")) for row in w126[-60:]) if v is not None
    ]
    if turnover_5 and turnover_60 and mean(turnover_60) > 0:
        out["volume_ratio_5_60"] = round(mean(turnover_5) / mean(turnover_60), 4)
    return out


# ── 板块共振上下文 ─────────────────────────────────────────────────────


class _SectorContext:
    """预计算的板块共振查找表（全部为 D 日及之前可观测口径）。"""

    def __init__(self) -> None:
        self.member_map: dict[str, dict[str, list[str]]] = {}
        self.sector_change: dict[tuple[str, str], float] = {}
        self.sector_rank_pct: dict[tuple[str, str], float] = {}
        self.sector_return_prev: dict[tuple[str, str], dict[str, float]] = {}
        self.sector_limit_count: dict[tuple[str, str], int] = {}
        self.sector_earliest_time: dict[tuple[str, str], str] = {}
        self.sector_limit_rank_pct: dict[tuple[str, str], float] = {}


def build_sector_context(
    events: Sequence[Mapping[str, object]],
    memberships: Sequence[Mapping[str, object]],
    sector_bars: Sequence[Mapping[str, object]],
) -> _SectorContext:
    """从事件、归属快照、板块指数日线构建板块共振查找表。

    涨停家数/最早封板用 sealed 事件自算（与样本同一口径）；板块涨幅排名
    按当日全板块 ``change_pct`` 分位；板块动量用严格 D 日之前的指数收盘。
    """

    ctx = _SectorContext()
    member_map: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in memberships:
        symbol = str(row.get("vt_symbol") or "")
        sector_id = str(row.get("sector_id") or "")
        sector_type = str(row.get("sector_type") or "")
        if symbol and sector_id and sector_type:
            member_map[symbol][sector_type].append(sector_id)
    ctx.member_map = {symbol: dict(types) for symbol, types in member_map.items()}
    bars_by_sector: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in sector_bars:
        bars_by_sector[str(bar.get("sector_id") or "")].append(bar)
    change_by_date: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for sector_id, rows in bars_by_sector.items():
        ordered = sorted(rows, key=lambda row: str(row.get("trade_date") or ""))
        for index, bar in enumerate(ordered):
            trade_date = str(bar.get("trade_date") or "")
            change = _number(bar.get("change_pct"))
            if change is not None:
                ctx.sector_change[(sector_id, trade_date)] = change
                change_by_date[trade_date].append((sector_id, change))
            closes = [_number(row.get("close_price")) for row in ordered[:index]]
            if not closes or not closes[-1]:
                continue
            momentum: dict[str, float] = {}
            if len(closes) >= 6 and closes[-6]:
                momentum["r5"] = round((closes[-1] / closes[-6] - 1) * 100, 4)
            if len(closes) >= 21 and closes[-21]:
                momentum["r20"] = round((closes[-1] / closes[-21] - 1) * 100, 4)
            if momentum:
                ctx.sector_return_prev[(sector_id, trade_date)] = momentum
    for trade_date, entries in change_by_date.items():
        ordered_changes = sorted(change for _, change in entries)
        total = len(ordered_changes)
        for sector_id, change in entries:
            # 分位 = 当日涨幅不超过本板块的板块占比（1 = 全市场最热板块）
            rank = sum(1 for value in ordered_changes if value <= change) / total
            ctx.sector_rank_pct[(sector_id, trade_date)] = round(rank, 4)

    sealed_by_date: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    for event in events:
        if not _bool(event.get("is_sealed")):
            continue
        sealed_by_date[str(event.get("trade_date") or "")].append(
            (
                str(event.get("vt_symbol") or ""),
                normalize_limit_time(event.get("first_limit_time")),
            )
        )
    for trade_date, sealed in sealed_by_date.items():
        for symbol, first_time in sealed:
            for sector_type in ("concept", "industry"):
                for sector_id in member_map.get(symbol, {}).get(sector_type, []):
                    key = (trade_date, sector_id)
                    ctx.sector_limit_count[key] = ctx.sector_limit_count.get(key, 0) + 1
                    if first_time:
                        current = ctx.sector_earliest_time.get(key)
                        if current is None or first_time < current:
                            ctx.sector_earliest_time[key] = first_time
    count_by_date: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for (trade_date, sector_id), count in ctx.sector_limit_count.items():
        count_by_date[trade_date].append((sector_id, count))
    for trade_date, entries in count_by_date.items():
        ordered_counts = sorted(count for _, count in entries)
        total = len(ordered_counts)
        for sector_id, count in entries:
            # 涨停家数在当日活跃板块中的分位（1 = 当日涨停最密集的板块）
            rank = sum(1 for value in ordered_counts if value <= count) / total
            ctx.sector_limit_rank_pct[(trade_date, sector_id)] = round(rank, 4)
    return ctx


_SECTOR_PREFIXES = ("concept", "industry")


def _sector_features(
    symbol: str,
    trade_date: str,
    first_limit_time: str | None,
    ctx: _SectorContext,
) -> dict[str, object]:
    """首板当天所属概念/行业板块的共振强度（D 日可观测口径）。"""

    out: dict[str, object] = {}
    for prefix in _SECTOR_PREFIXES:
        sector_ids = ctx.member_map.get(symbol, {}).get(prefix, [])
        out[f"{prefix}_count"] = len(sector_ids)
        changes = [
            ctx.sector_change[(sector_id, trade_date)]
            for sector_id in sector_ids
            if (sector_id, trade_date) in ctx.sector_change
        ]
        out[f"{prefix}_max_change_d"] = round(max(changes), 4) if changes else None
        out[f"{prefix}_avg_change_d"] = round(mean(changes), 4) if changes else None
        ranks = [
            ctx.sector_rank_pct[(sector_id, trade_date)]
            for sector_id in sector_ids
            if (sector_id, trade_date) in ctx.sector_rank_pct
        ]
        out[f"{prefix}_best_rank_pct"] = round(max(ranks), 4) if ranks else None
        counts = [
            ctx.sector_limit_count.get((trade_date, sector_id), 0)
            for sector_id in sector_ids
        ]
        out[f"{prefix}_max_limit_up_d"] = max(counts) if counts else None
        limit_ranks = [
            ctx.sector_limit_rank_pct[(trade_date, sector_id)]
            for sector_id in sector_ids
            if (trade_date, sector_id) in ctx.sector_limit_rank_pct
        ]
        out[f"{prefix}_max_limit_up_rank_pct"] = (
            round(max(limit_ranks), 4) if limit_ranks else None
        )
        earliest_hits = [
            sector_id
            for sector_id in sector_ids
            if first_limit_time
            and ctx.sector_earliest_time.get((trade_date, sector_id)) == first_limit_time
        ]
        out[f"{prefix}_earliest_seal"] = (
            1.0 if earliest_hits else (0.0 if first_limit_time else None)
        )
        momentum_5d = [
            ctx.sector_return_prev[(sector_id, trade_date)]["r5"]
            for sector_id in sector_ids
            if "r5" in ctx.sector_return_prev.get((sector_id, trade_date), {})
        ]
        momentum_20d = [
            ctx.sector_return_prev[(sector_id, trade_date)]["r20"]
            for sector_id in sector_ids
            if "r20" in ctx.sector_return_prev.get((sector_id, trade_date), {})
        ]
        out[f"{prefix}_max_return_5d"] = round(max(momentum_5d), 4) if momentum_5d else None
        out[f"{prefix}_max_return_20d"] = (
            round(max(momentum_20d), 4) if momentum_20d else None
        )
    return out


# ── D+1 标签（未来标签，仅对照用）───────────────────────────────────────


def _d1_labels(
    bars: Sequence[Mapping[str, object]],
    d_index: int,
    calendar: Sequence[str],
    day_number: Mapping[str, int],
) -> dict[str, object]:
    """D+1 开盘/收盘/最高相对 D 日收盘（≈涨停价）的收益——打板可执行口径。"""

    out: dict[str, object] = {
        "d1_open_return_pct": None,
        "d1_close_return_pct": None,
        "d1_high_return_pct": None,
    }
    trade_date = str(bars[d_index].get("trade_date") or "")
    if trade_date not in day_number or day_number[trade_date] + 1 >= len(calendar):
        return out
    next_date = calendar[day_number[trade_date] + 1]
    d1_bar = next(
        (row for row in bars[d_index + 1 :] if str(row.get("trade_date") or "") == next_date),
        None,
    )
    d_close = _number(bars[d_index].get("close_price"))
    if d1_bar is None or not d_close:
        return out
    d1_open = _number(d1_bar.get("open_price"))
    d1_close = _number(d1_bar.get("close_price"))
    d1_high = _number(d1_bar.get("high_price"))
    if d1_open:
        out["d1_open_return_pct"] = round((d1_open / d_close - 1) * 100, 4)
    if d1_close:
        out["d1_close_return_pct"] = round((d1_close / d_close - 1) * 100, 4)
    if d1_high:
        out["d1_high_return_pct"] = round((d1_high / d_close - 1) * 100, 4)
    return out


# ── 样本因子合成 ───────────────────────────────────────────────────────


def extract_deep_factor_vector(
    sample: Mapping[str, object],
    *,
    bars: Sequence[Mapping[str, object]],
    d_index: int,
    calendar: Sequence[str],
    day_number: Mapping[str, int],
    prior_limits: Mapping[str, object],
    sector_ctx: _SectorContext,
    market_counts: Mapping[str, int],
) -> dict[str, object]:
    """单个首板样本的全部因子（D 日及之前可观测）+ 对照标签。"""

    symbol = str(sample.get("vt_symbol") or "")
    trade_date = str(sample.get("trade_date") or "")
    bars_before = list(bars[:d_index])
    d_bar = bars[d_index]
    first_limit_time = normalize_limit_time(sample.get("first_limit_time"))
    bucket = classify_first_limit_time(sample.get("first_limit_time"))
    prior = prior_stock_features(list(bars), trade_date)
    shape = _prior_3d_shape(list(bars), trade_date)
    seal = _seal_quality(sample, d_bar)
    features: dict[str, object] = {
        "vt_symbol": symbol,
        "name": sample.get("name"),
        "trade_date": trade_date,
        "board_type": _board_type(symbol),
        "is_st": _is_st_name(sample.get("name")),
        "first_limit_time_bucket": bucket[0] if bucket else None,
        "first_limit_hour": (
            int(first_limit_time.split(":")[0]) if first_limit_time else None
        ),
        "is_early_seal": bool(first_limit_time and first_limit_time <= "10:00:00"),
        # 前 5 日 / 前 3 天（v1）
        "prior_return_5d_pct": prior["prior_return_5d_pct"],
        "prior_turnover_ratio_5d": prior["prior_turnover_ratio_5d"],
        "prior_change_pct": prior["prior_change_pct"],
        **shape,
        # 封板质量（v1）
        **seal,
        # 前 3 天之前 / 近半年（新）
        **_mid_window_features(bars_before),
        **_long_window_features(bars_before),
        # 涨停基因（v1）
        "prior_limit_count_126": prior_limits.get("prior_limit_count_126"),
        "prior_limit_count_20": prior_limits.get("prior_limit_count_20"),
        "days_since_prior_limit": prior_limits.get("days_since_prior_limit"),
        # 板块共振（新）
        **_sector_features(symbol, trade_date, first_limit_time, sector_ctx),
        # 市场情绪温度（新）：当日全市场封板数 / 首板数
        "market_sealed_count_d": market_counts.get("sealed"),
        "market_first_board_count_d": market_counts.get("first_board"),
        # 市值/流动性
        "float_market_cap": _number(sample.get("float_market_cap")),
        "turnover_rate": _number(sample.get("turnover_rate")),
        # 标签（仅供对照）
        "is_leader": sample.get("is_leader"),
        "eventual_peak": sample.get("eventual_peak"),
        **_d1_labels(bars, d_index, calendar, day_number),
    }
    return features


# ── 时间段 × 触板/封板/成龙/D+1 交叉 ────────────────────────────────────


def build_time_bucket_cross(
    events: Sequence[Mapping[str, object]],
    factor_samples: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """按首次触板时段统计触板数、封板率、首板成龙率与 D+1 收益。"""

    touch: dict[str, int] = defaultdict(int)
    sealed: dict[str, int] = defaultdict(int)
    for event in events:
        bucket = classify_first_limit_time(event.get("first_limit_time"))
        if bucket is None:
            continue
        touch[bucket[0]] += 1
        if _bool(event.get("is_sealed")):
            sealed[bucket[0]] += 1

    rows: list[dict[str, object]] = []
    for bucket_key, bucket_label, *_ in TIME_BUCKETS:
        members = [
            sample
            for sample in factor_samples
            if sample.get("first_limit_time_bucket") == bucket_key
        ]
        leaders = sum(1 for sample in members if _bool(sample.get("is_leader")))
        one_word = sum(1 for sample in members if _bool(sample.get("is_one_word_board")))
        d1_returns = [
            value
            for value in (
                _number(sample.get("d1_open_return_pct")) for sample in members
            )
            if value is not None
        ]
        touch_count = touch.get(bucket_key, 0)
        rows.append(
            {
                "bucket_key": bucket_key,
                "bucket_label": bucket_label,
                "touch_count": touch_count,
                "sealed_count": sealed.get(bucket_key, 0),
                "seal_rate": round(sealed.get(bucket_key, 0) / touch_count, 4)
                if touch_count
                else None,
                "first_board_count": len(members),
                "leader_count": leaders,
                "leader_rate": round(leaders / len(members), 4) if members else None,
                "one_word_share": round(one_word / len(members), 4) if members else None,
                "d1_open_return_mean": round(mean(d1_returns), 4) if d1_returns else None,
                "d1_open_win_rate": round(
                    sum(1 for value in d1_returns if value > 0) / len(d1_returns), 4
                )
                if d1_returns
                else None,
            }
        )
    return rows


# ── 组合假设（先验设定，非事后搜索）─────────────────────────────────────


def _f(sample: Mapping[str, object], key: str) -> float | None:
    return _sample_float(sample.get(key))


COMBO_DEFINITIONS: tuple[tuple[str, str, Callable[[Mapping[str, object]], bool]], ...] = (
    (
        "near_high_main",
        "距半年高点 ≤13%（强势位）且主板",
        lambda s: (
            (_f(s, "drawdown_from_126d_high_pct") or -999.0) >= -13.0
            and s.get("board_type") == "main"
        ),
    ),
    (
        "near_high_early_main",
        "距半年高点 ≤13% 且 10:00 前封板且主板",
        lambda s: (
            (_f(s, "drawdown_from_126d_high_pct") or -999.0) >= -13.0
            and _bool(s.get("is_early_seal"))
            and s.get("board_type") == "main"
        ),
    ),
    (
        "cold_sector_warm",
        "板块涨停家数 ≤20（非高潮）且板块20日涨幅 >5% 且主板",
        lambda s: (
            (_f(s, "concept_max_limit_up_d") or 0.0) <= 20.0
            and (_f(s, "concept_max_return_20d") or -999.0) > 5.0
            and s.get("board_type") == "main"
        ),
    ),
    (
        "full_setup",
        "强势位+早封+板块走强+小市值(≤120亿)+前3天放量(≥1.2)+主板",
        lambda s: (
            (_f(s, "drawdown_from_126d_high_pct") or -999.0) >= -13.0
            and _bool(s.get("is_early_seal"))
            and (_f(s, "concept_max_return_20d") or -999.0) > 5.0
            and (_f(s, "float_market_cap") or 1e18) <= 1.2e10
            and (_f(s, "turnover_ratio_3d_vs_prev7d") or 0.0) >= 1.2
            and s.get("board_type") == "main"
        ),
    ),
)


def evaluate_combos(
    samples: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """评估先验组合假设的成龙率与 D+1 收益（对照全样本基线）。"""

    def _stats(members: Sequence[Mapping[str, object]]) -> dict[str, object]:
        leaders = sum(1 for sample in members if _bool(sample.get("is_leader")))
        d1_returns = [
            value
            for value in (_number(sample.get("d1_open_return_pct")) for sample in members)
            if value is not None
        ]
        return {
            "total": len(members),
            "leader_count": leaders,
            "leader_rate": round(leaders / len(members), 4) if members else None,
            "d1_open_return_mean": round(mean(d1_returns), 4) if d1_returns else None,
            "d1_open_win_rate": round(
                sum(1 for value in d1_returns if value > 0) / len(d1_returns), 4
            )
            if d1_returns
            else None,
        }

    rows: list[dict[str, object]] = [
        {"combo": "__baseline__", "description": "全样本基线", **_stats(samples)}
    ]
    for name, description, predicate in COMBO_DEFINITIONS:
        members = [sample for sample in samples if predicate(sample)]
        rows.append({"combo": name, "description": description, **_stats(members)})
    return rows


# ── 分位 × 结局（成龙率 + D+1 收益）─────────────────────────────────────


def _quintile_outcomes(
    samples: Sequence[Mapping[str, object]], factor_key: str, *, buckets: int = 5
) -> list[dict[str, object]]:
    valued = sorted(
        (
            (value, sample)
            for sample in samples
            if (value := _sample_float(sample.get(factor_key))) is not None
        ),
        key=lambda item: item[0],
    )
    total = len(valued)
    if total < buckets:
        return []
    rows: list[dict[str, object]] = []
    for index in range(buckets):
        chunk = valued[index * total // buckets : (index + 1) * total // buckets]
        if not chunk:
            continue
        leaders = sum(1 for _, sample in chunk if _bool(sample.get("is_leader")))
        d1_returns = [
            value
            for value in (_number(sample.get("d1_open_return_pct")) for _, sample in chunk)
            if value is not None
        ]
        rows.append(
            {
                "quintile": index + 1,
                "total": len(chunk),
                "leader_rate": round(leaders / len(chunk), 4),
                "d1_open_return_mean": round(mean(d1_returns), 4) if d1_returns else None,
                "d1_open_win_rate": round(
                    sum(1 for value in d1_returns if value > 0) / len(d1_returns), 4
                )
                if d1_returns
                else None,
                "value_min": round(chunk[0][0], 4),
                "value_max": round(chunk[-1][0], 4),
            }
        )
    return rows


def _sample_float(value: object) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _categorical_outcomes(
    samples: Sequence[Mapping[str, object]], factor_key: str
) -> dict[str, object]:
    """分类因子各类的成龙率与 D+1 收益（按成龙率降序）。"""

    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for sample in samples:
        category = sample.get(factor_key)
        if category is None:
            continue
        grouped[str(category)].append(sample)
    categories: list[dict[str, object]] = []
    for key, members in grouped.items():
        leaders = sum(1 for sample in members if _bool(sample.get("is_leader")))
        d1_returns = [
            value
            for value in (_number(sample.get("d1_open_return_pct")) for sample in members)
            if value is not None
        ]
        categories.append(
            {
                "category": key,
                "total": len(members),
                "leader_rate": round(leaders / len(members), 4) if members else None,
                "d1_open_return_mean": round(mean(d1_returns), 4) if d1_returns else None,
                "d1_open_win_rate": round(
                    sum(1 for value in d1_returns if value > 0) / len(d1_returns), 4
                )
                if d1_returns
                else None,
            }
        )
    categories.sort(key=lambda item: item.get("leader_rate") or 0.0, reverse=True)
    return {"factor_key": factor_key, "categories": categories}


# ── 报告编排 ───────────────────────────────────────────────────────────

NUMERIC_FACTOR_KEYS = (
    # D 日封板质量（盘中可观测）
    "first_limit_hour",
    "is_early_seal",
    "open_times",
    "seal_to_turnover_ratio",
    "is_one_word_board",
    "is_clean_seal",
    # 前 3 天（v1）
    "prior_change_pct",
    "prior_return_5d_pct",
    "prior_turnover_ratio_5d",
    "prior_3d_cum_return_pct",
    "prior_3d_max_change_pct",
    "prior_3d_up_days",
    "prior_day_body_pct",
    "prior_day_range_pct",
    "prior_day_close_position",
    # 前 3 天之前 D-10..D-4（新）
    "prior_4_10d_return_pct",
    "prior_4_10d_max_change_pct",
    "prior_4_10d_up_days",
    "prior_10d_amplitude_pct",
    "turnover_ratio_3d_vs_prev7d",
    # 近半年（新）
    "return_20d_pct",
    "return_60d_pct",
    "return_126d_pct",
    "position_126d",
    "drawdown_from_126d_high_pct",
    "rebound_from_126d_low_pct",
    "amplitude_126d_pct",
    "volume_ratio_5_60",
    "days_since_126d_high",
    "days_since_126d_low",
    # 涨停基因（v1）
    "prior_limit_count_126",
    "prior_limit_count_20",
    "days_since_prior_limit",
    # 板块共振（新）
    "concept_count",
    "concept_max_change_d",
    "concept_avg_change_d",
    "concept_best_rank_pct",
    "concept_max_limit_up_d",
    "concept_max_limit_up_rank_pct",
    "concept_earliest_seal",
    "concept_max_return_5d",
    "concept_max_return_20d",
    "industry_max_change_d",
    "industry_best_rank_pct",
    "industry_max_limit_up_d",
    "industry_max_limit_up_rank_pct",
    "industry_earliest_seal",
    "industry_max_return_5d",
    "industry_max_return_20d",
    # 市场情绪温度（新）
    "market_sealed_count_d",
    "market_first_board_count_d",
    # 市值/流动性
    "float_market_cap",
    "turnover_rate",
)
CATEGORICAL_FACTOR_KEYS = ("board_type", "is_st")

_RESEARCH_NOTES = (
    "eventual_peak / d1_* 是未来标签，仅用于对照分组，绝不作为可交易因子。",
    "连板段切分用 wave 模式：provider 连板数递增/持平即同一浪（允许断板日），"
    "重新计 1 板或下降开新浪——覆盖「N 天 M 板」断板续板型妖股（锋龙股份 17 板型）；"
    "strict 模式（严格相邻+严格递增）会把此类浪切碎漏掉。",
    "板块归属用当前快照（历史快照仅 2026-07-13 起 15 天，不足以回溯 13 个月），"
    "个股历史板块归属可能漂移，板块共振因子解读需留此余量。",
    "板块当日涨幅/涨停家数在盘中逐步可观测、收盘完整；打板决策时刻看到的是近似值。",
    "样本仅覆盖 stock_events 现有区间（约 2025-06-27 起 13 个月），跨牛熊周期不足。",
    "D+1 收益口径 = D+1 开盘价 / D 日收盘价（≈涨停价）- 1，即涨停价打板、次日竞价卖出的毛利，未扣费。",
)


def build_factor_samples(
    events: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    memberships: Sequence[Mapping[str, object]],
    sector_bars: Sequence[Mapping[str, object]],
    *,
    min_consecutive_boards: int = DEFAULT_MIN_CONSECUTIVE_BOARDS,
    board_gap_mode: str = DEFAULT_BOARD_GAP_MODE,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """提取首板样本并合成全部因子向量（深度研究与稳定性研究共用）。"""

    samples = extract_first_board_samples(
        events,
        calendar,
        min_consecutive_boards=min_consecutive_boards,
        board_gap_mode=board_gap_mode,
    )
    prior_limits = compute_prior_limit_counts(samples, events, calendar)
    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in daily_bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)
    for symbol in bars_by_symbol:
        bars_by_symbol[symbol].sort(key=lambda row: str(row.get("trade_date") or ""))
    day_number = {value: index for index, value in enumerate(sorted(set(calendar)))}
    sector_ctx = build_sector_context(events, memberships, sector_bars)
    sealed_count_by_date: dict[str, int] = defaultdict(int)
    for event in events:
        if _bool(event.get("is_sealed")):
            sealed_count_by_date[str(event.get("trade_date") or "")] += 1
    first_board_count_by_date: dict[str, int] = defaultdict(int)
    for sample in samples:
        first_board_count_by_date[str(sample.get("trade_date") or "")] += 1

    factor_samples: list[dict[str, object]] = []
    for sample in samples:
        symbol = str(sample.get("vt_symbol") or "")
        trade_date = str(sample.get("trade_date") or "")
        bars = bars_by_symbol.get(symbol, [])
        index_by_date = {
            str(row.get("trade_date") or ""): idx for idx, row in enumerate(bars)
        }
        d_index = index_by_date.get(trade_date)
        if d_index is None:
            continue
        features = extract_deep_factor_vector(
            sample,
            bars=bars,
            d_index=d_index,
            calendar=sorted(day_number),
            day_number=day_number,
            prior_limits=prior_limits.get((symbol, trade_date), {}),
            sector_ctx=sector_ctx,
            market_counts={
                "sealed": sealed_count_by_date.get(trade_date, 0),
                "first_board": first_board_count_by_date.get(trade_date, 0),
            },
        )
        factor_samples.append(features)
    return samples, factor_samples


def build_deep_factor_report(
    events: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    memberships: Sequence[Mapping[str, object]],
    sector_bars: Sequence[Mapping[str, object]],
    *,
    min_consecutive_boards: int = DEFAULT_MIN_CONSECUTIVE_BOARDS,
    board_gap_mode: str = DEFAULT_BOARD_GAP_MODE,
    draws: int = COMPARE_DRAWS,
    seed: int = COMPARE_SEED,
) -> dict[str, object]:
    """编排深度因子挖掘（纯函数，不连数据库）。"""

    _, factor_samples = build_factor_samples(
        events,
        daily_bars,
        calendar,
        memberships,
        sector_bars,
        min_consecutive_boards=min_consecutive_boards,
        board_gap_mode=board_gap_mode,
    )

    numeric_ranking = [
        compare_numeric_factor(factor_samples, key, draws=draws, seed=seed)
        for key in NUMERIC_FACTOR_KEYS
    ]
    numeric_ranking.sort(key=lambda item: item.get("effect_strength") or 0.0, reverse=True)
    categorical_reports = {
        key: compare_categorical_factor(factor_samples, key)
        for key in CATEGORICAL_FACTOR_KEYS
    }
    categorical_outcome_reports = {
        key: _categorical_outcomes(factor_samples, key)
        for key in (*CATEGORICAL_FACTOR_KEYS, "first_limit_time_bucket")
    }
    quintile_outcome_reports = {
        key: _quintile_outcomes(factor_samples, key)
        for key in NUMERIC_FACTOR_KEYS
    }
    time_bucket_cross = build_time_bucket_cross(events, factor_samples)
    combo_rows = evaluate_combos(factor_samples)

    positive = sum(1 for sample in factor_samples if _bool(sample.get("is_leader")))
    return {
        "status": "ok" if factor_samples else "insufficient_data",
        "mode": "leader_first_board_deep_factor_lookahead_proxy",
        "execution_valid": False,
        "study_version": STUDY_VERSION,
        "min_consecutive_boards": min_consecutive_boards,
        "board_gap_mode": board_gap_mode,
        "first_board_count": len(factor_samples),
        "label_balance": {
            "positive": positive,
            "negative": len(factor_samples) - positive,
            "positive_rate": round(positive / len(factor_samples), 4)
            if factor_samples
            else None,
        },
        "numeric_factor_ranking": numeric_ranking,
        "categorical_factors": categorical_reports,
        "categorical_outcomes": categorical_outcome_reports,
        "quintile_outcomes": quintile_outcome_reports,
        "time_bucket_cross": time_bucket_cross,
        "combos": combo_rows,
        "notes": list(_RESEARCH_NOTES),
    }


def run_research(
    *,
    start: date,
    end: date,
    min_consecutive_boards: int = DEFAULT_MIN_CONSECUTIVE_BOARDS,
    board_gap_mode: str = DEFAULT_BOARD_GAP_MODE,
) -> dict[str, object]:
    """Load frozen dataset and return the deep first-board factor report."""

    dataset = load_limit_up_dataset(start, end)
    events = dataset["events"]
    daily_bars = load_daily_bars_all(
        start - timedelta(days=DAILY_LOOKBACK_DAYS),
        end + timedelta(days=DAILY_FORWARD_DAYS),
    )
    calendar = sorted(
        {str(bar.get("trade_date") or "") for bar in daily_bars if bar.get("trade_date")}
    )
    memberships = load_sector_memberships_all()
    sector_bars = load_sector_daily_bars(start - timedelta(days=SECTOR_LOOKBACK_DAYS), end)
    report = build_deep_factor_report(
        events,
        daily_bars,
        calendar,
        memberships,
        sector_bars,
        min_consecutive_boards=min_consecutive_boards,
        board_gap_mode=board_gap_mode,
    )
    coverage = dict(dataset.get("coverage") or {})
    coverage["trade_days_in_window"] = len(calendar)
    coverage["membership_rows"] = len(memberships)
    coverage["sector_bar_rows"] = len(sector_bars)
    report["start"] = start.isoformat()
    report["end"] = end.isoformat()
    report["coverage"] = coverage
    report["input_fingerprint"] = hashlib.sha256(
        f"{STUDY_VERSION}|{len(events)}|{len(daily_bars)}|{report['first_board_count']}".encode()
    ).hexdigest()[:16]
    return report


# ── Markdown 渲染 ──────────────────────────────────────────────────────


def render_markdown(result: Mapping[str, object]) -> str:
    """Render the deep first-board factor mining evidence."""

    balance = _mapping(result.get("label_balance"))
    coverage = _mapping(result.get("coverage"))
    ranking = result.get("numeric_factor_ranking") or []
    lines = [
        "# 连板龙头首板深度因子挖掘（v2）",
        "",
        "## Boundary",
        "",
        f"- 状态：`{str(result.get('status') or 'unavailable')}`；研究版本 `{str(result.get('study_version') or '-')}`。",
        "- 本报告只读 `stock_events`/`stock_daily_bars`/`sector_daily_bars`/板块归属快照，不改任何实时链路。",
        "- `eventual_peak` / `d1_*` 是未来标签，仅用于对照分组，绝不作为可交易因子。",
        f"- 连板阈值 `>= {_integer(result.get('min_consecutive_boards'))}` 板；去重 = 每段连板浪只留首板（`{str(result.get('board_gap_mode') or 'strict')}` 模式切分）。",
        "",
        "## Coverage",
        "",
        f"- 结算范围：`{str(result.get('start') or '-')}` 至 `{str(result.get('end') or '-')}`。",
        f"- 首板样本：{_integer(result.get('first_board_count'))} 个；输入指纹 `{str(result.get('input_fingerprint') or '-')}`。",
        f"- 板块归属行数：{_integer(coverage.get('membership_rows'))}；板块指数日线行数：{_integer(coverage.get('sector_bar_rows'))}。",
        "",
        "## Sample Balance",
        "",
        f"- 正样本（连板 >= 阈值）：{_integer(balance.get('positive'))}；"
        f"负样本：{_integer(balance.get('negative'))}；"
        f"正样本率：{_ratio_pct(balance.get('positive_rate'))}。",
        "",
        "## Numeric Factor Ranking（vs 成龙率，新+旧因子混合排行）",
        "",
        "| 因子 | 正/负 | 正均值 | 负均值 | AUC | 效应强度 | 方向 | 均值差 | 95%下限 | 95%上限 |",
        "|---|---:|---:|---:|---:|---:|---|---:|---:|---:|",
    ]
    for item in ranking:
        lines.append(_numeric_factor_row(item))
    cross = result.get("time_bucket_cross") or []
    if cross:
        lines.extend(
            [
                "",
                "## 时间段 × 触板/封板/成龙/D+1（首板涨停什么时间段更好）",
                "",
                "| 时段 | 触板数 | 封板数 | 封板率 | 首板数 | 成龙数 | 成龙率 | 一字占比 | D+1开盘收益 | D+1胜率 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in cross:
            item = _mapping(row)
            lines.append(
                f"| {str(item.get('bucket_label') or '-')} | {_integer(item.get('touch_count'))} | "
                f"{_integer(item.get('sealed_count'))} | {_ratio_pct(item.get('seal_rate'))} | "
                f"{_integer(item.get('first_board_count'))} | {_integer(item.get('leader_count'))} | "
                f"{_ratio_pct(item.get('leader_rate'))} | {_ratio_pct(item.get('one_word_share'))} | "
                f"{_pct_signed(item.get('d1_open_return_mean'))} | "
                f"{_ratio_pct(item.get('d1_open_win_rate'))} |"
            )
    combos = result.get("combos") or []
    if combos:
        lines.extend(
            [
                "",
                "## 组合假设（先验设定，非事后搜索；阈值来自排行/分位的方向性结论）",
                "",
                "| 组合 | 说明 | 样本 | 成龙数 | 成龙率 | D+1开盘收益 | D+1胜率 |",
                "|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in combos:
            item = _mapping(row)
            lines.append(
                f"| {str(item.get('combo') or '-')} | {str(item.get('description') or '-')} | "
                f"{_integer(item.get('total'))} | {_integer(item.get('leader_count'))} | "
                f"{_ratio_pct(item.get('leader_rate'))} | {_pct_signed(item.get('d1_open_return_mean'))} | "
                f"{_ratio_pct(item.get('d1_open_win_rate'))} |"
            )
    categorical_outcomes = _mapping(result.get("categorical_outcomes"))
    for key in ("board_type", "is_st", "first_limit_time_bucket"):
        report = _mapping(categorical_outcomes.get(key))
        categories = report.get("categories") or []
        if not categories:
            continue
        lines.extend(
            [
                "",
                f"## 分类因子 — {key}（成龙率 + D+1 收益）",
                "",
                "| 类别 | 样本 | 成龙率 | D+1开盘收益 | D+1胜率 |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for category in categories:
            row = _mapping(category)
            lines.append(
                f"| {str(row.get('category') or '-')} | {_integer(row.get('total'))} | "
                f"{_ratio_pct(row.get('leader_rate'))} | {_pct_signed(row.get('d1_open_return_mean'))} | "
                f"{_ratio_pct(row.get('d1_open_win_rate'))} |"
            )
    quintile_outcomes = _mapping(result.get("quintile_outcomes"))
    lines.extend(["", "## Top Factors — 五分位 ×（成龙率 + D+1 收益）", ""])
    for item in ranking[:8]:
        factor_key = str(item.get("factor_key") or "")
        rates = quintile_outcomes.get(factor_key) or []
        if not rates:
            continue
        lines.extend(
            [
                "",
                f"### {factor_key} (AUC={_fmt(item.get('auc'))}, 方向={str(item.get('direction') or '-')})",
                "",
                "| 分位 | 样本 | 成龙率 | D+1开盘收益 | D+1胜率 | 区间下限 | 区间上限 |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for rate in rates:
            row = _mapping(rate)
            lines.append(
                f"| Q{_integer(row.get('quintile'))} | {_integer(row.get('total'))} | "
                f"{_ratio_pct(row.get('leader_rate'))} | {_pct_signed(row.get('d1_open_return_mean'))} | "
                f"{_ratio_pct(row.get('d1_open_win_rate'))} | {_fmt(row.get('value_min'))} | {_fmt(row.get('value_max'))} |"
            )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "- 本报告为只读因子挖掘证据，`execution_valid` 恒为 False，不产出可执行信号。",
            "- 高效应因子仅作研究线索；任何上线须经独立自然前向验证与用户审批。",
            "",
            "## Evidence Boundary",
            "",
        ]
    )
    for note in result.get("notes") or []:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def _numeric_factor_row(item: Mapping[str, object]) -> str:
    return (
        f"| {str(item.get('factor_key') or '-')} | "
        f"{_integer(item.get('positive_count'))}/{_integer(item.get('negative_count'))} | "
        f"{_fmt(item.get('positive_mean'))} | {_fmt(item.get('negative_mean'))} | "
        f"{_fmt(item.get('auc'))} | {_fmt(item.get('effect_strength'))} | "
        f"{str(item.get('direction') or '-')} | "
        f"{_fmt(item.get('mean_delta'))} | {_fmt(item.get('mean_delta_lower_95'))} | "
        f"{_fmt(item.get('mean_delta_upper_95'))} |"
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _fmt(value: object) -> str:
    number = _number(value)
    return f"{number:.4f}" if number is not None else "-"


def _pct_signed(value: object) -> str:
    number = _number(value)
    return f"{number:+.2f}%" if number is not None else "-"


def _ratio_pct(value: object) -> str:
    number = _number(value)
    return f"{number * 100:.2f}%" if number is not None else "-"


def main(argv: Sequence[str] | None = None) -> None:
    """Run the deep first-board factor study and write evidence files."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--min-consecutive-boards", type=int, default=DEFAULT_MIN_CONSECUTIVE_BOARDS)
    parser.add_argument("--board-gap-mode", choices=("strict", "wave"), default=DEFAULT_BOARD_GAP_MODE)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    arguments = parser.parse_args(argv)

    result = run_research(
        start=arguments.start,
        end=arguments.end,
        min_consecutive_boards=arguments.min_consecutive_boards,
        board_gap_mode=arguments.board_gap_mode,
    )
    arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.json_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    arguments.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.markdown_output.write_text(render_markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
