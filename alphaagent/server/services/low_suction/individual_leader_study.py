"""Stock-by-stock evidence for event-recognized main-rise leader spells."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from collections.abc import Sequence
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .research_protocol import default_protocol
from .research_protocol import fingerprint_frame
from .research_protocol import protocol_hash


RECOGNITION_COLUMNS = (
    "event_id",
    "source_date",
    "sector_id",
    "concept_name",
    "cycle_id",
    "vt_symbol",
    "stock_name",
    "recognition_rank",
    "relative_percentile",
    "limit_times",
    "limit_up_suc_rate",
    "seal_strength",
    "amount",
    "signal_close",
    "active_direction",
    "danger_state",
    "market_phase",
    "evidence_level",
)
SPELL_IDENTITY_COLUMNS = (
    "leader_spell_id",
    "recognition_event_id",
    "recognition_source_date",
    "sector_id",
    "concept_name",
    "cycle_id",
    "vt_symbol",
    "stock_name",
    "recognition_rank",
    "relative_percentile",
    "limit_times",
    "limit_up_suc_rate",
    "seal_strength",
    "amount",
    "signal_close",
    "active_direction",
    "danger_state",
    "market_phase",
    "rank_mode",
    "evidence_level",
)
PROHIBITED_FEATURE_COLUMNS = frozenset(
    {
        "net_return_pct",
        "gross_return_pct",
        "double_cost_net_return_pct",
        "mfe_pct",
        "mae_pct",
        "exit_price",
        "outcome_group",
        "future_5d_close_return_pct",
        "future_5d_max_close_return_pct",
        "future_5d_max_drawdown_pct",
    }
)
STOCK_BAR_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
)
CONCEPT_BAR_COLUMNS = ("sector_id", "trade_date", "close_price")
MARKET_COLUMNS = ("trade_date", "market_daily_return")
STUDY_EVIDENCE_LEVEL = "event_recognition_individual_leader_spell_study"
FEATURE_COLUMNS = (
    "stock_close",
    "s_day_return_pct",
    "s_minus_1_return_pct",
    "pre_s_return_3d_pct",
    "pre_s_return_5d_pct",
    "stock_return_3d_pct",
    "stock_return_5d_pct",
    "stock_return_10d_pct",
    "stock_return_20d_pct",
    "prior_5d_return_pct",
    "return_acceleration_5d_pct",
    "ma5_gap_pct",
    "ma10_gap_pct",
    "ma20_gap_pct",
    "ma5_over_ma10_pct",
    "ma10_over_ma20_pct",
    "distance_from_prior_20d_high_pct",
    "volume_to_prior_5d_ratio",
    "volume_to_prior_20d_ratio",
    "near_limit_up_days_10d",
    "prior_near_limit_up_days_10d",
    "sessions_since_prior_near_limit_up",
    "consecutive_near_limit_up_days",
    "close_location_value",
    "concept_return_5d_pct",
    "concept_return_10d_pct",
    "stock_excess_concept_5d_pct",
    "stock_excess_concept_10d_pct",
    "market_return_5d_pct",
    "market_return_10d_pct",
    "stock_excess_market_5d_pct",
    "stock_excess_market_10d_pct",
)
PAIR_COMPARISON_COLUMNS = (
    "limit_times",
    "limit_up_suc_rate",
    "seal_strength",
    "amount",
    *FEATURE_COLUMNS,
)


def build_spell_identities(candidates: pd.DataFrame) -> pd.DataFrame:
    """Return the earliest raw recognition row for every leader spell."""

    _require_columns(candidates, RECOGNITION_COLUMNS, "recognition candidate")
    _reject_feature_leakage(candidates)
    frame = candidates.loc[:, list(RECOGNITION_COLUMNS)].copy()
    frame["source_date"] = pd.to_datetime(
        frame["source_date"], errors="raise"
    ).dt.normalize()
    for column in ("sector_id", "concept_name", "cycle_id", "vt_symbol", "stock_name"):
        frame[column] = frame[column].astype(str).str.strip()
        if frame[column].eq("").any():
            raise ValueError(f"recognition candidate {column} must not be empty")
    if frame["event_id"].isna().any():
        raise ValueError("recognition event IDs must not be null")
    frame["leader_spell_id"] = (
        frame["sector_id"] + ":" + frame["cycle_id"] + ":" + frame["vt_symbol"]
    )

    stable_identity = ("sector_id", "concept_name", "cycle_id", "vt_symbol", "stock_name")
    conflicts = frame.groupby("leader_spell_id", sort=False)[list(stable_identity)].nunique(
        dropna=False
    )
    if conflicts.gt(1).any(axis=None):
        raise ValueError("conflicting spell identity")

    frame = frame.sort_values(
        ["source_date", "event_id", "sector_id", "recognition_rank", "vt_symbol"],
        kind="stable",
    ).drop_duplicates("leader_spell_id", keep="first")
    frame = frame.rename(
        columns={
            "event_id": "recognition_event_id",
            "source_date": "recognition_source_date",
        }
    )
    frame["rank_mode"] = "event_recognition_proxy"
    return frame.loc[:, list(SPELL_IDENTITY_COLUMNS)].sort_values(
        [
            "recognition_source_date",
            "sector_id",
            "recognition_rank",
            "vt_symbol",
        ],
        kind="stable",
    ).reset_index(drop=True)


def build_spell_feature_ledger(
    spells: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    market_returns: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> pd.DataFrame:
    """Attach only S-close and earlier structural descriptors to each spell."""

    _require_columns(spells, SPELL_IDENTITY_COLUMNS, "leader spell")
    _reject_feature_leakage(spells, stock_bars, concept_bars, market_returns)
    calendar = _prepare_calendar(trading_dates)
    stock_features = _build_stock_feature_panel(stock_bars, calendar)
    concept_features = _build_concept_feature_panel(concept_bars, calendar)
    market_features = _build_market_feature_panel(market_returns, calendar)

    result = spells.copy()
    result["recognition_source_date"] = pd.to_datetime(
        result["recognition_source_date"], errors="raise"
    ).dt.normalize()
    result = result.merge(
        stock_features,
        left_on=["vt_symbol", "recognition_source_date"],
        right_on=["vt_symbol", "trade_date"],
        how="left",
        validate="one_to_one",
    ).drop(columns=["trade_date"])
    result = result.merge(
        concept_features,
        left_on=["sector_id", "recognition_source_date"],
        right_on=["sector_id", "trade_date"],
        how="left",
        validate="many_to_one",
    ).drop(columns=["trade_date"])
    result = result.merge(
        market_features,
        left_on="recognition_source_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
    ).drop(columns=["trade_date"])

    result["stock_excess_concept_5d_pct"] = (
        result["stock_return_5d_pct"] - result["concept_return_5d_pct"]
    )
    result["stock_excess_concept_10d_pct"] = (
        result["stock_return_10d_pct"] - result["concept_return_10d_pct"]
    )
    result["stock_excess_market_5d_pct"] = (
        result["stock_return_5d_pct"] - result["market_return_5d_pct"]
    )
    result["stock_excess_market_10d_pct"] = (
        result["stock_return_10d_pct"] - result["market_return_10d_pct"]
    )
    signal_close = pd.to_numeric(result["signal_close"], errors="coerce")
    stock_close = pd.to_numeric(result["stock_close"], errors="coerce")
    result["recognition_close_matches"] = (
        signal_close.notna()
        & stock_close.notna()
        & np.isclose(signal_close, stock_close, rtol=0, atol=1e-8)
    )
    numeric = result.loc[:, list(FEATURE_COLUMNS)].apply(pd.to_numeric, errors="coerce")
    complete = numeric.notna().all(axis=1) & np.isfinite(
        numeric.to_numpy(dtype=float)
    ).all(axis=1)
    result["feature_complete"] = complete
    result["feature_status"] = np.where(
        complete,
        "complete",
        "incomplete_s_history",
    )
    result["feature_cutoff_date"] = result["recognition_source_date"]
    ordered_columns = (
        *SPELL_IDENTITY_COLUMNS,
        *FEATURE_COLUMNS,
        "recognition_close_matches",
        "feature_complete",
        "feature_status",
        "feature_cutoff_date",
    )
    return result.loc[:, list(ordered_columns)].sort_values(
        [
            "recognition_source_date",
            "sector_id",
            "recognition_rank",
            "vt_symbol",
        ],
        kind="stable",
    ).reset_index(drop=True)


def build_spell_trajectories(
    spells: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    market_returns: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
    history_sessions: int = 20,
    future_sessions: int = 5,
) -> pd.DataFrame:
    """Return S-20..S+5 rows for individual inspection."""

    _require_columns(spells, SPELL_IDENTITY_COLUMNS, "leader spell")
    if history_sessions < 1 or future_sessions < 1:
        raise ValueError("history and future sessions must be positive")
    calendar = _prepare_calendar(trading_dates)
    positions = {value: index for index, value in enumerate(calendar)}
    stocks = _prepare_stock_bars(stock_bars)
    concepts = _prepare_concept_bars(concept_bars)
    market = _prepare_market_returns(market_returns)

    stock_index = {
        (str(row.vt_symbol), pd.Timestamp(row.trade_date)): row
        for row in stocks.itertuples(index=False)
    }
    concept_index = {
        (str(row.sector_id), pd.Timestamp(row.trade_date)): row
        for row in concepts.itertuples(index=False)
    }
    market_index = {
        pd.Timestamp(row.trade_date): row for row in market.itertuples(index=False)
    }
    rows: list[dict[str, Any]] = []
    for spell in spells.sort_values(
        ["recognition_source_date", "leader_spell_id"], kind="stable"
    ).to_dict("records"):
        source_date = pd.Timestamp(spell["recognition_source_date"]).normalize()
        source_position = positions.get(source_date)
        if source_position is None:
            raise ValueError("recognition date must exist in the trading calendar")
        source_stock = stock_index.get((str(spell["vt_symbol"]), source_date))
        source_concept = concept_index.get((str(spell["sector_id"]), source_date))
        source_market = market_index.get(source_date)
        source_stock_close = _positive_value(source_stock, "close_price")
        source_concept_close = _positive_value(source_concept, "close_price")
        source_market_level = _positive_value(source_market, "market_level")
        for offset in range(-history_sessions, future_sessions + 1):
            position = source_position + offset
            if position < 0 or position >= len(calendar):
                rows.append(
                    _trajectory_row(
                        spell,
                        trade_date=None,
                        session_offset=offset,
                        row_status="outside_calendar",
                    )
                )
                continue
            trade_date = calendar[position]
            stock = stock_index.get((str(spell["vt_symbol"]), trade_date))
            concept = concept_index.get((str(spell["sector_id"]), trade_date))
            market_row = market_index.get(trade_date)
            if stock is None:
                status = "missing_stock_bar"
            elif concept is None:
                status = "missing_concept_bar"
            elif market_row is None:
                status = "missing_market_return"
            else:
                status = "complete"
            stock_close = _positive_value(stock, "close_price")
            concept_close = _positive_value(concept, "close_price")
            market_level = _positive_value(market_row, "market_level")
            rows.append(
                {
                    **_trajectory_row(
                        spell,
                        trade_date=trade_date,
                        session_offset=offset,
                        row_status=status,
                    ),
                    "open_price": _numeric_value(stock, "open_price"),
                    "high_price": _numeric_value(stock, "high_price"),
                    "low_price": _numeric_value(stock, "low_price"),
                    "close_price": stock_close,
                    "volume": _numeric_value(stock, "volume"),
                    "stock_daily_return_pct": _pct_value(stock, "stock_daily_return"),
                    "stock_return_from_s_pct": _relative_return(
                        stock_close, source_stock_close
                    ),
                    "concept_close_price": concept_close,
                    "concept_daily_return_pct": _pct_value(
                        concept, "concept_daily_return"
                    ),
                    "concept_return_from_s_pct": _relative_return(
                        concept_close, source_concept_close
                    ),
                    "market_daily_return_pct": _pct_value(
                        market_row, "market_daily_return"
                    ),
                    "market_return_from_s_pct": _relative_return(
                        market_level, source_market_level
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["recognition_source_date", "leader_spell_id", "session_offset"],
        kind="stable",
    ).reset_index(drop=True)


def build_spell_outcome_labels(
    spells: pd.DataFrame,
    trajectories: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize S+1..S+5 paths without exposing them to feature construction."""

    _require_columns(spells, ("leader_spell_id",), "leader spell")
    _require_columns(
        trajectories,
        (
            "leader_spell_id",
            "session_offset",
            "close_price",
            "stock_return_from_s_pct",
            "row_status",
        ),
        "leader trajectory",
    )
    rows = []
    trajectory_groups = {
        str(key): group.sort_values("session_offset", kind="stable")
        for key, group in trajectories.groupby("leader_spell_id", sort=False)
    }
    for leader_spell_id in spells["leader_spell_id"].astype(str):
        group = trajectory_groups.get(leader_spell_id, pd.DataFrame())
        future = group.loc[
            group["session_offset"].between(1, 5)
            & group["row_status"].eq("complete")
        ].copy()
        future["close_price"] = pd.to_numeric(
            future["close_price"], errors="coerce"
        )
        future["stock_return_from_s_pct"] = pd.to_numeric(
            future["stock_return_from_s_pct"], errors="coerce"
        )
        future = future.dropna(subset=["close_price", "stock_return_from_s_pct"])
        future_sessions = int(future["session_offset"].nunique())
        complete = future_sessions == 5 and set(future["session_offset"].astype(int)) == {
            1,
            2,
            3,
            4,
            5,
        }
        if complete:
            close_return = float(
                future.loc[future["session_offset"].eq(5), "stock_return_from_s_pct"].item()
            )
            max_close_return = float(future["stock_return_from_s_pct"].max())
            path = group.loc[
                group["session_offset"].between(0, 5), "close_price"
            ].pipe(pd.to_numeric, errors="coerce").dropna()
            running_high = path.cummax()
            max_drawdown = float(((path / running_high) - 1.0).min() * 100.0)
            status = "complete"
        else:
            close_return = None
            max_close_return = None
            max_drawdown = None
            status = "incomplete_future_path"
        rows.append(
            {
                "leader_spell_id": leader_spell_id,
                "future_5d_close_return_pct": close_return,
                "future_5d_max_close_return_pct": max_close_return,
                "future_5d_max_drawdown_pct": max_drawdown,
                "future_sessions_available": future_sessions,
                "outcome_status": status,
            }
        )
    return pd.DataFrame(rows).sort_values("leader_spell_id", kind="stable").reset_index(
        drop=True
    )


def build_matched_spell_pairs(cases: pd.DataFrame) -> pd.DataFrame:
    """Pair strongest and weakest future paths within the same S date/concept."""

    required = (
        "leader_spell_id",
        "recognition_source_date",
        "sector_id",
        "concept_name",
        "vt_symbol",
        "stock_name",
        "recognition_rank",
        "future_5d_close_return_pct",
        "outcome_status",
    )
    _require_columns(cases, required, "labeled leader case")
    frame = cases.copy()
    frame["recognition_source_date"] = pd.to_datetime(
        frame["recognition_source_date"], errors="raise"
    ).dt.normalize()
    frame["future_5d_close_return_pct"] = pd.to_numeric(
        frame["future_5d_close_return_pct"], errors="coerce"
    )
    frame = frame.loc[
        frame["outcome_status"].eq("complete")
        & frame["future_5d_close_return_pct"].notna()
    ].copy()
    rows = []
    for (source_date, sector_id), group in frame.groupby(
        ["recognition_source_date", "sector_id"], sort=True
    ):
        if group["vt_symbol"].astype(str).nunique() < 2:
            continue
        if not group["future_5d_close_return_pct"].gt(0).any():
            continue
        if not group["future_5d_close_return_pct"].le(0).any():
            continue
        winner = group.sort_values(
            ["future_5d_close_return_pct", "recognition_rank", "vt_symbol"],
            ascending=[False, True, True],
            kind="stable",
        ).iloc[0]
        loser = group.sort_values(
            ["future_5d_close_return_pct", "recognition_rank", "vt_symbol"],
            ascending=[True, True, True],
            kind="stable",
        ).iloc[0]
        row: dict[str, Any] = {
            "pair_id": (
                f"{pd.Timestamp(source_date).date().isoformat()}:{sector_id}:"
                f"{winner['vt_symbol']}:{loser['vt_symbol']}"
            ),
            "recognition_source_date": pd.Timestamp(source_date),
            "sector_id": str(sector_id),
            "concept_name": str(winner["concept_name"]),
            "active_direction": str(winner.get("active_direction") or "UNKNOWN"),
            "danger_state": str(winner.get("danger_state") or "UNKNOWN"),
            "winner_leader_spell_id": str(winner["leader_spell_id"]),
            "winner_vt_symbol": str(winner["vt_symbol"]),
            "winner_stock_name": str(winner["stock_name"]),
            "winner_recognition_rank": int(winner["recognition_rank"]),
            "winner_future_5d_close_return_pct": float(
                winner["future_5d_close_return_pct"]
            ),
            "loser_leader_spell_id": str(loser["leader_spell_id"]),
            "loser_vt_symbol": str(loser["vt_symbol"]),
            "loser_stock_name": str(loser["stock_name"]),
            "loser_recognition_rank": int(loser["recognition_rank"]),
            "loser_future_5d_close_return_pct": float(
                loser["future_5d_close_return_pct"]
            ),
            "future_5d_return_spread_pct": float(
                winner["future_5d_close_return_pct"]
                - loser["future_5d_close_return_pct"]
            ),
        }
        for column in PAIR_COMPARISON_COLUMNS:
            if column in frame:
                row[f"winner_{column}"] = _optional_float(winner.get(column))
                row[f"loser_{column}"] = _optional_float(loser.get(column))
        rows.append(row)
    if not rows:
        return pd.DataFrame(
            columns=[
                "pair_id",
                "recognition_source_date",
                "sector_id",
                "concept_name",
                "winner_stock_name",
                "loser_stock_name",
                "future_5d_return_spread_pct",
            ]
        )
    return pd.DataFrame(rows).sort_values(
        [
            "recognition_source_date",
            "sector_id",
            "winner_vt_symbol",
            "loser_vt_symbol",
        ],
        kind="stable",
    ).reset_index(drop=True)


def build_individual_leader_report(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    pairs: pd.DataFrame,
    trajectories: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a machine report that preserves actual stock-level evidence."""

    _require_columns(features, (*SPELL_IDENTITY_COLUMNS, *FEATURE_COLUMNS), "feature")
    _require_columns(
        labels,
        (
            "leader_spell_id",
            "future_5d_close_return_pct",
            "future_5d_max_close_return_pct",
            "future_5d_max_drawdown_pct",
            "outcome_status",
        ),
        "outcome label",
    )
    cases = features.merge(labels, on="leader_spell_id", validate="one_to_one")
    cases = cases.sort_values(
        ["recognition_source_date", "sector_id", "recognition_rank", "vt_symbol"],
        kind="stable",
    ).reset_index(drop=True)
    complete = cases.loc[cases["outcome_status"].eq("complete")].copy()
    complete["future_5d_close_return_pct"] = pd.to_numeric(
        complete["future_5d_close_return_pct"], errors="coerce"
    )
    top = complete.sort_values(
        ["future_5d_close_return_pct", "recognition_source_date", "vt_symbol"],
        ascending=[False, True, True],
        kind="stable",
    ).head(20)
    bottom = complete.sort_values(
        ["future_5d_close_return_pct", "recognition_source_date", "vt_symbol"],
        ascending=[True, True, True],
        kind="stable",
    ).head(20)
    repeated = _build_repeated_stock_summary(cases)
    regime = _build_regime_summary(cases)
    tails = _build_tail_feature_profiles(cases)
    overall_path_summary = _build_overall_path_summary(cases)
    rank_summary = _build_dimension_path_summary(cases, "recognition_rank")
    limit_times_summary = _build_dimension_path_summary(cases, "limit_times")
    pair_directions = _build_matched_pair_direction_summary(pairs)
    phase_shapes = _build_phase_shape_summary(cases)
    protocol = default_protocol()
    coverage = dict(metadata.get("coverage", {}))
    coverage.setdefault("leader_spells", int(len(cases)))
    coverage.setdefault("unique_stocks", int(cases["vt_symbol"].nunique()))
    coverage.setdefault("unique_concepts", int(cases["sector_id"].nunique()))
    coverage.setdefault("complete_features", int(cases["feature_complete"].sum()))
    coverage.setdefault("complete_outcomes", int(cases["outcome_status"].eq("complete").sum()))
    coverage.setdefault("matched_pairs", int(len(pairs)))
    coverage.setdefault("trajectory_rows", int(len(trajectories)))
    return {
        "protocol_version": protocol.version,
        "protocol_hash": protocol_hash(protocol),
        "evidence_level": STUDY_EVIDENCE_LEVEL,
        "overall_conclusion": "individual_spell_evidence_ready",
        "formal_metrics": None,
        "formal_rule_selected": False,
        "phase_contract_selected": False,
        "strict_top3_claim": False,
        "holdout_price_values_read": False,
        "current_membership_rows_read": 0,
        "limit_up_strategy_rows_read": 0,
        "minute_rows_read": 0,
        "old_low_suction_trade_rows_read": 0,
        "frozen_contract": {
            "research_unit": "earliest (sector_id, cycle_id, vt_symbol) recognition spell",
            "feature_cutoff": "recognition date S close",
            "history_sessions": 20,
            "future_label_sessions": 5,
            "universe": "raw event-recognition proxy before neutral-day collision removal",
            "matched_pair_identity": ["recognition_source_date", "sector_id"],
            "matched_pair_selection": "maximum versus minimum S+5 close return with stable ties",
            "outcomes_are_features": False,
            "strict_historical_top3": False,
        },
        "coverage": coverage,
        "input_fingerprints": dict(metadata.get("input_fingerprints", {})),
        "overall_path_summary": overall_path_summary,
        "recognition_rank_summary": _records(rank_summary),
        "limit_times_summary": _records(limit_times_summary),
        "matched_pair_direction_summary": _records(pair_directions),
        "phase_shape_summary": _records(phase_shapes),
        "individual_cases": _records(cases),
        "individual_trajectories": _records(trajectories),
        "top_20_future_paths": _records(top),
        "bottom_20_future_paths": _records(bottom),
        "matched_pairs": _records(pairs),
        "repeated_stock_summary": _records(repeated),
        "regime_summary": _records(regime),
        "outcome_tail_feature_profiles": _records(tails),
        "limitations": [
            "event reasons cover an incomplete and non-random subset of concept members",
            "recognition ranks are not strict historical concept Top3 ranks",
            "future paths are descriptive labels and cannot enter S-close features",
            "repeated spells for one stock are not independent statistical samples",
            "no entry rule, formal return, compounding or production decision is selected",
        ],
    }


def load_individual_leader_study_data() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
]:
    """Load frozen proxy spells and build features, labels, pairs and trajectories."""

    from .concept_cycles import load_cycle_research_inputs
    from .event_recognition_falsification import load_event_falsification_inputs

    event_inputs = load_event_falsification_inputs()
    cycle_inputs = load_cycle_research_inputs()
    if cycle_inputs.split.discovery_dates[-1] != event_inputs.discovery_end:
        raise ValueError("event and cycle discovery boundaries must match")
    spells = build_spell_identities(event_inputs.candidates)
    features = build_spell_feature_ledger(
        spells,
        event_inputs.stock_bars,
        cycle_inputs.concept_bars,
        cycle_inputs.market_returns,
        trading_dates=event_inputs.trading_dates,
    )
    trajectories = build_spell_trajectories(
        spells,
        event_inputs.stock_bars,
        cycle_inputs.concept_bars,
        cycle_inputs.market_returns,
        trading_dates=event_inputs.trading_dates,
    )
    labels = build_spell_outcome_labels(spells, trajectories)
    cases = features.merge(labels, on="leader_spell_id", validate="one_to_one")
    pairs = build_matched_spell_pairs(cases)
    trajectory_status = trajectories["row_status"].value_counts(dropna=False).sort_index()
    coverage = {
        **dict(event_inputs.coverage),
        "leader_spells": int(len(spells)),
        "unique_stocks": int(spells["vt_symbol"].nunique()),
        "unique_concepts": int(spells["sector_id"].nunique()),
        "complete_features": int(features["feature_complete"].sum()),
        "complete_outcomes": int(labels["outcome_status"].eq("complete").sum()),
        "matched_pairs": int(len(pairs)),
        "trajectory_rows": int(len(trajectories)),
        "trajectory_status_counts": {
            str(key): int(value) for key, value in trajectory_status.items()
        },
        "gold_spells": int(spells["active_direction"].eq("GOLD").sum()),
        "silver_spells": int(spells["active_direction"].eq("SILVER").sum()),
        "holdout_price_values_read": False,
        "current_membership_rows_read": 0,
        "limit_up_strategy_rows_read": 0,
        "minute_rows_read": 0,
        "old_low_suction_trade_rows_read": 0,
    }
    cycle_fingerprints = {
        name: fingerprint.as_dict()
        for name, fingerprint in cycle_inputs.component_fingerprints
    }
    input_fingerprints = {
        **dict(event_inputs.input_fingerprints),
        **cycle_fingerprints,
        "individual_leader_spell_identities": fingerprint_frame(
            spells,
            identity_columns=("leader_spell_id",),
        ).as_dict(),
        "individual_leader_features": fingerprint_frame(
            features,
            identity_columns=("leader_spell_id",),
        ).as_dict(),
        "individual_leader_labels": fingerprint_frame(
            labels,
            identity_columns=("leader_spell_id",),
        ).as_dict(),
        "individual_leader_pairs": fingerprint_frame(
            pairs,
            identity_columns=("pair_id",),
        ).as_dict(),
        "individual_leader_trajectories": fingerprint_frame(
            trajectories,
            identity_columns=("leader_spell_id", "session_offset"),
        ).as_dict(),
    }
    metadata = {
        "coverage": coverage,
        "input_fingerprints": input_fingerprints,
        "discovery_start": event_inputs.discovery_start,
        "discovery_end": event_inputs.discovery_end,
    }
    return features, labels, pairs, trajectories, metadata


def run_individual_leader_study() -> dict[str, Any]:
    features, labels, pairs, trajectories, metadata = (
        load_individual_leader_study_data()
    )
    return build_individual_leader_report(
        features,
        labels,
        pairs,
        trajectories,
        metadata,
    )


def render_individual_leader_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def render_individual_leader_markdown(report: Mapping[str, Any]) -> str:
    coverage = report["coverage"]
    lines = [
        "# Low-suction Individual Main-rise Leader Spell Study",
        "",
        f"- Conclusion: `{report['overall_conclusion']}`",
        "- Evidence: event-recognition proxy, not strict historical Top3",
        "- Formal rule/phase contract: `false/false`",
        f"- Recognition candidates/leader spells: `{coverage.get('recognition_candidates', 0)}/"
        f"{coverage.get('leader_spells', 0)}`",
        f"- Stocks/concepts/matched pairs: `{coverage.get('unique_stocks', 0)}/"
        f"{coverage.get('unique_concepts', 0)}/{coverage.get('matched_pairs', 0)}`",
        f"- Complete S features/S+5 labels: `{coverage.get('complete_features', 0)}/"
        f"{coverage.get('complete_outcomes', 0)}`",
        "",
        "## Individual Evidence Summary",
        "",
        f"- Complete spell S+5 positive share/mean/median: "
        f"`{_pct(report['overall_path_summary'].get('positive_s5_share_pct'))}/"
        f"{_pct(report['overall_path_summary'].get('mean_future_5d_close_return_pct'))}/"
        f"{_pct(report['overall_path_summary'].get('median_future_5d_close_return_pct'))}`",
        "- Path returns start at S close and are descriptive, not executable trade returns.",
        "",
        "### Natural Phase Shapes",
        "",
        "| Shape | Segment | Spells | Days | Positive S+5 | Mean | Median | Max close | Drawdown |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["phase_shape_summary"]:
        lines.append(
            f"| `{row.get('shape')}` | `{row.get('segment')}` | {row.get('spells')} | "
            f"{row.get('source_days')} | {_pct(row.get('positive_s5_share_pct'))} | "
            f"{_pct(row.get('mean_future_5d_close_return_pct'))} | "
            f"{_pct(row.get('median_future_5d_close_return_pct'))} | "
            f"{_pct(row.get('mean_future_5d_max_close_return_pct'))} | "
            f"{_pct(row.get('mean_future_5d_max_drawdown_pct'))} |"
        )
    lines.extend(
        [
            "",
            "### Same-concept Direction Checks",
            "",
            "| S feature | Unequal pairs | Winner higher | Median winner-loser | Two-sided sign p |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    shown_direction_features = {
        "recognition_rank",
        "limit_times",
        "pre_s_return_5d_pct",
        "return_acceleration_5d_pct",
        "ma5_gap_pct",
        "sessions_since_prior_near_limit_up",
        "volume_to_prior_5d_ratio",
    }
    for row in report["matched_pair_direction_summary"]:
        if row.get("feature") not in shown_direction_features:
            continue
        lines.append(
            f"| `{row.get('feature')}` | {row.get('unequal_pairs')} | "
            f"{_pct(row.get('winner_higher_share_pct'))} | "
            f"{_number(row.get('median_winner_minus_loser'))} | "
            f"{_number(row.get('two_sided_sign_p_value'))} |"
        )
    lines.extend(
        [
            "",
            "## Strongest Individual S+5 Paths",
            "",
            "| S date | Stock | Concept | Rank | Regime | S 5d | Accel | Excess concept | Volume | S+5 close | Max | Drawdown |",
            "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["top_20_future_paths"]:
        lines.append(_case_markdown_row(row))
    lines.extend(
        [
            "",
            "## Weakest Individual S+5 Paths",
            "",
            "| S date | Stock | Concept | Rank | Regime | S 5d | Accel | Excess concept | Volume | S+5 close | Max | Drawdown |",
            "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["bottom_20_future_paths"]:
        lines.append(_case_markdown_row(row))
    lines.extend(
        [
            "",
            "## Same-date Same-concept Matched Cases",
            "",
            "| S date | Concept | Winner | Rank | S+5 | Loser | Rank | S+5 | Spread | Regime |",
            "| --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: | --- |",
        ]
    )
    sorted_pairs = sorted(
        report["matched_pairs"],
        key=lambda row: float(row.get("future_5d_return_spread_pct") or 0),
        reverse=True,
    )
    for row in sorted_pairs[:20]:
        lines.append(
            f"| {row.get('recognition_source_date')} | {row.get('concept_name')} | "
            f"{row.get('winner_stock_name')} ({row.get('winner_vt_symbol')}) | "
            f"{row.get('winner_recognition_rank')} | "
            f"{_pct(row.get('winner_future_5d_close_return_pct'))} | "
            f"{row.get('loser_stock_name')} ({row.get('loser_vt_symbol')}) | "
            f"{row.get('loser_recognition_rank')} | "
            f"{_pct(row.get('loser_future_5d_close_return_pct'))} | "
            f"{_pct(row.get('future_5d_return_spread_pct'))} | "
            f"`{row.get('active_direction')}/{row.get('danger_state')}` |"
        )
    lines.extend(
        [
            "",
            "## Repeated Stocks",
            "",
            "| Stock | Spells | Concepts | Positive S+5 | Mean S+5 | First | Last |",
            "| --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in report["repeated_stock_summary"][:20]:
        lines.append(
            f"| {row.get('stock_name')} ({row.get('vt_symbol')}) | {row.get('spells')} | "
            f"{row.get('concepts')} | {_pct(row.get('positive_s5_share_pct'))} | "
            f"{_pct(row.get('mean_future_5d_close_return_pct'))} | "
            f"{row.get('first_recognition_date')} | {row.get('last_recognition_date')} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "本报告首次保留真实股票名称、认可日、概念、逐股 S-20..S+5 轨迹和同概念配对。",
            "未来五日只作标签；报告不选择阶段阈值、买点或正式规则。事件原因不是完整成员分母，",
            "认可 Rank 也不是严格历史 Top3。完整逐股账本和全部轨迹在同名 JSON 中。",
            "",
        ]
    )
    return "\n".join(lines)


def _build_overall_path_summary(cases: pd.DataFrame) -> dict[str, Any]:
    complete = cases.loc[cases["outcome_status"].eq("complete")]
    values = pd.to_numeric(
        complete["future_5d_close_return_pct"], errors="coerce"
    ).dropna()
    return {
        "complete_spells": int(len(values)),
        "unique_stocks": int(complete["vt_symbol"].nunique()),
        "source_days": int(
            pd.to_datetime(complete["recognition_source_date"]).dt.date.nunique()
        ),
        "positive_s5_share_pct": (
            float(values.gt(0).mean() * 100.0) if len(values) else None
        ),
        "mean_future_5d_close_return_pct": (
            float(values.mean()) if len(values) else None
        ),
        "median_future_5d_close_return_pct": (
            float(values.median()) if len(values) else None
        ),
        "bottom_quartile_boundary_pct": (
            float(values.quantile(0.25)) if len(values) else None
        ),
        "top_quartile_boundary_pct": (
            float(values.quantile(0.75)) if len(values) else None
        ),
    }


def _build_dimension_path_summary(cases: pd.DataFrame, dimension: str) -> pd.DataFrame:
    _require_columns(cases, (dimension,), "dimension summary")
    rows = []
    complete = cases.loc[cases["outcome_status"].eq("complete")]
    for value, group in complete.groupby(dimension, sort=True, dropna=False):
        summary = _summarize_case_paths(group)
        rows.append({"dimension": dimension, "value": value, **summary})
    return pd.DataFrame(rows)


def _build_matched_pair_direction_summary(pairs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for feature in ("recognition_rank", *PAIR_COMPARISON_COLUMNS):
        winner_column = f"winner_{feature}"
        loser_column = f"loser_{feature}"
        if winner_column not in pairs or loser_column not in pairs:
            continue
        winner = pd.to_numeric(pairs[winner_column], errors="coerce")
        loser = pd.to_numeric(pairs[loser_column], errors="coerce")
        valid = winner.notna() & loser.notna() & winner.ne(loser)
        differences = winner.loc[valid] - loser.loc[valid]
        unequal_pairs = int(len(differences))
        winner_higher = int(differences.gt(0).sum())
        rows.append(
            {
                "feature": feature,
                "unequal_pairs": unequal_pairs,
                "winner_higher_pairs": winner_higher,
                "winner_higher_share_pct": (
                    float(winner_higher / unequal_pairs * 100.0)
                    if unequal_pairs
                    else None
                ),
                "median_winner_minus_loser": (
                    float(differences.median()) if unequal_pairs else None
                ),
                "mean_winner_minus_loser": (
                    float(differences.mean()) if unequal_pairs else None
                ),
                "two_sided_sign_p_value": _two_sided_sign_p_value(
                    winner_higher,
                    unequal_pairs,
                ),
            }
        )
    return pd.DataFrame(rows)


def _build_phase_shape_summary(cases: pd.DataFrame) -> pd.DataFrame:
    from .event_recognition_falsification import chronological_event_blocks

    complete = cases.loc[cases["outcome_status"].eq("complete")].copy()
    complete["recognition_source_date"] = pd.to_datetime(
        complete["recognition_source_date"], errors="raise"
    ).dt.normalize()
    source_dates = tuple(complete["recognition_source_date"].dt.date.unique())
    block_count = min(5, len(source_dates))
    if not block_count:
        return pd.DataFrame()
    blocks = chronological_event_blocks(
        source_dates,
        block_count=block_count,
    ).rename(columns={"source_date": "recognition_source_date"})
    blocks["recognition_source_date"] = pd.to_datetime(
        blocks["recognition_source_date"]
    ).dt.normalize()
    complete = complete.merge(
        blocks,
        on="recognition_source_date",
        how="left",
        validate="many_to_one",
    )
    limit_times = pd.to_numeric(complete["limit_times"], errors="coerce")
    prior_limits = pd.to_numeric(
        complete["prior_near_limit_up_days_10d"], errors="coerce"
    )
    consecutive = pd.to_numeric(
        complete["consecutive_near_limit_up_days"], errors="coerce"
    )
    shapes = (
        (
            "first_board_no_prior_limit_10d",
            limit_times.eq(1) & prior_limits.eq(0),
        ),
        (
            "first_board_after_prior_limit",
            limit_times.eq(1) & prior_limits.gt(0),
        ),
        ("consecutive_2", consecutive.eq(2)),
        ("consecutive_3_plus", consecutive.ge(3)),
    )
    early_blocks = tuple(range(1, min(3, block_count) + 1))
    late_blocks = tuple(range(4, block_count + 1))
    segments = [("all", tuple(range(1, block_count + 1))), ("early_1_3", early_blocks)]
    if late_blocks:
        segments.append(("late_4_5", late_blocks))
    rows = []
    for shape, mask in shapes:
        shape_cases = complete.loc[mask]
        for segment, selected_blocks in segments:
            group = shape_cases.loc[shape_cases["block"].isin(selected_blocks)]
            rows.append(
                {
                    "shape": shape,
                    "segment": segment,
                    **_summarize_case_paths(group),
                }
            )
    return pd.DataFrame(rows)


def _summarize_case_paths(frame: pd.DataFrame) -> dict[str, Any]:
    close_returns = pd.to_numeric(
        frame["future_5d_close_return_pct"], errors="coerce"
    ).dropna()
    max_returns = pd.to_numeric(
        frame["future_5d_max_close_return_pct"], errors="coerce"
    ).dropna()
    drawdowns = pd.to_numeric(
        frame["future_5d_max_drawdown_pct"], errors="coerce"
    ).dropna()
    return {
        "spells": int(len(close_returns)),
        "unique_stocks": int(frame["vt_symbol"].nunique()),
        "source_days": int(
            pd.to_datetime(frame["recognition_source_date"]).dt.date.nunique()
        ),
        "positive_s5_share_pct": (
            float(close_returns.gt(0).mean() * 100.0)
            if len(close_returns)
            else None
        ),
        "mean_future_5d_close_return_pct": (
            float(close_returns.mean()) if len(close_returns) else None
        ),
        "median_future_5d_close_return_pct": (
            float(close_returns.median()) if len(close_returns) else None
        ),
        "mean_future_5d_max_close_return_pct": (
            float(max_returns.mean()) if len(max_returns) else None
        ),
        "mean_future_5d_max_drawdown_pct": (
            float(drawdowns.mean()) if len(drawdowns) else None
        ),
    }


def _two_sided_sign_p_value(successes: int, trials: int) -> float | None:
    if trials <= 0:
        return None
    tail = min(successes, trials - successes)
    probability = sum(math.comb(trials, value) for value in range(tail + 1)) / (
        2**trials
    )
    return float(min(1.0, probability * 2.0))


def _build_repeated_stock_summary(cases: pd.DataFrame) -> pd.DataFrame:
    frame = cases.copy()
    frame["future_5d_close_return_pct"] = pd.to_numeric(
        frame["future_5d_close_return_pct"], errors="coerce"
    )
    frame["complete_outcome"] = frame["outcome_status"].eq("complete")
    frame["positive_outcome"] = (
        frame["complete_outcome"] & frame["future_5d_close_return_pct"].gt(0)
    )
    rows = []
    for (symbol, stock_name), group in frame.groupby(
        ["vt_symbol", "stock_name"], sort=True
    ):
        if len(group) < 2:
            continue
        complete = group.loc[group["complete_outcome"]]
        rows.append(
            {
                "vt_symbol": str(symbol),
                "stock_name": str(stock_name),
                "spells": int(len(group)),
                "concepts": int(group["sector_id"].nunique()),
                "complete_outcomes": int(len(complete)),
                "positive_s5_share_pct": (
                    float(complete["future_5d_close_return_pct"].gt(0).mean() * 100.0)
                    if len(complete)
                    else None
                ),
                "mean_future_5d_close_return_pct": (
                    float(complete["future_5d_close_return_pct"].mean())
                    if len(complete)
                    else None
                ),
                "first_recognition_date": pd.to_datetime(
                    group["recognition_source_date"]
                ).min(),
                "last_recognition_date": pd.to_datetime(
                    group["recognition_source_date"]
                ).max(),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["spells", "vt_symbol"], ascending=[False, True], kind="stable"
    ).reset_index(drop=True)


def _build_regime_summary(cases: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (direction, danger), group in cases.groupby(
        ["active_direction", "danger_state"], sort=True
    ):
        complete = group.loc[group["outcome_status"].eq("complete")].copy()
        close_returns = pd.to_numeric(
            complete["future_5d_close_return_pct"], errors="coerce"
        ).dropna()
        max_returns = pd.to_numeric(
            complete["future_5d_max_close_return_pct"], errors="coerce"
        ).dropna()
        drawdowns = pd.to_numeric(
            complete["future_5d_max_drawdown_pct"], errors="coerce"
        ).dropna()
        rows.append(
            {
                "active_direction": str(direction),
                "danger_state": str(danger),
                "spells": int(len(group)),
                "unique_stocks": int(group["vt_symbol"].nunique()),
                "source_days": int(
                    pd.to_datetime(group["recognition_source_date"]).dt.date.nunique()
                ),
                "complete_outcomes": int(len(close_returns)),
                "positive_s5_share_pct": (
                    float(close_returns.gt(0).mean() * 100.0)
                    if len(close_returns)
                    else None
                ),
                "mean_future_5d_close_return_pct": (
                    float(close_returns.mean()) if len(close_returns) else None
                ),
                "mean_future_5d_max_close_return_pct": (
                    float(max_returns.mean()) if len(max_returns) else None
                ),
                "mean_future_5d_max_drawdown_pct": (
                    float(drawdowns.mean()) if len(drawdowns) else None
                ),
            }
        )
    return pd.DataFrame(rows)


def _build_tail_feature_profiles(cases: pd.DataFrame) -> pd.DataFrame:
    complete = cases.loc[cases["outcome_status"].eq("complete")].copy()
    returns = pd.to_numeric(complete["future_5d_close_return_pct"], errors="coerce")
    complete = complete.loc[returns.notna()].copy()
    returns = returns.loc[returns.notna()]
    if complete.empty:
        return pd.DataFrame()
    lower = float(returns.quantile(0.25))
    upper = float(returns.quantile(0.75))
    rows = []
    for tail, mask in (
        ("bottom_quartile", returns.le(lower)),
        ("top_quartile", returns.ge(upper)),
    ):
        group = complete.loc[mask]
        row: dict[str, Any] = {
            "tail": tail,
            "spells": int(len(group)),
            "unique_stocks": int(group["vt_symbol"].nunique()),
            "return_boundary_pct": lower if tail == "bottom_quartile" else upper,
        }
        for column in FEATURE_COLUMNS:
            values = pd.to_numeric(group[column], errors="coerce").dropna()
            row[f"median_{column}"] = float(values.median()) if len(values) else None
        rows.append(row)
    return pd.DataFrame(rows)


def _case_markdown_row(row: Mapping[str, Any]) -> str:
    return (
        f"| {row.get('recognition_source_date')} | {row.get('stock_name')} "
        f"({row.get('vt_symbol')}) | {row.get('concept_name')} | "
        f"{row.get('recognition_rank')} | "
        f"`{row.get('active_direction')}/{row.get('danger_state')}` | "
        f"{_pct(row.get('stock_return_5d_pct'))} | "
        f"{_pct(row.get('return_acceleration_5d_pct'))} | "
        f"{_pct(row.get('stock_excess_concept_5d_pct'))} | "
        f"{_number(row.get('volume_to_prior_5d_ratio'))} | "
        f"{_pct(row.get('future_5d_close_return_pct'))} | "
        f"{_pct(row.get('future_5d_max_close_return_pct'))} | "
        f"{_pct(row.get('future_5d_max_drawdown_pct'))} |"
    )


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
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, date)):
        return pd.Timestamp(value).date().isoformat()
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    return value


def _pct(value: Any) -> str:
    number = _optional_float(value)
    return "-" if number is None else f"{number:.4f}%"


def _number(value: Any) -> str:
    number = _optional_float(value)
    return "-" if number is None else f"{number:.4f}"


def _prepare_calendar(trading_dates: Sequence[date]) -> tuple[pd.Timestamp, ...]:
    calendar = pd.DatetimeIndex(
        pd.to_datetime(tuple(trading_dates), errors="raise")
    ).normalize()
    calendar = calendar.drop_duplicates().sort_values()
    if calendar.empty:
        raise ValueError("trading dates must not be empty")
    return tuple(pd.Timestamp(value) for value in calendar)


def _prepare_stock_bars(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, STOCK_BAR_COLUMNS, "stock bar")
    result = frame.loc[:, list(STOCK_BAR_COLUMNS)].copy()
    result["vt_symbol"] = result["vt_symbol"].astype(str)
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.normalize()
    if result.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock bar identities must be unique")
    for column in ("open_price", "high_price", "low_price", "close_price", "volume"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.sort_values(["vt_symbol", "trade_date"], kind="stable")
    result["stock_daily_return"] = result.groupby("vt_symbol", sort=False)[
        "close_price"
    ].pct_change(fill_method=None)
    return result.reset_index(drop=True)


def _build_stock_feature_panel(
    stock_bars: pd.DataFrame,
    calendar: Sequence[pd.Timestamp],
) -> pd.DataFrame:
    bars = _prepare_stock_bars(stock_bars)
    frames = []
    calendar_index = pd.DatetimeIndex(calendar)
    for symbol, group in bars.groupby("vt_symbol", sort=True):
        frame = group.set_index("trade_date").reindex(calendar_index)
        frame.index.name = "trade_date"
        frame["vt_symbol"] = str(symbol)
        close = pd.to_numeric(frame["close_price"], errors="coerce")
        volume = pd.to_numeric(frame["volume"], errors="coerce")
        frame["stock_close"] = close
        daily_return = close / close.shift(1) - 1.0
        frame["s_day_return_pct"] = daily_return * 100.0
        frame["s_minus_1_return_pct"] = daily_return.shift(1) * 100.0
        frame["pre_s_return_3d_pct"] = (
            close.shift(1) / close.shift(4) - 1.0
        ) * 100.0
        frame["pre_s_return_5d_pct"] = (
            close.shift(1) / close.shift(6) - 1.0
        ) * 100.0
        for sessions in (3, 5, 10, 20):
            frame[f"stock_return_{sessions}d_pct"] = (
                close / close.shift(sessions) - 1.0
            ) * 100.0
        frame["prior_5d_return_pct"] = (
            close.shift(5) / close.shift(10) - 1.0
        ) * 100.0
        frame["return_acceleration_5d_pct"] = (
            frame["stock_return_5d_pct"] - frame["prior_5d_return_pct"]
        )
        moving_averages = {}
        for sessions in (5, 10, 20):
            moving_average = close.rolling(sessions, min_periods=sessions).mean()
            moving_averages[sessions] = moving_average
            frame[f"ma{sessions}_gap_pct"] = (
                close / moving_average.where(moving_average.gt(0)) - 1.0
            ) * 100.0
        frame["ma5_over_ma10_pct"] = (
            moving_averages[5] / moving_averages[10].where(moving_averages[10].gt(0))
            - 1.0
        ) * 100.0
        frame["ma10_over_ma20_pct"] = (
            moving_averages[10] / moving_averages[20].where(moving_averages[20].gt(0))
            - 1.0
        ) * 100.0
        prior_high = close.shift(1).rolling(20, min_periods=20).max()
        frame["distance_from_prior_20d_high_pct"] = (
            close / prior_high.where(prior_high.gt(0)) - 1.0
        ) * 100.0
        for sessions in (5, 20):
            prior_volume = volume.shift(1).rolling(
                sessions, min_periods=sessions
            ).mean()
            frame[f"volume_to_prior_{sessions}d_ratio"] = volume / prior_volume.where(
                prior_volume.gt(0)
            )
        near_limit = daily_return.ge(0.095) & close.notna() & close.shift(1).notna()
        frame["near_limit_up_days_10d"] = near_limit.astype(float).rolling(
            10, min_periods=10
        ).sum()
        prior_near_limit = near_limit.shift(1, fill_value=False)
        frame["prior_near_limit_up_days_10d"] = prior_near_limit.astype(
            float
        ).rolling(10, min_periods=10).sum()
        positions = pd.Series(np.arange(len(frame), dtype=float), index=frame.index)
        last_prior_near_position = positions.where(near_limit).ffill().shift(1)
        sessions_since_prior = positions - last_prior_near_position
        frame["sessions_since_prior_near_limit_up"] = sessions_since_prior.where(
            sessions_since_prior.le(20), 21.0
        )
        frame["sessions_since_prior_near_limit_up"] = frame[
            "sessions_since_prior_near_limit_up"
        ].fillna(21.0)
        streak_group = (~near_limit).cumsum()
        frame["consecutive_near_limit_up_days"] = near_limit.astype(int).groupby(
            streak_group.to_numpy()
        ).cumsum().astype(float)
        day_range = pd.to_numeric(frame["high_price"], errors="coerce") - pd.to_numeric(
            frame["low_price"], errors="coerce"
        )
        close_location = (
            close - pd.to_numeric(frame["low_price"], errors="coerce")
        ) / day_range.where(day_range.gt(0))
        one_price_session = (
            close.notna()
            & pd.to_numeric(frame["high_price"], errors="coerce").eq(close)
            & pd.to_numeric(frame["low_price"], errors="coerce").eq(close)
        )
        frame["close_location_value"] = close_location.mask(one_price_session, 1.0)
        frames.append(
            frame.reset_index().loc[
                :,
                [
                    "vt_symbol",
                    "trade_date",
                    "stock_close",
                    "s_day_return_pct",
                    "s_minus_1_return_pct",
                    "pre_s_return_3d_pct",
                    "pre_s_return_5d_pct",
                    "stock_return_3d_pct",
                    "stock_return_5d_pct",
                    "stock_return_10d_pct",
                    "stock_return_20d_pct",
                    "prior_5d_return_pct",
                    "return_acceleration_5d_pct",
                    "ma5_gap_pct",
                    "ma10_gap_pct",
                    "ma20_gap_pct",
                    "ma5_over_ma10_pct",
                    "ma10_over_ma20_pct",
                    "distance_from_prior_20d_high_pct",
                    "volume_to_prior_5d_ratio",
                    "volume_to_prior_20d_ratio",
                    "near_limit_up_days_10d",
                    "prior_near_limit_up_days_10d",
                    "sessions_since_prior_near_limit_up",
                    "consecutive_near_limit_up_days",
                    "close_location_value",
                ],
            ]
        )
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _prepare_concept_bars(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, CONCEPT_BAR_COLUMNS, "concept bar")
    result = frame.loc[:, list(CONCEPT_BAR_COLUMNS)].copy()
    result["sector_id"] = result["sector_id"].astype(str)
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.normalize()
    result["close_price"] = pd.to_numeric(result["close_price"], errors="coerce")
    if result.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("concept bar identities must be unique")
    result = result.sort_values(["sector_id", "trade_date"], kind="stable")
    result["concept_daily_return"] = result.groupby("sector_id", sort=False)[
        "close_price"
    ].pct_change(fill_method=None)
    return result.reset_index(drop=True)


def _build_concept_feature_panel(
    concept_bars: pd.DataFrame,
    calendar: Sequence[pd.Timestamp],
) -> pd.DataFrame:
    bars = _prepare_concept_bars(concept_bars)
    frames = []
    calendar_index = pd.DatetimeIndex(calendar)
    for sector_id, group in bars.groupby("sector_id", sort=True):
        frame = group.set_index("trade_date").reindex(calendar_index)
        frame.index.name = "trade_date"
        frame["sector_id"] = str(sector_id)
        close = pd.to_numeric(frame["close_price"], errors="coerce")
        for sessions in (5, 10):
            frame[f"concept_return_{sessions}d_pct"] = (
                close / close.shift(sessions) - 1.0
            ) * 100.0
        frames.append(
            frame.reset_index().loc[
                :,
                [
                    "sector_id",
                    "trade_date",
                    "concept_return_5d_pct",
                    "concept_return_10d_pct",
                ],
            ]
        )
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _prepare_market_returns(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, MARKET_COLUMNS, "market return")
    result = frame.loc[:, list(MARKET_COLUMNS)].copy()
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.normalize()
    result["market_daily_return"] = pd.to_numeric(
        result["market_daily_return"], errors="coerce"
    )
    if result.duplicated(["trade_date"]).any():
        raise ValueError("market return identities must be unique")
    result = result.sort_values("trade_date", kind="stable")
    result["market_level"] = (1.0 + result["market_daily_return"].fillna(0.0)).cumprod()
    return result.reset_index(drop=True)


def _build_market_feature_panel(
    market_returns: pd.DataFrame,
    calendar: Sequence[pd.Timestamp],
) -> pd.DataFrame:
    market = _prepare_market_returns(market_returns).set_index("trade_date").reindex(
        pd.DatetimeIndex(calendar)
    )
    market.index.name = "trade_date"
    daily = pd.to_numeric(market["market_daily_return"], errors="coerce")
    result = market.reset_index().loc[:, ["trade_date"]]
    for sessions in (5, 10):
        result[f"market_return_{sessions}d_pct"] = (
            (1.0 + daily)
            .rolling(sessions, min_periods=sessions)
            .apply(np.prod, raw=True)
            .to_numpy()
            - 1.0
        ) * 100.0
    return result


def _trajectory_row(
    spell: Mapping[str, Any],
    *,
    trade_date: pd.Timestamp | None,
    session_offset: int,
    row_status: str,
) -> dict[str, Any]:
    return {
        **{column: spell.get(column) for column in SPELL_IDENTITY_COLUMNS},
        "trade_date": trade_date,
        "session_offset": int(session_offset),
        "known_at_s_close": bool(session_offset <= 0),
        "row_status": row_status,
    }


def _numeric_value(row: Any | None, field: str) -> float | None:
    if row is None:
        return None
    value = getattr(row, field, None)
    if value is None or pd.isna(value):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _positive_value(row: Any | None, field: str) -> float | None:
    value = _numeric_value(row, field)
    return value if value is not None and value > 0 else None


def _pct_value(row: Any | None, field: str) -> float | None:
    value = _numeric_value(row, field)
    return value * 100.0 if value is not None else None


def _relative_return(value: float | None, anchor: float | None) -> float | None:
    if value is None or anchor is None or anchor <= 0:
        return None
    return (value / anchor - 1.0) * 100.0


def _optional_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _reject_feature_leakage(*frames: pd.DataFrame) -> None:
    prohibited = set().union(
        *(PROHIBITED_FEATURE_COLUMNS & set(frame) for frame in frames)
    )
    prohibited.update(
        column
        for frame in frames
        for column in frame
        if str(column).startswith(("future_", "outcome_"))
    )
    if prohibited:
        raise ValueError(
            f"future or outcome columns are prohibited from leader features: {sorted(prohibited)}"
        )


def _require_columns(frame: pd.DataFrame, columns: Sequence[str], label: str) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
