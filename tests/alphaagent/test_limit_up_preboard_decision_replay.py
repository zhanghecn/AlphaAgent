from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd

from alphaagent.server.services.limit_up import preboard_decision_replay as replay
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PreboardPolicyThresholds,
    PreboardRankingMode,
)
from alphaagent.server.services.limit_up.preboard_decision_replay import (
    ENTRY_CONTRACT,
    EXIT_CONTRACT,
    FROZEN_PATH_MANIFEST_VERSION,
    attach_replay_labels,
    build_historical_point_rows,
    build_replay_order_sets,
    calibrate_policy_thresholds,
    candidate_index_fingerprint,
    decide_historical_promotion,
    fit_opportunity_calibration,
    load_frozen_preboard_path_index,
    render_preboard_replay_markdown,
    split_replay_dates,
)


def test_main_requires_explicit_flag_to_publish_research_model(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        replay,
        "evaluate_preboard_replay",
        lambda **kwargs: calls.append(kwargs) or {"status": "historical_rejected"},
    )
    monkeypatch.setattr(replay, "render_preboard_replay_markdown", lambda _report: "")

    replay.main(["--sessions", "1", "--publish-research-model"])

    assert calls[0]["publish_research_model"] is True


def test_performance_report_records_peak_rss(monkeypatch) -> None:
    monkeypatch.setattr(replay, "_peak_rss_mib", lambda: 123.456)

    report = replay._performance_report(replay.monotonic())

    assert report["total_seconds"] >= 0
    assert report["peak_rss_mib"] == 123.456


def test_point_rows_are_causal_and_ignore_future_bars_and_labels() -> None:
    point = _point()

    baseline = build_historical_point_rows([point])
    changed = deepcopy(point)
    changed["candidates"][0].update(
        physical_touch_at="2026-07-20T10:12:00",
        first_limit_time="10:12:00",
        final_sealed=False,
        d1_close_price=8.0,
    )
    changed["candidates"][0]["minute_bars"].append(
        _bar(datetime(2026, 7, 20, 10, 12), 11.0, high=11.0)
    )

    after = build_historical_point_rows([changed])

    assert len(baseline) == len(after) == 1
    causal_fields = (
        "quality_gate_passed",
        "lane_blockers",
        "feature_values",
        "feature_fingerprint",
        "fillable",
        "entry_price",
    )
    assert {field: baseline[0][field] for field in causal_fields} == {
        field: after[0][field] for field in causal_fields
    }
    assert baseline[0]["decision_at"] == "2026-07-20T10:10:00"
    assert baseline[0]["signal_price"] < baseline[0]["limit_price"]
    assert baseline[0]["adapter_input_count"] == 1
    assert baseline[0]["capture_pool_count"] == 1
    assert baseline[0]["eligible_first_board_pool_count"] == 1
    assert baseline[0]["quality_pool_count"] == 1


def test_projected_point_rows_do_not_retain_transient_source_prefixes() -> None:
    point = _point()

    row = build_historical_point_rows([point])[0]

    assert {
        "minute_bars",
        "path_prefix",
        "candidates",
        "cross_section_snapshots",
        "transaction_rows",
        "historical_evidence",
        "execution_checks",
    }.isdisjoint(row)
    assert row["feature_status"] == "scoreable"
    assert row["feature_values"]
    assert row["next_quote_at"] == "2026-07-20T10:11:00"


def test_large_replay_indexes_reuse_loaded_dict_rows() -> None:
    minute = {
        "vt_symbol": "600001.SSE",
        "trade_date": "2026-07-20",
        "bar_time": "2026-07-20T10:10:00",
    }
    transaction = {
        "vt_symbol": "600001.SSE",
        "trade_date": "2026-07-20",
        "bar_time": "2026-07-20T10:10:00",
    }
    environment = {
        "vt_symbol": "600001.SSE",
        "trade_date": "2026-07-20",
        "captured_at": "2026-07-20T10:10:00",
    }

    assert replay._bars_by_pair([minute])[("600001.SSE", date(2026, 7, 20))][0] is minute
    assert replay._transaction_index([transaction])[
        ("600001.SSE", date(2026, 7, 20), datetime(2026, 7, 20, 10, 10))
    ] is transaction
    assert replay._environment_index([environment])[
        ("600001.SSE", date(2026, 7, 20))
    ][0] is environment


def test_prior_indexes_are_built_lazily_one_trade_date_at_a_time(monkeypatch) -> None:
    calls: list[tuple[str, date]] = []

    monkeypatch.setattr(
        replay.history_engine,
        "build_analog_index",
        lambda _rows, *, result_before: calls.append(("analog", result_before)) or {},
    )
    monkeypatch.setattr(
        replay,
        "build_same_stock_first_board_d1_index",
        lambda _rows, *, signal_date: calls.append(("stock", signal_date)) or {},
    )
    dates = (date(2026, 7, 17), date(2026, 7, 20))

    iterator = replay._iter_prior_indexes(dates, [])

    assert calls == []
    first_date, first_indexes = next(iterator)
    assert first_date == dates[0]
    assert first_indexes == ({}, {})
    assert calls == [("analog", dates[0]), ("stock", dates[0])]


def test_frozen_scope_indexes_drop_unrequested_pairs_and_symbols() -> None:
    kept_pair = ("600001.SSE", date(2026, 7, 20))
    dropped_pair = ("600002.SSE", date(2026, 7, 20))
    kept_feature = {"quality": "kept"}
    kept_financial = [(date(2026, 3, 31), {"report": "kept"})]

    features, financials = replay._filter_static_scope_indexes(
        (kept_pair,),
        {
            kept_pair: kept_feature,
            dropped_pair: {"quality": "dropped"},
        },
        {
            kept_pair[0]: kept_financial,
            dropped_pair[0]: [(date(2026, 3, 31), {"report": "dropped"})],
        },
    )

    assert features == {kept_pair: kept_feature}
    assert features[kept_pair] is kept_feature
    assert financials == {kept_pair[0]: kept_financial}
    assert financials[kept_pair[0]] is kept_financial


def test_frozen_scope_membership_survives_current_static_gate_drift() -> None:
    first = ("600001.SSE", date(2026, 7, 20))
    drifted = ("600002.SSE", date(2026, 7, 20))
    raw_manifest = pd.DataFrame(
        [
            {"vt_symbol": first[0], "trade_date": pd.Timestamp(first[1])},
            {"vt_symbol": drifted[0], "trade_date": pd.Timestamp(drifted[1])},
        ]
    )
    current_static_manifest = raw_manifest.iloc[:1].copy()

    scoped, audit = replay._reconstruct_frozen_static_scope(
        raw_manifest,
        current_static_manifest,
        (first, drifted),
        {first: {"feature": 1}, drifted: {"feature": 2}},
    )

    assert audit["status"] == "ready"
    assert len(scoped) == 2
    assert audit["current_static_upper_bound_pair_count"] == 1
    assert audit["current_static_drift_pairs"] == [
        {"vt_symbol": drifted[0], "trade_date": drifted[1].isoformat()}
    ]
    assert audit["current_static_role"] == "audit_only_not_membership"


def test_frozen_scope_reconstruction_fails_when_a_frozen_feature_is_missing() -> None:
    pair = ("600001.SSE", date(2026, 7, 20))
    manifest = pd.DataFrame(
        [{"vt_symbol": pair[0], "trade_date": pd.Timestamp(pair[1])}]
    )

    _scoped, audit = replay._reconstruct_frozen_static_scope(
        manifest,
        manifest,
        (pair,),
        {},
    )

    assert audit["status"] == "blocked_by_frozen_static_input_reconstruction"
    assert audit["missing_feature_pairs"] == [
        {"vt_symbol": pair[0], "trade_date": pair[1].isoformat()}
    ]


def test_recent_static_candidate_excludes_outcome_labels() -> None:
    manifest = {
        "vt_symbol": "600001.SSE",
        "trade_date": "2026-07-20",
        "name": "样本",
        "previous_close": 10.0,
        "limit_price": 11.0,
        "eligible_main_board": True,
        "physical_touch_at": "2026-07-20T10:20:00",
        "final_sealed": True,
        "d1_close_price": 11.5,
    }
    feature = {
        "financial_risk": {"blocked": False, "level": "clear", "reasons": []},
        "financial_snapshot": {},
        "formal_baseline_identity": True,
        "net_return_pct": 5.0,
    }

    candidate = replay._static_candidate(
        manifest,
        feature,
        financial_index={},
    )

    assert replay._LABEL_ONLY_FIELDS.isdisjoint(candidate)
    assert candidate["vt_symbol"] == "600001.SSE"
    assert candidate["trade_date"] == "2026-07-20"


def test_recent_current_code_replay_activates_after_three_and_uses_completed_bars(
    monkeypatch,
) -> None:
    from alphaagent.server.services.limit_up.first_board_quality import PreboardPools

    trade_date = date(2026, 7, 20)
    symbol = "600001.SSE"
    pair = (symbol, trade_date)
    static = {
        "vt_symbol": symbol,
        "trade_date": trade_date.isoformat(),
        "previous_close": 10.0,
        "limit_price": 11.0,
        "expected_d1_net_return_pct": 2.0,
        "d1_win_probability": 0.70,
        "seal_probability_given_touch": 0.75,
    }
    minute_rows = tuple(
        {
            **_bar(datetime(2026, 7, 20, 10, minute), close),
            "vt_symbol": symbol,
            "trade_date": trade_date.isoformat(),
        }
        for minute, close in ((0, 10.20), (1, 10.80), (2, 10.95))
    )
    inputs = replay.RecentReplayInputs(
        status="ready",
        candidates={pair: static},
        minute_rows=minute_rows,
        transaction_rows=(),
        audit={"membership_rule": "label_independent"},
    )
    observations = [
        {
            "vt_symbol": symbol,
            "trade_date": trade_date.isoformat(),
            "captured_at": "2026-07-20T10:00:30",
            "last_price": 10.29,
            "limit_price": 11.0,
            "change_pct": 2.9,
            "capture_state": "pre_radar",
        },
        {
            "vt_symbol": symbol,
            "trade_date": trade_date.isoformat(),
            "captured_at": "2026-07-20T10:01:30",
            "last_price": 10.89,
            "limit_price": 11.0,
            "change_pct": 8.9,
            "capture_state": "near_limit",
        },
        {
            "vt_symbol": symbol,
            "trade_date": trade_date.isoformat(),
            "captured_at": "2026-07-20T10:02:30",
            "last_price": 10.98,
            "limit_price": 11.0,
            "change_pct": 9.8,
            "capture_state": "failed",
        },
    ]
    projected_bar_times: list[list[datetime]] = []

    monkeypatch.setattr(
        replay,
        "build_lane_prefixes",
        lambda rows, *, previous_close: [
            {"point_count": index + 1} for index, _row in enumerate(rows)
        ],
    )

    def build_pools(candidates, *, decision_at, market_gate):
        candidate = {**dict(candidates[0]), "quality_gate_passed": True}
        active = float(candidate["change_pct"]) >= 3.0
        failed = candidate.get("capture_state") == "failed"
        stage = (
            "eligible_already_touched_or_failed"
            if failed
            else "quality_pool"
            if active
            else "eligible_below_observation_floor"
        )
        reasons = (
            ("already_touched_or_failed",)
            if failed
            else ()
            if active
            else ("below_observation_floor",)
        )
        return PreboardPools(
            adapter_input_count=1,
            capture_pool=(candidate,),
            eligible_first_board_pool=(candidate,),
            quality_pool=(candidate,) if active and not failed else (),
            rejection_counts=(
                {"already_touched_or_failed": 1}
                if failed
                else {}
                if active
                else {"below_observation_floor": 1}
            ),
            candidate_audit=(
                {
                    **candidate,
                    "pool_stage": stage,
                    "rejection_codes": reasons,
                    "strictly_preboard": not failed,
                    "preboard_hard_blockers": (),
                    "preboard_deferred_blockers": (),
                    "failed_environment_checks": (),
                    "diagnostic_environment_checks": (),
                },
            ),
        )

    monkeypatch.setattr(replay, "build_preboard_pools", build_pools)

    def project(_prepared, *, minute_bars, cross_section_snapshots):
        projected_bar_times.append([row["bar_time"] for row in minute_bars])
        return {"feature_status": "scoreable"}

    monkeypatch.setattr(
        replay,
        "project_prepared_historical_decision_features",
        project,
    )
    monkeypatch.setattr(
        replay,
        "score_preboard_rows",
        lambda _model, rows: [
            {
                **dict(row),
                "feature_status": "scoreable",
                "probability_status": "ready",
                "touch_probability_3m": 0.80,
                "eventual_touch_probability": 0.90,
            }
            for row in rows
        ],
    )

    summary, by_pair = replay._replay_recent_current_code(
        inputs,
        observations,
        model_bundle=object(),
    )

    metrics = by_pair[pair]
    assert summary["capture_pair_count"] == 1
    assert summary["quality_pair_count"] == 1
    assert metrics["first_capture_pool_at"] == "2026-07-20T10:00:30"
    assert metrics["first_quality_pass_at"] == "2026-07-20T10:00:30"
    assert metrics["first_ge_3_at"] == "2026-07-20T10:01:30"
    assert metrics["first_quality_pool_at"] == "2026-07-20T10:01:30"
    assert metrics["first_scoreable_at"] == "2026-07-20T10:01:30"
    assert metrics["first_probability_rank_top2_at"] == "2026-07-20T10:01:30"
    assert metrics["maximum_replayed_preboard_gain_pct"] == 8.9
    assert metrics["maximum_replayed_preboard_pool_stage"] == "quality_pool"
    assert metrics["last_pool_stage"] == "eligible_already_touched_or_failed"
    assert projected_bar_times == [
        [
            datetime(2026, 7, 20, 10, 0),
            datetime(2026, 7, 20, 10, 1),
        ]
    ]


def test_label_attachment_does_not_change_model_inputs() -> None:
    row = build_historical_point_rows([_point()])[0]
    labels = {
        (date(2026, 7, 20), "600001.SSE"): {
            "physical_touch_at": "2026-07-20T10:12:00",
            "formal_baseline_identity": True,
            "sealed_limit": True,
            "d1_close_price": 11.5,
            "result_date": "2026-07-21",
        }
    }

    labeled = attach_replay_labels([row], labels)[0]

    assert labeled["feature_values"] == row["feature_values"]
    assert labeled["feature_fingerprint"] == row["feature_fingerprint"]
    assert labeled["formal_touch_within_3m"] is True
    assert labeled["eventual_formal_touch"] is True
    assert labeled["d1_net_return_pct"] is not None


def test_touch_price_or_unreachable_next_quote_never_becomes_an_order() -> None:
    below = build_historical_point_rows([_point(next_open=10.75)])[0]
    touched = build_historical_point_rows([_point(next_open=11.0)])[0]
    missing = build_historical_point_rows([_point(next_open=None)])[0]
    thresholds = _thresholds()
    for row in (below, touched, missing):
        row.update(
            probability_status="ready",
            touch_probability_3m=0.90,
            eventual_touch_probability=0.95,
        )

    order_sets = build_replay_order_sets(
        rows=[below, touched, missing],
        thresholds=thresholds,
        formal_orders=[],
    )

    assert ENTRY_CONTRACT == "first_new_quote_after_action_strictly_below_limit"
    assert EXIT_CONTRACT == "d1_official_close_after_formal_costs"
    assert len(order_sets["c_first_board_orders"]) == 1
    order = order_sets["c_first_board_orders"][0]
    assert order["entry_price"] == 10.75
    assert order["entry_price"] < order["limit_price"]


def test_strict_preboard_uses_first_probability_action_and_keeps_relay() -> None:
    early = build_historical_point_rows([_point(decision_time="10:10:00")])[0]
    late_point = _point(decision_time="10:11:00", next_open=10.82)
    late = build_historical_point_rows([late_point])[0]
    for row in (early, late):
        row.update(
            probability_status="ready",
            touch_probability_3m=0.90,
            eventual_touch_probability=0.95,
        )
    relay = {
        "vt_symbol": "600099.SSE",
        "lane": "two_to_three",
        "signal_date": "2026-07-20",
        "buy_time": "10:20:00",
        "entry_price": 20.0,
        "limit_price": 20.0,
    }

    order_sets = build_replay_order_sets(
        rows=[early, late],
        thresholds=_thresholds(),
        formal_orders=[relay],
    )

    assert order_sets["c_action_rows"][0]["decision_at"].endswith("10:10:00")
    assert order_sets["c_combined_orders"][0] == relay


def test_action_pool_is_counted_before_two_slot_selection() -> None:
    rows = []
    for index in range(3):
        point = _point(decision_time="10:10:00", next_open=10.75 + index * 0.01)
        point["candidates"][0]["vt_symbol"] = f"60000{index}.SSE"
        row = build_historical_point_rows([point])[0]
        row.update(
            probability_status="ready",
            touch_probability_3m=0.90,
            eventual_touch_probability=0.95,
        )
        rows.append(row)

    order_sets = build_replay_order_sets(
        rows=rows,
        thresholds=_thresholds(),
        formal_orders=[],
    )

    assert len(order_sets["c_action_pool_rows"]) == 3
    assert len(order_sets["c_action_rows"]) == 2
    assert len(order_sets["c_first_board_orders"]) == 2


def test_pool_audit_reports_high_quality_mother_pool_before_observation() -> None:
    rows = [
        {
            "trade_date": "2026-07-20",
            "vt_symbol": "600001.SSE",
            "execution_environment_passed": False,
            "failed_environment_checks": ("market_gate",),
        },
        {
            "trade_date": "2026-07-20",
            "vt_symbol": "600002.SSE",
            "execution_environment_passed": False,
            "failed_environment_checks": ("market_gate",),
        },
    ]

    audit = replay._pool_audit(
        rows,
        {"2026-07-20": 3},
        {"2026-07-20": {"600001.SSE", "600002.SSE", "600003.SSE"}},
    )

    daily = audit["daily"][0]
    assert daily["raw_capture_symbol_count"] == 3
    assert daily["eligible_first_board_point_count"] == 2
    assert daily["eligible_first_board_symbol_count"] == 2
    assert daily["quality_pool_point_count"] == 2


def test_threshold_calibration_reads_only_calibration_dates() -> None:
    start = date(2026, 6, 1)
    calibration_dates = {start + timedelta(days=index) for index in range(10)}
    rows = []
    for index, trade_date in enumerate(sorted(calibration_dates)):
        rows.append(
            _scored_row(
                trade_date,
                f"600{index:03d}.SSE",
                probability=0.6 + index * 0.02,
                net_return=1.0,
            )
        )
    validation = _scored_row(
        date(2026, 7, 1),
        "601999.SSE",
        probability=0.99,
        net_return=-9.0,
    )

    baseline = calibrate_policy_thresholds(
        [*rows, validation],
        calibration_dates=calibration_dates,
        model_fingerprint="sha256:model",
        minimum_action_count=10,
    )
    changed = {**validation, "d1_net_return_pct": 10.0, "formal_touch_within_3m": True}
    after = calibrate_policy_thresholds(
        [*rows, changed],
        calibration_dates=calibration_dates,
        model_fingerprint="sha256:model",
        minimum_action_count=10,
    )

    assert baseline.status == after.status == "ready"
    assert baseline.thresholds == after.thresholds
    assert baseline.selected_metrics == after.selected_metrics


def test_opportunity_calibration_uses_fit_only_and_one_row_per_stock_day() -> None:
    fit_date = date(2026, 6, 1)
    rows = []
    for index in range(5):
        touched = _scored_row(
            fit_date,
            f"6001{index:02d}.SSE",
            probability=0.80,
            net_return=-2.0,
        )
        touched.update(eventual_formal_touch=True, sealed_limit=False)
        rows.append(touched)
        non_touch = _scored_row(
            fit_date,
            f"6002{index:02d}.SSE",
            probability=0.80,
            net_return=-4.0,
        )
        non_touch.update(eventual_formal_touch=False, sealed_limit=False)
        rows.append(non_touch)

    duplicate = {**rows[0], "decision_at": "2026-06-01T10:11:00", "d1_net_return_pct": 50.0}
    validation_outlier = {
        **rows[-1],
        "trade_date": "2026-07-01",
        "signal_date": "2026-07-01",
        "decision_at": "2026-07-01T10:10:00",
        "d1_net_return_pct": -99.0,
    }

    result = fit_opportunity_calibration(
        [*rows, duplicate, validation_outlier],
        fit_dates={fit_date},
        thresholds=_thresholds(),
        model_fingerprint="sha256:model",
    )

    assert result.status == "ready"
    assert result.calibration is not None
    assert result.calibration.touched_unsealed_sample_count == 5
    assert result.calibration.non_touch_sample_count == 5
    assert result.calibration.touched_unsealed_expected_return_pct == -2.0
    assert result.calibration.non_touch_expected_return_pct == -4.0


def test_opportunity_calibration_fails_closed_when_a_failure_branch_is_small() -> None:
    fit_date = date(2026, 6, 1)
    rows = []
    for index in range(4):
        row = _scored_row(
            fit_date,
            f"6003{index:02d}.SSE",
            probability=0.80,
            net_return=-3.0,
        )
        row.update(eventual_formal_touch=False, sealed_limit=False)
        rows.append(row)

    result = fit_opportunity_calibration(
        rows,
        fit_dates={fit_date},
        thresholds=_thresholds(),
        model_fingerprint="sha256:model",
    )

    assert result.status == "insufficient_fit_scenarios"
    assert result.calibration is None


def test_replay_order_sets_can_compare_touch_first_without_changing_action_pool() -> None:
    trade_date = date(2026, 7, 1)
    high_d1 = _scored_row(
        trade_date,
        "600001.SSE",
        probability=0.71,
        net_return=1.0,
    )
    high_d1["expected_d1_net_return_pct"] = 5.0
    high_touch = _scored_row(
        trade_date,
        "600002.SSE",
        probability=0.95,
        net_return=1.0,
    )
    high_touch["expected_d1_net_return_pct"] = 1.0
    middle_touch = _scored_row(
        trade_date,
        "600003.SSE",
        probability=0.90,
        net_return=1.0,
    )
    middle_touch["expected_d1_net_return_pct"] = 0.5

    current = build_replay_order_sets(
        rows=[high_d1, high_touch, middle_touch],
        thresholds=_thresholds(),
        formal_orders=[],
    )
    touch_first = build_replay_order_sets(
        rows=[high_d1, high_touch, middle_touch],
        thresholds=_thresholds(),
        formal_orders=[],
        ranking_mode=PreboardRankingMode.PURE_TOUCH_PROBABILITY,
    )

    assert len(current["c_action_pool_rows"]) == len(
        touch_first["c_action_pool_rows"]
    ) == 3
    assert [row["vt_symbol"] for row in current["c_action_rows"]] == [
        "600001.SSE",
        "600002.SSE",
    ]
    assert [row["vt_symbol"] for row in touch_first["c_action_rows"]] == [
        "600002.SSE",
        "600003.SSE",
    ]


def test_ranking_topk_uses_the_same_action_gate_as_slot_selection() -> None:
    trade_date = date(2026, 7, 1)
    eligible = _scored_row(
        trade_date,
        "600001.SSE",
        probability=0.80,
        net_return=1.0,
    )
    environment_blocked = _scored_row(
        trade_date,
        "600002.SSE",
        probability=0.99,
        net_return=1.0,
    )
    environment_blocked["execution_environment_passed"] = False

    report = replay._ranking_topk_report(
        [eligible, environment_blocked],
        allowed_dates={trade_date},
        thresholds=_thresholds(),
        ranking_mode=PreboardRankingMode.PURE_TOUCH_PROBABILITY,
        opportunity_calibration=None,
    )

    assert report["formal_positive_pair_count"] == 1
    assert report["top1_covered_count"] == 1
    assert report["top2_unique_pair_count"] == 1


def test_date_split_is_exact_44_15_30() -> None:
    start = date(2026, 3, 1)
    dates = [start + timedelta(days=index) for index in range(89)]

    split = split_replay_dates(dates)

    assert len(split.fit) == 44
    assert len(split.calibration) == 15
    assert len(split.validation) == 30
    assert max(split.fit) < min(split.calibration) < min(split.validation)


def test_replay_session_calendar_keeps_zero_candidate_trading_days() -> None:
    start = date(2026, 3, 1)
    sessions = [start + timedelta(days=index) for index in range(89)]

    bounded = replay._bounded_replay_dates(
        start=sessions[0],
        end=sessions[-1],
        trade_dates=[sessions[0] - timedelta(days=1), *sessions, sessions[-1] + timedelta(days=1)],
    )

    assert bounded == tuple(sessions)
    assert len(bounded) == 89


def test_frozen_v1_path_index_does_not_rebuild_the_v2_scope(monkeypatch) -> None:
    manifest = {
        "manifest_version": FROZEN_PATH_MANIFEST_VERSION,
        "session_count": 89,
        "start_date": date(2026, 3, 11),
        "end_date": date(2026, 7, 20),
        "status": "ready",
        "input_fingerprint": "sha256:frozen-v1",
        "manifest_pair_count": 4,
        "complete_minute_pair_count": 4,
        "static_upper_bound_pair_count": 3,
        "shared_pair_count": 2,
        "pairs": [
            {"vt_symbol": "600001.SSE", "trade_date": "2026-07-17"},
            {"vt_symbol": "000001.SZSE", "trade_date": "2026-07-20"},
        ],
    }
    calls = []

    def load_manifest(*, manifest_version, session_count, end_date):
        calls.append((manifest_version, session_count, end_date))
        return manifest

    def load_coverage(frame):
        assert set(frame.columns) == {"vt_symbol", "trade_date"}
        return [
            {
                "vt_symbol": row["vt_symbol"],
                "trade_date": row["trade_date"],
                "coverage_status": "complete",
                "raw_row_count": 240,
            }
            for row in frame.to_dict(orient="records")
        ]

    def load_flow_coverage(pairs, *, feature_version):
        assert len(pairs) == 2
        assert feature_version
        return {"ready_pair_count": 2, "requested_pair_count": 2}

    index = load_frozen_preboard_path_index(
        session_count=89,
        end_date=date(2026, 7, 20),
        verify_reference=False,
        manifest_loader=load_manifest,
        minute_coverage_loader=load_coverage,
        transaction_coverage_loader=load_flow_coverage,
    )

    assert calls == [(FROZEN_PATH_MANIFEST_VERSION, 89, date(2026, 7, 20))]
    assert index.status == "ready"
    assert len(index.pairs) == 2
    assert index.minute_complete_pair_count == 2
    assert index.transaction_ready_pair_count == 2
    assert index.raw_upper_bound_pair_count == 4
    assert index.source_complete_minute_pair_count == 4
    assert index.static_high_quality_pair_count == 3


def test_candidate_index_fingerprint_ignores_all_outcome_labels() -> None:
    rows = [
        {
            "vt_symbol": "600001.SSE",
            "trade_date": "2026-07-20",
            "physical_touch_at": "2026-07-20T10:30:00",
            "sealed_limit": True,
            "d1_close_price": 11.5,
            "formal_baseline_identity": True,
        },
        {
            "vt_symbol": "600002.SSE",
            "trade_date": "2026-07-20",
            "physical_touch_at": None,
            "sealed_limit": False,
            "d1_close_price": 9.5,
            "formal_baseline_identity": False,
        },
    ]
    mutated = [
        {
            **row,
            "physical_touch_at": (
                None if row["physical_touch_at"] else "2099-01-01T10:00:00"
            ),
            "sealed_limit": not row["sealed_limit"],
            "d1_close_price": 100.0 - float(row["d1_close_price"]),
            "formal_baseline_identity": not row["formal_baseline_identity"],
        }
        for row in rows
    ]

    assert candidate_index_fingerprint(rows) == candidate_index_fingerprint(mutated)


def test_insufficient_date_split_report_uses_frozen_feature_rows(monkeypatch) -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(10))
    dataset = replay.ReplayDataset(
        status="ready",
        dates=dates,
        rows=(
            {
                "trade_date": dates[-1].isoformat(),
                "feature_status": "scoreable",
                "feature_values": {},
                "known_at": f"{dates[-1].isoformat()}T10:00:00",
                "decision_at": f"{dates[-1].isoformat()}T10:00:00",
            },
        ),
        formal_orders=(),
        account_bars=(),
        trade_dates=dates,
        market_diagnostics={},
        coverage={},
        candidate_index_audit={},
        pool_audit={},
        profitability_audit={},
        input_fingerprint="sha256:" + "a" * 64,
    )
    monkeypatch.setattr(
        replay,
        "load_frozen_replay_dataset",
        lambda **_kwargs: dataset,
    )

    report = replay.evaluate_preboard_replay()

    assert report["decision"]["reason"] == "frozen_date_split_insufficient"
    assert report["dataset"]["feature_parity_audit"]["field_count"] > 0


def test_probability_rejection_short_circuits_threshold_search(monkeypatch) -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(89))
    dataset = replay.ReplayDataset(
        status="ready",
        dates=dates,
        rows=({"trade_date": dates[-1].isoformat()},),
        formal_orders=(),
        account_bars=(),
        trade_dates=dates,
        market_diagnostics={},
        coverage={},
        candidate_index_audit={"label_mutation_membership_invariant": True},
        pool_audit={},
        profitability_audit={},
        input_fingerprint="sha256:" + "a" * 64,
    )
    model = SimpleNamespace(
        status="ready",
        fingerprint="sha256:" + "b" * 64,
        feature_names=(),
        head_reports={},
    )
    monkeypatch.setattr(
        replay,
        "load_frozen_replay_dataset",
        lambda **_kwargs: dataset,
    )
    monkeypatch.setattr(
        replay,
        "fit_preboard_model",
        lambda *_args, **_kwargs: model,
    )
    monkeypatch.setattr(
        replay,
        "score_preboard_rows",
        lambda _model, rows: [dict(row) for row in rows],
    )
    monkeypatch.setattr(
        replay,
        "qualify_preboard_probabilities",
        lambda _rows: {
            "status": "model_unavailable",
            "reasons": ["touch_3m:brier_not_better_than_climatology"],
            "heads": {},
        },
    )
    monkeypatch.setattr(
        replay,
        "calibrate_policy_thresholds",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("threshold search must not run")
        ),
    )
    recent_timing = {
        "status": "ready",
        "formal_positive_count": 1,
        "rows": [
            {
                "trade_date": "2026-07-21",
                "vt_symbol": "603629.SSE",
                "formal_baseline_positive": True,
                "formal_touch_at": "2026-07-21T10:59:08",
                "last_preboard_at": "2026-07-21T10:58:08",
                "gate_matrix": [
                    {"code": "stock_momentum", "status": "failed"}
                ],
            }
        ],
    }
    monkeypatch.setattr(
        replay,
        "load_recent_live_timing_audit",
        lambda _start, _end, **_kwargs: recent_timing,
    )

    report = replay.evaluate_preboard_replay()

    assert report["status"] == "probability_rejected"
    assert report["calibration"]["status"] == "not_run_probability_rejected"
    assert report["validation"]["accounts"]["a_first_board"]["filled_count"] == 0
    assert report["validation"]["accounts"]["c_first_board"]["filled_count"] == 0
    assert "consecutive_losses" in report["validation"]
    assert set(report["validation"]["half_hour_by_account"]) == {
        "a_first_board",
        "c_first_board",
    }
    assert report["recent_live_timing"] == recent_timing
    assert report["recent_live_timing"]["rows"][0]["formal_baseline_positive"] is True


def test_recent_timing_audit_uses_formal_backtest_orders_as_positive_labels(
    monkeypatch,
) -> None:
    from alphaagent.server.services.limit_up import (
        preboard_decision_repository,
        radar_observation_repository,
    )

    formal_order = {
        "entry_date": "2026-07-21",
        "vt_symbol": "603629.SSE",
        "name": "利通电子",
        "lane": "first_board",
        "buy_time": "10:59:08",
        "decision": "eligible",
    }
    observations = [
        {
            "trade_date": date(2026, 7, 21),
            "captured_at": datetime(2026, 7, 21, 10, 58, 8),
            "vt_symbol": "603629.SSE",
            "name": "利通电子",
            "change_pct": 8.701,
            "last_price": 106.31,
            "limit_price": 107.58,
            "capture_state": "near_limit",
            "support_score": 54.4362,
            "concept_state": "warming",
            "concept_leader_rank": 2,
            "sector_main_net_inflow": -982_000_000.0,
            "history_sample_count": 15,
            "historical_combined_rate": 86.67,
            "formal_action": "pass",
            "lane_blocker_codes": [],
            "blocker_codes": ["stock_momentum", "sector_route"],
        },
        {
            "trade_date": date(2026, 7, 21),
            "captured_at": datetime(2026, 7, 21, 10, 59, 8),
            "vt_symbol": "603629.SSE",
            "name": "利通电子",
            "change_pct": 10.0,
            "last_price": 107.58,
            "limit_price": 107.58,
            "capture_state": "sealed",
            "formal_action": "pass",
            "lane_blocker_codes": [],
            "blocker_codes": [],
        },
    ]
    loaded_symbols: list[str] = []

    monkeypatch.setattr(
        replay,
        "_recent_formal_baseline_orders",
        lambda _start, _end: [formal_order],
        raising=False,
    )
    monkeypatch.setattr(
        radar_observation_repository,
        "load_frames",
        lambda _start, _end: [],
    )
    monkeypatch.setattr(
        radar_observation_repository,
        "load_action_observation_pairs",
        lambda _start, _end: [],
        raising=False,
    )

    def load_observations(_start, _end, *, symbols=None):
        loaded_symbols.extend(symbols or ())
        return observations

    monkeypatch.setattr(
        radar_observation_repository,
        "load_observations",
        load_observations,
    )
    monkeypatch.setattr(
        preboard_decision_repository,
        "load_decision_feature_rows",
        lambda _dates, *, symbols=None: [],
    )
    monkeypatch.setattr(
        preboard_decision_repository,
        "load_decision_actions",
        lambda **_kwargs: [],
    )

    report = replay.load_recent_live_timing_audit(
        date(2026, 7, 21),
        date(2026, 7, 22),
    )

    assert loaded_symbols == ["603629.SSE"]
    assert report["formal_positive_count"] == 1
    assert report["queried_symbol_count"] == 1
    assert len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["formal_baseline_positive"] is True
    assert row["formal_touch_at"] == "2026-07-21T10:59:08"
    assert row["last_preboard_at"] == "2026-07-21T10:58:08"
    assert row["last_preboard_gain_pct"] == 8.701
    assert row["maximum_preboard_gain_pct"] == 8.701
    assert row["formal_touch_lead_seconds"] == 60.0
    assert {item["code"]: item["status"] for item in row["gate_matrix"]} == {
        "formal_baseline_quality": "passed",
        "strict_preboard_price": "passed",
        "profitability_gate": "passed",
        "lane_quality": "passed",
        "stock_momentum": "failed",
        "sector_route": "failed",
        "stock_flow": "unknown",
        "turnover_rate": "unknown",
        "completed_minute_features": "failed",
        "touch_probability_3m": "unavailable",
        "eventual_touch_probability": "unavailable",
        "d1_priority": "unavailable",
        "two_slot": "not_selected",
        "current_product_rank_top2": "not_selected",
        "current_touch_probability_rank_top2": "not_selected",
    }


def test_half_hour_report_always_has_six_fixed_cash_buckets() -> None:
    trade_date = date(2026, 7, 20)
    dataset = replay.ReplayDataset(
        status="ready",
        dates=(trade_date,),
        rows=(),
        formal_orders=(),
        account_bars=(),
        trade_dates=(trade_date,),
        market_diagnostics={},
        coverage={},
        candidate_index_audit={},
        pool_audit={},
        profitability_audit={},
        input_fingerprint="sha256:" + "a" * 64,
    )

    rows = replay._half_hour_report(
        [],
        orders=[],
        dataset=dataset,
        allowed_dates={trade_date},
    )

    assert [row["time_bucket"] for row in rows] == [
        "10:00-10:30",
        "10:30-11:00",
        "11:00-11:30",
        "13:00-13:30",
        "13:30-14:00",
        "14:00-14:30",
    ]
    for row in rows:
        assert set(row) == {
            "time_bucket",
            "action_count",
            "strict_fill_count",
            "formal_touch_within_3m_rate_pct",
            "eventual_formal_touch_rate_pct",
            "d1_win_rate_pct",
            "d1_expected_return_pct",
            "cash_compound_return_pct",
        }


def test_consecutive_loss_report_distinguishes_false_positive_and_ranking_error() -> None:
    trade_date = date(2026, 7, 20)
    account = {
        "executed_trades": [
            {
                "entry_date": trade_date.isoformat(),
                "vt_symbol": "600001.SSE",
                "return_pct": -3.0,
                "eventual_formal_touch": False,
            },
            {
                "entry_date": trade_date.isoformat(),
                "vt_symbol": "600002.SSE",
                "return_pct": -2.0,
                "eventual_formal_touch": True,
            },
        ]
    }
    quality_rows = [
        {
            "trade_date": trade_date.isoformat(),
            "vt_symbol": "600003.SSE",
            "d1_net_return_pct": 4.0,
        }
    ]

    report = replay._consecutive_loss_report(
        {"a_first_board": account, "c_first_board": account},
        quality_rows,
        market_diagnostics={
            trade_date.isoformat(): {
                "trade_date": trade_date.isoformat(),
                "failed_rate_pct": 25.0,
                "d1_gold_silver_state": "GOLD_ACTIVE",
            }
        },
        allowed_dates={trade_date},
    )

    run = report["c_first_board"]["runs"][0]
    assert run["classification_counts"] == {
        "false_positive_occupancy": 1,
        "ranking_error": 1,
    }
    assert run["unselected_positive_quality_pool"][0]["vt_symbol"] == "600003.SSE"


def test_unreplayable_historical_environment_matches_live_diagnostic_contract() -> None:
    point = _point()
    candidate = point["candidates"][0]
    candidate["execution_checks"] = [
        {"code": "stock_momentum", "status": "passed", "blocking": True},
        {"code": "sector_route", "status": "pending", "blocking": True},
        {"code": "stock_flow", "status": "pending", "blocking": True},
        {"code": "turnover_rate", "status": "passed", "blocking": True},
    ]

    row = build_historical_point_rows([point])[0]
    row.update(
        probability_status="ready",
        touch_probability_3m=0.99,
        eventual_touch_probability=0.99,
    )
    order_sets = build_replay_order_sets(
        rows=[row],
        thresholds=_thresholds(),
        formal_orders=[],
    )

    assert row["quality_gate_passed"] is True
    assert row["execution_environment_passed"] is True
    assert row["failed_environment_checks"] == ()
    assert set(row["diagnostic_environment_checks"]) == {
        "sector_route",
        "stock_flow",
    }
    assert [value["vt_symbol"] for value in order_sets["c_action_rows"]] == [
        row["vt_symbol"]
    ]


def test_promotion_requires_twenty_strict_actions_and_both_accounts() -> None:
    passing_account = {
        "filled_count": 20,
        "win_rate": 68.0,
        "total_return_pct": 18.0,
        "max_drawdown_pct": -5.0,
        "profit_factor": 1.8,
    }
    baseline = {
        "filled_count": 20,
        "win_rate": 69.0,
        "total_return_pct": 19.0,
        "max_drawdown_pct": -4.0,
        "profit_factor": 2.0,
    }

    insufficient = decide_historical_promotion(
        strict_first_board=passing_account,
        formal_first_board=baseline,
        strict_combined=passing_account,
        formal_combined=baseline,
        strict_double_cost={**passing_account, "total_return_pct": 5.0},
        positive_stability_blocks=3,
        strict_action_count=19,
    )
    passed = decide_historical_promotion(
        strict_first_board=passing_account,
        formal_first_board=baseline,
        strict_combined=passing_account,
        formal_combined=baseline,
        strict_double_cost={**passing_account, "total_return_pct": 5.0},
        positive_stability_blocks=3,
        strict_action_count=20,
    )

    assert insufficient["status"] == "insufficient_for_portfolio_promotion"
    assert passed["status"] == "historical_pass_for_shadow"


def test_markdown_reports_only_formal_and_strict_accounts() -> None:
    markdown = render_preboard_replay_markdown(
        {
            "status": "insufficient_for_portfolio_promotion",
            "decision": {"reason": "insufficient_calibration_actions"},
            "formal_strategy_changed": False,
            "date_split": {
                "fit": {"date_count": 44},
                "calibration": {"date_count": 15},
                "validation": {"date_count": 30},
            },
            "dataset": {
                "coverage": {
                    "quality_pool": {"point_count": 100, "pair_count": 10},
                    "historical_environment": {"date_count": 1},
                },
                "pool_audit": {
                    "distributions": {
                        "raw_capture_symbol_count": {"p50": 8, "p90": 12},
                        "eligible_first_board_symbol_count": {"p50": 3, "p90": 5},
                        "quality_pool_symbol_count": {"p50": 3, "p90": 5},
                    },
                    "environment_failure_counts": {"market_gate": 100},
                },
            },
            "model": {"status": "ready", "model_fingerprint": "sha256:model"},
            "calibration": {"status": "insufficient_calibration_actions"},
            "validation": {"accounts": {}, "identity_and_timing": {}},
            "recent_live_timing": {"rows": []},
            "performance": {"peak_rss_mib": 123.456},
        }
    )

    assert "44 / 15 / 30" in markdown
    assert "五层漏斗" in markdown
    assert "A 正式触板首板" in markdown
    assert "C 新严格板前首板" in markdown
    assert "market_gate" in markdown
    assert "回放峰值 RSS：123.4560 MiB" in markdown


def test_markdown_does_not_render_unavailable_combined_ranking_as_zero() -> None:
    markdown = render_preboard_replay_markdown(
        {
            "status": "historical_rejected",
            "decision": {},
            "dataset": {},
            "model": {},
            "calibration": {},
            "validation": {
                "ranking_comparison": {
                    "strategies": {
                        "combined_opportunity_value": {
                            "status": "insufficient_fit_scenarios"
                        }
                    }
                }
            },
        }
    )

    combined_row = next(
        line for line in markdown.splitlines() if line.startswith("| 综合机会价值")
    )
    assert "insufficient_fit_scenarios" in combined_row
    assert "| 0 |" not in combined_row


def _point(
    *,
    decision_time: str = "10:10:00",
    next_open: float | None = 10.75,
) -> dict[str, object]:
    decision_at = datetime.fromisoformat(f"2026-07-20T{decision_time}")
    bars = [
        _bar(
            datetime(2026, 7, 20, 10, 4) + timedelta(minutes=index),
            10.20 + index * 0.08,
        )
        for index in range(7)
    ]
    bars[-1].update(close_price=10.68, high_price=10.70)
    candidate = _candidate()
    candidate.update(
        decision_at=decision_at.isoformat(),
        signal_time=decision_at.time().isoformat(),
        last_price=10.68,
        change_pct=6.8,
        minute_bars=bars,
        candidate_first_observed_at="2026-07-20T10:05:00",
        transaction_status="flow_ready",
        transaction_feature_at=decision_at.isoformat(),
        transaction_features={
            "tx_trade_count_acceleration_1m_5m": 1.5,
            "tx_max_print_turnover_share_1m": 0.2,
            "tx_large_print_turnover_share_1m": 0.3,
            "tx_large_print_turnover_share_3m": 0.25,
            "tx_direction_01_imbalance_1m": 0.4,
            "tx_direction_01_imbalance_3m": 0.3,
            "tx_price_move_turnover_imbalance_1m": 0.5,
            "tx_price_move_turnover_imbalance_3m": 0.35,
            "tx_path_efficiency_1m": 0.6,
        },
        next_quote_at=(decision_at + timedelta(minutes=1)).isoformat(),
        next_quote_price=next_open,
    )
    previous_candidates = [
        {"vt_symbol": "600001.SSE", "gain_pct": 6.0},
        {"vt_symbol": "600002.SSE", "gain_pct": 4.0},
    ]
    current_candidates = [
        {"vt_symbol": "600001.SSE", "gain_pct": 6.8},
        {"vt_symbol": "600002.SSE", "gain_pct": 4.2},
    ]
    return {
        "decision_at": decision_at.isoformat(),
        "market_gate": {"passed": True},
        "candidates": [candidate],
        "cross_section_snapshots": [
            {
                "captured_at": (decision_at - timedelta(minutes=1)).isoformat(),
                "candidates": previous_candidates,
            },
            {
                "captured_at": decision_at.isoformat(),
                "candidates": current_candidates,
            },
        ],
    }


def _candidate() -> dict[str, object]:
    return {
        "trade_date": "2026-07-20",
        "signal_date": "2026-07-20",
        "vt_symbol": "600001.SSE",
        "name": "主板样本",
        "board_level": 1,
        "board_lane": "first_board",
        "previous_limit_up": False,
        "prior_streak": 0,
        "target_board": 1,
        "state": "near_limit",
        "previous_close": 10.0,
        "limit_price": 11.0,
        "action": "observe",
        "entry_window_passed": True,
        "snapshot_fresh": True,
        "quote_fresh": True,
        "risk_gate_passed": True,
        "signal_kind": "intraday",
        "prior_limit_count_126": 3,
        "prior_touch_count_126": 8,
        "prior_seal_success_rate_126": 0.75,
        "prior_limit_count_5": 0,
        "trade_days_since_prior_limit": 18,
        "pullback_from_prior_limit_pct": -12.0,
        "prior_position_120": 0.28,
        "auction_gap_pct": 3.2,
        "prior_turnover_rate": 9.0,
        "prior_amount_ratio_5d": 1.6,
        "prior_amplitude_pct": 7.0,
        "prior_low_change_pct": -2.0,
        "prior_industry_heat_score": 72.0,
        "prior_industry_heat_rank": 2,
        "prior_industry_count": 30,
        "prior_industry_leader_rank": 1,
        "prior_market_phase": "repair",
        "prior_market_failed_rate": 0.40,
        "prior_market_one_to_two_rate": 0.30,
        "prior_market_two_to_three_rate": 0.25,
        "financial_risk": {"level": "clear", "blocked": False, "reasons": []},
        "financial_snapshot": {
            "publish_date": "2026-06-30",
            "period_type": "quarterly",
            "net_profit_yoy": 18.0,
        },
        "path_prefix": {
            "point_count": 15,
            "last_pct": 6.8,
            "touch_count": 0,
            "break_count": 0,
            "reseal_count": 0,
            "minimum_pct": 0.0,
            "approach_3point_pct": 3.0,
            "recent_15m_min_pct": 3.0,
            "recent_15m_change_pct": 3.8,
            "recent_15m_range_pct": 3.8,
            "recent_15m_drawdown_pct": 0.0,
            "recent_30m_min_pct": 1.8,
            "recent_30m_change_pct": 5.0,
        },
        "execution_checks": [
            {"code": "stock_momentum", "status": "pending", "blocking": True},
            {"code": "sector_route", "status": "passed", "blocking": True},
            {"code": "stock_flow", "status": "passed", "blocking": True},
            {"code": "turnover_rate", "status": "passed", "blocking": True},
        ],
        "historical_evidence": {
            "as_of_date": "2026-07-20",
            "average_return_pct": 2.2,
            "smoothed_win_rate": 70.0,
            "effective_sample_count": 80,
            "stock_gene_touch_count": 8,
            "stock_gene_seal_count": 6,
            "seal_success_rate": 75.0,
            "d1_money_effect_sample_count": 7,
            "d1_money_effect_win_rate": 71.4286,
            "d1_money_effect_average_return_pct": 2.1,
            "historical_win_rate": 53.5714,
        },
    }


def _bar(
    bar_time: datetime,
    close: float,
    *,
    high: float | None = None,
) -> dict[str, object]:
    return {
        "bar_time": bar_time,
        "open_price": close - 0.02,
        "high_price": high if high is not None else close + 0.02,
        "low_price": close - 0.04,
        "close_price": close,
        "volume": 1_000_000.0 + bar_time.minute * 10_000,
        "turnover": 10_000_000.0 + bar_time.minute * 100_000,
    }


def _thresholds() -> PreboardPolicyThresholds:
    return PreboardPolicyThresholds(
        minimum_touch_probability_3m=0.60,
        minimum_eventual_touch_probability=0.70,
        calibrated_dates=(date(2026, 7, 1),),
        fingerprint="sha256:thresholds",
    )


def _scored_row(
    trade_date: date,
    symbol: str,
    *,
    probability: float,
    net_return: float,
) -> dict[str, object]:
    return {
        **_candidate(),
        "trade_date": trade_date.isoformat(),
        "signal_date": trade_date.isoformat(),
        "decision_at": f"{trade_date.isoformat()}T10:10:00",
        "vt_symbol": symbol,
        "quality_gate_passed": True,
        "preparation_environment_passed": True,
        "execution_environment_passed": True,
        "profitability_gate_passed": True,
        "historical_prior_status": "ready",
        "probability_status": "ready",
        "last_price": 10.7,
        "change_pct": 7.0,
        "touch_probability_3m": probability,
        "eventual_touch_probability": probability,
        "formal_touch_within_3m": probability >= 0.6,
        "eventual_formal_touch": probability >= 0.6,
        "d1_net_return_pct": net_return,
        "fillable": True,
        "entry_price": 10.75,
        "next_quote_price": 10.75,
        "next_quote_at": f"{trade_date.isoformat()}T10:11:00",
        "expected_d1_net_return_pct": 2.2,
        "d1_win_probability": 0.70,
        "seal_probability_given_touch": 0.75,
        "d1_win_probability_given_seal": 0.71,
        "lane_support_score": 65.0,
    }
