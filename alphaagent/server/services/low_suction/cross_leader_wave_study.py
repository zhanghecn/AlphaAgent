"""Cross-stock validation of the frozen Xuguang leader-wave observations."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .leader_waves import build_leader_wave_ledger
from .stock_wave_pullbacks import (
    build_first_support_approaches,
    build_stock_wave_features,
    build_wave_pullback_trades,
)
from .true_leader_study import EVIDENCE_LEVEL, REFERENCE_CAMPAIGNS


STUDY_VERSION = "cross-leader-wave-pattern-v1"
DEFAULT_HORIZON_SESSIONS = 40
XUGUANG_CLIMAX_GAIN_PCT = 50.0
XUGUANG_CLIMAX_STRONG_DAYS = 3
XUGUANG_CLIMAX_VOLUME_RATIO = 3.0
RESOLVED_WAVE_STATUSES = frozenset(
    ("continued_to_higher_high", "terminal_failure_observed")
)
EPISODE_COLUMNS = (
    "episode_id",
    "cohort",
    "vt_symbol",
    "stock_name",
    "anchor_date",
    "observation_end",
    "causal_rank",
    "sector_id",
    "concept_name",
    "time_block",
)


def build_causal_wave_episodes(
    causal_ranks: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
    horizon_sessions: int = DEFAULT_HORIZON_SESSIONS,
) -> pd.DataFrame:
    """Select outcome-neutral, non-overlapping Top3 stock observation windows."""

    if horizon_sessions <= 0:
        raise ValueError("horizon sessions must be positive")
    required = (
        "cycle_id",
        "trade_date",
        "sector_id",
        "concept_name",
        "vt_symbol",
        "stock_name",
        "causal_rank",
        "causal_top3",
        "main_rise_alive",
        "feature_cutoff_date",
    )
    _require_columns(causal_ranks, required, "causal leader rank")
    frame = causal_ranks.loc[:, list(required)].copy()
    for column in ("trade_date", "feature_cutoff_date"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.normalize()
    if not frame["feature_cutoff_date"].eq(frame["trade_date"]).all():
        raise ValueError("feature cutoff must equal the causal rank trade date")

    calendar = pd.DatetimeIndex(pd.to_datetime(tuple(trading_dates))).normalize()
    calendar = calendar.drop_duplicates().sort_values()
    if len(calendar) <= horizon_sessions:
        return _empty_episode_frame()
    end_by_anchor = {
        anchor: calendar[position + horizon_sessions]
        for position, anchor in enumerate(calendar[:-horizon_sessions])
    }
    frame["anchor_date"] = frame["trade_date"]
    frame["observation_end"] = frame["anchor_date"].map(end_by_anchor)
    frame = frame.loc[
        frame["causal_top3"].astype(bool)
        & pd.to_numeric(frame["causal_rank"], errors="coerce").between(1, 3)
        & frame["main_rise_alive"].astype(bool)
        & frame["observation_end"].notna()
        & frame["vt_symbol"].map(_is_main_board_symbol)
    ].copy()
    if frame.empty:
        return _empty_episode_frame()

    identity = ["vt_symbol", "anchor_date"]
    concepts = (
        frame.groupby(identity, sort=False)
        .agg(
            concept_count_at_anchor=("sector_id", "nunique"),
            concept_ids_at_anchor=("sector_id", _joined_unique),
            concept_names_at_anchor=("concept_name", _joined_unique),
        )
        .reset_index()
    )
    selected = (
        frame.sort_values(
            ["vt_symbol", "anchor_date", "causal_rank", "sector_id", "cycle_id"],
            kind="stable",
        )
        .drop_duplicates(identity, keep="first")
        .merge(concepts, on=identity, how="left", validate="one_to_one")
    )
    retained = _retain_non_overlapping_windows(selected)
    if retained.empty:
        return _empty_episode_frame()
    retained["episode_id"] = retained.apply(
        lambda row: (
            f"dynamic:{row['vt_symbol']}:"
            f"{pd.Timestamp(row['anchor_date']).date().isoformat()}"
        ),
        axis=1,
    )
    retained["cohort"] = "dynamic_causal_top3_proxy"
    retained["horizon_sessions"] = horizon_sessions
    retained["membership_evidence"] = EVIDENCE_LEVEL
    retained["feature_cutoff_date"] = retained["anchor_date"]
    retained["time_block"] = _chronological_blocks(retained["anchor_date"])
    columns = [
        *EPISODE_COLUMNS,
        "cycle_id",
        "feature_cutoff_date",
        "horizon_sessions",
        "membership_evidence",
        "concept_count_at_anchor",
        "concept_ids_at_anchor",
        "concept_names_at_anchor",
    ]
    return retained.loc[:, columns].sort_values(
        ["anchor_date", "vt_symbol"], kind="stable"
    ).reset_index(drop=True)


def filter_complete_episode_paths(
    episodes: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Exclude fixed-horizon episodes with any missing stock session."""

    episode_columns = ("episode_id", "vt_symbol", "anchor_date", "observation_end")
    bar_columns = ("vt_symbol", "trade_date")
    _require_columns(episodes, episode_columns, "leader wave episode")
    _require_columns(stock_bars, bar_columns, "stock daily bar")
    if episodes.empty:
        return episodes.copy(), pd.DataFrame()
    frame = episodes.copy()
    for column in ("anchor_date", "observation_end"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.normalize()
    bars = stock_bars.loc[:, list(bar_columns)].copy()
    bars["vt_symbol"] = bars["vt_symbol"].astype(str)
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.normalize()
    calendar = list(
        pd.DatetimeIndex(pd.to_datetime(tuple(trading_dates)))
        .normalize()
        .drop_duplicates()
        .sort_values()
    )
    positions = {trade_date: position for position, trade_date in enumerate(calendar)}
    available = {
        symbol: set(group["trade_date"])
        for symbol, group in bars.groupby("vt_symbol", sort=False)
    }
    retained: list[int] = []
    exclusions: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        anchor = pd.Timestamp(row["anchor_date"])
        boundary = pd.Timestamp(row["observation_end"])
        if anchor not in positions or boundary not in positions:
            raise ValueError("episode boundary is absent from the trading calendar")
        expected = calendar[positions[anchor] : positions[boundary] + 1]
        observed = available.get(str(row["vt_symbol"]), set())
        missing = [trade_date for trade_date in expected if trade_date not in observed]
        if not missing:
            retained.append(index)
            continue
        exclusions.append(
            {
                "episode_id": str(row["episode_id"]),
                "vt_symbol": str(row["vt_symbol"]),
                "anchor_date": anchor,
                "observation_end": boundary,
                "expected_sessions": len(expected),
                "observed_sessions": len(expected) - len(missing),
                "missing_session_count": len(missing),
                "first_missing_session": missing[0],
                "exclusion_reason": "incomplete_fixed_stock_path",
            }
        )
    return (
        frame.loc[retained].reset_index(drop=True),
        pd.DataFrame.from_records(exclusions),
    )


def classify_xuguang_climax(
    impulse_gain_pct: object,
    strong_days_ge_9_5pct: object,
    max_volume_ratio_prior5: object,
) -> bool:
    """Apply the predeclared three-part Xuguang climax hypothesis unchanged."""

    gain = _finite_or_none(impulse_gain_pct)
    strong_days = _finite_or_none(strong_days_ge_9_5pct)
    volume_ratio = _finite_or_none(max_volume_ratio_prior5)
    return bool(
        gain is not None
        and strong_days is not None
        and volume_ratio is not None
        and gain >= XUGUANG_CLIMAX_GAIN_PCT
        and strong_days >= XUGUANG_CLIMAX_STRONG_DAYS
        and volume_ratio >= XUGUANG_CLIMAX_VOLUME_RATIO
    )


def replay_leader_wave_episodes(
    episodes: pd.DataFrame,
    stock_bars: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Replay the existing wave/support/trade contract for every stock episode."""

    _require_columns(episodes, EPISODE_COLUMNS, "leader wave episode")
    bar_columns = (
        "vt_symbol",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
    )
    _require_columns(stock_bars, bar_columns, "stock daily bar")
    if episodes.empty:
        return _empty_replay()
    bars = stock_bars.loc[:, list(bar_columns)].copy()
    bars["vt_symbol"] = bars["vt_symbol"].astype(str)
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.normalize()
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock daily bar identities must be unique")
    needed = set(episodes["vt_symbol"].astype(str))
    features_by_symbol = {
        symbol: build_stock_wave_features(group.drop(columns="vt_symbol"))
        for symbol, group in bars.loc[bars["vt_symbol"].isin(needed)].groupby(
            "vt_symbol", sort=False
        )
    }
    missing = sorted(needed - set(features_by_symbol))
    if missing:
        raise ValueError(f"missing stock bars for wave episodes: {', '.join(missing)}")

    collected: dict[str, list[pd.DataFrame]] = {
        "waves": [],
        "approaches": [],
        "trades": [],
        "impulses": [],
    }
    for episode in episodes.sort_values(["anchor_date", "vt_symbol"]).to_dict("records"):
        symbol = str(episode["vt_symbol"])
        features = features_by_symbol[symbol]
        anchor = pd.Timestamp(episode["anchor_date"])
        boundary = pd.Timestamp(episode["observation_end"])
        available = set(features["trade_date"])
        if anchor not in available or boundary not in available:
            raise ValueError("episode boundaries must have stock daily bars")
        waves = build_leader_wave_ledger(
            features,
            anchor_date=anchor.date(),
            observation_end=boundary.date(),
            minimum_pullback_pct=5.0,
        )
        approaches = build_first_support_approaches(
            features,
            waves,
            approach_tolerance_pct=2.0,
        )
        trades = build_wave_pullback_trades(
            approaches,
            features,
            waves,
            round_trip_cost_pct=0.2,
        )
        impulses = _build_wave_impulses(features, waves)
        for name, frame in (
            ("waves", waves),
            ("approaches", approaches),
            ("trades", trades),
            ("impulses", impulses),
        ):
            collected[name].append(_attach_episode(frame, episode))

    replay = {
        name: pd.concat(frames, ignore_index=True, sort=False)
        if frames
        else pd.DataFrame()
        for name, frames in collected.items()
    }
    impulse_context = replay["impulses"].loc[
        :,
        [
            "episode_id",
            "wave_number",
            "impulse_gain_pct",
            "strong_days_ge_9_5pct",
            "max_volume_ratio_prior5",
            "median_volume_ratio_prior5",
            "xuguang_climax_candidate",
        ],
    ]
    for name in ("waves", "approaches", "trades"):
        if not replay[name].empty:
            replay[name] = replay[name].merge(
                impulse_context,
                on=["episode_id", "wave_number"],
                how="left",
                validate="many_to_one",
            )
    return replay


def build_non_overlapping_wave_paths(trades: pd.DataFrame) -> pd.DataFrame:
    """Keep one earliest support entry per wave and sequence it within each episode."""

    required = (
        "episode_id",
        "wave_number",
        "entry_date",
        "support_depth",
        "exit_date",
        "net_return_pct",
    )
    _require_columns(trades, required, "wave pullback trade")
    if trades.empty:
        result = trades.copy()
        result["episode_equity_after_exit"] = pd.Series(dtype=float)
        return result
    paths: list[pd.DataFrame] = []
    for _, episode_trades in trades.groupby("episode_id", sort=False):
        path = (
            episode_trades.sort_values(
                ["wave_number", "entry_date", "support_depth"],
                kind="stable",
            )
            .drop_duplicates("wave_number", keep="first")
            .reset_index(drop=True)
        )
        previous_exit: pd.Timestamp | None = None
        equity = 1.0
        equities: list[float | None] = []
        for row in path.to_dict("records"):
            entry = pd.Timestamp(row["entry_date"])
            if previous_exit is not None and entry < previous_exit:
                raise ValueError("one-position wave path contains overlapping trades")
            exit_date = row.get("exit_date")
            net_return = _finite_or_none(row.get("net_return_pct"))
            if exit_date is None or pd.isna(exit_date) or net_return is None:
                equities.append(None)
                previous_exit = None
                continue
            if net_return <= -100.0:
                raise ValueError("wave path return cannot lose more than all capital")
            equity *= 1.0 + net_return / 100.0
            equities.append(equity)
            previous_exit = pd.Timestamp(exit_date)
        path["episode_equity_after_exit"] = equities
        paths.append(path)
    return pd.concat(paths, ignore_index=True, sort=False)


def build_cross_leader_wave_report(
    *,
    dynamic_episodes: pd.DataFrame,
    dynamic_replay: Mapping[str, pd.DataFrame],
    reference_episodes: pd.DataFrame,
    reference_replay: Mapping[str, pd.DataFrame],
    coverage: Mapping[str, Any],
    fingerprints: Mapping[str, Mapping[str, Any]],
    dynamic_path_exclusions: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build descriptive cross-stock evidence without promoting formal metrics."""

    dynamic_waves = _replay_frame(dynamic_replay, "waves")
    dynamic_trades = _replay_frame(dynamic_replay, "trades")
    dynamic_path = build_non_overlapping_wave_paths(dynamic_trades)
    dynamic_path = _attach_retrospective_episode_class(dynamic_path, dynamic_waves)
    dynamic_impulses = _replay_frame(dynamic_replay, "impulses")
    reference_waves = _replay_frame(reference_replay, "waves")
    reference_trades = _replay_frame(reference_replay, "trades")
    reference_path = build_non_overlapping_wave_paths(reference_trades)
    path_exclusions = (
        dynamic_path_exclusions
        if isinstance(dynamic_path_exclusions, pd.DataFrame)
        else pd.DataFrame()
    )
    report = {
        "study_version": STUDY_VERSION,
        "research_status": "exploratory_cross_stock_proxy",
        "formal_strategy": False,
        "formal_metrics": {
            "win_rate_pct": None,
            "compounded_return_pct": None,
            "profit_factor": None,
            "maximum_drawdown_pct": None,
        },
        "dynamic_cohort": {
            "selection": "point_in_time_causal_top3_and_stock_main_rise_alive",
            "membership_evidence": EVIDENCE_LEVEL,
            "horizon_sessions": DEFAULT_HORIZON_SESSIONS,
            "same_stock_overlap_policy": "keep_earliest_then_skip_through_window_end",
            "episodes": int(len(dynamic_episodes)),
            "symbols": _nunique(dynamic_episodes, "vt_symbol"),
            "anchor_dates": _nunique(dynamic_episodes, "anchor_date"),
            "waves": int(len(dynamic_waves)),
            "resolved_waves": int(
                dynamic_waves.get("resolution_status", pd.Series(dtype=str))
                .isin(RESOLVED_WAVE_STATUSES)
                .sum()
            ),
            "support_trades": int(len(dynamic_trades)),
            "primary_path_trades": int(len(dynamic_path)),
            "incomplete_path_exclusions": int(len(path_exclusions)),
        },
        "reference_cohort": {
            "selection": "user_inspected_declared_campaigns",
            "pooled_with_dynamic": False,
            "episodes": int(len(reference_episodes)),
            "waves": int(len(reference_waves)),
            "support_trades": int(len(reference_trades)),
            "primary_path_trades": int(len(reference_path)),
        },
        "trade_contract": {
            "minimum_ordered_pullback_pct": 5.0,
            "approach_tolerance_pct": 2.0,
            "entry_proxy": "approach_day_close",
            "primary_exit": "first_later_higher_high_then_close",
            "defensive_exit": "second_consecutive_close_below_ma20",
            "round_trip_cost_pct": 0.2,
        },
        "xuguang_hypotheses": {
            "normal_volume_pullback_candidate": "0.8x_to_1.2x_prior5_median",
            "ma20_lower_risk_candidate": True,
            "climax_candidate": {
                "impulse_gain_pct_gte": XUGUANG_CLIMAX_GAIN_PCT,
                "strong_days_ge_9_5pct_gte": XUGUANG_CLIMAX_STRONG_DAYS,
                "max_volume_ratio_prior5_gte": XUGUANG_CLIMAX_VOLUME_RATIO,
                "combination": "all_three_required",
            },
        },
        "coverage": _json_safe(dict(coverage)),
        "fingerprints": _json_safe(dict(fingerprints)),
        "tables_read": {
            "stock_daily_bars": int(coverage.get("discovery_stock_bar_rows", 0))
            + int(coverage.get("reference_stock_bar_rows", 0)),
            "current_memberships": int(coverage.get("current_membership_rows", 0)),
            "strict_historical_memberships": int(
                coverage.get("strict_historical_membership_rows", 0)
            ),
            "minute_bars": 0,
            "market_timing": 0,
            "old_low_suction_outcomes": 0,
        },
        "dynamic_wave_summary": _wave_summary(dynamic_impulses),
        "dynamic_wave_maturity_summary": _wave_group_summary(
            dynamic_impulses.assign(
                wave_bucket=dynamic_impulses.get(
                    "wave_number", pd.Series(dtype=float)
                ).map(_wave_bucket)
            ),
            "wave_bucket",
        ),
        "dynamic_climax_summary": _wave_group_summary(
            dynamic_impulses,
            "xuguang_climax_candidate",
        ),
        "dynamic_support_summary": _trade_group_summary(
            dynamic_trades,
            "support_line",
        ),
        "dynamic_volume_summary": _trade_group_summary(
            dynamic_trades,
            "volume_class_prior5",
        ),
        "dynamic_reclaim_summary": _trade_group_summary(
            dynamic_trades,
            "close_reclaimed_support",
        ),
        "dynamic_rank_summary": _trade_group_summary(
            dynamic_trades.assign(
                rank_bucket=dynamic_trades.get(
                    "causal_rank", pd.Series(dtype=float)
                ).map(_rank_bucket)
            ),
            "rank_bucket",
        ),
        "dynamic_time_block_summary": _trade_group_summary(
            dynamic_trades,
            "time_block",
        ),
        "dynamic_climax_trade_summary": _trade_group_summary(
            dynamic_trades,
            "xuguang_climax_candidate",
        ),
        "dynamic_primary_path_summary": _path_summary(dynamic_path),
        "dynamic_primary_path_support_summary": _trade_group_summary(
            dynamic_path,
            "support_line",
        ),
        "dynamic_primary_path_volume_summary": _trade_group_summary(
            dynamic_path,
            "volume_class_prior5",
        ),
        "dynamic_primary_path_time_block_summary": _trade_group_summary(
            dynamic_path,
            "time_block",
        ),
        "dynamic_primary_path_wave_summary": _trade_group_summary(
            dynamic_path.assign(
                wave_bucket=dynamic_path.get(
                    "wave_number", pd.Series(dtype=float)
                ).map(_wave_bucket)
            ),
            "wave_bucket",
        ),
        "dynamic_retrospective_episode_summary": _trade_group_summary(
            dynamic_path,
            "retrospective_episode_class",
        ),
        "reference_cases": _reference_case_summaries(
            reference_episodes,
            reference_waves,
            reference_trades,
            reference_path,
        ),
        "representative_dynamic_waves": _representative_wave_rows(dynamic_impulses),
        "evidence_boundaries": {
            "identity_features": "point_in_time",
            "support_features": "point_in_time",
            "wave_resolution": "retrospective_label",
            "entry_fill": "daily_close_proxy",
            "dynamic_episode_independence": "same_stock_40_session_windows_do_not_overlap",
            "support_path_independence": "multiple_line_hypotheses_can_overlap_within_episode",
        },
        "limitations": [
            "Historical concept membership is a current-membership survivorship proxy, not strict point-in-time membership.",
            "Causal Top3 identity previously failed the absolute identity gate and is used only as a broad proxy cohort.",
            "Support-line paths inside one episode can overlap and must not be compounded as independent trades.",
            "The reference leaders were already inspected and remain separate from the dynamic cohort.",
            "Daily closes are proxies; no D+1 10:30 execution claim is made without minute bars.",
        ],
    }
    report["observed_hypothesis_results"] = _observed_hypothesis_results(report)
    report["dynamic_episode_manifest"] = _records(dynamic_episodes)
    report["dynamic_path_exclusions"] = _records(path_exclusions)
    report["dynamic_wave_ledger"] = _records(dynamic_waves)
    report["dynamic_support_trade_ledger"] = _records(dynamic_trades)
    report["dynamic_primary_wave_path"] = _records(dynamic_path)
    report["reference_wave_ledger"] = _records(reference_waves)
    report["reference_support_trade_ledger"] = _records(reference_trades)
    report["reference_primary_wave_path"] = _records(reference_path)
    report["reproduce"] = (
        "legacy CLI retired; use the daily-factor-* commands for current "
        "low-suction research"
    )
    return report


def render_cross_leader_wave_json(report: Mapping[str, Any]) -> str:
    """Render deterministic machine-readable cross-leader evidence."""

    return json.dumps(
        _json_safe(report),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_cross_leader_wave_markdown(report: Mapping[str, Any]) -> str:
    """Render the cross-leader comparisons and evidence boundaries."""

    dynamic = _mapping(report.get("dynamic_cohort"))
    wave = _mapping(report.get("dynamic_wave_summary"))
    lines = [
        "# AlphaAgent 跨龙头主升波浪与均线低吸研究",
        "",
        "结论边界：动态 cohort 使用当前成员生存偏差代理，正式 Top3 尚未通过身份门。",
        "正式胜率、收益、复利：`null`。以下比例只描述固定历史代理路径。",
        "",
        "## Coverage",
        "",
        f"- 动态非重叠 episode：`{dynamic.get('episodes', 0)}`；股票："
        f"`{dynamic.get('symbols', 0)}`；锚点日期：`{dynamic.get('anchor_dates', 0)}`。",
        f"- 波浪：`{wave.get('waves', 0)}`；已决波浪："
        f"`{wave.get('resolved_waves', 0)}`；再创新高："
        f"`{wave.get('continued_waves', 0)}`；终止：`{wave.get('terminal_waves', 0)}`。",
        f"- 已决波浪描述性续浪比例："
        f"`{_pct(wave.get('descriptive_continuation_share_pct'))}`。",
        f"- 支撑路径：`{dynamic.get('support_trades', 0)}`；同一 episode 内不同均线"
        "可以重叠，不能当作独立账户交易复利。",
        "",
        "## Primary Non-overlapping Path",
        "",
        *_primary_path_lines(report.get("dynamic_primary_path_summary")),
        "",
        "## MA Support",
        "",
        "| Support | Episodes | Closed | Positive share | Higher-high share | Median net | Median MAE | False exits |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_trade_summary_lines(report.get("dynamic_support_summary")),
        "",
        "## Pullback Volume",
        "",
        "| Volume | Episodes | Closed | Positive share | Higher-high share | Median net | Median MAE | False exits |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_trade_summary_lines(report.get("dynamic_volume_summary")),
        "",
        "## Wave Maturity",
        "",
        "| Wave | Episodes | Resolved | Continued | Terminal | Continuation share |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        *_wave_summary_lines(report.get("dynamic_wave_maturity_summary")),
        "",
        "## Primary Path By Wave",
        "",
        "| Wave | Episodes | Closed | Positive share | Higher-high share | Median net | Median MAE | False exits |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_trade_summary_lines(report.get("dynamic_primary_path_wave_summary")),
        "",
        "## Xuguang Climax Test",
        "",
        "固定条件为涨幅至少 50%、至少 3 个接近涨停日、最大量比至少 3x，三项必须同时成立。",
        "",
        "| Climax | Episodes | Resolved | Continued | Terminal | Continuation share |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        *_wave_summary_lines(report.get("dynamic_climax_summary")),
        "",
        "## Chronological Blocks",
        "",
        "| Block | Episodes | Closed | Positive share | Higher-high share | Median net | Median MAE | False exits |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_trade_summary_lines(report.get("dynamic_primary_path_time_block_summary")),
        "",
        "## Retrospective Leader Diagnosis",
        "",
        "该分组需要完整 40 日后才知道，只用于解释身份问题，不能成为实时过滤器。",
        "",
        "| Outcome class | Episodes | Closed | Positive share | Higher-high share | Median net | Median MAE | False exits |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_trade_summary_lines(report.get("dynamic_retrospective_episode_summary")),
        "",
        "## Reference Leaders",
        "",
        "参考个股已经被查看过，只作逐股解释，不与动态 cohort 混合。",
        "",
        "| Stock | Anchor | Waves | Resolved | Continued | Terminal | Entries | Positive | Median net | Median MAE |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_reference_lines(report.get("reference_cases")),
        "",
        "## Hypothesis Results",
        "",
        *_hypothesis_lines(report.get("observed_hypothesis_results")),
        "",
        "## Boundaries",
        "",
        "- 候选身份、均线位置、回踩量能和买入日字段只读当日及以前。",
        "- 后来再创新高、终止浪和收益是事后标签，不参与 episode 选择。",
        "- 动态 episode 同股 40 个交易时段不重叠；均线支撑路径仍可能重叠。",
        "- 本轮未读取分钟线、金银环境或旧低吸结果，不能回答 D+1 10:30 精确成交。",
        "",
        "## Reproduce",
        "",
        "```bash",
        str(report.get("reproduce") or ""),
        "```",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_reference_wave_episodes(reference_bars: pd.DataFrame) -> pd.DataFrame:
    """Build full observed windows for the already-inspected reference leaders."""

    required = ("vt_symbol", "trade_date")
    _require_columns(reference_bars, required, "reference stock bar")
    bars = reference_bars.loc[:, list(required)].copy()
    bars["vt_symbol"] = bars["vt_symbol"].astype(str)
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.normalize()
    rows: list[dict[str, Any]] = []
    for symbol, stock_name, anchor_date in REFERENCE_CAMPAIGNS:
        stock_dates = bars.loc[bars["vt_symbol"].eq(symbol), "trade_date"]
        anchor = pd.Timestamp(anchor_date)
        if stock_dates.empty or anchor not in set(stock_dates):
            raise ValueError(f"reference campaign is unavailable: {symbol} {anchor_date}")
        rows.append(
            {
                "episode_id": f"reference:{symbol}:{anchor_date.isoformat()}",
                "cohort": "declared_reference",
                "vt_symbol": symbol,
                "stock_name": stock_name,
                "anchor_date": anchor,
                "observation_end": stock_dates.max(),
                "causal_rank": None,
                "sector_id": "declared_reference",
                "concept_name": "",
                "time_block": "reference",
            }
        )
    return pd.DataFrame.from_records(rows, columns=list(EPISODE_COLUMNS))


def run_cross_leader_wave_study() -> dict[str, Any]:
    """Run the full proxy cohort and the isolated declared reference leaders."""

    from .research_protocol import fingerprint_frame
    from .true_leader_study import (
        build_emotion_cycle_candidates,
        build_point_in_time_stock_features,
        load_true_leader_study_inputs,
        rank_causal_cycle_leaders,
    )

    inputs = load_true_leader_study_inputs(include_reference_bars=True)
    stock_features = build_point_in_time_stock_features(inputs.stock_bars)
    candidates = build_emotion_cycle_candidates(
        inputs.cycle_starts,
        inputs.memberships,
        stock_features,
    )
    causal_ranks = rank_causal_cycle_leaders(candidates)
    selected_episodes = build_causal_wave_episodes(
        causal_ranks,
        trading_dates=inputs.trading_dates,
    )
    dynamic_episodes, path_exclusions = filter_complete_episode_paths(
        selected_episodes,
        inputs.stock_bars,
        trading_dates=inputs.trading_dates,
    )
    dynamic_replay = replay_leader_wave_episodes(dynamic_episodes, inputs.stock_bars)
    reference_episodes = build_reference_wave_episodes(inputs.reference_bars)
    reference_replay = replay_leader_wave_episodes(
        reference_episodes,
        inputs.reference_bars,
    )
    coverage = {
        **inputs.coverage,
        "causal_rank_rows": int(len(causal_ranks)),
        "causal_top3_rows": int(causal_ranks["causal_top3"].astype(bool).sum()),
        "causal_top3_main_rise_alive_rows": int(
            (
                causal_ranks["causal_top3"].astype(bool)
                & causal_ranks["main_rise_alive"].astype(bool)
            ).sum()
        ),
        "dynamic_non_overlapping_episodes": int(len(dynamic_episodes)),
        "dynamic_pre_path_gate_episodes": int(len(selected_episodes)),
        "dynamic_incomplete_path_exclusions": int(len(path_exclusions)),
        "dynamic_episode_symbols": int(dynamic_episodes["vt_symbol"].nunique()),
        "dynamic_wave_rows": int(len(dynamic_replay["waves"])),
        "dynamic_support_trade_rows": int(len(dynamic_replay["trades"])),
        "reference_episodes": int(len(reference_episodes)),
        "reference_wave_rows": int(len(reference_replay["waves"])),
        "reference_support_trade_rows": int(len(reference_replay["trades"])),
    }
    generated_fingerprints = {
        "dynamic_wave_episodes": fingerprint_frame(
            dynamic_episodes,
            identity_columns=("episode_id",),
        ).as_dict(),
        "dynamic_wave_ledger": fingerprint_frame(
            dynamic_replay["waves"],
            identity_columns=("episode_id", "wave_number"),
        ).as_dict(),
        "dynamic_support_trades": fingerprint_frame(
            dynamic_replay["trades"],
            identity_columns=("episode_id", "trade_id"),
        ).as_dict(),
        "reference_wave_ledger": fingerprint_frame(
            reference_replay["waves"],
            identity_columns=("episode_id", "wave_number"),
        ).as_dict(),
    }
    return build_cross_leader_wave_report(
        dynamic_episodes=dynamic_episodes,
        dynamic_replay=dynamic_replay,
        reference_episodes=reference_episodes,
        reference_replay=reference_replay,
        coverage=coverage,
        fingerprints={**inputs.fingerprints, **generated_fingerprints},
        dynamic_path_exclusions=path_exclusions,
    )


def _observed_hypothesis_results(report: Mapping[str, Any]) -> dict[str, Any]:
    support = _summary_by_group(report.get("dynamic_support_summary"))
    volume = _summary_by_group(report.get("dynamic_volume_summary"))
    climax = _summary_by_group(report.get("dynamic_climax_summary"))
    ma5 = support.get("ma5", {})
    ma20 = support.get("ma20", {})
    normal = volume.get("normal", {})
    explosion = volume.get("explosion", {})
    climax_true = climax.get("True", {})
    climax_false = climax.get("False", {})
    ma_lower_risk = _greater(
        ma20.get("median_mae_pct"),
        ma5.get("median_mae_pct"),
    )
    ma_higher_net = _greater(
        ma20.get("median_net_return_pct"),
        ma5.get("median_net_return_pct"),
    )
    volume_higher_net = _greater(
        normal.get("median_net_return_pct"),
        explosion.get("median_net_return_pct"),
    )
    volume_higher_high = _greater(
        normal.get("eventual_higher_high_share_pct"),
        explosion.get("eventual_higher_high_share_pct"),
    )
    climax_lower_continuation = _less(
        climax_true.get("descriptive_continuation_share_pct"),
        climax_false.get("descriptive_continuation_share_pct"),
    )
    false_exits = sum(
        int(_mapping(row).get("defensive_exit_preceded_later_higher_high") or 0)
        for row in _sequence(report.get("dynamic_support_summary"))
    )
    primary = _mapping(report.get("dynamic_primary_path_summary"))
    return {
        "ma20_vs_ma5": {
            "status": _pair_status(ma_lower_risk, ma_higher_net),
            "ma20_has_lower_median_mae": ma_lower_risk,
            "ma20_has_higher_median_net": ma_higher_net,
            "ma20_entries": ma20.get("entries"),
            "ma5_entries": ma5.get("entries"),
        },
        "normal_vs_explosion_volume": {
            "status": _pair_status(volume_higher_net, volume_higher_high),
            "normal_has_higher_median_net": volume_higher_net,
            "normal_has_higher_higher_high_share": volume_higher_high,
            "normal_entries": normal.get("entries"),
            "explosion_entries": explosion.get("entries"),
        },
        "xuguang_climax_terminal_risk": {
            "status": (
                "supported" if climax_lower_continuation is True else
                "not_supported" if climax_lower_continuation is False else
                "insufficient"
            ),
            "climax_has_lower_continuation_share": climax_lower_continuation,
            "climax_resolved_waves": climax_true.get("resolved_waves"),
            "non_climax_resolved_waves": climax_false.get("resolved_waves"),
        },
        "two_close_ma20_exit": {
            "false_exit_paths_before_later_higher_high": false_exits,
            "primary_path_false_exits_before_later_higher_high": primary.get(
                "false_exit_paths_before_later_higher_high"
            ),
            "status": "no_observed_false_exit" if false_exits == 0 else "false_exits_observed",
        },
    }


def _summary_by_group(raw: object) -> dict[str, Mapping[str, Any]]:
    return {
        str(_mapping(item).get("group")): _mapping(item)
        for item in _sequence(raw)
    }


def _trade_summary_lines(raw: object) -> list[str]:
    rows = []
    for item in _sequence(raw):
        row = _mapping(item)
        rows.append(
            f"| `{row.get('group')}` | {row.get('episodes')} | "
            f"{row.get('closed_entries')} | "
            f"{_pct(row.get('descriptive_positive_share_pct'))} | "
            f"{_pct(row.get('eventual_higher_high_share_pct'))} | "
            f"{_pct(row.get('median_net_return_pct'))} | "
            f"{_pct(row.get('median_mae_pct'))} | "
            f"{row.get('defensive_exit_preceded_later_higher_high')} |"
        )
    return rows or ["| - | 0 | 0 | - | - | - | - | 0 |"]


def _primary_path_lines(raw: object) -> list[str]:
    row = _mapping(raw)
    if not row:
        return ["- 无闭合主路径。"]
    return [
        f"- 每浪最早且顺序不重叠：`{row.get('trades')}` 笔，闭合 "
        f"`{row.get('closed_trades')}` 笔；成本后为正比例 "
        f"`{_pct(row.get('descriptive_positive_share_pct'))}`。",
        f"- 单笔均值/中位数：`{_pct(row.get('mean_net_return_pct'))}` / "
        f"`{_pct(row.get('median_net_return_pct'))}`；MAE 中位数 "
        f"`{_pct(row.get('median_mae_pct'))}`。",
        f"- 单 episode 顺序复合收益中位数："
        f"`{_pct(row.get('median_episode_compounded_return_pct'))}`；"
        f"正复合 episode 比例 `{_pct(row.get('positive_episode_compound_share_pct'))}`。",
        f"- 两日跌破 MA20 后退出、后来又创新高："
        f"`{row.get('false_exit_paths_before_later_higher_high')}` 笔。",
    ]


def _wave_summary_lines(raw: object) -> list[str]:
    rows = []
    for item in _sequence(raw):
        row = _mapping(item)
        rows.append(
            f"| `{row.get('group')}` | {row.get('episodes')} | "
            f"{row.get('resolved_waves')} | {row.get('continued_waves')} | "
            f"{row.get('terminal_waves')} | "
            f"{_pct(row.get('descriptive_continuation_share_pct'))} |"
        )
    return rows or ["| - | 0 | 0 | 0 | 0 | - |"]


def _reference_lines(raw: object) -> list[str]:
    rows = []
    for item in _sequence(raw):
        row = _mapping(item)
        rows.append(
            f"| {row.get('stock_name')} `{row.get('vt_symbol')}` | "
            f"{row.get('anchor_date')} | {row.get('waves')} | "
            f"{row.get('resolved_waves')} | {row.get('continued_waves')} | "
            f"{row.get('terminal_waves')} | {row.get('support_entries')} | "
            f"{row.get('positive_support_entries')} | "
            f"{_pct(row.get('median_support_net_return_pct'))} | "
            f"{_pct(row.get('median_support_mae_pct'))} |"
        )
    return rows or ["| - | - | 0 | 0 | 0 | 0 | 0 | 0 | - | - |"]


def _hypothesis_lines(raw: object) -> list[str]:
    rows = []
    for name, item in sorted(_mapping(raw).items()):
        detail = _mapping(item)
        rows.append(f"- `{name}`：`{detail.get('status')}`；`{_compact_detail(detail)}`。")
    return rows or ["- 尚无可比较样本。"]


def _compact_detail(values: Mapping[str, Any]) -> str:
    return ", ".join(
        f"{key}={_json_safe(value)}"
        for key, value in values.items()
        if key != "status"
    )


def _pair_status(first: bool | None, second: bool | None) -> str:
    if first is None or second is None:
        return "insufficient"
    if first and second:
        return "supported"
    if not first and not second:
        return "not_supported"
    return "mixed"


def _greater(left: object, right: object) -> bool | None:
    first = _finite_or_none(left)
    second = _finite_or_none(right)
    return first > second if first is not None and second is not None else None


def _less(left: object, right: object) -> bool | None:
    first = _finite_or_none(left)
    second = _finite_or_none(right)
    return first < second if first is not None and second is not None else None


def _retain_non_overlapping_windows(frame: pd.DataFrame) -> pd.DataFrame:
    retained: list[int] = []
    for _, symbol_frame in frame.groupby("vt_symbol", sort=True):
        last_end: pd.Timestamp | None = None
        for index, row in symbol_frame.sort_values("anchor_date").iterrows():
            anchor = pd.Timestamp(row["anchor_date"])
            if last_end is not None and anchor <= last_end:
                continue
            retained.append(index)
            last_end = pd.Timestamp(row["observation_end"])
    return frame.loc[retained].copy()


def _chronological_blocks(values: pd.Series, block_count: int = 5) -> pd.Series:
    dates = sorted(pd.to_datetime(values, errors="raise").dt.normalize().unique())
    mapping: dict[pd.Timestamp, str] = {}
    for block_number, block_dates in enumerate(np.array_split(dates, block_count), start=1):
        for value in block_dates:
            mapping[pd.Timestamp(value)] = f"block_{block_number}"
    return pd.to_datetime(values).dt.normalize().map(mapping)


def _build_wave_impulses(
    features: pd.DataFrame,
    waves: pd.DataFrame,
) -> pd.DataFrame:
    positions = {
        pd.Timestamp(trade_date): position
        for position, trade_date in enumerate(features["trade_date"])
    }
    rows: list[dict[str, Any]] = []
    for wave in waves.to_dict("records"):
        start = pd.Timestamp(wave["wave_start_date"])
        peak = pd.Timestamp(wave["peak_date"])
        impulse = features.loc[features["trade_date"].between(start, peak)]
        gain = (
            float(wave["peak_price"]) / float(impulse.iloc[0]["close_price"]) - 1.0
        ) * 100.0
        strong_days = int(impulse["daily_return_pct"].ge(9.5).sum())
        max_volume = _finite_or_none(impulse["volume_ratio_prior5"].max())
        median_volume = _finite_or_none(impulse["volume_ratio_prior5"].median())
        rows.append(
            {
                "wave_number": int(wave["wave_number"]),
                "wave_start_date": start,
                "peak_date": peak,
                "sessions_to_peak": positions[peak] - positions[start],
                "start_close": float(impulse.iloc[0]["close_price"]),
                "peak_price": float(wave["peak_price"]),
                "impulse_gain_pct": gain,
                "strong_days_ge_9_5pct": strong_days,
                "max_volume_ratio_prior5": max_volume,
                "median_volume_ratio_prior5": median_volume,
                "resolution_status": str(wave["resolution_status"]),
                "xuguang_climax_candidate": classify_xuguang_climax(
                    gain,
                    strong_days,
                    max_volume,
                ),
            }
        )
    return pd.DataFrame.from_records(rows)


def _attach_episode(frame: pd.DataFrame, episode: Mapping[str, Any]) -> pd.DataFrame:
    result = frame.copy()
    for column in EPISODE_COLUMNS:
        result[column] = episode.get(column)
    return result


def _wave_summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "waves": 0,
            "resolved_waves": 0,
            "continued_waves": 0,
            "terminal_waves": 0,
            "descriptive_continuation_share_pct": None,
        }
    resolved = frame.loc[frame["resolution_status"].isin(RESOLVED_WAVE_STATUSES)]
    continued = int(resolved["resolution_status"].eq("continued_to_higher_high").sum())
    return {
        "episodes": int(frame["episode_id"].nunique()),
        "waves": int(len(frame)),
        "resolved_waves": int(len(resolved)),
        "continued_waves": continued,
        "terminal_waves": int(
            resolved["resolution_status"].eq("terminal_failure_observed").sum()
        ),
        "descriptive_continuation_share_pct": (
            continued / len(resolved) * 100.0 if not resolved.empty else None
        ),
        "climax_waves": int(frame["xuguang_climax_candidate"].astype(bool).sum()),
    }


def _wave_group_summary(frame: pd.DataFrame, group_column: str) -> list[dict[str, Any]]:
    if frame.empty or group_column not in frame:
        return []
    rows = []
    for group, grouped in frame.groupby(group_column, dropna=False, sort=True):
        rows.append({"group": _json_safe(group), **_wave_summary(grouped)})
    return rows


def _trade_group_summary(frame: pd.DataFrame, group_column: str) -> list[dict[str, Any]]:
    if frame.empty or group_column not in frame:
        return []
    rows: list[dict[str, Any]] = []
    for group, grouped in frame.groupby(group_column, dropna=False, sort=True):
        closed = grouped.loc[grouped["exit_date"].notna()]
        positive = int(closed["net_return_pct"].gt(0).sum())
        later_high = int(closed["eventually_made_higher_high"].astype(bool).sum())
        rows.append(
            {
                "group": _json_safe(group),
                "episodes": int(grouped["episode_id"].nunique()),
                "entries": int(len(grouped)),
                "closed_entries": int(len(closed)),
                "positive_closed_entries": positive,
                "descriptive_positive_share_pct": (
                    positive / len(closed) * 100.0 if not closed.empty else None
                ),
                "eventual_higher_high_entries": later_high,
                "eventual_higher_high_share_pct": (
                    later_high / len(closed) * 100.0 if not closed.empty else None
                ),
                "mean_net_return_pct": _mean(closed["net_return_pct"]),
                "median_net_return_pct": _median(closed["net_return_pct"]),
                "median_mae_pct": _median(closed["maximum_adverse_excursion_pct"]),
                "defensive_exit_preceded_later_higher_high": int(
                    closed["defensive_exit_preceded_later_higher_high"]
                    .astype(bool)
                    .sum()
                ),
            }
        )
    return rows


def _reference_case_summaries(
    episodes: pd.DataFrame,
    waves: pd.DataFrame,
    trades: pd.DataFrame,
    paths: pd.DataFrame,
) -> list[dict[str, Any]]:
    if episodes.empty:
        return []
    rows = []
    for episode in episodes.sort_values("anchor_date").to_dict("records"):
        episode_id = str(episode["episode_id"])
        case_waves = waves.loc[waves["episode_id"].astype(str).eq(episode_id)]
        case_trades = trades.loc[trades["episode_id"].astype(str).eq(episode_id)]
        case_path = paths.loc[paths["episode_id"].astype(str).eq(episode_id)]
        closed = case_trades.loc[case_trades["exit_date"].notna()]
        rows.append(
            {
                "vt_symbol": str(episode["vt_symbol"]),
                "stock_name": str(episode["stock_name"]),
                "anchor_date": _date_text(episode["anchor_date"]),
                "observation_end": _date_text(episode["observation_end"]),
                **_wave_summary(case_waves),
                "support_entries": int(len(case_trades)),
                "positive_support_entries": int(closed["net_return_pct"].gt(0).sum()),
                "median_support_net_return_pct": _median(closed["net_return_pct"]),
                "median_support_mae_pct": _median(
                    closed["maximum_adverse_excursion_pct"]
                ),
                "primary_path": _path_summary(case_path),
            }
        )
    return rows


def _path_summary(path: pd.DataFrame) -> dict[str, Any]:
    if path.empty:
        return {
            "episodes": 0,
            "trades": 0,
            "closed_trades": 0,
            "positive_trades": 0,
            "descriptive_positive_share_pct": None,
            "mean_net_return_pct": None,
            "median_net_return_pct": None,
            "median_mae_pct": None,
            "median_episode_compounded_return_pct": None,
            "positive_episode_compound_share_pct": None,
            "false_exit_paths_before_later_higher_high": 0,
        }
    closed = path.loc[path["exit_date"].notna()].copy()
    final_equities = (
        closed.dropna(subset=["episode_equity_after_exit"])
        .sort_values(["episode_id", "exit_date"], kind="stable")
        .groupby("episode_id", sort=False)["episode_equity_after_exit"]
        .last()
    )
    positive = int(closed["net_return_pct"].gt(0).sum())
    return {
        "episodes": int(path["episode_id"].nunique()),
        "trades": int(len(path)),
        "closed_trades": int(len(closed)),
        "positive_trades": positive,
        "descriptive_positive_share_pct": (
            positive / len(closed) * 100.0 if not closed.empty else None
        ),
        "mean_net_return_pct": _mean(closed["net_return_pct"]),
        "median_net_return_pct": _median(closed["net_return_pct"]),
        "median_mae_pct": _median(closed["maximum_adverse_excursion_pct"]),
        "median_episode_compounded_return_pct": (
            _median((final_equities - 1.0) * 100.0)
            if not final_equities.empty
            else None
        ),
        "positive_episode_compound_share_pct": (
            float(final_equities.gt(1.0).mean() * 100.0)
            if not final_equities.empty
            else None
        ),
        "false_exit_paths_before_later_higher_high": int(
            closed["defensive_exit_preceded_later_higher_high"].astype(bool).sum()
        ),
    }


def _attach_retrospective_episode_class(
    path: pd.DataFrame,
    waves: pd.DataFrame,
) -> pd.DataFrame:
    result = path.copy()
    if result.empty:
        result["retrospective_episode_class"] = pd.Series(dtype=str)
        return result
    continued = (
        waves.assign(
            continued=waves["resolution_status"].eq("continued_to_higher_high")
        )
        .groupby("episode_id", sort=False)["continued"]
        .sum()
    )
    counts = result["episode_id"].map(continued).fillna(0).astype(int)
    result["retrospective_episode_class"] = np.select(
        [counts.ge(2), counts.eq(1)],
        ["confirmed_multi_wave", "single_continuation"],
        default="no_continuation",
    )
    return result


def _representative_wave_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    columns = [
        "episode_id",
        "vt_symbol",
        "stock_name",
        "anchor_date",
        "concept_name",
        "causal_rank",
        "wave_number",
        "peak_date",
        "impulse_gain_pct",
        "strong_days_ge_9_5pct",
        "max_volume_ratio_prior5",
        "xuguang_climax_candidate",
        "resolution_status",
    ]
    resolved = frame.loc[frame["resolution_status"].isin(RESOLVED_WAVE_STATUSES)].copy()
    successful = resolved.loc[
        resolved["resolution_status"].eq("continued_to_higher_high")
    ].nlargest(5, "impulse_gain_pct")
    terminal = resolved.loc[
        resolved["resolution_status"].eq("terminal_failure_observed")
    ].nlargest(5, "impulse_gain_pct")
    return _records(pd.concat([successful, terminal], ignore_index=True)[columns])


def _empty_episode_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            *EPISODE_COLUMNS,
            "cycle_id",
            "feature_cutoff_date",
            "horizon_sessions",
            "membership_evidence",
            "concept_count_at_anchor",
            "concept_ids_at_anchor",
            "concept_names_at_anchor",
        ]
    )


def _empty_replay() -> dict[str, pd.DataFrame]:
    return {name: pd.DataFrame() for name in ("waves", "approaches", "trades", "impulses")}


def _replay_frame(replay: Mapping[str, pd.DataFrame], name: str) -> pd.DataFrame:
    frame = replay.get(name)
    return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def _wave_bucket(value: object) -> str:
    numeric = _finite_or_none(value)
    if numeric is None:
        return "unavailable"
    wave = int(numeric)
    return f"wave_{wave}" if wave <= 3 else "wave_4_plus"


def _rank_bucket(value: object) -> str:
    numeric = _finite_or_none(value)
    if numeric is None:
        return "reference"
    return "top1" if int(numeric) == 1 else "top2_3"


def _joined_unique(values: pd.Series) -> str:
    return "|".join(sorted(set(values.dropna().astype(str))))


def _is_main_board_symbol(value: object) -> bool:
    text = str(value).strip().upper()
    if text.endswith(".SSE"):
        return text.split(".", 1)[0].startswith(("600", "601", "603", "605"))
    if text.endswith(".SZSE"):
        return text.split(".", 1)[0].startswith(("000", "001", "002", "003"))
    return False


def _nunique(frame: pd.DataFrame, column: str) -> int:
    return int(frame[column].nunique()) if column in frame else 0


def _mean(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.mean()) if not numeric.empty else None


def _median(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.median()) if not numeric.empty else None


def _finite_or_none(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _date_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _pct(value: object) -> str:
    numeric = _finite_or_none(value)
    return f"{numeric:.4f}%" if numeric is not None else "-"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[Any]:
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


def _require_columns(
    frame: pd.DataFrame,
    required: Sequence[str],
    label: str,
) -> None:
    missing = sorted(set(required) - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
