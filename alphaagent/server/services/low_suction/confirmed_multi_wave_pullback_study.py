"""Causal pullback study after two already-confirmed higher highs."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .cross_leader_wave_study import (
    build_causal_wave_episodes,
    classify_xuguang_climax,
    filter_complete_episode_paths,
    replay_leader_wave_episodes,
)
from .stock_wave_pullbacks import build_stock_wave_features, classify_volume_ratio
from .true_leader_study import EVIDENCE_LEVEL


STUDY_VERSION = "confirmed-multi-wave-pullback-v1"
MIN_CONFIRMED_HIGHER_HIGHS = 2
MIN_PULLBACK_PCT = 5.0
APPROACH_TOLERANCE_PCT = 2.0
ROUND_TRIP_COST_PCT = 0.2
MIN_PRIMARY_CLOSED_TRADES = 100
MIN_BLOCK_CLOSED_TRADES = 30
MIN_POOLED_POSITIVE_SHARE_PCT = 60.0
MIN_BLOCK_POSITIVE_SHARE_PCT = 55.0
MIN_PROFIT_FACTOR = 1.20
MIN_STABLE_BLOCKS = 4

SUPPORT_DEPTH = {"ma5": 1, "ma10": 2, "ma20": 3}
SIGNAL_MODES = ("first_approach", "stabilized_reclaim")
EPISODE_COLUMNS = (
    "episode_id",
    "cycle_id",
    "vt_symbol",
    "stock_name",
    "sector_id",
    "concept_name",
    "anchor_date",
    "observation_end",
    "causal_rank",
    "time_block",
)
SIGNAL_COLUMNS = (
    *EPISODE_COLUMNS,
    "signal_id",
    "signal_mode",
    "wave_number",
    "wave_bucket",
    "confirmed_higher_highs_at_wave_start",
    "wave_start_date",
    "pullback_confirmation_date",
    "first_support_approach_date",
    "signal_date",
    "reference_peak_date",
    "reference_peak_price",
    "support_line",
    "support_depth",
    "support_price",
    "line_distance_low_pct",
    "line_distance_close_pct",
    "close_reclaimed_support",
    "signal_close_not_below_previous",
    "signal_daily_return_pct",
    "signal_close_to_peak_pct",
    "pullback_confirmation_low_to_peak_pct",
    "volume_ratio_prior5",
    "volume_ratio_impulse",
    "volume_class_prior5",
    "volume_class_impulse",
    "impulse_gain_pct",
    "strong_days_ge_9_5pct",
    "max_volume_ratio_prior5",
    "xuguang_climax_candidate",
    "stock_structure_intact",
    "concept_state_available",
    "concept_cycle_active",
    "concept_trend_order",
    "concept_main_rise_intact",
    "concept_active_cycle_id",
    "primary_eligible",
    "feature_cutoff_date",
)


@dataclass(frozen=True)
class ConfirmedPullbackResult:
    signals: pd.DataFrame
    trades: pd.DataFrame
    exclusions: pd.DataFrame


def build_confirmed_multi_wave_signals(
    episodes: pd.DataFrame,
    waves: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_states: pd.DataFrame,
) -> pd.DataFrame:
    """Replay wave 3+ signals without selecting on the final wave outcome."""

    return _build_support_signals(
        episodes,
        waves,
        stock_bars,
        concept_states,
        minimum_wave_number=MIN_CONFIRMED_HIGHER_HIGHS + 1,
    )


def build_campaign_support_signals(
    episodes: pd.DataFrame,
    waves: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_states: pd.DataFrame,
) -> pd.DataFrame:
    """Replay stabilized support opportunities from the campaign's first wave."""

    return _build_support_signals(
        episodes,
        waves,
        stock_bars,
        concept_states,
        minimum_wave_number=1,
    )


def _build_support_signals(
    episodes: pd.DataFrame,
    waves: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_states: pd.DataFrame,
    *,
    minimum_wave_number: int,
) -> pd.DataFrame:
    if minimum_wave_number < 1:
        raise ValueError("minimum wave number must be positive")

    episode_frame = _prepare_episodes(episodes)
    wave_frame = _prepare_waves(waves)
    stock_features = _stock_features_by_symbol(stock_bars)
    concept_index = _prepare_concept_state_index(concept_states)
    eligible = wave_frame.loc[
        wave_frame["wave_number"].ge(minimum_wave_number)
    ].merge(
        episode_frame,
        on="episode_id",
        how="inner",
        validate="many_to_one",
        suffixes=("_wave", ""),
    )
    if eligible.empty:
        return pd.DataFrame(columns=list(SIGNAL_COLUMNS))

    rows: list[dict[str, Any]] = []
    for wave in eligible.sort_values(
        ["wave_start_date", "episode_id", "wave_number"], kind="stable"
    ).to_dict("records"):
        symbol = str(wave["vt_symbol"])
        features = stock_features.get(symbol)
        if features is None:
            raise ValueError(f"missing stock bars for confirmed wave: {symbol}")
        rows.extend(_replay_confirmed_wave(wave, features, concept_index))
    if not rows:
        return pd.DataFrame(columns=list(SIGNAL_COLUMNS))
    result = pd.DataFrame.from_records(rows, columns=list(SIGNAL_COLUMNS))
    if result["signal_id"].duplicated().any():
        raise ValueError("confirmed pullback signal identities must be unique")
    return result.sort_values(
        ["signal_date", "episode_id", "wave_number", "signal_mode"],
        kind="stable",
    ).reset_index(drop=True)


def build_confirmed_pullback_trades(
    signals: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    round_trip_cost_pct: float = ROUND_TRIP_COST_PCT,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Enter after the close signal and apply the frozen structural exits."""

    if round_trip_cost_pct < 0:
        raise ValueError("round-trip cost cannot be negative")
    _require_columns(
        signals,
        (
            "signal_id",
            "episode_id",
            "vt_symbol",
            "signal_mode",
            "signal_date",
            "reference_peak_price",
            "observation_end",
        ),
        "confirmed pullback signal",
    )
    if signals.empty:
        return pd.DataFrame(), pd.DataFrame()
    signal_frame = signals.copy()
    for column in ("signal_date", "observation_end"):
        signal_frame[column] = pd.to_datetime(
            signal_frame[column], errors="raise"
        ).dt.normalize()
    features_by_symbol = _stock_features_by_symbol(stock_bars)
    trades: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for signal in signal_frame.sort_values(
        ["signal_date", "signal_id"], kind="stable"
    ).to_dict("records"):
        features = features_by_symbol.get(str(signal["vt_symbol"]))
        if features is None:
            raise ValueError(
                f"missing stock bars for signal: {signal['vt_symbol']}"
            )
        trade, exclusion = _execute_signal(
            signal,
            features,
            round_trip_cost_pct=round_trip_cost_pct,
        )
        if exclusion is not None:
            exclusions.append(exclusion)
        elif trade is not None:
            trades.append(trade)
    return (
        pd.DataFrame.from_records(trades),
        pd.DataFrame.from_records(exclusions),
    )


def summarize_confirmed_pullback_trades(
    trades: pd.DataFrame,
    group_column: str,
) -> pd.DataFrame:
    """Summarize closed rows while retaining censor coverage."""

    if trades.empty or group_column not in trades:
        return pd.DataFrame(columns=_summary_columns())
    rows: list[dict[str, Any]] = []
    for group, grouped in trades.groupby(group_column, dropna=False, sort=True):
        rows.append(
            {
                "group": _json_safe(group),
                **_trade_metrics(grouped),
            }
        )
    return pd.DataFrame.from_records(rows, columns=_summary_columns())


def evaluate_confirmed_pullback_candidate(
    trades: pd.DataFrame,
) -> dict[str, Any]:
    """Apply the predeclared reused-history nomination gate."""

    _require_columns(
        trades,
        ("signal_mode", "primary_eligible", "time_block", "exit_date"),
        "confirmed pullback trade",
    )
    primary = trades.loc[
        trades["signal_mode"].eq("stabilized_reclaim")
        & trades["primary_eligible"].astype(bool)
    ].copy()
    pooled = _trade_metrics(primary)
    block_rows = []
    stable_blocks = 0
    for block_number in range(1, 6):
        block = f"block_{block_number}"
        metrics = _trade_metrics(primary.loc[primary["time_block"].eq(block)])
        stable = bool(
            metrics["closed_entries"] >= MIN_BLOCK_CLOSED_TRADES
            and _greater_equal(
                metrics["descriptive_positive_share_pct"],
                MIN_BLOCK_POSITIVE_SHARE_PCT,
            )
            and _greater(metrics["mean_net_return_pct"], 0.0)
        )
        stable_blocks += int(stable)
        block_rows.append({"block": block, **metrics, "stable": stable})

    by_block = {str(row["block"]): row for row in block_rows}
    late_blocks_pass = all(
        bool(
            by_block[block]["closed_entries"] >= MIN_BLOCK_CLOSED_TRADES
            and _greater_equal(
                by_block[block]["descriptive_positive_share_pct"],
                MIN_BLOCK_POSITIVE_SHARE_PCT,
            )
            and _greater(by_block[block]["mean_net_return_pct"], 0.0)
        )
        for block in ("block_4", "block_5")
    )
    candidate = bool(
        pooled["closed_entries"] >= MIN_PRIMARY_CLOSED_TRADES
        and _greater(
            pooled["descriptive_positive_share_pct"],
            MIN_POOLED_POSITIVE_SHARE_PCT,
        )
        and _greater(pooled["mean_net_return_pct"], 0.0)
        and _greater_equal(pooled["profit_factor"], MIN_PROFIT_FACTOR)
        and late_blocks_pass
        and stable_blocks >= MIN_STABLE_BLOCKS
    )
    return {
        "primary_definition": (
            "wave_3/stabilized_reclaim/concept_main_rise_intact/"
            "stock_structure_intact/non_climax"
        ),
        "minimum_primary_closed_trades": MIN_PRIMARY_CLOSED_TRADES,
        "minimum_block_closed_trades": MIN_BLOCK_CLOSED_TRADES,
        "minimum_pooled_positive_share_pct_strict": (
            MIN_POOLED_POSITIVE_SHARE_PCT
        ),
        "minimum_block_positive_share_pct": MIN_BLOCK_POSITIVE_SHARE_PCT,
        "minimum_profit_factor": MIN_PROFIT_FACTOR,
        "minimum_stable_blocks": MIN_STABLE_BLOCKS,
        "pooled": pooled,
        "blocks": block_rows,
        "stable_blocks": stable_blocks,
        "late_blocks_pass": late_blocks_pass,
        "candidate_for_new_forward_block": candidate,
    }


def build_confirmed_multi_wave_pullback_report(
    *,
    result: ConfirmedPullbackResult,
    coverage: Mapping[str, Any],
    fingerprints: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a reused-history report with formal metrics quarantined."""

    candidate_gate = evaluate_confirmed_pullback_candidate(result.trades)
    primary = _primary_trades(result.trades)
    report = {
        "study_version": STUDY_VERSION,
        "research_status": (
            "exploratory_candidate_requires_new_forward_block"
            if candidate_gate["candidate_for_new_forward_block"]
            else "no_confirmed_multi_wave_pullback_edge"
        ),
        "validation_status": "reused_history_not_validation",
        "formal_strategy": False,
        "formal_metrics": {
            "win_rate_pct": None,
            "average_net_return_pct": None,
            "compounded_return_pct": None,
            "profit_factor": None,
            "maximum_drawdown_pct": None,
        },
        "membership_evidence": EVIDENCE_LEVEL,
        "signal_contract": {
            "minimum_confirmed_higher_highs": MIN_CONFIRMED_HIGHER_HIGHS,
            "minimum_causal_pullback_pct": MIN_PULLBACK_PCT,
            "support_approach_tolerance_pct": APPROACH_TOLERANCE_PCT,
            "signal_modes": list(SIGNAL_MODES),
            "stabilization": (
                "close_at_or_above_deepest_tested_support_and_not_below_prior_close"
            ),
            "concept_main_rise": (
                "breakout_trend_in_cycle_and_same_day_sustain_qualifies"
            ),
            "stock_structure": (
                "no_close_below_ma20_and_no_second_below_ma10_with_ma5_lte_ma10"
            ),
            "primary": candidate_gate["primary_definition"],
            "feature_cutoff": "signal_session_close",
        },
        "trade_contract": {
            "entry": "next_session_open_after_close_signal",
            "gap_rejection": "entry_open_at_or_above_reference_peak",
            "target_exit": "first_later_high_above_reference_peak_then_close",
            "defensive_exit": "second_consecutive_close_below_ma20_then_close",
            "right_censor": "no_price_fallback_at_episode_boundary",
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
        },
        "candidate_gate": _json_safe(candidate_gate),
        "coverage": {
            **dict(coverage),
            "confirmed_signal_rows": int(len(result.signals)),
            "confirmed_signal_episodes": _nunique(result.signals, "episode_id"),
            "confirmed_signal_symbols": _nunique(result.signals, "vt_symbol"),
            "confirmed_signal_dates": _nunique(result.signals, "signal_date"),
            "next_open_trade_rows": int(len(result.trades)),
            "trade_exclusion_rows": int(len(result.exclusions)),
            "primary_trade_rows": int(len(primary)),
            "primary_closed_rows": int(primary["exit_date"].notna().sum())
            if "exit_date" in primary
            else 0,
        },
        "signal_mode_summary": _records(
            summarize_confirmed_pullback_trades(result.trades, "signal_mode")
        ),
        "primary_funnel_summary": _funnel_summary(result.trades),
        "primary_block_summary": _records(
            summarize_confirmed_pullback_trades(primary, "time_block")
        ),
        "primary_support_summary": _records(
            summarize_confirmed_pullback_trades(primary, "support_line")
        ),
        "primary_support_block_summary": _trade_matrix_summary(
            primary,
            "support_line",
        ),
        "primary_volume_summary": _records(
            summarize_confirmed_pullback_trades(
                primary, "volume_class_prior5"
            )
        ),
        "primary_volume_block_summary": _trade_matrix_summary(
            primary,
            "volume_class_prior5",
        ),
        "primary_wave_summary": _records(
            summarize_confirmed_pullback_trades(primary, "wave_bucket")
        ),
        "primary_exit_summary": _records(
            summarize_confirmed_pullback_trades(
                primary, "executable_exit_reason"
            )
        ),
        "representative_cases": _representative_cases(result.trades),
        "boundaries": [
            "all five chronological blocks were viewed in prior wave studies",
            "current concept membership is a survivorship proxy",
            "causal Top3 failed the prior absolute identity gate",
            "wave outcome and trade return never select a signal",
            "right-censored trades are excluded from return denominators",
            "descriptive positive share is not formal low-suction win rate",
        ],
        "fingerprints": _json_safe(dict(fingerprints)),
        "signal_ledger": _records(result.signals),
        "trade_ledger": _records(result.trades),
        "trade_exclusions": _records(result.exclusions),
        "reproduce": (
            "legacy CLI retired; use the daily-factor-* commands for current "
            "low-suction research"
        ),
    }
    return _json_safe(report)


def render_confirmed_pullback_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_confirmed_pullback_markdown(report: Mapping[str, Any]) -> str:
    coverage = _mapping(report.get("coverage"))
    gate = _mapping(report.get("candidate_gate"))
    pooled = _mapping(gate.get("pooled"))
    lines = [
        "# AlphaAgent 确认多浪后的回调低吸研究",
        "",
        f"研究状态：`{report.get('research_status')}`；验证边界："
        f"`{report.get('validation_status')}`。",
        "正式 Top3、低吸胜率、收益、复利：`null`。",
        "",
        "## Coverage",
        "",
        f"- 因果信号：`{coverage.get('confirmed_signal_rows', 0)}`；股票 "
        f"`{coverage.get('confirmed_signal_symbols', 0)}`；信号日 "
        f"`{coverage.get('confirmed_signal_dates', 0)}`。",
        f"- 次日开盘路径：`{coverage.get('next_open_trade_rows', 0)}`；"
        f"入场剔除 `{coverage.get('trade_exclusion_rows', 0)}`。",
        f"- 冻结主组：`{coverage.get('primary_trade_rows', 0)}`；闭合 "
        f"`{coverage.get('primary_closed_rows', 0)}`。",
        "",
        "## Frozen Primary",
        "",
        "- 第二个更高高点已经确认后才开始观察。",
        "- 先出现点时可见的 5% 回调，再等收回最深已测试均线且收盘不低于前收。",
        "- 信号日概念主升与个股结构均完整，并排除冻结的旭光高潮组合。",
        "- D 收盘确认，D+1 开盘买；越过前峰或连续两日收盘低于 MA20 后收盘卖。",
        "",
        "## Primary Result",
        "",
        f"- 闭合 `{pooled.get('closed_entries', 0)}`；成本后为正比例 "
        f"`{_pct(pooled.get('descriptive_positive_share_pct'))}`。",
        f"- 单笔均值/中位数 `{_pct(pooled.get('mean_net_return_pct'))}` / "
        f"`{_pct(pooled.get('median_net_return_pct'))}`；利润因子 "
        f"`{_number(pooled.get('profit_factor'))}`。",
        f"- MAE 中位数 `{_pct(pooled.get('median_mae_pct'))}`；稳定块 "
        f"`{gate.get('stable_blocks', 0)}/5`；候选门 "
        f"`{gate.get('candidate_for_new_forward_block')}`。",
        "",
        "## Funnel",
        "",
        "| Stage | Entries | Closed | Positive | Mean net | PF | Higher high | False exits |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_summary_lines(report.get("primary_funnel_summary")),
        "",
        "## Time Blocks",
        "",
        "| Block | Entries | Closed | Positive | Mean net | PF | Higher high | False exits |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_summary_lines(report.get("primary_block_summary")),
        "",
        "## Support",
        "",
        "| Support | Entries | Closed | Positive | Mean net | PF | Higher high | False exits |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_summary_lines(report.get("primary_support_summary")),
        "",
        "## Support By Block",
        "",
        "下表只检查时间集中，不能改变冻结候选门。",
        "",
        "| Support | Block | Entries | Closed | Positive | Mean net | PF |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        *_matrix_summary_lines(report.get("primary_support_block_summary")),
        "",
        "## Volume",
        "",
        "| Volume | Entries | Closed | Positive | Mean net | PF | Higher high | False exits |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_summary_lines(report.get("primary_volume_summary")),
        "",
        "## Volume By Block",
        "",
        "| Volume | Block | Entries | Closed | Positive | Mean net | PF |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        *_matrix_summary_lines(report.get("primary_volume_block_summary")),
        "",
        "## Cases",
        "",
        *_case_lines(report.get("representative_cases")),
        "",
        "## Boundaries",
        "",
        *[f"- {item}" for item in _sequence(report.get("boundaries"))],
        "",
        "## Reproduce",
        "",
        "```bash",
        str(report.get("reproduce") or ""),
        "```",
    ]
    return "\n".join(lines).rstrip() + "\n"


def run_confirmed_multi_wave_pullback_study() -> dict[str, Any]:
    """Run the frozen confirmed-wave study on the existing proxy episodes."""

    from .concept_cycles import build_cycle_candidates, load_cycle_research_inputs
    from .research_protocol import fingerprint_frame
    from .true_leader_study import (
        build_emotion_cycle_candidates,
        build_point_in_time_stock_features,
        load_true_leader_study_inputs,
        rank_causal_cycle_leaders,
    )

    inputs = load_true_leader_study_inputs(include_reference_bars=False)
    cycle_inputs = load_cycle_research_inputs()
    if tuple(cycle_inputs.split.discovery_dates) != tuple(inputs.trading_dates):
        raise ValueError("confirmed-wave study calendars must match")
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
    episodes, path_exclusions = filter_complete_episode_paths(
        selected_episodes,
        inputs.stock_bars,
        trading_dates=inputs.trading_dates,
    )
    replay = replay_leader_wave_episodes(episodes, inputs.stock_bars)
    concept_states = build_cycle_candidates(
        cycle_inputs.concept_bars,
        cycle_inputs.market_returns,
    )
    signals = build_confirmed_multi_wave_signals(
        episodes,
        replay["waves"],
        inputs.stock_bars,
        concept_states,
    )
    trades, trade_exclusions = build_confirmed_pullback_trades(
        signals,
        inputs.stock_bars,
    )
    result = ConfirmedPullbackResult(
        signals=signals,
        trades=trades,
        exclusions=trade_exclusions,
    )
    coverage = {
        **inputs.coverage,
        "causal_rank_rows": int(len(causal_ranks)),
        "selected_episode_rows": int(len(selected_episodes)),
        "complete_episode_rows": int(len(episodes)),
        "incomplete_episode_path_exclusions": int(len(path_exclusions)),
        "wave_rows": int(len(replay["waves"])),
        "eligible_wave_3_plus_rows": int(
            pd.to_numeric(replay["waves"]["wave_number"], errors="coerce")
            .sub(1)
            .ge(MIN_CONFIRMED_HIGHER_HIGHS)
            .sum()
        ),
        "concept_state_rows": int(
            concept_states["definition"].eq("breakout_trend").sum()
        ),
    }
    generated_fingerprints = {
        "confirmed_wave_episodes": fingerprint_frame(
            episodes,
            identity_columns=("episode_id",),
        ).as_dict(),
        "confirmed_wave_ledger": fingerprint_frame(
            replay["waves"],
            identity_columns=("episode_id", "wave_number"),
        ).as_dict(),
        "confirmed_pullback_signals": fingerprint_frame(
            signals,
            identity_columns=("signal_id",),
        ).as_dict(),
        "confirmed_pullback_trades": fingerprint_frame(
            trades,
            identity_columns=("signal_id",),
        ).as_dict(),
    }
    if not trade_exclusions.empty:
        generated_fingerprints["confirmed_pullback_trade_exclusions"] = (
            fingerprint_frame(
                trade_exclusions,
                identity_columns=("signal_id",),
            ).as_dict()
        )
    return build_confirmed_multi_wave_pullback_report(
        result=result,
        coverage=coverage,
        fingerprints={**inputs.fingerprints, **generated_fingerprints},
    )


def _prepare_episodes(episodes: pd.DataFrame) -> pd.DataFrame:
    _require_columns(episodes, EPISODE_COLUMNS, "confirmed wave episode")
    frame = episodes.loc[:, list(EPISODE_COLUMNS)].copy()
    frame["episode_id"] = frame["episode_id"].astype(str)
    frame["vt_symbol"] = frame["vt_symbol"].astype(str)
    for column in ("anchor_date", "observation_end"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.normalize()
    if frame["episode_id"].duplicated().any():
        raise ValueError("confirmed wave episode IDs must be unique")
    return frame


def _prepare_waves(waves: pd.DataFrame) -> pd.DataFrame:
    required = ("episode_id", "wave_number", "wave_start_date", "observation_end")
    _require_columns(waves, required, "confirmed wave ledger")
    frame = waves.loc[:, list(required)].copy()
    frame["episode_id"] = frame["episode_id"].astype(str)
    frame["wave_number"] = pd.to_numeric(
        frame["wave_number"], errors="raise"
    ).astype(int)
    for column in ("wave_start_date", "observation_end"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.normalize()
    if frame.duplicated(["episode_id", "wave_number"]).any():
        raise ValueError("confirmed wave identities must be unique")
    return frame


def _stock_features_by_symbol(stock_bars: pd.DataFrame) -> dict[str, pd.DataFrame]:
    _require_columns(
        stock_bars,
        (
            "vt_symbol",
            "trade_date",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
        ),
        "stock daily bar",
    )
    bars = stock_bars.copy()
    bars["vt_symbol"] = bars["vt_symbol"].astype(str)
    bars["trade_date"] = pd.to_datetime(
        bars["trade_date"], errors="raise"
    ).dt.normalize()
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock daily bar identities must be unique")
    return {
        str(symbol): build_stock_wave_features(
            group.drop(columns=["vt_symbol"], errors="ignore")
        )
        for symbol, group in bars.groupby("vt_symbol", sort=False)
    }


def _prepare_concept_state_index(
    concept_states: pd.DataFrame,
) -> dict[tuple[str, pd.Timestamp], dict[str, Any]]:
    required = (
        "sector_id",
        "trade_date",
        "definition",
        "in_cycle",
        "sustain_qualifies",
        "cycle_id",
    )
    _require_columns(concept_states, required, "concept cycle state")
    frame = concept_states.loc[:, list(required)].copy()
    frame = frame.loc[frame["definition"].astype(str).eq("breakout_trend")]
    frame["sector_id"] = frame["sector_id"].astype(str)
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    if frame.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("breakout concept state identities must be unique")
    return {
        (str(row["sector_id"]), pd.Timestamp(row["trade_date"])): row
        for row in frame.to_dict("records")
    }


def _replay_confirmed_wave(
    wave: Mapping[str, Any],
    features: pd.DataFrame,
    concept_index: Mapping[tuple[str, pd.Timestamp], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    wave_start = pd.Timestamp(wave["wave_start_date"])
    boundary = pd.Timestamp(wave["observation_end_wave"])
    window = features.loc[
        features["trade_date"].between(wave_start, boundary)
    ].reset_index(drop=True)
    if window.empty or pd.Timestamp(window.iloc[0]["trade_date"]) != wave_start:
        raise ValueError("confirmed wave start must have one stock bar")
    record_peak = float(window.iloc[0]["high_price"])
    peak_date = wave_start
    confirmation_date: pd.Timestamp | None = None
    confirmation_low_pct: float | None = None
    deepest_support: str | None = None
    first_approach_date: pd.Timestamp | None = None
    emitted: dict[str, dict[str, Any]] = {}

    for position in range(1, len(window)):
        bar = window.iloc[position]
        trade_date = pd.Timestamp(bar["trade_date"])
        high = float(bar["high_price"])
        low = float(bar["low_price"])
        if confirmation_date is None:
            if high > record_peak:
                record_peak = high
                peak_date = trade_date
            if (
                trade_date > peak_date
                and low <= record_peak * (1.0 - MIN_PULLBACK_PCT / 100.0)
            ):
                confirmation_date = trade_date
                confirmation_low_pct = (low / record_peak - 1.0) * 100.0
            else:
                continue
        elif high > record_peak:
            break

        approached = _approached_supports(bar)
        if approached:
            deepest_today = max(approached, key=SUPPORT_DEPTH.__getitem__)
            if first_approach_date is None:
                first_approach_date = trade_date
                emitted["first_approach"] = _signal_row(
                    wave,
                    window,
                    bar,
                    signal_mode="first_approach",
                    confirmation_date=confirmation_date,
                    confirmation_low_pct=confirmation_low_pct,
                    first_approach_date=first_approach_date,
                    peak_date=peak_date,
                    peak_price=record_peak,
                    support_line=deepest_today,
                    concept_index=concept_index,
                )
            if (
                deepest_support is None
                or SUPPORT_DEPTH[deepest_today] > SUPPORT_DEPTH[deepest_support]
            ):
                deepest_support = deepest_today

        if deepest_support is not None and "stabilized_reclaim" not in emitted:
            previous_close = float(window.iloc[position - 1]["close_price"])
            support_price = _finite_or_none(bar[deepest_support])
            stabilized = bool(
                support_price is not None
                and float(bar["close_price"]) >= support_price
                and float(bar["close_price"]) >= previous_close
            )
            if stabilized:
                emitted["stabilized_reclaim"] = _signal_row(
                    wave,
                    window,
                    bar,
                    signal_mode="stabilized_reclaim",
                    confirmation_date=confirmation_date,
                    confirmation_low_pct=confirmation_low_pct,
                    first_approach_date=first_approach_date,
                    peak_date=peak_date,
                    peak_price=record_peak,
                    support_line=deepest_support,
                    concept_index=concept_index,
                )
        if len(emitted) == len(SIGNAL_MODES):
            break
    return [emitted[mode] for mode in SIGNAL_MODES if mode in emitted]


def _approached_supports(bar: pd.Series) -> list[str]:
    approached = []
    for support_line in SUPPORT_DEPTH:
        support = _finite_or_none(bar[support_line])
        if (
            support is not None
            and float(bar["low_price"])
            <= support * (1.0 + APPROACH_TOLERANCE_PCT / 100.0)
        ):
            approached.append(support_line)
    return approached


def _signal_row(
    wave: Mapping[str, Any],
    window: pd.DataFrame,
    bar: pd.Series,
    *,
    signal_mode: str,
    confirmation_date: pd.Timestamp,
    confirmation_low_pct: float | None,
    first_approach_date: pd.Timestamp | None,
    peak_date: pd.Timestamp,
    peak_price: float,
    support_line: str,
    concept_index: Mapping[tuple[str, pd.Timestamp], Mapping[str, Any]],
) -> dict[str, Any]:
    signal_date = pd.Timestamp(bar["trade_date"])
    support_price = float(bar[support_line])
    before = window.loc[window["trade_date"].le(signal_date)]
    signal_position = int(before.index[-1])
    previous_close = (
        float(window.iloc[signal_position - 1]["close_price"])
        if signal_position > 0
        else float(bar["close_price"])
    )
    impulse = window.loc[
        window["trade_date"].between(
            pd.Timestamp(wave["wave_start_date"]), peak_date
        )
    ]
    start_close = float(impulse.iloc[0]["close_price"])
    impulse_gain = (peak_price / start_close - 1.0) * 100.0
    strong_days = int(impulse["daily_return_pct"].ge(9.5).sum())
    max_volume = _finite_or_none(impulse["volume_ratio_prior5"].max())
    impulse_volume = _finite_or_none(impulse["volume"].median())
    volume_ratio_impulse = (
        float(bar["volume"]) / impulse_volume
        if impulse_volume is not None and impulse_volume > 0
        else None
    )
    structural_intact = _stock_structure_intact(
        window,
        peak_date=peak_date,
        signal_date=signal_date,
    )
    concept = concept_index.get((str(wave["sector_id"]), signal_date))
    concept_available = concept is not None
    concept_cycle_active = bool(concept.get("in_cycle", False)) if concept else False
    concept_trend_order = (
        bool(concept.get("sustain_qualifies", False)) if concept else False
    )
    concept_main_rise = concept_cycle_active and concept_trend_order
    climax = classify_xuguang_climax(impulse_gain, strong_days, max_volume)
    close_price = float(bar["close_price"])
    primary = bool(
        signal_mode == "stabilized_reclaim"
        and int(wave["wave_number"]) == 3
        and concept_main_rise
        and structural_intact
        and not climax
    )
    row = {column: wave.get(column) for column in EPISODE_COLUMNS}
    row.update(
        {
            "signal_id": (
                f"{wave['episode_id']}:wave-{int(wave['wave_number'])}:"
                f"{signal_mode}:{signal_date.date().isoformat()}"
            ),
            "signal_mode": signal_mode,
            "wave_number": int(wave["wave_number"]),
            "wave_bucket": _wave_bucket(int(wave["wave_number"])),
            "confirmed_higher_highs_at_wave_start": int(wave["wave_number"]) - 1,
            "wave_start_date": pd.Timestamp(wave["wave_start_date"]),
            "pullback_confirmation_date": confirmation_date,
            "first_support_approach_date": first_approach_date,
            "signal_date": signal_date,
            "reference_peak_date": peak_date,
            "reference_peak_price": peak_price,
            "support_line": support_line,
            "support_depth": SUPPORT_DEPTH[support_line],
            "support_price": support_price,
            "line_distance_low_pct": (
                float(bar["low_price"]) / support_price - 1.0
            )
            * 100.0,
            "line_distance_close_pct": (close_price / support_price - 1.0)
            * 100.0,
            "close_reclaimed_support": bool(close_price >= support_price),
            "signal_close_not_below_previous": bool(close_price >= previous_close),
            "signal_daily_return_pct": _finite_or_none(bar["daily_return_pct"]),
            "signal_close_to_peak_pct": (close_price / peak_price - 1.0)
            * 100.0,
            "pullback_confirmation_low_to_peak_pct": confirmation_low_pct,
            "volume_ratio_prior5": _finite_or_none(bar["volume_ratio_prior5"]),
            "volume_ratio_impulse": volume_ratio_impulse,
            "volume_class_prior5": classify_volume_ratio(
                bar["volume_ratio_prior5"]
            ),
            "volume_class_impulse": classify_volume_ratio(volume_ratio_impulse),
            "impulse_gain_pct": impulse_gain,
            "strong_days_ge_9_5pct": strong_days,
            "max_volume_ratio_prior5": max_volume,
            "xuguang_climax_candidate": climax,
            "stock_structure_intact": structural_intact,
            "concept_state_available": concept_available,
            "concept_cycle_active": concept_cycle_active,
            "concept_trend_order": concept_trend_order,
            "concept_main_rise_intact": concept_main_rise,
            "concept_active_cycle_id": (
                str(concept.get("cycle_id"))
                if concept and concept.get("cycle_id") is not None
                else None
            ),
            "primary_eligible": primary,
            "feature_cutoff_date": signal_date,
        }
    )
    return row


def _wave_bucket(wave_number: int) -> str:
    if wave_number <= 3:
        return f"wave_{wave_number}"
    return "wave_4_plus"


def _stock_structure_intact(
    window: pd.DataFrame,
    *,
    peak_date: pd.Timestamp,
    signal_date: pd.Timestamp,
) -> bool:
    path = window.loc[
        window["trade_date"].gt(peak_date)
        & window["trade_date"].le(signal_date)
    ].copy()
    if path.empty:
        return True
    below_ma10 = path["close_price"].lt(path["ma10"]).fillna(False)
    structural_break = path["close_price"].lt(path["ma20"]).fillna(False) | (
        below_ma10
        & below_ma10.shift(1, fill_value=False)
        & path["ma5"].le(path["ma10"]).fillna(False)
    )
    return not bool(structural_break.any())


def _execute_signal(
    signal: Mapping[str, Any],
    features: pd.DataFrame,
    *,
    round_trip_cost_pct: float,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    signal_date = pd.Timestamp(signal["signal_date"])
    boundary = pd.Timestamp(signal["observation_end"])
    after_signal = features.loc[
        features["trade_date"].gt(signal_date)
        & features["trade_date"].le(boundary)
    ].reset_index(drop=True)
    if after_signal.empty:
        return None, _trade_exclusion(signal, "next_session_open_unavailable")
    entry = after_signal.iloc[0]
    entry_date = pd.Timestamp(entry["trade_date"])
    entry_price = float(entry["open_price"])
    peak_price = float(signal["reference_peak_price"])
    if entry_price >= peak_price:
        return None, _trade_exclusion(signal, "opportunity_gone_at_entry")

    target_matches = after_signal.loc[after_signal["high_price"].gt(peak_price)]
    target = target_matches.iloc[0] if not target_matches.empty else None
    defense_path = features.loc[
        features["trade_date"].ge(signal_date)
        & features["trade_date"].le(boundary)
    ].copy()
    below_ma20 = defense_path["close_price"].lt(defense_path["ma20"]).fillna(False)
    second_below = below_ma20 & below_ma20.shift(1, fill_value=False)
    defense_matches = defense_path.loc[
        defense_path["trade_date"].ge(entry_date) & second_below
    ]
    defensive = defense_matches.iloc[0] if not defense_matches.empty else None
    exit_row, exit_reason = _first_exit(target, defensive)
    metrics = _next_open_path_metrics(
        after_signal,
        entry_date=entry_date,
        entry_price=entry_price,
        exit_row=exit_row,
        round_trip_cost_pct=round_trip_cost_pct,
    )
    target_date = (
        pd.Timestamp(target["trade_date"]) if target is not None else pd.NaT
    )
    defensive_date = (
        pd.Timestamp(defensive["trade_date"]) if defensive is not None else pd.NaT
    )
    false_exit = bool(
        exit_reason == "two_closes_below_ma20"
        and target is not None
        and pd.Timestamp(defensive["trade_date"]) < target_date
    )
    trade = dict(signal)
    trade.update(
        {
            "trade_id": f"next-open:{signal['signal_id']}",
            "entry_date": entry_date,
            "entry_price": entry_price,
            "entry_proxy": "next_session_open_after_close_signal",
            "executable_exit_reason": exit_reason,
            **metrics,
            "eventually_made_higher_high": target is not None,
            "unrestricted_higher_high_date": target_date,
            "unrestricted_higher_high_close": (
                float(target["close_price"]) if target is not None else None
            ),
            "unrestricted_return_at_higher_high_close_pct": (
                (float(target["close_price"]) / entry_price - 1.0) * 100.0
                - round_trip_cost_pct
                if target is not None
                else None
            ),
            "defensive_exit_date": defensive_date,
            "defensive_exit_preceded_later_higher_high": false_exit,
            "round_trip_cost_pct": round_trip_cost_pct,
        }
    )
    return trade, None


def _trade_exclusion(
    signal: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "signal_id": str(signal["signal_id"]),
        "episode_id": str(signal["episode_id"]),
        "vt_symbol": str(signal["vt_symbol"]),
        "signal_mode": str(signal["signal_mode"]),
        "signal_date": pd.Timestamp(signal["signal_date"]),
        "exclusion_reason": reason,
    }


def _first_exit(
    target: pd.Series | None,
    defensive: pd.Series | None,
) -> tuple[pd.Series | None, str]:
    if target is None and defensive is None:
        return None, "right_censored"
    if target is None:
        return defensive, "two_closes_below_ma20"
    if defensive is None:
        return target, "higher_high_confirmed"
    if pd.Timestamp(target["trade_date"]) <= pd.Timestamp(defensive["trade_date"]):
        return target, "higher_high_confirmed"
    return defensive, "two_closes_below_ma20"


def _next_open_path_metrics(
    path: pd.DataFrame,
    *,
    entry_date: pd.Timestamp,
    entry_price: float,
    exit_row: pd.Series | None,
    round_trip_cost_pct: float,
) -> dict[str, Any]:
    if exit_row is None:
        return {
            "exit_date": pd.NaT,
            "exit_price": None,
            "holding_sessions": None,
            "gross_return_pct": None,
            "net_return_pct": None,
            "maximum_adverse_excursion_pct": None,
            "maximum_favorable_excursion_pct": None,
        }
    exit_date = pd.Timestamp(exit_row["trade_date"])
    observed = path.loc[
        path["trade_date"].ge(entry_date) & path["trade_date"].le(exit_date)
    ]
    entry_position = int(path.index[path["trade_date"].eq(entry_date)][0])
    exit_position = int(path.index[path["trade_date"].eq(exit_date)][0])
    exit_price = float(exit_row["close_price"])
    gross_return = (exit_price / entry_price - 1.0) * 100.0
    return {
        "exit_date": exit_date,
        "exit_price": exit_price,
        "holding_sessions": exit_position - entry_position,
        "gross_return_pct": gross_return,
        "net_return_pct": gross_return - round_trip_cost_pct,
        "maximum_adverse_excursion_pct": min(
            0.0,
            (float(observed["low_price"].min()) / entry_price - 1.0) * 100.0,
        ),
        "maximum_favorable_excursion_pct": max(
            0.0,
            (float(observed["high_price"].max()) / entry_price - 1.0) * 100.0,
        ),
    }


def _trade_metrics(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {
            "episodes": 0,
            "entries": 0,
            "closed_entries": 0,
            "censored_entries": 0,
            "positive_closed_entries": 0,
            "descriptive_positive_share_pct": None,
            "mean_net_return_pct": None,
            "median_net_return_pct": None,
            "profit_factor": None,
            "median_mae_pct": None,
            "median_holding_sessions": None,
            "eventual_higher_high_share_pct": None,
            "defensive_exit_preceded_later_higher_high": 0,
        }
    closed = trades.loc[
        trades["exit_date"].notna()
        & pd.to_numeric(trades["net_return_pct"], errors="coerce").notna()
    ].copy()
    returns = pd.to_numeric(closed["net_return_pct"], errors="coerce").dropna()
    positive = returns.gt(0)
    gains = returns.loc[returns.gt(0)].sum()
    losses = returns.loc[returns.lt(0)].sum()
    profit_factor = (
        float(gains / abs(losses))
        if losses < 0
        else None
    )
    eventual = trades.get(
        "eventually_made_higher_high", pd.Series(False, index=trades.index)
    ).astype(bool)
    false_exits = trades.get(
        "defensive_exit_preceded_later_higher_high",
        pd.Series(False, index=trades.index),
    ).astype(bool)
    return {
        "episodes": _nunique(trades, "episode_id"),
        "entries": int(len(trades)),
        "closed_entries": int(len(closed)),
        "censored_entries": int(len(trades) - len(closed)),
        "positive_closed_entries": int(positive.sum()),
        "descriptive_positive_share_pct": (
            float(positive.mean() * 100.0) if len(positive) else None
        ),
        "mean_net_return_pct": _mean(returns),
        "median_net_return_pct": _median(returns),
        "profit_factor": profit_factor,
        "median_mae_pct": _median(
            pd.to_numeric(
                closed.get(
                    "maximum_adverse_excursion_pct",
                    pd.Series(dtype=float),
                ),
                errors="coerce",
            )
        ),
        "median_holding_sessions": _median(
            pd.to_numeric(
                closed.get("holding_sessions", pd.Series(dtype=float)),
                errors="coerce",
            )
        ),
        "eventual_higher_high_share_pct": float(eventual.mean() * 100.0),
        "defensive_exit_preceded_later_higher_high": int(false_exits.sum()),
    }


def _summary_columns() -> list[str]:
    return ["group", *_trade_metrics(pd.DataFrame()).keys()]


def _primary_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    return trades.loc[
        trades["signal_mode"].eq("stabilized_reclaim")
        & trades["primary_eligible"].astype(bool)
    ].copy()


def _funnel_summary(trades: pd.DataFrame) -> list[dict[str, Any]]:
    if trades.empty:
        return []
    stabilized = trades.loc[
        trades["signal_mode"].eq("stabilized_reclaim")
        & pd.to_numeric(trades["wave_number"], errors="coerce").eq(3)
    ]
    concept = stabilized.loc[stabilized["concept_main_rise_intact"].astype(bool)]
    structure = concept.loc[concept["stock_structure_intact"].astype(bool)]
    primary = structure.loc[
        ~structure["xuguang_climax_candidate"].astype(bool)
    ]
    return [
        {"group": "wave_3_stabilized", **_trade_metrics(stabilized)},
        {"group": "concept_main_rise_intact", **_trade_metrics(concept)},
        {"group": "stock_and_concept_intact", **_trade_metrics(structure)},
        {"group": "primary_non_climax", **_trade_metrics(primary)},
    ]


def _trade_matrix_summary(
    trades: pd.DataFrame,
    group_column: str,
) -> list[dict[str, Any]]:
    if trades.empty or group_column not in trades or "time_block" not in trades:
        return []
    rows = []
    for (group, block), grouped in trades.groupby(
        [group_column, "time_block"],
        dropna=False,
        sort=True,
    ):
        rows.append(
            {
                "group": _json_safe(group),
                "time_block": _json_safe(block),
                **_trade_metrics(grouped),
            }
        )
    return _json_safe(rows)


def _representative_cases(trades: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    primary = _primary_trades(trades)
    closed = primary.loc[primary.get("exit_date", pd.Series(dtype=object)).notna()]
    columns = (
        "episode_id",
        "vt_symbol",
        "stock_name",
        "concept_name",
        "wave_number",
        "signal_date",
        "support_line",
        "entry_date",
        "entry_price",
        "exit_date",
        "executable_exit_reason",
        "net_return_pct",
        "maximum_adverse_excursion_pct",
    )
    if closed.empty:
        return {"winners": [], "losers": []}
    winners = closed.loc[closed["net_return_pct"].gt(0)].sort_values(
        ["signal_date", "episode_id"], kind="stable"
    )
    losers = closed.loc[closed["net_return_pct"].le(0)].sort_values(
        ["signal_date", "episode_id"], kind="stable"
    )
    return {
        "winners": _records(winners.loc[:, list(columns)].head(5)),
        "losers": _records(losers.loc[:, list(columns)].head(5)),
    }


def _summary_lines(raw: object) -> list[str]:
    lines = []
    for item in _sequence(raw):
        row = _mapping(item)
        lines.append(
            f"| `{row.get('group')}` | {row.get('entries', 0)} | "
            f"{row.get('closed_entries', 0)} | "
            f"{_pct(row.get('descriptive_positive_share_pct'))} | "
            f"{_pct(row.get('mean_net_return_pct'))} | "
            f"{_number(row.get('profit_factor'))} | "
            f"{_pct(row.get('eventual_higher_high_share_pct'))} | "
            f"{row.get('defensive_exit_preceded_later_higher_high', 0)} |"
        )
    return lines or ["| - | 0 | 0 | - | - | - | - | 0 |"]


def _matrix_summary_lines(raw: object) -> list[str]:
    lines = []
    for item in _sequence(raw):
        row = _mapping(item)
        lines.append(
            f"| `{row.get('group')}` | `{row.get('time_block')}` | "
            f"{row.get('entries', 0)} | {row.get('closed_entries', 0)} | "
            f"{_pct(row.get('descriptive_positive_share_pct'))} | "
            f"{_pct(row.get('mean_net_return_pct'))} | "
            f"{_number(row.get('profit_factor'))} |"
        )
    return lines or ["| - | - | 0 | 0 | - | - | - |"]


def _case_lines(raw: object) -> list[str]:
    cases = _mapping(raw)
    lines = []
    for label, key in (("成功", "winners"), ("失败", "losers")):
        for item in _sequence(cases.get(key)):
            row = _mapping(item)
            lines.append(
                f"- {label}：{row.get('stock_name')} `{row.get('vt_symbol')}`，"
                f"第 {row.get('wave_number')} 浪，{row.get('signal_date')} "
                f"`{row.get('support_line')}`，成本后 "
                f"`{_pct(row.get('net_return_pct'))}`。"
            )
    return lines or ["- 无闭合主组案例。"]


def _nunique(frame: pd.DataFrame, column: str) -> int:
    return int(frame[column].nunique()) if column in frame else 0


def _mean(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.mean()) if not numeric.empty else None


def _median(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.median()) if not numeric.empty else None


def _greater(value: object, threshold: float) -> bool:
    numeric = _finite_or_none(value)
    return bool(numeric is not None and numeric > threshold)


def _greater_equal(value: object, threshold: float) -> bool:
    numeric = _finite_or_none(value)
    return bool(numeric is not None and numeric >= threshold)


def _finite_or_none(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


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


def _pct(value: object) -> str:
    numeric = _finite_or_none(value)
    return f"{numeric:.4f}%" if numeric is not None else "-"


def _number(value: object) -> str:
    numeric = _finite_or_none(value)
    return f"{numeric:.4f}" if numeric is not None else "-"


def _require_columns(
    frame: pd.DataFrame,
    required: Sequence[str],
    label: str,
) -> None:
    missing = sorted(set(required) - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
