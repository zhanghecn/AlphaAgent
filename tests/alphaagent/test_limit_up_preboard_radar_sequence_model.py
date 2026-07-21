from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

from alphaagent.server.services.limit_up.preboard_radar_sequence_model import (
    ACTION_SCORE_FIELD,
    CANDIDATE_SCORE_FIELD,
    FIRST_LAYER_FEATURE_NAMES,
    SECOND_LAYER_FEATURE_NAMES,
    build_expanding_oof_top1,
    build_top1_action_training_batch,
    calibrate_radar_action_threshold,
    candidate_feature_vector,
    canonical_contract_fingerprint,
    canonicalize_historical_rows,
    canonicalize_live_rows,
    enrich_radar_sequence_features,
    fit_candidate_touch_model,
    fit_top1_action_model,
    score_candidate_touch_rows,
    score_top1_action_rows,
    select_minute_top1,
    select_radar_actions,
)


SHANGHAI = timezone(timedelta(hours=8))


def test_historical_and_live_adapters_produce_identical_canonical_rows() -> None:
    historical = _historical_row()
    live = _live_row()
    live.update(
        {
            "concept_strength_score": 99.0,
            "sector_main_net_inflow": 1_000_000_000.0,
            "stock_main_net_inflow": 500_000_000.0,
            "market_timing_state": "GOLD_ACTIVE",
            "future_formal_touch": True,
        }
    )

    historical_rows = canonicalize_historical_rows([historical])
    live_rows = canonicalize_live_rows([live])

    assert historical_rows == live_rows
    assert set(historical_rows[0]) == {
        "signal_date",
        "signal_time",
        "vt_symbol",
        "gain_pct",
        "rank_score",
        "history_sample_count",
        "historical_combined_rate",
        "support_score",
        "entry_quality_score",
        "shared_strategy_passed",
        "before_first_limit_touch",
    }
    assert canonical_contract_fingerprint() == canonical_contract_fingerprint()


def test_live_adapter_fails_closed_for_stale_wrong_scope_or_missing_gate() -> None:
    invalid_variants = []
    for field, value in (
        ("frame_is_stale", True),
        ("source_trade_date", date(2026, 7, 1)),
        ("board_lane", "two_to_three"),
        ("capture_state", "fill_followup"),
        ("blocking_scope", "market"),
        ("history_sample_count", None),
        ("history_sample_count", 4),
        ("historical_combined_rate", None),
        ("historical_combined_rate", 29.99),
        ("rank_score", None),
        ("entry_quality_score", None),
        ("support_score", None),
        ("shared_strategy_passed", False),
        ("before_first_limit_touch", False),
    ):
        row = _live_row()
        row[field] = value
        invalid_variants.append(row)
    blocked = _live_row()
    blocked["blocker_codes"] = ["financial_risk"]
    invalid_variants.append(blocked)
    old_quote = _live_row()
    old_quote["quote_observed_at"] = datetime(
        2026, 7, 2, 9, 59, 14, tzinfo=SHANGHAI
    )
    invalid_variants.append(old_quote)
    wrong_completed_minute = _live_row()
    wrong_completed_minute["signal_at"] = datetime(
        2026, 7, 2, 9, 59, tzinfo=SHANGHAI
    )
    invalid_variants.append(wrong_completed_minute)

    for row in invalid_variants:
        assert canonicalize_live_rows([row]) == []


def test_live_adapter_keeps_earliest_fresh_frame_for_symbol_minute() -> None:
    first = _live_row()
    second = _live_row()
    second["captured_at"] = datetime(2026, 7, 2, 10, 0, 45, tzinfo=SHANGHAI)
    second["quote_observed_at"] = datetime(
        2026, 7, 2, 10, 0, 44, tzinfo=SHANGHAI
    )
    second["gain_pct"] = 7.0

    rows = canonicalize_live_rows([second, first])

    assert len(rows) == 1
    assert rows[0]["gain_pct"] == 5.2


def test_live_adapter_normalizes_utc_timestamps_to_shanghai_minute() -> None:
    live = _live_row()
    live["signal_at"] = datetime(2026, 7, 2, 2, 0, tzinfo=timezone.utc)
    live["captured_at"] = datetime(2026, 7, 2, 2, 0, 15, tzinfo=timezone.utc)
    live["quote_observed_at"] = datetime(
        2026, 7, 2, 2, 0, 14, tzinfo=timezone.utc
    )

    assert canonicalize_live_rows([live]) == canonicalize_historical_rows(
        [_historical_row()]
    )


def test_sequence_features_use_only_current_and_past_rows() -> None:
    rows = [
        _canonical("600001.SSE", "10:00", gain=4.0, rank=60.0),
        _canonical("600002.SSE", "10:00", gain=5.0, rank=70.0),
        _canonical("600001.SSE", "10:01", gain=4.5, rank=65.0),
        _canonical("600002.SSE", "10:01", gain=4.8, rank=68.0),
        _canonical("600001.SSE", "10:02", gain=5.1, rank=72.0),
    ]
    baseline = enrich_radar_sequence_features(rows)
    changed = deepcopy(rows)
    changed.append(_canonical("600003.SSE", "10:03", gain=9.4, rank=99.0))
    changed[-1]["future_oracle_identity"] = True
    with_future = enrich_radar_sequence_features(changed)

    assert with_future[: len(baseline)] == baseline
    first_1001 = next(
        row
        for row in baseline
        if row["vt_symbol"] == "600001.SSE" and row["signal_time"] == "10:01"
    )
    features = first_1001["sequence_features"]
    assert features["candidate_gain_delta_1m"] == 0.5
    assert features["candidate_visible_count_3m"] == 2.0
    assert features["candidate_gain_strength_pct"] == 0.5
    assert features["market_active_candidate_count_log1p"] > 0
    assert features["market_upward_momentum_ratio_1m"] == 0.5


def test_candidate_vector_is_fixed_and_ignores_source_only_fields() -> None:
    row = enrich_radar_sequence_features(
        [_canonical("600001.SSE", "10:00", gain=4.0, rank=60.0)]
    )[0]
    baseline = candidate_feature_vector(row)
    changed = deepcopy(row)
    changed.update(
        {
            "concept_strength_score": 100.0,
            "stock_main_net_inflow": 1e10,
            "formal_touch_within_3m": True,
            "d1_net_return_pct": 9.0,
        }
    )

    assert baseline is not None
    assert len(baseline) == len(FIRST_LAYER_FEATURE_NAMES)
    assert candidate_feature_vector(changed) == baseline


def test_candidate_model_is_deterministic_and_uses_only_declared_fit_dates() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(8))
    rows = _model_rows(dates)

    first = fit_candidate_touch_model(rows, fit_dates=set(dates[:6]))
    changed = deepcopy(rows)
    for row in changed:
        if date.fromisoformat(str(row["signal_date"])) in set(dates[6:]):
            row["formal_touch_within_3m"] = not row["formal_touch_within_3m"]
            row["future_oracle"] = 999.0
    second = fit_candidate_touch_model(changed, fit_dates=set(dates[:6]))

    assert first.status == "ready"
    assert first.fingerprint == second.fingerprint
    assert first.booster_model_text == second.booster_model_text
    assert first.fit_dates == tuple(value.isoformat() for value in dates[:6])
    assert set(first.feature_importance_by_name) == set(FIRST_LAYER_FEATURE_NAMES)


def test_minute_top1_is_stable_by_probability_then_rank_then_symbol() -> None:
    rows = [
        {
            **_model_row(date(2026, 7, 2), "600002.SSE", "10:00", 0),
            CANDIDATE_SCORE_FIELD: 0.8,
            "rank_score": 70.0,
        },
        {
            **_model_row(date(2026, 7, 2), "600001.SSE", "10:00", 1),
            CANDIDATE_SCORE_FIELD: 0.8,
            "rank_score": 70.0,
        },
        {
            **_model_row(date(2026, 7, 2), "600003.SSE", "10:00", 1),
            CANDIDATE_SCORE_FIELD: 0.7,
            "rank_score": 99.0,
        },
    ]

    selected = select_minute_top1(rows)

    assert len(selected) == 1
    assert selected[0]["vt_symbol"] == "600001.SSE"
    assert selected[0]["candidate_count"] == 3
    assert selected[0]["candidate_top1_score_margin"] == 0.0


def test_expanding_oof_top1_never_reads_scored_block_or_future_labels() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(30))
    rows = _model_rows(dates)
    baseline = build_expanding_oof_top1(
        rows,
        fit_dates=set(dates),
        minimum_seed_dates=20,
        block_size=5,
    )
    changed = deepcopy(rows)
    for row in changed:
        row_date = date.fromisoformat(str(row["signal_date"]))
        if row_date >= dates[25]:
            row["formal_touch_within_3m"] = not row["formal_touch_within_3m"]
            row["d1_net_return_pct"] = 99.0
    rerun = build_expanding_oof_top1(
        changed,
        fit_dates=set(dates),
        minimum_seed_dates=20,
        block_size=5,
    )

    first_block = [row for row in baseline if row["signal_date"] < dates[25].isoformat()]
    changed_first_block = [
        row for row in rerun if row["signal_date"] < dates[25].isoformat()
    ]
    assert first_block == changed_first_block
    assert first_block
    assert all(
        str(row["oof_training_date_end"]) < str(row["signal_date"])
        for row in baseline
    )


def test_second_layer_target_belongs_to_selected_top1_not_any_minute_winner() -> None:
    rows = [
        {
            **_model_row(date(2026, 7, 2), "600001.SSE", "10:00", 0),
            CANDIDATE_SCORE_FIELD: 0.9,
            "candidate_top1_score_margin": 0.4,
            "candidate_count": 2,
            "oof_training_date_end": "2026-07-01",
            "oof_candidate_model_fingerprint": "sha256:first",
        },
        {
            **_model_row(date(2026, 7, 2), "600002.SSE", "10:00", 1),
            CANDIDATE_SCORE_FIELD: 0.5,
            "candidate_top1_score_margin": 0.4,
            "candidate_count": 2,
            "oof_training_date_end": "2026-07-01",
            "oof_candidate_model_fingerprint": "sha256:first",
        },
    ]
    selected = select_minute_top1(rows)

    _, labels, keys = build_top1_action_training_batch(selected)

    assert keys == (("2026-07-02", "10:00", "600001.SSE"),)
    assert labels.tolist() == [0]


def test_second_layer_training_rejects_in_sample_or_unfingerprinted_top1() -> None:
    base = {
        **_model_row(date(2026, 7, 2), "600001.SSE", "10:00", 1),
        CANDIDATE_SCORE_FIELD: 0.9,
        "candidate_top1_score_margin": 0.4,
        "candidate_count": 2,
    }
    missing_oof = deepcopy(base)
    in_sample = {
        **base,
        "oof_training_date_end": "2026-07-02",
        "oof_candidate_model_fingerprint": "sha256:in-sample",
    }
    missing_fingerprint = {
        **base,
        "oof_training_date_end": "2026-07-01",
    }

    matrix, labels, keys = build_top1_action_training_batch(
        [missing_oof, in_sample, missing_fingerprint]
    )

    assert matrix.shape == (0, len(SECOND_LAYER_FEATURE_NAMES))
    assert labels.tolist() == []
    assert keys == ()


def test_second_layer_fit_and_scoring_are_deterministic() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(30))
    oof = build_expanding_oof_top1(
        _model_rows(dates),
        fit_dates=set(dates),
        minimum_seed_dates=20,
        block_size=5,
    )
    for index, row in enumerate(oof):
        row["formal_touch_within_3m"] = index % 3 == 0

    first = fit_top1_action_model(oof)
    second = fit_top1_action_model(deepcopy(oof))
    scored = score_top1_action_rows(oof, first)

    assert first.status == "ready"
    assert first.fingerprint == second.fingerprint
    assert set(first.coefficient_by_feature) == set(SECOND_LAYER_FEATURE_NAMES)
    assert scored
    assert all(0.0 <= float(row[ACTION_SCORE_FIELD]) <= 1.0 for row in scored)


def test_action_calibration_requires_ten_stock_days_and_seventy_percent() -> None:
    rows = [
        {
            **_model_row(
                date(2026, 7, 1) + timedelta(days=index),
                f"{600000 + index}.SSE",
                "10:00",
                1 if index < 7 else 0,
            ),
            ACTION_SCORE_FIELD: 0.8,
        }
        for index in range(10)
    ]
    calibration_dates = {
        date.fromisoformat(str(row["signal_date"])) for row in rows
    }

    ready = calibrate_radar_action_threshold(
        rows,
        calibration_dates=calibration_dates,
        thresholds=(0.75,),
    )
    too_few = calibrate_radar_action_threshold(
        rows[:9],
        calibration_dates=set(sorted(calibration_dates)[:9]),
        thresholds=(0.75,),
    )
    low_precision_rows = deepcopy(rows)
    for index, row in enumerate(low_precision_rows):
        row["formal_touch_within_3m"] = index < 6
    low_precision = calibrate_radar_action_threshold(
        low_precision_rows,
        calibration_dates=calibration_dates,
        thresholds=(0.75,),
    )

    assert ready.status == "ready"
    assert ready.threshold == 0.75
    assert ready.selected_metrics["selection_count"] == 10
    assert ready.selected_metrics["precision"] == 0.7
    assert too_few.status == "insufficient_calibration_actions"
    assert too_few.threshold is None
    assert low_precision.status == "calibration_precision_gate_failed"
    assert low_precision.threshold is None


def test_action_capacity_keeps_first_stock_day_and_at_most_two_per_day() -> None:
    rows = []
    for minute, symbol in (("10:00", "600001.SSE"), ("10:01", "600001.SSE"), ("10:02", "600002.SSE"), ("10:03", "600003.SSE")):
        rows.append(
            {
                **_model_row(date(2026, 7, 2), symbol, minute, 1),
                ACTION_SCORE_FIELD: 0.9,
            }
        )

    actions = select_radar_actions(rows, threshold=0.8)

    assert [(row["signal_time"], row["vt_symbol"]) for row in actions] == [
        ("10:00", "600001.SSE"),
        ("10:02", "600002.SSE"),
    ]


def _historical_row() -> dict[str, object]:
    return {
        "signal_date": date(2026, 7, 2),
        "signal_at": datetime(2026, 7, 2, 10, 0),
        "signal_time": "10:00:00",
        "vt_symbol": "600001.SSE",
        "board_lane": "first_board",
        "capture_state": "tracking",
        "gain_pct": 5.2,
        "rank_score": 77.0,
        "history_sample_count": 12,
        "historical_combined_rate": 48.5,
        "support_score": 61.0,
        "entry_quality_score": 73.0,
        "shared_strategy_passed": True,
        "before_first_limit_touch": True,
        "blocking_scope": "none",
        "blocker_codes": [],
    }


def _live_row() -> dict[str, object]:
    return {
        **_historical_row(),
        "signal_at": datetime(2026, 7, 2, 10, 0, tzinfo=SHANGHAI),
        "captured_at": datetime(2026, 7, 2, 10, 0, 15, tzinfo=SHANGHAI),
        "quote_observed_at": datetime(2026, 7, 2, 10, 0, 14, tzinfo=SHANGHAI),
        "frame_is_stale": False,
        "frame_quality_status": "ready",
        "source_trade_date": date(2026, 7, 2),
    }


def _canonical(
    symbol: str,
    signal_time: str,
    *,
    gain: float,
    rank: float,
) -> dict[str, object]:
    return {
        "signal_date": "2026-07-02",
        "signal_time": signal_time,
        "vt_symbol": symbol,
        "gain_pct": gain,
        "rank_score": rank,
        "history_sample_count": 12.0,
        "historical_combined_rate": 48.5,
        "support_score": 61.0,
        "entry_quality_score": 73.0,
        "shared_strategy_passed": True,
        "before_first_limit_touch": True,
    }


def _model_rows(dates: tuple[date, ...]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for date_index, trade_date in enumerate(dates):
        for minute_index, signal_time in enumerate(("10:00", "10:01")):
            for symbol_index, symbol in enumerate(("600001.SSE", "600002.SSE")):
                label = int((date_index + minute_index + symbol_index) % 2 == 0)
                rows.append(
                    _model_row(
                        trade_date,
                        symbol,
                        signal_time,
                        label,
                        offset=date_index + minute_index + symbol_index,
                    )
                )
    return rows


def _model_row(
    trade_date: date,
    symbol: str,
    signal_time: str,
    label: int,
    *,
    offset: int = 0,
) -> dict[str, object]:
    features = {
        name: float((index + 1) * 0.1 + offset * 0.01 + label * 0.03)
        for index, name in enumerate(FIRST_LAYER_FEATURE_NAMES)
    }
    return {
        "signal_date": trade_date.isoformat(),
        "signal_time": signal_time,
        "vt_symbol": symbol,
        "rank_score": 60.0 + offset + label,
        "sequence_features": features,
        "formal_touch_within_3m": bool(label),
    }
