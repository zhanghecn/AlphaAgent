from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from alphaagent.server.services.low_suction.prelaunch_first_explosion_study import (
    PrelaunchRule,
    apply_prelaunch_rule,
    attach_prelaunch_context,
    attach_verified_first_explosion_labels,
    build_prelaunch_first_explosion_report,
    discover_prelaunch_rule,
    evaluate_prelaunch_rule,
    execute_prelaunch_trade_gate,
    render_prelaunch_first_explosion_json,
    render_prelaunch_first_explosion_markdown,
    run_prelaunch_first_explosion_study,
)
from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.prelaunch_universe import PRELAUNCH_FEATURES
from alphaagent.server.services.low_suction import prelaunch_first_explosion_study as study


def _features(*, dates: tuple[date, ...] = (date(2025, 1, 6), date(2025, 1, 7))) -> pd.DataFrame:
    rows = []
    for entry_date in dates:
        for symbol_index in (1, 2):
            row = {feature: float(symbol_index) for feature in PRELAUNCH_FEATURES}
            row.update(
                {
                    "event_id": f"prelaunch:{entry_date}:60000{symbol_index}.SSE",
                    "context_date": entry_date - timedelta(days=3 if entry_date.weekday() == 0 else 1),
                    "entry_date": entry_date,
                    "feature_cutoff_date": entry_date
                    - timedelta(days=3 if entry_date.weekday() == 0 else 1),
                    "vt_symbol": f"60000{symbol_index}.SSE",
                    "symbol": f"60000{symbol_index}",
                    "exchange": "SSE",
                    "stock_name": f"测试{symbol_index}",
                    "security_evidence_level": "reconstructed_current_name",
                    "prior_sessions": 80,
                    "prior_strong_days_10d": 0,
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def _relations() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "source_date": date(2025, 1, 6),
                "sector_id": "BK0001",
                "concept_name": "活跃概念一",
                "vt_symbol": "600001.SSE",
            },
            {
                "event_id": 2,
                "source_date": date(2025, 1, 6),
                "sector_id": "BK0002",
                "concept_name": "活跃概念二",
                "vt_symbol": "600001.SSE",
            },
            {
                "event_id": 3,
                "source_date": date(2025, 1, 6),
                "sector_id": "BK0003",
                "concept_name": "非主升概念",
                "vt_symbol": "600002.SSE",
            },
            {
                "event_id": 4,
                "source_date": date(2025, 1, 7),
                "sector_id": "BK0001",
                "concept_name": "活跃概念一",
                "vt_symbol": "600001.SSE",
            },
        ]
    )


def _cycle_states() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "definition": "breakout_trend",
                "trade_date": date(2025, 1, 6),
                "sector_id": sector_id,
                "in_cycle": True,
                "cycle_id": f"cycle:{sector_id}",
            }
            for sector_id in ("BK0001", "BK0002")
        ]
        + [
            {
                "definition": "breakout_trend",
                "trade_date": date(2025, 1, 6),
                "sector_id": "BK0003",
                "in_cycle": False,
                "cycle_id": None,
            },
            {
                "definition": "breakout_trend",
                "trade_date": date(2025, 1, 7),
                "sector_id": "BK0001",
                "in_cycle": True,
                "cycle_id": "cycle:BK0001",
            },
        ]
    )


def _label_bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"vt_symbol": "600001.SSE", "trade_date": date(2025, 1, 3), "close_price": 10.0},
            {"vt_symbol": "600001.SSE", "trade_date": date(2025, 1, 6), "close_price": 10.6},
            {"vt_symbol": "600001.SSE", "trade_date": date(2025, 1, 7), "close_price": 10.7},
            {"vt_symbol": "600002.SSE", "trade_date": date(2025, 1, 3), "close_price": 10.0},
            {"vt_symbol": "600002.SSE", "trade_date": date(2025, 1, 6), "close_price": 10.7},
            {"vt_symbol": "600002.SSE", "trade_date": date(2025, 1, 7), "close_price": 10.8},
        ]
    )


def test_labels_require_exact_active_main_rise_relation_and_five_percent_d_return() -> None:
    labels = attach_verified_first_explosion_labels(
        _features(),
        _relations(),
        _cycle_states(),
        _label_bars(),
    ).set_index(["entry_date", "vt_symbol"])

    positive = labels.loc[(date(2025, 1, 6), "600001.SSE")]
    inactive = labels.loc[(date(2025, 1, 6), "600002.SSE")]
    weak = labels.loc[(date(2025, 1, 7), "600001.SSE")]

    assert bool(positive["verified_first_explosion"])
    assert positive["verified_concept_count"] == 2
    assert positive["verified_concept_names"] == "活跃概念一 | 活跃概念二"
    assert positive["d_return_pct"] == pytest.approx(6.0)
    assert not bool(inactive["verified_first_explosion"])
    assert inactive["label_status"] == "not_verified_by_available_event_evidence"
    assert not bool(weak["verified_first_explosion"])


def test_label_attachment_rejects_outcomes_inside_feature_input() -> None:
    with pytest.raises(ValueError, match="feature input"):
        attach_verified_first_explosion_labels(
            _features().assign(verified_first_explosion=True),
            _relations(),
            _cycle_states(),
            _label_bars(),
        )


def test_context_uses_entry_blocks_and_d1_market_timing_only() -> None:
    dates = tuple(date(2025, 1, 6) + timedelta(days=index) for index in range(5))
    features = _features(dates=dates)
    labels = attach_verified_first_explosion_labels(
        features,
        _relations(),
        _cycle_states(),
        _label_bars(),
    )
    timing = pd.DataFrame(
        [
            {
                "source_date": context_date,
                "active_direction": "GOLD" if index % 2 == 0 else "SILVER",
                "danger_state": "NORMAL",
                "market_phase": "launch",
            }
            for index, context_date in enumerate(
                sorted(pd.to_datetime(features["context_date"]).dt.date.unique())
            )
        ]
    )

    contextual = attach_prelaunch_context(labels, timing)

    assert set(contextual["block"]) == {1, 2, 3, 4, 5}
    assert contextual["market_regime"].isin({"GOLD/NORMAL", "SILVER/NORMAL"}).all()
    assert contextual["timing_source_date"].eq(contextual["context_date"]).all()


def _tree_labels(*, weaken_validation: bool = False) -> pd.DataFrame:
    rows = []
    for block in range(1, 6):
        block_start = date(2025, 1, 1) + timedelta(days=(block - 1) * 50)
        for index in range(4_000):
            rare_group = index < 400
            positive = (rare_group and index < 80) or (
                not rare_group and index % 100 == 0
            )
            if weaken_validation and block >= 4:
                positive = index % 200 == 0
            entry_date = block_start + timedelta(days=index % 40)
            row = {
                feature: float((index + feature_index) % 7) / 10.0
                for feature_index, feature in enumerate(PRELAUNCH_FEATURES)
            }
            row.update(
                {
                    "event_id": f"tree:{block}:{index}",
                    "context_date": entry_date - timedelta(days=1),
                    "entry_date": entry_date,
                    "feature_cutoff_date": entry_date - timedelta(days=1),
                    "vt_symbol": f"{600000 + index:06d}.SSE",
                    "return_1d_pct": 2.0 if rare_group else -1.0,
                    "verified_first_explosion": positive,
                    "label_status": (
                        "verified_active_main_rise_first_explosion"
                        if positive
                        else "not_verified_by_available_event_evidence"
                    ),
                    "block": block,
                    "market_regime": "GOLD/NORMAL",
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def test_discovery_tree_is_depth_two_and_persists_every_leaf_attempt() -> None:
    discovery = discover_prelaunch_rule(_tree_labels())

    assert discovery.model.get_depth() <= 2
    assert discovery.selected_rule is not None
    assert len(discovery.selected_rule.conditions) <= 2
    assert len(discovery.attempts) == discovery.model.get_n_leaves()
    assert sum(attempt.status == "selected" for attempt in discovery.attempts) == 1
    assert all(
        attempt.status == "selected" or attempt.rejection_reasons
        for attempt in discovery.attempts
    )


def test_validation_extremes_cannot_change_development_tree_thresholds() -> None:
    baseline = _tree_labels()
    changed = baseline.copy()
    changed.loc[changed["block"].ge(4), list(PRELAUNCH_FEATURES)] = 999.0

    original = discover_prelaunch_rule(baseline)
    repeated = discover_prelaunch_rule(changed)

    np.testing.assert_array_equal(
        original.model.tree_.threshold,
        repeated.model.tree_.threshold,
    )
    assert original.selected_rule == repeated.selected_rule


def test_frozen_leaf_passes_only_when_validation_label_gates_hold() -> None:
    good_labels = _tree_labels()
    discovery = discover_prelaunch_rule(good_labels)
    good = evaluate_prelaunch_rule(good_labels, discovery)
    weak_labels = _tree_labels(weaken_validation=True)
    weak = evaluate_prelaunch_rule(weak_labels, discovery)

    assert good["overall_conclusion"] == "validated_prelaunch_label_edge"
    assert good["trade_gate_passed"] is True
    assert good["validation_metrics"]["precision_lift"] >= 1.5
    assert weak["overall_conclusion"] == "prelaunch_label_validation_failed"
    assert weak["trade_gate_passed"] is False
    assert "precision_lift_below_1_5" in weak["failed_gates"]


def test_rule_application_is_a_frozen_conjunction() -> None:
    labels = _tree_labels()
    discovery = discover_prelaunch_rule(labels)
    assert isinstance(discovery.selected_rule, PrelaunchRule)

    selected = apply_prelaunch_rule(labels, discovery.selected_rule)

    assert selected["prelaunch_rule_match"].dtype == bool
    assert 0 < selected["prelaunch_rule_match"].sum() <= len(selected) * 0.10


def test_trade_outcomes_are_only_read_after_label_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[pd.DataFrame] = []

    def fake_execute(matches, _stock_bars, *, trading_dates):
        del trading_dates
        calls.append(matches.copy())
        normal = pd.DataFrame(
            {
                "event_id": matches["event_id"],
                "status": "closed",
                "net_return_pct": matches["verified_first_explosion"].map(
                    {True: 2.0, False: -1.0}
                ),
            }
        )
        stressed = normal.assign(net_return_pct=normal["net_return_pct"] - 0.2)
        return normal, stressed

    monkeypatch.setattr(study, "_execute_prelaunch_rule_hits", fake_execute)
    good_labels = _tree_labels()
    discovery = discover_prelaunch_rule(good_labels)
    good_evaluation = evaluate_prelaunch_rule(good_labels, discovery)
    completed = execute_prelaunch_trade_gate(
        good_labels,
        discovery,
        good_evaluation,
        pd.DataFrame(),
        trading_dates=(),
    )
    weak_labels = _tree_labels(weaken_validation=True)
    weak_evaluation = evaluate_prelaunch_rule(weak_labels, discovery)
    blocked = execute_prelaunch_trade_gate(
        weak_labels,
        discovery,
        weak_evaluation,
        pd.DataFrame(),
        trading_dates=(),
    )

    assert len(calls) == 1
    assert calls[0]["verified_first_explosion"].any()
    assert (~calls[0]["verified_first_explosion"]).any()
    assert completed["status"] == "completed_reused_history_diagnostic"
    assert completed["trade_outcomes_read"] is True
    assert completed["trade_metrics"]
    assert blocked["status"] == "not_run_label_gate_failed"
    assert blocked["trade_outcomes_read"] is False


def _report_parts():
    labels = _tree_labels(weaken_validation=True)
    discovery = discover_prelaunch_rule(labels)
    evaluation = evaluate_prelaunch_rule(labels, discovery)
    trade = {
        "status": "not_run_label_gate_failed",
        "trade_outcomes_read": False,
        "selected_rule_id": None,
        "trade_metrics": [],
    }
    metadata = {
        "coverage": {
            "target_dates": 200,
            "universe_rows": len(labels),
            "universe_symbols": labels["vt_symbol"].nunique(),
            "verified_positives": int(labels["verified_first_explosion"].sum()),
        },
        "input_fingerprints": {"prelaunch_labels": {"digest": "sha256:test"}},
        "discovery_start": date(2025, 1, 1),
        "discovery_end": date(2025, 12, 31),
    }
    return labels, discovery, evaluation, trade, metadata


def test_report_preserves_leaf_failures_label_noise_and_formal_nulls() -> None:
    report = build_prelaunch_first_explosion_report(*_report_parts())
    payload = render_prelaunch_first_explosion_json(report)
    markdown = render_prelaunch_first_explosion_markdown(report)

    assert len(report["leaf_attempts"]) == report["tree_leaf_count"]
    assert report["formal_metrics"] is None
    assert report["formal_rule_selected"] is False
    assert report["trade_outcomes_read"] is False
    assert report["outer_holdout_price_values_read"] is False
    assert '"formal_metrics": null' in payload
    assert "not_verified_by_available_event_evidence" in markdown
    assert "当前名称重建" in markdown
    assert "D 开盘到 D+1 收盘" in markdown
    assert "## 数据覆盖" in markdown
    assert "## 输入指纹" in markdown


def test_runner_and_cli_expose_no_tree_or_threshold_switches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        study,
        "load_prelaunch_first_explosion_study_data",
        lambda: _report_parts(),
    )

    report = run_prelaunch_first_explosion_study()
    args = build_parser().parse_args(
        ["v2-prelaunch-first-explosion-study", "--format", "json"]
    )

    assert report["study_track"] == "prelaunch_first_explosion_proxy"
    assert args.command == "v2-prelaunch-first-explosion-study"
    for name in ("depth", "min_samples", "threshold", "features", "rule"):
        assert not hasattr(args, name)
