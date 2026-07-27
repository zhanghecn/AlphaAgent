from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from alphaagent.server.db import schema
from alphaagent.server.main import create_app
from alphaagent.server.services.limit_up import history_engine
from alphaagent.server.services.limit_up import factor_audit
from alphaagent.server.services.limit_up import history_repository
from alphaagent.server.services.limit_up import history_service
from alphaagent.server.services.limit_up import versions


def test_history_replay_schema_uses_date_and_version_primary_key() -> None:
    table = schema.limit_up_history_replays

    assert [column.name for column in table.primary_key.columns] == [
        "trade_date",
        "strategy_version",
    ]
    assert {"payload", "coverage", "source_mode"}.issubset(table.c.keys())


def test_v2_formal_filter_reuses_the_frozen_v1_history_dataset() -> None:
    assert history_engine.HISTORY_STRATEGY_VERSION == "limit-up-core-abc-v1"
    assert versions.LIVE_STRATEGY_VERSION == "limit-up-core-abc-v2"


def test_compact_trade_keeps_public_quality_estimates_for_audit() -> None:
    compact = history_service._compact_account_trade(
        {
            "vt_symbol": "600001.SSE",
            "quality_priority_tier": "A_industry_expanding",
            "public_quality_contract_version": "limit-up-core-abc-v2",
            "public_quality_status": "actionable",
            "public_quality_actionable": True,
            "quality_win_probability": 0.75,
            "quality_expected_d1_net_return_pct": 2.5,
            "stock_d1_sample_count": 8,
        }
    )

    assert compact == {
        "vt_symbol": "600001.SSE",
        "quality_priority_tier": "A_industry_expanding",
        "public_quality_contract_version": "limit-up-core-abc-v2",
        "public_quality_status": "actionable",
        "public_quality_actionable": True,
        "quality_win_probability": 0.75,
        "quality_expected_d1_net_return_pct": 2.5,
        "stock_d1_sample_count": 8,
    }


def test_scheduled_backtest_cache_key_changes_after_external_ledger_rebuild(
    monkeypatch,
) -> None:
    revisions = iter(
        [
            datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 24, 10, 5, tzinfo=timezone.utc),
        ]
    )
    keys: list[str] = []

    class RecordingCache:
        def get_or_set(self, key, _ttl, _loader):
            keys.append(key)
            return {"orders": [], "trades": [], "skipped_orders": []}

    monkeypatch.setattr(
        history_service.history_repository,
        "history_ledger_updated_at",
        lambda _version: next(revisions),
    )
    monkeypatch.setattr(history_service, "_BACKTEST_REPORT_CACHE", RecordingCache())

    history_service.get_scheduled_history_backtest(None, None, trade_limit=None)
    history_service.get_scheduled_history_backtest(None, None, trade_limit=None)

    assert keys[0] != keys[1]
    assert "2026-07-24T10:00:00+00:00" in keys[0]
    assert "2026-07-24T10:05:00+00:00" in keys[1]


def test_reliable_date_window_rejects_sparse_prefix() -> None:
    counts = [
        (date(2024, 1, 11), 2999),
        (date(2024, 1, 12), 3050),
        (date(2024, 1, 15), 5307),
        (date(2024, 1, 16), 5310),
    ]

    result = history_repository.reliable_date_window(counts, min_symbols=3000)

    assert result == [date(2024, 1, 12), date(2024, 1, 15), date(2024, 1, 16)]


def test_reliable_date_window_requires_usable_dates() -> None:
    with pytest.raises(ValueError, match="reliable daily history"):
        history_repository.reliable_date_window(
            [(date(2024, 1, 11), 100)],
            min_symbols=3000,
        )


def test_bounded_history_window_keeps_requested_lookback_and_end_date() -> None:
    all_dates = [date(2026, 1, day) for day in range(1, 8)]
    reliable_dates = all_dates[1:]

    load_start, load_end = history_repository.bounded_history_load_window(
        all_dates,
        reliable_dates,
        evaluation_start=date(2026, 1, 6),
        evaluation_end=date(2026, 1, 7),
        lookback_sessions=3,
    )

    assert load_start == date(2026, 1, 3)
    assert load_end == date(2026, 1, 7)


def test_bounded_history_window_rejects_reversed_evaluation_range() -> None:
    dates = [date(2026, 1, day) for day in range(1, 4)]

    with pytest.raises(ValueError, match="range is reversed"):
        history_repository.bounded_history_load_window(
            dates,
            dates,
            evaluation_start=date(2026, 1, 3),
            evaluation_end=date(2026, 1, 2),
            lookback_sessions=1,
        )


def test_history_refresh_skips_when_persisted_ledger_is_current(monkeypatch) -> None:
    rebuilt: list[bool] = []
    monkeypatch.setattr(
        history_service.history_repository,
        "history_coverage",
        lambda _version: {"persisted_end": "2026-07-10", "persisted_days": 600},
    )
    monkeypatch.setattr(
        history_service,
        "rebuild_history_sync",
        lambda: rebuilt.append(True),
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "history_inputs_newer_than_ledger",
        lambda _version: False,
        raising=False,
    )

    result = history_service.refresh_history_if_needed(date(2026, 7, 10))

    assert result["status"] == "skipped"
    assert result["persisted_end"] == "2026-07-10"
    assert rebuilt == []


def test_history_refresh_rebuilds_when_persisted_inputs_are_newer(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        history_service.history_repository,
        "history_coverage",
        lambda _version: {"persisted_end": "2026-07-10", "persisted_days": 600},
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "history_inputs_newer_than_ledger",
        lambda _version: True,
        raising=False,
    )
    monkeypatch.setattr(
        history_service,
        "rebuild_history_sync",
        lambda: {
            "status": "ready",
            "persisted_days": 600,
            "start": "2024-01-15",
            "end": "2026-07-10",
        },
    )

    result = history_service.refresh_history_if_needed(date(2026, 7, 10))

    assert result["status"] == "ready"
    assert result["forced"] is True
    assert result["previous_persisted_end"] == "2026-07-10"


def test_history_refresh_rebuilds_when_complete_daily_bar_advances(monkeypatch) -> None:
    monkeypatch.setattr(
        history_service.history_repository,
        "history_coverage",
        lambda _version: {"persisted_end": "2026-07-09", "persisted_days": 599},
    )
    monkeypatch.setattr(
        history_service,
        "rebuild_history_sync",
        lambda: {
            "status": "ready",
            "persisted_days": 600,
            "start": "2024-01-15",
            "end": "2026-07-10",
        },
    )

    result = history_service.refresh_history_if_needed(date(2026, 7, 10))

    assert result["status"] == "ready"
    assert result["previous_persisted_end"] == "2026-07-09"
    assert result["latest_reliable_date"] == "2026-07-10"


def test_history_refresh_force_rebuilds_current_ledger(monkeypatch) -> None:
    monkeypatch.setattr(
        history_service.history_repository,
        "history_coverage",
        lambda _version: {"persisted_end": "2026-07-10", "persisted_days": 600},
    )
    monkeypatch.setattr(
        history_service,
        "rebuild_history_sync",
        lambda: {
            "status": "ready",
            "persisted_days": 600,
            "start": "2024-01-15",
            "end": "2026-07-10",
        },
    )

    result = history_service.refresh_history_if_needed(
        date(2026, 7, 10),
        force=True,
    )

    assert result["status"] == "ready"
    assert result["previous_persisted_end"] == "2026-07-10"
    assert result["latest_reliable_date"] == "2026-07-10"


def test_history_rebuild_does_not_eagerly_warm_full_backtests(monkeypatch) -> None:
    source = pd.DataFrame({"trade_date": [pd.Timestamp("2026-07-20")]})
    released: list[bool] = []
    monkeypatch.setattr(
        history_service.history_repository,
        "load_reliable_history_frame",
        lambda: (
            source,
            {
                "reliable_start": "2026-07-20",
                "reliable_end": "2026-07-20",
            },
        ),
    )
    monkeypatch.setattr(
        history_service.lane_repository,
        "load_lane_research_data",
        lambda *_args: ({}, {}, {}),
    )
    monkeypatch.setattr(
        history_service.history_engine,
        "build_daily_feature_frame",
        lambda frame, **_kwargs: frame,
    )
    monkeypatch.setattr(
        history_service.history_engine,
        "build_history_replays",
        lambda *_args, **_kwargs: [
            {
                "trade_date": "2026-07-20",
                "source_mode": "daily_point_in_time",
            }
        ],
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "replace_history_replays",
        lambda *_args: 1,
    )
    monkeypatch.setattr(
        history_service,
        "start_backtest_cache_warmup",
        lambda: pytest.fail("full backtests must remain on demand after rebuild"),
    )
    monkeypatch.setattr(
        history_service,
        "_release_rebuild_memory",
        lambda: released.append(True),
    )

    result = history_service.rebuild_history_sync()

    assert result["status"] == "ready"
    assert result["persisted_days"] == 1
    assert released == [True]


def test_history_storage_omits_reconstructable_board_aliases() -> None:
    displayed = {"first_board": [{"vt_symbol": "600001.SSE", "lane_rank": 1}]}
    candidate_pool = {
        "first_board": [{"vt_symbol": "600001.SSE", "pool_rank": 1}]
    }
    replay = {
        "trade_date": "2026-07-20",
        "board_lanes": displayed,
        "board_candidate_pool": candidate_pool,
        "lane_portfolio": {
            "lanes": displayed,
            "candidate_pool": candidate_pool,
            "selected": displayed["first_board"],
        },
    }

    stored = history_repository._history_payload_for_storage(replay)
    restored = history_repository._expand_history_payload(stored)

    assert "board_lanes" not in stored
    assert "board_candidate_pool" not in stored
    assert restored["board_lanes"] == displayed
    assert restored["board_candidate_pool"] == candidate_pool
    assert replay["board_lanes"] == displayed


def test_history_storage_builds_bounded_batches_lazily(monkeypatch) -> None:
    converted: list[str] = []

    def convert(row):
        converted.append(str(row["trade_date"]))
        return {"trade_date": row["trade_date"]}

    monkeypatch.setattr(history_repository, "_history_replay_value", convert)
    rows = [{"trade_date": f"2026-07-{day:02d}"} for day in range(1, 26)]
    batches = history_repository._history_replay_value_batches(rows)

    first = next(batches)

    assert len(first) == history_repository.HISTORY_REPLAY_WRITE_BATCH_SIZE
    assert len(converted) == history_repository.HISTORY_REPLAY_WRITE_BATCH_SIZE
    assert sum(len(batch) for batch in batches) + len(first) == len(rows)


def test_history_industries_use_daily_snapshot_before_current_membership(monkeypatch) -> None:
    frame = pd.DataFrame(
        [
            {"trade_date": "2024-01-02", "vt_symbol": "600001.SSE", "industry": "日线行业"},
            {"trade_date": "2024-01-03", "vt_symbol": "600001.SSE", "industry": "日线行业"},
            {"trade_date": "2024-01-04", "vt_symbol": "600001.SSE", "industry": "日线行业"},
        ]
    )
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])

    def fake_read_sql(statement, _engine, **_kwargs):
        sql = str(statement)
        if "stock_sector_membership_snapshots" in sql:
            return pd.DataFrame(
                [
                    {
                        "snapshot_date": "2024-01-02",
                        "vt_symbol": "600001.SSE",
                        "industry_id": "OLD.SI",
                        "industry_name": "旧行业",
                        "rank": 2,
                    },
                    {
                        "snapshot_date": "2024-01-03",
                        "vt_symbol": "600001.SSE",
                        "industry_id": "NEW.SI",
                        "industry_name": "新行业",
                        "rank": 2,
                    },
                ]
            )
        return pd.DataFrame(
            [
                {
                    "vt_symbol": "600001.SSE",
                    "industry_id": "FUTURE.SI",
                    "industry_name": "未来当前行业",
                    "stock_count": 300,
                }
            ]
        )

    monkeypatch.setattr(history_repository.pd, "read_sql", fake_read_sql)
    monkeypatch.setattr(history_repository, "get_engine", lambda: object())

    result, coverage = history_repository._attach_primary_industries(frame)

    by_date = result.set_index(result["trade_date"].dt.date)
    assert by_date.loc[date(2024, 1, 2), "industry_id"] == "OLD.SI"
    assert by_date.loc[date(2024, 1, 3), "industry_id"] == "NEW.SI"
    assert by_date.loc[date(2024, 1, 4), "industry_id"] == "FUTURE.SI"
    assert coverage["industry_membership_mode"] == "mixed_point_in_time_and_current_proxy"
    assert coverage["industry_membership_point_in_time_rows"] == 2
    assert coverage["industry_membership_current_proxy_rows"] == 1
    assert coverage["industry_membership_survivorship_risk"] is True


def test_route_candidates_separate_first_board_from_next_day_two_board() -> None:
    rows = _route_rows()
    frame = history_engine.build_daily_feature_frame(rows)

    lanes = history_engine.route_candidates_for_date(frame, date(2024, 1, 4))

    auction = {row["vt_symbol"]: row for row in lanes["auction"]}
    next_auction = {row["vt_symbol"]: row for row in lanes["next_auction"]}
    assert auction["600001.SSE"]["target_board"] == 1
    assert "600002.SSE" not in auction
    assert next_auction["600002.SSE"]["target_board"] == 2
    assert "600001.SSE" not in next_auction


def test_route_entry_dates_and_prices_are_not_shared() -> None:
    frame = history_engine.build_daily_feature_frame(_route_rows())
    lanes = history_engine.route_candidates_for_date(frame, date(2024, 1, 4))

    auction = lanes["auction"][0]
    next_auction = lanes["next_auction"][0]
    assert auction["signal_date"] == "2024-01-04"
    assert auction["plan_date"] == "2024-01-04"
    assert auction["entry_date"] == "2024-01-04"
    assert auction["entry_price"] == 10.3
    assert next_auction["signal_date"] == "2024-01-04"
    assert next_auction["plan_date"] == "2024-01-03"
    assert next_auction["entry_date"] == "2024-01-04"
    assert next_auction["entry_price"] == 11.33


def test_pretrade_payload_excludes_same_day_close_and_future_outcome() -> None:
    frame = history_engine.build_daily_feature_frame(_route_rows())
    lanes = history_engine.route_candidates_for_date(frame, date(2024, 1, 4))

    known = lanes["auction"][0]["known_at_signal"]

    assert known["data_cutoff"] == "D_OPEN_AND_D_MINUS_1_CLOSE"
    assert "close_price" not in known
    assert "sealed" not in known
    assert "next_open_return_pct" not in known
    assert known["auction_gap_pct"] == pytest.approx(3.0)


def test_same_day_close_does_not_change_auction_candidate_universe() -> None:
    frame = history_engine.build_daily_feature_frame(_route_rows())
    baseline = history_engine.route_candidates_for_date(frame, date(2024, 1, 4))
    mutated = frame.copy()
    mutated.loc[
        mutated["trade_date"].eq(pd.Timestamp("2024-01-04")),
        "change_pct",
    ] = 80.0

    changed = history_engine.route_candidates_for_date(mutated, date(2024, 1, 4))

    assert [row["vt_symbol"] for row in changed["auction"]] == [
        row["vt_symbol"] for row in baseline["auction"]
    ]
    assert [row["vt_symbol"] for row in changed["next_auction"]] == [
        row["vt_symbol"] for row in baseline["next_auction"]
    ]


def test_history_replay_uses_only_matured_prior_samples() -> None:
    rows = _chronological_rows()
    target = "2024-01-12"
    full = history_engine.build_history_replays(
        rows,
        warmup_days=2,
        holdout_days=2,
        min_analogs=1,
    )
    truncated = history_engine.build_history_replays(
        [row for row in rows if str(row["trade_date"]) <= "2024-01-15"],
        warmup_days=2,
        holdout_days=0,
        min_analogs=1,
    )

    full_day = next(row for row in full if row["trade_date"] == target)
    truncated_day = next(row for row in truncated if row["trade_date"] == target)

    assert full_day["lanes"] == truncated_day["lanes"]


def test_mutating_future_outcome_does_not_change_earlier_top5() -> None:
    rows = _chronological_rows()
    baseline = history_engine.build_history_replays(
        rows,
        warmup_days=2,
        holdout_days=2,
        min_analogs=1,
    )
    mutated = [dict(row) for row in rows]
    for row in mutated:
        if str(row["trade_date"]) >= "2024-01-17":
            row["open_price"] = float(row["open_price"]) * 0.8
            row["close_price"] = float(row["close_price"]) * 0.8
            row["high_price"] = float(row["high_price"]) * 0.8
            row["low_price"] = float(row["low_price"]) * 0.8
    changed = history_engine.build_history_replays(
        mutated,
        warmup_days=2,
        holdout_days=2,
        min_analogs=1,
    )

    baseline_day = next(row for row in baseline if row["trade_date"] == "2024-01-12")
    changed_day = next(row for row in changed if row["trade_date"] == "2024-01-12")

    assert baseline_day["lanes"] == changed_day["lanes"]


def test_history_replay_marks_warmup_expanding_and_locked_holdout() -> None:
    result = history_engine.build_history_replays(
        _chronological_rows(),
        warmup_days=2,
        holdout_days=2,
        min_analogs=1,
    )

    assert [row["validation_phase"] for row in result[:2]] == ["warmup", "warmup"]
    assert result[2]["validation_phase"] == "expanding_oos"
    assert [row["validation_phase"] for row in result[-2:]] == [
        "locked_holdout",
        "locked_holdout",
    ]
    assert all(len(row["lanes"]["auction"]) <= 5 for row in result)


def test_locked_holdout_does_not_learn_from_holdout_outcomes() -> None:
    frame = history_engine.build_daily_feature_frame(_chronological_rows())
    dates = sorted(frame["trade_date"].dropna().unique())
    first_holdout = dates[-4]
    baseline = history_engine.build_history_replays(
        frame,
        warmup_days=2,
        holdout_days=4,
        min_analogs=1,
    )
    mutated = frame.copy()
    holdout_rows = mutated["trade_date"].eq(first_holdout)
    mutated.loc[holdout_rows, "next_open_price"] = (
        mutated.loc[holdout_rows, "next_open_price"] * 0.25
    )
    mutated.loc[holdout_rows, "next_close_price"] = (
        mutated.loc[holdout_rows, "next_close_price"] * 0.25
    )

    changed = history_engine.build_history_replays(
        mutated,
        warmup_days=2,
        holdout_days=4,
        min_analogs=1,
    )

    assert baseline[-1]["lanes"] == changed[-1]["lanes"]


def test_execution_gate_requires_broad_market_and_blocks_three_board_auction() -> None:
    analog = {
        "effective_sample_count": 240,
        "average_return_pct": 2.0,
        "smoothed_win_rate": 62.0,
        "hard_loss_rate": 8.0,
        "seal_after_touch_rate": 65.0,
    }
    sweep = {
        "entry_mode": "sweep",
        "target_board": 1,
        "analog": analog,
        "known_at_signal": {
            "prior_market_phase": "broad_rise",
            "prior_market_failed_rate": 0.3,
        },
    }

    assert history_engine._history_action(sweep, "expanding_oos", min_analogs=60) == "wait_sweep"
    assert history_engine._history_action(
        {
            **sweep,
            "known_at_signal": {**sweep["known_at_signal"], "prior_market_phase": "retreat"},
        },
        "expanding_oos",
        min_analogs=60,
    ) == "pass"
    assert history_engine._history_action(
        {
            **sweep,
            "entry_mode": "next_auction",
            "target_board": 3,
            "known_at_signal": {
                **sweep["known_at_signal"],
                "auction_gap_pct": 4.5,
                "prior_amount_ratio_5d": 2.0,
                "prior_market_one_to_two_rate": 0.25,
            },
        },
        "expanding_oos",
        min_analogs=60,
    ) == "pass"


def test_history_backtest_uses_only_executable_top5_and_separates_phases(monkeypatch) -> None:
    rows = [
        _persisted_replay_day("2024-01-10", "warmup", 3.0, "auction_buy"),
        _persisted_replay_day("2024-01-11", "expanding_oos", 2.0, "auction_buy"),
        _persisted_replay_day("2024-01-12", "locked_holdout", -1.0, "watch_first_board"),
        _persisted_replay_day("2024-01-15", "locked_holdout", -6.0, "auction_buy"),
    ]
    monkeypatch.setattr(history_service.history_repository, "load_history_range", lambda *_args: rows)

    report = history_service.get_history_backtest(
        start=date(2024, 1, 10),
        end=date(2024, 1, 15),
        entry_mode="auction",
        exit_mode="next_open",
    )

    assert report["summary"]["signal_count"] == 4
    assert report["summary"]["filled_count"] == 3
    assert report["summary"]["win_rate"] == pytest.approx(66.6667)
    assert report["phase_summaries"]["expanding_oos"]["filled_count"] == 1
    assert report["phase_summaries"]["locked_holdout"]["filled_count"] == 1
    assert report["phase_summaries"]["locked_holdout"]["average_return_pct"] == -6.0


def test_history_backtest_sweep_requires_touch_proxy(monkeypatch) -> None:
    row = _persisted_replay_day("2024-01-11", "expanding_oos", 2.0, "wait_sweep")
    candidate = row["lanes"]["auction"][0]
    row["lanes"]["sweep"] = [
        {
            **candidate,
            "entry_mode": "sweep",
            "action": "wait_sweep",
            "execution_confidence": "daily_touch_proxy_without_queue",
            "outcome": {**candidate["outcome"], "touched": False},
        }
    ]
    monkeypatch.setattr(history_service.history_repository, "load_history_range", lambda *_args: [row])

    report = history_service.get_history_backtest(
        start=None,
        end=None,
        entry_mode="sweep",
        exit_mode="next_open",
    )

    assert report["summary"]["signal_count"] == 1
    assert report["summary"]["filled_count"] == 0


def test_history_backtest_tail_keeps_unverifiable_fill_out_of_main_result(monkeypatch) -> None:
    row = _persisted_replay_day("2024-01-11", "expanding_oos", 2.0, "wait_tail")
    candidate = row["lanes"]["auction"][0]
    row["lanes"]["tail"] = [
        {
            **candidate,
            "entry_mode": "tail",
            "action": "wait_tail",
            "execution_confidence": "daily_close_proxy_unverifiable",
        }
    ]
    monkeypatch.setattr(history_service.history_repository, "load_history_range", lambda *_args: [row])

    report = history_service.get_history_backtest(
        start=None,
        end=None,
        entry_mode="tail",
        exit_mode="next_open",
    )

    assert report["summary"]["filled_count"] == 0
    assert report["observational_proxy"]["summary"]["filled_count"] == 1
    assert report["observational_proxy"]["summary"]["average_return_pct"] == 2.0


def test_factor_audit_ranks_from_expanding_oos_and_only_validates_on_holdout() -> None:
    baseline = factor_audit.build_history_factor_audit(
        _factor_audit_rows(reverse_holdout_heat=False),
        entry_mode="auction",
        exit_mode="next_open",
    )
    reversed_holdout = factor_audit.build_history_factor_audit(
        _factor_audit_rows(reverse_holdout_heat=True),
        entry_mode="auction",
        exit_mode="next_open",
    )

    baseline_codes = [row["code"] for row in baseline["factors"]]
    reversed_codes = [row["code"] for row in reversed_holdout["factors"]]
    assert baseline_codes == reversed_codes
    assert baseline_codes[0] == "prior_industry_heat_score"
    baseline_heat = baseline["factors"][0]
    reversed_heat = reversed_holdout["factors"][0]
    assert baseline_heat["expanding_oos"] == reversed_heat["expanding_oos"]
    assert baseline_heat["validation_status"] == "confirmed"
    assert reversed_heat["validation_status"] == "reversed"
    assert baseline["selection_basis"] == "expanding_oos_only"


def test_factor_audit_classifies_d1_paths_and_keeps_candidate_scope_explicit() -> None:
    report = factor_audit.build_history_factor_audit(
        _factor_audit_rows(reverse_holdout_heat=False),
        entry_mode="auction",
        exit_mode="next_open",
    )

    holdout_buckets = {
        row["code"]: row for row in report["outcome_buckets"]["locked_holdout"]
    }
    assert holdout_buckets["continuation_limit_up"]["count"] == 10
    assert holdout_buckets["direct_breakdown"]["count"] == 10
    assert report["phase_summaries"]["locked_holdout"]["sample_count"] == 20
    assert report["sample_scope"] == "top5_candidate_outcomes_not_fills"
    assert len(report["examples"]["winners"]) == 5
    assert len(report["examples"]["breakdowns"]) == 5


def test_history_factor_api_passes_range_route_and_exit(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    captured: dict[str, object] = {}

    def fake_factor_audit(start, end, entry_mode, exit_mode):
        captured.update(start=start, end=end, entry_mode=entry_mode, exit_mode=exit_mode)
        return {"status": "ready", "factors": [], "outcome_buckets": {}}

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        limit_up,
        "get_limit_up_history_factor_audit",
        fake_factor_audit,
    )

    response = TestClient(create_app()).get(
        "/api/limit-up/history/factors",
        params={
            "start": "2024-01-15",
            "end": "2026-07-10",
            "entry_mode": "next_auction",
            "exit_mode": "next_close",
        },
    )

    assert response.status_code == 200
    assert str(captured["start"]) == "2024-01-15"
    assert str(captured["end"]) == "2026-07-10"
    assert captured["entry_mode"] == "next_auction"
    assert captured["exit_mode"] == "next_close"


def test_history_day_api_returns_selected_replay(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        limit_up,
        "get_limit_up_history_day",
        lambda trade_date: {"status": "ready", "trade_date": trade_date.isoformat(), "lanes": {}},
    )

    response = TestClient(create_app()).get(
        "/api/limit-up/history/day",
        params={"date": "2024-01-15"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["trade_date"] == "2024-01-15"


def test_history_day_api_returns_404_outside_reliable_window(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        limit_up,
        "get_limit_up_history_day",
        lambda trade_date: {"status": "not_found", "trade_date": trade_date.isoformat()},
    )

    response = TestClient(create_app()).get(
        "/api/limit-up/history/day",
        params={"date": "2020-01-02"},
    )

    assert response.status_code == 404


def test_legacy_entry_backtest_api_uses_full_history_service(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    captured: dict[str, object] = {}

    def fake_history_backtest(start, end, entry_mode, exit_mode):
        captured.update(start=start, end=end, entry_mode=entry_mode, exit_mode=exit_mode)
        return {"status": "ready", "mode": "point_in_time_history_replay", "trades": []}

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(limit_up, "get_limit_up_history_backtest", fake_history_backtest)

    response = TestClient(create_app()).get(
        "/api/limit-up/backtest",
        params={"entry_mode": "next_auction", "exit_mode": "next_open"},
    )

    assert response.status_code == 200
    assert captured["entry_mode"] == "next_auction"


def test_history_backtest_api_defaults_to_formal_portfolio_scope(
    monkeypatch,
) -> None:
    from alphaagent.server.api import limit_up

    captured: dict[str, object] = {}

    def fake_lane_backtest(start, end, lane, exit_mode):
        captured.update(start=start, end=end, lane=lane, exit_mode=exit_mode)
        return {"status": "ready", "mode": "scheduled_unified_intraday_cash_replay"}

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        limit_up,
        "get_limit_up_lane_history_backtest",
        fake_lane_backtest,
    )

    response = TestClient(create_app()).get("/api/limit-up/history/backtest")

    assert response.status_code == 200
    assert captured["lane"] == "portfolio"
    assert captured["exit_mode"] == "next_close"


def _persisted_replay_day(
    trade_date: str,
    phase: str,
    return_pct: float,
    action: str,
) -> dict[str, object]:
    candidate = {
        "vt_symbol": "600001.SSE",
        "name": "历史候选",
        "entry_mode": "auction",
        "action": action,
        "signal_date": trade_date,
        "plan_date": trade_date,
        "entry_date": trade_date,
        "result_date": trade_date,
        "target_board": 1,
        "entry_price": 10.0,
        "rank": 1,
        "validation_phase": phase,
        "execution_confidence": "daily_open_proxy",
        "analog": {
            "sample_count": 200,
            "effective_sample_count": 150,
            "smoothed_win_rate": 55.0,
            "average_return_pct": 1.0,
            "hard_loss_rate": 10.0,
            "confidence": "medium",
        },
        "outcome": {
            "touched": True,
            "sealed": True,
            "next_open_return_pct": return_pct,
            "next_close_return_pct": return_pct + 0.5,
            "next_open_price": 10.5,
            "next_close_price": 10.55,
        },
    }
    return {
        "trade_date": trade_date,
        "strategy_version": history_engine.HISTORY_STRATEGY_VERSION,
        "validation_phase": phase,
        "lanes": {"auction": [candidate], "sweep": [], "tail": [], "next_auction": []},
        "coverage": {"reliable_trade_days": 600},
    }


def _factor_audit_rows(*, reverse_holdout_heat: bool) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    phases = (("expanding_oos", 40), ("locked_holdout", 10))
    day_index = 0
    for phase, side_count in phases:
        for is_win in (True, False):
            for item_index in range(side_count):
                day_index += 1
                winner_heat = 90.0 + item_index / 100
                loser_heat = 20.0 + item_index / 100
                if phase == "locked_holdout" and reverse_holdout_heat:
                    winner_heat, loser_heat = loser_heat, winner_heat
                heat = winner_heat if is_win else loser_heat
                return_pct = 3.0 if is_win else -6.0
                close_price = 12.1 if is_win else 10.2
                candidate = {
                    "vt_symbol": f"600{day_index:03d}.SSE",
                    "name": f"样本{day_index}",
                    "industry_name": "机器人",
                    "entry_mode": "auction",
                    "action": "auction_buy",
                    "signal_date": f"2025-01-{(day_index % 28) + 1:02d}",
                    "entry_date": f"2025-01-{(day_index % 28) + 1:02d}",
                    "result_date": f"2025-02-{(day_index % 28) + 1:02d}",
                    "target_board": 1,
                    "rank": item_index % 5 + 1,
                    "known_at_signal": {
                        "auction_gap_pct": 3.0 + (item_index % 3) * 0.1,
                        "prior_turnover_rate": 8.0 + (1 if is_win else 0),
                        "prior_amount_ratio_5d": 1.2 + (item_index % 4) * 0.05,
                        "prior_industry_heat_score": heat,
                        "prior_market_failed_rate": 0.2 if is_win else 0.4,
                        "prior_market_phase": "repair" if is_win else "retreat",
                    },
                    "outcome": {
                        "touched": is_win,
                        "sealed": is_win,
                        "entry_day_close_price": 11.0,
                        "next_open_price": 11.4 if is_win else 10.3,
                        "next_close_price": close_price,
                        "next_open_return_pct": return_pct,
                        "next_close_return_pct": 9.5 if is_win else -7.0,
                    },
                }
                rows.append(
                    {
                        "trade_date": candidate["signal_date"],
                        "validation_phase": phase,
                        "lanes": {
                            "auction": [candidate],
                            "sweep": [],
                            "tail": [],
                            "next_auction": [],
                        },
                        "coverage": {"reliable_trade_days": 600},
                    }
                )
    return rows


def _route_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    series = {
        "600001.SSE": [
            ("2024-01-02", 9.8, 10.0, 10.1, 9.7, 0.0),
            ("2024-01-03", 10.0, 10.0, 10.2, 9.9, 0.0),
            ("2024-01-04", 10.3, 11.0, 11.0, 10.2, 10.0),
            ("2024-01-05", 11.2, 11.1, 11.4, 10.9, 0.9),
        ],
        "600002.SSE": [
            ("2024-01-02", 9.8, 10.0, 10.1, 9.7, 0.0),
            ("2024-01-03", 10.0, 11.0, 11.0, 9.9, 10.0),
            ("2024-01-04", 11.33, 12.1, 12.1, 11.2, 10.0),
            ("2024-01-05", 12.2, 12.0, 12.4, 11.8, -0.8),
        ],
    }
    for symbol, bars in series.items():
        for trade_date, open_price, close_price, high_price, low_price, change_pct in bars:
            rows.append(
                {
                    "vt_symbol": symbol,
                    "symbol": symbol.split(".", 1)[0],
                    "name": symbol,
                    "industry": "测试",
                    "exchange": "SSE",
                    "trade_date": trade_date,
                    "open_price": open_price,
                    "close_price": close_price,
                    "high_price": high_price,
                    "low_price": low_price,
                    "volume": 1_000_000,
                    "turnover": 100_000_000,
                    "turnover_rate": 8.0,
                    "change_pct": change_pct,
                }
            )
    return rows


def _chronological_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    dates = [timestamp.date().isoformat() for timestamp in pd.bdate_range("2024-01-02", periods=14)]
    for symbol_index, symbol in enumerate(("600011.SSE", "600012.SSE", "600013.SSE")):
        previous_close = 10.0 + symbol_index
        for index, trade_date in enumerate(dates):
            gap = 0.03 + symbol_index * 0.005
            open_price = round(previous_close * (1 + gap), 2)
            sealed = index % 4 == symbol_index
            close_price = round(previous_close * (1.1 if sealed else 1.02 + symbol_index * 0.005), 2)
            high_price = round(previous_close * (1.1 if sealed or index % 3 == 0 else 1.05), 2)
            low_price = round(min(open_price, close_price) * 0.98, 2)
            change_pct = round((close_price / previous_close - 1) * 100, 4)
            rows.append(
                {
                    "vt_symbol": symbol,
                    "symbol": symbol.split(".", 1)[0],
                    "name": symbol,
                    "industry": "测试",
                    "exchange": "SSE",
                    "trade_date": trade_date,
                    "open_price": open_price,
                    "close_price": close_price,
                    "high_price": high_price,
                    "low_price": low_price,
                    "volume": 1_000_000 + index * 10_000,
                    "turnover": 100_000_000 + index * 2_000_000,
                    "turnover_rate": 5.0 + symbol_index * 2,
                    "change_pct": change_pct,
                }
            )
            previous_close = close_price
    return rows
