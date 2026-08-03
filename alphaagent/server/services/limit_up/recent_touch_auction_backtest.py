"""涨停记忆 × 竞价缺口 打板回测（v1，只读研究模拟）。

模型（三轮结构研究裁决后的落地版，证据见 fused_score v2 报告 ⑩ 与结构报告 ⑮）：

- **通用因子（D-1 盘前可观测）**：近 20 个市场日内有过 zt/zbgc 触碰（涨停记忆/股性；
  三轮研究最强单条件：lift 2.51、≥2 板召回 50%）。
- **涨停因子（D 日竞价可观测）**：竞价缺口 = open(D)/close(D-1)-1 ∈ [1%, 4%)
  （可交易区间；≥4% 追高风险区、≥9.5% 一字买不进）。
- **买入** D 日开盘价；**卖出** T+1 = D+1 开盘价（A 股 T+1 当日不可卖）。
  另报 D 日 open→close 盘中口径（仅信息，不可执行）。
- **对照臂（单变量隔离）**：A 仅竞价（全市场 gap[1,4)）、B 组合（记忆+gap[1,4)，本模型）、
  C 记忆无确认（记忆+gap<1%）、D 追高（记忆+gap[4%,9.5%)）。
- **成本（预声明）**：双边 0.2%（佣金万 2.5×2 + 印花税千 0.5 + 滑点≈0.1%）。

只读研究脚本：不写任何数据库表。结局标签（当日触板/封板/首板峰值）仅用于分组统计，
绝不进入买入条件。仓位管理/复利是 v2 的事，本版报逐笔统计 + 月度一致性。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median

from alphaagent.server.services.a_share_universe import is_eligible_main_board
from alphaagent.server.services.limit_up.consecutive_leader_first_board_factor_research import (
    extract_first_board_samples,
)
from alphaagent.server.services.limit_up.leader_first_board_deep_factor_research import (
    _number,
)
from alphaagent.server.services.limit_up.leader_minute_backtest import (
    _is_first_board_candidate,
)
from alphaagent.server.services.limit_up.repository import (
    load_daily_bars_all,
    load_limit_up_dataset,
    load_stock_names,
)

STUDY_VERSION = "recent-touch-auction-backtest-v1"

# ── 预声明参数（不调参；记忆窗/缺口区间/成本全部来自上游研究裁决）─────────────
TOUCH_LOOKBACK_MARKET_DAYS = 20  # 涨停记忆窗（fused_score v2 的 L7 口径）
TRADEABLE_GAP_MIN_PCT = 1.0  # 竞价确认下限（梯度中 1-2% 起显著）
TRADEABLE_GAP_MAX_PCT = 4.0  # 可交易上限（≥4% 追高风险区）
CHASE_GAP_MAX_PCT = 9.5  # 一字板买不进的上限
COST_ROUND_TRIP_PCT = 0.2  # 双边成本：佣金万2.5×2 + 印花税千0.5 + 滑点≈0.1%
EVENTS_LOOKBACK_DAYS = 45  # 事件前向加载（覆盖 20 市场日记忆回溯删失）
BARS_FORWARD_DAYS = 10  # 日线后向加载（让窗口末尾交易能 T+1 出场）

# ── v2 持有卖出规则（主人 2026-08-03 定稿）─────────────────────────────────
# 买入后逐日检查：当日涨停（收盘>=前收×SEAL_THRESHOLD）→ 以收盘价（=涨停价）卖出
# 剩余仓位的一半；当日未涨停 → 以收盘价卖出全部剩余。T+1 买入当天不可卖，从次日走起。
SEAL_THRESHOLD = 1.098  # 主板涨停判定（与 _limit_flags 同口径）
MAX_HOLD_DAYS = 20  # 封顶持有天数（防停牌/连板拖死数据末端；预声明）

ARM_NAMES = ("A_auction_only", "B_combo", "C_touch_no_confirm", "D_chase")

_RESEARCH_NOTES = (
    "买入条件全部买入时可见（D-1 触碰史 + D 日竞价缺口）；结局标签（触板/封板/峰值）仅分组统计。",
    "v2 卖出规则（主人 2026-08-03 定稿）：持有期每日判定，涨停（收盘>=前收×1.098）以收盘价卖"
    "当前仓位一半，未涨停以收盘价全卖；封板日以涨停价成交现实可行（有排队买单），未涨停日"
    "以收盘价成交是日线粒度下的最晚确认价（真实交易可能更早，偏差方向不定）。",
    "成本按预声明双边 0.2% 逐笔扣减；未建模一字跌停无法卖出等极端情形（占比极小）。",
    "D+1 为该票下一根日线（停牌顺延，收益如实计）；D+1 开盘价缺失的笔剔除并计数。",
    "≥2板占比的分母限 D 日恰为首板的交易（wave 口径）；窗口末端峰值右删失，只作参考。",
    "逐笔等权统计，不做仓位管理/复利；日均笔数单列供容量评估（v2 再定组合层）。",
    "近 10 市场日内封过板的票按首板标签口径机械出不了「首板」，记忆臂的首板结局天然偏低——"
    "这不影响金钱收益口径（封板/触板/T+1 收益不受标签定义影响）。",
)


# ── 事件索引（触碰记忆 + 当日结局）──────────────────────────────────────────


def _touch_positions_by_symbol(
    events: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
) -> dict[str, list[int]]:
    """每票的 zt/zbgc 触碰日 → 市场日位置升序表（记忆窗判定用）。"""

    position = {day: index for index, day in enumerate(calendar)}
    touches: dict[str, list[int]] = defaultdict(list)
    for event in events:
        if event.get("event_type") not in ("limit_pool_zt", "limit_pool_zbgc"):
            continue
        day = str(event.get("trade_date") or "")
        if day in position:
            touches[str(event.get("vt_symbol") or "")].append(position[day])
    return {symbol: sorted(set(days)) for symbol, days in touches.items()}


def _had_recent_touch(
    touch_positions: Sequence[int], day_position: int, *, lookback: int
) -> bool:
    """[day_position-lookback, day_position-1] 内有无触碰（bisect O(log)）。"""

    left = bisect_left(touch_positions, day_position - lookback)
    right = bisect_left(touch_positions, day_position)
    return right > left


def _board_event_map(
    events: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str], str]:
    """{(symbol, date): "zt"|"zbgc"}（zt 优先）——当日触板/封板结局。"""

    out: dict[tuple[str, str], str] = {}
    for event in events:
        if event.get("event_type") not in ("limit_pool_zt", "limit_pool_zbgc"):
            continue
        key = (str(event.get("vt_symbol") or ""), str(event.get("trade_date") or ""))
        if event.get("event_type") == "limit_pool_zt":
            out[key] = "zt"
        else:
            out.setdefault(key, "zbgc")
    return out


# ── v2 持有卖出模拟（主人规则：涨停卖一半，不涨停全卖）────────────────────────


def _simulate_hold_exit(
    rows: Sequence[Mapping[str, object]], entry_index: int
) -> dict[str, object] | None:
    """从次日（T+1 可卖首日）起逐日走主人规则，返回卖出明细；开盘价缺失则 None。

    - 涨停日（close >= 前收×1.098）：以收盘价卖出当前仓位一半（封板时涨停价有排队买单，可成交）
    - 未涨停日：以收盘价卖出全部剩余（确认未封板后的当日可执行价；日线粒度无法更早）
    - 数据耗尽/达 MAX_HOLD_DAYS：以最后可得收盘价清仓（exit_reason 标记删失）
    收益 = Σ(每段卖出仓位×价格)/买入开盘价 - 1。
    """

    open_d = _number(rows[entry_index].get("open_price"))
    if not open_d or open_d <= 0:
        return None
    position = 1.0
    proceeds = 0.0
    seal_days = 0
    hold_days = 0
    exit_reason = "window_end"
    exit_date = str(rows[-1].get("trade_date") or "")
    last_close = open_d
    for index in range(entry_index + 1, len(rows)):
        close = _number(rows[index].get("close_price"))
        prev_close = _number(rows[index - 1].get("close_price"))
        if close is None or prev_close is None or prev_close <= 0:
            continue  # 缺数据日视同停牌：不可卖也不判定，顺延
        hold_days += 1
        last_close = close
        exit_date = str(rows[index].get("trade_date") or "")
        if close >= prev_close * SEAL_THRESHOLD:
            proceeds += (position / 2) * close
            position /= 2
            seal_days += 1
            if hold_days >= MAX_HOLD_DAYS:
                proceeds += position * close
                position = 0.0
                exit_reason = "max_hold"
                break
        else:
            proceeds += position * close
            position = 0.0
            exit_reason = "no_seal"
            break
    if position > 0:
        proceeds += position * last_close
    return {
        "v2_ret_pct": round((proceeds / open_d - 1) * 100, 4),
        "v2_seal_days": seal_days,
        "v2_hold_days": hold_days,
        "v2_exit_reason": exit_reason,
        "v2_exit_date": exit_date,
    }


# ── 交易条目生成（买入时可见条件 + 结局标签分离）──────────────────────────────


def generate_entries(
    daily_bars: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    names: Mapping[str, str],
    *,
    lookback: int = TOUCH_LOOKBACK_MARKET_DAYS,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    """全市场股票日扫描：每个可交易日生成一条（缺口/记忆/收益/结局），臂由调用方过滤。

    入场前提：主板合格 + D-1 未涨停（`_is_first_board_candidate` 口径）。
    收益：ret_intraday = close(D)/open(D)-1（仅信息）；ret_t1 = open(D+1)/open(D)-1（主口径）。
    D+1 开盘价缺失 → 剔除（dropped_no_exit 计数）。
    """

    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in daily_bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)
    for rows in bars_by_symbol.values():
        rows.sort(key=lambda row: str(row.get("trade_date") or ""))
    calendar_position = {day: index for index, day in enumerate(calendar)}
    touch_by_symbol = _touch_positions_by_symbol(events, calendar)
    board_map = _board_event_map(events)
    first_board_index = {
        (str(sample.get("vt_symbol") or ""), str(sample.get("trade_date") or "")): sample.get(
            "eventual_peak"
        )
        for sample in extract_first_board_samples(
            events, calendar, min_consecutive_boards=2, board_gap_mode="wave"
        )
    }

    entries: list[dict[str, object]] = []
    stats = {"scanned_days": 0, "dropped_no_exit": 0, "dropped_gap_data": 0}
    for symbol, rows in sorted(bars_by_symbol.items()):
        if not is_eligible_main_board(symbol, names.get(symbol, "")):
            continue
        dates = [str(row.get("trade_date") or "") for row in rows]
        touches = touch_by_symbol.get(symbol, [])
        for index in range(1, len(rows)):
            day = dates[index]
            day_position = calendar_position.get(day)
            if day_position is None:
                continue
            stats["scanned_days"] += 1
            if not _is_first_board_candidate(rows[:index]):
                continue
            open_d = _number(rows[index].get("open_price"))
            close_d = _number(rows[index].get("close_price"))
            close_d1 = _number(rows[index - 1].get("close_price"))
            if not open_d or not close_d1 or close_d1 <= 0 or close_d is None:
                stats["dropped_gap_data"] += 1
                continue
            open_next = (
                _number(rows[index + 1].get("open_price")) if index + 1 < len(rows) else None
            )
            if open_next is None or open_next <= 0:
                stats["dropped_no_exit"] += 1
                continue
            gap_pct = (open_d / close_d1 - 1) * 100
            board_today = board_map.get((symbol, day))
            entry = {
                "vt_symbol": symbol,
                "trade_date": day,
                "month": day[:7],
                "gap_pct": round(gap_pct, 4),
                "recent_touch": _had_recent_touch(touches, day_position, lookback=lookback),
                "ret_intraday_pct": round((close_d / open_d - 1) * 100, 4),
                "ret_t1_pct": round((open_next / open_d - 1) * 100, 4),
                "sealed": board_today == "zt",
                "touched": board_today is not None,
                "eventual_peak": first_board_index.get((symbol, day)),
            }
            hold_exit = _simulate_hold_exit(rows, index)
            if hold_exit is not None:
                entry.update(hold_exit)
            entries.append(entry)
    return entries, stats


# ── 臂过滤与汇总 ────────────────────────────────────────────────────────────


def _arm_filter(
    entry: Mapping[str, object],
    *,
    gap_min: float,
    gap_max: float,
    chase_max: float,
) -> tuple[str, ...]:
    """条目归属的臂（A 与 B 可重叠；C/D 与 A/B 互斥）。"""

    gap = float(entry.get("gap_pct") or 0.0)
    touch = entry.get("recent_touch") is True
    arms: list[str] = []
    if gap_min <= gap < gap_max:
        arms.append("A_auction_only")
        if touch:
            arms.append("B_combo")
    if touch and gap < gap_min:
        arms.append("C_touch_no_confirm")
    if touch and gap_max <= gap < chase_max:
        arms.append("D_chase")
    return tuple(arms)


def _quartiles(values: Sequence[float]) -> tuple[float | None, float | None]:
    if len(values) < 4:
        return None, None
    ordered = sorted(values)
    return ordered[len(ordered) // 4], ordered[(3 * len(ordered)) // 4]


def summarize_entries(
    entries: Sequence[Mapping[str, object]], *, cost_pct: float = COST_ROUND_TRIP_PCT
) -> dict[str, object]:
    """逐笔等权汇总：v1（T+1 开盘卖）与 v2（涨停卖一半/不涨停全卖）双口径。"""

    if not entries:
        return {
            "trades": 0,
            "win_rate": None,
            "mean_t1_gross": None,
            "mean_t1_net": None,
            "median_t1_net": None,
            "p25_t1_net": None,
            "p75_t1_net": None,
            "sum_t1_net": None,
            "mean_intraday": None,
            "seal_rate": None,
            "touch_rate": None,
            "first_board_count": 0,
            "peak2_share": None,
            "v2_trades": 0,
            "v2_win_rate": None,
            "v2_mean_gross": None,
            "v2_mean_net": None,
            "v2_median_net": None,
            "v2_sum_net": None,
            "v2_mean_seal_days": None,
            "v2_mean_hold_days": None,
            "v2_exit_reasons": {},
        }
    t1 = [float(entry.get("ret_t1_pct") or 0.0) for entry in entries]
    net = [round(value - cost_pct, 4) for value in t1]
    intraday = [float(entry.get("ret_intraday_pct") or 0.0) for entry in entries]
    first_boards = [entry for entry in entries if entry.get("eventual_peak") is not None]
    peak2 = sum(
        1 for entry in first_boards if (float(entry.get("eventual_peak") or 0)) >= 2
    )
    p25, p75 = _quartiles(net)
    v2_entries = [entry for entry in entries if entry.get("v2_ret_pct") is not None]
    v2_gross = [float(entry.get("v2_ret_pct") or 0.0) for entry in v2_entries]
    v2_net = [round(value - cost_pct, 4) for value in v2_gross]
    exit_reasons: dict[str, int] = defaultdict(int)
    for entry in v2_entries:
        exit_reasons[str(entry.get("v2_exit_reason") or "unknown")] += 1
    return {
        "trades": len(entries),
        "win_rate": round(sum(1 for value in net if value > 0) / len(net), 4),
        "mean_t1_gross": round(mean(t1), 4),
        "mean_t1_net": round(mean(net), 4),
        "median_t1_net": round(median(net), 4),
        "p25_t1_net": round(p25, 4) if p25 is not None else None,
        "p75_t1_net": round(p75, 4) if p75 is not None else None,
        "sum_t1_net": round(sum(net), 2),
        "mean_intraday": round(mean(intraday), 4),
        "seal_rate": round(sum(1 for e in entries if e.get("sealed")) / len(entries), 4),
        "touch_rate": round(sum(1 for e in entries if e.get("touched")) / len(entries), 4),
        "first_board_count": len(first_boards),
        "peak2_share": round(peak2 / len(first_boards), 4) if first_boards else None,
        "v2_trades": len(v2_entries),
        "v2_win_rate": (
            round(sum(1 for value in v2_net if value > 0) / len(v2_net), 4) if v2_net else None
        ),
        "v2_mean_gross": round(mean(v2_gross), 4) if v2_gross else None,
        "v2_mean_net": round(mean(v2_net), 4) if v2_net else None,
        "v2_median_net": round(median(v2_net), 4) if v2_net else None,
        "v2_sum_net": round(sum(v2_net), 2) if v2_net else None,
        "v2_mean_seal_days": (
            round(mean([float(entry.get("v2_seal_days") or 0) for entry in v2_entries]), 3)
            if v2_entries
            else None
        ),
        "v2_mean_hold_days": (
            round(mean([float(entry.get("v2_hold_days") or 0) for entry in v2_entries]), 3)
            if v2_entries
            else None
        ),
        "v2_exit_reasons": dict(exit_reasons),
    }


def _gap_bucket(gap_pct: float) -> str:
    for low, high in ((-99, 0), (0, 1), (1, 2), (2, 4), (4, 9.5), (9.5, 999)):
        if low <= gap_pct < high:
            return f"{low}~{high}"
    return "other"


def build_backtest_report(
    entries: Sequence[Mapping[str, object]],
    scan_stats: Mapping[str, int],
    *,
    gap_min: float = TRADEABLE_GAP_MIN_PCT,
    gap_max: float = TRADEABLE_GAP_MAX_PCT,
    chase_max: float = CHASE_GAP_MAX_PCT,
    cost_pct: float = COST_ROUND_TRIP_PCT,
) -> dict[str, object]:
    """臂汇总 + B 臂缺口细分 + 记忆票缺口梯度 + B 臂逐月一致性。"""

    trade_days = len({str(entry.get("trade_date")) for entry in entries})
    arms: dict[str, list[Mapping[str, object]]] = {name: [] for name in ARM_NAMES}
    for entry in entries:
        for arm in _arm_filter(entry, gap_min=gap_min, gap_max=gap_max, chase_max=chase_max):
            arms[arm].append(entry)

    arm_rows = []
    for name in ARM_NAMES:
        summary = summarize_entries(arms[name], cost_pct=cost_pct)
        summary["arm"] = name
        summary["trades_per_day"] = (
            round(summary["trades"] / trade_days, 2) if trade_days else None
        )
        arm_rows.append(summary)

    # B 臂按缺口细分（1-2% / 2-4%）
    combo_bucket_rows = []
    for low, high in ((gap_min, 2.0), (2.0, gap_max)):
        members = [
            entry for entry in arms["B_combo"] if low <= float(entry.get("gap_pct") or 0) < high
        ]
        row = summarize_entries(members, cost_pct=cost_pct)
        row["bucket"] = f"{low}~{high}%"
        combo_bucket_rows.append(row)

    # 全部涨停记忆票的缺口六桶（梯度复核，不限臂）
    touch_entries = [entry for entry in entries if entry.get("recent_touch") is True]
    gradient_rows = []
    for bucket in ("-99~0", "0~1", "1~2", "2~4", "4~9.5", "9.5~999"):
        members = [entry for entry in touch_entries if _gap_bucket(float(entry.get("gap_pct") or 0)) == bucket]
        row = summarize_entries(members, cost_pct=cost_pct)
        row["bucket"] = bucket.replace("-99", "<0").replace("999", "不限")
        gradient_rows.append(row)

    # B 臂逐月一致性（胜率/净均值/笔数）
    by_month: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for entry in arms["B_combo"]:
        by_month[str(entry.get("month"))].append(entry)
    monthly_rows = []
    for month in sorted(by_month):
        row = summarize_entries(by_month[month], cost_pct=cost_pct)
        row["month"] = month
        monthly_rows.append(row)
    profitable_months = sum(
        1 for row in monthly_rows if (row.get("mean_t1_net") or 0) > 0
    )
    profitable_months_v2 = sum(
        1 for row in monthly_rows if (row.get("v2_mean_net") or 0) > 0
    )

    return {
        "trade_days": trade_days,
        "scan_stats": dict(scan_stats),
        "params": {
            "lookback": TOUCH_LOOKBACK_MARKET_DAYS,
            "gap_min": gap_min,
            "gap_max": gap_max,
            "chase_max": chase_max,
            "cost_pct": cost_pct,
            "seal_threshold": SEAL_THRESHOLD,
            "max_hold_days": MAX_HOLD_DAYS,
        },
        "arms": arm_rows,
        "combo_gap_buckets": combo_bucket_rows,
        "touch_gap_gradient": gradient_rows,
        "combo_monthly": monthly_rows,
        "combo_profitable_months": profitable_months,
        "combo_profitable_months_v2": profitable_months_v2,
        "combo_month_count": len(monthly_rows),
    }


def run_backtest(*, start: date, end: date) -> dict[str, object]:
    """加载数据并返回回测报告（事件前向 45 自然日，日线后向 10 自然日）。"""

    events = load_limit_up_dataset(start - timedelta(days=EVENTS_LOOKBACK_DAYS), end)["events"]
    daily_bars = load_daily_bars_all(
        start - timedelta(days=EVENTS_LOOKBACK_DAYS),
        end + timedelta(days=BARS_FORWARD_DAYS),
    )
    calendar = sorted(
        {str(bar.get("trade_date") or "") for bar in daily_bars if bar.get("trade_date")}
    )
    names = load_stock_names()
    entries, scan_stats = generate_entries(daily_bars, events, calendar, names)
    # 只统计样本窗口内的交易（前向加载的 bar 只供记忆/候选判定）
    window_entries = [
        entry
        for entry in entries
        if start.isoformat() <= str(entry.get("trade_date")) <= end.isoformat()
    ]
    report = build_backtest_report(window_entries, scan_stats)
    report["status"] = "ok" if window_entries else "insufficient_data"
    report["study_version"] = STUDY_VERSION
    report["start"] = start.isoformat()
    report["end"] = end.isoformat()
    report["notes"] = list(_RESEARCH_NOTES)
    report["input_fingerprint"] = hashlib.sha256(
        f"{STUDY_VERSION}|{len(events)}|{len(daily_bars)}|{len(window_entries)}".encode()
    ).hexdigest()[:16]
    return report


# ── Markdown 渲染 ─────────────────────────────────────────────────────────

_ARM_LABELS = {
    "A_auction_only": "A 仅竞价（全市场 1-4%）",
    "B_combo": "B 组合（涨停记忆 + 竞价 1-4%）",
    "C_touch_no_confirm": "C 记忆无确认（缺口<1%）",
    "D_chase": "D 追高（记忆 + 缺口 4-9.5%）",
}


def _pct(value: object) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "-"


def _rate(value: object) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def render_markdown(result: Mapping[str, object]) -> str:
    lines: list[str] = []
    lines.append("# 涨停记忆 × 竞价缺口 打板回测 v1（盘前股性池 + 竞价确认 + T+1）")
    lines.append("")
    lines.append("## Boundary")
    lines.append("")
    for note in result.get("notes") or []:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("## 模型")
    lines.append("")
    lines.append("- 池（D-1 可见）：主板合格 + D-1 未涨停 + 近 20 市场日有过 zt/zbgc 触碰（涨停记忆）")
    lines.append("- 确认（D 日竞价可见）：竞价缺口 = open/close(D-1)-1；买入开盘价")
    lines.append("- v1 卖出：T+1 开盘价一刀切；**v2 卖出（主人规则）：持有期每日，涨停以收盘价卖一半，"
                 "未涨停以收盘价全卖**")
    params = result.get("params") or {}
    lines.append(
        f"- 参数：可交易缺口 [{params.get('gap_min')}%, {params.get('gap_max')}%)、"
        f"追高区 [{params.get('gap_max')}%, {params.get('chase_max')}%)、成本双边 {params.get('cost_pct')}%"
    )
    lines.append("")
    scan = result.get("scan_stats") or {}
    lines.append(
        f"- 扫描股票日 {scan.get('scanned_days')}（{result.get('trade_days')} 个交易日）；"
        f"D+1 无开盘价剔除 {scan.get('dropped_no_exit')}、缺口数据缺失 {scan.get('dropped_gap_data')}"
    )
    lines.append("")

    lines.append("## ① 对照臂总表（v1=T+1 开盘一刀切卖；v2=主人规则：涨停卖一半/不涨停全卖）")
    lines.append("")
    lines.append(
        "| 臂 | 笔数 | 笔/日 | v1胜率 | v1均净 | v1总净 | v2胜率 | v2均净 | v2中位净 | v2总净 | v2均涨停天数 | v2均持有天数 | 封板率 |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in result.get("arms") or []:
        lines.append(
            f"| {_ARM_LABELS.get(str(row.get('arm')), row.get('arm'))} | {row.get('trades')} | "
            f"{row.get('trades_per_day')} | {_rate(row.get('win_rate'))} | {_pct(row.get('mean_t1_net'))} | "
            f"{row.get('sum_t1_net')} | {_rate(row.get('v2_win_rate'))} | {_pct(row.get('v2_mean_net'))} | "
            f"{_pct(row.get('v2_median_net'))} | {row.get('v2_sum_net')} | "
            f"{row.get('v2_mean_seal_days')} | {row.get('v2_mean_hold_days')} | {_rate(row.get('seal_rate'))} |"
        )
    lines.append("")
    combo = next((row for row in result.get("arms") or [] if row.get("arm") == "B_combo"), {})
    lines.append(f"- B 臂 v2 卖出原因分布：{combo.get('v2_exit_reasons')}")
    lines.append(f"- B 臂 v1 口径补充：毛均 {_pct(combo.get('mean_t1_gross'))}、盘中均 {_pct(combo.get('mean_intraday'))}、"
                 f"触板率 {_rate(combo.get('touch_rate'))}、首板≥2板 {_rate(combo.get('peak2_share'))}")
    lines.append("")

    lines.append("## ② B 臂缺口细分")
    lines.append("")
    lines.append("| 缺口桶 | 笔数 | 胜率(净) | 均收益(净) | 中位(净) | 封板率 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for row in result.get("combo_gap_buckets") or []:
        lines.append(
            f"| {row.get('bucket')} | {row.get('trades')} | {_rate(row.get('win_rate'))} | "
            f"{_pct(row.get('mean_t1_net'))} | {_pct(row.get('median_t1_net'))} | {_rate(row.get('seal_rate'))} |"
        )
    lines.append("")

    lines.append("## ③ 涨停记忆票缺口六桶（梯度复核）")
    lines.append("")
    lines.append("| 缺口桶(%) | 笔数 | 胜率(净) | 均收益(净) | 触板率 | 封板率 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for row in result.get("touch_gap_gradient") or []:
        lines.append(
            f"| {row.get('bucket')} | {row.get('trades')} | {_rate(row.get('win_rate'))} | "
            f"{_pct(row.get('mean_t1_net'))} | {_rate(row.get('touch_rate'))} | {_rate(row.get('seal_rate'))} |"
        )
    lines.append("")

    lines.append("## ④ B 臂逐月（一致性纪律，v1/v2 双口径）")
    lines.append("")
    lines.append(
        f"- 净均值为正的月份：v1 **{result.get('combo_profitable_months')}/{result.get('combo_month_count')}**、"
        f"v2 **{result.get('combo_profitable_months_v2')}/{result.get('combo_month_count')}**"
    )
    lines.append("")
    lines.append("| 月份 | 笔数 | v1胜率 | v1均净 | v2胜率 | v2均净 | v2中位净 | 封板率 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for row in result.get("combo_monthly") or []:
        lines.append(
            f"| {row.get('month')} | {row.get('trades')} | {_rate(row.get('win_rate'))} | "
            f"{_pct(row.get('mean_t1_net'))} | {_rate(row.get('v2_win_rate'))} | "
            f"{_pct(row.get('v2_mean_net'))} | {_pct(row.get('v2_median_net'))} | {_rate(row.get('seal_rate'))} |"
        )
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append(f"- study_version: {result.get('study_version')}")
    lines.append(f"- input_fingerprint: {result.get('input_fingerprint')}")
    lines.append(f"- 窗口: {result.get('start')}..{result.get('end')}")
    return "\n".join(lines) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="涨停记忆×竞价缺口 打板回测 v1")
    parser.add_argument("--start", required=True, help="窗口起点（ISO 日期）")
    parser.add_argument("--end", required=True, help="窗口终点（ISO 日期）")
    parser.add_argument("--json-output", required=True, help="JSON 证据输出路径")
    parser.add_argument("--markdown-output", required=True, help="Markdown 报告输出路径")
    arguments = parser.parse_args(argv)

    report = run_backtest(
        start=date.fromisoformat(arguments.start),
        end=date.fromisoformat(arguments.end),
    )
    json_path = Path(arguments.json_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    markdown_path = Path(arguments.markdown_output)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    arms = {row["arm"]: row for row in report.get("arms") or []}
    combo = arms.get("B_combo") or {}
    print(
        f"recent-touch auction backtest: status={report['status']} "
        f"B_trades={combo.get('trades')} "
        f"B_v1_net={combo.get('mean_t1_net')} "
        f"B_v2_net={combo.get('v2_mean_net')} "
        f"B_v2_win={combo.get('v2_win_rate')} "
        f"v2_profitable_months={report.get('combo_profitable_months_v2')}/{report.get('combo_month_count')}"
    )


if __name__ == "__main__":
    main()
