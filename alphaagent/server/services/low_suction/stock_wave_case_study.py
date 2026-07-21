"""Read-only single-stock wave study for Xuguang Electronics."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine

from .leader_waves import build_leader_wave_ledger
from .research_protocol import fingerprint_frame
from .stock_wave_pullbacks import (
    build_declared_continuation_trade,
    build_first_support_approaches,
    build_stock_wave_features,
    build_wave_pullback_trades,
    find_campaign_ignitions,
)


XUGUANG_SYMBOL = "600353.SSE"
XUGUANG_NAME = "旭光电子"
XUGUANG_LOAD_START = date(2025, 4, 1)
XUGUANG_CAMPAIGN_START = date(2025, 5, 16)
XUGUANG_CONFIRMATION_DATE = date(2025, 5, 23)
XUGUANG_OBSERVATION_END = date(2025, 10, 23)
XUGUANG_2026_LOAD_START = date(2026, 3, 1)
XUGUANG_2026_CONTINUATION_START = date(2026, 5, 7)
XUGUANG_2026_CONFIRMATION_DATE = date(2026, 5, 14)
XUGUANG_2026_OBSERVATION_END = date(2026, 7, 17)


@dataclass(frozen=True)
class StockWaveCaseInputs:
    vt_symbol: str
    stock_name: str
    daily_bars: pd.DataFrame
    coverage: dict[str, Any]
    fingerprint: dict[str, Any]


def load_xuguang_wave_case_inputs() -> StockWaveCaseInputs:
    """Load the declared Xuguang case window without changing database state."""

    return load_stock_wave_case_inputs(
        vt_symbol=XUGUANG_SYMBOL,
        expected_name=XUGUANG_NAME,
        load_start=XUGUANG_LOAD_START,
        observation_end=XUGUANG_OBSERVATION_END,
    )


def load_xuguang_2026_continuation_inputs() -> StockWaveCaseInputs:
    """Load the 2026 Xuguang continuation window without changing database state."""

    return load_stock_wave_case_inputs(
        vt_symbol=XUGUANG_SYMBOL,
        expected_name=XUGUANG_NAME,
        load_start=XUGUANG_2026_LOAD_START,
        observation_end=XUGUANG_2026_OBSERVATION_END,
    )


def load_stock_wave_case_inputs(
    *,
    vt_symbol: str,
    expected_name: str,
    load_start: date,
    observation_end: date,
) -> StockWaveCaseInputs:
    """Load one declared stock/window and return immutable coverage evidence."""

    statement = (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stocks.c.name.label("stock_name"),
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.volume,
            schema.stock_daily_bars.c.source,
        )
        .select_from(
            schema.stock_daily_bars.join(
                schema.stocks,
                schema.stock_daily_bars.c.vt_symbol == schema.stocks.c.vt_symbol,
            )
        )
        .where(
            schema.stock_daily_bars.c.vt_symbol == vt_symbol,
            schema.stock_daily_bars.c.trade_date.between(
                load_start,
                observation_end,
            ),
        )
        .order_by(schema.stock_daily_bars.c.trade_date)
    )
    bars = pd.read_sql(statement, get_engine(), parse_dates=["trade_date"])
    if bars.empty:
        raise ValueError("stock daily bars are unavailable for the declared case window")
    names = tuple(sorted(bars["stock_name"].dropna().astype(str).unique()))
    if names != (expected_name,):
        raise ValueError("stock identity does not match the declared case")
    fingerprint = fingerprint_frame(
        bars,
        identity_columns=("vt_symbol", "trade_date"),
    ).as_dict()
    coverage = {
        "rows": int(len(bars)),
        "trade_days": int(bars["trade_date"].nunique()),
        "start": bars["trade_date"].min().date().isoformat(),
        "end": bars["trade_date"].max().date().isoformat(),
        "sources": sorted(bars["source"].dropna().astype(str).unique()),
    }
    return StockWaveCaseInputs(
        vt_symbol=vt_symbol,
        stock_name=names[0],
        daily_bars=bars,
        coverage=coverage,
        fingerprint=fingerprint,
    )


def build_stock_wave_case_report(
    *,
    vt_symbol: str,
    stock_name: str,
    daily_bars: pd.DataFrame,
    campaign_start: date,
    observation_end: date,
    coverage: Mapping[str, Any] | None = None,
    fingerprint: Mapping[str, Any] | None = None,
    require_ignition_anchor: bool = True,
) -> dict[str, Any]:
    """Build one stock's structure ledger and point-in-time execution evidence."""

    features = build_stock_wave_features(daily_bars)
    ignitions = find_campaign_ignitions(features)
    anchor = pd.Timestamp(campaign_start)
    boundary = pd.Timestamp(observation_end)
    if require_ignition_anchor and not ignitions["trade_date"].eq(anchor).any():
        raise ValueError("campaign start must be a point-in-time ignition")
    waves = build_leader_wave_ledger(
        features,
        anchor_date=campaign_start,
        observation_end=observation_end,
    )
    approaches = build_first_support_approaches(features, waves)
    trades = build_wave_pullback_trades(approaches, features, waves)
    wave_path = _build_wave_path(trades)
    campaign_ignitions = ignitions.loc[
        ignitions["trade_date"].between(anchor, boundary)
    ].copy()
    first_supports = _first_campaign_supports(approaches)
    return {
        "study_version": "stock-wave-pullback-case-v1",
        "research_status": "exploratory_single_stock_case",
        "formal_strategy": False,
        "case": {
            "vt_symbol": vt_symbol,
            "stock_name": stock_name,
            "campaign_start": campaign_start.isoformat(),
            "observation_end": observation_end.isoformat(),
        },
        "coverage": dict(coverage or {}),
        "fingerprint": dict(fingerprint or {}),
        "tables_read": {
            "stocks": 1,
            "stock_daily_bars": int(len(daily_bars)),
            "stock_minute_bars": 0,
            "concept_memberships": 0,
            "market_timing_labels": 0,
            "low_suction_outcomes": 0,
        },
        "population_metrics": {
            "win_rate_pct": None,
            "compounded_return_pct": None,
            "profit_factor": None,
            "maximum_drawdown_pct": None,
        },
        "evidence_boundaries": {
            "signal_features": "point_in_time",
            "wave_resolution": "retrospective_label",
            "entry_fill": "daily_close_proxy",
            "minute_bars_read": 0,
            "overlapping_entries": "standalone_hypothesis_paths_not_portfolio",
            "wave_path": "one_earliest_entry_per_wave_non_overlapping",
        },
        "trade_rules": {
            "approach": "daily_low_at_or_below_ma_line_plus_2pct",
            "entry": "approach_day_close",
            "primary_exit": "first_later_high_above_pre_pullback_peak_then_close",
            "defensive_exit": "second_consecutive_close_below_ma20",
            "event_precedence": "earliest_exit_event",
            "round_trip_cost_pct": 0.2,
        },
        "emotion_state_machine": _emotion_state_machine(),
        "campaign_summary": _campaign_summary(features, waves, anchor, boundary),
        "case_trade_summary": _trade_summary(trades),
        "case_wave_path_summary": _wave_path_summary(wave_path),
        "support_summary": _group_trade_summary(trades, "support_line"),
        "volume_summary": _group_trade_summary(trades, "volume_class_prior5"),
        "ignitions": _records(campaign_ignitions, _ignition_columns()),
        "waves": _records(waves),
        "first_campaign_supports": _records(first_supports),
        "approaches": _records(approaches),
        "trades": _records(trades),
        "wave_path": _records(wave_path),
        "limitations": [
            "Only one already-inspected stock is studied; this cannot estimate population win rate.",
            "Wave peaks, troughs and final resolution are retrospective labels and never select an entry.",
            "The entry is a daily-close proxy because continuous intraday coverage is unavailable.",
            "Standalone support entries can overlap and therefore cannot be compounded as one account.",
            "Concept leadership and GOLD/SILVER timing are intentionally excluded from this case pass.",
        ],
        "next_validation": (
            "Apply the unchanged signal state machine to dynamically calculated historical leaders "
            "and compare successful versus failed pullback waves in chronological blocks."
        ),
        "reproduce": (
            "docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace "
            "-w /workspace alphaagent-api python -m "
            "alphaagent.server.services.low_suction.cli "
            "v2-stock-wave-case-study --format markdown"
        ),
    }


def build_declared_continuation_case_report(
    *,
    vt_symbol: str,
    stock_name: str,
    daily_bars: pd.DataFrame,
    campaign_start: date,
    observation_end: date,
    coverage: Mapping[str, Any] | None = None,
    fingerprint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a wave report around a declared continuation, not a strict ignition."""

    features = build_stock_wave_features(daily_bars)
    diagnostic = build_declared_continuation_trade(
        features,
        anchor_date=campaign_start,
    )
    report = build_stock_wave_case_report(
        vt_symbol=vt_symbol,
        stock_name=stock_name,
        daily_bars=daily_bars,
        campaign_start=campaign_start,
        observation_end=observation_end,
        coverage=coverage,
        fingerprint=fingerprint,
        require_ignition_anchor=False,
    )
    report["research_status"] = "exploratory_declared_continuation_case"
    report["case"]["anchor_contract"] = "user_declared_continuation_candidate"
    report["declared_continuation"] = _json_safe(diagnostic)
    report["wave_impulse_diagnostics"] = _wave_impulse_diagnostics(
        features,
        report["waves"],
    )
    report["evidence_boundaries"]["declared_anchor"] = (
        "user_supplied_date_evaluated_without_future_selection"
    )
    report["limitations"].insert(
        1,
        "The declared continuation anchor is user-supplied and is not relabelled as a strict ignition.",
    )
    return report


def run_xuguang_wave_case_study() -> dict[str, Any]:
    """Run the real Xuguang case and verify both observed ignition landmarks."""

    inputs = load_xuguang_wave_case_inputs()
    report = build_stock_wave_case_report(
        vt_symbol=inputs.vt_symbol,
        stock_name=inputs.stock_name,
        daily_bars=inputs.daily_bars,
        campaign_start=XUGUANG_CAMPAIGN_START,
        observation_end=XUGUANG_OBSERVATION_END,
        coverage=inputs.coverage,
        fingerprint=inputs.fingerprint,
    )
    ignition_dates = {row["trade_date"] for row in report["ignitions"]}
    required = {
        XUGUANG_CAMPAIGN_START.isoformat(),
        XUGUANG_CONFIRMATION_DATE.isoformat(),
    }
    if not required.issubset(ignition_dates):
        raise ValueError("Xuguang ignition landmarks changed under the frozen definition")
    report["case"]["confirmation_ignition_date"] = (
        XUGUANG_CONFIRMATION_DATE.isoformat()
    )
    return report


def run_xuguang_2026_continuation_study() -> dict[str, Any]:
    """Run the declared May 7 continuation and every later Xuguang wave."""

    inputs = load_xuguang_2026_continuation_inputs()
    report = build_declared_continuation_case_report(
        vt_symbol=inputs.vt_symbol,
        stock_name=inputs.stock_name,
        daily_bars=inputs.daily_bars,
        campaign_start=XUGUANG_2026_CONTINUATION_START,
        observation_end=XUGUANG_2026_OBSERVATION_END,
        coverage=inputs.coverage,
        fingerprint=inputs.fingerprint,
    )
    diagnostic = _mapping(report["declared_continuation"])
    if diagnostic.get("strict_ignition") is not False:
        raise ValueError("May 7 must remain distinct from the strict ignition contract")
    ignition_dates = {row["trade_date"] for row in report["ignitions"]}
    if XUGUANG_2026_CONFIRMATION_DATE.isoformat() not in ignition_dates:
        raise ValueError("the May 14 strict confirmation is missing")
    report["case"]["confirmation_ignition_date"] = (
        XUGUANG_2026_CONFIRMATION_DATE.isoformat()
    )
    report["next_validation"] = (
        "Compare the unchanged continuation state across Xuguang 2025/2026 and then "
        "apply it to predeclared dynamically calculated leaders."
    )
    report["reproduce"] = (
        "docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace "
        "-w /workspace alphaagent-api python -m "
        "alphaagent.server.services.low_suction.cli v2-stock-wave-case-study "
        "--campaign xuguang-2026-continuation --format markdown"
    )
    return report


def render_stock_wave_case_json(report: Mapping[str, Any]) -> str:
    """Render deterministic machine-readable case evidence."""

    return json.dumps(
        _json_safe(report),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_stock_wave_case_markdown(report: Mapping[str, Any]) -> str:
    """Render the full single-stock wave and execution ledger."""

    case = _mapping(report.get("case"))
    campaign = _mapping(report.get("campaign_summary"))
    trades = _mapping(report.get("case_trade_summary"))
    wave_path = _mapping(report.get("case_wave_path_summary"))
    declared = _mapping(report.get("declared_continuation"))
    anchor_label = "声明续浪点" if declared else "起升锚点"
    confirmation_label = "后续严格点火" if declared else "二次点火"
    lines = [
        "# AlphaAgent 旭光电子主升波浪与均线低吸个案",
        "",
        "结论边界：这是单只已观察龙头的路径研究，不是全市场胜率，也不是已冻结策略。",
        "买点只读当日及以前；峰谷和是否再创新高属于事后波浪标签，两者严格分开。",
        "",
        "## Campaign",
        "",
        f"- 股票：{case.get('stock_name')} `{case.get('vt_symbol')}`。",
        f"- {anchor_label}：`{case.get('campaign_start')}`；{confirmation_label}："
        f"`{case.get('confirmation_ignition_date') or '-'}`。",
        f"- 观察截止：`{case.get('observation_end')}`。",
        f"- 波浪：`{campaign.get('wave_count', 0)}` 段；确认更高高点 "
        f"`{campaign.get('confirmed_higher_highs', 0)}` 次。",
        f"- 全段最高：`{_fmt(campaign.get('record_high_price'))}`，日期 "
        f"`{campaign.get('record_high_date') or '-'}`。",
        f"- 最终状态：`{campaign.get('final_resolution_status') or '-'}`。",
        f"- 每浪只做第一次机会的个案复利："
        f"`{_pct(wave_path.get('compounded_return_pct'))}`；这不是全市场复利。",
        "",
        "全市场胜率、现金复利、利润因子、最大回撤：`null`。当前仅有同一只股票中"
        "彼此重叠的独立支撑路径，不能当作独立交易样本复利。",
        "",
        *_declared_continuation_lines(declared),
        "## 资金情绪波浪状态机",
        "",
        "`点火 -> 涨潮创高 -> 退潮测试支撑 -> 回流越过前峰并结算`；若连续两日收盘"
        "跌破 MA20，则只退出当前交易浪。后来重新创记录高点时开启新浪，不永久判定"
        "龙头死亡。`retrospective_terminal` 只能事后标注，实时信号不能读取。",
        "",
        "## Point-In-Time Ignitions",
        "",
        "| Date | Return | Prior-high break | Volume ratio | MA5 | MA10 | MA20 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(_ignition_rows(report.get("ignitions")))
    lines.extend(
        [
            "",
            "## Retrospective Waves",
            "",
            "| Wave | Peak | Peak price | Trough | Pullback | Deepest support | Higher high | Recovery | Volume ratio | Status |",
            "| ---: | --- | ---: | --- | ---: | --- | --- | ---: | ---: | --- |",
        ]
    )
    lines.extend(_wave_rows(report.get("waves")))
    lines.extend(_wave_impulse_lines(report.get("wave_impulse_diagnostics")))
    lines.extend(
        [
            "",
            "## 首次接近 MA5/MA10/MA20",
            "",
            "这里的“接近”允许最低价停在均线上方 2% 内；日期一旦出现就不被后来最低点替换。",
            "",
            "| Line | First date | Wave | Support | Low distance | Close reclaim | Entry close | Prior-5 volume | Impulse volume |",
            "| --- | --- | ---: | ---: | ---: | --- | ---: | --- | --- |",
        ]
    )
    lines.extend(_approach_rows(report.get("first_campaign_supports")))
    lines.extend(
        [
            "",
            "## 每浪第一次机会的非重叠路径",
            "",
            "每一浪只保留最早出现的已选支撑；上一笔退出后下一浪才可能入场，"
            "因此这张表可以顺序复合，但仍然只是旭光电子个案。",
            "",
            "| Wave | Buy | Line | Entry | Exit | Reason | Net | MAE | Equity |",
            "| ---: | --- | --- | ---: | --- | --- | ---: | ---: | ---: |",
        ]
    )
    lines.extend(_wave_path_rows(report.get("wave_path")))
    lines.extend(
        [
            "",
            f"个案路径：`{wave_path.get('trades', 0)}` 笔，成本后为正 "
            f"`{wave_path.get('positive_trades', 0)}` 笔，复利 "
            f"`{_pct(wave_path.get('compounded_return_pct'))}`，"
            f"仅按平仓权益计算的最大回撤 "
            f"`{_pct(wave_path.get('closed_equity_max_drawdown_pct'))}`。",
            "",
            "## All Wave Support Approaches",
            "",
            "| Wave | Line | Date | Peak drawdown | Low distance | Reclaim | Volume prior-5 | Volume impulse | Selected |",
            "| ---: | --- | --- | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    lines.extend(_all_approach_rows(report.get("approaches")))
    lines.extend(
        [
            "",
            "## 尾盘代理买入与因果退出",
            "",
            "| Wave | Buy | Line | Entry | Exit | Reason | Net | MAE | MFE | Later new high | Early defensive exit |",
            "| ---: | --- | --- | ---: | --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    lines.extend(_trade_rows(report.get("trades")))
    lines.extend(
        [
            "",
            "## Case Diagnostics",
            "",
            f"- 独立尾盘路径：`{trades.get('entries', 0)}`；已退出 "
            f"`{trades.get('closed_entries', 0)}`；成本后为正 "
            f"`{trades.get('positive_closed_entries', 0)}`。这个比例不是全市场胜率。",
            f"- 先结构退出、后来仍创新高："
            f"`{trades.get('defensive_exit_preceded_later_higher_high', 0)}` 条。",
            f"- 成本后收益中位数：`{_pct(trades.get('median_net_return_pct'))}`；"
            f"MAE 中位数：`{_pct(trades.get('median_mae_pct'))}`。",
            "",
            "### By Support",
            "",
            "| Support | Entries | Positive | Eventual higher high | Early defensive exit | Median net | Median MAE |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(_summary_rows(report.get("support_summary"), "group"))
    lines.extend(
        [
            "",
            "### By Volume",
            "",
            "| Volume | Entries | Positive | Eventual higher high | Early defensive exit | Median net | Median MAE |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(_summary_rows(report.get("volume_summary"), "group"))
    lines.extend(_case_finding_lines(report))
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- 信号特征：`point_in_time`。",
            "- 事后波浪标签：`retrospective_label`，只用于回答后来是否创新高。",
            "- 买价：日线收盘代理；没有连续分钟线，不声称盘中可精确成交。",
            "- 本轮没有读取概念成员、金银手指或旧低吸成败数据。",
            "",
            "## Next Validation",
            "",
            str(report.get("next_validation") or "-"),
            "",
            "## Reproduce",
            "",
            "```bash",
            str(report.get("reproduce") or "-"),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _declared_continuation_lines(diagnostic: Mapping[str, Any]) -> list[str]:
    if not diagnostic:
        return []
    return [
        "## 声明续浪点诊断",
        "",
        f"- 严格点火：`{str(bool(diagnostic.get('strict_ignition'))).lower()}`；"
        "该日期由用户声明，程序没有用后续涨幅反选。",
        f"- 前峰：`{diagnostic.get('reference_peak_date')}` / "
        f"`{_fmt(diagnostic.get('reference_peak_price'))}`；峰后最低 "
        f"`{diagnostic.get('pre_anchor_trough_date')}` / "
        f"`{_fmt(diagnostic.get('pre_anchor_trough_price'))}`，回撤 "
        f"`{_pct(diagnostic.get('pre_anchor_pullback_pct'))}`。",
        f"- 声明日涨幅 `{_pct(diagnostic.get('anchor_daily_return_pct'))}`，"
        f"距前峰 `{_pct(diagnostic.get('anchor_prior_high_break_pct'))}`，"
        f"量比 `{_fmt(diagnostic.get('anchor_volume_ratio_prior5'))}x` "
        f"(`{diagnostic.get('anchor_volume_class_prior5')}`)。",
        f"- 最低价距 MA5/MA10/MA20："
        f"`{_pct(diagnostic.get('anchor_low_to_ma5_pct'))}` / "
        f"`{_pct(diagnostic.get('anchor_low_to_ma10_pct'))}` / "
        f"`{_pct(diagnostic.get('anchor_low_to_ma20_pct'))}`；"
        "收盘位于三线之上。",
        f"- 尾盘代理买入 `{diagnostic.get('entry_date')}` / "
        f"`{_fmt(diagnostic.get('entry_price'))}`，"
        f"退出 `{diagnostic.get('exit_date') or '-'}` / "
        f"`{_fmt(diagnostic.get('exit_price'))}`，原因 "
        f"`{diagnostic.get('executable_exit_reason')}`，成本后 "
        f"`{_pct(diagnostic.get('net_return_pct'))}`，MAE "
        f"`{_pct(diagnostic.get('maximum_adverse_excursion_pct'))}`。",
        "",
    ]


def _campaign_summary(
    features: pd.DataFrame,
    waves: pd.DataFrame,
    anchor: pd.Timestamp,
    boundary: pd.Timestamp,
) -> dict[str, Any]:
    campaign = features.loc[features["trade_date"].between(anchor, boundary)]
    record = campaign.loc[campaign["high_price"].idxmax()]
    start = campaign.loc[campaign["trade_date"].eq(anchor)].iloc[0]
    final = waves.iloc[-1]
    return {
        "wave_count": int(len(waves)),
        "confirmed_higher_highs": int(
            waves["resolution_status"].eq("continued_to_higher_high").sum()
        ),
        "record_high_date": pd.Timestamp(record["trade_date"]).date().isoformat(),
        "record_high_price": float(record["high_price"]),
        "record_high_gain_from_anchor_close_pct": (
            float(record["high_price"]) / float(start["close_price"]) - 1.0
        )
        * 100.0,
        "final_resolution_status": str(final["resolution_status"]),
        "structural_break_date": _date_text(final.get("structural_break_date")),
        "observation_close": float(campaign.iloc[-1]["close_price"]),
    }


def _wave_impulse_diagnostics(
    features: pd.DataFrame,
    raw_waves: Any,
) -> list[dict[str, Any]]:
    positions = {
        pd.Timestamp(trade_date): position
        for position, trade_date in enumerate(features["trade_date"])
    }
    rows: list[dict[str, Any]] = []
    for item in _sequence(raw_waves):
        wave = _mapping(item)
        start = pd.Timestamp(wave["wave_start_date"])
        peak = pd.Timestamp(wave["peak_date"])
        impulse = features.loc[features["trade_date"].between(start, peak)]
        start_close = float(impulse.iloc[0]["close_price"])
        peak_price = float(wave["peak_price"])
        rows.append(
            {
                "wave_number": int(wave["wave_number"]),
                "wave_start_date": start.date().isoformat(),
                "peak_date": peak.date().isoformat(),
                "sessions_to_peak": positions[peak] - positions[start],
                "start_close": start_close,
                "peak_price": peak_price,
                "impulse_gain_pct": (peak_price / start_close - 1.0) * 100.0,
                "strong_days_ge_9_5pct": int(
                    impulse["daily_return_pct"].ge(9.5).sum()
                ),
                "max_volume_ratio_prior5": float(
                    impulse["volume_ratio_prior5"].max()
                ),
                "median_volume_ratio_prior5": float(
                    impulse["volume_ratio_prior5"].median()
                ),
                "resolution_status": str(wave["resolution_status"]),
            }
        )
    return rows


def _trade_summary(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {
            "entries": 0,
            "closed_entries": 0,
            "positive_closed_entries": 0,
            "case_positive_share_pct": None,
            "median_net_return_pct": None,
            "median_mae_pct": None,
            "defensive_exit_preceded_later_higher_high": 0,
        }
    closed = trades.loc[trades["exit_date"].notna()]
    positive = int(closed["net_return_pct"].gt(0).sum())
    return {
        "entries": int(len(trades)),
        "closed_entries": int(len(closed)),
        "positive_closed_entries": positive,
        "case_positive_share_pct": (
            positive / len(closed) * 100.0 if not closed.empty else None
        ),
        "median_net_return_pct": _median(closed["net_return_pct"]),
        "median_mae_pct": _median(closed["maximum_adverse_excursion_pct"]),
        "defensive_exit_preceded_later_higher_high": int(
            trades["defensive_exit_preceded_later_higher_high"].astype(bool).sum()
        ),
    }


def _group_trade_summary(trades: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    if trades.empty:
        return []
    records = []
    for group, frame in trades.groupby(column, dropna=False, sort=True):
        closed = frame.loc[frame["exit_date"].notna()]
        records.append(
            {
                "group": str(group),
                "entries": int(len(frame)),
                "positive_closed_entries": int(closed["net_return_pct"].gt(0).sum()),
                "eventual_higher_high_entries": int(
                    frame["eventually_made_higher_high"].astype(bool).sum()
                ),
                "defensive_exit_preceded_later_higher_high": int(
                    frame["defensive_exit_preceded_later_higher_high"].astype(bool).sum()
                ),
                "median_net_return_pct": _median(closed["net_return_pct"]),
                "median_mae_pct": _median(closed["maximum_adverse_excursion_pct"]),
            }
        )
    return records


def _build_wave_path(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    path = (
        trades.sort_values(
            ["wave_number", "entry_date", "support_depth"],
            kind="stable",
        )
        .drop_duplicates("wave_number", keep="first")
        .reset_index(drop=True)
    )
    previous_exit: pd.Timestamp | None = None
    equities: list[float | None] = []
    equity = 1.0
    for row in path.to_dict("records"):
        entry_date = pd.Timestamp(row["entry_date"])
        if previous_exit is not None and entry_date < previous_exit:
            raise ValueError("one-position wave path contains overlapping trades")
        exit_date = row.get("exit_date")
        net_return = _number(row.get("net_return_pct"))
        if exit_date is None or pd.isna(exit_date) or net_return is None:
            equities.append(None)
            previous_exit = None
            continue
        if net_return <= -100:
            raise ValueError("wave path return cannot lose more than all capital")
        equity *= 1.0 + net_return / 100.0
        equities.append(equity)
        previous_exit = pd.Timestamp(exit_date)
    path["case_equity_after_exit"] = equities
    return path


def _wave_path_summary(path: pd.DataFrame) -> dict[str, Any]:
    if path.empty:
        return {
            "trades": 0,
            "closed_trades": 0,
            "positive_trades": 0,
            "positive_trade_share_pct": None,
            "compounded_return_pct": None,
            "closed_equity_max_drawdown_pct": None,
            "median_mae_pct": None,
        }
    closed = path.loc[path["exit_date"].notna()].copy()
    equities = pd.to_numeric(
        closed["case_equity_after_exit"], errors="coerce"
    ).dropna()
    curve = pd.Series([1.0, *equities.tolist()], dtype=float)
    drawdowns = (curve / curve.cummax() - 1.0) * 100.0
    return {
        "trades": int(len(path)),
        "closed_trades": int(len(closed)),
        "positive_trades": int(closed["net_return_pct"].gt(0).sum()),
        "positive_trade_share_pct": (
            float(closed["net_return_pct"].gt(0).mean() * 100.0)
            if not closed.empty
            else None
        ),
        "compounded_return_pct": (
            (float(equities.iloc[-1]) - 1.0) * 100.0 if not equities.empty else None
        ),
        "closed_equity_max_drawdown_pct": (
            float(drawdowns.min()) if not drawdowns.empty else None
        ),
        "median_mae_pct": _median(closed["maximum_adverse_excursion_pct"]),
    }


def _emotion_state_machine() -> list[dict[str, str]]:
    return [
        {
            "state": "ignition",
            "known_at": "same_day_close",
            "transition": "strong prior-20 high breakout with volume and aligned averages",
        },
        {
            "state": "rising_tide",
            "known_at": "each_completed_day",
            "transition": "record high keeps advancing before a five-percent ebb",
        },
        {
            "state": "ebb_support_test",
            "known_at": "approach_day_close",
            "transition": "first low within two percent above MA5, MA10, or MA20",
        },
        {
            "state": "return_flow_higher_high",
            "known_at": "higher_high_day_close",
            "transition": "later high exceeds the pre-pullback peak; close exits current trade",
        },
        {
            "state": "structural_exit",
            "known_at": "second_below_ma20_close",
            "transition": "exit current wave, but permit a new wave after a later record high",
        },
        {
            "state": "retrospective_terminal",
            "known_at": "only_after_observation_horizon",
            "transition": "no later record high; never available to entry construction",
        },
    ]


def _first_campaign_supports(approaches: pd.DataFrame) -> pd.DataFrame:
    if approaches.empty:
        return approaches.copy()
    return (
        approaches.sort_values(["approach_date", "support_depth"], kind="stable")
        .drop_duplicates("support_line", keep="first")
        .sort_values("support_depth", kind="stable")
        .reset_index(drop=True)
    )


def _ignition_columns() -> list[str]:
    return [
        "ignition_number",
        "trade_date",
        "daily_return_pct",
        "close_price",
        "prior_high20",
        "volume_ratio_prior5",
        "ma5",
        "ma10",
        "ma20",
        "ignition_definition",
    ]


def _records(
    frame: pd.DataFrame,
    columns: list[str] | None = None,
) -> list[dict[str, Any]]:
    selected = frame.loc[:, columns] if columns is not None else frame
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in selected.to_dict("records")
    ]


def _ignition_rows(raw: Any) -> list[str]:
    rows = []
    for item in _sequence(raw):
        row = _mapping(item)
        break_pct = (
            (float(row.get("close_price")) / float(row.get("prior_high20")) - 1.0)
            * 100.0
            if row.get("prior_high20")
            else None
        )
        rows.append(
            f"| {row.get('trade_date')} | {_pct(row.get('daily_return_pct'))} | "
            f"{_pct(break_pct)} | {_fmt(row.get('volume_ratio_prior5'))}x | "
            f"{_fmt(row.get('ma5'))} | {_fmt(row.get('ma10'))} | {_fmt(row.get('ma20'))} |"
        )
    return rows or ["| - | - | - | - | - | - | - |"]


def _wave_rows(raw: Any) -> list[str]:
    rows = []
    for item in _sequence(raw):
        row = _mapping(item)
        rows.append(
            f"| {row.get('wave_number')} | {row.get('peak_date')} | "
            f"{_fmt(row.get('peak_price'))} | {row.get('trough_date') or '-'} | "
            f"{_pct(row.get('pullback_pct'))} | {row.get('deepest_tested_support') or '-'} | "
            f"{row.get('higher_high_date') or '-'} | {row.get('recovery_sessions') or '-'} | "
            f"{_fmt(row.get('trough_volume_ratio_5d'))}x | "
            f"`{row.get('resolution_status')}` |"
        )
    return rows or ["| - | - | - | - | - | - | - | - | - | - |"]


def _wave_impulse_lines(raw: Any) -> list[str]:
    diagnostics = _sequence(raw)
    if not diagnostics:
        return []
    rows = [
        "",
        "## 起浪加速与高潮对比",
        "",
        "这些字段只在整浪结束后比较成功浪与终止浪，不参与声明日或回踩日选点。",
        "",
        "| Wave | Start | Peak | Sessions | Impulse gain | >=9.5% days | Max volume | Median volume | Status |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in diagnostics:
        row = _mapping(item)
        rows.append(
            f"| {row.get('wave_number')} | {row.get('wave_start_date')} | "
            f"{row.get('peak_date')} | {row.get('sessions_to_peak')} | "
            f"{_pct(row.get('impulse_gain_pct'))} | "
            f"{row.get('strong_days_ge_9_5pct')} | "
            f"{_fmt(row.get('max_volume_ratio_prior5'))}x | "
            f"{_fmt(row.get('median_volume_ratio_prior5'))}x | "
            f"`{row.get('resolution_status')}` |"
        )
    return rows


def _approach_rows(raw: Any) -> list[str]:
    rows = []
    for item in _sequence(raw):
        row = _mapping(item)
        rows.append(
            f"| `{str(row.get('support_line')).upper()}` | {row.get('approach_date')} | "
            f"{row.get('wave_number')} | {_fmt(row.get('support_price'))} | "
            f"{_pct(row.get('line_distance_low_pct'))} | "
            f"{_yes(row.get('close_reclaimed_support'))} | {_fmt(row.get('entry_price'))} | "
            f"`{row.get('volume_class_prior5')}` {_fmt(row.get('volume_ratio_prior5'))}x | "
            f"`{row.get('volume_class_impulse')}` {_fmt(row.get('volume_ratio_impulse'))}x |"
        )
    return rows or ["| - | - | - | - | - | - | - | - | - |"]


def _all_approach_rows(raw: Any) -> list[str]:
    rows = []
    for item in _sequence(raw):
        row = _mapping(item)
        rows.append(
            f"| {row.get('wave_number')} | `{str(row.get('support_line')).upper()}` | "
            f"{row.get('approach_date')} | {_pct(row.get('peak_to_entry_drawdown_pct'))} | "
            f"{_pct(row.get('line_distance_low_pct'))} | "
            f"{_yes(row.get('close_reclaimed_support'))} | "
            f"`{row.get('volume_class_prior5')}` {_fmt(row.get('volume_ratio_prior5'))}x | "
            f"`{row.get('volume_class_impulse')}` {_fmt(row.get('volume_ratio_impulse'))}x | "
            f"{_yes(row.get('execution_selected'))} |"
        )
    return rows or ["| - | - | - | - | - | - | - | - | - |"]


def _trade_rows(raw: Any) -> list[str]:
    rows = []
    for item in _sequence(raw):
        row = _mapping(item)
        rows.append(
            f"| {row.get('wave_number')} | {row.get('entry_date')} | "
            f"`{str(row.get('support_line')).upper()}` | {_fmt(row.get('entry_price'))} | "
            f"{row.get('exit_date') or '-'} | `{row.get('executable_exit_reason')}` | "
            f"{_pct(row.get('net_return_pct'))} | "
            f"{_pct(row.get('maximum_adverse_excursion_pct'))} | "
            f"{_pct(row.get('maximum_favorable_excursion_pct'))} | "
            f"{_yes(row.get('eventually_made_higher_high'))} | "
            f"{_yes(row.get('defensive_exit_preceded_later_higher_high'))} |"
        )
    return rows or ["| - | - | - | - | - | - | - | - | - | - | - |"]


def _wave_path_rows(raw: Any) -> list[str]:
    rows = []
    for item in _sequence(raw):
        row = _mapping(item)
        rows.append(
            f"| {row.get('wave_number')} | {row.get('entry_date')} | "
            f"`{str(row.get('support_line')).upper()}` | {_fmt(row.get('entry_price'))} | "
            f"{row.get('exit_date') or '-'} | `{row.get('executable_exit_reason')}` | "
            f"{_pct(row.get('net_return_pct'))} | "
            f"{_pct(row.get('maximum_adverse_excursion_pct'))} | "
            f"{_pct(_equity_return_pct(row.get('case_equity_after_exit')))} |"
        )
    return rows or ["| - | - | - | - | - | - | - | - | - |"]


def _case_finding_lines(report: Mapping[str, Any]) -> list[str]:
    support = {
        str(_mapping(item).get("group")): _mapping(item)
        for item in _sequence(report.get("support_summary"))
    }
    volume = {
        str(_mapping(item).get("group")): _mapping(item)
        for item in _sequence(report.get("volume_summary"))
    }
    ma20 = support.get("ma20", {})
    ma5 = support.get("ma5", {})
    contraction = volume.get("contraction", {})
    normal = volume.get("normal", {})
    early = _mapping(report.get("case_trade_summary")).get(
        "defensive_exit_preceded_later_higher_high",
        0,
    )
    return [
        "",
        "## What This Case Supports",
        "",
        f"- MA20 的独立路径中位收益 `{_pct(ma20.get('median_net_return_pct'))}`，"
        f"MAE 中位数 `{_pct(ma20.get('median_mae_pct'))}`；MA5 分别为 "
        f"`{_pct(ma5.get('median_net_return_pct'))}` 和 "
        f"`{_pct(ma5.get('median_mae_pct'))}`。本个案中 MA5 明显更早、风险更大。",
        f"- 缩量路径中位收益 `{_pct(contraction.get('median_net_return_pct'))}`，"
        f"正常量路径为 `{_pct(normal.get('median_net_return_pct'))}`；"
        "终止浪同样会缩量，所以缩量只能描述抛压，不能单独确认主升仍活着。",
        f"- 连续两日收盘跌破 MA20 后退出，有 `{early}` 条后来仍创新高。"
        "这说明该条件适合结束当前交易浪，但不能永久判定龙头死亡；"
        "若后来重新创记录高点，应建立新浪并等待下一次回踩。",
        "- 单日可以同时穿过 MA5、MA10、MA20，不能机械地把第几根阴线等同于"
        "第几条均线；程序按当天实际到达的最深支撑归类。",
    ]


def _summary_rows(raw: Any, label: str) -> list[str]:
    rows = []
    for item in _sequence(raw):
        row = _mapping(item)
        rows.append(
            f"| `{row.get(label)}` | {row.get('entries')} | "
            f"{row.get('positive_closed_entries')} | "
            f"{row.get('eventual_higher_high_entries')} | "
            f"{row.get('defensive_exit_preceded_later_higher_high')} | "
            f"{_pct(row.get('median_net_return_pct'))} | "
            f"{_pct(row.get('median_mae_pct'))} |"
        )
    return rows or ["| - | 0 | 0 | 0 | 0 | - | - |"]


def _median(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.median()) if not numeric.empty else None


def _date_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()


def _pct(value: object) -> str:
    numeric = _number(value)
    return f"{numeric:.4f}%" if numeric is not None else "-"


def _fmt(value: object) -> str:
    numeric = _number(value)
    return f"{numeric:.4f}" if numeric is not None else "-"


def _number(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _equity_return_pct(value: object) -> float | None:
    numeric = _number(value)
    return (numeric - 1.0) * 100.0 if numeric is not None else None


def _yes(value: object) -> str:
    return "是" if bool(value) else "否"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _json_safe(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, date)):
        return pd.Timestamp(value).date().isoformat()
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value) if np.isfinite(value) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value
