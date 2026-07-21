from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

import pytest

from alphaagent.server.services.limit_up import live_policy
from alphaagent.server.services.limit_up.preboard_point_trigger_contract import (
    FRAME_FEATURE_FIELDS,
    IDENTITY_FEATURE_FIELDS,
    TRANSIENT_LANE_BLOCKER_CODES,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_dataset import (
    attach_point_trigger_labels,
    audit_point_trigger_day,
    build_formal_baseline_orders,
    build_point_trigger_rows,
    finalize_point_trigger_day_audit,
    point_trigger_label_metrics,
    point_trigger_input_fingerprint,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_model import (
    IDENTITY_MODEL_FEATURE_FIELDS,
    build_identity_training_batch,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
TRADE_DATE = date(2026, 7, 21)
RUNTIME_FINGERPRINT = "sha256:" + "a" * 64


def test_complete_day_accepts_twenty_seconds_and_rejects_twenty_point_zero_zero_one() -> None:
    frames, observations = _complete_day(step_seconds=20.0)

    ready = audit_point_trigger_day(frames, observations)
    slow_frames, slow_observations = _complete_day(step_seconds=20.001)
    slow = audit_point_trigger_day(slow_frames, slow_observations)

    assert ready.is_complete
    assert ready.status == "complete"
    assert ready.metrics["scan_interval_p90_seconds"] == pytest.approx(20.0)
    assert not slow.is_complete
    assert "scan_interval_p90_above_20s" in slow.reason_codes


def test_day_audit_fails_closed_for_stale_quote_source_and_concept_gaps() -> None:
    frames, observations = _complete_day(step_seconds=20.0)

    stale_frames = deepcopy(frames)
    for frame in stale_frames[:20]:
        frame["is_stale"] = True
    stale = audit_point_trigger_day(stale_frames, observations)

    old_quotes = deepcopy(observations)
    for observation in old_quotes:
        observation["quote_observed_at"] = observation["captured_at"] - timedelta(
            seconds=61
        )
    quote = audit_point_trigger_day(frames, old_quotes)

    wrong_source = deepcopy(frames)
    wrong_source[0]["source_trade_date"] = TRADE_DATE - timedelta(days=1)
    source = audit_point_trigger_day(wrong_source, observations)

    missing_concept = deepcopy(observations)
    for observation in missing_concept:
        observation["concept_change_acceleration_1m"] = None
    concept = audit_point_trigger_day(frames, missing_concept)

    assert "non_stale_frame_ratio_below_98pct" in stale.reason_codes
    assert "fresh_quote_ratio_below_98pct" in quote.reason_codes
    assert "source_trade_date_mismatch" in source.reason_codes
    assert "concept_acceleration_coverage_below_95pct" in concept.reason_codes


def test_window_boundaries_and_unobserved_tail_count_as_scan_gaps() -> None:
    frames, observations = _complete_day(step_seconds=20.0)
    morning_end = datetime.combine(TRADE_DATE, time(11, 30), SHANGHAI)
    truncated_ids = {
        int(frame["id"])
        for frame in frames
        if morning_end - timedelta(seconds=61)
        < frame["captured_at"]
        <= morning_end
    }
    truncated_frames = [
        frame for frame in frames if int(frame["id"]) not in truncated_ids
    ]
    truncated_observations = [
        row for row in observations if int(row["frame_id"]) not in truncated_ids
    ]

    audit = audit_point_trigger_day(truncated_frames, truncated_observations)

    assert not audit.is_complete
    assert "entry_window_max_gap_above_60s" in audit.reason_codes
    assert float(audit.metrics["entry_window_max_gap_seconds"]) > 60.0


def test_fast_afternoon_cannot_dilute_a_slow_morning_window() -> None:
    frames, observations = _complete_day(step_seconds=10.0)
    slow_start = datetime.combine(TRADE_DATE, time(10, 45), SHANGHAI)
    slow_end = datetime.combine(TRADE_DATE, time(11, 30), SHANGHAI)
    removed_ids = {
        int(frame["id"])
        for frame in frames
        if slow_start <= frame["captured_at"] <= slow_end
        and int((frame["captured_at"] - slow_start).total_seconds()) % 60 != 0
    }
    sparse_frames = [
        frame for frame in frames if int(frame["id"]) not in removed_ids
    ]
    sparse_observations = [
        row for row in observations if int(row["frame_id"]) not in removed_ids
    ]

    audit = audit_point_trigger_day(sparse_frames, sparse_observations)

    assert not audit.is_complete
    assert "scan_interval_p90_above_20s" in audit.reason_codes
    assert audit.metrics["scan_interval_p90_seconds"] == pytest.approx(60.0)


def test_fast_window_cannot_dilute_ready_or_concept_coverage() -> None:
    frames, observations = _complete_day(step_seconds=10.0)
    morning_frames = [
        frame
        for frame in frames
        if time(10, 0) <= frame["captured_at"].time() <= time(11, 30)
    ]

    degraded_frames = deepcopy(frames)
    degraded_ids = {int(frame["id"]) for frame in morning_frames[:16]}
    for frame in degraded_frames:
        if int(frame["id"]) in degraded_ids:
            frame["quality_status"] = "degraded"
    degraded = audit_point_trigger_day(degraded_frames, observations)

    missing_concept = deepcopy(observations)
    missing_concept_ids = {int(frame["id"]) for frame in morning_frames[:42]}
    for observation in missing_concept:
        if int(observation["frame_id"]) in missing_concept_ids:
            observation["concept_change_acceleration_1m"] = None
    concept = audit_point_trigger_day(frames, missing_concept)

    assert "ready_frame_ratio_below_98pct" in degraded.reason_codes
    assert degraded.metrics["ready_frame_ratio"] < 0.98
    assert "concept_acceleration_coverage_below_95pct" in concept.reason_codes
    assert concept.metrics["concept_acceleration_coverage_ratio"] < 0.95


def test_day_audit_requires_one_valid_capture_runtime_fingerprint() -> None:
    frames, observations = _complete_day(step_seconds=20.0)
    missing_frames = deepcopy(frames)
    missing_frames[0]["capture_runtime_fingerprint"] = None
    changed_frames = deepcopy(frames)
    changed_frames[0]["capture_runtime_fingerprint"] = "sha256:" + "b" * 64
    invalid_frames = deepcopy(frames)
    invalid_frames[0]["capture_runtime_fingerprint"] = "not-a-fingerprint"

    complete = audit_point_trigger_day(frames, observations)
    missing = audit_point_trigger_day(missing_frames, observations)
    changed = audit_point_trigger_day(changed_frames, observations)
    invalid = audit_point_trigger_day(invalid_frames, observations)

    assert complete.capture_runtime_fingerprint == RUNTIME_FINGERPRINT
    assert "capture_runtime_fingerprint_missing" in missing.reason_codes
    assert "capture_runtime_fingerprint_changed" in changed.reason_codes
    assert "capture_runtime_fingerprint_invalid" in invalid.reason_codes


def test_reachability_funnel_separates_data_history_and_static_gates() -> None:
    captured_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)

    def metrics(**candidate_overrides: object) -> dict[str, float | int | None]:
        candidate_frame = _frame(1, captured_at)
        candidate = _observation(1, captured_at)
        candidate.update(candidate_overrides)
        event_at = captured_at + timedelta(seconds=30)
        event = _observation(2, event_at)
        event.update({"formal_action": "buy_now", "capture_state": "sealed"})
        return audit_point_trigger_day(
            [candidate_frame, _frame(2, event_at)],
            [candidate, event],
        ).metrics

    complete = metrics()
    stale_quote = metrics(quote_observed_at=captured_at - timedelta(seconds=61))
    weak_history = metrics(history_sample_count=4)
    missing_lane_contract = metrics(lane_blocker_codes=None)
    static_blocked = metrics(lane_blocker_codes=["first_board_repair_setup_missing"])

    assert complete["formal_first_board_event_count"] == 1
    assert complete["formal_event_raw_3pct_within_60s_count"] == 1
    assert complete["formal_event_quality_3pct_within_60s_count"] == 1
    assert complete["formal_event_fresh_3pct_within_60s_count"] == 1
    assert complete["formal_event_history_eligible_within_60s_count"] == 1
    assert complete["formal_event_lane_contract_available_within_60s_count"] == 1
    assert complete["formal_event_static_eligible_within_60s_count"] == 1
    assert stale_quote["formal_event_quality_3pct_within_60s_count"] == 1
    assert stale_quote["formal_event_fresh_3pct_within_60s_count"] == 0
    assert weak_history["formal_event_history_eligible_within_60s_count"] == 0
    assert missing_lane_contract["formal_event_history_eligible_within_60s_count"] == 1
    assert (
        missing_lane_contract[
            "formal_event_lane_contract_available_within_60s_count"
        ]
        == 0
    )
    assert static_blocked["formal_event_history_eligible_within_60s_count"] == 1
    assert static_blocked["formal_event_lane_contract_available_within_60s_count"] == 1
    assert static_blocked["formal_event_static_eligible_within_60s_count"] == 0


def test_day_audit_avoids_full_row_copy() -> None:
    captured_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    event_at = captured_at + timedelta(seconds=30)
    candidate = _observation(1, captured_at)
    event = _observation(2, event_at)
    event.update({"formal_action": "buy_now", "capture_state": "sealed"})

    audit = audit_point_trigger_day(
        [_frame(1, captured_at), _frame(2, event_at)],
        [_NonCopyableMapping(candidate), _NonCopyableMapping(event)],
    )

    assert audit.metrics["formal_first_board_event_count"] == 1
    assert audit.metrics["formal_event_static_eligible_within_60s_count"] == 1


def test_sequence_features_read_only_current_and_past_frames() -> None:
    start = datetime(2026, 7, 21, 10, 0, tzinfo=SHANGHAI)
    frames: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []
    for index in range(10):
        captured_at = start + timedelta(seconds=index * 20)
        frame = _frame(index + 1, captured_at)
        observation = _observation(
            index + 1,
            captured_at,
            gain=3.1 + index * 0.1,
            rank=60.0 + index,
        )
        observation["volume"] = 1_000.0 + index * 100.0
        observation["turnover"] = 10_000.0 + index * 1_000.0
        frames.append(frame)
        observations.append(observation)

    baseline = build_point_trigger_rows(frames, observations)
    current = next(
        row
        for row in baseline
        if row["captured_at"] == start + timedelta(seconds=180)
    )
    future_frames = frames + [_frame(11, start + timedelta(seconds=200))]
    future_observation = _observation(
        11,
        start + timedelta(seconds=200),
        gain=9.4,
        rank=99.0,
    )
    future_observation.update(
        {
            "formal_action": "buy_now",
            "d1_net_return_pct": 99.0,
            "stock_main_net_inflow_ratio": 999.0,
        }
    )
    with_future = build_point_trigger_rows(
        future_frames,
        observations + [future_observation],
    )
    unchanged = next(
        row
        for row in with_future
        if row["captured_at"] == current["captured_at"]
    )

    assert unchanged == current
    assert point_trigger_input_fingerprint([unchanged]) == point_trigger_input_fingerprint(
        [current]
    )
    features = current["identity_features"]
    assert features["candidate_gain_slope_20s"] == pytest.approx(0.3)
    assert features["candidate_gain_slope_60s"] == pytest.approx(0.3)
    assert features["candidate_gain_slope_180s"] == pytest.approx(0.3)
    assert features["candidate_max_drawdown_180s"] == 0.0
    assert features["candidate_recovery_180s"] == pytest.approx(0.9)
    assert features["candidate_rank_delta_60s"] == pytest.approx(3.0)
    assert features["candidate_rank_delta_60s_missing"] == 0.0
    assert features["candidate_quote_main_net_inflow_ratio_delta_60s_missing"] == 0.0
    assert current["frame_features"]["market_candidate_count_3_5"] == 1.0


def test_market_event_clock_counts_each_stock_once_at_a_shared_frame() -> None:
    start = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    event_at = start + timedelta(seconds=20)
    repeated_at = start + timedelta(seconds=25)
    current_at = start + timedelta(seconds=30)
    first_event = _observation(2, event_at)
    first_event.update({"formal_action": "buy_now", "capture_state": "sealed"})
    second_event = {
        **first_event,
        "vt_symbol": "600002.SSE",
        "name": "测试二号",
    }
    repeated_event = {
        **_observation(3, repeated_at),
        "formal_action": "buy_now",
        "capture_state": "sealed",
    }
    current = {
        **_observation(4, current_at),
        "vt_symbol": "600003.SSE",
        "name": "测试三号",
    }

    rows = build_point_trigger_rows(
        [
            _frame(1, start),
            _frame(2, event_at),
            _frame(3, repeated_at),
            _frame(4, current_at),
        ],
        [
            _observation(1, start),
            first_event,
            second_event,
            repeated_event,
            current,
        ],
    )

    row = next(item for item in rows if item["vt_symbol"] == "600003.SSE")
    assert row["frame_features"]["market_formal_event_count_20s"] == 2.0
    assert row["frame_features"]["market_formal_event_count_60s"] == 2.0
    assert row["frame_features"]["market_formal_event_count_180s"] == 2.0


@pytest.mark.parametrize("timing", ["FADING", "GOLD_FADING", "SILVER_FADING"])
def test_gold_and_silver_fading_share_the_fading_feature(timing: str) -> None:
    first_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    frames = [
        {**_frame(1, first_at), "market_timing_state": timing},
        {
            **_frame(2, first_at + timedelta(seconds=15)),
            "market_timing_state": timing,
        },
    ]
    rows = build_point_trigger_rows(
        frames,
        [
            _observation(1, first_at),
            _observation(2, first_at + timedelta(seconds=15)),
        ],
    )

    market = rows[-1]["frame_features"]
    assert market["market_timing_fading"] == 1.0
    assert market["market_timing_none"] == 0.0


def test_bounded_live_history_matches_full_day_after_continuous_feature_caps() -> None:
    start = datetime(2026, 7, 21, 10, 0, tzinfo=SHANGHAI)
    frames = [
        _frame(index + 1, start + timedelta(seconds=index * 15))
        for index in range(30)
    ]
    observations = [
        _observation(
            index + 1,
            start + timedelta(seconds=index * 15),
            gain=3.1 + index * 0.05,
            rank=60.0 + index,
        )
        for index in range(30)
    ]
    current_at = frames[-1]["captured_at"]
    cutoff = current_at - timedelta(seconds=220)

    full = build_point_trigger_rows(frames, observations)[-1]
    recent_frames = [row for row in frames if row["captured_at"] >= cutoff]
    recent_ids = {row["id"] for row in recent_frames}
    recent_observations = [
        row for row in observations if row["frame_id"] in recent_ids
    ]
    bounded = build_point_trigger_rows(recent_frames, recent_observations)[-1]

    assert bounded == full


def test_continuous_age_and_frame_count_reset_after_observation_gap() -> None:
    start = datetime(2026, 7, 21, 10, 0, tzinfo=SHANGHAI)
    frames = [_frame(1, start), _frame(2, start + timedelta(seconds=45))]
    observations = [
        _observation(1, start),
        _observation(2, start + timedelta(seconds=45)),
    ]

    current = build_point_trigger_rows(frames, observations)[-1]

    assert current["identity_features"]["candidate_age_seconds_log1p"] == 0.0
    assert current["identity_features"]["candidate_visible_frame_count_log1p"] == (
        pytest.approx(0.6931471806)
    )
    assert current["frame_features"]["market_new_candidate_count_20s"] == 1.0


def test_flow_values_are_used_only_when_source_date_matches_frame_date() -> None:
    captured_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    frame = _frame(1, captured_at)
    current = _observation(1, captured_at)
    stale_flow = deepcopy(current)
    stale_flow["vt_symbol"] = "600002.SSE"
    stale_flow["sector_flow_trade_date"] = TRADE_DATE - timedelta(days=1)
    stale_flow["stock_flow_trade_date"] = TRADE_DATE - timedelta(days=1)

    rows = build_point_trigger_rows([frame], [current, stale_flow])
    by_symbol = {str(row["vt_symbol"]): row for row in rows}

    current_features = by_symbol["600001.SSE"]["identity_features"]
    stale_features = by_symbol["600002.SSE"]["identity_features"]
    assert current_features["candidate_sector_flow_missing"] == 0.0
    assert current_features["candidate_stock_flow_missing"] == 0.0
    assert current_features["candidate_sector_main_net_inflow_ratio"] == 2.0
    assert current_features["candidate_stock_main_net_inflow_ratio"] == 1.0
    assert stale_features["candidate_sector_flow_missing"] == 1.0
    assert stale_features["candidate_stock_flow_missing"] == 1.0
    assert stale_features["candidate_sector_main_net_inflow_ratio"] == 0.0
    assert stale_features["candidate_stock_main_net_inflow_ratio"] == 0.0


def test_cold_start_and_missing_quote_flow_remain_finite_model_rows() -> None:
    captured_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    observation = _observation(1, captured_at)
    observation["quote_main_net_inflow_ratio"] = None

    row = build_point_trigger_rows(
        [_frame(1, captured_at)],
        [observation],
    )[0]
    identity = row["identity_features"]

    assert all(isinstance(value, float) and isfinite(value) for value in identity.values())
    assert identity["candidate_rank_delta_20s"] == 0.0
    assert identity["candidate_rank_delta_20s_missing"] == 1.0
    assert identity["candidate_rank_delta_60s"] == 0.0
    assert identity["candidate_rank_delta_60s_missing"] == 1.0
    assert identity["candidate_quote_main_net_inflow_missing"] == 1.0
    assert identity["candidate_quote_main_net_inflow_ratio_delta_20s"] == 0.0
    assert identity["candidate_quote_main_net_inflow_ratio_delta_20s_missing"] == 1.0
    assert identity["candidate_quote_main_net_inflow_ratio_delta_60s"] == 0.0
    assert identity["candidate_quote_main_net_inflow_ratio_delta_60s_missing"] == 1.0
    for horizon in (20, 60, 180):
        assert identity[f"candidate_gain_slope_{horizon}s"] == 0.0
        assert identity[f"candidate_gain_slope_{horizon}s_missing"] == 1.0
        assert identity[f"candidate_gain_acceleration_{horizon}s"] == 0.0
        assert identity[f"candidate_gain_acceleration_{horizon}s_missing"] == 1.0
    for horizon in (20, 60):
        assert identity[f"candidate_volume_delta_rate_{horizon}s"] == 0.0
        assert identity[f"candidate_volume_delta_rate_{horizon}s_missing"] == 1.0
        assert identity[f"candidate_turnover_delta_rate_{horizon}s"] == 0.0
        assert identity[f"candidate_turnover_delta_rate_{horizon}s_missing"] == 1.0

    labeled = {
        **row,
        "label_status": "known",
        "formal_event_within_60s": True,
        "formal_identity_within_60s": True,
    }
    matrix, labels, groups, keys = build_identity_training_batch(
        [labeled],
        [TRADE_DATE],
    )

    assert matrix.shape == (1, len(IDENTITY_MODEL_FEATURE_FIELDS))
    assert labels.tolist() == [1]
    assert groups == (1,)
    assert len(keys) == 1


def test_stale_or_future_quote_enrichment_is_not_used_as_a_model_feature() -> None:
    captured_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    stale = _observation(1, captured_at)
    stale["quote_flow_observed_at"] = captured_at - timedelta(seconds=21)
    future = deepcopy(stale)
    future["vt_symbol"] = "600002.SSE"
    future["quote_flow_observed_at"] = captured_at + timedelta(seconds=1)

    rows = build_point_trigger_rows(
        [_frame(1, captured_at)],
        [stale, future],
    )

    for row in rows:
        identity = row["identity_features"]
        assert identity["candidate_quote_speed"] == 0.0
        assert identity["candidate_quote_speed_missing"] == 1.0
        assert identity["candidate_quote_amplitude_pct"] == 0.0
        assert identity["candidate_quote_amplitude_missing"] == 1.0
        assert identity["candidate_quote_main_net_inflow_ratio"] == 0.0
        assert identity["candidate_quote_main_net_inflow_missing"] == 1.0


def test_transient_lane_blockers_stay_in_the_prediction_pool_but_hard_blockers_do_not() -> None:
    captured_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    frame = _frame(1, captured_at)
    transient = _observation(1, captured_at)
    transient.update(
        {
            "support_score": None,
            "entry_quality_score": None,
            "blocking_scope": "dynamic",
            "lane_blocker_codes": ["intraday_support_unavailable"],
            "blocker_codes": ["intraday_support_unavailable", "stock_momentum"],
        }
    )
    hard = {
        **_observation(1, captured_at),
        "vt_symbol": "600002.SSE",
        "blocking_scope": "structural",
        "lane_blocker_codes": ["fundamental_risk"],
        "blocker_codes": ["fundamental_risk", "lane_gate"],
    }

    rows = build_point_trigger_rows([frame], [transient, hard])

    assert [row["vt_symbol"] for row in rows] == ["600001.SSE"]
    features = rows[0]["identity_features"]
    assert features["candidate_support_score"] == 0.0
    assert features["candidate_support_missing"] == 1.0
    assert features["candidate_entry_quality_score"] == 0.0
    assert features["candidate_entry_quality_missing"] == 1.0
    assert features["candidate_dynamic_blocked"] == 1.0
    assert features["candidate_transient_lane_blocker_count_log1p"] > 0.0


def test_prediction_pool_transient_blockers_match_formal_dynamic_classification() -> None:
    assert TRANSIENT_LANE_BLOCKER_CODES == frozenset(
        live_policy._DYNAMIC_LANE_BLOCKERS
    )


@pytest.mark.parametrize(
    "static_blocker",
    [
        "first_board_touch_gene_weak",
        "financial_report_unavailable",
        "first_board_repair_setup_missing",
    ],
)
def test_static_first_board_quality_blockers_stay_out_of_prediction_pool(
    static_blocker: str,
) -> None:
    captured_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    observation = _observation(1, captured_at)
    observation.update(
        {
            "blocking_scope": "structural",
            "lane_blocker_codes": [static_blocker],
            "blocker_codes": [static_blocker, "lane_gate"],
        }
    )

    assert build_point_trigger_rows([_frame(1, captured_at)], [observation]) == []


def test_market_features_use_broad_three_percent_observations_not_identity_pool() -> None:
    captured_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    eligible = _observation(1, captured_at, gain=4.0)
    static_blocked = {
        **_observation(1, captured_at, gain=6.0),
        "vt_symbol": "600002.SSE",
        "blocking_scope": "structural",
        "lane_blocker_codes": ["financial_report_unavailable"],
        "blocker_codes": ["financial_report_unavailable", "lane_gate"],
    }

    rows = build_point_trigger_rows(
        [_frame(1, captured_at)],
        [eligible, static_blocked],
    )

    assert [row["vt_symbol"] for row in rows] == ["600001.SSE"]
    market = rows[0]["frame_features"]
    assert market["market_candidate_count_total"] == 2.0
    assert market["market_candidate_count_3_5"] == 1.0
    assert market["market_candidate_count_5_7"] == 1.0


def test_labels_ignore_formal_events_outside_the_current_candidate_frame() -> None:
    captured_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    rows = [
        _point_row(captured_at, "600001.SSE"),
        _point_row(captured_at, "600002.SSE"),
    ]
    future = [
        _future_observation(
            captured_at + timedelta(seconds=20),
            "600099.SSE",
            action="buy_now",
            formal_rank=1,
        ),
        _future_observation(
            captured_at + timedelta(seconds=40),
            "600002.SSE",
            action="buy_now",
            formal_rank=2,
        ),
        _future_observation(captured_at + timedelta(seconds=60), "600001.SSE"),
    ]

    labeled = attach_point_trigger_labels(rows, future)
    by_symbol = {str(row["vt_symbol"]): row for row in labeled}

    assert by_symbol["600001.SSE"]["formal_event_at"] == captured_at + timedelta(
        seconds=40
    )
    assert by_symbol["600001.SSE"]["formal_event_within_60s"] is True
    assert by_symbol["600001.SSE"]["formal_identity_within_60s"] is False
    assert by_symbol["600002.SSE"]["formal_identity_within_60s"] is True


def test_sixty_second_labels_use_open_right_window_and_stable_formal_identity() -> None:
    captured_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    rows = [
        _point_row(captured_at, "600001.SSE"),
        _point_row(captured_at, "600002.SSE"),
    ]
    future = [
        _future_observation(captured_at, "600001.SSE", action="buy_now"),
        _future_observation(captured_at + timedelta(seconds=20), "600001.SSE"),
        _future_observation(
            captured_at + timedelta(seconds=40),
            "600001.SSE",
            action="buy_now",
            formal_rank=2,
        ),
        _future_observation(
            captured_at + timedelta(seconds=40),
            "600002.SSE",
            action="buy_now",
            formal_rank=1,
        ),
        _future_observation(captured_at + timedelta(seconds=60), "600001.SSE"),
    ]

    labeled = attach_point_trigger_labels(rows, future)
    by_symbol = {str(row["vt_symbol"]): row for row in labeled}

    assert by_symbol["600001.SSE"]["label_status"] == "known"
    assert by_symbol["600001.SSE"]["formal_event_within_60s"] is True
    assert by_symbol["600001.SSE"]["formal_identity_within_60s"] is False
    assert by_symbol["600002.SSE"]["formal_identity_within_60s"] is True
    assert by_symbol["600002.SSE"]["formal_identity_vt_symbol"] == "600002.SSE"
    assert by_symbol["600002.SSE"]["formal_event_at"] == captured_at + timedelta(
        seconds=40
    )


def test_sixty_second_labels_ignore_repeated_buy_now_after_first_stock_event() -> None:
    captured_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    rows = [
        _point_row(captured_at, "600001.SSE"),
        _point_row(captured_at, "600002.SSE"),
    ]
    future = [
        _future_observation(
            captured_at - timedelta(seconds=10),
            "600001.SSE",
            action="buy_now",
            formal_rank=1,
        ),
        _future_observation(
            captured_at + timedelta(seconds=10),
            "600001.SSE",
            action="buy_now",
            formal_rank=1,
        ),
        _future_observation(captured_at + timedelta(seconds=20), "600001.SSE"),
        _future_observation(
            captured_at + timedelta(seconds=40),
            "600002.SSE",
            action="buy_now",
            formal_rank=1,
        ),
        _future_observation(captured_at + timedelta(seconds=60), "600001.SSE"),
    ]

    labeled = attach_point_trigger_labels(rows, future)
    by_symbol = {str(row["vt_symbol"]): row for row in labeled}

    assert by_symbol["600001.SSE"]["formal_event_at"] == captured_at + timedelta(
        seconds=40
    )
    assert by_symbol["600001.SSE"]["formal_identity_within_60s"] is False
    assert by_symbol["600002.SSE"]["formal_identity_within_60s"] is True


def test_label_is_unknown_for_internal_gap_or_cross_session_horizon() -> None:
    captured_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    gap_future = [
        _future_observation(captured_at + timedelta(seconds=15), "600001.SSE"),
        _future_observation(captured_at + timedelta(seconds=45), "600001.SSE"),
        _future_observation(captured_at + timedelta(seconds=60), "600001.SSE"),
    ]

    gap = attach_point_trigger_labels(
        [_point_row(captured_at, "600001.SSE")],
        gap_future,
    )[0]
    lunch_at = datetime(2026, 7, 21, 11, 29, 30, tzinfo=SHANGHAI)
    cross_session = attach_point_trigger_labels(
        [_point_row(lunch_at, "600001.SSE")],
        [],
    )[0]

    assert gap["label_status"] == "unknown_incomplete_horizon"
    assert gap["formal_event_within_60s"] is None
    assert cross_session["label_status"] == "unknown_cross_session_horizon"
    assert cross_session["formal_identity_within_60s"] is None

    metrics = point_trigger_label_metrics([gap, cross_session])
    assert metrics == {
        "label_row_count": 2,
        "label_eligible_horizon_row_count": 1,
        "label_known_row_count": 0,
        "label_unknown_incomplete_horizon_row_count": 1,
        "label_unknown_cross_session_row_count": 1,
        "label_unknown_other_row_count": 0,
        "label_known_ratio": 0.0,
        "label_known_eligible_horizon_ratio": 0.0,
        "reachable_formal_event_count": 0,
    }


def test_label_quality_finalizer_rejects_unknown_eligible_horizons() -> None:
    frames, observations = _complete_day(step_seconds=20.0)
    audit = audit_point_trigger_day(frames, observations)
    unknown = {
        **_point_row(
            datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI),
            "600001.SSE",
        ),
        "label_status": "unknown_incomplete_horizon",
        "formal_event_within_60s": None,
        "formal_identity_within_60s": None,
        "formal_identity_vt_symbol": None,
        "formal_event_at": None,
    }

    finalized = finalize_point_trigger_day_audit(audit, [unknown])

    assert finalized.is_complete is False
    assert finalized.eligible_for_model is False
    assert "label_known_eligible_horizon_ratio_below_98pct" in finalized.reason_codes


def test_label_quality_finalizer_reconciles_reverse_reachable_events() -> None:
    frames, observations = _complete_day(step_seconds=20.0)
    audit = audit_point_trigger_day(frames, observations)
    audit = replace(
        audit,
        metrics={
            **audit.metrics,
            "formal_event_static_eligible_within_60s_count": 1,
        },
    )

    finalized = finalize_point_trigger_day_audit(audit, [])

    assert finalized.is_complete is False
    assert finalized.metrics["reachable_formal_event_count"] == 0
    assert "reachable_event_label_cohort_incomplete" in finalized.reason_codes


def test_complete_zero_candidate_day_has_vacuous_label_coverage() -> None:
    frames, observations = _complete_day(step_seconds=20.0)
    audit = audit_point_trigger_day(frames, observations)

    finalized = finalize_point_trigger_day_audit(audit, [])

    assert finalized.is_complete is True
    assert finalized.eligible_for_model is True
    assert finalized.metrics["label_known_eligible_horizon_ratio"] == 1.0
    assert finalized.metrics["reachable_event_label_coverage_ratio"] == 1.0


def test_day_with_no_static_eligible_candidates_is_not_selected_out() -> None:
    frames, observations = _complete_day(step_seconds=20.0)
    for observation in observations:
        observation["lane_blocker_codes"] = [
            "first_board_repair_setup_missing"
        ]

    audit = audit_point_trigger_day(frames, observations)
    finalized = finalize_point_trigger_day_audit(audit, [])

    assert audit.metrics["eligible_candidate_count"] == 0
    assert audit.metrics["concept_acceleration_coverage_ratio"] == 1.0
    assert finalized.is_complete is True
    assert finalized.eligible_for_model is True


def test_day_with_zero_captured_observations_remains_a_complete_market_day() -> None:
    frames, _observations = _complete_day(step_seconds=20.0)
    for frame in frames:
        frame["capture_count"] = 0

    audit = audit_point_trigger_day(frames, [])
    finalized = finalize_point_trigger_day_audit(audit, [])

    assert audit.metrics["observation_capture_count_mismatch_count"] == 0
    assert audit.metrics["fresh_quote_ratio"] == 1.0
    assert audit.metrics["eligible_candidate_count"] == 0
    assert finalized.is_complete is True


def test_day_audit_rejects_frame_observation_count_mismatch() -> None:
    frames, observations = _complete_day(step_seconds=20.0)

    audit = audit_point_trigger_day(frames, observations[1:])

    assert audit.is_complete is False
    assert audit.metrics["observation_capture_count_mismatch_count"] == 1
    assert "observation_capture_count_mismatch" in audit.reason_codes


def test_day_audit_requires_frozen_formal_two_slot_evidence_on_every_frame() -> None:
    frames, observations = _complete_day(step_seconds=20.0)
    frames[0]["formal_two_slot_observed"] = None
    frames[0]["formal_two_slot_symbols"] = None

    audit = audit_point_trigger_day(frames, observations)

    assert audit.is_complete is False
    assert "formal_two_slot_evidence_incomplete" in audit.reason_codes
    assert audit.metrics["formal_two_slot_evidence_coverage_ratio"] < 1.0


def test_formal_baseline_orders_start_only_when_live_portfolio_reaches_buy_now() -> None:
    preboard_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    buy_now_at = preboard_at + timedelta(seconds=30)
    repeated_at = buy_now_at + timedelta(seconds=15)
    frames = [
        _frame(1, preboard_at),
        {
            **_frame(2, buy_now_at),
            "formal_two_slot_symbols": ["600001.SSE"],
        },
        {
            **_frame(3, repeated_at),
            "formal_two_slot_symbols": ["600001.SSE"],
        },
    ]
    observations = [
        _observation(1, preboard_at),
        {
            **_observation(2, buy_now_at),
            "formal_action": "buy_now",
            "capture_state": "sealed",
        },
        {
            **_observation(3, repeated_at),
            "formal_action": "buy_now",
            "capture_state": "sealed",
        },
    ]

    orders = build_formal_baseline_orders(frames, observations)

    assert len(orders) == 1
    assert orders[0]["vt_symbol"] == "600001.SSE"
    assert orders[0]["buy_time"] == "10:05:30"
    assert orders[0]["entry_price"] == 11.0
    assert orders[0]["source_frame_id"] == 2


def test_complete_day_audit_carries_its_formal_baseline_orders() -> None:
    frames, observations = _complete_day(step_seconds=20.0)
    frames[10]["formal_two_slot_symbols"] = ["600001.SSE"]
    observations[10].update(
        {"formal_action": "buy_now", "capture_state": "sealed"}
    )

    audit = audit_point_trigger_day(frames, observations)

    assert audit.is_complete is True
    assert audit.formal_baseline_order_projection_complete is True
    assert len(audit.formal_baseline_orders) == 1
    assert audit.formal_baseline_orders[0]["source_frame_id"] == frames[10]["id"]


def test_formal_baseline_order_projection_rejects_impossible_frame_state() -> None:
    captured_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    frame = {
        **_frame(1, captured_at),
        "formal_two_slot_symbols": ["600001.SSE"],
    }

    with pytest.raises(ValueError, match="formal portfolio symbol is not buy_now"):
        build_formal_baseline_orders([frame], [_observation(1, captured_at)])


def test_action_frame_eligibility_is_derived_from_frozen_causal_inputs() -> None:
    first_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    second_at = first_at + timedelta(seconds=15)
    rows = build_point_trigger_rows(
        [_frame(1, first_at), _frame(2, second_at)],
        [_observation(1, first_at), _observation(2, second_at)],
    )

    first, second = rows
    assert first["action_frame_eligible"] is False
    assert first["action_previous_frame_gap_seconds"] is None
    assert second["action_frame_eligible"] is True
    assert second["action_previous_frame_gap_seconds"] == 15.0
    assert second["action_quote_coverage_ratio"] == 0.95
    assert second["action_market_timing_observed"] is True
    assert second["formal_two_slot_observed"] is True
    assert second["formal_two_slot_symbols"] == []


def test_action_frame_eligibility_rejects_missing_market_timing_state() -> None:
    first_at = datetime(2026, 7, 21, 10, 5, tzinfo=SHANGHAI)
    second_at = first_at + timedelta(seconds=15)
    second_frame = _frame(2, second_at)
    second_frame["market_timing_state"] = None

    rows = build_point_trigger_rows(
        [_frame(1, first_at), second_frame],
        [_observation(1, first_at), _observation(2, second_at)],
    )

    second = rows[1]
    assert second["action_market_timing_observed"] is False
    assert second["action_frame_eligible"] is False
    assert point_trigger_input_fingerprint([second]) != point_trigger_input_fingerprint(
        [{**second, "action_market_timing_observed": True}]
    )


def test_model_field_whitelists_exclude_source_and_label_fields() -> None:
    forbidden = {
        "frame_id",
        "trade_date",
        "captured_at",
        "vt_symbol",
        "name",
        "concept_id",
        "sector_id",
        "formal_action",
        "formal_event_within_60s",
        "formal_identity_within_60s",
        "d1_net_return_pct",
    }

    assert FRAME_FEATURE_FIELDS
    assert IDENTITY_FEATURE_FIELDS
    assert forbidden.isdisjoint(FRAME_FEATURE_FIELDS)
    assert forbidden.isdisjoint(IDENTITY_FEATURE_FIELDS)
    assert len(FRAME_FEATURE_FIELDS) == len(set(FRAME_FEATURE_FIELDS))
    assert len(IDENTITY_FEATURE_FIELDS) == len(set(IDENTITY_FEATURE_FIELDS))


def _complete_day(
    *,
    step_seconds: float,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    frames: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []
    frame_id = 1
    for start_time, end_time in ((time(10, 0), time(11, 30)), (time(13, 0), time(14, 30))):
        current = datetime.combine(TRADE_DATE, start_time, SHANGHAI)
        end = datetime.combine(TRADE_DATE, end_time, SHANGHAI)
        while current <= end:
            frames.append(_frame(frame_id, current))
            observations.append(_observation(frame_id, current))
            frame_id += 1
            current += timedelta(seconds=step_seconds)
    return frames, observations


class _NonCopyableMapping(Mapping[str, object]):
    def __init__(self, values: Mapping[str, object]) -> None:
        self._values = values

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("point-trigger audit copied a complete observation row")

    def __len__(self) -> int:
        return len(self._values)


def _frame(frame_id: int, captured_at: datetime) -> dict[str, object]:
    return {
        "id": frame_id,
        "trade_date": captured_at.date(),
        "captured_at": captured_at,
        "capture_runtime_fingerprint": RUNTIME_FINGERPRINT,
        "source_trade_date": captured_at.date(),
        "quality_status": "ready",
        "is_stale": False,
        "quote_coverage_ratio": 0.95,
        "market_timing_state": "GOLD_ACTIVE",
        "formal_two_slot_observed": True,
        "formal_two_slot_symbols": [],
        "capture_count": 1,
    }


def _observation(
    frame_id: int,
    captured_at: datetime,
    *,
    gain: float = 4.0,
    rank: float = 70.0,
) -> dict[str, object]:
    return {
        "frame_id": frame_id,
        "captured_at": captured_at,
        "vt_symbol": "600001.SSE",
        "name": "测试股份",
        "change_pct": gain,
        "last_price": 10.4,
        "quote_observed_at": captured_at - timedelta(seconds=1),
        "quote_flow_observed_at": captured_at - timedelta(seconds=1),
        "volume": 1_000.0,
        "turnover": 10_000.0,
        "previous_close": 10.0,
        "limit_price": 11.0,
        "capture_state": "pre_radar",
        "board_lane": "first_board",
        "support_score": 61.0,
        "entry_quality_score": 65.0,
        "rank_score": rank,
        "quote_speed": 1.2,
        "quote_amplitude_pct": 4.5,
        "quote_main_net_inflow_ratio": 2.5,
        "concept_id": "BK0001",
        "concept_strength_score": 80.0,
        "concept_leader_rank": 1,
        "concept_strong_5_count": 3,
        "concept_change_acceleration_1m": 0.2,
        "concept_change_acceleration_3m": 0.3,
        "concept_change_acceleration_5m": 0.4,
        "concept_turnover_acceleration_1m": 1_000.0,
        "concept_turnover_acceleration_3m": 2_000.0,
        "concept_turnover_acceleration_5m": 3_000.0,
        "sector_main_net_inflow_ratio": 2.0,
        "sector_flow_trade_date": captured_at.date(),
        "stock_main_net_inflow_ratio": 1.0,
        "stock_flow_trade_date": captured_at.date(),
        "history_sample_count": 8,
        "historical_combined_rate": 45.0,
        "formal_action": "pass",
        "blocking_scope": "none",
        "lane_blocker_codes": [],
        "blocker_codes": [],
    }


def _point_row(captured_at: datetime, symbol: str) -> dict[str, object]:
    return {
        "contract_version": "limit-up-preboard-point-trigger-v9",
        "frame_id": 1,
        "trade_date": captured_at.date(),
        "captured_at": captured_at,
        "vt_symbol": symbol,
        "frame_features": {},
        "identity_features": {},
    }


def _future_observation(
    captured_at: datetime,
    symbol: str,
    *,
    action: str = "pass",
    formal_rank: int | None = None,
) -> dict[str, object]:
    return {
        "captured_at": captured_at,
        "vt_symbol": symbol,
        "board_lane": "first_board",
        "formal_action": action,
        "formal_rank": formal_rank,
        "rank_score": 70.0,
    }
