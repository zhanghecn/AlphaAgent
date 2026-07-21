from __future__ import annotations

import json

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.daily_leader_spell_date_study import (
    build_daily_leader_spell_date_report,
    build_daily_event_candidate_ledger,
    build_leader_continuation_truth,
    build_leader_confirmations,
    build_leader_lifecycles,
    build_restart_aware_concept_impulses,
    render_daily_leader_spell_date_json,
    render_daily_leader_spell_date_markdown,
    summarize_exploratory_continuation_slice,
    summarize_leader_date_modes,
    summarize_leader_outcome_groups,
)


def test_candidate_ledger_allows_new_leader_to_overtake_old_leaders() -> None:
    ledger = build_daily_event_candidate_ledger(
        _campaigns(),
        _relations(),
        _bars(),
    )

    new = ledger.loc[ledger["vt_symbol"].eq("002579.SZSE")]
    assert new["trade_date"].tolist() == list(
        pd.to_datetime(["2026-05-26", "2026-05-27", "2026-05-28"])
    )
    assert new["causal_gain_rank"].tolist() == [2, 1, 1]
    assert set(
        ledger.loc[
            ledger["trade_date"].eq(pd.Timestamp("2026-05-25")),
            "vt_symbol",
        ]
    ) == {"002745.SZSE", "603256.SSE"}


def test_candidate_ledger_ignores_future_price_mutation() -> None:
    baseline = build_daily_event_candidate_ledger(
        _campaigns(),
        _relations(),
        _bars(),
    )
    changed = _bars()
    changed.loc[changed["trade_date"].gt("2026-05-27"), "close_price"] *= 4
    changed.loc[changed["trade_date"].gt("2026-05-27"), "high_price"] *= 4
    changed.loc[changed["trade_date"].gt("2026-05-27"), "low_price"] *= 4

    mutated = build_daily_event_candidate_ledger(
        _campaigns(),
        _relations(),
        changed,
    )

    cutoff = pd.Timestamp("2026-05-27")
    pd.testing.assert_frame_equal(
        baseline.loc[baseline["trade_date"].le(cutoff)].reset_index(drop=True),
        mutated.loc[mutated["trade_date"].le(cutoff)].reset_index(drop=True),
    )


def test_same_stock_gets_a_fresh_spell_in_a_later_campaign() -> None:
    campaigns = pd.concat(
        [
            _campaigns(),
            pd.DataFrame(
                [
                    {
                        "campaign_id": "pcb-2",
                        "sector_id": "BK0877",
                        "concept_name": "PCB",
                        "anchor_date": "2026-06-02",
                        "end_date": "2026-06-03",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    relations = pd.concat(
        [
            _relations(),
            pd.DataFrame(
                [
                    {
                        "source_date": "2026-06-02",
                        "sector_id": "BK0877",
                        "concept_name": "PCB",
                        "vt_symbol": "002579.SZSE",
                        "stock_name": "中京电子",
                        "limit_times": 1,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    ledger = build_daily_event_candidate_ledger(campaigns, relations, _bars())
    rows = ledger.loc[ledger["vt_symbol"].eq("002579.SZSE")]

    assert rows["campaign_id"].nunique() == 2
    assert rows["leader_spell_id"].nunique() == 2
    assert set(rows["ignition_date"]) == {
        pd.Timestamp("2026-05-26"),
        pd.Timestamp("2026-06-02"),
    }


def test_two_strong_closes_confirm_new_leader_without_backdating() -> None:
    ledger = build_daily_event_candidate_ledger(
        _campaigns(),
        _relations(),
        _bars(),
    )

    confirmations = build_leader_confirmations(ledger)
    row = confirmations.loc[
        confirmations["vt_symbol"].eq("002579.SZSE")
        & confirmations["leader_date_mode"].eq("two_strong_gain_top3")
    ].iloc[0]

    assert row["ignition_date"] == pd.Timestamp("2026-05-26")
    assert row["confirmation_date"] == pd.Timestamp("2026-05-27")
    assert row["confirmation_known_at"] == pd.Timestamp("2026-05-27")
    assert row["confirmation_lag_sessions"] == 1
    assert row["confirmation_causal_gain_rank"] == 1
    assert row["confirmation_gain_pct"] > 20
    assert "realized_peak_date" not in confirmations


def test_early_phase_mode_rejects_a_mature_ignition() -> None:
    relations = _relations()
    relations.loc[
        relations["vt_symbol"].eq("002579.SZSE"), "limit_times"
    ] += 2
    ledger = build_daily_event_candidate_ledger(_campaigns(), relations, _bars())

    confirmations = build_leader_confirmations(ledger)
    zhongjing_modes = set(
        confirmations.loc[
            confirmations["vt_symbol"].eq("002579.SZSE"), "leader_date_mode"
        ]
    )

    assert "two_strong_gain_top3" in zhongjing_modes
    assert "two_strong_gain_top3_early_phase" not in zhongjing_modes


def test_lifecycle_separates_realized_peak_from_causal_end_confirmation() -> None:
    ledger = build_daily_event_candidate_ledger(
        _campaigns(),
        _relations(),
        _bars(),
    )
    confirmations = build_leader_confirmations(ledger)

    lifecycles = build_leader_lifecycles(confirmations, _bars())
    row = lifecycles.loc[
        lifecycles["vt_symbol"].eq("002579.SZSE")
        & lifecycles["leader_date_mode"].eq("two_strong_gain_top3")
    ].iloc[0]

    assert row["realized_peak_date"] == pd.Timestamp("2026-06-02")
    assert row["realized_peak_close"] == 20.76
    assert row["first_end_warning_date"] == pd.Timestamp("2026-06-05")
    assert row["end_warning_date"] == pd.Timestamp("2026-06-05")
    assert row["end_confirmation_date"] == pd.Timestamp("2026-06-08")
    assert row["end_confirmation_known_at"] == pd.Timestamp("2026-06-08")


def test_one_ma5_break_is_cleared_before_a_later_confirmed_end() -> None:
    dates = pd.bdate_range("2026-01-02", periods=14)
    closes = [10, 10, 10, 10, 10, 11, 12, 10.5, 13, 13.5, 11.5, 11, 10.5, 10]
    bars = pd.DataFrame(
        {
            "vt_symbol": "600001.SSE",
            "trade_date": dates,
            "open_price": closes,
            "high_price": [value * 1.01 for value in closes],
            "low_price": [value * 0.99 for value in closes],
            "close_price": closes,
            "volume": 1_000_000.0,
            "turnover": 100_000_000.0,
        }
    )
    confirmations = pd.DataFrame(
        [
            {
                "leader_date_mode": "two_strong_gain_top3",
                "leader_spell_id": "spell-a",
                "campaign_id": "campaign-a",
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "vt_symbol": "600001.SSE",
                "stock_name": "测试股票",
                "ignition_date": dates[5],
                "confirmation_date": dates[6],
                "confirmation_known_at": dates[6],
            }
        ]
    )

    row = build_leader_lifecycles(confirmations, bars).iloc[0]

    assert row["first_end_warning_date"] == dates[7]
    assert row["realized_peak_date"] == dates[9]
    assert row["end_warning_date"] == dates[10]
    assert row["end_confirmation_date"] == dates[11]


def test_continuation_truth_separates_recovery_from_terminal_failure() -> None:
    confirmations, bars = _truth_inputs()
    original = confirmations.copy(deep=True)

    truth = build_leader_continuation_truth(
        confirmations,
        bars,
        horizon_sessions=20,
    ).set_index("vt_symbol")

    assert bool(truth.loc["600001.SSE", "continued_after_pullback"])
    assert bool(truth.loc["600001.SSE", "later_higher_high"])
    assert not bool(truth.loc["600002.SSE", "continued_after_pullback"])
    assert truth.loc["600001.SSE", "truth_status"] == "complete"
    assert truth.loc["600002.SSE", "truth_status"] == "complete"
    assert truth.loc["600001.SSE", "d5_close_return_pct"] > 0
    assert truth.loc["600002.SSE", "d5_close_return_pct"] < 0
    pd.testing.assert_frame_equal(confirmations, original)


def test_mode_summary_uses_deterministic_five_date_blocks() -> None:
    rows: list[dict[str, object]] = []
    for index, confirmation_date in enumerate(
        pd.bdate_range("2025-01-02", periods=10)
    ):
        for mode in ("ignition_gain_top3", "two_strong_gain_top3"):
            rows.append(
                {
                    "leader_date_mode": mode,
                    "leader_spell_id": f"{mode}-{index}",
                    "confirmation_date": confirmation_date,
                    "confirmation_lag_sessions": 0 if "ignition" in mode else 1,
                    "ignition_limit_times": 1 if index % 2 else 3,
                    "truth_status": "complete",
                    "continued_after_pullback": index % 2 == 0,
                    "d5_close_return_pct": float(index - 4),
                    "future_max_return_pct": float(index + 1),
                    "future_max_drawdown_pct": float(-index),
                }
            )

    summary = summarize_leader_date_modes(pd.DataFrame(rows), block_count=5)

    assert set(summary["segment"]) == {
        "all",
        "block_1",
        "block_2",
        "block_3",
        "block_4",
        "block_5",
    }
    pooled = summary.loc[summary["segment"].eq("all")]
    assert pooled["spells"].eq(10).all()
    assert pooled["complete_truth_rows"].eq(10).all()
    assert pooled["continuation_after_pullback_rate_pct"].eq(50.0).all()


def test_concept_impulse_restarts_only_after_drawdown_and_new_anchor_edge() -> None:
    dates = pd.bdate_range("2026-01-02", periods=9)
    features = pd.DataFrame(
        {
            "sector_id": "BK0001",
            "concept_name": "测试概念",
            "trade_date": dates,
            "close_price": [100, 105, 101, 102, 106, 108, 102, 101, 100],
            "anchor_breakout_relative_turnover": [
                True,
                True,
                False,
                False,
                True,
                True,
                False,
                False,
                False,
            ],
        }
    )

    impulses = build_restart_aware_concept_impulses(features)

    assert impulses["anchor_date"].tolist() == [dates[0], dates[4]]
    assert impulses["end_date"].tolist() == [dates[3], dates[8]]
    assert impulses["end_reason"].tolist() == [
        "next_impulse_restart",
        "confirmed_running_peak_drawdown",
    ]


def test_concept_impulse_rejects_missing_anchor_state() -> None:
    features = pd.DataFrame(
        {
            "sector_id": ["BK0001"],
            "concept_name": ["测试概念"],
            "trade_date": [pd.Timestamp("2026-01-02")],
            "close_price": [100.0],
            "anchor_breakout_relative_turnover": [None],
        }
    )

    with pytest.raises(ValueError, match="anchors cannot be missing"):
        build_restart_aware_concept_impulses(features)


def test_outcome_groups_and_post_hoc_slice_keep_explicit_denominators() -> None:
    dates = pd.bdate_range("2025-01-02", periods=10)
    truth = pd.DataFrame(
        [
            {
                "leader_date_mode": "two_strong_gain_top3_early_phase",
                "leader_spell_id": f"spell-{index}",
                "confirmation_date": confirmation_date,
                "confirmation_gain_pct": 22.0 if index % 2 == 0 else 30.0,
                "confirmation_cohort_size": 5,
                "confirmation_causal_gain_rank": 2 if index % 2 == 0 else 1,
                "truth_status": "complete",
                "continued_after_pullback": index % 2 == 0,
                "d5_close_return_pct": 2.0 if index % 2 == 0 else -2.0,
                "future_max_return_pct": 20.0 if index % 2 == 0 else 5.0,
                "future_max_drawdown_pct": -10.0,
            }
            for index, confirmation_date in enumerate(dates)
        ]
    )

    profiles = summarize_leader_outcome_groups(truth)
    slices = summarize_exploratory_continuation_slice(truth, block_count=5)
    pooled_candidate = slices.loc[
        slices["segment"].eq("all")
        & slices["slice"].eq("gain_20_25_rank_2_3")
    ].iloc[0]

    assert profiles["spells"].tolist() == [5, 5]
    assert pooled_candidate["spells"] == 5
    assert pooled_candidate["continuation_after_pullback_rate_pct"] == 100.0
    assert pooled_candidate["d5_positive_share_pct"] == 100.0
    assert set(slices["segment"]) == {
        "all",
        "block_1",
        "block_2",
        "block_3",
        "block_4",
        "block_5",
    }


def test_report_keeps_restart_study_exploratory_and_renders_legacy_audit() -> None:
    audit = pd.DataFrame(
        [
            {
                "legacy_anchor_date": pd.Timestamp("2026-04-13"),
                "legacy_end_date": pd.Timestamp("2026-07-06"),
                "restart_aware_anchor_date": pd.Timestamp("2026-05-25"),
                "restart_aware_end_date": pd.Timestamp("2026-06-16"),
            }
        ]
    )
    report = build_daily_leader_spell_date_report(
        coverage={
            "membership_rows_read": 0,
            "minute_rows_read": 0,
            "fund_cycle_rows_read": 0,
            "prior_outcome_rows_read": 0,
        },
        fingerprints={},
        metrics=pd.DataFrame(),
        outcome_groups=pd.DataFrame(),
        exploratory_slice=pd.DataFrame(),
        spell_ledger=pd.DataFrame(),
        zhongjing=pd.DataFrame(),
        zhongjing_path=pd.DataFrame(),
        concept_restart_audit=audit,
    )

    payload = json.loads(render_daily_leader_spell_date_json(report))
    markdown = render_daily_leader_spell_date_markdown(report)

    assert payload["formal_metrics"] is None
    assert payload["formal_strategy"] is False
    assert payload["contract"]["restart_reset_drawdown_pct"] == 3.0
    assert "2026-04-13" in markdown
    assert "2026-05-25" in markdown
    assert "3% reset" in markdown


def test_cli_registers_daily_leader_spell_date_study() -> None:
    args = build_parser().parse_args(
        ["v2-daily-leader-spell-date-study", "--format", "json"]
    )

    assert args.command == "v2-daily-leader-spell-date-study"
    assert args.format == "json"


def _campaigns() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "campaign_id": "pcb-1",
                "sector_id": "BK0877",
                "concept_name": "PCB",
                "anchor_date": "2026-05-25",
                "end_date": "2026-05-28",
            }
        ]
    )


def _relations() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_date": "2026-05-25",
                "sector_id": "BK0877",
                "concept_name": "PCB",
                "vt_symbol": "002745.SZSE",
                "stock_name": "木林森",
                "limit_times": 1,
            },
            {
                "source_date": "2026-05-25",
                "sector_id": "BK0877",
                "concept_name": "PCB",
                "vt_symbol": "603256.SSE",
                "stock_name": "宏和科技",
                "limit_times": 2,
            },
            {
                "source_date": "2026-05-26",
                "sector_id": "BK0877",
                "concept_name": "PCB",
                "vt_symbol": "002579.SZSE",
                "stock_name": "中京电子",
                "limit_times": 1,
            },
            {
                "source_date": "2026-05-27",
                "sector_id": "BK0877",
                "concept_name": "PCB",
                "vt_symbol": "002579.SZSE",
                "stock_name": "中京电子",
                "limit_times": 2,
            },
        ]
    )


def _bars() -> pd.DataFrame:
    dates = pd.bdate_range("2026-05-22", "2026-06-10")
    closes = {
        "002579.SZSE": [
            13.46,
            13.67,
            15.04,
            16.54,
            18.19,
            17.15,
            18.87,
            20.76,
            19.45,
            20.61,
            18.69,
            16.82,
            16.74,
            15.82,
        ],
        "002745.SZSE": [
            9.84,
            10.82,
            10.46,
            11.00,
            10.80,
            10.60,
            10.40,
            10.20,
            10.00,
            9.80,
            9.60,
            9.40,
            9.20,
            9.00,
        ],
        "603256.SSE": [
            159.38,
            175.31,
            183.90,
            179.92,
            178.00,
            176.00,
            174.00,
            172.00,
            170.00,
            168.00,
            166.00,
            164.00,
            162.00,
            160.00,
        ],
    }
    rows: list[dict[str, object]] = []
    for symbol, values in closes.items():
        for trade_date, close in zip(dates, values, strict=True):
            rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "open_price": close * 0.99,
                    "high_price": close * 1.01,
                    "low_price": close * 0.98,
                    "close_price": close,
                    "volume": 1_000_000.0,
                    "turnover": 100_000_000.0,
                }
            )
    return pd.DataFrame(rows)


def _truth_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2025-01-02", periods=30)
    confirmation_date = dates[5]
    confirmations = pd.DataFrame(
        [
            {
                "leader_date_mode": "two_strong_gain_top3",
                "leader_spell_id": f"spell-{symbol}",
                "campaign_id": "campaign-a",
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "vt_symbol": symbol,
                "stock_name": symbol,
                "ignition_date": dates[4],
                "ignition_limit_times": 1,
                "confirmation_date": confirmation_date,
                "confirmation_known_at": confirmation_date,
                "confirmation_lag_sessions": 1,
                "confirmation_strong_closes": 2,
                "confirmation_gain_pct": 20.0,
                "confirmation_causal_gain_rank": rank,
                "confirmation_cohort_size": 3,
                "feature_cutoff_date": confirmation_date,
            }
            for rank, symbol in enumerate(("600001.SSE", "600002.SSE"), 1)
        ]
    )
    winner = [10.0] * 5 + [11.0, 12.0, 11.2, 12.5, 13.0, 13.5]
    loser = [10.0] * 5 + [11.0, 12.0, 11.0, 10.5, 10.0, 9.5]
    paths = {
        "600001.SSE": winner + [13.5 + index * 0.1 for index in range(19)],
        "600002.SSE": loser + [9.5 - index * 0.05 for index in range(19)],
    }
    rows: list[dict[str, object]] = []
    for symbol, closes in paths.items():
        for trade_date, close in zip(dates, closes, strict=True):
            rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "open_price": close,
                    "high_price": close * 1.01,
                    "low_price": close * 0.99,
                    "close_price": close,
                    "volume": 1_000_000.0,
                    "turnover": 100_000_000.0,
                }
            )
    return confirmations, pd.DataFrame(rows)
