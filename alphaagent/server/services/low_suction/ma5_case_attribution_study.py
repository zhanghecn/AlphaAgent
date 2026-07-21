"""Stock-by-stock attribution for the frozen multi-wave MA5 cohort."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY_VERSION = "ma5-case-attribution-v1"
PARENT_REPORT_PATH = (
    Path(__file__).resolve().parents[4]
    / "memory/06_backtests/low_suction_confirmed_multi_wave_pullback_study_20260718.json"
)
PARENT_REPORT_SHA256 = (
    "6b503d1c6eaa19f9cc86cac6aeb16641f72df44031b68b1e28151fa639afa42c"
)
EXPECTED_COHORT_ROWS = 57
MIN_BLOCK_SIDE_ROWS = 3

PARENT_SIGNAL_COLUMNS = (
    "signal_id",
    "episode_id",
    "vt_symbol",
    "stock_name",
    "sector_id",
    "concept_name",
    "time_block",
    "causal_rank",
    "signal_date",
    "wave_start_date",
    "wave_number",
    "reference_peak_date",
    "reference_peak_price",
    "pullback_confirmation_date",
    "signal_daily_return_pct",
    "signal_close_to_peak_pct",
    "pullback_confirmation_low_to_peak_pct",
    "line_distance_close_pct",
    "volume_ratio_prior5",
    "volume_ratio_impulse",
    "volume_class_prior5",
    "impulse_gain_pct",
    "strong_days_ge_9_5pct",
)
PRE_ENTRY_FEATURE_COLUMNS = (
    *PARENT_SIGNAL_COLUMNS,
    "pullback_sessions_from_peak",
    "stock_return_5d_pct",
    "stock_return_10d_pct",
    "stock_ma5_slope_3_pct",
    "stock_ma10_slope_3_pct",
    "stock_ma20_slope_3_pct",
    "stock_ma5_ma10_gap_pct",
    "stock_ma10_ma20_gap_pct",
    "stock_close_location_pct",
    "stock_ordered_ma",
    "concept_return_5d_pct",
    "concept_return_10d_pct",
    "concept_ma5_slope_3_pct",
    "concept_ma10_slope_3_pct",
    "concept_ma20_slope_3_pct",
    "concept_ma5_ma10_gap_pct",
    "concept_ma10_ma20_gap_pct",
    "concept_close_location_pct",
    "concept_ordered_ma",
    "concept_return_5d_percentile",
    "concept_return_10d_percentile",
    "stock_excess_concept_5d_pct",
    "stock_excess_concept_10d_pct",
    "proxy_member_count",
    "proxy_member_observed_5d_count",
    "proxy_positive_breadth_5d_pct",
    "proxy_positive_breadth_10d_pct",
    "proxy_stock_return_10d_rank",
    "proxy_stock_is_top3_10d",
    "proxy_top3_mean_return_10d_pct",
    "signal_stock_in_current_membership_proxy",
    "membership_evidence",
    "active_direction",
    "danger_state",
    "market_phase",
    "timing_evidence",
    "feature_cutoff_date",
)
NUMERIC_PRE_ENTRY_FEATURES = (
    "signal_daily_return_pct",
    "signal_close_to_peak_pct",
    "pullback_confirmation_low_to_peak_pct",
    "line_distance_close_pct",
    "pullback_sessions_from_peak",
    "volume_ratio_prior5",
    "volume_ratio_impulse",
    "impulse_gain_pct",
    "strong_days_ge_9_5pct",
    "stock_return_5d_pct",
    "stock_return_10d_pct",
    "stock_ma5_slope_3_pct",
    "stock_ma10_slope_3_pct",
    "stock_ma20_slope_3_pct",
    "stock_ma5_ma10_gap_pct",
    "stock_ma10_ma20_gap_pct",
    "stock_close_location_pct",
    "concept_return_5d_pct",
    "concept_return_10d_pct",
    "concept_ma5_slope_3_pct",
    "concept_ma10_slope_3_pct",
    "concept_ma20_slope_3_pct",
    "concept_ma5_ma10_gap_pct",
    "concept_ma10_ma20_gap_pct",
    "concept_close_location_pct",
    "concept_return_5d_percentile",
    "concept_return_10d_percentile",
    "stock_excess_concept_5d_pct",
    "stock_excess_concept_10d_pct",
    "proxy_positive_breadth_5d_pct",
    "proxy_positive_breadth_10d_pct",
    "proxy_stock_return_10d_rank",
    "proxy_top3_mean_return_10d_pct",
)
CATEGORICAL_PRE_ENTRY_FEATURES = (
    "volume_class_prior5",
    "stock_ordered_ma",
    "concept_ordered_ma",
    "proxy_stock_is_top3_10d",
    "active_direction",
    "danger_state",
    "time_block",
)
OUTCOME_COLUMNS = (
    "entry_date",
    "exit_date",
    "entry_price",
    "exit_price",
    "holding_sessions",
    "net_return_pct",
    "maximum_adverse_excursion_pct",
    "maximum_favorable_excursion_pct",
    "executable_exit_reason",
    "eventually_made_higher_high",
    "defensive_exit_preceded_later_higher_high",
)


def select_ma5_attribution_cohort(trades: pd.DataFrame) -> pd.DataFrame:
    """Select the already-frozen closed primary MA5 cohort."""

    required = {
        *PARENT_SIGNAL_COLUMNS,
        *OUTCOME_COLUMNS,
        "signal_mode",
        "primary_eligible",
        "support_line",
    }
    _require_columns(trades, required, "confirmed pullback trade ledger")
    cohort = trades.loc[
        trades["signal_mode"].astype(str).eq("stabilized_reclaim")
        & trades["primary_eligible"].fillna(False).astype(bool)
        & trades["support_line"].astype(str).eq("ma5")
        & trades["exit_date"].notna()
    ].copy()
    if cohort["signal_id"].duplicated().any():
        raise ValueError("MA5 attribution signal IDs must be unique")
    return cohort.sort_values(
        ["signal_date", "signal_id"],
        kind="stable",
    ).reset_index(drop=True)


def build_pre_entry_ma5_features(
    cohort: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    memberships: pd.DataFrame,
    timing_labels: pd.DataFrame,
) -> pd.DataFrame:
    """Build features known no later than the signal-session close."""

    _require_columns(cohort, PARENT_SIGNAL_COLUMNS, "MA5 attribution cohort")
    base = cohort.loc[:, list(PARENT_SIGNAL_COLUMNS)].copy()
    for column in (
        "signal_date",
        "wave_start_date",
        "reference_peak_date",
        "pullback_confirmation_date",
    ):
        base[column] = pd.to_datetime(base[column], errors="raise").dt.normalize()
    stock_features = _price_features(stock_bars, "vt_symbol")
    concept_features = _price_features(concept_bars, "sector_id")
    concept_features["return_5d_percentile"] = concept_features.groupby(
        "trade_date",
        sort=False,
    )["return_5d_pct"].rank(method="average", pct=True)
    concept_features["return_10d_percentile"] = concept_features.groupby(
        "trade_date",
        sort=False,
    )["return_10d_pct"].rank(method="average", pct=True)

    stock_view = _prefixed_feature_view(stock_features, "vt_symbol", "stock")
    concept_view = _prefixed_feature_view(
        concept_features,
        "sector_id",
        "concept",
    )
    enriched = base.merge(
        stock_view,
        left_on=["vt_symbol", "signal_date"],
        right_on=["vt_symbol", "stock_trade_date"],
        how="left",
        validate="many_to_one",
    ).drop(columns="stock_trade_date")
    enriched = enriched.merge(
        concept_view,
        left_on=["sector_id", "signal_date"],
        right_on=["sector_id", "concept_trade_date"],
        how="left",
        validate="many_to_one",
    ).drop(columns="concept_trade_date")

    peak_positions = stock_features.loc[
        : , ["vt_symbol", "trade_date", "session_position"]
    ].rename(
        columns={
            "trade_date": "reference_peak_date",
            "session_position": "reference_peak_position",
        }
    )
    enriched = enriched.merge(
        peak_positions,
        on=["vt_symbol", "reference_peak_date"],
        how="left",
        validate="many_to_one",
    )
    enriched["pullback_sessions_from_peak"] = (
        enriched["stock_session_position"]
        - enriched["reference_peak_position"]
    )
    enriched["stock_excess_concept_5d_pct"] = (
        enriched["stock_return_5d_pct"]
        - enriched["concept_return_5d_pct"]
    )
    enriched["stock_excess_concept_10d_pct"] = (
        enriched["stock_return_10d_pct"]
        - enriched["concept_return_10d_pct"]
    )

    peer_rows = _proxy_member_diagnostics(
        enriched,
        stock_features,
        memberships,
    )
    enriched = enriched.merge(
        peer_rows,
        on="signal_id",
        how="left",
        validate="one_to_one",
    )
    enriched = _attach_timing_labels(enriched, timing_labels)
    enriched["feature_cutoff_date"] = enriched["signal_date"]
    for column in PRE_ENTRY_FEATURE_COLUMNS:
        if column not in enriched:
            enriched[column] = pd.NA
    return enriched.loc[:, list(PRE_ENTRY_FEATURE_COLUMNS)].sort_values(
        ["signal_date", "signal_id"],
        kind="stable",
    ).reset_index(drop=True)


def attach_ma5_outcome_attribution(
    features: pd.DataFrame,
    cohort: pd.DataFrame,
    concept_bars: pd.DataFrame,
    concept_states: pd.DataFrame,
) -> pd.DataFrame:
    """Attach realized paths only after all signal-date features are fixed."""

    _require_columns(features, PRE_ENTRY_FEATURE_COLUMNS, "pre-entry features")
    _require_columns(
        cohort,
        ("signal_id", *OUTCOME_COLUMNS),
        "MA5 attribution cohort outcomes",
    )
    outcomes = cohort.loc[:, ["signal_id", *OUTCOME_COLUMNS]].copy()
    for column in ("entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(
            outcomes[column],
            errors="raise",
        ).dt.normalize()
    if outcomes["signal_id"].duplicated().any():
        raise ValueError("MA5 attribution outcomes must be unique")
    ledger = features.merge(
        outcomes,
        on="signal_id",
        how="left",
        validate="one_to_one",
    )
    post_returns = _concept_post_signal_returns(ledger, concept_bars)
    ledger = ledger.merge(
        post_returns,
        on="signal_id",
        how="left",
        validate="one_to_one",
    )
    state_rows = _concept_state_attribution(ledger, concept_states)
    ledger = ledger.merge(
        state_rows,
        on="signal_id",
        how="left",
        validate="one_to_one",
    )
    ledger["outcome_group"] = np.where(
        pd.to_numeric(ledger["net_return_pct"], errors="coerce").gt(0),
        "winner",
        "loser",
    )
    ledger["failure_mechanism"] = ledger.apply(
        _failure_mechanism,
        axis=1,
    )
    ledger["outcome_feature_boundary"] = "post_entry_attribution_only"
    return ledger.sort_values(
        ["signal_date", "signal_id"],
        kind="stable",
    ).reset_index(drop=True)


def build_ma5_case_attribution_report(
    ledger: pd.DataFrame,
    *,
    parent_sha256: str,
    input_fingerprints: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a descriptive report without fitting thresholds or combinations."""

    _require_columns(
        ledger,
        (*PRE_ENTRY_FEATURE_COLUMNS, "outcome_group", "net_return_pct"),
        "MA5 attribution ledger",
    )
    numeric = _numeric_feature_comparison(ledger)
    block_checks = _block_direction_checks(ledger, numeric)
    stable = [
        row
        for row in block_checks
        if row["sufficient_blocks"] >= 4
        and row["consistent_blocks"] == row["sufficient_blocks"]
        and row["global_direction"] not in ("flat", "missing")
    ]
    has_separation = any(
        row.get("median_diff_pooled_iqr") not in (None, 0.0)
        for row in numeric
    )
    if stable:
        status = "forward_diagnostic_candidate_found"
    elif has_separation:
        status = "descriptive_separation_not_stable"
    else:
        status = "no_clear_ma5_failure_separation"
    returns = _finite_series(ledger["net_return_pct"])
    winners = ledger["outcome_group"].eq("winner")
    report = {
        "study_version": STUDY_VERSION,
        "research_status": status,
        "validation_status": "reused_history_attribution_not_validation",
        "formal_strategy": False,
        "formal_metrics": {
            "win_rate_pct": None,
            "average_net_return_pct": None,
            "compounded_return_pct": None,
            "profit_factor": None,
            "maximum_drawdown_pct": None,
        },
        "parent_evidence": {
            "study_version": "confirmed-multi-wave-pullback-v1",
            "sha256": parent_sha256,
            "cohort": (
                "primary_eligible/stabilized_reclaim/ma5/closed"
            ),
        },
        "feature_contract": {
            "cutoff": "signal_session_close",
            "comparison": "fixed_univariate_no_threshold_search",
            "membership": "current_membership_proxy_diagnostic_only",
            "timing": "exact_signal_date_when_available",
            "outcomes_attached_after_features": True,
            "post_entry_fields_never_entry_filters": True,
        },
        "coverage": {
            "individual_case_rows": int(len(ledger)),
            "winner_rows": int(winners.sum()),
            "loser_rows": int((~winners).sum()),
            "symbols": int(ledger["vt_symbol"].nunique()),
            "concepts": int(ledger["sector_id"].nunique()),
            "signal_dates": int(ledger["signal_date"].nunique()),
            "membership_proxy_rows": int(
                ledger["membership_evidence"]
                .astype(str)
                .eq("current_membership_proxy")
                .sum()
            ),
            "timing_rows": int(
                ledger["timing_evidence"].astype(str).eq("available").sum()
            ),
        },
        "descriptive_parent_result": {
            "closed_entries": int(len(returns)),
            "positive_share_pct": _round(winners.mean() * 100.0),
            "mean_net_return_pct": _round(returns.mean()),
            "median_net_return_pct": _round(returns.median()),
            "profit_factor": _profit_factor(returns),
        },
        "pre_entry_numeric_comparison": numeric,
        "pre_entry_categorical_comparison": (
            _categorical_feature_comparison(ledger)
        ),
        "block_direction_checks": block_checks,
        "forward_diagnostic_candidates": [
            {
                "feature": row["feature"],
                "global_direction": row["global_direction"],
                "consistent_blocks": row["consistent_blocks"],
                "sufficient_blocks": row["sufficient_blocks"],
                "use": "observe_forward_without_threshold_or_signal_effect",
            }
            for row in stable
        ],
        "failure_mechanism_summary": _group_summary(
            ledger,
            "failure_mechanism",
        ),
        "concept_continuation_summary": _concept_continuation_summary(ledger),
        "individual_case_ledger": _records(ledger),
        "input_fingerprints": _json_safe(dict(input_fingerprints or {})),
        "boundaries": [
            "all five historical blocks were already viewed",
            "current memberships are a survivorship proxy, not historical fact",
            "causal Top3 did not pass the prior absolute identity gate",
            "post-entry concept continuation explains outcomes but cannot trigger entry",
            "stable direction nominates forward diagnostics only, never a fitted rule",
            "formal Top3, win rate, return and compounding remain null",
        ],
        "reproduce": (
            "docker compose run --rm --no-deps "
            "-v /root/project/ai/vnpy:/workspace -w /workspace "
            "alphaagent-api python -m "
            "alphaagent.server.services.low_suction.cli "
            "v2-ma5-case-attribution-study --format markdown"
        ),
    }
    return _json_safe(report)


def render_ma5_case_attribution_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_ma5_case_attribution_markdown(report: Mapping[str, Any]) -> str:
    coverage = _mapping(report.get("coverage"))
    parent = _mapping(report.get("descriptive_parent_result"))
    candidates = _sequence(report.get("forward_diagnostic_candidates"))
    lines = [
        "# AlphaAgent 多浪龙头 MA5 成功/失败逐票归因",
        "",
        f"研究状态：`{report.get('research_status')}`；验证边界："
        f"`{report.get('validation_status')}`。",
        "正式 Top3、胜率、收益和复利：`null`。",
        "",
        "## Coverage",
        "",
        f"- 完整逐票记录：`{coverage.get('individual_case_rows', 0)}`；"
        f"成功/失败：`{coverage.get('winner_rows', 0)}` / "
        f"`{coverage.get('loser_rows', 0)}`。",
        f"- 股票/概念/信号日：`{coverage.get('symbols', 0)}` / "
        f"`{coverage.get('concepts', 0)}` / "
        f"`{coverage.get('signal_dates', 0)}`。",
        f"- 当前成员代理覆盖：`{coverage.get('membership_proxy_rows', 0)}`；"
        f"金银标签覆盖：`{coverage.get('timing_rows', 0)}`。",
        "",
        "## Parent Descriptive Result",
        "",
        f"- 57 笔闭合中成本后为正比例 `{_pct(parent.get('positive_share_pct'))}`，"
        f"均值 `{_pct(parent.get('mean_net_return_pct'))}`，"
        f"利润因子 `{_number(parent.get('profit_factor'))}`。",
        "- 这些是已看历史的描述值，不是正式低吸胜率。",
        "",
        "## Pre-entry Differences",
        "",
        "| Feature | Winner median | Loser median | Diff / pooled IQR |",
        "| --- | ---: | ---: | ---: |",
        *_numeric_lines(report.get("pre_entry_numeric_comparison")),
        "",
        "## Forward Diagnostics",
        "",
    ]
    if candidates:
        lines.extend(
            f"- `{item.get('feature')}`：赢家方向 `{item.get('global_direction')}`，"
            f"充分块中 `{item.get('consistent_blocks')}/"
            f"{item.get('sufficient_blocks')}` 同向；只前向观察，不设阈值。"
            for item in candidates
        )
    else:
        lines.append("- 没有信号日前特征在至少四个充分时间块保持同向。")
    lines.extend(
        [
            "",
            "## Failure Mechanisms",
            "",
            "| Mechanism | Cases | Positive | Mean net |",
            "| --- | ---: | ---: | ---: |",
            *_group_lines(report.get("failure_mechanism_summary")),
            "",
            "## Concept Continuation",
            "",
            "| Outcome | Cases | Post 1d median | Post 5d median | Post 10d median |",
            "| --- | ---: | ---: | ---: | ---: |",
            *_continuation_lines(report.get("concept_continuation_summary")),
            "",
            "概念后续涨跌属于信号后的归因：它解释为何同样的 MA5 结构分化，"
            "不能直接变成买入条件。",
            "",
            "## Individual Cases",
            "",
            "| Date | Stock | Concept | Result | Net | Impulse | MA5-MA10 | Volume | Concept +5d | Mechanism |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
            *_case_lines(report.get("individual_case_ledger")),
            "",
            "## Boundaries",
            "",
            *[
                f"- {item}"
                for item in _values(report.get("boundaries"))
            ],
            "",
            "## Reproduce",
            "",
            "```bash",
            str(report.get("reproduce") or ""),
            "```",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def run_ma5_case_attribution_study() -> dict[str, Any]:
    """Run the audit against the immutable parent report and local raw bars."""

    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine
    from alphaagent.server.services.a_share_universe import is_eligible_main_board

    from .concept_cycles import build_cycle_candidates, load_cycle_research_inputs
    from .concept_index_coverage import CANONICAL_CONCEPT_INDEX_SOURCE
    from .contracts import CONCEPT_SECTOR_TYPES
    from .repository import _load_timing_labels
    from .research_protocol import fingerprint_frame

    parent, parent_hash = _load_parent_report()
    trades = pd.DataFrame.from_records(parent.get("trade_ledger") or [])
    cohort = select_ma5_attribution_cohort(trades)
    if len(cohort) != EXPECTED_COHORT_ROWS:
        raise ValueError(
            "frozen parent MA5 cohort changed: "
            f"expected {EXPECTED_COHORT_ROWS}, got {len(cohort)}"
        )
    signal_dates = pd.to_datetime(cohort["signal_date"], errors="raise")
    exit_dates = pd.to_datetime(cohort["exit_date"], errors="raise")
    load_start = (signal_dates.min() - pd.Timedelta(days=90)).date()
    load_end = (exit_dates.max() + pd.Timedelta(days=30)).date()
    sector_ids = tuple(sorted(cohort["sector_id"].astype(str).unique()))
    engine = get_engine()
    memberships = pd.read_sql(
        select(
            schema.sector_memberships.c.sector_id,
            schema.sector_memberships.c.vt_symbol,
            schema.sector_memberships.c.name,
            schema.sector_memberships.c.source,
        ).where(schema.sector_memberships.c.sector_id.in_(sector_ids)),
        engine,
    )
    memberships = memberships.loc[
        memberships.apply(
            lambda row: is_eligible_main_board(
                str(row["vt_symbol"]),
                str(row.get("name") or ""),
            ),
            axis=1,
        )
    ].reset_index(drop=True)
    symbols = tuple(
        sorted(
            set(cohort["vt_symbol"].astype(str))
            | set(memberships["vt_symbol"].astype(str))
        )
    )
    stock_bars = pd.read_sql(
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.volume,
        )
        .where(
            schema.stock_daily_bars.c.vt_symbol.in_(symbols),
            schema.stock_daily_bars.c.trade_date.between(load_start, load_end),
        )
        .order_by(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
        ),
        engine,
        parse_dates=["trade_date"],
    )
    concept_bars = pd.read_sql(
        select(
            schema.sector_daily_bars.c.sector_id,
            schema.sector_daily_bars.c.trade_date,
            schema.sector_daily_bars.c.open_price,
            schema.sector_daily_bars.c.high_price,
            schema.sector_daily_bars.c.low_price,
            schema.sector_daily_bars.c.close_price,
            schema.sector_daily_bars.c.volume,
            schema.sector_daily_bars.c.turnover,
        )
        .select_from(
            schema.sector_daily_bars.join(
                schema.sectors,
                schema.sector_daily_bars.c.sector_id == schema.sectors.c.id,
            )
        )
        .where(
            schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES),
            schema.sector_daily_bars.c.source
            == CANONICAL_CONCEPT_INDEX_SOURCE,
            schema.sector_daily_bars.c.trade_date.between(load_start, load_end),
        )
        .order_by(
            schema.sector_daily_bars.c.sector_id,
            schema.sector_daily_bars.c.trade_date,
        ),
        engine,
        parse_dates=["trade_date"],
    )
    timing = _load_timing_labels()
    cycle_inputs = load_cycle_research_inputs()
    concept_states = build_cycle_candidates(
        cycle_inputs.concept_bars,
        cycle_inputs.market_returns,
    )
    features = build_pre_entry_ma5_features(
        cohort,
        stock_bars,
        concept_bars,
        memberships,
        timing,
    )
    ledger = attach_ma5_outcome_attribution(
        features,
        cohort,
        concept_bars,
        concept_states,
    )
    fingerprints = {
        "parent_cohort": fingerprint_frame(
            cohort,
            identity_columns=("signal_id",),
        ).as_dict(),
        "stock_bars": fingerprint_frame(
            stock_bars,
            identity_columns=("vt_symbol", "trade_date"),
        ).as_dict(),
        "concept_bars": fingerprint_frame(
            concept_bars,
            identity_columns=("sector_id", "trade_date"),
        ).as_dict(),
        "memberships": fingerprint_frame(
            memberships,
            identity_columns=("sector_id", "vt_symbol"),
        ).as_dict(),
        "attribution_ledger": fingerprint_frame(
            ledger,
            identity_columns=("signal_id",),
        ).as_dict(),
    }
    return build_ma5_case_attribution_report(
        ledger,
        parent_sha256=f"sha256:{parent_hash}",
        input_fingerprints=fingerprints,
    )


def _load_parent_report() -> tuple[dict[str, Any], str]:
    raw = PARENT_REPORT_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PARENT_REPORT_SHA256:
        raise ValueError(
            "confirmed multi-wave parent report fingerprint changed: "
            f"{digest}"
        )
    report = json.loads(raw.decode("utf-8"))
    if report.get("study_version") != "confirmed-multi-wave-pullback-v1":
        raise ValueError("unexpected confirmed multi-wave parent study version")
    return report, digest


def _price_features(bars: pd.DataFrame, key_column: str) -> pd.DataFrame:
    required = (
        key_column,
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
    )
    _require_columns(bars, required, f"{key_column} price bars")
    frame = bars.loc[:, list(dict.fromkeys(required))].copy()
    frame[key_column] = frame[key_column].astype(str)
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"],
        errors="raise",
    ).dt.normalize()
    if frame.duplicated([key_column, "trade_date"]).any():
        raise ValueError(f"duplicate {key_column} price bars")
    numeric_columns = (
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
    )
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    rows = []
    for _, group in frame.groupby(key_column, sort=False):
        item = group.sort_values("trade_date", kind="stable").copy()
        item["session_position"] = np.arange(len(item), dtype=int)
        close = item["close_price"]
        for window in (5, 10, 20):
            item[f"ma{window}"] = close.rolling(
                window,
                min_periods=window,
            ).mean()
            item[f"ma{window}_slope_3_pct"] = (
                item[f"ma{window}"]
                / item[f"ma{window}"].shift(3)
                - 1.0
            ) * 100.0
        item["return_5d_pct"] = (close / close.shift(5) - 1.0) * 100.0
        item["return_10d_pct"] = (close / close.shift(10) - 1.0) * 100.0
        item["ma5_ma10_gap_pct"] = (
            item["ma5"] / item["ma10"] - 1.0
        ) * 100.0
        item["ma10_ma20_gap_pct"] = (
            item["ma10"] / item["ma20"] - 1.0
        ) * 100.0
        spread = item["high_price"] - item["low_price"]
        item["close_location_pct"] = (
            (item["close_price"] - item["low_price"])
            / spread.where(spread.gt(0))
            * 100.0
        )
        item["ordered_ma"] = (
            item["close_price"].ge(item["ma5"])
            & item["ma5"].gt(item["ma10"])
            & item["ma10"].gt(item["ma20"])
        )
        rows.append(item)
    return pd.concat(rows, ignore_index=True) if rows else frame


def _prefixed_feature_view(
    features: pd.DataFrame,
    key_column: str,
    prefix: str,
) -> pd.DataFrame:
    columns = (
        key_column,
        "trade_date",
        "session_position",
        "return_5d_pct",
        "return_10d_pct",
        "ma5_slope_3_pct",
        "ma10_slope_3_pct",
        "ma20_slope_3_pct",
        "ma5_ma10_gap_pct",
        "ma10_ma20_gap_pct",
        "close_location_pct",
        "ordered_ma",
        "return_5d_percentile",
        "return_10d_percentile",
    )
    available = [column for column in columns if column in features]
    return features.loc[:, available].rename(
        columns={
            column: f"{prefix}_{column}"
            for column in available
            if column != key_column
        }
    )


def _proxy_member_diagnostics(
    signals: pd.DataFrame,
    stock_features: pd.DataFrame,
    memberships: pd.DataFrame,
) -> pd.DataFrame:
    required = ("sector_id", "vt_symbol")
    if memberships.empty:
        member_map: dict[str, set[str]] = {}
    else:
        _require_columns(memberships, required, "current membership proxy")
        member_map = {
            str(sector_id): set(group["vt_symbol"].astype(str))
            for sector_id, group in memberships.groupby("sector_id", sort=False)
        }
    indexed = {
        (str(symbol), pd.Timestamp(trade_date)): row
        for (symbol, trade_date), row in stock_features.set_index(
            ["vt_symbol", "trade_date"]
        ).iterrows()
    }
    rows = []
    for signal in signals.to_dict("records"):
        signal_id = str(signal["signal_id"])
        sector_id = str(signal["sector_id"])
        symbol = str(signal["vt_symbol"])
        signal_date = pd.Timestamp(signal["signal_date"])
        members = member_map.get(sector_id, set())
        observed = []
        for member in sorted(members):
            item = indexed.get((member, signal_date))
            if item is None:
                continue
            observed.append(
                {
                    "vt_symbol": member,
                    "return_5d_pct": _finite_or_none(item.get("return_5d_pct")),
                    "return_10d_pct": _finite_or_none(item.get("return_10d_pct")),
                }
            )
        peer = pd.DataFrame.from_records(observed)
        valid_5 = (
            pd.to_numeric(peer.get("return_5d_pct"), errors="coerce").dropna()
            if not peer.empty
            else pd.Series(dtype=float)
        )
        valid_10_frame = (
            peer.loc[pd.to_numeric(peer["return_10d_pct"], errors="coerce").notna()].copy()
            if not peer.empty
            else pd.DataFrame(columns=["vt_symbol", "return_10d_pct"])
        )
        if not valid_10_frame.empty:
            valid_10_frame["return_10d_pct"] = pd.to_numeric(
                valid_10_frame["return_10d_pct"],
                errors="raise",
            )
            valid_10_frame["rank"] = valid_10_frame["return_10d_pct"].rank(
                ascending=False,
                method="min",
            )
        symbol_row = valid_10_frame.loc[
            valid_10_frame["vt_symbol"].eq(symbol)
        ]
        symbol_rank = (
            float(symbol_row.iloc[0]["rank"])
            if not symbol_row.empty
            else None
        )
        top3 = valid_10_frame.nsmallest(3, "rank")
        rows.append(
            {
                "signal_id": signal_id,
                "proxy_member_count": len(members),
                "proxy_member_observed_5d_count": int(len(valid_5)),
                "proxy_positive_breadth_5d_pct": (
                    _round(valid_5.gt(0).mean() * 100.0)
                    if len(valid_5)
                    else None
                ),
                "proxy_positive_breadth_10d_pct": (
                    _round(
                        valid_10_frame["return_10d_pct"].gt(0).mean()
                        * 100.0
                    )
                    if len(valid_10_frame)
                    else None
                ),
                "proxy_stock_return_10d_rank": symbol_rank,
                "proxy_stock_is_top3_10d": (
                    bool(symbol_rank <= 3) if symbol_rank is not None else None
                ),
                "proxy_top3_mean_return_10d_pct": (
                    _round(top3["return_10d_pct"].mean())
                    if not top3.empty
                    else None
                ),
                "signal_stock_in_current_membership_proxy": symbol in members,
                "membership_evidence": (
                    "current_membership_proxy" if members else "missing"
                ),
            }
        )
    return pd.DataFrame.from_records(rows)


def _attach_timing_labels(
    signals: pd.DataFrame,
    timing_labels: pd.DataFrame,
) -> pd.DataFrame:
    if timing_labels.empty:
        result = signals.copy()
        result["active_direction"] = "MISSING"
        result["danger_state"] = "MISSING"
        result["market_phase"] = "MISSING"
        result["timing_evidence"] = "missing"
        return result
    required = ("trade_date", "active_direction", "danger_state", "market_phase")
    _require_columns(timing_labels, required, "market timing labels")
    timing = timing_labels.loc[:, list(required)].copy()
    timing["trade_date"] = pd.to_datetime(
        timing["trade_date"],
        errors="raise",
    ).dt.normalize()
    if timing["trade_date"].duplicated().any():
        raise ValueError("market timing labels must have unique trade dates")
    result = signals.merge(
        timing,
        left_on="signal_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
    ).drop(columns="trade_date")
    available = result["active_direction"].notna()
    for column in ("active_direction", "danger_state", "market_phase"):
        result[column] = result[column].fillna("MISSING").astype(str)
    result["timing_evidence"] = np.where(available, "available", "missing")
    return result


def _concept_post_signal_returns(
    ledger: pd.DataFrame,
    concept_bars: pd.DataFrame,
) -> pd.DataFrame:
    features = _price_features(concept_bars, "sector_id")
    grouped = {
        str(sector_id): group.sort_values("trade_date", kind="stable").reset_index(drop=True)
        for sector_id, group in features.groupby("sector_id", sort=False)
    }
    rows = []
    for signal in ledger.to_dict("records"):
        group = grouped.get(str(signal["sector_id"]))
        result: dict[str, Any] = {"signal_id": str(signal["signal_id"])}
        for horizon in (1, 3, 5, 10):
            result[f"concept_post_{horizon}d_return_pct"] = None
        if group is not None:
            matches = group.index[
                group["trade_date"].eq(pd.Timestamp(signal["signal_date"]))
            ]
            if len(matches) == 1:
                position = int(matches[0])
                start_close = float(group.iloc[position]["close_price"])
                for horizon in (1, 3, 5, 10):
                    target = position + horizon
                    if target < len(group):
                        result[f"concept_post_{horizon}d_return_pct"] = _round(
                            (
                                float(group.iloc[target]["close_price"])
                                / start_close
                                - 1.0
                            )
                            * 100.0
                        )
        rows.append(result)
    return pd.DataFrame.from_records(rows)


def _concept_state_attribution(
    ledger: pd.DataFrame,
    concept_states: pd.DataFrame,
) -> pd.DataFrame:
    if concept_states.empty:
        return pd.DataFrame.from_records(
            [
                {
                    "signal_id": signal_id,
                    "concept_state_observed_sessions": 0,
                    "concept_lost_main_rise_before_exit": None,
                }
                for signal_id in ledger["signal_id"].astype(str)
            ]
        )
    required = (
        "sector_id",
        "trade_date",
        "definition",
        "in_cycle",
        "sustain_qualifies",
    )
    _require_columns(concept_states, required, "concept cycle states")
    states = concept_states.loc[
        concept_states["definition"].astype(str).eq("breakout_trend"),
        list(required),
    ].copy()
    states["sector_id"] = states["sector_id"].astype(str)
    states["trade_date"] = pd.to_datetime(
        states["trade_date"],
        errors="raise",
    ).dt.normalize()
    states["main_rise_intact"] = (
        states["in_cycle"].fillna(False).astype(bool)
        & states["sustain_qualifies"].fillna(False).astype(bool)
    )
    rows = []
    for signal in ledger.to_dict("records"):
        path = states.loc[
            states["sector_id"].eq(str(signal["sector_id"]))
            & states["trade_date"].gt(pd.Timestamp(signal["signal_date"]))
            & states["trade_date"].le(pd.Timestamp(signal["exit_date"]))
        ]
        rows.append(
            {
                "signal_id": str(signal["signal_id"]),
                "concept_state_observed_sessions": int(len(path)),
                "concept_lost_main_rise_before_exit": (
                    bool((~path["main_rise_intact"]).any())
                    if not path.empty
                    else None
                ),
            }
        )
    return pd.DataFrame.from_records(rows)


def _failure_mechanism(row: pd.Series) -> str:
    winner = str(row.get("outcome_group")) == "winner"
    higher_high = bool(row.get("eventually_made_higher_high"))
    defensive_exit = str(row.get("executable_exit_reason")) == (
        "two_closes_below_ma20"
    )
    concept_lost = row.get("concept_lost_main_rise_before_exit")
    post_5d = _finite_or_none(row.get("concept_post_5d_return_pct"))
    if winner:
        return (
            "higher_high_rebreak_winner"
            if higher_high
            else "positive_without_higher_high"
        )
    if defensive_exit and higher_high:
        return "defensive_exit_before_later_rebreak"
    if defensive_exit and not higher_high:
        if concept_lost is True or (post_5d is not None and post_5d <= 0):
            return "concept_and_stock_wave_ended"
        if concept_lost is False:
            return "stock_failed_inside_intact_concept"
        return "stock_wave_ended_context_unknown"
    if higher_high:
        return "higher_high_but_entry_to_exit_loss"
    return "loss_without_higher_high"


def _numeric_feature_comparison(ledger: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    winner_mask = ledger["outcome_group"].eq("winner")
    for feature in NUMERIC_PRE_ENTRY_FEATURES:
        winners = _finite_series(ledger.loc[winner_mask, feature])
        losers = _finite_series(ledger.loc[~winner_mask, feature])
        pooled = pd.concat([winners, losers], ignore_index=True)
        pooled_iqr = (
            float(pooled.quantile(0.75) - pooled.quantile(0.25))
            if len(pooled)
            else math.nan
        )
        winner_median = _median(winners)
        loser_median = _median(losers)
        median_difference = (
            winner_median - loser_median
            if winner_median is not None and loser_median is not None
            else None
        )
        rows.append(
            {
                "feature": feature,
                "winner_rows": int(len(winners)),
                "loser_rows": int(len(losers)),
                "winner_median": winner_median,
                "winner_q25": _quantile(winners, 0.25),
                "winner_q75": _quantile(winners, 0.75),
                "loser_median": loser_median,
                "loser_q25": _quantile(losers, 0.25),
                "loser_q75": _quantile(losers, 0.75),
                "median_difference": _round(median_difference),
                "median_diff_pooled_iqr": (
                    _round(median_difference / pooled_iqr)
                    if median_difference is not None
                    and math.isfinite(pooled_iqr)
                    and pooled_iqr > 0
                    else None
                ),
            }
        )
    return rows


def _block_direction_checks(
    ledger: pd.DataFrame,
    numeric_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    global_by_feature = {
        str(row["feature"]): _direction(row.get("median_difference"))
        for row in numeric_rows
    }
    results = []
    winner_mask = ledger["outcome_group"].eq("winner")
    for feature in NUMERIC_PRE_ENTRY_FEATURES:
        global_direction = global_by_feature.get(feature, "missing")
        blocks = []
        sufficient_blocks = 0
        consistent_blocks = 0
        for block_number in range(1, 6):
            block = f"block_{block_number}"
            mask = ledger["time_block"].astype(str).eq(block)
            winners = _finite_series(ledger.loc[mask & winner_mask, feature])
            losers = _finite_series(ledger.loc[mask & ~winner_mask, feature])
            sufficient = bool(
                len(winners) >= MIN_BLOCK_SIDE_ROWS
                and len(losers) >= MIN_BLOCK_SIDE_ROWS
            )
            direction = (
                _direction(float(winners.median() - losers.median()))
                if sufficient
                else "insufficient"
            )
            consistent = bool(
                sufficient
                and direction == global_direction
                and direction not in ("flat", "missing")
            )
            sufficient_blocks += int(sufficient)
            consistent_blocks += int(consistent)
            blocks.append(
                {
                    "block": block,
                    "winner_rows": int(len(winners)),
                    "loser_rows": int(len(losers)),
                    "winner_median": _median(winners),
                    "loser_median": _median(losers),
                    "direction": direction,
                    "sufficient": sufficient,
                    "consistent_with_global": consistent,
                }
            )
        results.append(
            {
                "feature": feature,
                "global_direction": global_direction,
                "sufficient_blocks": sufficient_blocks,
                "consistent_blocks": consistent_blocks,
                "blocks": blocks,
            }
        )
    return results


def _categorical_feature_comparison(
    ledger: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows = []
    for feature in CATEGORICAL_PRE_ENTRY_FEATURES:
        values = ledger[feature].astype("object").where(
            ledger[feature].notna(),
            "MISSING",
        )
        for value, indexes in values.groupby(values, sort=True).groups.items():
            group = ledger.loc[indexes]
            positive = group["outcome_group"].eq("winner")
            returns = _finite_series(group["net_return_pct"])
            rows.append(
                {
                    "feature": feature,
                    "value": _json_safe(value),
                    "cases": int(len(group)),
                    "winners": int(positive.sum()),
                    "losers": int((~positive).sum()),
                    "positive_share_pct": _round(positive.mean() * 100.0),
                    "mean_net_return_pct": _round(returns.mean()),
                }
            )
    return rows


def _group_summary(ledger: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    rows = []
    for value, group in ledger.groupby(column, dropna=False, sort=True):
        positive = group["outcome_group"].eq("winner")
        returns = _finite_series(group["net_return_pct"])
        rows.append(
            {
                "group": _json_safe(value),
                "cases": int(len(group)),
                "positive_share_pct": _round(positive.mean() * 100.0),
                "mean_net_return_pct": _round(returns.mean()),
            }
        )
    return rows


def _concept_continuation_summary(ledger: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for outcome, group in ledger.groupby("outcome_group", sort=True):
        row: dict[str, Any] = {
            "outcome_group": str(outcome),
            "cases": int(len(group)),
        }
        for horizon in (1, 3, 5, 10):
            values = _finite_series(
                group[f"concept_post_{horizon}d_return_pct"]
            )
            row[f"post_{horizon}d_rows"] = int(len(values))
            row[f"post_{horizon}d_median_pct"] = _median(values)
            row[f"post_{horizon}d_mean_pct"] = _round(values.mean())
            row[f"post_{horizon}d_positive_share_pct"] = (
                _round(values.gt(0).mean() * 100.0) if len(values) else None
            )
        rows.append(row)
    return rows


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str] | set[str],
    label: str,
) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")


def _finite_series(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.loc[np.isfinite(numeric.to_numpy(dtype=float))].astype(float)


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: Any) -> float | None:
    number = _finite_or_none(value)
    return round(number, 4) if number is not None else None


def _median(values: pd.Series) -> float | None:
    return _round(values.median()) if len(values) else None


def _quantile(values: pd.Series, quantile: float) -> float | None:
    return _round(values.quantile(quantile)) if len(values) else None


def _profit_factor(returns: pd.Series) -> float | None:
    gains = float(returns.loc[returns.gt(0)].sum())
    losses = abs(float(returns.loc[returns.lt(0)].sum()))
    return _round(gains / losses) if losses > 0 else None


def _direction(value: Any) -> str:
    number = _finite_or_none(value)
    if number is None:
        return "missing"
    if number > 0:
        return "higher_in_winners"
    if number < 0:
        return "lower_in_winners"
    return "flat"


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat() if value == value.normalize() else value.isoformat()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if value is pd.NA:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in (value or []) if isinstance(item, Mapping)]


def _values(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _pct(value: Any) -> str:
    number = _finite_or_none(value)
    return "-" if number is None else f"{number:.4f}%"


def _number(value: Any) -> str:
    number = _finite_or_none(value)
    return "-" if number is None else f"{number:.4f}"


def _numeric_lines(value: Any) -> list[str]:
    rows = _sequence(value)
    ordered = sorted(
        rows,
        key=lambda row: abs(
            _finite_or_none(row.get("median_diff_pooled_iqr")) or 0.0
        ),
        reverse=True,
    )
    return [
        f"| `{row.get('feature')}` | {_number(row.get('winner_median'))} | "
        f"{_number(row.get('loser_median'))} | "
        f"{_number(row.get('median_diff_pooled_iqr'))} |"
        for row in ordered
    ]


def _group_lines(value: Any) -> list[str]:
    return [
        f"| `{row.get('group')}` | {row.get('cases', 0)} | "
        f"{_pct(row.get('positive_share_pct'))} | "
        f"{_pct(row.get('mean_net_return_pct'))} |"
        for row in _sequence(value)
    ]


def _continuation_lines(value: Any) -> list[str]:
    return [
        f"| `{row.get('outcome_group')}` | {row.get('cases', 0)} | "
        f"{_pct(row.get('post_1d_median_pct'))} | "
        f"{_pct(row.get('post_5d_median_pct'))} | "
        f"{_pct(row.get('post_10d_median_pct'))} |"
        for row in _sequence(value)
    ]


def _case_lines(value: Any) -> list[str]:
    return [
        f"| {row.get('signal_date')} | {row.get('stock_name')} "
        f"`{row.get('vt_symbol')}` | {row.get('concept_name')} | "
        f"`{row.get('outcome_group')}` | {_pct(row.get('net_return_pct'))} | "
        f"{_pct(row.get('impulse_gain_pct'))} | "
        f"{_pct(row.get('stock_ma5_ma10_gap_pct'))} | "
        f"{_number(row.get('volume_ratio_prior5'))} | "
        f"{_pct(row.get('concept_post_5d_return_pct'))} | "
        f"`{row.get('failure_mechanism')}` |"
        for row in _sequence(value)
    ]
