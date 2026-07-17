from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from alphaagent.server.services.low_suction import event_neutral_minutes
from alphaagent.server.services.low_suction.event_neutral_minutes import (
    load_complete_event_neutral_5m_bars,
)
from alphaagent.server.services.low_suction.leader_pullback_moment_study import (
    attach_cycle_leader_identities,
    build_cycle_leader_pullback_report,
    build_leader_pullback_moments,
    build_leader_moment_cohort_trades,
    build_leader_moment_metrics,
    evaluate_causal_leader_moments,
    label_leader_pullback_moments,
    render_cycle_leader_pullback_json,
    render_cycle_leader_pullback_markdown,
    run_cycle_leader_pullback_study,
)
from alphaagent.server.services.low_suction import leader_pullback_moment_study as study
from alphaagent.server.services.low_suction.cli import build_parser


CYCLE_ID = "breakout_trend:BK0001:2025-01-02"


def _candidate() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "source_date": date(2025, 1, 7),
                "entry_date": date(2025, 1, 7),
                "planned_exit_date": date(2025, 1, 8),
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "cycle_id": CYCLE_ID,
                "vt_symbol": "600001.SSE",
                "stock_name": "甲股份",
                "recognition_rank": 1,
                "signal_close": 10.2,
                "active_direction": "GOLD",
                "danger_state": "NORMAL",
                "market_phase": "recovery",
                "leader_spell_id": f"BK0001:{CYCLE_ID}:600001.SSE",
                "recognition_source_date": date(2025, 1, 3),
                "context_date": date(2025, 1, 6),
                "previous_high": 10.3,
                "ma5": 10.0,
                "ma10": 9.5,
                "cycle_relative_percentile": 0.9,
                "spell_session_offset": 2,
                "main_rise": True,
                "is_top3": True,
                "rank_mode": "event_recognition_proxy",
                "evidence_level": "test",
            }
        ]
    )


def _dynamic_leaders() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cycle_id": CYCLE_ID,
                "sector_id": "BK0001",
                "entry_date": pd.Timestamp("2025-01-07"),
                "context_date": pd.Timestamp("2025-01-06"),
                "feature_cutoff_date": pd.Timestamp("2025-01-06"),
                "leader_spell_id": f"BK0001:{CYCLE_ID}:600001.SSE",
                "recognition_source_date": pd.Timestamp("2025-01-03"),
                "vt_symbol": "600001.SSE",
                "stock_name": "甲股份",
                "dynamic_feature_status": "complete",
                "dynamic_stock_return_pct": 20.0,
                "dynamic_concept_return_pct": 5.0,
                "dynamic_excess_return_pct": 15.0,
                "dynamic_near_limit_up_days": 2,
                "dynamic_max_consecutive_near_limit_up_days": 2,
                "dynamic_sessions_since_last_near_limit_up": 0,
                "dynamic_traded_value_20d": 10_000_000.0,
                "dynamic_rank": 1,
                "dynamic_pool_size": 3,
                "dynamic_top3_qualified": True,
                "dynamic_top1": True,
                "dynamic_top3": True,
            }
        ]
    )


def _realized_leaders() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cycle_id": CYCLE_ID,
                "sector_id": "BK0001",
                "vt_symbol": "600001.SSE",
                "stock_name": "甲股份",
                "realized_market_rank": 1,
                "realized_return_rank": 2,
                "realized_stock_return_pct": 30.0,
                "realized_excess_return_pct": 20.0,
                "realized_near_limit_up_days": 3,
                "realized_max_consecutive_near_limit_up_days": 2,
                "realized_path_status": "complete",
            }
        ]
    )


def _minute_times() -> list[datetime]:
    morning = [
        datetime(2025, 1, 7, 9, 35) + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    afternoon = [
        datetime(2025, 1, 7, 13, 5) + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    return [*morning, *afternoon]


def _minute_bars() -> pd.DataFrame:
    closes = [10.20, 9.90, 10.10, 9.30, 9.55, *([9.70] * 43)]
    lows = [10.15, 9.85, 9.98, 9.20, 9.45, *([9.60] * 43)]
    opens = [10.20, *closes[:-1]]
    volumes = [100.0] * 48
    return pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2025, 1, 7),
                "bar_time": bar_time,
                "interval": "5m",
                "open_price": open_price,
                "high_price": max(open_price, close_price) + 0.05,
                "low_price": low_price,
                "close_price": close_price,
                "volume": volume,
                "turnover": close_price * volume,
                "source": "tdx_public_hq",
            }
            for bar_time, open_price, low_price, close_price, volume in zip(
                _minute_times(),
                opens,
                lows,
                closes,
                volumes,
                strict=True,
            )
        ]
    )


def _identified_candidate() -> pd.DataFrame:
    return attach_cycle_leader_identities(
        _candidate(),
        _dynamic_leaders(),
        _realized_leaders(),
    )


def test_complete_minute_loader_returns_exact_candidate_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = pd.DataFrame(
        [{"event_id": 1, "vt_symbol": "600001.SSE", "entry_date": date(2025, 1, 7), "status": "complete"}]
    )
    monkeypatch.setattr(
        event_neutral_minutes,
        "load_event_neutral_5m_manifest",
        lambda candidates: manifest,
    )
    monkeypatch.setattr(pd, "read_sql", lambda *args, **kwargs: _minute_bars())
    monkeypatch.setattr(
        "alphaagent.server.db.session.get_engine",
        lambda: object(),
    )

    bars = load_complete_event_neutral_5m_bars(_candidate())

    assert len(bars) == 48
    assert bars["bar_time"].nunique() == 48
    assert {
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "turnover",
    }.issubset(bars.columns)


def test_complete_minute_loader_fails_closed_for_incomplete_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = pd.DataFrame(
        [{"event_id": 1, "vt_symbol": "600001.SSE", "entry_date": date(2025, 1, 7), "status": "incomplete"}]
    )
    monkeypatch.setattr(
        event_neutral_minutes,
        "load_event_neutral_5m_manifest",
        lambda candidates: manifest,
    )

    with pytest.raises(ValueError, match="complete"):
        load_complete_event_neutral_5m_bars(_candidate())


def test_identity_attachment_keeps_dynamic_and_realized_columns_explicit() -> None:
    identified = _identified_candidate().iloc[0]

    assert identified["dynamic_rank"] == 1
    assert bool(identified["dynamic_top1"])
    assert identified["realized_market_rank"] == 1
    assert identified["realized_return_rank"] == 2
    assert bool(identified["oracle_market_top1"])
    assert bool(identified["oracle_return_top3"])


def test_all_frozen_pullback_moments_use_next_bar_open() -> None:
    moments = build_leader_pullback_moments(_identified_candidate(), _minute_bars())
    by_rule = moments.set_index("moment_rule")

    assert set(by_rule.index) == {
        "ma5_touch_hold",
        "ma10_touch_hold",
        "vwap_reclaim",
        "drawdown_1_reversal",
        "drawdown_3_reversal",
    }
    assert by_rule.loc["ma5_touch_hold", "observed_at"] == datetime(2025, 1, 7, 9, 45)
    assert by_rule.loc["ma5_touch_hold", "entry_time"] == datetime(2025, 1, 7, 9, 50)
    assert by_rule.loc["ma5_touch_hold", "entry_price_raw"] == pytest.approx(10.10)
    assert by_rule.loc["ma10_touch_hold", "observed_at"] == datetime(2025, 1, 7, 9, 55)
    assert by_rule.loc["ma10_touch_hold", "entry_time"] == datetime(2025, 1, 7, 10, 0)
    assert by_rule.loc["ma10_touch_hold", "entry_price_raw"] == pytest.approx(9.55)
    assert not moments.duplicated(["event_id", "moment_rule"]).any()


def test_later_minutes_cannot_change_selected_pullback_moments() -> None:
    baseline = build_leader_pullback_moments(_identified_candidate(), _minute_bars())
    changed_bars = _minute_bars().copy()
    future = changed_bars["bar_time"].gt(datetime(2025, 1, 7, 10, 0))
    changed_bars.loc[future, ["open_price", "high_price", "low_price", "close_price"]] = 30.0
    changed_bars.loc[future, "turnover"] = changed_bars.loc[future, "volume"] * 30.0
    changed = build_leader_pullback_moments(_identified_candidate(), changed_bars)
    columns = [
        "observation_id",
        "moment_rule",
        "observed_at",
        "entry_time",
        "entry_price_raw",
    ]

    pd.testing.assert_frame_equal(baseline[columns], changed[columns])


def _daily_bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": trade_date,
                "open_price": close,
                "high_price": close + 0.2,
                "low_price": close - 0.2,
                "close_price": close,
                "volume": 100_000.0,
            }
            for trade_date, close in (
                (date(2025, 1, 6), 10.2),
                (date(2025, 1, 7), 9.7),
                (date(2025, 1, 8), 10.5),
            )
        ]
    )


def test_moment_labels_attach_only_after_identity_and_double_cost() -> None:
    moments = build_leader_pullback_moments(_identified_candidate(), _minute_bars())
    trades = label_leader_pullback_moments(
        moments,
        _daily_bars(),
        trading_dates=(date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)),
    )

    assert trades["normal_status"].eq("closed").all()
    assert trades["stressed_status"].eq("closed").all()
    assert trades["double_cost_net_return_pct"].le(trades["net_return_pct"]).all()
    assert trades["dynamic_rank"].eq(1).all()
    assert trades["realized_market_rank"].eq(1).all()


def _metric_trades() -> pd.DataFrame:
    rows = []
    dates = tuple(pd.bdate_range("2025-01-02", periods=50).date)
    for index, entry_date in enumerate(dates):
        block = index % 3 + 1 if index < 30 else index % 2 + 4
        for rule, value in (
            ("ma5_touch_hold", 1.0 if index % 4 else -0.5),
            ("vwap_reclaim", 0.5 if index % 2 else -1.0),
        ):
            rows.append(
                {
                    "observation_id": f"{rule}-{index}",
                    "event_id": index,
                    "cycle_id": CYCLE_ID,
                    "entry_date": entry_date,
                    "block": block,
                    "moment_rule": rule,
                    "dynamic_top3_qualified": True,
                    "dynamic_top1": index % 2 == 0,
                    "dynamic_top3": True,
                    "oracle_market_top1": index % 3 == 0,
                    "oracle_market_top3": True,
                    "oracle_return_top1": index % 5 == 0,
                    "oracle_return_top3": True,
                    "signal_time_bucket": "opening_30",
                    "drawdown_bucket": "moderate_1_3",
                    "intraday_volume_class": "normal",
                    "market_regime": "GOLD/NORMAL",
                    "normal_status": "closed",
                    "stressed_status": "closed",
                    "net_return_pct": value,
                    "double_cost_net_return_pct": value - 0.2,
                }
            )
    unqualified = pd.DataFrame(rows[:2]).assign(
        observation_id=lambda frame: "unqualified-" + frame["observation_id"],
        dynamic_top3_qualified=False,
        dynamic_top1=False,
        dynamic_top3=False,
    )
    return pd.concat([pd.DataFrame(rows), unqualified], ignore_index=True)


def test_causal_and_oracle_metrics_are_separate_and_time_split() -> None:
    cohorts = build_leader_moment_cohort_trades(_metric_trades())
    metrics = build_leader_moment_metrics(cohorts)
    evaluation = evaluate_causal_leader_moments(metrics)

    assert {
        "causal_rule_x_identity",
        "oracle_rule_x_identity",
    }.issubset(set(cohorts["table_id"]))
    causal = cohorts.loc[cohorts["table_id"].eq("causal_rule_x_identity")]
    assert not causal["cohort_key"].str.contains("oracle").any()
    assert not causal["observation_id"].str.startswith("unqualified").any()
    top3_ma5 = metrics.loc[
        metrics["table_id"].eq("causal_rule_x_identity")
        & metrics["cohort_key"].eq("dynamic_top3|ma5_touch_hold")
    ].set_index("segment")
    assert top3_ma5.loc["development", "closed_trades"] == 30
    assert top3_ma5.loc["validation", "closed_trades"] == 20
    assert top3_ma5.loc["all", "compound_return_pct"] > 0
    assert top3_ma5.loc["all", "maximum_drawdown_pct"] <= 0
    assert evaluation["causal_evaluated_cohorts"] >= 1
    assert evaluation["causal_adequately_sampled_cohorts"] >= 1
    assert any(row["adequately_sampled"] for row in evaluation["cohort_evaluation"])


def _period_summary() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sector_id": "BK0001",
                "concept_name": "测试概念一",
                "cycle_id": CYCLE_ID,
                "period_start": pd.Timestamp("2025-01-02"),
                "period_end": pd.Timestamp("2025-01-09"),
                "active_sessions": 6,
                "candidate_count": 3,
                "period_status": "completed",
                "candidate_pool": "event_candidate_pool",
                "realized_market_top3": "甲股份 (600001.SSE)",
                "realized_return_top3": "乙股份 (600002.SSE)",
                "dynamic_sessions": 2,
                "qualified_dynamic_sessions": 1,
                "distinct_dynamic_top1": 1,
                "realized_market_top1_dynamic_top3_retention_pct": 100.0,
            },
            {
                "sector_id": "BK0002",
                "concept_name": "测试概念二",
                "cycle_id": "breakout_trend:BK0002:2025-01-02",
                "period_start": pd.Timestamp("2025-01-02"),
                "period_end": pd.Timestamp("2025-01-09"),
                "active_sessions": 6,
                "candidate_count": 2,
                "period_status": "censored_at_discovery_end",
                "candidate_pool": "event_candidate_pool",
                "realized_market_top3": "丁股份 (600004.SSE)",
                "realized_return_top3": "戊股份 (600005.SSE)",
                "dynamic_sessions": 0,
                "qualified_dynamic_sessions": 0,
                "distinct_dynamic_top1": 0,
                "realized_market_top1_dynamic_top3_retention_pct": None,
            },
        ]
    )


def _report_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    trades = _metric_trades()
    cohorts = build_leader_moment_cohort_trades(trades)
    metrics = build_leader_moment_metrics(cohorts)
    evaluation = evaluate_causal_leader_moments(metrics)
    return _period_summary(), trades, metrics, evaluation


def test_report_lists_every_period_and_keeps_formal_claims_closed() -> None:
    periods, trades, metrics, evaluation = _report_frames()
    report = build_cycle_leader_pullback_report(
        periods,
        trades,
        metrics,
        evaluation,
        metadata={
            "coverage": {"observed_periods": 2, "minute_rows": 48},
            "input_fingerprints": {},
            "discovery_start": date(2025, 1, 1),
            "discovery_end": date(2025, 2, 1),
        },
    )
    payload = render_cycle_leader_pullback_json(report)
    markdown = render_cycle_leader_pullback_markdown(report)
    assert "因果规则组/充分样本组/稳定正期望/高胜率" in markdown

    assert report["formal_metrics"] is None
    assert report["formal_rule_selected"] is False
    assert len(report["period_leaders"]) == 2
    assert "NaN" not in payload
    assert "测试概念一" in markdown
    assert "测试概念二" in markdown
    assert "事后阶段龙头" in markdown
    assert "D-1 动态龙头" in markdown


def test_runner_and_cli_have_no_threshold_or_identity_switches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = _report_frames()
    monkeypatch.setattr(
        study,
        "load_cycle_leader_pullback_study_data",
        lambda: (
            *frames,
            {
                "coverage": {"observed_periods": 2, "minute_rows": 48},
                "input_fingerprints": {},
                "discovery_start": date(2025, 1, 1),
                "discovery_end": date(2025, 2, 1),
            },
        ),
    )

    report = run_cycle_leader_pullback_study()
    args = build_parser().parse_args(
        ["v2-cycle-leader-pullback-study", "--format", "json"]
    )
    assert report["frozen_contract"]["causal_identity"] == "D-1 dynamic Top1/Top3"
    assert args.command == "v2-cycle-leader-pullback-study"
    assert not hasattr(args, "threshold")
    assert not hasattr(args, "identity_mode")
