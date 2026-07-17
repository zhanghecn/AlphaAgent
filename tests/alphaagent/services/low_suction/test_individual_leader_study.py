from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.individual_leader_study import (
    build_individual_leader_report,
    build_matched_spell_pairs,
    build_spell_feature_ledger,
    build_spell_identities,
    build_spell_outcome_labels,
    build_spell_trajectories,
    render_individual_leader_json,
)


def _calendar() -> tuple[date, ...]:
    return tuple(pd.date_range("2025-01-02", periods=35, freq="B").date)


def _recognition_candidates() -> pd.DataFrame:
    calendar = _calendar()
    rows = []
    for event_id, source_position, symbol, name, rank in (
        (10, 25, "600001.SSE", "甲公司", 1),
        (11, 26, "600001.SSE", "甲公司", 2),
        (20, 25, "600002.SSE", "乙公司", 2),
    ):
        rows.append(
            {
                "event_id": event_id,
                "source_date": calendar[source_position],
                "entry_date": calendar[source_position + 1],
                "planned_exit_date": calendar[source_position + 2],
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "cycle_id": "BK0001:2025-01-02",
                "vt_symbol": symbol,
                "stock_name": name,
                "recognition_rank": rank,
                "relative_percentile": 0.9,
                "limit_times": 2 if event_id == 10 else 1,
                "limit_up_suc_rate": 0.8,
                "seal_strength": 0.03,
                "amount": 1_000_000.0,
                "signal_close": 12.5,
                "prior_sessions": 100,
                "active_direction": "GOLD",
                "danger_state": "NORMAL",
                "market_phase": "warming",
                "evidence_level": "event_recognition_falsification",
            }
        )
    return pd.DataFrame(rows)


def _spell_identities() -> pd.DataFrame:
    return build_spell_identities(_recognition_candidates())


def _stock_bars() -> pd.DataFrame:
    rows = []
    calendar = _calendar()
    for symbol, future_direction in (("600001.SSE", 1.0), ("600002.SSE", -1.0)):
        for position, trade_date in enumerate(calendar):
            close = 10.0 + position * 0.1
            if position > 25:
                close += future_direction * (position - 25) * 0.25
            rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "open_price": close - 0.05,
                    "high_price": close + 0.2,
                    "low_price": close - 0.2,
                    "close_price": close,
                    "volume": 100_000.0 + position * 1_000.0,
                }
            )
    return pd.DataFrame(rows)


def _concept_bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sector_id": "BK0001",
            "concept_name": "测试概念",
            "trade_date": _calendar(),
            "close_price": [100.0 + index * 0.5 for index in range(len(_calendar()))],
            "source": "test",
        }
    )


def _market_returns() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": _calendar(),
            "market_daily_return": [0.001] * len(_calendar()),
            "market_return_10d": [0.01] * len(_calendar()),
            "research_date_valid": [True] * len(_calendar()),
        }
    )


def _features() -> pd.DataFrame:
    return build_spell_feature_ledger(
        _spell_identities(),
        _stock_bars(),
        _concept_bars(),
        _market_returns(),
        trading_dates=_calendar(),
    )


def _trajectory() -> pd.DataFrame:
    return build_spell_trajectories(
        _spell_identities(),
        _stock_bars(),
        _concept_bars(),
        _market_returns(),
        trading_dates=_calendar(),
    )


def _labels() -> pd.DataFrame:
    return build_spell_outcome_labels(_spell_identities(), _trajectory())


def _labeled_cases() -> pd.DataFrame:
    return _features().merge(_labels(), on="leader_spell_id", validate="one_to_one")


def test_build_spell_identities_keeps_one_real_stock_per_spell() -> None:
    rows = build_spell_identities(_recognition_candidates())

    assert rows["leader_spell_id"].is_unique
    assert len(rows) == 2
    assert rows.loc[0, "vt_symbol"] == "600001.SSE"
    assert rows.loc[0, "stock_name"] == "甲公司"
    assert rows.loc[0, "recognition_source_date"] == pd.Timestamp(_calendar()[25])


def test_build_spell_identities_uses_earliest_raw_recognition() -> None:
    rows = build_spell_identities(_recognition_candidates())

    assert rows.loc[0, "recognition_event_id"] == 10
    assert rows.loc[0, "recognition_rank"] == 1


def test_spell_identity_rejects_conflicting_stock_names() -> None:
    candidates = _recognition_candidates()
    candidates.loc[1, "stock_name"] = "错误名称"

    with pytest.raises(ValueError, match="conflicting spell identity"):
        build_spell_identities(candidates)


def test_pre_recognition_features_use_only_bars_through_s_close() -> None:
    baseline = _features()
    mutated = _stock_bars()
    mutated.loc[
        pd.to_datetime(mutated["trade_date"]).dt.date > _calendar()[25],
        ["open_price", "high_price", "low_price", "close_price", "volume"],
    ] = [1.0, 999.0, 0.5, 999.0, 999_999.0]
    changed = build_spell_feature_ledger(
        _spell_identities(),
        mutated,
        _concept_bars(),
        _market_returns(),
        trading_dates=_calendar(),
    )

    pd.testing.assert_frame_equal(baseline, changed)


def test_feature_ledger_keeps_real_identity_and_structural_values() -> None:
    row = _features().iloc[0]

    assert row["stock_name"] == "甲公司"
    assert bool(row["feature_complete"])
    assert row["stock_return_5d_pct"] > 0
    assert row["volume_to_prior_5d_ratio"] > 1
    assert row["stock_excess_concept_5d_pct"] != 0


def test_one_price_limit_up_has_top_close_location() -> None:
    bars = _stock_bars()
    mask = bars["vt_symbol"].eq("600001.SSE") & pd.to_datetime(
        bars["trade_date"]
    ).dt.date.eq(_calendar()[25])
    close = bars.loc[mask, "close_price"].item()
    bars.loc[mask, ["open_price", "high_price", "low_price"]] = close

    features = build_spell_feature_ledger(
        _spell_identities(),
        bars,
        _concept_bars(),
        _market_returns(),
        trading_dates=_calendar(),
    )
    row = features.loc[features["vt_symbol"].eq("600001.SSE")].iloc[0]

    assert row["close_location_value"] == pytest.approx(1.0)
    assert bool(row["feature_complete"])


def test_feature_ledger_describes_pre_s_limit_up_sequence() -> None:
    bars = _stock_bars()
    symbol_mask = bars["vt_symbol"].eq("600001.SSE")
    previous_close = bars.loc[
        symbol_mask & pd.to_datetime(bars["trade_date"]).dt.date.eq(_calendar()[23]),
        "close_price",
    ].item()
    s_minus_1_close = previous_close * 1.10
    s_close = s_minus_1_close * 1.10
    for trade_date, close in (
        (_calendar()[24], s_minus_1_close),
        (_calendar()[25], s_close),
    ):
        mask = symbol_mask & pd.to_datetime(bars["trade_date"]).dt.date.eq(trade_date)
        bars.loc[mask, ["open_price", "high_price", "low_price", "close_price"]] = close

    features = build_spell_feature_ledger(
        _spell_identities(),
        bars,
        _concept_bars(),
        _market_returns(),
        trading_dates=_calendar(),
    )
    row = features.loc[features["vt_symbol"].eq("600001.SSE")].iloc[0]

    assert row["s_day_return_pct"] == pytest.approx(10.0)
    assert row["s_minus_1_return_pct"] == pytest.approx(10.0)
    assert row["prior_near_limit_up_days_10d"] == pytest.approx(1.0)
    assert row["sessions_since_prior_near_limit_up"] == pytest.approx(1.0)
    assert row["consecutive_near_limit_up_days"] == pytest.approx(2.0)


def test_trajectory_keeps_real_daily_rows_and_offsets() -> None:
    trajectory = _trajectory()
    rows = trajectory.loc[trajectory["leader_spell_id"].str.endswith("600001.SSE")]

    assert rows["session_offset"].tolist() == list(range(-20, 6))
    assert rows.loc[rows["session_offset"].eq(0), "known_at_s_close"].item()
    assert not rows.loc[rows["session_offset"].gt(0), "known_at_s_close"].any()
    assert rows["stock_name"].eq("甲公司").all()


def test_trajectory_keeps_missing_calendar_rows_explicit() -> None:
    bars = _stock_bars()
    missing_date = _calendar()[20]
    bars = bars.loc[
        ~(
            bars["vt_symbol"].eq("600001.SSE")
            & pd.to_datetime(bars["trade_date"]).dt.date.eq(missing_date)
        )
    ]
    trajectory = build_spell_trajectories(
        _spell_identities(),
        bars,
        _concept_bars(),
        _market_returns(),
        trading_dates=_calendar(),
    )
    row = trajectory.loc[
        trajectory["leader_spell_id"].str.endswith("600001.SSE")
        & trajectory["trade_date"].eq(pd.Timestamp(missing_date))
    ].iloc[0]

    assert row["row_status"] == "missing_stock_bar"


def test_outcome_labels_are_built_after_feature_ledger() -> None:
    labels = _labels()

    assert labels.columns.tolist() == [
        "leader_spell_id",
        "future_5d_close_return_pct",
        "future_5d_max_close_return_pct",
        "future_5d_max_drawdown_pct",
        "future_sessions_available",
        "outcome_status",
    ]
    assert labels.loc[0, "future_5d_close_return_pct"] > 0
    assert labels.loc[1, "future_5d_close_return_pct"] < labels.loc[0, "future_5d_close_return_pct"]


def test_matched_pairs_require_same_recognition_date_and_concept() -> None:
    pairs = build_matched_spell_pairs(_labeled_cases())

    assert len(pairs) == 1
    assert pairs.loc[0, "winner_stock_name"] == "甲公司"
    assert pairs.loc[0, "loser_stock_name"] == "乙公司"
    assert pairs.loc[0, "recognition_source_date"] == pd.Timestamp(_calendar()[25])
    assert pairs.loc[0, "sector_id"] == "BK0001"
    assert pairs.loc[0, "winner_limit_times"] == pytest.approx(2.0)
    assert pairs.loc[0, "loser_limit_times"] == pytest.approx(1.0)


def test_pairing_is_deterministic_under_input_shuffle() -> None:
    cases = _labeled_cases()
    baseline = build_matched_spell_pairs(cases)
    shuffled = build_matched_spell_pairs(cases.sample(frac=1, random_state=7))

    pd.testing.assert_frame_equal(baseline, shuffled)


def test_report_contains_actual_case_rows_not_only_aggregates() -> None:
    features = _features()
    labels = _labels()
    pairs = build_matched_spell_pairs(features.merge(labels, on="leader_spell_id"))
    report = build_individual_leader_report(
        features,
        labels,
        pairs,
        _trajectory(),
        {},
    )

    assert report["formal_rule_selected"] is False
    assert report["strict_top3_claim"] is False
    assert report["individual_cases"][0]["stock_name"] == "甲公司"
    assert report["matched_pairs"][0]["winner_stock_name"] == "甲公司"
    assert report["overall_path_summary"]["complete_spells"] == 2
    assert any(
        row["feature"] == "recognition_rank"
        for row in report["matched_pair_direction_summary"]
    )
    assert any(
        row["shape"] == "first_board_no_prior_limit_10d"
        for row in report["phase_shape_summary"]
    )
    assert "甲公司" in render_individual_leader_json(report)


def test_cli_registers_individual_leader_study() -> None:
    args = build_parser().parse_args(["v2-individual-leader-study"])

    assert args.command == "v2-individual-leader-study"
    assert args.format == "markdown"
