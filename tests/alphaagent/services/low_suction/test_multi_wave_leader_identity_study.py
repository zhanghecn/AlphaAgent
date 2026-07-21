from __future__ import annotations

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.multi_wave_leader_identity_study import (
    MULTI_WAVE_FEATURES,
    MultiWaveIdentityCohort,
    assign_multi_wave_time_blocks,
    build_multi_wave_identity_report,
    build_multi_wave_feature_panel,
    build_multi_wave_identity_labels,
    discover_multi_wave_identity,
    evaluate_multi_wave_identity,
    evaluate_multi_wave_univariate,
    render_multi_wave_identity_json,
    render_multi_wave_identity_markdown,
)
from alphaagent.server.services.low_suction.cli import build_parser


def _episode(episode_id: str, symbol: str) -> dict[str, object]:
    return {
        "episode_id": episode_id,
        "cohort": "dynamic_causal_top3_proxy",
        "vt_symbol": symbol,
        "stock_name": f"股票-{symbol}",
        "anchor_date": pd.Timestamp("2025-01-02"),
        "observation_end": pd.Timestamp("2025-03-03"),
        "causal_rank": 1,
        "sector_id": "BK001",
        "concept_name": "测试概念",
        "time_block": "block_1",
        "cycle_id": f"cycle-{episode_id}",
    }


def _wave(
    episode_id: str,
    wave_number: int,
    status: str,
    *,
    higher_high_date: str | None,
    structural_break_date: str | None = None,
) -> dict[str, object]:
    first_wave = wave_number == 1
    return {
        "episode_id": episode_id,
        "wave_number": wave_number,
        "wave_start_date": pd.Timestamp("2025-01-02" if first_wave else "2025-01-20"),
        "peak_date": pd.Timestamp("2025-01-08" if first_wave else "2025-02-03"),
        "peak_price": 12.0 if first_wave else 14.0,
        "trough_date": pd.Timestamp("2025-01-13" if first_wave else "2025-02-10"),
        "trough_price": 10.8 if first_wave else 12.4,
        "pullback_pct": -10.0 if first_wave else -11.428571,
        "higher_high_date": (
            pd.Timestamp(higher_high_date) if higher_high_date is not None else pd.NaT
        ),
        "higher_high_price": 12.2 if higher_high_date is not None else None,
        "recovery_sessions": 5 if first_wave else 4,
        "trough_volume_ratio_5d": 0.7 if first_wave else 1.4,
        "deepest_tested_support": "ma5" if first_wave else "ma10",
        "trough_close_reclaimed_ma5": first_wave,
        "trough_close_reclaimed_ma10": True,
        "structural_break_date": (
            pd.Timestamp(structural_break_date)
            if structural_break_date is not None
            else pd.NaT
        ),
        "resolution_status": status,
        "observation_end": pd.Timestamp("2025-03-03"),
    }


def _impulse(episode_id: str, wave_number: int) -> dict[str, object]:
    return {
        "episode_id": episode_id,
        "wave_number": wave_number,
        "impulse_gain_pct": 20.0 if wave_number == 1 else 15.0,
        "strong_days_ge_9_5pct": 1 if wave_number == 1 else 3,
        "max_volume_ratio_prior5": 2.0 if wave_number == 1 else 9.0,
        "median_volume_ratio_prior5": 1.1 if wave_number == 1 else 4.0,
    }


def test_multi_wave_labels_use_first_rebreak_and_censor_unresolved_second_wave() -> None:
    episodes = pd.DataFrame(
        [
            _episode("continued", "600001.SSE"),
            _episode("terminal", "600002.SSE"),
            _episode("unresolved", "600003.SSE"),
        ]
    )
    waves = pd.DataFrame(
        [
            _wave(
                episode_id,
                1,
                "continued_to_higher_high",
                higher_high_date="2025-01-20",
            )
            for episode_id in ("continued", "terminal", "unresolved")
        ]
        + [
            _wave(
                "continued",
                2,
                "continued_to_higher_high",
                higher_high_date="2025-02-17",
            ),
            _wave(
                "terminal",
                2,
                "terminal_failure_observed",
                higher_high_date=None,
                structural_break_date="2025-02-14",
            ),
            _wave(
                "unresolved",
                2,
                "unresolved_pullback_censored",
                higher_high_date=None,
            ),
        ]
    )
    impulses = pd.DataFrame(
        [
            _impulse(episode_id, wave_number)
            for episode_id in ("continued", "terminal", "unresolved")
            for wave_number in (1, 2)
        ]
    )

    cohort = build_multi_wave_identity_labels(episodes, waves, impulses)

    assert cohort.labels["episode_id"].tolist() == ["continued", "terminal"]
    assert cohort.labels["multi_wave_leader"].tolist() == [True, False]
    assert cohort.labels["decision_date"].eq(pd.Timestamp("2025-01-20")).all()
    assert cohort.labels["feature_cutoff_date"].eq(cohort.labels["decision_date"]).all()
    assert cohort.labels["first_wave_gain_pct"].eq(20.0).all()
    assert cohort.censored[["episode_id", "second_wave_status"]].to_dict(
        "records"
    ) == [
        {
            "episode_id": "unresolved",
            "second_wave_status": "unresolved_pullback_censored",
        }
    ]


def test_wave_two_path_values_cannot_change_decision_features() -> None:
    episodes = pd.DataFrame([_episode("continued", "600001.SSE")])
    waves = pd.DataFrame(
        [
            _wave(
                "continued",
                1,
                "continued_to_higher_high",
                higher_high_date="2025-01-20",
            ),
            _wave(
                "continued",
                2,
                "continued_to_higher_high",
                higher_high_date="2025-02-17",
            ),
        ]
    )
    impulses = pd.DataFrame([_impulse("continued", 1), _impulse("continued", 2)])
    changed_waves = waves.copy()
    changed_waves.loc[changed_waves["wave_number"].eq(2), [
        "peak_price",
        "trough_price",
        "pullback_pct",
        "recovery_sessions",
        "trough_volume_ratio_5d",
    ]] = [999.0, 0.01, -99.0, 99, 99.0]
    changed_impulses = impulses.copy()
    changed_impulses.loc[changed_impulses["wave_number"].eq(2), [
        "impulse_gain_pct",
        "strong_days_ge_9_5pct",
        "max_volume_ratio_prior5",
        "median_volume_ratio_prior5",
    ]] = [999.0, 99, 99.0, 99.0]

    original = build_multi_wave_identity_labels(episodes, waves, impulses).labels
    changed = build_multi_wave_identity_labels(
        episodes,
        changed_waves,
        changed_impulses,
    ).labels

    pd.testing.assert_frame_equal(original, changed)


def _context_fixture() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    episodes = pd.DataFrame([_episode("continued", "600001.SSE")])
    waves = pd.DataFrame(
        [
            _wave(
                "continued",
                1,
                "continued_to_higher_high",
                higher_high_date="2025-01-20",
            ),
            _wave(
                "continued",
                2,
                "continued_to_higher_high",
                higher_high_date="2025-02-17",
            ),
        ]
    )
    impulses = pd.DataFrame([_impulse("continued", 1), _impulse("continued", 2)])
    labels = build_multi_wave_identity_labels(episodes, waves, impulses).labels
    dates = pd.bdate_range("2024-11-01", "2025-03-03")
    stock_rows = []
    for symbol_index, symbol in enumerate(
        ("600001.SSE", "600002.SSE", "000001.SZSE")
    ):
        for position, trade_date in enumerate(dates):
            close = 10.0 + symbol_index + position * (0.04 + symbol_index * 0.005)
            volume = 1000.0 + symbol_index * 100.0 + position * 10.0
            stock_rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "open_price": close - 0.02,
                    "high_price": close + 0.10,
                    "low_price": close - 0.10,
                    "close_price": close,
                    "volume": volume,
                    "turnover": close * volume,
                }
            )
    stock_bars = pd.DataFrame(stock_rows)
    concept_bars = pd.DataFrame(
        [
            {
                "sector_id": "BK001",
                "trade_date": trade_date,
                "close_price": 100.0 + position * 0.2,
                "turnover": 1_000_000.0 + position * 10_000.0,
            }
            for position, trade_date in enumerate(dates)
        ]
    )
    memberships = pd.DataFrame(
        [
            {"sector_id": "BK001", "vt_symbol": symbol}
            for symbol in ("600001.SSE", "600002.SSE", "000001.SZSE")
        ]
    )
    ranks = pd.DataFrame(
        [
            {
                "cycle_id": "cycle-continued",
                "vt_symbol": "600001.SSE",
                "trade_date": pd.Timestamp("2025-01-02"),
                "feature_cutoff_date": pd.Timestamp("2025-01-02"),
                "causal_rank": 1,
                "candidate_pool_size": 8,
            }
        ]
    )
    return labels, ranks, stock_bars, concept_bars, memberships


def test_feature_panel_is_complete_and_uses_current_proxy_member_breadth() -> None:
    labels, ranks, stock_bars, concept_bars, memberships = _context_fixture()

    panel = build_multi_wave_feature_panel(
        labels,
        ranks,
        stock_bars,
        concept_bars,
        memberships,
    )

    assert len(panel) == 1
    assert panel.iloc[0]["feature_complete"]
    assert panel.iloc[0]["feature_cutoff_date"] == pd.Timestamp("2025-01-20")
    assert panel.iloc[0]["first_trough_support_depth"] == 1.0
    assert panel.iloc[0]["breadth_member_count"] == 3
    assert panel.iloc[0]["member_positive_5d_breadth_pct"] == 100.0
    assert panel.iloc[0]["causal_rank"] == 1.0
    assert panel.iloc[0]["candidate_pool_size"] == 8.0
    assert pd.to_numeric(panel.loc[:, list(MULTI_WAVE_FEATURES)].iloc[0]).notna().all()


def test_post_decision_stock_and_concept_bars_cannot_change_features() -> None:
    labels, ranks, stock_bars, concept_bars, memberships = _context_fixture()
    original = build_multi_wave_feature_panel(
        labels,
        ranks,
        stock_bars,
        concept_bars,
        memberships,
    )
    changed_stocks = stock_bars.copy()
    future_stock = changed_stocks["trade_date"].gt(pd.Timestamp("2025-01-20"))
    for column in (
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
    ):
        changed_stocks.loc[future_stock, column] *= 10.0
    changed_concepts = concept_bars.copy()
    future_concept = changed_concepts["trade_date"].gt(pd.Timestamp("2025-01-20"))
    changed_concepts.loc[future_concept, ["close_price", "turnover"]] *= 10.0

    changed = build_multi_wave_feature_panel(
        labels,
        ranks,
        changed_stocks,
        changed_concepts,
        memberships,
    )

    compared = ["episode_id", "feature_cutoff_date", *MULTI_WAVE_FEATURES]
    pd.testing.assert_frame_equal(original[compared], changed[compared])


def test_feature_contract_contains_no_future_or_trade_outcome_fields() -> None:
    prohibited_tokens = (
        "second_wave",
        "future",
        "exit",
        "net_return",
        "trade_return",
        "gold",
        "silver",
    )

    assert not [
        feature
        for feature in MULTI_WAVE_FEATURES
        if any(token in feature for token in prohibited_tokens)
    ]


def _model_panel() -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2025-01-02", periods=5)
    for block_index, decision_date in enumerate(dates, start=1):
        for row_index in range(200):
            high_signal = row_index >= 100
            positive_limit = 80 if block_index <= 3 else 70
            low_positive_limit = 30 if block_index <= 3 else 40
            within_group = row_index - 100 if high_signal else row_index
            positive = within_group < (
                positive_limit if high_signal else low_positive_limit
            )
            row = {
                "episode_id": f"b{block_index}-{row_index:03d}",
                "decision_date": decision_date,
                "multi_wave_leader": positive,
                "feature_complete": True,
            }
            row.update(dict.fromkeys(MULTI_WAVE_FEATURES, 0.0))
            row["first_wave_gain_pct"] = 10.0 if high_signal else 0.0
            rows.append(row)
    return pd.DataFrame(rows)


def test_time_blocks_keep_every_decision_date_together() -> None:
    panel = assign_multi_wave_time_blocks(_model_panel())

    assert panel["block"].value_counts().sort_index().to_dict() == {
        1: 200,
        2: 200,
        3: 200,
        4: 200,
        5: 200,
    }
    assert panel.groupby("decision_date")["block"].nunique().eq(1).all()


def test_univariate_direction_is_frozen_on_development_blocks() -> None:
    panel = assign_multi_wave_time_blocks(_model_panel())

    metrics = evaluate_multi_wave_univariate(panel)
    gain = metrics.loc[metrics["feature"].eq("first_wave_gain_pct")].iloc[0]

    assert gain["direction"] == "higher"
    assert gain["development_directional_auc"] > 0.70
    assert gain["block_4_directional_auc"] > 0.60
    assert gain["block_5_directional_auc"] > 0.60
    changed = panel.copy()
    changed.loc[changed["block"].isin((4, 5)), "multi_wave_leader"] = ~changed.loc[
        changed["block"].isin((4, 5)), "multi_wave_leader"
    ]
    changed_gain = evaluate_multi_wave_univariate(changed).loc[
        lambda frame: frame["feature"].eq("first_wave_gain_pct")
    ].iloc[0]
    assert changed_gain["direction"] == gain["direction"]
    assert changed_gain["development_directional_auc"] == gain[
        "development_directional_auc"
    ]


def test_tree_freezes_one_development_leaf_without_validation_selection() -> None:
    panel = assign_multi_wave_time_blocks(_model_panel())

    discovery = discover_multi_wave_identity(panel)
    changed = panel.copy()
    changed.loc[changed["block"].isin((4, 5)), "multi_wave_leader"] = ~changed.loc[
        changed["block"].isin((4, 5)), "multi_wave_leader"
    ]
    changed_discovery = discover_multi_wave_identity(changed)

    assert discovery.development_base_rate_pct == pytest.approx(55.0)
    assert discovery.selected_rule is not None
    assert discovery.selected_rule == changed_discovery.selected_rule
    selected_attempt = next(
        attempt for attempt in discovery.attempts if attempt.selected
    )
    assert selected_attempt.precision_pct == pytest.approx(80.0)
    assert selected_attempt.precision_lift_pct_points == pytest.approx(25.0)
    assert selected_attempt.rows == 300


def test_frozen_leaf_passes_both_validation_blocks_only_at_registered_gates() -> None:
    panel = assign_multi_wave_time_blocks(_model_panel())
    discovery = discover_multi_wave_identity(panel)

    result = evaluate_multi_wave_identity(panel, discovery)

    assert result["overall_conclusion"] == "validated_multi_wave_identity_edge"
    assert result["identity_gate_passed"] is True
    assert result["selected_validation"]["rows"] == 200
    assert result["selected_validation"]["precision_pct"] == 70.0
    assert result["selected_validation"]["recall_pct"] > 60.0
    assert result["failed_gates"] == []
    assert [row["rows"] for row in result["validation_blocks"]] == [100, 100]
    assert [row["precision_pct"] for row in result["validation_blocks"]] == [70.0, 70.0]


def test_report_keeps_identity_metrics_separate_from_trade_performance() -> None:
    labels, _, _, _, _ = _context_fixture()
    cohort = MultiWaveIdentityCohort(labels=labels, censored=labels.iloc[0:0].copy())
    panel = assign_multi_wave_time_blocks(_model_panel())
    univariate = evaluate_multi_wave_univariate(panel)
    discovery = discover_multi_wave_identity(panel)
    validation = evaluate_multi_wave_identity(panel, discovery)

    report = build_multi_wave_identity_report(
        cohort=cohort,
        panel=panel,
        univariate=univariate,
        discovery=discovery,
        validation=validation,
        coverage={"strict_historical_membership_rows": 0},
        fingerprints={},
    )

    assert report["research_status"] == "validated_multi_wave_identity_edge"
    assert report["membership_evidence"] == "current_membership_and_security_proxy"
    assert report["formal_metrics"] == {
        "win_rate_pct": None,
        "compounded_return_pct": None,
        "profit_factor": None,
        "maximum_drawdown_pct": None,
    }
    assert report["identity_validation"]["trade_outcomes_read"] is False
    rendered_json = render_multi_wave_identity_json(report)
    rendered_markdown = render_multi_wave_identity_markdown(report)
    assert render_multi_wave_identity_json(report) == rendered_json
    assert '"formal_metrics"' in rendered_json
    assert "正式低吸胜率、收益、复利：`null`" in rendered_markdown


def test_cli_accepts_multi_wave_leader_identity_study() -> None:
    args = build_parser().parse_args(
        ["v2-multi-wave-leader-identity-study", "--format", "json"]
    )

    assert args.command == "v2-multi-wave-leader-identity-study"
    assert args.format == "json"
