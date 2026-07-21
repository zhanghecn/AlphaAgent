from __future__ import annotations

import pandas as pd

from alphaagent.server.services.low_suction import causal_leader_pullback_study
from alphaagent.server.services.low_suction.causal_leader_pullback import (
    CampaignPreparation,
    EXACT_REQUIRED_SUPPORT,
    MINIMUM_REQUIRED_SUPPORT,
)
from alphaagent.server.services.low_suction.causal_leader_pullback_study import (
    _variant_decision,
)
from alphaagent.server.services.low_suction.causal_leader_pullback_study import (
    CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
    GOLD_STRONG_RECLAIM_VARIANT,
    assign_trade_time_blocks,
    attach_signal_market_timing,
    build_causal_stock_features,
    build_causal_leader_pullback_report,
    build_dynamic_leader_paths,
    build_named_case_audit,
    prepare_dynamic_leader_paths,
    replay_dynamic_leader_paths,
    render_causal_leader_pullback_json,
    render_causal_leader_pullback_markdown,
)
from alphaagent.server.services.low_suction.cli import build_parser


def test_report_keeps_algorithm_metrics_separate_from_formal_metrics() -> None:
    report = build_causal_leader_pullback_report(
        coverage={
            "concepts": 1,
            "current_membership_rows": 4,
            "strict_historical_membership_rows": 0,
        },
        fingerprints={"stock_bars": {"digest": "sha256:test", "rows": 8}},
        campaigns=pd.DataFrame([{"campaign_id": "campaign-1"}]),
        leader_paths=pd.DataFrame(
            [{"campaign_id": "campaign-1", "vt_symbol": "600001.SSE"}]
        ),
        signals=pd.DataFrame(
            [
                {
                    "signal_id": "signal-1",
                    "non_contraction_confirmation": True,
                    "support_line": "ma5",
                    "wave_number": 1,
                    "dynamic_rank": 1,
                }
            ]
        ),
        trades=_trades(),
        leader_spells=pd.DataFrame(),
        waves=pd.DataFrame(),
        case_audit=[],
        cash_results={
            "base_confirmation": _cash_result(),
            "non_contraction_confirmation": _cash_result(),
            GOLD_STRONG_RECLAIM_VARIANT: _cash_result(),
            CROSS_REGIME_SUPPORT_RECLAIM_VARIANT: _cash_result(),
        },
    )

    assert report["study_version"] == "causal-leader-pullback-study-v4"
    assert report["algorithm_version"] == "causal-leader-pullback-close-v2"
    assert report["policy_version"] == "causal-leader-pullback-cross-regime-v3"
    assert report["formal_strategy"] is False
    assert report["formal_metrics"] is None
    assert report["contract"]["entry"] == "D completed close research proxy"
    assert (
        report["data_quality"]["membership_evidence"]
        == "current_membership_survivorship_proxy"
    )
    assert report["data_quality"]["gold_silver_used_for_selection"] is True
    assert len(report["overall_metrics"]) == 4
    assert len(report["time_block_metrics"]) == 20


def test_renderers_expose_rules_metrics_and_data_boundary() -> None:
    report = build_causal_leader_pullback_report(
        coverage={"strict_historical_membership_rows": 0},
        fingerprints={},
        campaigns=pd.DataFrame(),
        leader_paths=pd.DataFrame(),
        signals=pd.DataFrame(),
        trades=pd.DataFrame(),
        leader_spells=pd.DataFrame(),
        waves=pd.DataFrame(),
        case_audit=[],
        cash_results={},
    )

    rendered_json = render_causal_leader_pullback_json(report)
    rendered_markdown = render_causal_leader_pullback_markdown(report)

    assert '"algorithm_version": "causal-leader-pullback-close-v2"' in rendered_json
    assert "第一轮回调" in rendered_markdown
    assert "GOLD/NORMAL" in rendered_markdown
    assert "D+1" in rendered_markdown
    assert "历史代理门" in rendered_markdown
    assert "当前成员幸存者代理" in rendered_markdown


def test_market_timing_attaches_only_same_day_context() -> None:
    signals = pd.DataFrame(
        {
            "signal_id": ["signal-1", "signal-2"],
            "signal_date": pd.to_datetime(["2026-01-05", "2026-01-06"]),
        }
    )
    timing = pd.DataFrame(
        {
            "source_date": pd.to_datetime(["2026-01-05", "2026-01-07"]),
            "active_direction": ["GOLD", "SILVER"],
            "danger_state": ["NORMAL", "DANGER"],
            "market_phase": ["markup", "decline"],
        }
    )

    attached = attach_signal_market_timing(signals, timing)

    assert attached["active_direction"].tolist() == ["GOLD", "UNKNOWN"]
    assert attached["danger_state"].tolist() == ["NORMAL", "UNKNOWN"]
    assert attached["market_timing_evidence"].tolist() == ["available", "missing"]
    assert attached["market_timing_feature_cutoff_date"].equals(attached["signal_date"])


def test_campaign_ledger_keeps_only_right_censored_endpoint_active(
    monkeypatch,
) -> None:
    dates = pd.bdate_range("2026-01-05", periods=5)
    features = pd.DataFrame(
        [
            {
                "sector_id": sector_id,
                "concept_name": concept_name,
                "trade_date": trade_date,
                "close_price": close_price,
                "anchor_breakout_relative_turnover": position == 0,
            }
            for sector_id, concept_name, closes in (
                ("BK_OPEN", "仍在主升", (100.0, 103.0, 105.0, 106.0, 107.0)),
                ("BK_ENDED", "确认退潮", (100.0, 110.0, 104.0, 103.0, 102.0)),
            )
            for position, (trade_date, close_price) in enumerate(
                zip(dates, closes, strict=True)
            )
        ]
    )
    monkeypatch.setattr(
        causal_leader_pullback_study,
        "build_concept_campaign_features",
        lambda _bars: features,
    )

    campaigns, paths = causal_leader_pullback_study.build_concept_campaign_ledger(
        pd.DataFrame({"placeholder": [1]})
    )

    status_by_sector = campaigns.set_index("sector_id")["right_censored"].to_dict()
    endpoint_active = paths.loc[paths["is_endpoint"]].set_index("sector_id")[
        "campaign_active"
    ].to_dict()
    assert status_by_sector == {"BK_ENDED": False, "BK_OPEN": True}
    assert endpoint_active == {"BK_ENDED": False, "BK_OPEN": True}


def test_gold_variant_executes_its_signal_set_independently(monkeypatch) -> None:
    signal_date = pd.Timestamp("2026-01-05")
    signals = pd.DataFrame(
        [
            _signal("base-only", signal_date, daily_return=2.0),
            _signal("gold", signal_date, daily_return=8.0),
        ]
    )
    prepared = CampaignPreparation(
        paths=_replay_paths(signal_date),
        signals=signals,
        daily_ledger=pd.DataFrame(),
    )
    executed_signal_sets: list[list[str]] = []

    monkeypatch.setattr(
        causal_leader_pullback_study,
        "prepare_stock_campaigns",
        lambda _, **_kwargs: prepared,
    )
    monkeypatch.setattr(
        causal_leader_pullback_study,
        "_summarize_replay_waves",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )

    def execute(signals: pd.DataFrame, _: CampaignPreparation) -> pd.DataFrame:
        executed_signal_sets.append(signals["signal_id"].tolist())
        return pd.DataFrame(
            [_trade(signal_id, signal_date) for signal_id in signals["signal_id"]]
        )

    monkeypatch.setattr(
        causal_leader_pullback_study,
        "execute_prepared_close_trades",
        execute,
    )

    result = replay_dynamic_leader_paths(
        _replay_paths(signal_date),
        pd.DataFrame(
            [
                {
                    "source_date": signal_date,
                    "active_direction": "GOLD",
                    "danger_state": "NORMAL",
                    "market_phase": "rotation",
                }
            ]
        ),
    )

    assert executed_signal_sets == [
        ["base-only", "gold"],
        ["base-only", "gold"],
        ["gold"],
        ["gold"],
    ]
    assert result.trades.loc[
        result.trades["variant"].eq(GOLD_STRONG_RECLAIM_VARIANT), "signal_id"
    ].tolist() == ["gold"]
    assert result.trades.loc[
        result.trades["variant"].eq(CROSS_REGIME_SUPPORT_RECLAIM_VARIANT),
        "signal_id",
    ].tolist() == ["gold"]


def test_dynamic_replay_forwards_the_support_match_mode(monkeypatch) -> None:
    captured: list[str] = []
    prepared = CampaignPreparation(
        paths=_replay_paths(pd.Timestamp("2026-01-05")),
        signals=pd.DataFrame(columns=["signal_date"]),
        daily_ledger=pd.DataFrame(),
    )
    empty_timing = pd.DataFrame(
        columns=["source_date", "active_direction", "danger_state", "market_phase"]
    )

    def prepare_campaigns(_: pd.DataFrame, *, support_match_mode: str):
        captured.append(support_match_mode)
        return prepared

    monkeypatch.setattr(
        causal_leader_pullback_study,
        "prepare_stock_campaigns",
        prepare_campaigns,
    )
    monkeypatch.setattr(
        causal_leader_pullback_study,
        "_summarize_replay_waves",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )

    causal_leader_pullback_study.replay_dynamic_leader_paths(
        _replay_paths(pd.Timestamp("2026-01-05")),
        empty_timing,
    )
    causal_leader_pullback_study.replay_dynamic_leader_paths(
        _replay_paths(pd.Timestamp("2026-01-05")),
        empty_timing,
        support_match_mode=EXACT_REQUIRED_SUPPORT,
    )

    assert captured == [MINIMUM_REQUIRED_SUPPORT, EXACT_REQUIRED_SUPPORT]


def test_dynamic_preparation_never_executes_trade_variants(monkeypatch) -> None:
    signal_date = pd.Timestamp("2026-01-05")
    prepared = CampaignPreparation(
        paths=_replay_paths(signal_date),
        signals=pd.DataFrame(columns=["signal_date"]),
        daily_ledger=pd.DataFrame(),
    )
    monkeypatch.setattr(
        causal_leader_pullback_study,
        "prepare_stock_campaigns",
        lambda *_args, **_kwargs: prepared,
    )
    monkeypatch.setattr(
        causal_leader_pullback_study,
        "_summarize_replay_waves",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )

    def fail_if_executed(*_args, **_kwargs):
        raise AssertionError("dynamic preparation must not execute trade variants")

    monkeypatch.setattr(
        causal_leader_pullback_study,
        "execute_prepared_close_trades",
        fail_if_executed,
    )

    result = prepare_dynamic_leader_paths(
        _replay_paths(signal_date),
        pd.DataFrame(
            columns=[
                "source_date",
                "active_direction",
                "danger_state",
                "market_phase",
            ]
        ),
    )

    assert result.campaigns is prepared
    assert not hasattr(result, "trades")


def test_cli_registers_causal_leader_pullback_study() -> None:
    args = build_parser().parse_args(
        ["v2-causal-leader-pullback-study", "--format", "json"]
    )

    assert args.command == "v2-causal-leader-pullback-study"
    assert args.format == "json"

    cross_regime = build_parser().parse_args(
        ["v3-cross-regime-pullback-study", "--format", "json"]
    )
    assert cross_regime.command == "v3-cross-regime-pullback-study"
    assert cross_regime.format == "json"


def test_time_blocks_are_assigned_within_each_variant_observation_window() -> None:
    rows = []
    for variant, start in (
        ("base_confirmation", "2025-01-01"),
        (GOLD_STRONG_RECLAIM_VARIANT, "2026-01-01"),
    ):
        for offset, entry_date in enumerate(pd.date_range(start, periods=5, freq="D")):
            rows.append(
                {
                    "variant": variant,
                    "signal_id": f"{variant}-{offset}",
                    "entry_date": entry_date,
                    "exit_date": entry_date + pd.Timedelta(days=1),
                    "dynamic_rank": 1,
                }
            )

    assigned = assign_trade_time_blocks(pd.DataFrame(rows))

    for _, trades in assigned.groupby("variant", sort=False):
        assert trades.sort_values("entry_date")["time_block"].tolist() == [
            "block_1",
            "block_2",
            "block_3",
            "block_4",
            "block_5",
        ]


def test_named_case_audit_includes_pullback_confirmation_blockers() -> None:
    symbol = "002636.SZSE"
    paths = pd.DataFrame(
        [
            {
                "campaign_id": "campaign-1",
                "vt_symbol": symbol,
                "trade_date": pd.Timestamp("2026-06-30"),
                "dynamic_top3": True,
            }
        ]
    )
    daily = pd.DataFrame(
        [
            {
                "campaign_id": "campaign-1",
                "vt_symbol": symbol,
                "trade_date": pd.Timestamp("2026-06-29"),
                "confirmation_status": "not_dynamic_top3",
            },
            {
                "campaign_id": "campaign-1",
                "vt_symbol": symbol,
                "trade_date": pd.Timestamp("2026-06-30"),
                "confirmation_status": "signal_emitted",
            },
        ]
    )

    cases = build_named_case_audit(
        paths,
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        daily,
    )
    case = next(row for row in cases if row["vt_symbol"] == symbol)

    assert case["confirmation_status_counts"] == {
        "not_dynamic_top3": 1,
        "signal_emitted": 1,
    }
    assert len(case["pullback_confirmation_rows"]) == 2


def test_proxy_gate_requires_two_qualified_market_phases() -> None:
    overall = [
        {
            "variant": CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
            "closed_trades": 120,
            "positive_rate_pct": 61.0,
            "mean_net_return_pct": 1.0,
            "profit_factor": 2.0,
        }
    ]
    blocks = [
        {
            "variant": CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
            "closed_trades": 20,
            "positive_rate_pct": win_rate,
            "mean_net_return_pct": 1.0,
        }
        for win_rate in (61.0, 62.0, 63.0, 60.0, 59.0)
    ]
    phase_metrics = [
        {
            "variant": CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
            "group": phase,
            "closed_trades": 30,
            "positive_rate_pct": win_rate,
            "compound_return_pct": compound_return,
        }
        for phase, win_rate, compound_return in (
            ("rotation", 61.0, 20.0),
            ("warming", 62.0, 30.0),
            ("retreat", 80.0, -1.0),
        )
    ]

    decision = _variant_decision(
        CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
        overall,
        blocks,
        phase_metrics,
        {"compound_return_pct": 61.0, "maximum_drawdown_pct": -9.0},
        strict_membership_rows=0,
    )

    assert decision["stable_time_blocks"] == 3
    assert decision["qualified_market_phases"] == ["rotation", "warming"]
    assert decision["historical_proxy_gate_passed"] is True
    assert decision["failed_gates"] == ["strict_historical_membership_missing"]


def test_proxy_gate_treats_sixty_percent_phase_win_rate_as_failure() -> None:
    overall = [
        {
            "variant": CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
            "closed_trades": 120,
            "positive_rate_pct": 61.0,
            "mean_net_return_pct": 1.0,
            "profit_factor": 2.0,
        }
    ]
    blocks = [
        {
            "variant": CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
            "closed_trades": 20,
            "positive_rate_pct": 61.0,
            "mean_net_return_pct": 1.0,
        }
        for _ in range(5)
    ]
    phases = [
        {
            "variant": CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
            "group": phase,
            "closed_trades": 30,
            "positive_rate_pct": win_rate,
            "compound_return_pct": 10.0,
        }
        for phase, win_rate in (("rotation", 61.0), ("warming", 60.0))
    ]

    decision = _variant_decision(
        CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
        overall,
        blocks,
        phases,
        {"compound_return_pct": 61.0, "maximum_drawdown_pct": -9.0},
        strict_membership_rows=1,
    )

    assert decision["qualified_market_phases"] == ["rotation"]
    assert "qualified_market_phases<2" in decision["failed_gates"]


def test_complete_member_ranking_retains_only_top3_stock_paths() -> None:
    dates = pd.to_datetime(["2026-01-15", "2026-01-16", "2026-01-19"])
    campaign_paths = pd.DataFrame(
        [
            {
                "campaign_id": "campaign-1",
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "anchor_date": dates[0],
                "trade_date": trade_date,
                "campaign_day": day,
                "close_price": 100.0 + day,
                "cumulative_gain_pct": float(day),
                "campaign_active": True,
            }
            for day, trade_date in enumerate(dates)
        ]
    )
    memberships = pd.DataFrame(
        [
            {
                "sector_id": "BK0001",
                "vt_symbol": f"60000{member}.SSE",
                "stock_name": f"成员{member}",
            }
            for member in range(1, 5)
        ]
    )
    stock_features = pd.DataFrame(
        [
            _stock_feature(member, day, trade_date)
            for member in range(1, 5)
            for day, trade_date in enumerate(dates)
        ]
    )

    leader_paths, coverage = build_dynamic_leader_paths(
        campaign_paths, memberships, stock_features
    )

    assert coverage["expanded_member_date_rows"] == 12
    assert coverage["dynamic_top3_rows"] == 9
    assert leader_paths["vt_symbol"].nunique() == 3
    assert len(leader_paths) == 9
    assert (
        leader_paths.loc[
            leader_paths["trade_date"].eq(dates[-1])
            & leader_paths["dynamic_rank"].eq(1),
            "close_price",
        ].item()
        == 18.0
    )


def test_vectorized_stock_rolling_features_match_per_symbol_formulas() -> None:
    dates = pd.bdate_range("2026-01-02", periods=30)
    bars = pd.DataFrame(
        [
            {
                "vt_symbol": symbol,
                "trade_date": trade_date,
                "open_price": 10.0 + day * step,
                "high_price": 10.2 + day * step,
                "low_price": 9.8 + day * step,
                "close_price": 10.1 + day * step,
                "volume": 1_000_000.0 + day * 10_000.0,
                "turnover": 10_000_000.0 + day * 100_000.0,
            }
            for symbol, step in (("600001.SSE", 0.10), ("600002.SSE", -0.03))
            for day, trade_date in enumerate(dates)
        ]
    )
    ordered = bars.sort_values(["vt_symbol", "trade_date"], kind="stable").reset_index(
        drop=True
    )
    grouped = ordered.groupby("vt_symbol", sort=False)

    features = build_causal_stock_features(bars)

    expected = {
        "ma5": grouped["close_price"].transform(
            lambda values: values.rolling(5, min_periods=5).mean()
        ),
        "ma10": grouped["close_price"].transform(
            lambda values: values.rolling(10, min_periods=10).mean()
        ),
        "ma20": grouped["close_price"].transform(
            lambda values: values.rolling(20, min_periods=20).mean()
        ),
        "prior_high20": grouped["high_price"].transform(
            lambda values: values.shift(1).rolling(20, min_periods=20).max()
        ),
        "volume_ratio_prior5": ordered["volume"]
        / grouped["volume"].transform(
            lambda values: values.shift(1).rolling(5, min_periods=5).median()
        ),
        "turnover_expansion": grouped["turnover"].transform(
            lambda values: values.rolling(5, min_periods=5).mean()
        )
        / grouped["turnover"].transform(
            lambda values: values.shift(5).rolling(20, min_periods=15).mean()
        ),
    }
    for column, values in expected.items():
        pd.testing.assert_series_equal(
            features[column],
            values,
            check_names=False,
        )
    assert (
        features.loc[features["vt_symbol"].eq("600002.SSE"), "ma5"]
        .iloc[:4]
        .isna()
        .all()
    )


def _trades() -> pd.DataFrame:
    rows = []
    for variant in (
        "base_confirmation",
        "non_contraction_confirmation",
        GOLD_STRONG_RECLAIM_VARIANT,
        CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
    ):
        for block in range(1, 6):
            rows.append(
                {
                    "signal_id": f"{variant}-{block}",
                    "variant": variant,
                    "time_block": f"block_{block}",
                    "exit_date": pd.Timestamp(2026, 1, block + 1),
                    "net_return_pct": 1.0,
                    "exit_reason": "higher_high_confirmed",
                    "support_line": "ma5",
                    "wave_number": 1,
                    "dynamic_rank": 1,
                }
            )
    return pd.DataFrame(rows)


def _signal(
    signal_id: str,
    signal_date: pd.Timestamp,
    *,
    daily_return: float,
) -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "campaign_id": "campaign-1",
        "sector_id": "BK0001",
        "vt_symbol": "600001.SSE",
        "signal_date": signal_date,
        "feature_cutoff_date": signal_date,
        "signal_close": 95.0,
        "signal_low": 98.0,
        "support_price": 100.0,
        "signal_daily_return_pct": daily_return,
        "wave_number": 1,
        "support_line": "ma5",
        "support_depth": 1,
        "support_test_date": signal_date - pd.Timedelta(days=1),
        "support_test_session_gap": 1,
        "reference_peak_price": 100.0,
        "dynamic_rank": 1,
        "non_contraction_confirmation": True,
    }


def _trade(signal_id: str, entry_date: pd.Timestamp) -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "campaign_id": "campaign-1",
        "sector_id": "BK0001",
        "vt_symbol": "600001.SSE",
        "wave_number": 1,
        "support_line": "ma5",
        "support_depth": 1,
        "support_test_date": entry_date - pd.Timedelta(days=1),
        "dynamic_rank": 1,
        "entry_date": entry_date,
        "exit_date": entry_date + pd.Timedelta(days=1),
        "net_return_pct": 1.0,
        "exit_reason": "higher_high_confirmed",
    }


def _replay_paths(signal_date: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for offset in range(2):
        trade_date = signal_date + pd.Timedelta(days=offset)
        rows.append(
            {
                "campaign_id": "campaign-1",
                "vt_symbol": "600001.SSE",
                "trade_date": trade_date,
                "open_price": 10.0,
                "high_price": 10.2,
                "low_price": 9.8,
                "close_price": 10.1,
                "volume": 1_000_000.0,
                "turnover": 10_000_000.0,
                "daily_return_pct": 1.0,
                "ma5": 10.0,
                "ma10": 9.9,
                "ma20": 9.8,
                "prior_high20": 10.0,
                "volume_ratio_prior5": 1.0,
                "close_location": 0.75,
            }
        )
    return pd.DataFrame(rows)


def _cash_result() -> dict[str, object]:
    return {
        "initial_cash": 100_000.0,
        "final_equity": 101_000.0,
        "compound_return_pct": 1.0,
        "maximum_drawdown_pct": -0.5,
        "accepted_entries": 5,
        "closed_trades": 5,
    }


def _stock_feature(
    member: int, day: int, trade_date: pd.Timestamp
) -> dict[str, object]:
    close_price = 10.0 + (5 - member) * day
    return {
        "vt_symbol": f"60000{member}.SSE",
        "trade_date": trade_date,
        "open_price": close_price - 0.1,
        "high_price": close_price + 0.2,
        "low_price": close_price - 0.2,
        "close_price": close_price,
        "volume": 1_000_000.0,
        "turnover": 10_000_000.0,
        "daily_return_pct": 6.0 if day == 0 else 1.0,
        "ma5": close_price - 0.2,
        "ma10": close_price - 0.4,
        "ma20": close_price - 0.6,
        "prior_high20": close_price - 1.0,
        "volume_ratio_prior5": 2.0,
        "turnover_expansion": 2.0 - member / 10,
        "close_location": 0.75,
        "stock_session_index": 100 + day,
        "previous_close": 10.0,
        "strong_day": day == 0,
        "ignition": day == 0,
        "last_ignition_session_index": 100,
        "sessions_since_ignition": day,
        "last_ignition_date": pd.Timestamp("2026-01-15"),
        "ignition_base_close": 10.0 if day == 0 else None,
        "last_ignition_base_close": 10.0,
        "structure_intact": True,
        "feature_complete": True,
        "feature_cutoff_date": trade_date,
    }
