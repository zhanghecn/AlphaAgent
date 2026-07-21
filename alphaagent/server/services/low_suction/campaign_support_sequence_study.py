"""Campaign-wide daily support sequence and D+1 failure research."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .confirmed_multi_wave_pullback_study import build_campaign_support_signals
from .research_protocol import fingerprint_frame
from .stock_wave_pullbacks import build_stock_wave_features


STUDY_VERSION = "campaign-support-sequence-d1-v1"
RESEARCH_STATUS = "reused_history_campaign_sequence_not_formal_validation"
EXECUTION_ASSUMPTION = "same_close_research_proxy"
ROUND_TRIP_COST_PCT = 0.2
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CROSS_LEADER_REPORT_PATH = (
    REPOSITORY_ROOT
    / "memory/06_backtests/low_suction_cross_leader_wave_study_20260718.json"
)
CROSS_LEADER_REPORT_SHA256 = (
    "04a882562377ced2b0b7d9c5f76ab9ccc7fc176ec0ae3fe35af814960d641df6"
)
SUPPORT_ZONES = (
    "ma5_near",
    "ma5_ma10_band",
    "ma10_ma20_band",
    "below_ma20",
)
OPPORTUNITY_COLUMNS = (
    "signal_id",
    "signal_mode",
    "episode_id",
    "vt_symbol",
    "signal_date",
    "first_support_approach_date",
    "observation_end",
    "reference_peak_price",
    "wave_number",
)


def classify_support_zone(
    low: float,
    *,
    ma5: float,
    ma10: float,
    ma20: float,
) -> str:
    """Classify the pullback low by the moving-average interval it reached."""

    values = (low, ma5, ma10, ma20)
    if not all(math.isfinite(float(value)) for value in values):
        return "unavailable"
    if low >= ma5:
        return "ma5_near"
    if low >= ma10:
        return "ma5_ma10_band"
    if low >= ma20:
        return "ma10_ma20_band"
    return "below_ma20"


def build_campaign_opportunity_ledger(
    signals: pd.DataFrame,
    daily_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Number stabilized support opportunities across each complete campaign."""

    _require_columns(signals, OPPORTUNITY_COLUMNS, "campaign support signal")
    features_by_symbol = _features_by_symbol(daily_bars)
    stabilized = signals.loc[
        signals["signal_mode"].astype(str).eq("stabilized_reclaim")
    ].copy()
    if stabilized.empty:
        return pd.DataFrame()
    if stabilized["signal_id"].astype(str).duplicated().any():
        raise ValueError("campaign support signal IDs must be unique")

    rows = [
        _opportunity_row(signal, features_by_symbol)
        for signal in stabilized.to_dict("records")
    ]
    ledger = pd.DataFrame.from_records(rows).sort_values(
        ["episode_id", "signal_date", "campaign_wave_number", "signal_id"],
        kind="stable",
    )
    ledger["campaign_opportunity_ordinal"] = (
        ledger.groupby("episode_id", sort=False).cumcount() + 1
    )
    ledger["campaign_opportunity_bucket"] = ledger[
        "campaign_opportunity_ordinal"
    ].map(_opportunity_bucket)
    ledger["campaign_wave_bucket"] = ledger["campaign_wave_number"].map(
        _wave_bucket
    )
    return ledger.sort_values(
        ["signal_date", "episode_id", "campaign_opportunity_ordinal"],
        kind="stable",
    ).reset_index(drop=True)


def build_campaign_close_trades(
    opportunities: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    round_trip_cost_pct: float = ROUND_TRIP_COST_PCT,
) -> pd.DataFrame:
    """Compare structural and D+1 exits from the stabilization-day close."""

    if round_trip_cost_pct < 0:
        raise ValueError("round-trip cost cannot be negative")
    _require_columns(
        opportunities,
        (
            "signal_id",
            "episode_id",
            "vt_symbol",
            "signal_date",
            "observation_end",
            "reference_peak_price",
            "signal_close_price",
            "d1_date",
            "d1_close_price",
            "d1_not_up",
            "d1_not_up_and_below_ma5",
        ),
        "campaign opportunity",
    )
    if opportunities.empty:
        return pd.DataFrame()
    features_by_symbol = _features_by_symbol(daily_bars)
    rows = [
        _close_trade_row(opportunity, features_by_symbol, round_trip_cost_pct)
        for opportunity in opportunities.to_dict("records")
    ]
    return pd.DataFrame.from_records(rows).sort_values(
        ["signal_date", "episode_id", "campaign_opportunity_ordinal"],
        kind="stable",
    ).reset_index(drop=True)


def build_case_daily_path(
    case_trades: pd.DataFrame,
    daily_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Build an auditable daily path with peak, signal, and D+1 roles."""

    _require_columns(
        case_trades,
        (
            "episode_id",
            "vt_symbol",
            "anchor_date",
            "reference_peak_date",
            "campaign_wave_number",
            "signal_date",
            "campaign_opportunity_ordinal",
            "d1_date",
            "d1_not_up_and_below_ma5",
        ),
        "daily case trade",
    )
    if case_trades.empty:
        return pd.DataFrame()
    if case_trades["episode_id"].astype(str).nunique() != 1:
        raise ValueError("daily case path requires exactly one campaign episode")
    if case_trades["vt_symbol"].astype(str).nunique() != 1:
        raise ValueError("daily case path requires exactly one stock")

    symbol = str(case_trades.iloc[0]["vt_symbol"])
    features = _features_by_symbol(daily_bars).get(symbol)
    if features is None:
        raise ValueError(f"missing daily bars for case path: {symbol}")
    start = pd.to_datetime(case_trades["anchor_date"], errors="raise").min()
    d1_dates = pd.to_datetime(case_trades["d1_date"], errors="coerce").dropna()
    end = (
        d1_dates.max()
        if not d1_dates.empty
        else pd.to_datetime(case_trades["signal_date"], errors="raise").max()
    )
    annotations: dict[pd.Timestamp, list[str]] = {}
    for trade in case_trades.sort_values("signal_date").to_dict("records"):
        wave_number = int(trade["campaign_wave_number"])
        ordinal = int(trade["campaign_opportunity_ordinal"])
        peak_date = pd.Timestamp(trade["reference_peak_date"]).normalize()
        signal_date = pd.Timestamp(trade["signal_date"]).normalize()
        annotations.setdefault(peak_date, []).append(
            f"wave_{wave_number}_reference_peak"
        )
        annotations.setdefault(signal_date, []).append(
            f"opportunity_{ordinal}_stabilization"
        )
        if bool(trade["d1_not_up_and_below_ma5"]):
            d1_date = pd.Timestamp(trade["d1_date"]).normalize()
            annotations.setdefault(d1_date, []).append(
                f"opportunity_{ordinal}_d1_failure"
            )

    rows = []
    for _, bar in features.loc[features["trade_date"].between(start, end)].iterrows():
        trade_date = pd.Timestamp(bar["trade_date"])
        labels = list(annotations.get(trade_date, []))
        if any(label.endswith("_reference_peak") for label in labels):
            low_to_ma5 = _distance_pct(bar["low_price"], bar["ma5"])
            if low_to_ma5 is not None and low_to_ma5 <= 5.0:
                labels.append("peak_day_low_within_5pct_of_ma5_observation")
        rows.append(
            {
                "trade_date": trade_date,
                "open_price": float(bar["open_price"]),
                "high_price": float(bar["high_price"]),
                "low_price": float(bar["low_price"]),
                "close_price": float(bar["close_price"]),
                "daily_return_pct": _finite_or_none(bar["daily_return_pct"]),
                "ma5": _finite_or_none(bar["ma5"]),
                "ma10": _finite_or_none(bar["ma10"]),
                "ma20": _finite_or_none(bar["ma20"]),
                "low_to_ma5_pct": _distance_pct(bar["low_price"], bar["ma5"]),
                "close_to_ma5_pct": _distance_pct(
                    bar["close_price"], bar["ma5"]
                ),
                "annotations": ";".join(labels),
            }
        )
    return pd.DataFrame.from_records(rows)


def build_campaign_support_sequence_report(
    *,
    candidates: pd.DataFrame,
    episodes: pd.DataFrame,
    waves: pd.DataFrame,
    opportunities: pd.DataFrame,
    trades: pd.DataFrame,
    input_fingerprints: Mapping[str, Any],
    case_daily_path: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build reused-history evidence without promoting a live strategy."""

    baseline_summary = _baseline_summaries(trades)
    main_rise_trades = trades.loc[trades["main_rise_intact"].astype(bool)].copy()
    case_episode_ids = set(candidates["episode_id"].astype(str))
    case_trades = trades.loc[
        trades["episode_id"].astype(str).isin(case_episode_ids)
    ].copy()
    report = {
        "study_version": STUDY_VERSION,
        "research_status": RESEARCH_STATUS,
        "validation_status": "reused_history_not_forward_validation",
        "formal_strategy": False,
        "formal_metrics": None,
        "predeclared_hypotheses": {
            "campaign_sequence": (
                "support opportunities are numbered continuously from the structured "
                "leader campaign anchor and never reset after a higher high"
            ),
            "first_opportunity": "first stabilization is expected near MA5",
            "second_opportunity": (
                "second stabilization may enter the MA5-MA10 band and reclaim MA5"
            ),
            "d1_not_up": "D+1 close is less than or equal to the entry-day close",
            "d1_not_up_and_below_ma5": (
                "D+1 is not up and its close is below its completed MA5"
            ),
        },
        "contract": {
            "primary_episode_selector": (
                "all outcome-neutral causal Top3 campaign anchors in the structured "
                "dynamic episode manifest"
            ),
            "case_overlay": "frozen 35 leader-MA5 wave-3 candidate episode IDs",
            "episode_anchor_source": "structured dynamic_episode_manifest.anchor_date",
            "bar_interval": "1d",
            "minute_bars_used": False,
            "fund_cycle_used": False,
            "concept_daily_cycle_used": True,
            "entry": "stabilization_day_close",
            "entry_execution_assumption": EXECUTION_ASSUMPTION,
            "point_in_time_executable": False,
            "baseline_exit": (
                "first later reference-peak rebreak or second consecutive close below "
                "MA20, executed at trigger-day close"
            ),
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
        },
        "coverage": {
            "frozen_candidate_rows": int(len(candidates)),
            "campaign_episodes": int(episodes["episode_id"].nunique()),
            "causal_campaign_episodes": int(episodes["episode_id"].nunique()),
            "frozen_case_campaigns": int(len(case_episode_ids)),
            "campaign_wave_rows": int(len(waves)),
            "stabilized_opportunities": int(len(opportunities)),
            "closed_baseline_trades": int(
                trades["baseline_net_return_pct"].notna().sum()
            ),
            "d1_observed_rows": int(trades["d1_close_price"].notna().sum()),
            "main_rise_opportunities": int(len(main_rise_trades)),
            "minute_rows_read": 0,
            "fund_cycle_rows_read": 0,
        },
        "baseline_summary": baseline_summary,
        "main_rise_summary": _baseline_summaries(main_rise_trades),
        "selected_case_summary": _baseline_summaries(case_trades),
        "d1_exit_comparison": {
            "d1_not_up": _variant_comparison(trades, "d1_not_up"),
            "d1_not_up_and_below_ma5": _variant_comparison(
                trades,
                "d1_not_up_and_below_ma5",
            ),
        },
        "main_rise_d1_exit_comparison": {
            "d1_not_up": _variant_comparison(main_rise_trades, "d1_not_up"),
            "d1_not_up_and_below_ma5": _variant_comparison(
                main_rise_trades,
                "d1_not_up_and_below_ma5",
            ),
        },
        "selected_case_d1_exit_comparison": {
            "d1_not_up": _variant_comparison(case_trades, "d1_not_up"),
            "d1_not_up_and_below_ma5": _variant_comparison(
                case_trades,
                "d1_not_up_and_below_ma5",
            ),
        },
        "zhongjing_case": _records(
            case_trades.loc[
                case_trades["vt_symbol"].astype(str).eq("002579.SZSE")
            ]
        ),
        "zhongjing_daily_path": _records(
            case_daily_path if case_daily_path is not None else pd.DataFrame()
        ),
        "individual_opportunity_ledger": _records(trades),
        "input_fingerprints": dict(input_fingerprints),
        "boundaries": [
            "the 35 episode selectors and their outcomes were already viewed",
            "same-close signal confirmation and entry is a research proxy, not a fill",
            "support zones describe the observed daily low relative to completed MAs",
            "D+1 variants were compared on winners and losers, including false exits",
            "current concept membership and causal Top3 identity remain proxy evidence",
            "no API, UI, paper portfolio, or live strategy rule is changed by this study",
        ],
        "reproduce": (
            "docker compose run --rm --no-deps "
            "-v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api "
            "python -m alphaagent.server.services.low_suction.cli "
            "v2-campaign-support-sequence-study --format markdown"
        ),
    }
    return report


def render_campaign_support_sequence_json(report: Mapping[str, Any]) -> str:
    """Render deterministic machine-readable evidence."""

    return json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=_json_default,
    ) + "\n"


def render_campaign_support_sequence_markdown(report: Mapping[str, Any]) -> str:
    """Render the campaign sequence and D+1 comparison for human audit."""

    coverage = _mapping(report.get("coverage"), "coverage")
    baseline = _mapping(report.get("baseline_summary"), "baseline summary")
    all_metrics = _mapping(baseline.get("all"), "baseline all")
    lines = [
        "# AlphaAgent Campaign Support Sequence And D+1 Failure Study",
        "",
        f"Research status: `{report['research_status']}`.",
        "Formal strategy/metrics: `false/null`.",
        "",
        "## Coverage",
        "",
        f"- Frozen case candidates/primary causal campaigns: "
        f"`{coverage['frozen_candidate_rows']}/{coverage['campaign_episodes']}`.",
        f"- Campaign waves/stabilized opportunities: `{coverage['campaign_wave_rows']}/"
        f"{coverage['stabilized_opportunities']}`.",
        f"- Baseline closed/D+1 observed: `{coverage['closed_baseline_trades']}/"
        f"{coverage['d1_observed_rows']}`.",
        f"- Signal-day concept and stock main-rise opportunities: "
        f"`{coverage['main_rise_opportunities']}`.",
        "- Minute/fund-cycle rows read: `0/0`.",
        "",
        "## Baseline",
        "",
        f"- Higher-high success: `{_percent(all_metrics.get('higher_high_success_rate_pct'))}`.",
        f"- Positive return: `{_percent(all_metrics.get('positive_return_rate_pct'))}`.",
        f"- Mean return/PF: `{_percent(all_metrics.get('mean_net_return_pct'))}` / "
        f"`{_decimal(all_metrics.get('profit_factor'))}`.",
        f"- Overlap-ignored compound/drawdown: "
        f"`{_percent(all_metrics.get('compounded_return_pct'))}` / "
        f"`{_percent(all_metrics.get('maximum_drawdown_pct'))}`.",
        "",
        "## Campaign opportunity",
        "",
        "| Opportunity | N | Higher high | Positive | Mean | PF | Compound | Drawdown |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in baseline.get("by_campaign_opportunity_ordinal", []):
        metrics = _mapping(row, "opportunity summary")
        lines.append(_metric_table_row(metrics))
    lines.extend(
        [
            "",
            "## Support zone",
            "",
            "| Zone | N | Higher high | Positive | Mean | PF | Compound | Drawdown |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in baseline.get("by_support_zone", []):
        lines.append(_metric_table_row(_mapping(row, "support summary")))
    lines.extend(
        [
            "",
            "## Signal-day main rise intact",
            "",
            "This subset requires both the concept daily cycle and the stock structure "
            "to remain intact on the completed signal day.",
            "",
            "| Opportunity | N | Higher high | Positive | Mean | PF | Compound | Drawdown |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    main_rise = _mapping(report.get("main_rise_summary"), "main-rise summary")
    for row in main_rise.get("by_campaign_opportunity_ordinal", []):
        lines.append(_metric_table_row(_mapping(row, "main-rise opportunity summary")))
    lines.extend(
        [
            "",
            "## Frozen 35-case overlay",
            "",
            "This overlay is conditioned on campaigns that later reached the old "
            "wave-3 candidate and is not a causal win-rate estimate.",
            "",
            "| Opportunity | N | Higher high | Positive | Mean | PF | Compound | Drawdown |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    selected = _mapping(report.get("selected_case_summary"), "selected case summary")
    for row in selected.get("by_campaign_opportunity_ordinal", []):
        lines.append(_metric_table_row(_mapping(row, "selected opportunity summary")))
    lines.extend(["", "## D+1 Exit Comparison", ""])
    comparisons = _mapping(report.get("d1_exit_comparison"), "D+1 comparison")
    for key, label in (
        ("d1_not_up", "D+1 not up"),
        ("d1_not_up_and_below_ma5", "D+1 not up and below MA5"),
    ):
        comparison = _mapping(comparisons.get(key), key)
        lines.append(
            f"- {label}: triggered `{comparison['triggered_trades']}`, rescued losers "
            f"`{comparison['rescued_baseline_losers']}`, harmed winners "
            f"`{comparison['harmed_baseline_winners']}`, false exits before later "
            f"higher high `{comparison['false_exits_before_later_higher_high']}`, "
            f"mean delta `{_percent(comparison.get('mean_net_return_delta_pct'))}`."
        )
    lines.extend(
        [
            "",
            "### Frozen 35-case strict D+1 by opportunity",
            "",
            "| Opportunity | Triggered | Rescued losers | Harmed winners | False exits | "
            "Mean delta |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    selected_comparisons = _mapping(
        report.get("selected_case_d1_exit_comparison"),
        "selected case D+1 comparison",
    )
    selected_strict = _mapping(
        selected_comparisons.get("d1_not_up_and_below_ma5"),
        "selected strict D+1 comparison",
    )
    for item in selected_strict.get("by_campaign_opportunity_ordinal", []):
        row = _mapping(item, "selected strict opportunity comparison")
        lines.append(
            f"| {row.get('group')} | {row.get('triggered_trades')} | "
            f"{row.get('rescued_baseline_losers')} | "
            f"{row.get('harmed_baseline_winners')} | "
            f"{row.get('false_exits_before_later_higher_high')} | "
            f"{_percent(row.get('mean_net_return_delta_pct'))} |"
        )
    lines.extend(
        [
            "",
            "## Zhongjing Electronics",
            "",
            "| Signal | Opportunity | Wave | Zone | Test low | MA5 | MA10 | D+1 | "
            "D+1 below MA5 | Higher high | Baseline | D+1 strict |",
            "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | --- | "
            "---: | ---: |",
        ]
    )
    for case in report.get("zhongjing_case", []):
        row = _mapping(case, "Zhongjing case")
        lines.append(
            f"| {_date_text(row.get('signal_date'))} | "
            f"{row.get('campaign_opportunity_ordinal')} | "
            f"{row.get('campaign_wave_number')} | {row.get('support_zone')} | "
            f"{_decimal(row.get('support_test_low'))} | "
            f"{_decimal(row.get('support_test_ma5'))} | "
            f"{_decimal(row.get('support_test_ma10'))} | "
            f"{_decimal(row.get('d1_close_price'))} | "
            f"{bool(row.get('d1_close_below_ma5'))} | "
            f"{bool(row.get('eventually_made_higher_high'))} | "
            f"{_percent(row.get('baseline_net_return_pct'))} | "
            f"{_percent(row.get('d1_not_up_and_below_ma5_net_return_pct'))} |"
        )
    lines.extend(
        [
            "",
            "### Daily path",
            "",
            "| Date | Open | High | Low | Close | Return | MA5 | MA10 | Low/MA5 | Role |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for item in report.get("zhongjing_daily_path", []):
        row = _mapping(item, "Zhongjing daily path")
        lines.append(
            f"| {_date_text(row.get('trade_date'))} | {_decimal(row.get('open_price'))} | "
            f"{_decimal(row.get('high_price'))} | {_decimal(row.get('low_price'))} | "
            f"{_decimal(row.get('close_price'))} | "
            f"{_percent(row.get('daily_return_pct'))} | {_decimal(row.get('ma5'))} | "
            f"{_decimal(row.get('ma10'))} | {_percent(row.get('low_to_ma5_pct'))} | "
            f"{row.get('annotations') or ''} |"
        )
    lines.extend(["", "## Boundaries", ""])
    lines.extend(f"- {item}" for item in report.get("boundaries", []))
    lines.extend(
        [
            "",
            "## Reproduce",
            "",
            "```bash",
            str(report["reproduce"]),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def load_frozen_campaign_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """Load all causal campaigns plus the frozen 35-case overlay."""

    from .leader_ma5_scheme_study import load_frozen_scheme_candidates

    raw = CROSS_LEADER_REPORT_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != CROSS_LEADER_REPORT_SHA256:
        raise ValueError(f"cross-leader report fingerprint changed: {digest}")
    report = json.loads(raw.decode("utf-8"))
    if report.get("study_version") != "cross-leader-wave-pattern-v1":
        raise ValueError("unexpected cross-leader study version")

    candidates = load_frozen_scheme_candidates()
    episode_manifest = pd.DataFrame.from_records(
        report.get("dynamic_episode_manifest") or []
    )
    wave_ledger = pd.DataFrame.from_records(report.get("dynamic_wave_ledger") or [])
    _require_columns(
        episode_manifest,
        ("episode_id", "anchor_date", "observation_end", "vt_symbol"),
        "structured campaign manifest",
    )
    _require_columns(
        wave_ledger,
        ("episode_id", "wave_number", "wave_start_date", "observation_end"),
        "structured campaign wave ledger",
    )
    episodes = episode_manifest.copy()
    if episodes["episode_id"].astype(str).duplicated().any():
        raise ValueError("structured campaign episode IDs must be unique")
    candidate_episode_ids = set(candidates["episode_id"].astype(str))
    observed_episode_ids = set(episodes["episode_id"].astype(str))
    if not candidate_episode_ids.issubset(observed_episode_ids):
        missing = sorted(candidate_episode_ids - observed_episode_ids)
        raise ValueError(
            "frozen candidate episode is absent from structured manifest: "
            + ", ".join(missing)
        )
    waves = wave_ledger.copy()
    if waves.duplicated(["episode_id", "wave_number"]).any():
        raise ValueError("structured campaign wave identities must be unique")
    if set(waves["episode_id"].astype(str)) != observed_episode_ids:
        raise ValueError("structured campaign is missing its wave ledger")
    daily_bars = _load_campaign_daily_bars(episodes)
    return candidates, episodes, waves, daily_bars


def run_campaign_support_sequence_study() -> dict[str, Any]:
    """Replay all causal campaigns and retain the frozen 35-case overlay."""

    from .concept_cycles import build_cycle_candidates, load_cycle_research_inputs

    candidates, episodes, waves, daily_bars = load_frozen_campaign_inputs()
    cycle_inputs = load_cycle_research_inputs()
    concept_states = build_cycle_candidates(
        cycle_inputs.concept_bars,
        cycle_inputs.market_returns,
    )
    signals = build_campaign_support_signals(
        episodes,
        waves,
        daily_bars,
        concept_states,
    )
    opportunities = build_campaign_opportunity_ledger(signals, daily_bars)
    trades = build_campaign_close_trades(opportunities, daily_bars)
    zhongjing_episode_ids = set(
        candidates.loc[
            candidates["vt_symbol"].astype(str).eq("002579.SZSE"),
            "episode_id",
        ].astype(str)
    )
    zhongjing_trades = trades.loc[
        trades["episode_id"].astype(str).isin(zhongjing_episode_ids)
    ].copy()
    case_daily_path = build_case_daily_path(zhongjing_trades, daily_bars)
    fingerprints = {
        "cross_leader_report": {
            "algorithm": "sha256",
            "digest": f"sha256:{CROSS_LEADER_REPORT_SHA256}",
        },
        "candidates": fingerprint_frame(
            candidates,
            identity_columns=("signal_id",),
        ).as_dict(),
        "episodes": fingerprint_frame(
            episodes,
            identity_columns=("episode_id",),
        ).as_dict(),
        "waves": fingerprint_frame(
            waves,
            identity_columns=("episode_id", "wave_number"),
        ).as_dict(),
        "daily_bars": fingerprint_frame(
            daily_bars,
            identity_columns=("vt_symbol", "trade_date"),
        ).as_dict(),
        "concept_states": fingerprint_frame(
            concept_states,
            identity_columns=("sector_id", "trade_date", "definition"),
        ).as_dict(),
        "opportunities": fingerprint_frame(
            opportunities,
            identity_columns=("signal_id",),
        ).as_dict(),
        "trades": fingerprint_frame(
            trades,
            identity_columns=("signal_id",),
        ).as_dict(),
    }
    return build_campaign_support_sequence_report(
        candidates=candidates,
        episodes=episodes,
        waves=waves,
        opportunities=opportunities,
        trades=trades,
        input_fingerprints=fingerprints,
        case_daily_path=case_daily_path,
    )


def _load_campaign_daily_bars(episodes: pd.DataFrame) -> pd.DataFrame:
    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    symbols = tuple(sorted(episodes["vt_symbol"].astype(str).unique()))
    anchors = pd.to_datetime(episodes["anchor_date"], errors="raise")
    boundaries = pd.to_datetime(episodes["observation_end"], errors="raise")
    load_start = anchors.min().date() - timedelta(days=120)
    load_end = boundaries.max().date()
    frames = []
    for offset in range(0, len(symbols), 400):
        chunk = symbols[offset : offset + 400]
        statement = (
            select(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.trade_date,
                schema.stock_daily_bars.c.open_price,
                schema.stock_daily_bars.c.high_price,
                schema.stock_daily_bars.c.low_price,
                schema.stock_daily_bars.c.close_price,
                schema.stock_daily_bars.c.volume,
                schema.stock_daily_bars.c.turnover,
            )
            .where(
                schema.stock_daily_bars.c.vt_symbol.in_(chunk),
                schema.stock_daily_bars.c.trade_date.between(load_start, load_end),
            )
            .order_by(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.trade_date,
            )
        )
        frames.append(
            pd.read_sql(
                statement,
                get_engine(),
                parse_dates=["trade_date"],
            )
        )
    bars = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    observed_symbols = set(bars["vt_symbol"].astype(str)) if not bars.empty else set()
    missing_symbols = sorted(set(symbols) - observed_symbols)
    if missing_symbols:
        raise ValueError(
            "campaign daily bars are missing symbols: " + ", ".join(missing_symbols)
        )
    return bars


def _trade_metrics(frame: pd.DataFrame, return_column: str) -> dict[str, Any]:
    if frame.empty:
        return _empty_metrics()
    _require_columns(
        frame,
        (return_column, "eventually_made_higher_high", "signal_date"),
        "campaign trade metrics",
    )
    ordered = frame.sort_values(["signal_date", "signal_id"], kind="stable")
    returns = pd.to_numeric(ordered[return_column], errors="coerce").dropna()
    successes = ordered["eventually_made_higher_high"].astype(bool)
    gains = returns.loc[returns.gt(0)]
    losses = returns.loc[returns.le(0)]
    loss_total = float(-losses.sum())
    profit_factor = float(gains.sum()) / loss_total if loss_total > 0 else None
    return {
        "signals": int(len(ordered)),
        "closed_trades": int(len(returns)),
        "higher_high_successes": int(successes.sum()),
        "higher_high_success_rate_pct": float(successes.mean() * 100.0),
        "winning_trades": int(returns.gt(0).sum()),
        "positive_return_rate_pct": (
            float(returns.gt(0).mean() * 100.0) if not returns.empty else None
        ),
        "mean_net_return_pct": (
            float(returns.mean()) if not returns.empty else None
        ),
        "median_net_return_pct": (
            float(returns.median()) if not returns.empty else None
        ),
        "profit_factor": profit_factor,
        "compounded_return_pct": _compound_return(returns),
        "maximum_drawdown_pct": _maximum_drawdown(returns),
        "best_net_return_pct": float(returns.max()) if not returns.empty else None,
        "worst_net_return_pct": float(returns.min()) if not returns.empty else None,
    }


def _baseline_summaries(trades: pd.DataFrame) -> dict[str, Any]:
    return {
        "all": _trade_metrics(trades, "baseline_net_return_pct"),
        "by_campaign_opportunity_ordinal": _group_metrics(
            trades,
            "campaign_opportunity_bucket",
            "baseline_net_return_pct",
        ),
        "by_campaign_wave_number": _group_metrics(
            trades,
            "campaign_wave_bucket",
            "baseline_net_return_pct",
        ),
        "by_support_zone": _group_metrics(
            trades,
            "support_zone",
            "baseline_net_return_pct",
        ),
        "by_opportunity_and_support": _cross_group_metrics(
            trades,
            ("campaign_opportunity_bucket", "support_zone"),
            "baseline_net_return_pct",
        ),
    }


def _group_metrics(
    frame: pd.DataFrame,
    group_column: str,
    return_column: str,
) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows = []
    for group, grouped in frame.groupby(group_column, dropna=False, sort=True):
        rows.append(
            {
                "group": _json_safe(group),
                **_trade_metrics(grouped, return_column),
            }
        )
    return rows


def _cross_group_metrics(
    frame: pd.DataFrame,
    group_columns: tuple[str, ...],
    return_column: str,
) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows = []
    for group, grouped in frame.groupby(
        list(group_columns),
        dropna=False,
        sort=True,
    ):
        values = group if isinstance(group, tuple) else (group,)
        rows.append(
            {
                **{
                    column: _json_safe(value)
                    for column, value in zip(group_columns, values, strict=True)
                },
                **_trade_metrics(grouped, return_column),
            }
        )
    return rows


def _variant_comparison(
    frame: pd.DataFrame,
    prefix: str,
    *,
    include_groups: bool = True,
) -> dict[str, Any]:
    trigger_column = f"{prefix}_exit_triggered"
    return_column = f"{prefix}_net_return_pct"
    false_exit_column = f"{prefix}_false_exit_before_higher_high"
    _require_columns(
        frame,
        (
            "baseline_net_return_pct",
            trigger_column,
            return_column,
            false_exit_column,
        ),
        "D+1 variant comparison",
    )
    baseline = pd.to_numeric(frame["baseline_net_return_pct"], errors="coerce")
    variant = pd.to_numeric(frame[return_column], errors="coerce")
    triggered = frame[trigger_column].astype(bool)
    paired = baseline.notna() & variant.notna()
    baseline_losers = triggered & baseline.le(0)
    baseline_winners = triggered & baseline.gt(0)
    deltas = variant.loc[paired] - baseline.loc[paired]
    metrics = _trade_metrics(frame, return_column)
    result = {
        "triggered_trades": int(triggered.sum()),
        "trigger_rate_pct": float(triggered.mean() * 100.0),
        "triggered_baseline_losers": int(baseline_losers.sum()),
        "rescued_baseline_losers": int(
            (baseline_losers & variant.gt(baseline)).sum()
        ),
        "baseline_losers_converted_to_winners": int(
            (baseline_losers & variant.gt(0)).sum()
        ),
        "triggered_baseline_winners": int(baseline_winners.sum()),
        "harmed_baseline_winners": int(
            (baseline_winners & variant.lt(baseline)).sum()
        ),
        "false_exits_before_later_higher_high": int(
            frame[false_exit_column].astype(bool).sum()
        ),
        "mean_net_return_delta_pct": (
            float(deltas.mean()) if not deltas.empty else None
        ),
        "worst_net_return_delta_pct": (
            float(deltas.min()) if not deltas.empty else None
        ),
        "variant_metrics": metrics,
    }
    if include_groups:
        result["by_campaign_opportunity_ordinal"] = [
            {
                "group": _json_safe(group),
                **_variant_comparison(
                    grouped,
                    prefix,
                    include_groups=False,
                ),
            }
            for group, grouped in frame.groupby(
                "campaign_opportunity_bucket",
                dropna=False,
                sort=True,
            )
        ]
    return result


def _empty_metrics() -> dict[str, Any]:
    return {
        "signals": 0,
        "closed_trades": 0,
        "higher_high_successes": 0,
        "higher_high_success_rate_pct": None,
        "winning_trades": 0,
        "positive_return_rate_pct": None,
        "mean_net_return_pct": None,
        "median_net_return_pct": None,
        "profit_factor": None,
        "compounded_return_pct": None,
        "maximum_drawdown_pct": None,
        "best_net_return_pct": None,
        "worst_net_return_pct": None,
    }


def _compound_return(returns: pd.Series) -> float | None:
    if returns.empty:
        return None
    return float(((1.0 + returns / 100.0).prod() - 1.0) * 100.0)


def _maximum_drawdown(returns: pd.Series) -> float | None:
    if returns.empty:
        return None
    equity = (1.0 + returns / 100.0).cumprod()
    equity = pd.concat([pd.Series([1.0]), equity.reset_index(drop=True)], ignore_index=True)
    drawdowns = equity / equity.cummax() - 1.0
    return float(drawdowns.min() * 100.0)


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {key: _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _json_safe(value: object) -> Any:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(value).date().isoformat()
    if isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    if hasattr(value, "item"):
        return _json_safe(value.item())
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _json_default(value: object) -> Any:
    safe = _json_safe(value)
    if safe is value:
        raise TypeError(f"cannot serialize {type(value).__name__}")
    return safe


def _opportunity_bucket(value: object) -> str:
    ordinal = int(value)
    return f"opportunity_{ordinal}" if ordinal <= 3 else "opportunity_4_plus"


def _wave_bucket(value: object) -> str:
    wave_number = int(value)
    return f"wave_{wave_number}" if wave_number <= 3 else "wave_4_plus"


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _metric_table_row(metrics: Mapping[str, Any]) -> str:
    return (
        f"| {metrics.get('group')} | {metrics.get('signals')} | "
        f"{_percent(metrics.get('higher_high_success_rate_pct'))} | "
        f"{_percent(metrics.get('positive_return_rate_pct'))} | "
        f"{_percent(metrics.get('mean_net_return_pct'))} | "
        f"{_decimal(metrics.get('profit_factor'))} | "
        f"{_percent(metrics.get('compounded_return_pct'))} | "
        f"{_percent(metrics.get('maximum_drawdown_pct'))} |"
    )


def _percent(value: object) -> str:
    numeric = _finite_or_none(value)
    return "n/a" if numeric is None else f"{numeric:.4f}%"


def _decimal(value: object) -> str:
    numeric = _finite_or_none(value)
    return "n/a" if numeric is None else f"{numeric:.4f}"


def _date_text(value: object) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return pd.Timestamp(value).date().isoformat()


def _opportunity_row(
    signal: Mapping[str, Any],
    features_by_symbol: Mapping[str, pd.DataFrame],
) -> dict[str, Any]:
    symbol = str(signal["vt_symbol"])
    features = features_by_symbol.get(symbol)
    if features is None:
        raise ValueError(f"missing daily bars for campaign signal: {symbol}")
    signal_date = pd.Timestamp(signal["signal_date"]).normalize()
    approach_date = pd.Timestamp(signal["first_support_approach_date"]).normalize()
    observation_end = pd.Timestamp(signal["observation_end"]).normalize()
    signal_bar = _one_bar(features, signal_date, "signal")
    test_window = features.loc[
        features["trade_date"].between(approach_date, signal_date)
    ]
    if test_window.empty:
        raise ValueError("support test window must contain a daily bar")
    test_bar = test_window.loc[test_window["low_price"].idxmin()]
    d1_matches = features.loc[
        features["trade_date"].gt(signal_date)
        & features["trade_date"].le(observation_end)
    ]
    d1_bar = d1_matches.iloc[0] if not d1_matches.empty else None
    signal_close = float(signal_bar["close_price"])
    d1_close = float(d1_bar["close_price"]) if d1_bar is not None else None
    d1_ma5 = _finite_or_none(d1_bar["ma5"]) if d1_bar is not None else None
    d1_not_up = bool(d1_close is not None and d1_close <= signal_close)
    concept_main_rise = _optional_bool(signal.get("concept_main_rise_intact"))
    stock_main_rise = _optional_bool(signal.get("stock_structure_intact"))

    row = dict(signal)
    row.update(
        {
            "signal_date": signal_date,
            "first_support_approach_date": approach_date,
            "observation_end": observation_end,
            "campaign_wave_number": int(signal["wave_number"]),
            "main_rise_state_available": bool(
                concept_main_rise is not None and stock_main_rise is not None
            ),
            "main_rise_intact": bool(concept_main_rise and stock_main_rise),
            "support_test_date": pd.Timestamp(test_bar["trade_date"]),
            "support_test_low": float(test_bar["low_price"]),
            "support_test_ma5": _finite_or_none(test_bar["ma5"]),
            "support_test_ma10": _finite_or_none(test_bar["ma10"]),
            "support_test_ma20": _finite_or_none(test_bar["ma20"]),
            "support_zone": _support_zone_from_bar(test_bar),
            "support_test_low_to_ma5_pct": _distance_pct(
                test_bar["low_price"], test_bar["ma5"]
            ),
            "support_test_low_to_ma10_pct": _distance_pct(
                test_bar["low_price"], test_bar["ma10"]
            ),
            "support_test_low_to_ma20_pct": _distance_pct(
                test_bar["low_price"], test_bar["ma20"]
            ),
            "signal_close_price": signal_close,
            "signal_ma5": _finite_or_none(signal_bar["ma5"]),
            "signal_ma10": _finite_or_none(signal_bar["ma10"]),
            "signal_ma20": _finite_or_none(signal_bar["ma20"]),
            "signal_close_reclaimed_ma5": _greater_equal(
                signal_close, signal_bar["ma5"]
            ),
            "d1_date": (
                pd.Timestamp(d1_bar["trade_date"]) if d1_bar is not None else pd.NaT
            ),
            "d1_close_price": d1_close,
            "d1_ma5": d1_ma5,
            "d1_close_return_pct": (
                (d1_close / signal_close - 1.0) * 100.0
                if d1_close is not None
                else None
            ),
            "d1_not_up": d1_not_up,
            "d1_close_below_ma5": bool(
                d1_close is not None and d1_ma5 is not None and d1_close < d1_ma5
            ),
            "d1_not_up_and_below_ma5": bool(
                d1_not_up
                and d1_ma5 is not None
                and d1_close is not None
                and d1_close < d1_ma5
            ),
        }
    )
    return row


def _close_trade_row(
    opportunity: Mapping[str, Any],
    features_by_symbol: Mapping[str, pd.DataFrame],
    round_trip_cost_pct: float,
) -> dict[str, Any]:
    symbol = str(opportunity["vt_symbol"])
    features = features_by_symbol.get(symbol)
    if features is None:
        raise ValueError(f"missing daily bars for campaign opportunity: {symbol}")
    signal_date = pd.Timestamp(opportunity["signal_date"]).normalize()
    observation_end = pd.Timestamp(opportunity["observation_end"]).normalize()
    path = features.loc[
        features["trade_date"].between(signal_date, observation_end)
    ].reset_index(drop=True)
    if path.empty or pd.Timestamp(path.iloc[0]["trade_date"]) != signal_date:
        raise ValueError("campaign entry date must have one daily bar")

    entry_price = float(opportunity["signal_close_price"])
    target = _first_higher_high(
        path,
        signal_date,
        float(opportunity["reference_peak_price"]),
    )
    defensive = _second_close_below_ma20(path, signal_date)
    baseline_exit, baseline_reason = _first_exit(target, defensive)
    baseline = _exit_metrics(
        path,
        entry_price=entry_price,
        exit_row=baseline_exit,
        round_trip_cost_pct=round_trip_cost_pct,
    )
    target_date = (
        pd.Timestamp(target["trade_date"]) if target is not None else pd.NaT
    )
    d1_row = _optional_bar(path, opportunity.get("d1_date"))
    d1_not_up = _variant_metrics(
        path,
        entry_price=entry_price,
        trigger=bool(opportunity["d1_not_up"]),
        d1_row=d1_row,
        baseline=baseline,
        baseline_reason=baseline_reason,
        target_date=target_date,
        round_trip_cost_pct=round_trip_cost_pct,
    )
    d1_below_ma5 = _variant_metrics(
        path,
        entry_price=entry_price,
        trigger=bool(opportunity["d1_not_up_and_below_ma5"]),
        d1_row=d1_row,
        baseline=baseline,
        baseline_reason=baseline_reason,
        target_date=target_date,
        round_trip_cost_pct=round_trip_cost_pct,
    )
    row = dict(opportunity)
    row.update(
        {
            "entry_date": signal_date,
            "entry_price": entry_price,
            "entry_proxy": "stabilization_day_close_research_proxy",
            "baseline_exit_reason": baseline_reason,
            **{f"baseline_{key}": value for key, value in baseline.items()},
            "eventually_made_higher_high": target is not None,
            "unrestricted_higher_high_date": target_date,
            "round_trip_cost_pct": round_trip_cost_pct,
            **{f"d1_not_up_{key}": value for key, value in d1_not_up.items()},
            **{
                f"d1_not_up_and_below_ma5_{key}": value
                for key, value in d1_below_ma5.items()
            },
        }
    )
    return row


def _variant_metrics(
    path: pd.DataFrame,
    *,
    entry_price: float,
    trigger: bool,
    d1_row: pd.Series | None,
    baseline: Mapping[str, Any],
    baseline_reason: str,
    target_date: pd.Timestamp,
    round_trip_cost_pct: float,
) -> dict[str, Any]:
    if not trigger:
        return {
            "exit_triggered": False,
            "exit_reason": baseline_reason,
            "false_exit_before_higher_high": False,
            **dict(baseline),
        }
    if d1_row is None:
        raise ValueError("D+1 exit trigger requires one D+1 bar")
    metrics = _exit_metrics(
        path,
        entry_price=entry_price,
        exit_row=d1_row,
        round_trip_cost_pct=round_trip_cost_pct,
    )
    d1_date = pd.Timestamp(d1_row["trade_date"])
    return {
        "exit_triggered": True,
        "exit_reason": "d1_close_failure",
        "false_exit_before_higher_high": bool(
            not pd.isna(target_date) and d1_date < target_date
        ),
        **metrics,
    }


def _features_by_symbol(daily_bars: pd.DataFrame) -> dict[str, pd.DataFrame]:
    _require_columns(
        daily_bars,
        (
            "vt_symbol",
            "trade_date",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
        ),
        "campaign daily bar",
    )
    bars = daily_bars.copy()
    bars["vt_symbol"] = bars["vt_symbol"].astype(str)
    bars["trade_date"] = pd.to_datetime(
        bars["trade_date"], errors="raise"
    ).dt.normalize()
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("campaign daily bar identities must be unique")
    return {
        str(symbol): build_stock_wave_features(
            group.drop(columns="vt_symbol", errors="ignore")
        )
        for symbol, group in bars.groupby("vt_symbol", sort=False)
    }


def _first_higher_high(
    path: pd.DataFrame,
    entry_date: pd.Timestamp,
    reference_peak: float,
) -> pd.Series | None:
    matches = path.loc[
        path["trade_date"].gt(entry_date) & path["high_price"].gt(reference_peak)
    ]
    return matches.iloc[0] if not matches.empty else None


def _second_close_below_ma20(
    path: pd.DataFrame,
    entry_date: pd.Timestamp,
) -> pd.Series | None:
    below = path["close_price"].lt(path["ma20"]).fillna(False)
    second = below & below.shift(1, fill_value=False)
    matches = path.loc[path["trade_date"].gt(entry_date) & second]
    return matches.iloc[0] if not matches.empty else None


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


def _exit_metrics(
    path: pd.DataFrame,
    *,
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
    observed = path.loc[path["trade_date"].le(exit_date)]
    exit_price = float(exit_row["close_price"])
    gross_return = (exit_price / entry_price - 1.0) * 100.0
    exit_position = int(path.index[path["trade_date"].eq(exit_date)][0])
    return {
        "exit_date": exit_date,
        "exit_price": exit_price,
        "holding_sessions": exit_position,
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


def _support_zone_from_bar(bar: pd.Series) -> str:
    values = [_finite_or_none(bar[column]) for column in ("low_price", "ma5", "ma10", "ma20")]
    if any(value is None for value in values):
        return "unavailable"
    low, ma5, ma10, ma20 = values
    return classify_support_zone(low, ma5=ma5, ma10=ma10, ma20=ma20)


def _one_bar(features: pd.DataFrame, trade_date: pd.Timestamp, label: str) -> pd.Series:
    matches = features.loc[features["trade_date"].eq(trade_date)]
    if len(matches) != 1:
        raise ValueError(f"{label} date must have one daily bar")
    return matches.iloc[0]


def _optional_bar(
    path: pd.DataFrame,
    trade_date: object,
) -> pd.Series | None:
    if trade_date is None or pd.isna(trade_date):
        return None
    return _one_bar(path, pd.Timestamp(trade_date).normalize(), "D+1")


def _distance_pct(value: object, reference: object) -> float | None:
    numeric = _finite_or_none(value)
    denominator = _finite_or_none(reference)
    if numeric is None or denominator is None or denominator == 0:
        return None
    return (numeric / denominator - 1.0) * 100.0


def _greater_equal(value: object, reference: object) -> bool:
    numeric = _finite_or_none(value)
    denominator = _finite_or_none(reference)
    return bool(
        numeric is not None and denominator is not None and numeric >= denominator
    )


def _finite_or_none(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _optional_bool(value: object) -> bool | None:
    if value is None or pd.isna(value):
        return None
    return bool(value)


def _require_columns(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"{label} missing columns: {', '.join(missing)}")
