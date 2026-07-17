from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

import alphaagent.server.services.low_suction.tail_feature_study as study
import alphaagent.server.services.low_suction.tail_gold_feature_study as gold_study
from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.tail_gold_feature_study import (
    build_gold_tail_feature_report,
    run_gold_tail_feature_study,
)
from alphaagent.server.services.low_suction.tail_feature_study import (
    TAIL_NUMERIC_FEATURES,
    build_categorical_feature_metrics,
    build_numeric_success_failure_profiles,
    build_tail_feature_panel,
    build_tail_feature_report,
    evaluate_single_feature_groups,
    execute_tail_trades,
    render_tail_feature_json,
    render_tail_feature_markdown,
    run_tail_feature_study,
)


DATES = tuple(pd.bdate_range("2025-01-02", periods=32).date)
CONTEXT_DATE = DATES[-3]
ENTRY_DATE = DATES[-2]
EXIT_DATE = DATES[-1]


def _five_minute_times(trade_date: date) -> tuple[datetime, ...]:
    morning = [
        datetime.combine(trade_date, datetime.strptime("09:35", "%H:%M").time())
        + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    afternoon = [
        datetime.combine(trade_date, datetime.strptime("13:05", "%H:%M").time())
        + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    return tuple([*morning, *afternoon])


def _candidate(vt_symbol: str = "600001.SSE") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "leader_spell_id": f"BK0001:cycle:{vt_symbol}",
                "recognition_source_date": DATES[-6],
                "context_date": CONTEXT_DATE,
                "source_date": ENTRY_DATE,
                "entry_date": ENTRY_DATE,
                "planned_exit_date": EXIT_DATE,
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "cycle_id": "BK0001:cycle",
                "vt_symbol": vt_symbol,
                "stock_name": "测试股份",
                "recognition_rank": 1,
                "cycle_relative_percentile": 0.9,
                "spell_session_offset": 2,
                "active_direction": "GOLD",
                "danger_state": "NORMAL",
                "market_phase": "launch",
                "main_rise": True,
                "is_top3": True,
                "rank_mode": "event_recognition_proxy",
                "evidence_level": "event_recognition_neutral_day_falsification",
                "block": 1,
            }
        ]
    )


def _daily_bars(vt_symbol: str = "600001.SSE") -> pd.DataFrame:
    rows = []
    close = 9.4
    for index, trade_date in enumerate(DATES):
        close += 0.02
        if trade_date == CONTEXT_DATE:
            close = 10.0
        elif trade_date == ENTRY_DATE:
            close = 10.2
        elif trade_date == EXIT_DATE:
            close = 10.4
        rows.append(
            {
                "vt_symbol": vt_symbol,
                "trade_date": trade_date,
                "open_price": close - 0.05,
                "high_price": close + 0.2,
                "low_price": close - 0.2,
                "close_price": close,
                "volume": 1_000_000.0 + index * 10_000.0,
                "turnover": close * (1_000_000.0 + index * 10_000.0),
            }
        )
    return pd.DataFrame(rows)


def _minute_bars(vt_symbol: str = "600001.SSE") -> pd.DataFrame:
    rows = []
    for trade_date in (ENTRY_DATE, EXIT_DATE):
        for index, bar_time in enumerate(_five_minute_times(trade_date)):
            base = 10.45 if trade_date == ENTRY_DATE else 10.35
            open_price = base
            close_price = base + 0.01
            high_price = max(open_price, close_price) + 0.03
            low_price = min(open_price, close_price) - 0.03
            if trade_date == ENTRY_DATE and bar_time.strftime("%H:%M") == "13:05":
                low_price = 10.20
                close_price = 10.30
            if trade_date == ENTRY_DATE and bar_time.strftime("%H:%M") == "11:30":
                low_price = 10.25
            if trade_date == ENTRY_DATE and bar_time.strftime("%H:%M") == "14:50":
                open_price = 10.28
                high_price = 10.32
                low_price = 10.24
                close_price = 10.30
            if trade_date == ENTRY_DATE and bar_time.strftime("%H:%M") == "14:55":
                open_price = 10.31
                close_price = 10.32
            if trade_date == EXIT_DATE and bar_time.strftime("%H:%M") == "10:35":
                open_price = 10.55
                close_price = 10.56
            volume = 100_000.0 + index * 1_000.0
            rows.append(
                {
                    "vt_symbol": vt_symbol,
                    "trade_date": trade_date,
                    "bar_time": bar_time,
                    "interval": "5m",
                    "open_price": open_price,
                    "high_price": high_price,
                    "low_price": low_price,
                    "close_price": close_price,
                    "volume": volume,
                    "turnover": close_price * volume,
                    "source": "test",
                }
            )
    return pd.DataFrame(rows)


def test_tail_features_stop_at_1450_and_classify_support() -> None:
    features = build_tail_feature_panel(
        _candidate(),
        _daily_bars(),
        _minute_bars(),
    )

    assert len(features) == 1
    row = features.iloc[0]
    assert row["feature_cutoff_time"] == "14:50"
    assert pd.Timestamp(row["feature_cutoff_at"]).strftime("%H:%M") == "14:50"
    assert row["morning_support_state"] == "false_break_reclaimed"
    assert row["support_zone"] == "below_vwap_above_ma5"
    assert row["tail_above_ma5"]
    assert not row["tail_above_vwap"]
    assert set(TAIL_NUMERIC_FEATURES).issubset(features.columns)
    assert {"entry_price", "exit_price", "net_return_pct"}.isdisjoint(
        features.columns
    )


def test_1455_and_d1_mutations_cannot_change_tail_features() -> None:
    baseline = build_tail_feature_panel(
        _candidate(),
        _daily_bars(),
        _minute_bars(),
    )
    changed = _minute_bars()
    times = pd.to_datetime(changed["bar_time"])
    future = times.dt.date > ENTRY_DATE
    future |= (times.dt.date == ENTRY_DATE) & times.dt.strftime("%H:%M").ge("14:55")
    changed.loc[
        future,
        ["open_price", "high_price", "low_price", "close_price", "volume", "turnover"],
    ] = 999_999.0

    repeated = build_tail_feature_panel(
        _candidate(),
        _daily_bars(),
        changed,
    )

    pd.testing.assert_frame_equal(baseline, repeated)


@pytest.mark.parametrize(
    ("afternoon_low", "tail_close", "expected"),
    [
        (10.36, 10.40, "held"),
        (10.20, 10.30, "false_break_reclaimed"),
        (10.20, 10.22, "broken_unrecovered"),
    ],
)
def test_morning_support_states_are_separate(
    afternoon_low: float,
    tail_close: float,
    expected: str,
) -> None:
    bars = _minute_bars()
    entry_day = pd.to_datetime(bars["trade_date"]).dt.date.eq(ENTRY_DATE)
    bar_hhmm = pd.to_datetime(bars["bar_time"]).dt.strftime("%H:%M")
    afternoon = entry_day & bar_hhmm.ge("13:05") & bar_hhmm.le("14:50")
    tail = entry_day & pd.to_datetime(bars["bar_time"]).dt.strftime("%H:%M").eq(
        "14:50"
    )
    bars.loc[afternoon, "low_price"] = afternoon_low
    bars.loc[tail, "close_price"] = tail_close
    bars.loc[tail, "turnover"] = tail_close * bars.loc[tail, "volume"]

    features = build_tail_feature_panel(_candidate(), _daily_bars(), bars)

    assert features.loc[0, "morning_support_state"] == expected


def test_tail_execution_uses_1455_entry_and_first_bar_after_1030() -> None:
    daily = _daily_bars()
    minutes = _minute_bars()
    features = build_tail_feature_panel(_candidate(), daily, minutes)

    ledger = execute_tail_trades(features, daily, minutes)

    row = ledger.iloc[0]
    assert row["status"] == "closed"
    assert pd.Timestamp(row["entry_time"]).strftime("%H:%M") == "14:55"
    assert pd.Timestamp(row["exit_time"]).strftime("%H:%M") == "10:35"
    assert row["entry_price_raw"] == pytest.approx(10.31)
    assert row["exit_price_raw"] == pytest.approx(10.55)
    assert row["tail_success"] == (row["net_return_pct"] > 0)
    assert row["double_cost_net_return_pct"] < row["net_return_pct"]


def test_limit_up_entry_and_limit_down_exit_are_not_assumed_fillable() -> None:
    daily = _daily_bars()
    minutes = _minute_bars()
    features = build_tail_feature_panel(_candidate(), daily, minutes)

    limit_up = minutes.copy()
    entry = pd.to_datetime(limit_up["bar_time"]).eq(
        pd.Timestamp(datetime.combine(ENTRY_DATE, datetime.strptime("14:55", "%H:%M").time()))
    )
    limit_up.loc[entry, "open_price"] = 11.0
    rejected = execute_tail_trades(features, daily, limit_up)

    limit_down = minutes.copy()
    exit_bar = pd.to_datetime(limit_down["bar_time"]).eq(
        pd.Timestamp(datetime.combine(EXIT_DATE, datetime.strptime("10:35", "%H:%M").time()))
    )
    limit_down.loc[exit_bar, "open_price"] = 9.18
    unclosed = execute_tail_trades(features, daily, limit_down)

    assert rejected.loc[0, "status"] == "rejected"
    assert rejected.loc[0, "reason"] == "entry_limit_up_queue_unknown_without_l2"
    assert unclosed.loc[0, "status"] == "unclosed"
    assert unclosed.loc[0, "reason"] == "exit_limit_down_queue_unknown_without_l2"


def _profile_ledger() -> pd.DataFrame:
    rows = []
    dates = tuple(pd.bdate_range("2025-03-03", periods=50).date)
    for index in range(120):
        success = index % 3 == 0
        block = index % 5 + 1
        rows.append(
            {
                "event_id": index + 1,
                "entry_date": dates[index % len(dates)],
                "planned_exit_date": dates[min(index % len(dates) + 1, len(dates) - 1)],
                "block": block,
                "vt_symbol": f"60{index:04d}.SSE",
                "stock_name": f"股票{index}",
                "concept_name": "测试概念",
                "recognition_rank": index % 3 + 1,
                "spell_session_offset": index % 4 + 1,
                "market_regime": "GOLD/NORMAL" if block <= 3 else "SILVER/NORMAL",
                "support_zone": "above_vwap_and_ma5" if success else "below_ma20",
                "morning_support_state": "held" if success else "broken_unrecovered",
                "support_break_count": 0 if success else 5,
                "tail_above_vwap": success,
                "tail_above_ma5": success,
                "tail_above_ma10": success,
                "tail_above_ma20": success,
                "tail_return_bucket": "0_to_3" if success else "below_0",
                "tail_drawdown_bucket": "within_1" if success else "below_5",
                "tail_range_bucket": "top_20" if success else "bottom_20",
                "late_momentum_bucket": "rising" if success else "falling",
                "late_volume_bucket": "contraction" if success else "expansion",
                "recognition_rank_bucket": "rank1" if index % 3 == 0 else "rank2_3",
                "spell_offset_bucket": f"S+{index % 4 + 1}",
                **{
                    feature: float(index + (10 if success else 0))
                    for feature in TAIL_NUMERIC_FEATURES
                },
                "status": "closed",
                "reason": None,
                "entry_time": datetime.combine(dates[index % len(dates)], datetime.strptime("14:55", "%H:%M").time()),
                "exit_time": datetime.combine(dates[min(index % len(dates) + 1, len(dates) - 1)], datetime.strptime("10:35", "%H:%M").time()),
                "entry_price_raw": 10.0,
                "exit_price_raw": 10.2 if success else 9.9,
                "net_return_pct": 1.0 if success else -1.0,
                "double_cost_net_return_pct": 0.7 if success else -1.3,
                "tail_success": success,
                "outcome_group": "success" if success else "failure",
            }
        )
    return pd.DataFrame(rows)


def test_feature_profiles_keep_successes_failures_and_all_states() -> None:
    ledger = _profile_ledger()

    profiles = build_numeric_success_failure_profiles(ledger)
    metrics = build_categorical_feature_metrics(ledger)
    evaluation = evaluate_single_feature_groups(metrics)

    assert set(profiles["outcome_group"]) == {"success", "failure"}
    assert set(TAIL_NUMERIC_FEATURES) == set(profiles["feature"])
    assert "baseline" in set(metrics["table_id"])
    assert "support_zone" in set(metrics["table_id"])
    assert {"all", "development", "validation"}.issubset(metrics["segment"])
    assert evaluation["combined_rule_selected"] is False
    assert evaluation["evaluated_groups"] > 0


def test_report_preserves_formal_nulls_cases_and_boundaries() -> None:
    ledger = _profile_ledger()
    ledger["tail_success"] = ledger["tail_success"].astype("boolean")
    nonfills = ledger.iloc[:2].copy()
    nonfills["event_id"] = [10_001, 10_002]
    nonfills["status"] = ["rejected", "unclosed"]
    nonfills["reason"] = [
        "entry_limit_up_queue_unknown_without_l2",
        "exit_limit_down_queue_unknown_without_l2",
    ]
    nonfills["outcome_group"] = "unavailable"
    ledger = pd.concat([ledger, nonfills], ignore_index=True)
    features = ledger.drop(
        columns=[
            "status",
            "reason",
            "entry_time",
            "exit_time",
            "entry_price_raw",
            "exit_price_raw",
            "net_return_pct",
            "double_cost_net_return_pct",
            "tail_success",
            "outcome_group",
        ]
    )
    metadata = {
        "coverage": {
            "candidate_rows": len(features),
            "complete_pairs": len(features),
            **study._execution_coverage(ledger),
        },
        "input_fingerprints": {
            "tail_features": {
                "algorithm": "sha256",
                "columns": ["event_id", "entry_date"],
                "digest": "sha256:test",
                "rows": len(features),
            }
        },
        "discovery_start": date(2025, 1, 1),
        "discovery_end": date(2025, 12, 31),
    }

    report = build_tail_feature_report(features, ledger, metadata)
    payload = render_tail_feature_json(report)
    markdown = render_tail_feature_markdown(report)

    assert report["formal_rule_selected"] is False
    assert report["formal_metrics"] is None
    assert report["entry_contract"]["feature_cutoff"] == "D 14:50 close"
    assert report["entry_contract"]["entry"] == "D 14:55 bar open"
    assert report["entry_contract"]["exit"] == "D+1 10:35 bar open"
    assert report["largest_winners"]
    assert report["largest_failures"]
    assert all(row["net_return_pct"] > 0 for row in report["largest_winners"])
    assert all(row["net_return_pct"] <= 0 for row in report["largest_failures"])
    assert report["coverage"]["successful_trades"] == 40
    assert report["coverage"]["failed_trades"] == 80
    assert report["coverage"]["status_counts"] == {
        "closed": 120,
        "rejected": 1,
        "unclosed": 1,
    }
    assert '"formal_metrics": null' in payload
    assert "成功案例" in markdown
    assert "失败案例" in markdown
    assert "10:30 后" in markdown
    assert "闭合/成功/失败：`120/40/80`" in markdown
    assert "entry_limit_up_queue_unknown_without_l2" in markdown
    assert "exit_limit_down_queue_unknown_without_l2" in markdown
    assert "## 输入指纹" in markdown
    assert "sha256:test" in markdown


def test_runner_and_cli_expose_no_time_or_feature_switches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _profile_ledger()
    features = ledger.drop(
        columns=[
            "status",
            "reason",
            "entry_time",
            "exit_time",
            "entry_price_raw",
            "exit_price_raw",
            "net_return_pct",
            "double_cost_net_return_pct",
            "tail_success",
            "outcome_group",
        ]
    )
    metadata = {"coverage": {}, "input_fingerprints": {}}
    monkeypatch.setattr(
        study,
        "load_tail_feature_study_data",
        lambda: (features, ledger, metadata),
    )

    report = run_tail_feature_study()
    args = build_parser().parse_args(["v2-tail-feature-study", "--format", "json"])

    assert report["study_track"] == "tail_low_suction_feature_discovery"
    assert args.command == "v2-tail-feature-study"
    for name in ("entry_time", "exit_time", "feature", "support", "threshold"):
        assert not hasattr(args, name)


def test_gold_tail_report_requires_a_pure_d1_gold_cohort() -> None:
    ledger = _profile_ledger().loc[lambda frame: frame["block"].ne(5)].copy()
    ledger["active_direction"] = "GOLD"
    ledger["market_regime"] = "GOLD/NORMAL"
    features = ledger.drop(
        columns=[
            "status",
            "reason",
            "entry_time",
            "exit_time",
            "entry_price_raw",
            "exit_price_raw",
            "net_return_pct",
            "double_cost_net_return_pct",
            "tail_success",
            "outcome_group",
        ]
    )
    metadata = {
        "coverage": {
            "parent_candidate_rows": 120,
            "parent_direction_candidate_counts": {"GOLD": 96, "SILVER": 24},
            "candidate_rows": len(features),
            "complete_pairs": len(features),
            "cohort_candidate_share_pct": 80.0,
            "block_feature_rows": {
                "block_1": 24,
                "block_2": 24,
                "block_3": 24,
                "block_4": 24,
                "block_5": 0,
            },
            "block_dates": {
                "block_1": 10,
                "block_2": 10,
                "block_3": 10,
                "block_4": 10,
                "block_5": 0,
            },
            **study._execution_coverage(ledger),
        },
        "input_fingerprints": {},
    }

    report = build_gold_tail_feature_report(features, ledger, metadata)
    markdown = render_tail_feature_markdown(report)

    assert report["study_track"] == "tail_low_suction_gold_feature_discovery"
    assert report["overall_conclusion"] == "no_stable_gold_tail_feature_group"
    assert report["cohort_contract"] == {
        "active_direction": "GOLD",
        "filter_before_minute_outcomes": True,
        "known_at": "D-1 close",
        "parent_direction_counts_read": True,
        "silver_candidate_feature_or_trade_rows": 0,
    }
    assert report["formal_metrics"] is None
    assert report["formal_rule_selected"] is False
    assert "金手指龙头尾盘低吸" in markdown
    assert "D-1 close" in markdown
    assert "原始时间块覆盖" in markdown
    assert "GOLD" in markdown
    assert "validation 实际只来自 `block_4`" in markdown

    mixed = ledger.copy()
    mixed.loc[mixed.index[-1], "active_direction"] = "SILVER"
    with pytest.raises(ValueError, match="GOLD-only"):
        build_gold_tail_feature_report(features, mixed, metadata)


def test_gold_filter_preserves_parent_chronological_blocks() -> None:
    dates = tuple(pd.bdate_range("2025-01-02", periods=10).date)
    parent = pd.DataFrame(
        {
            "entry_date": dates,
            "active_direction": [
                "GOLD",
                "SILVER",
                "SILVER",
                "SILVER",
                "SILVER",
                "SILVER",
                "SILVER",
                "SILVER",
                "GOLD",
                "SILVER",
            ],
        }
    )

    blocked = study._attach_original_tail_blocks(parent)
    gold = blocked.loc[blocked["active_direction"].eq("GOLD")]

    assert gold[["entry_date", "block"]].to_dict("records") == [
        {"entry_date": dates[0], "block": 1},
        {"entry_date": dates[8], "block": 5},
    ]


def test_gold_tail_runner_and_cli_use_a_fixed_cohort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = _profile_ledger()
    ledger["active_direction"] = "GOLD"
    ledger["market_regime"] = "GOLD/NORMAL"
    features = ledger.drop(
        columns=[
            "status",
            "reason",
            "entry_time",
            "exit_time",
            "entry_price_raw",
            "exit_price_raw",
            "net_return_pct",
            "double_cost_net_return_pct",
            "tail_success",
            "outcome_group",
        ]
    )
    metadata = {
        "coverage": {
            "candidate_rows": len(features),
            "complete_pairs": len(features),
            **study._execution_coverage(ledger),
        },
        "input_fingerprints": {},
    }
    requested: dict[str, str | None] = {}

    def fake_loader(
        *, active_direction: str | None = None
    ) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
        requested["active_direction"] = active_direction
        return features, ledger, metadata

    monkeypatch.setattr(gold_study, "load_tail_feature_study_data", fake_loader)

    report = run_gold_tail_feature_study()
    args = build_parser().parse_args(
        ["v2-tail-gold-feature-study", "--format", "json"]
    )

    assert requested == {"active_direction": "GOLD"}
    assert report["study_track"] == "tail_low_suction_gold_feature_discovery"
    assert args.command == "v2-tail-gold-feature-study"
    for name in ("active_direction", "regime", "threshold", "feature"):
        assert not hasattr(args, name)
