from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cross_leader_wave_study import (
    build_causal_wave_episodes,
    build_cross_leader_wave_report,
    build_non_overlapping_wave_paths,
    classify_xuguang_climax,
    filter_complete_episode_paths,
    render_cross_leader_wave_json,
    render_cross_leader_wave_markdown,
    replay_leader_wave_episodes,
)


def _trading_dates(periods: int = 90) -> tuple[date, ...]:
    return tuple(pd.bdate_range("2025-01-02", periods=periods).date)


def _rank_row(
    *,
    cycle_id: str,
    trade_date: date,
    sector_id: str,
    vt_symbol: str,
    causal_rank: int = 1,
    main_rise_alive: bool = True,
) -> dict[str, object]:
    return {
        "cycle_id": cycle_id,
        "trade_date": trade_date,
        "sector_id": sector_id,
        "concept_name": f"概念-{sector_id}",
        "vt_symbol": vt_symbol,
        "stock_name": f"股票-{vt_symbol}",
        "causal_rank": causal_rank,
        "causal_top3": causal_rank <= 3,
        "main_rise_alive": main_rise_alive,
        "feature_cutoff_date": trade_date,
    }


def _causal_rank_fixture() -> tuple[pd.DataFrame, tuple[date, ...]]:
    dates = _trading_dates()
    rows = [
        _rank_row(
            cycle_id="cycle-a",
            trade_date=dates[5],
            sector_id="BK001",
            vt_symbol="600001.SSE",
            causal_rank=1,
        ),
        _rank_row(
            cycle_id="cycle-b",
            trade_date=dates[5],
            sector_id="BK002",
            vt_symbol="600001.SSE",
            causal_rank=2,
        ),
        _rank_row(
            cycle_id="cycle-c",
            trade_date=dates[10],
            sector_id="BK003",
            vt_symbol="600001.SSE",
            causal_rank=1,
        ),
        _rank_row(
            cycle_id="cycle-d",
            trade_date=dates[5],
            sector_id="BK004",
            vt_symbol="600002.SSE",
            main_rise_alive=False,
        ),
        _rank_row(
            cycle_id="cycle-e",
            trade_date=dates[55],
            sector_id="BK005",
            vt_symbol="600003.SSE",
        ),
        _rank_row(
            cycle_id="cycle-f",
            trade_date=dates[5],
            sector_id="BK006",
            vt_symbol="600004.SSE",
            causal_rank=4,
        ),
    ]
    return pd.DataFrame(rows), dates


def test_causal_episode_selection_is_outcome_neutral_and_non_overlapping() -> None:
    ranks, dates = _causal_rank_fixture()

    episodes = build_causal_wave_episodes(ranks, trading_dates=dates)
    changed = ranks.assign(
        future_wave_count=[99, -99, 1000, 2, 3, 4],
        net_return_pct=[-100.0, 100.0, 999.0, 1.0, 2.0, 3.0],
    )
    mutated = build_causal_wave_episodes(changed, trading_dates=dates)

    identity = ["episode_id", "vt_symbol", "anchor_date", "observation_end"]
    pd.testing.assert_frame_equal(episodes[identity], mutated[identity])
    assert episodes["vt_symbol"].tolist() == ["600001.SSE"]
    assert episodes["anchor_date"].tolist() == [pd.Timestamp(dates[5])]
    assert episodes["observation_end"].tolist() == [pd.Timestamp(dates[45])]
    assert episodes["concept_count_at_anchor"].tolist() == [2]
    assert episodes["feature_cutoff_date"].eq(episodes["anchor_date"]).all()


def test_causal_episode_selection_rejects_noncausal_known_at() -> None:
    ranks, dates = _causal_rank_fixture()
    ranks.loc[0, "feature_cutoff_date"] = dates[6]

    with pytest.raises(ValueError, match="feature cutoff"):
        build_causal_wave_episodes(ranks, trading_dates=dates)


def test_incomplete_stock_paths_are_explicitly_excluded() -> None:
    dates = tuple(pd.bdate_range("2025-01-02", periods=4).date)
    episodes = pd.DataFrame(
        [
            {
                "episode_id": "complete",
                "vt_symbol": "600001.SSE",
                "anchor_date": dates[0],
                "observation_end": dates[3],
            },
            {
                "episode_id": "missing",
                "vt_symbol": "600002.SSE",
                "anchor_date": dates[0],
                "observation_end": dates[3],
            },
        ]
    )
    bars = pd.DataFrame(
        [
            {"vt_symbol": symbol, "trade_date": trade_date}
            for symbol in ("600001.SSE", "600002.SSE")
            for trade_date in dates
            if not (symbol == "600002.SSE" and trade_date == dates[2])
        ]
    )

    eligible, excluded = filter_complete_episode_paths(
        episodes,
        bars,
        trading_dates=dates,
    )

    assert eligible["episode_id"].tolist() == ["complete"]
    assert excluded[["episode_id", "missing_session_count"]].to_dict("records") == [
        {"episode_id": "missing", "missing_session_count": 1}
    ]


@pytest.mark.parametrize(
    ("gain", "strong_days", "volume_ratio", "expected"),
    [
        (50.0, 3, 3.0, True),
        (49.999, 3, 3.0, False),
        (50.0, 2, 3.0, False),
        (50.0, 3, 2.999, False),
        (None, 3, 3.0, False),
    ],
)
def test_xuguang_climax_requires_all_predeclared_observations(
    gain: float | None,
    strong_days: int,
    volume_ratio: float,
    expected: bool,
) -> None:
    assert classify_xuguang_climax(gain, strong_days, volume_ratio) is expected


def _bar(
    trade_date: pd.Timestamp,
    *,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> dict[str, object]:
    return {
        "vt_symbol": "600001.SSE",
        "trade_date": trade_date,
        "open_price": close,
        "high_price": high,
        "low_price": low,
        "close_price": close,
        "volume": volume,
        "turnover": close * volume,
    }


def _wave_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=32)
    rows = [
        _bar(day, high=10.2, low=9.8, close=10.0, volume=100.0)
        for day in dates[:25]
    ]
    rows.extend(
        [
            _bar(dates[25], high=11.0, low=9.9, close=10.8, volume=200.0),
            _bar(dates[26], high=12.0, low=10.7, close=11.8, volume=160.0),
            _bar(dates[27], high=11.7, low=10.9, close=11.4, volume=70.0),
            _bar(dates[28], high=11.3, low=10.55, close=10.7, volume=90.0),
            _bar(dates[29], high=10.8, low=9.9, close=10.1, volume=180.0),
            _bar(dates[30], high=11.5, low=10.0, close=11.2, volume=120.0),
            _bar(dates[31], high=12.5, low=11.1, close=12.3, volume=150.0),
        ]
    )
    return pd.DataFrame(rows)


def test_episode_replay_uses_existing_wave_and_cost_contract() -> None:
    bars = _wave_bars()
    anchor = pd.Timestamp(bars.iloc[25]["trade_date"])
    episodes = pd.DataFrame(
        [
            {
                "episode_id": "dynamic:600001.SSE:2025-02-06",
                "cohort": "dynamic_causal_top3_proxy",
                "vt_symbol": "600001.SSE",
                "stock_name": "测试股票",
                "anchor_date": anchor,
                "observation_end": pd.Timestamp(bars.iloc[-1]["trade_date"]),
                "causal_rank": 1,
                "sector_id": "BK001",
                "concept_name": "测试概念",
                "time_block": "block_1",
            }
        ]
    )

    result = replay_leader_wave_episodes(episodes, bars)

    assert set(result) == {"waves", "approaches", "trades", "impulses"}
    assert not result["waves"].empty
    assert result["waves"].iloc[0]["resolution_status"] == "continued_to_higher_high"
    assert result["approaches"]["approach_tolerance_pct"].eq(2.0).all()
    assert result["trades"]["round_trip_cost_pct"].eq(0.2).all()
    assert result["trades"]["executable_exit_reason"].eq(
        "higher_high_confirmed"
    ).any()
    path = build_non_overlapping_wave_paths(result["trades"])
    assert len(path) == 1
    assert path.iloc[0]["support_line"] == "ma5"
    assert path.iloc[0]["episode_equity_after_exit"] == pytest.approx(
        1.0 + path.iloc[0]["net_return_pct"] / 100.0
    )


def test_report_keeps_reference_and_formal_metrics_separate() -> None:
    bars = _wave_bars()
    anchor = pd.Timestamp(bars.iloc[25]["trade_date"])
    dynamic_episodes = pd.DataFrame(
        [
            {
                "episode_id": "dynamic:600001.SSE:2025-02-06",
                "cohort": "dynamic_causal_top3_proxy",
                "vt_symbol": "600001.SSE",
                "stock_name": "测试股票",
                "anchor_date": anchor,
                "observation_end": pd.Timestamp(bars.iloc[-1]["trade_date"]),
                "causal_rank": 1,
                "sector_id": "BK001",
                "concept_name": "测试概念",
                "time_block": "block_1",
            }
        ]
    )
    replay = replay_leader_wave_episodes(dynamic_episodes, bars)

    report = build_cross_leader_wave_report(
        dynamic_episodes=dynamic_episodes,
        dynamic_replay=replay,
        reference_episodes=pd.DataFrame(),
        reference_replay={key: value.iloc[0:0] for key, value in replay.items()},
        coverage={"strict_historical_membership_rows": 0},
        fingerprints={},
    )

    assert report["formal_metrics"] == {
        "win_rate_pct": None,
        "compounded_return_pct": None,
        "profit_factor": None,
        "maximum_drawdown_pct": None,
    }
    assert report["dynamic_cohort"]["membership_evidence"] == (
        "current_membership_and_security_proxy"
    )
    assert report["reference_cohort"]["pooled_with_dynamic"] is False
    assert report["trade_contract"]["round_trip_cost_pct"] == 0.2
    assert report["dynamic_retrospective_episode_summary"][0]["group"] == (
        "single_continuation"
    )
    rendered_json = render_cross_leader_wave_json(report)
    rendered_markdown = render_cross_leader_wave_markdown(report)
    assert render_cross_leader_wave_json(report) == rendered_json
    assert '"formal_metrics"' in rendered_json
    assert "正式胜率、收益、复利：`null`" in rendered_markdown
