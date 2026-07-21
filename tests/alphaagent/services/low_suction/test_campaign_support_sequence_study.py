from __future__ import annotations

import json

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.campaign_support_sequence_study import (
    build_campaign_close_trades,
    build_campaign_opportunity_ledger,
    build_campaign_support_sequence_report,
    build_case_daily_path,
    classify_support_zone,
    render_campaign_support_sequence_json,
    render_campaign_support_sequence_markdown,
)
from alphaagent.server.services.low_suction.confirmed_multi_wave_pullback_study import (
    build_campaign_support_signals,
    build_confirmed_multi_wave_signals,
)


def _campaign_fixture() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    dates = pd.bdate_range("2025-01-02", periods=40)
    closes = [10.0 + index * 0.01 for index in range(25)]
    closes.extend(
        [
            11.50,
            10.30,
            10.50,
            12.00,
            11.30,
            11.50,
            12.60,
            11.80,
            12.00,
            13.20,
        ]
    )
    closes.extend([13.10, 13.00, 12.90, 12.80, 12.70])
    explicit = {
        25: (11.70, 11.30),
        26: (10.50, 10.20),
        27: (10.70, 10.20),
        28: (12.20, 11.80),
        29: (11.60, 11.10),
        30: (11.70, 11.10),
        31: (12.80, 12.40),
        32: (12.10, 11.60),
        33: (12.20, 11.60),
        34: (13.40, 13.00),
    }
    bars = pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": trade_date,
                "open_price": close,
                "high_price": explicit.get(index, (close + 0.1, close - 0.1))[0],
                "low_price": explicit.get(index, (close + 0.1, close - 0.1))[1],
                "close_price": close,
                "volume": 100.0,
                "turnover": close * 100.0,
            }
            for index, (trade_date, close) in enumerate(zip(dates, closes, strict=True))
        ]
    )
    episode_id = "campaign-a"
    episodes = pd.DataFrame(
        [
            {
                "episode_id": episode_id,
                "cycle_id": "cycle-a",
                "vt_symbol": "600001.SSE",
                "stock_name": "测试龙头",
                "sector_id": "BK001",
                "concept_name": "测试概念",
                "anchor_date": dates[25],
                "observation_end": dates[-1],
                "causal_rank": 1,
                "time_block": "block_1",
            }
        ]
    )
    waves = pd.DataFrame(
        [
            {
                "episode_id": episode_id,
                "wave_number": wave_number,
                "wave_start_date": dates[start],
                "observation_end": dates[-1],
            }
            for wave_number, start in ((1, 25), (2, 28), (3, 31))
        ]
    )
    concept_states = pd.DataFrame(
        [
            {
                "sector_id": "BK001",
                "trade_date": trade_date,
                "definition": "breakout_trend",
                "in_cycle": True,
                "sustain_qualifies": True,
                "cycle_id": "cycle-a",
            }
            for trade_date in dates
        ]
    )
    return episodes, waves, bars, concept_states


def test_campaign_replay_starts_at_wave_one_without_changing_confirmed_default() -> None:
    episodes, waves, bars, concept_states = _campaign_fixture()

    campaign = build_campaign_support_signals(
        episodes,
        waves,
        bars,
        concept_states,
    )
    confirmed = build_confirmed_multi_wave_signals(
        episodes,
        waves,
        bars,
        concept_states,
    )

    campaign_stabilized = campaign.loc[
        campaign["signal_mode"].eq("stabilized_reclaim")
    ]
    assert campaign_stabilized["wave_number"].tolist() == [1, 2, 3]
    assert campaign_stabilized["wave_bucket"].tolist() == [
        "wave_1",
        "wave_2",
        "wave_3",
    ]
    assert confirmed["wave_number"].eq(3).all()


@pytest.mark.parametrize(
    ("low", "expected"),
    [
        (10.10, "ma5_near"),
        (9.50, "ma5_ma10_band"),
        (8.50, "ma10_ma20_band"),
        (7.50, "below_ma20"),
    ],
)
def test_support_zone_uses_the_actual_low_between_moving_averages(
    low: float,
    expected: str,
) -> None:
    assert classify_support_zone(low, ma5=10.0, ma10=9.0, ma20=8.0) == expected


def test_opportunity_ordinal_does_not_reset_after_a_higher_high() -> None:
    episodes, waves, bars, concept_states = _campaign_fixture()
    signals = build_campaign_support_signals(
        episodes,
        waves,
        bars,
        concept_states,
    )

    ledger = build_campaign_opportunity_ledger(signals, bars)

    assert ledger["campaign_opportunity_ordinal"].tolist() == [1, 2, 3]
    assert ledger["campaign_wave_number"].tolist() == [1, 2, 3]
    assert ledger["episode_id"].nunique() == 1


def test_case_daily_path_distinguishes_peak_day_observation_from_confirmation() -> None:
    episodes, waves, bars, concept_states = _campaign_fixture()
    signals = build_campaign_support_signals(
        episodes,
        waves,
        bars,
        concept_states,
    )
    opportunities = build_campaign_opportunity_ledger(signals, bars)
    trades = build_campaign_close_trades(opportunities, bars)

    path = build_case_daily_path(trades, bars)

    first_signal_date = trades.iloc[0]["signal_date"]
    first_peak_date = trades.iloc[0]["reference_peak_date"]
    signal_annotation = path.loc[
        path["trade_date"].eq(first_signal_date), "annotations"
    ].iloc[0]
    peak_annotation = path.loc[
        path["trade_date"].eq(first_peak_date), "annotations"
    ].iloc[0]
    assert "opportunity_1_stabilization" in signal_annotation
    assert "wave_1_reference_peak" in peak_annotation


def _exit_fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2025-01-02", periods=25)
    paths = {
        "terminal": [*([10.0] * 20), 12.0, 9.5, 9.0, 8.8, 8.7],
        "clean": [*([10.0] * 20), 10.0, 10.5, 11.2, 11.1, 11.0],
        "false_exit": [*([10.0] * 20), 10.2, 9.8, 11.2, 11.1, 11.0],
    }
    peaks = {"terminal": 13.0, "clean": 11.0, "false_exit": 11.0}
    bars = []
    signals = []
    for symbol, closes in paths.items():
        for index, (trade_date, close) in enumerate(zip(dates, closes, strict=True)):
            high = close + 0.1
            if symbol in {"clean", "false_exit"} and index == 22:
                high = 11.5
            bars.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "open_price": close,
                    "high_price": high,
                    "low_price": close - 0.1,
                    "close_price": close,
                    "volume": 100.0,
                    "turnover": close * 100.0,
                }
            )
        signals.append(
            {
                "signal_id": f"signal-{symbol}",
                "signal_mode": "stabilized_reclaim",
                "episode_id": f"episode-{symbol}",
                "vt_symbol": symbol,
                "stock_name": symbol,
                "sector_id": "BK001",
                "concept_name": "测试概念",
                "anchor_date": dates[20],
                "observation_end": dates[-1],
                "causal_rank": 1,
                "time_block": "block_1",
                "wave_number": 1,
                "wave_start_date": dates[20],
                "first_support_approach_date": dates[20],
                "signal_date": dates[20],
                "reference_peak_date": dates[19],
                "reference_peak_price": peaks[symbol],
                "concept_main_rise_intact": True,
                "stock_structure_intact": True,
            }
        )
    return pd.DataFrame(signals), pd.DataFrame(bars)


def test_d1_variants_measure_rescues_and_false_exits_without_lookahead() -> None:
    signals, bars = _exit_fixture()
    opportunities = build_campaign_opportunity_ledger(signals, bars)

    trades = build_campaign_close_trades(opportunities, bars).set_index("vt_symbol")

    terminal = trades.loc["terminal"]
    assert terminal["d1_not_up"]
    assert terminal["d1_not_up_and_below_ma5"]
    assert terminal["d1_not_up_net_return_pct"] > terminal[
        "baseline_net_return_pct"
    ]
    clean = trades.loc["clean"]
    assert not clean["d1_not_up"]
    assert clean["d1_not_up_net_return_pct"] == pytest.approx(
        clean["baseline_net_return_pct"]
    )
    false_exit = trades.loc["false_exit"]
    assert false_exit["eventually_made_higher_high"]
    assert false_exit["d1_not_up_exit_triggered"]
    assert false_exit["d1_not_up_net_return_pct"] < 0
    assert false_exit["baseline_net_return_pct"] > 0


def test_report_separates_higher_high_success_from_positive_return() -> None:
    signals, bars = _exit_fixture()
    opportunities = build_campaign_opportunity_ledger(signals, bars)
    trades = build_campaign_close_trades(opportunities, bars)
    episodes = signals.loc[
        :,
        [
            "episode_id",
            "vt_symbol",
            "anchor_date",
            "observation_end",
        ],
    ]
    waves = signals.loc[
        :,
        ["episode_id", "wave_number", "wave_start_date", "observation_end"],
    ]

    report = build_campaign_support_sequence_report(
        candidates=signals.iloc[:2],
        episodes=episodes,
        waves=waves,
        opportunities=opportunities,
        trades=trades,
        input_fingerprints={},
    )

    assert report["formal_strategy"] is False
    assert report["formal_metrics"] is None
    assert report["coverage"]["causal_campaign_episodes"] == 3
    assert report["coverage"]["frozen_case_campaigns"] == 2
    baseline = report["baseline_summary"]["all"]
    assert baseline["signals"] == 3
    assert baseline["higher_high_success_rate_pct"] == pytest.approx(200 / 3)
    assert baseline["positive_return_rate_pct"] == pytest.approx(200 / 3)
    assert report["main_rise_summary"]["all"]["signals"] == 3
    assert report["selected_case_summary"]["all"]["signals"] == 2
    d1 = report["d1_exit_comparison"]["d1_not_up"]
    assert d1["triggered_trades"] == 2
    assert d1["rescued_baseline_losers"] == 1
    assert d1["false_exits_before_later_higher_high"] == 1
    assert len(d1["by_campaign_opportunity_ordinal"]) == 1

    encoded = json.loads(render_campaign_support_sequence_json(report))
    assert encoded["coverage"]["campaign_episodes"] == 3
    markdown = render_campaign_support_sequence_markdown(report)
    assert "Campaign opportunity" in markdown
    assert "D+1 not up" in markdown


def test_cli_accepts_campaign_support_sequence_study() -> None:
    args = build_parser().parse_args(
        ["v2-campaign-support-sequence-study", "--format", "json"]
    )

    assert args.command == "v2-campaign-support-sequence-study"
    assert args.format == "json"
