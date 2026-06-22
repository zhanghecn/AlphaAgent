from __future__ import annotations

import json
import math
import os
import pickle
from collections import defaultdict
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text

from alphaagent.market.boards import stock_board
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope
from alphaagent.server.services.backtest import engine as backtest_engine
from alphaagent.server.services.backtest.factor_audit import CandidateCluster, IndependentTradeResult, simulate_independent_candidate_trade
from alphaagent.server.services.backtest.engine import list_backtests
from alphaagent.server.services.backtest.schemas import BacktestParams
from alphaagent.server.services.quant.factors import DRAGON_PULLBACK_STRATEGY_ID, Bar
from alphaagent.server.services.quant.low_suction_quality import low_suction_launch_quality_bucket


QUICK_WINDOW_DAYS = 80
QUICK_MAX_SYMBOLS = 120
FULL_MAX_SYMBOLS = 5_000
CANDIDATE_COHORT_TOP_N = 20
MIN_FULL_COMMON_COHORT_DATES = 20
NO_POSITION_SENTINEL_MAX_POSITIONS = 5_000
CANDIDATE_SNAPSHOT_CACHE_VERSION = 1
CANDIDATE_SNAPSHOT_CACHE_DIR = Path("memory/06_backtests/cache")


def test_current_strategy_quick_acceptance_uses_latest_data_window() -> None:
    """Fast strategy channel: recompute latest-window top20 candidate quality."""

    dates = _trading_dates_or_skip()
    start = _quick_start_date(dates)
    end = dates[-1]

    params = _candidate_quality_params(start=start, end=end, max_symbols=_quick_max_symbols())
    candidates, bars_by_symbol = _current_code_top_candidate_rows(params, top_n=CANDIDATE_COHORT_TOP_N)
    report = _candidate_path_report(candidates, bars_by_symbol, params, top_n=CANDIDATE_COHORT_TOP_N)

    assert candidates
    assert report["evaluated_count"] > 0
    assert report["daily"]
    summary = _candidate_metric_summary(report["rows"])
    assert _float_or_none(summary.get("average_return_pct")) is not None
    assert _float_or_none(summary.get("average_max_drawdown_pct")) is not None


def test_current_strategy_candidate_quality_matrix_report() -> None:
    """Explicit report channel for default-off candidate quality experiments."""

    if not _truthy_env("ALPHAAGENT_RUN_STRATEGY_MATRIX_REPORT"):
        pytest.skip("Set ALPHAAGENT_RUN_STRATEGY_MATRIX_REPORT=1 to print the candidate quality matrix.")

    dates = _trading_dates_or_skip()
    if _truthy_env("ALPHAAGENT_STRATEGY_MATRIX_FULL"):
        start = dates[0]
        max_symbols = _full_max_symbols()
        scope = "full"
    else:
        start = _quick_start_date(dates)
        max_symbols = _quick_max_symbols()
        scope = "quick"
    end = dates[-1]

    base_params = _candidate_quality_params(start=start, end=end, max_symbols=max_symbols)
    report = _candidate_quality_matrix_report(base_params, top_n=CANDIDATE_COHORT_TOP_N, scope=scope)

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    assert report["variants"]
    assert all(item["evaluated_count"] > 0 for item in report["variants"])


def test_current_strategy_candidate_quality_postprocess_report() -> None:
    """Explicit report channel for Top80 post-score candidate-quality experiments."""

    if not _truthy_env("ALPHAAGENT_RUN_STRATEGY_POSTPROCESS_REPORT"):
        pytest.skip("Set ALPHAAGENT_RUN_STRATEGY_POSTPROCESS_REPORT=1 to print the Top80 postprocess report.")

    dates = _trading_dates_or_skip()
    start = _quick_start_date(dates)
    end = dates[-1]
    base_params = _candidate_quality_params(start=start, end=end, max_symbols=_quick_max_symbols())
    report = _candidate_quality_postprocess_report(base_params, top_n=CANDIDATE_COHORT_TOP_N, pool_n=80)

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    assert report["variants"]
    assert all(item["overall"]["evaluated_count"] > 0 for item in report["variants"])


def test_current_strategy_candidate_factor_path_report() -> None:
    """Explicit report channel for why Top20 candidates surge or decline."""

    if not _truthy_env("ALPHAAGENT_RUN_CANDIDATE_FACTOR_PATH_REPORT"):
        pytest.skip("Set ALPHAAGENT_RUN_CANDIDATE_FACTOR_PATH_REPORT=1 to print the candidate factor path report.")

    dates = _trading_dates_or_skip()
    start = _quick_start_date(dates)
    end = dates[-1]
    params = _candidate_quality_params(start=start, end=end, max_symbols=_quick_max_symbols())
    pool_rows, bars_by_symbol = _current_code_top_candidate_rows_with_context(params, top_n=80)
    top_rows = [row for row in pool_rows if (_int_or_none(row.get("rank")) or 9999) <= CANDIDATE_COHORT_TOP_N]
    report = _candidate_path_report(top_rows, bars_by_symbol, params, top_n=CANDIDATE_COHORT_TOP_N)
    factor_report = _candidate_factor_path_report(
        report["rows"],
        pool_rows=pool_rows,
        top_n=CANDIDATE_COHORT_TOP_N,
    )

    print(json.dumps(factor_report, ensure_ascii=False, indent=2, default=str))
    assert factor_report["overall"]["evaluated_count"] > 0
    assert factor_report["surge_buckets"]
    assert factor_report["decline_buckets"]


def test_current_strategy_candidate_launch_path_report() -> None:
    """Explicit report channel for when candidates lift hard or fail after entry."""

    if not _truthy_env("ALPHAAGENT_RUN_CANDIDATE_LAUNCH_PATH_REPORT"):
        pytest.skip("Set ALPHAAGENT_RUN_CANDIDATE_LAUNCH_PATH_REPORT=1 to print the launch path report.")

    dates = _trading_dates_or_skip()
    start = _quick_start_date(dates)
    end = dates[-1]
    params = _candidate_quality_params(start=start, end=end, max_symbols=_quick_max_symbols())
    pool_rows, bars_by_symbol = _current_code_top_candidate_rows_with_context(params, top_n=80)
    top_rows = [row for row in pool_rows if (_int_or_none(row.get("rank")) or 9999) <= CANDIDATE_COHORT_TOP_N]
    report = _candidate_path_report(top_rows, bars_by_symbol, params, top_n=CANDIDATE_COHORT_TOP_N)
    launch_report = _candidate_launch_path_report(
        report["rows"],
        pool_rows=pool_rows,
        bars_by_symbol=bars_by_symbol,
        top_n=CANDIDATE_COHORT_TOP_N,
    )

    print(json.dumps(launch_report, ensure_ascii=False, indent=2, default=str))
    assert launch_report["overall"]["evaluated_count"] > 0
    assert launch_report["path_order_buckets"]
    assert launch_report["bad_setup_buckets"]


def test_current_strategy_candidate_stock_drilldown_report() -> None:
    """Explicit report channel for drilling from factor buckets into individual stocks."""

    if not _truthy_env("ALPHAAGENT_RUN_CANDIDATE_STOCK_DRILLDOWN_REPORT"):
        pytest.skip("Set ALPHAAGENT_RUN_CANDIDATE_STOCK_DRILLDOWN_REPORT=1 to print stock drilldown samples.")

    dates = _trading_dates_or_skip()
    start = _quick_start_date(dates)
    end = dates[-1]
    params = _candidate_quality_params(start=start, end=end, max_symbols=_quick_max_symbols())
    pool_rows, bars_by_symbol = _current_code_top_candidate_rows_with_context(params, top_n=80)
    top_rows = [row for row in pool_rows if (_int_or_none(row.get("rank")) or 9999) <= CANDIDATE_COHORT_TOP_N]
    report = _candidate_path_report(top_rows, bars_by_symbol, params, top_n=CANDIDATE_COHORT_TOP_N)
    drilldown = _candidate_stock_drilldown_report(
        report["rows"],
        pool_rows=pool_rows,
        bars_by_symbol=bars_by_symbol,
        top_n=CANDIDATE_COHORT_TOP_N,
        sample_limit=max(_int_env("ALPHAAGENT_STOCK_DRILLDOWN_SAMPLE_LIMIT", 5), 1),
    )

    print(json.dumps(drilldown, ensure_ascii=False, indent=2, default=str))
    assert drilldown["overall"]["evaluated_count"] > 0
    assert any(drilldown["samples"].values())


def test_current_strategy_postprocess_stock_audit_report() -> None:
    """Explicit report channel for stock-level postprocess removals/additions."""

    if not _truthy_env("ALPHAAGENT_RUN_POSTPROCESS_STOCK_AUDIT"):
        pytest.skip("Set ALPHAAGENT_RUN_POSTPROCESS_STOCK_AUDIT=1 to print postprocess stock audit samples.")

    dates = _trading_dates_or_skip()
    start = _quick_start_date(dates)
    end = dates[-1]
    params = _candidate_quality_params(start=start, end=end, max_symbols=_quick_max_symbols())
    report = _postprocess_stock_audit_report(
        params,
        top_n=CANDIDATE_COHORT_TOP_N,
        pool_n=80,
        sample_limit=max(_int_env("ALPHAAGENT_STOCK_DRILLDOWN_SAMPLE_LIMIT", 5), 1),
    )

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    assert report["variants"]
    assert any(item["samples"]["removed_worst"] or item["samples"]["added_best"] for item in report["variants"])


def test_current_strategy_full_acceptance_against_best_product_baseline() -> None:
    """Full strategy channel: compare no-position top20 candidate quality with the product baseline."""

    if not _truthy_env("ALPHAAGENT_RUN_FULL_STRATEGY_ACCEPTANCE"):
        pytest.skip("Set ALPHAAGENT_RUN_FULL_STRATEGY_ACCEPTANCE=1 to run the full strategy acceptance channel.")

    dates = _trading_dates_or_skip()
    start = dates[0]
    end = dates[-1]
    baseline = _best_product_baseline_or_skip()

    full_max_symbols = _full_max_symbols()
    params = _candidate_quality_params(start=start, end=end, max_symbols=full_max_symbols)
    candidate_comparison = _candidate_cohort_comparison_or_skip(
        current_params=params,
        baseline=baseline,
        start=start,
        end=end,
        top_n=CANDIDATE_COHORT_TOP_N,
    )
    _assert_candidate_cohort_comparable(candidate_comparison, limited=full_max_symbols < FULL_MAX_SYMBOLS)
    if full_max_symbols < FULL_MAX_SYMBOLS:
        assert candidate_comparison["common_candidate_day_count"] > 0
        return
    if _require_candidate_quality_gate():
        _assert_candidate_cohort_quality_gate_passed(candidate_comparison)
    else:
        _assert_candidate_cohort_not_materially_regressed(candidate_comparison)


def test_high_risk_d2_follow_through_entry_only_delays_high_risk_candidates() -> None:
    params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        enable_high_risk_d2_follow_through_entry=True,
        strict_entry=True,
        min_entry_score=76.0,
    )
    bars = _sample_follow_through_bars(d1_close=10.1, d1_change=1.0)

    normal_row = _candidate_path_row(_sample_candidate(close_location=0.52, low_suction_days=4), {"000001.SZSE": bars}, params)
    high_risk_row = _candidate_path_row(
        _sample_candidate(close_location=0.92, low_suction_days=7, launch_bucket="high_close_launch"),
        {"000001.SZSE": bars},
        params,
    )

    assert normal_row is not None
    assert high_risk_row is not None
    assert normal_row["entry_model"] == "legacy_next_open"
    assert normal_row["entry_execute_date"] == date(2026, 1, 2)
    assert high_risk_row["entry_model"] == "high_risk_d2_follow_through"
    assert high_risk_row["entry_execute_date"] == date(2026, 1, 5)


def test_high_risk_d2_follow_through_entry_rejects_failed_d1_confirmation() -> None:
    params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        enable_high_risk_d2_follow_through_entry=True,
        strict_entry=True,
        min_entry_score=76.0,
    )
    bars = _sample_follow_through_bars(d1_close=9.6, d1_change=-4.1)
    row = _candidate_path_row(
        _sample_candidate(close_location=0.92, low_suction_days=7, launch_bucket="high_close_launch"),
        {"000001.SZSE": bars},
        params,
    )

    assert row is not None
    assert row["entry_model"] == "high_risk_d2_follow_through"
    assert row["status"] == "d1_follow_through_failed"
    assert row["entry_execute_date"] == date(2026, 1, 2)
    assert row["return_pct"] is None


def test_candidate_path_marks_probable_unadjusted_price_discontinuity() -> None:
    params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
    )
    bars = [
        Bar(date(2026, 1, 1), 10.0, 10.2, 9.8, 10.0, change_pct=0.0),
        Bar(date(2026, 1, 2), 10.0, 10.3, 9.9, 10.1, change_pct=1.0),
        Bar(date(2026, 1, 5), 7.1, 7.4, 7.0, 7.3, change_pct=None),
        Bar(date(2026, 1, 6), 7.3, 7.6, 7.2, 7.5, change_pct=2.0),
    ]

    row = _candidate_path_row(
        _sample_candidate(close_location=0.45, low_suction_days=4),
        {"000001.SZSE": bars},
        params,
    )

    assert row is not None
    assert row["has_price_discontinuity"] is True
    assert row["first_price_discontinuity_date"] == date(2026, 1, 5)
    assert row["first_price_discontinuity_open_gap_pct"] < -20.0


def _candidate_quality_params(*, start: date, end: date, max_symbols: int) -> BacktestParams:
    # Candidate quality simulation only uses these params for scoring and sell
    # logic. Cash, position count, sizing and replacement are deliberately not
    # consulted by simulate_independent_candidate_trade().
    return BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=start,
        end=end,
        initial_cash=1_000_000,
        max_positions=NO_POSITION_SENTINEL_MAX_POSITIONS,
        max_position_pct=1.0,
        candidate_limit=CANDIDATE_COHORT_TOP_N,
        max_symbols=max_symbols,
        min_entry_score=76.0,
        strict_entry=True,
        execution_model="legacy_next_open",
        enable_signal_rotation=True,
        enable_candidate_tail_risk_penalty=_truthy_env("ALPHAAGENT_ENABLE_CANDIDATE_TAIL_RISK_PENALTY"),
        enable_mainline_momentum_lane=_truthy_env("ALPHAAGENT_ENABLE_MAINLINE_MOMENTUM_LANE"),
        enable_mainline_momentum_risk_control=_truthy_env("ALPHAAGENT_ENABLE_MAINLINE_MOMENTUM_RISK_CONTROL"),
        enable_mainline_momentum_hard_filter=_truthy_env("ALPHAAGENT_ENABLE_MAINLINE_MOMENTUM_HARD_FILTER"),
        enable_surge_quality_lane=_truthy_env("ALPHAAGENT_ENABLE_SURGE_QUALITY_LANE"),
        enable_top20_day_quality_gate=_truthy_env("ALPHAAGENT_ENABLE_TOP20_DAY_QUALITY_GATE"),
        enable_weekly_top_fractal_relief=_truthy_env("ALPHAAGENT_ENABLE_WEEKLY_TOP_FRACTAL_RELIEF"),
        enable_pure_loss_weak_bucket_penalty=_truthy_env("ALPHAAGENT_ENABLE_PURE_LOSS_WEAK_BUCKET_PENALTY"),
        enable_selective_setup_quality_lane=_truthy_env("ALPHAAGENT_ENABLE_SELECTIVE_SETUP_QUALITY_LANE"),
        enable_low_suction_buildup_quality_lane=_truthy_env("ALPHAAGENT_ENABLE_LOW_SUCTION_BUILDUP_QUALITY_LANE"),
        enable_high_risk_d2_follow_through_entry=_truthy_env("ALPHAAGENT_ENABLE_HIGH_RISK_D2_FOLLOW_THROUGH_ENTRY"),
        persist=False,
        reuse_signal_cache=False,
        exclude_from_product_baseline=True,
    )


def _sample_candidate(
    *,
    close_location: float,
    low_suction_days: int,
    launch_bucket: str = "balanced_first_lift",
) -> dict[str, Any]:
    return {
        "trade_date": date(2026, 1, 1),
        "vt_symbol": "000001.SZSE",
        "rank": 1,
        "total_score": 96.0,
        "reason": {
            "low_suction_launch_quality_bucket": launch_bucket,
            "close_location_in_range": close_location,
            "low_suction_days": low_suction_days,
            "ma_convergence_pct": 8.0,
            "large_bull_count_20d": 0,
            "near_limit_up_count_20d": 0,
            "recent_limit_up_20d": False,
            "volume_ratio_5d_20d": 1.0,
        },
    }


def _sample_follow_through_bars(*, d1_close: float, d1_change: float) -> list[Bar]:
    return [
        Bar(date(2026, 1, 1), 10.0, 10.2, 9.8, 10.0, change_pct=0.0),
        Bar(date(2026, 1, 2), 10.0, 10.4, 9.8, d1_close, change_pct=d1_change),
        Bar(date(2026, 1, 5), 10.2, 10.7, 10.0, 10.5, change_pct=2.5),
        Bar(date(2026, 1, 6), 10.5, 11.0, 10.4, 10.8, change_pct=2.8),
    ]


def _candidate_quality_matrix_report(base_params: BacktestParams, *, top_n: int, scope: str) -> dict[str, Any]:
    variant_specs = _candidate_quality_matrix_variants()
    rows_by_variant, bars_by_symbol = _current_code_top_candidate_matrix_rows(base_params, variant_specs, top_n=top_n)
    variants = []
    default_overall: dict[str, Any] | None = None
    for variant in variant_specs:
        item = _candidate_variant_report(
            base_params,
            rows_by_variant[str(variant["label"])],
            bars_by_symbol,
            top_n=top_n,
            **variant,
        )
        if variant["label"] == "default":
            default_overall = item["overall"]
        variants.append(item)
    if default_overall:
        for item in variants:
            item["vs_default"] = {
                "average_return_pct": _delta(item["overall"].get("average_return_pct"), default_overall.get("average_return_pct")),
                "win_rate": _delta(item["overall"].get("win_rate"), default_overall.get("win_rate")),
                "average_max_drawdown_pct": _delta(
                    item["overall"].get("average_max_drawdown_pct"),
                    default_overall.get("average_max_drawdown_pct"),
                ),
                "worst_max_drawdown_pct": _delta(
                    item["overall"].get("worst_max_drawdown_pct"),
                    default_overall.get("worst_max_drawdown_pct"),
                ),
            }
    return {
        "method": (
            "无仓位候选质量矩阵：每个候选日取 Top20，"
            "默认每只票独立 D+1 开盘入场，按当前卖点退出；"
            "带 entry 实验开关的 variant 会在对应字段中标明替代入场口径；"
            "不看现金、仓位、满仓、已有持仓或换仓。"
        ),
        "scope": scope,
        "start": base_params.start,
        "end": base_params.end,
        "max_symbols": base_params.max_symbols,
        "top_n": top_n,
        "variants": variants,
    }


def _candidate_quality_postprocess_report(base_params: BacktestParams, *, top_n: int, pool_n: int) -> dict[str, Any]:
    pool_rows, bars_by_symbol = _current_code_top_candidate_rows_with_context(base_params, top_n=pool_n)
    base_rows = [row for row in pool_rows if (_int_or_none(row.get("rank")) or 9999) <= top_n]
    base_keys = _candidate_identity_keys(base_rows)
    default_sell_params = base_params
    mfe_keep4_params = replace(
        base_params,
        enable_mid_profit_giveback_stop=True,
        mid_profit_giveback_min_high_gain_pct=0.08,
        mid_profit_giveback_max_current_gain_pct=0.04,
        mid_profit_giveback_drawdown_pct=0.06,
    )
    mfe_keep6_params = replace(
        base_params,
        enable_mid_profit_giveback_stop=True,
        mid_profit_giveback_min_high_gain_pct=0.08,
        mid_profit_giveback_max_current_gain_pct=0.06,
        mid_profit_giveback_drawdown_pct=0.05,
    )
    variant_specs = [
        {"label": "default_top20", "mode": "default", "sell_params": default_sell_params},
        {"label": "default_top20_mfe8_keep4_giveback6", "mode": "default", "sell_params": mfe_keep4_params},
        {"label": "default_top20_mfe8_keep6_giveback5", "mode": "default", "sell_params": mfe_keep6_params},
        {"label": "top80_quality_overlay", "mode": "top80_quality_overlay", "sell_params": default_sell_params},
        {"label": "top80_quality_overlay_mfe8_keep4_giveback6", "mode": "top80_quality_overlay", "sell_params": mfe_keep4_params},
        {"label": "top80_gentle_overlay_mfe8_keep4_giveback6", "mode": "top80_gentle_overlay", "sell_params": mfe_keep4_params},
        {"label": "top80_strict_overlay_mfe8_keep4_giveback6", "mode": "top80_strict_overlay", "sell_params": mfe_keep4_params},
        {"label": "weak_day_cap10_overlay_mfe8_keep4_giveback6", "mode": "weak_day_cap10_overlay", "sell_params": mfe_keep4_params},
        {"label": "weak_day_cap10_overlay_mfe8_keep6_giveback5", "mode": "weak_day_cap10_overlay", "sell_params": mfe_keep6_params},
        {"label": "weak_day_cap5_overlay_mfe8_keep4_giveback6", "mode": "weak_day_cap5_overlay", "sell_params": mfe_keep4_params},
        {"label": "v2_cap10_overlay_mfe8_keep6_giveback5", "mode": "v2_cap10_overlay", "sell_params": mfe_keep6_params},
        {"label": "v2_cap8_overlay_mfe8_keep6_giveback5", "mode": "v2_cap8_overlay", "sell_params": mfe_keep6_params},
        {"label": "v3_support_lift_cap10_mfe8_keep6_giveback5", "mode": "v3_support_lift_cap10", "sell_params": mfe_keep6_params},
        {"label": "v3_support_lift_cap8_mfe8_keep6_giveback5", "mode": "v3_support_lift_cap8", "sell_params": mfe_keep6_params},
        {"label": "v4_launch_quality_cap10_mfe8_keep6_giveback5", "mode": "v4_launch_quality_cap10", "sell_params": mfe_keep6_params},
        {"label": "v4_launch_quality_cap8_mfe8_keep6_giveback5", "mode": "v4_launch_quality_cap8", "sell_params": mfe_keep6_params},
        {"label": "v5_v2_lift_guard_cap10_mfe8_keep6_giveback5", "mode": "v5_v2_lift_guard_cap10", "sell_params": mfe_keep6_params},
        {"label": "v5_v2_lift_guard_cap8_mfe8_keep6_giveback5", "mode": "v5_v2_lift_guard_cap8", "sell_params": mfe_keep6_params},
        {"label": "v6_v2_right_tail_guard_cap8_mfe8_keep6_giveback5", "mode": "v6_v2_right_tail_guard_cap8", "sell_params": mfe_keep6_params},
        {"label": "v7_v2_soft_right_tail_cap8_mfe8_keep6_giveback5", "mode": "v7_v2_soft_right_tail_cap8", "sell_params": mfe_keep6_params},
    ]
    path_cache: dict[tuple[tuple[Any, ...], date, str], dict[str, Any] | None] = {}
    base_reports_by_sell_key = {
        _postprocess_sell_key(default_sell_params): _candidate_path_report_cached(
            base_rows,
            bars_by_symbol,
            default_sell_params,
            top_n=top_n,
            path_cache=path_cache,
        ),
        _postprocess_sell_key(mfe_keep4_params): _candidate_path_report_cached(
            base_rows,
            bars_by_symbol,
            mfe_keep4_params,
            top_n=top_n,
            path_cache=path_cache,
        ),
        _postprocess_sell_key(mfe_keep6_params): _candidate_path_report_cached(
            base_rows,
            bars_by_symbol,
            mfe_keep6_params,
            top_n=top_n,
            path_cache=path_cache,
        ),
    }
    variants = []
    default_overall: dict[str, Any] | None = None
    for spec in variant_specs:
        mode = str(spec["mode"])
        rows = (
            [dict(row) | {"source": "postprocess_default_top20"} for row in base_rows]
            if mode == "default"
            else _postprocess_candidate_pool(pool_rows, top_n=top_n, mode=mode)
        )
        report = (
            base_reports_by_sell_key[_postprocess_sell_key(spec["sell_params"])]
            if mode == "default"
            else _candidate_path_report_cached(
                rows,
                bars_by_symbol,
                spec["sell_params"],
                top_n=top_n,
                path_cache=path_cache,
            )
        )
        dates = sorted(report["daily"])
        item = {
            "label": spec["label"],
            "mode": mode,
            "candidate_count": report["candidate_count"],
            "candidate_day_count": len(report["daily"]),
            "overall": _candidate_overall_for_dates(report, dates),
            "overall_without_price_discontinuity": _candidate_overall_for_dates(
                _candidate_report_without_price_discontinuity(report),
                dates,
            ),
            "data_quality": _candidate_path_data_quality(report["rows"]),
            "changes_vs_default_top20": _postprocess_change_summary(
                base_keys=base_keys,
                variant_rows=rows,
                base_report=base_reports_by_sell_key[_postprocess_sell_key(spec["sell_params"])],
                variant_report=report,
            ),
        }
        if spec["label"] == "default_top20":
            default_overall = item["overall"]
        variants.append(item)

    if default_overall:
        for item in variants:
            item["vs_default_top20"] = {
                "average_return_pct": _delta(item["overall"].get("average_return_pct"), default_overall.get("average_return_pct")),
                "win_rate": _delta(item["overall"].get("win_rate"), default_overall.get("win_rate")),
                "average_max_drawdown_pct": _delta(
                    item["overall"].get("average_max_drawdown_pct"),
                    default_overall.get("average_max_drawdown_pct"),
                ),
                "worst_max_drawdown_pct": _delta(
                    item["overall"].get("worst_max_drawdown_pct"),
                    default_overall.get("worst_max_drawdown_pct"),
                ),
            }

    return {
        "method": (
            "测试通道 Top80 后处理：先按当前代码取每个候选日 Top80，"
            "只用信号日已存在 evidence 做质量重排或坏日压缩，再取 Top20/Top10/Top5 独立模拟；"
            "不改变真实策略评分、买卖、仓位或缓存；"
            "data_quality/overall_without_price_discontinuity 只用于审计疑似未复权价格断层。"
        ),
        "start": base_params.start,
        "end": base_params.end,
        "max_symbols": base_params.max_symbols,
        "pool_n": pool_n,
        "top_n": top_n,
        "variants": variants,
    }


def _candidate_factor_path_report(rows: list[dict[str, Any]], *, pool_rows: list[dict[str, Any]], top_n: int) -> dict[str, Any]:
    evaluated = [row for row in rows if _is_evaluated_candidate_path(row)]
    clean_rows = [row for row in evaluated if not row.get("has_price_discontinuity")]
    analysis_rows = clean_rows or evaluated
    day_profiles = {
        trade_date: _postprocess_day_profile(sorted_rows[:top_n])
        for trade_date, sorted_rows in _candidate_rows_grouped_by_day(pool_rows).items()
    }
    enriched = [_candidate_factor_path_enriched_row(row, day_profiles=day_profiles) for row in analysis_rows]
    weak_days = _candidate_day_profile_outcome(enriched, day_profiles=day_profiles, strong=False)
    strong_days = _candidate_day_profile_outcome(enriched, day_profiles=day_profiles, strong=True)
    return {
        "method": (
            "显式测试通道：每个候选日取当前重算 Top20，D+1 开盘独立入场，按当前卖点退出；"
            "只用信号日可见 evidence 分桶解释后验路径，后验标签不进入真实策略。"
        ),
        "top_n": top_n,
        "overall": _candidate_factor_metric_summary(enriched),
        "data_quality": _candidate_path_data_quality(evaluated),
        "surge_definition": "max_runup_pct >= 8 或 return_pct >= 8",
        "decline_definition": "return_pct <= -5 或 max_drawdown_pct <= -8",
        "pure_loss_definition": "max_runup_pct < 3 且 return_pct < 0",
        "giveback_definition": "max_runup_pct >= 8 且 return_pct <= 0",
        "surge_buckets": _candidate_top_factor_buckets(enriched, mode="surge"),
        "decline_buckets": _candidate_top_factor_buckets(enriched, mode="decline"),
        "pure_loss_buckets": _candidate_top_factor_buckets(enriched, mode="pure_loss"),
        "giveback_buckets": _candidate_top_factor_buckets(enriched, mode="giveback"),
        "factor_pairs": _candidate_factor_pair_buckets(enriched),
        "day_profiles": {
            "weak_day": weak_days,
            "strong_day": strong_days,
        },
        "worst_samples": _candidate_factor_samples(enriched, mode="worst", limit=12),
        "surge_samples": _candidate_factor_samples(enriched, mode="surge", limit=12),
        "inference": [
            "猛拉更像活跃资金在低/中低收盘区的支撑抬升，而不是单纯突破5日线。",
            "买后下跌集中在高收盘弱启动、低吸过久但缺少新激活、均线过紧且缺活跃资金，以及弱候选日的拥挤高位票。",
            "低吸蓄势本身不应被扣分；需要扣的是没有活跃资金或 fresh lift 的 6-10 天滞涨低吸。",
            "行情线只能做交互项；false_bull 或 warning 不能单独一刀切。",
        ],
    }


def _candidate_stock_drilldown_report(
    rows: list[dict[str, Any]],
    *,
    pool_rows: list[dict[str, Any]],
    bars_by_symbol: dict[str, list[Bar]],
    top_n: int,
    sample_limit: int,
) -> dict[str, Any]:
    evaluated = [row for row in rows if _is_evaluated_candidate_path(row)]
    clean_rows = [row for row in evaluated if not row.get("has_price_discontinuity")]
    analysis_rows = clean_rows or evaluated
    day_profiles = {
        trade_date: _postprocess_day_profile(sorted_rows[:top_n])
        for trade_date, sorted_rows in _candidate_rows_grouped_by_day(pool_rows).items()
    }
    enriched = [_candidate_factor_path_enriched_row(row, day_profiles=day_profiles) for row in analysis_rows]
    samples = {
        "surge": _candidate_stock_drilldown_samples(enriched, bars_by_symbol, kind="surge", limit=sample_limit),
        "worst_loss": _candidate_stock_drilldown_samples(enriched, bars_by_symbol, kind="worst_loss", limit=sample_limit),
        "pure_loss": _candidate_stock_drilldown_samples(enriched, bars_by_symbol, kind="pure_loss", limit=sample_limit),
        "giveback": _candidate_stock_drilldown_samples(enriched, bars_by_symbol, kind="giveback", limit=sample_limit),
    }
    return {
        "method": (
            "显式个股钻取通道：从同一 Top20 独立候选路径中抽取强拉、深亏、纯亏、冲高回吐样本；"
            "展示信号日可见因子、行情/资金上下文、MA/压力位和入场后 K 线路径；只读，不进入评分。"
        ),
        "top_n": top_n,
        "overall": _candidate_factor_metric_summary(enriched),
        "data_quality": _candidate_path_data_quality(evaluated),
        "sample_limit": sample_limit,
        "samples": samples,
        "how_to_read": [
            "signal_bar 是 D 日收盘后可见状态；entry_window 从 D+1 执行日起看路径。",
            "resistance 用信号日前 20 日高点、pivot_high_20d 和入场后首次触及位置近似，帮助判断承压位。",
            "fund_flow / smart_money / hot_rank / lhb 是可见代理指标，不等于真实主力意图。",
        ],
    }


def _postprocess_stock_audit_report(
    base_params: BacktestParams,
    *,
    top_n: int,
    pool_n: int,
    sample_limit: int,
) -> dict[str, Any]:
    pool_rows, bars_by_symbol = _current_code_top_candidate_rows_with_context(base_params, top_n=pool_n)
    base_rows = [row for row in pool_rows if (_int_or_none(row.get("rank")) or 9999) <= top_n]
    base_keys = _candidate_identity_keys(base_rows)
    mfe_keep6_params = replace(
        base_params,
        enable_mid_profit_giveback_stop=True,
        mid_profit_giveback_min_high_gain_pct=0.08,
        mid_profit_giveback_max_current_gain_pct=0.06,
        mid_profit_giveback_drawdown_pct=0.05,
    )
    specs = [
        {"label": "v2_cap8_overlay_mfe8_keep6_giveback5", "mode": "v2_cap8_overlay"},
        {"label": "v5_v2_lift_guard_cap8_mfe8_keep6_giveback5", "mode": "v5_v2_lift_guard_cap8"},
    ]
    path_cache: dict[tuple[tuple[Any, ...], date, str], dict[str, Any] | None] = {}
    base_report = _candidate_path_report_cached(
        base_rows,
        bars_by_symbol,
        mfe_keep6_params,
        top_n=top_n,
        path_cache=path_cache,
    )
    day_profiles = {
        trade_date: _postprocess_day_profile(sorted_rows[:top_n])
        for trade_date, sorted_rows in _candidate_rows_grouped_by_day(pool_rows).items()
    }
    variants = []
    for spec in specs:
        variant_rows = _postprocess_candidate_pool(pool_rows, top_n=top_n, mode=str(spec["mode"]))
        variant_report = _candidate_path_report_cached(
            variant_rows,
            bars_by_symbol,
            mfe_keep6_params,
            top_n=top_n,
            path_cache=path_cache,
        )
        variant_keys = _candidate_identity_keys(variant_rows)
        removed_keys = base_keys - variant_keys
        added_keys = variant_keys - base_keys
        removed_rows = [
            row
            for row in base_report["rows"]
            if (_as_date(row.get("signal_date")), str(row.get("vt_symbol") or "").strip().upper()) in removed_keys
        ]
        added_rows = [
            row
            for row in variant_report["rows"]
            if (_as_date(row.get("signal_date")), str(row.get("vt_symbol") or "").strip().upper()) in added_keys
        ]
        variants.append(
            {
                "label": spec["label"],
                "mode": spec["mode"],
                "overall": _candidate_factor_metric_summary(
                    [
                        _candidate_factor_path_enriched_row(row, day_profiles=day_profiles)
                        for row in variant_report["rows"]
                        if not row.get("has_price_discontinuity")
                    ]
                ),
                "changes": {
                    "removed_count": len(removed_keys),
                    "added_count": len(added_keys),
                    "removed_quality": _candidate_metric_summary(removed_rows),
                    "added_quality": _candidate_metric_summary(added_rows),
                },
                "factor_buckets": {
                    "removed": _postprocess_change_factor_buckets(removed_rows, day_profiles=day_profiles),
                    "added": _postprocess_change_factor_buckets(added_rows, day_profiles=day_profiles),
                },
                "samples": {
                    "removed_worst": _postprocess_change_stock_samples(
                        removed_rows,
                        bars_by_symbol,
                        day_profiles=day_profiles,
                        mode="worst",
                        limit=sample_limit,
                    ),
                    "removed_best_missed": _postprocess_change_stock_samples(
                        removed_rows,
                        bars_by_symbol,
                        day_profiles=day_profiles,
                        mode="best",
                        limit=sample_limit,
                    ),
                    "added_best": _postprocess_change_stock_samples(
                        added_rows,
                        bars_by_symbol,
                        day_profiles=day_profiles,
                        mode="best",
                        limit=sample_limit,
                    ),
                    "added_worst": _postprocess_change_stock_samples(
                        added_rows,
                        bars_by_symbol,
                        day_profiles=day_profiles,
                        mode="worst",
                        limit=sample_limit,
                    ),
                },
            }
        )
    return {
        "method": (
            "测试通道个股对照：以 default Top20 + mfe8_keep6 为参照，"
            "查看 V2/V5 后处理从同一候选日移除和替换了哪些股票；"
            "样本展示信号日因子、资金/行情代理、MA/压力位和入场后路径。只读，不进入真实策略。"
        ),
        "start": base_params.start,
        "end": base_params.end,
        "max_symbols": base_params.max_symbols,
        "top_n": top_n,
        "pool_n": pool_n,
        "base_overall": _candidate_factor_metric_summary(
            [
                _candidate_factor_path_enriched_row(row, day_profiles=day_profiles)
                for row in base_report["rows"]
                if not row.get("has_price_discontinuity")
            ]
        ),
        "base_data_quality": _candidate_path_data_quality(base_report["rows"]),
        "sample_limit": sample_limit,
        "variants": variants,
        "inference": [
            "V2/V5 的收益变化要看 removed 和 added 的质量差，而不是只看总收益。",
            "如果 added 仍是负收益，说明后处理只是删掉坏票，还没有找到足够好的替换票。",
            "若 removed_best_missed 很强，说明规则误伤了右尾赢家，需要从个股因子中找保护条件。",
        ],
    }


def _postprocess_change_factor_buckets(
    rows: list[dict[str, Any]],
    *,
    day_profiles: dict[date, dict[str, Any]],
    min_count: int = 5,
    limit: int = 12,
) -> list[dict[str, Any]]:
    enriched = [
        _candidate_factor_path_enriched_row(row, day_profiles=day_profiles)
        for row in rows
        if _is_evaluated_candidate_path(row) and not row.get("has_price_discontinuity")
    ]
    factor_keys = [
        "candidate_shape",
        "launch_bucket",
        "close_bucket",
        "ma5_distance_bucket",
        "low_suction_days_bucket",
        "active_bucket",
        "day_shape",
        "market_regime",
    ]
    buckets: list[dict[str, Any]] = []
    for key in factor_keys:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in enriched:
            grouped[str(row.get(key) or "unknown")].append(row)
        for value, bucket_rows in grouped.items():
            if len(bucket_rows) < min_count:
                continue
            buckets.append({"factor": key, "value": value, **_candidate_factor_metric_summary(bucket_rows)})
    return sorted(
        buckets,
        key=lambda item: (
            _float_or_none(item.get("average_return_pct")) if _float_or_none(item.get("average_return_pct")) is not None else 999.0,
            _float_or_none(item.get("average_max_drawdown_pct")) or 0.0,
            -int(item.get("evaluated_count") or 0),
        ),
    )[:limit]


def _postprocess_change_stock_samples(
    rows: list[dict[str, Any]],
    bars_by_symbol: dict[str, list[Bar]],
    *,
    day_profiles: dict[date, dict[str, Any]],
    mode: str,
    limit: int,
) -> list[dict[str, Any]]:
    enriched = [
        _candidate_launch_path_enriched_row(
            row,
            bars_by_symbol.get(str(row.get("vt_symbol") or "").strip().upper(), []),
            day_profiles=day_profiles,
        )
        for row in rows
        if _is_evaluated_candidate_path(row) and not row.get("has_price_discontinuity")
    ]
    if mode == "best":
        selected = sorted(
            enriched,
            key=lambda row: (
                _float_or_none(row.get("return_pct")) or -999.0,
                _float_or_none(row.get("max_runup_pct")) or -999.0,
            ),
            reverse=True,
        )
    else:
        selected = sorted(
            enriched,
            key=lambda row: (
                _float_or_none(row.get("return_pct")) if _float_or_none(row.get("return_pct")) is not None else 999.0,
                _float_or_none(row.get("max_drawdown_pct")) or 0.0,
            ),
        )
    samples = []
    seen: set[tuple[str, date | None]] = set()
    for row in selected:
        symbol = str(row.get("vt_symbol") or "").strip().upper()
        signal_date = _as_date(row.get("signal_date"))
        key = (symbol, signal_date)
        if not symbol or key in seen:
            continue
        seen.add(key)
        samples.append(
            _candidate_stock_drilldown_row(row, bars_by_symbol.get(symbol, []))
            | {
                "postprocess_labels": {
                    "path_order": row.get("path_order"),
                    "support_lift_signature": row.get("support_lift_signature"),
                    "setup_failure_signature": row.get("setup_failure_signature"),
                    "active_strength": row.get("active_strength"),
                    "fresh_lift": row.get("fresh_lift"),
                    "latest_change_bucket": row.get("latest_change_bucket"),
                    "ma5_slope_bucket": row.get("ma5_slope_bucket"),
                }
            }
        )
        if len(samples) >= limit:
            break
    return samples


def _candidate_launch_path_report(
    rows: list[dict[str, Any]],
    *,
    pool_rows: list[dict[str, Any]],
    bars_by_symbol: dict[str, list[Bar]],
    top_n: int,
) -> dict[str, Any]:
    evaluated = [row for row in rows if _is_evaluated_candidate_path(row)]
    clean_rows = [row for row in evaluated if not row.get("has_price_discontinuity")]
    analysis_rows = clean_rows or evaluated
    day_profiles = {
        trade_date: _postprocess_day_profile(sorted_rows[:top_n])
        for trade_date, sorted_rows in _candidate_rows_grouped_by_day(pool_rows).items()
    }
    enriched = [
        _candidate_launch_path_enriched_row(row, bars_by_symbol.get(str(row.get("vt_symbol") or "").strip().upper(), []), day_profiles=day_profiles)
        for row in analysis_rows
    ]
    fast_lift_rows = [row for row in enriched if row.get("path_order") in {"up8_before_down3", "up5_before_down3"}]
    early_fail_rows = [row for row in enriched if row.get("path_order") in {"down3_before_up5", "down5_before_up8"}]
    return {
        "method": (
            "显式测试通道：每个候选日取当前 Top20，D+1 开盘独立入场，"
            "只用入场后 K 线做路径标签、只用信号日 evidence 做原因分桶；"
            "路径标签只用于研究，不进入真实评分、买卖或仓位。"
        ),
        "top_n": top_n,
        "overall": _candidate_launch_metric_summary(enriched),
        "data_quality": _candidate_path_data_quality(evaluated),
        "path_order_definition": {
            "up8_before_down3": "入场后先触发 +8% 高点，且在此之前未先跌破 -3%",
            "up5_before_down3": "入场后先触发 +5% 高点，且在此之前未先跌破 -3%",
            "down3_before_up5": "入场后先跌破 -3%，且在此之前未先触发 +5%",
            "down5_before_up8": "入场后先跌破 -5%，且在此之前未先触发 +8%",
        },
        "path_order_buckets": _candidate_launch_group_buckets(enriched, ("path_order",), min_count=10, limit=12),
        "fast_lift_factor_buckets": _candidate_launch_factor_buckets(fast_lift_rows, min_count=8, limit=18),
        "early_fail_factor_buckets": _candidate_launch_factor_buckets(early_fail_rows, min_count=8, limit=18),
        "bad_setup_buckets": _candidate_launch_group_buckets(
            enriched,
            ("setup_failure_signature",),
            min_count=10,
            limit=16,
            sort_mode="bad",
        ),
        "support_lift_buckets": _candidate_launch_group_buckets(
            enriched,
            ("support_lift_signature",),
            min_count=10,
            limit=16,
            sort_mode="good",
        ),
        "factor_cross_buckets": _candidate_launch_group_buckets(
            enriched,
            ("support_lift_signature", "setup_failure_signature"),
            min_count=8,
            limit=18,
            sort_mode="spread",
        ),
        "daily_weak_samples": _candidate_launch_daily_samples(enriched, strong=False, limit=10),
        "daily_strong_samples": _candidate_launch_daily_samples(enriched, strong=True, limit=10),
        "fast_lift_samples": _candidate_launch_samples(fast_lift_rows, mode="fast_lift", limit=12),
        "early_fail_samples": _candidate_launch_samples(early_fail_rows, mode="early_fail", limit=12),
        "inference": [
            "低吸很多天不是问题，问题是低吸后没有 fresh lift、没有活跃资金、或同日 Top20 已经是高位弱启动拥挤。",
            "启动不只是突破 MA5；更有效的信号是 D 日仍贴近 MA5/MA10，MA5 开始上拐，收盘位置可控，并且近期有活跃资金痕迹。",
            "买后快速下跌多来自高收盘弱启动、远离 MA5、6-10 天滞涨低吸、极窄均线无激活，以及 false_bull/warning 与弱 setup 的叠加。",
            "高 MFE 后回吐需要单独卖点保护；不要用卖点问题掩盖候选纯亏问题。",
        ],
    }


def _candidate_launch_path_enriched_row(
    row: dict[str, Any],
    bars: list[Bar],
    *,
    day_profiles: dict[date, dict[str, Any]],
) -> dict[str, Any]:
    base = _candidate_factor_path_enriched_row(row, day_profiles=day_profiles)
    evidence = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    features = _postprocess_candidate_features(row)
    path = _candidate_entry_path_profile(row, bars)
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ma5_slope = _float_or_none(evidence.get("ma5_slope_pct"))
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    active_strength = _candidate_active_strength(evidence)
    fresh_lift = _candidate_fresh_lift(features, latest_change=latest_change, ma5_slope=ma5_slope)
    support_lift = _candidate_support_lift_signature(
        features,
        fresh_lift=fresh_lift,
        active_strength=active_strength,
        ma5_slope=ma5_slope,
        ma10_distance=ma10_distance,
    )
    failure_signature = _candidate_setup_failure_signature(
        features,
        fresh_lift=fresh_lift,
        active_strength=active_strength,
        ma5_slope=ma5_slope,
        ma10_distance=ma10_distance,
        ma20_distance=ma20_distance,
        market_regime=str(evidence.get("dynamic_market_regime") or "unknown"),
    )
    return base | path | {
        "active_strength": active_strength,
        "fresh_lift": fresh_lift,
        "support_lift_signature": support_lift,
        "setup_failure_signature": failure_signature,
        "latest_change_bucket": _candidate_latest_change_bucket(latest_change),
        "ma5_slope_bucket": _candidate_ma5_slope_bucket(ma5_slope),
        "ma10_distance_bucket": _candidate_ma10_distance_bucket(ma10_distance),
        "ma20_distance_bucket": _candidate_ma20_distance_bucket(ma20_distance),
        "score_bucket": _candidate_score_bucket(_float_or_none(row.get("score") or row.get("total_score"))),
    }


def _candidate_entry_path_profile(row: dict[str, Any], bars: list[Bar], *, max_days: int = 10) -> dict[str, Any]:
    entry_date = _as_date(row.get("entry_execute_date"))
    sorted_bars = sorted(bars, key=lambda bar: bar.trade_date)
    entry_index = _bar_index_on_or_after(sorted_bars, entry_date)
    if entry_index is None:
        return {
            "path_order": "unknown",
            "first_up5_day": None,
            "first_up8_day": None,
            "first_down3_day": None,
            "first_down5_day": None,
            "close_return_3d": None,
            "close_return_5d": None,
            "close_return_10d": None,
            "max_runup_10d": None,
            "max_drawdown_10d": None,
        }
    window = sorted_bars[entry_index : entry_index + max_days]
    entry_price = float(sorted_bars[entry_index].open_price)
    first_up5 = _first_threshold_day(window, entry_price, threshold=5.0, high=True)
    first_up8 = _first_threshold_day(window, entry_price, threshold=8.0, high=True)
    first_down3 = _first_threshold_day(window, entry_price, threshold=-3.0, high=False)
    first_down5 = _first_threshold_day(window, entry_price, threshold=-5.0, high=False)
    return {
        "path_order": _candidate_path_order(first_up5=first_up5, first_up8=first_up8, first_down3=first_down3, first_down5=first_down5),
        "first_up5_day": first_up5,
        "first_up8_day": first_up8,
        "first_down3_day": first_down3,
        "first_down5_day": first_down5,
        "close_return_3d": _window_close_return(window, entry_price, day_count=3),
        "close_return_5d": _window_close_return(window, entry_price, day_count=5),
        "close_return_10d": _window_close_return(window, entry_price, day_count=10),
        "max_runup_10d": _candidate_window_runup_pct(window, entry_price),
        "max_drawdown_10d": _candidate_window_drawdown_pct(window, entry_price),
    }


def _first_threshold_day(window: list[Bar], entry_price: float, *, threshold: float, high: bool) -> int | None:
    if entry_price <= 0:
        return None
    for index, bar in enumerate(window, start=1):
        price = float(bar.high_price if high else bar.low_price)
        value = _pct_return(price, entry_price)
        if value is None:
            continue
        if high and value >= threshold:
            return index
        if not high and value <= threshold:
            return index
    return None


def _candidate_path_order(
    *,
    first_up5: int | None,
    first_up8: int | None,
    first_down3: int | None,
    first_down5: int | None,
) -> str:
    if first_up8 is not None and (first_down3 is None or first_up8 <= first_down3):
        return "up8_before_down3"
    if first_up5 is not None and (first_down3 is None or first_up5 <= first_down3):
        return "up5_before_down3"
    if first_down5 is not None and (first_up5 is None or first_down5 < first_up5):
        return "down5_before_up8"
    if first_down3 is not None and (first_up5 is None or first_down3 < first_up5):
        return "down3_before_up5"
    return "no_5pct_move"


def _window_close_return(window: list[Bar], entry_price: float, *, day_count: int) -> float | None:
    if not window or entry_price <= 0:
        return None
    index = min(day_count, len(window)) - 1
    return _pct_return(float(window[index].close_price), entry_price)


def _candidate_fresh_lift(features: dict[str, Any], *, latest_change: float | None, ma5_slope: float | None) -> bool:
    ma5_distance = features["ma5_distance"]
    close_location = features["close_location"]
    controlled_change = latest_change is not None and 0.4 <= latest_change <= 5.8
    ma5_turning = ma5_slope is not None and ma5_slope >= 0.10
    near_ma5 = ma5_distance is not None and 0.0 <= ma5_distance <= 3.2
    controlled_close = close_location is None or close_location <= 0.75
    return bool((controlled_change or ma5_turning or near_ma5) and controlled_close)


def _candidate_support_lift_signature(
    features: dict[str, Any],
    *,
    fresh_lift: bool,
    active_strength: float,
    ma5_slope: float | None,
    ma10_distance: float | None,
) -> str:
    close_location = features["close_location"]
    ma_convergence = features["ma_convergence"]
    ma5_distance = features["ma5_distance"]
    low_suction_days = features["low_suction_days"]
    low_or_lower_mid = close_location is not None and close_location <= 0.58
    mid_controlled = close_location is not None and 0.58 < close_location <= 0.75
    tradable_ma5 = ma5_distance is None or ma5_distance <= 3.5
    ma_live = ma_convergence is not None and 3.0 <= ma_convergence <= 18.0
    ma10_ok = ma10_distance is None or ma10_distance <= 4.5
    if features["active"] and low_or_lower_mid and tradable_ma5 and ma_live and fresh_lift:
        return "active_low_mid_fresh_lift"
    if features["active"] and mid_controlled and tradable_ma5 and ma_convergence is not None and 6.0 <= ma_convergence <= 18.0:
        return "active_mid_live_trend"
    if 3.0 <= low_suction_days <= 5.0 and low_or_lower_mid and tradable_ma5 and ma10_ok and fresh_lift:
        return "controlled_3_5d_low_suction_lift"
    if low_or_lower_mid and tradable_ma5 and ma5_slope is not None and ma5_slope >= 0.10:
        return "ma5_turning_low_mid"
    if active_strength >= 4.0 and tradable_ma5 and ma_live:
        return "strong_active_tradable_ma"
    return "no_clear_support_lift"


def _candidate_setup_failure_signature(
    features: dict[str, Any],
    *,
    fresh_lift: bool,
    active_strength: float,
    ma5_slope: float | None,
    ma10_distance: float | None,
    ma20_distance: float | None,
    market_regime: str,
) -> str:
    close_location = features["close_location"]
    launch_bucket = features["launch_bucket"]
    ma_convergence = features["ma_convergence"]
    ma5_distance = features["ma5_distance"]
    warning_level = features["warning_level"]
    low_suction_days = features["low_suction_days"]
    high_close = close_location is not None and close_location > 0.75
    extreme_close = close_location is not None and close_location > 0.88
    if ma5_distance is not None and ma5_distance > 6.0:
        return "ma5_overextended_6pct_plus"
    if high_close and launch_bucket in {"high_close_launch", "repeated_launch", "other_confirmed_launch", "thin_volume_launch"}:
        return "high_close_crowded_launch"
    if 6.0 <= low_suction_days <= 10.0 and active_strength < 3.0 and not fresh_lift:
        return "stale_6_10d_low_suction_no_lift"
    if ma_convergence is not None and ma_convergence < 3.0 and active_strength < 3.0:
        return "tight_quiet_no_activation"
    if launch_bucket == "other_confirmed_launch" and active_strength < 3.0:
        return "confirmed_but_no_active_money"
    if market_regime == "false_bull" and warning_level >= 2.0 and not (features["active"] and close_location is not None and close_location <= 0.58):
        return "false_bull_warning_without_low_support"
    if extreme_close and ma5_distance is not None and ma5_distance > 3.5:
        return "extreme_close_far_ma5"
    if ma10_distance is not None and ma10_distance > 6.0 and active_strength < 3.0:
        return "ma10_overextended_no_active"
    if ma20_distance is not None and ma20_distance < -3.0:
        return "ma20_support_not_reclaimed"
    if ma5_slope is not None and ma5_slope < 0.0 and active_strength < 3.0:
        return "ma5_not_turning_no_active"
    return "no_obvious_failure_signature"


def _candidate_launch_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _candidate_factor_metric_summary(rows)
    evaluated = [row for row in rows if _is_evaluated_candidate_path(row)]
    summary.update(
        {
            "up8_before_down3_rate": _ratio(sum(1 for row in evaluated if row.get("path_order") == "up8_before_down3"), len(evaluated)),
            "up5_before_down3_rate": _ratio(sum(1 for row in evaluated if row.get("path_order") in {"up8_before_down3", "up5_before_down3"}), len(evaluated)),
            "down3_before_up5_rate": _ratio(sum(1 for row in evaluated if row.get("path_order") in {"down3_before_up5", "down5_before_up8"}), len(evaluated)),
            "down5_before_up8_rate": _ratio(sum(1 for row in evaluated if row.get("path_order") == "down5_before_up8"), len(evaluated)),
            "average_close_return_3d": _avg(row.get("close_return_3d") for row in evaluated),
            "average_close_return_5d": _avg(row.get("close_return_5d") for row in evaluated),
            "average_close_return_10d": _avg(row.get("close_return_10d") for row in evaluated),
            "average_max_runup_10d": _avg(row.get("max_runup_10d") for row in evaluated),
            "average_max_drawdown_10d": _avg(row.get("max_drawdown_10d") for row in evaluated),
        }
    )
    return summary


def _candidate_launch_factor_buckets(rows: list[dict[str, Any]], *, min_count: int, limit: int) -> list[dict[str, Any]]:
    factor_keys = [
        "support_lift_signature",
        "setup_failure_signature",
        "candidate_shape",
        "launch_bucket",
        "close_bucket",
        "ma5_distance_bucket",
        "ma10_distance_bucket",
        "ma_convergence_bucket",
        "low_suction_days_bucket",
        "active_bucket",
        "latest_change_bucket",
        "ma5_slope_bucket",
        "day_shape",
        "market_regime",
        "warning_bucket",
        "score_bucket",
        "rank_bucket",
    ]
    buckets: list[dict[str, Any]] = []
    for key in factor_keys:
        buckets.extend(_candidate_launch_group_buckets(rows, (key,), min_count=min_count, limit=999, sort_mode="spread"))
    return sorted(
        buckets,
        key=lambda item: (
            -abs(_float_or_none(item.get("fast_vs_fail_spread")) or 0.0),
            -abs(_float_or_none(item.get("average_return_pct")) or 0.0),
            -int(item.get("evaluated_count") or 0),
        ),
    )[:limit]


def _candidate_launch_group_buckets(
    rows: list[dict[str, Any]],
    keys: tuple[str, ...],
    *,
    min_count: int,
    limit: int,
    sort_mode: str = "spread",
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(str(row.get(key) or "unknown") for key in keys)].append(row)
    buckets = []
    for values, bucket_rows in grouped.items():
        if len(bucket_rows) < min_count:
            continue
        metrics = _candidate_launch_metric_summary(bucket_rows)
        fast_rate = _float_or_none(metrics.get("up5_before_down3_rate")) or 0.0
        fail_rate = _float_or_none(metrics.get("down3_before_up5_rate")) or 0.0
        buckets.append(
            {
                "factor": "+".join(keys),
                "value": "|".join(values),
                **metrics,
                "fast_vs_fail_spread": fast_rate - fail_rate,
            }
        )
    sorters = {
        "good": lambda item: (
            -(_float_or_none(item.get("fast_vs_fail_spread")) or -999.0),
            -(_float_or_none(item.get("average_return_pct")) or -999.0),
            -int(item.get("evaluated_count") or 0),
        ),
        "bad": lambda item: (
            _float_or_none(item.get("fast_vs_fail_spread")) or 999.0,
            _float_or_none(item.get("average_return_pct")) or 999.0,
            -int(item.get("evaluated_count") or 0),
        ),
        "spread": lambda item: (
            -abs(_float_or_none(item.get("fast_vs_fail_spread")) or 0.0),
            -abs(_float_or_none(item.get("average_return_pct")) or 0.0),
            -int(item.get("evaluated_count") or 0),
        ),
    }
    return sorted(buckets, key=sorters[sort_mode])[:limit]


def _candidate_launch_daily_samples(rows: list[dict[str, Any]], *, strong: bool, limit: int) -> list[dict[str, Any]]:
    grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        signal_date = _as_date(row.get("signal_date"))
        if signal_date is not None:
            grouped[signal_date].append(row)
    samples = []
    for signal_date, date_rows in grouped.items():
        metrics = _candidate_launch_metric_summary(date_rows)
        fast_rate = _float_or_none(metrics.get("up5_before_down3_rate")) or 0.0
        fail_rate = _float_or_none(metrics.get("down3_before_up5_rate")) or 0.0
        samples.append({"signal_date": signal_date, **metrics, "fast_vs_fail_spread": fast_rate - fail_rate})
    return sorted(
        samples,
        key=lambda item: (
            _float_or_none(item.get("fast_vs_fail_spread")) if item.get("fast_vs_fail_spread") is not None else 0.0,
            _float_or_none(item.get("average_return_pct")) or 0.0,
        ),
        reverse=strong,
    )[:limit]


def _candidate_launch_samples(rows: list[dict[str, Any]], *, mode: str, limit: int) -> list[dict[str, Any]]:
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            -(_float_or_none(row.get("max_runup_10d")) or -999.0),
            -(_float_or_none(row.get("return_pct")) or -999.0),
        )
        if mode == "fast_lift"
        else (
            _float_or_none(row.get("max_drawdown_10d")) or 0.0,
            _float_or_none(row.get("return_pct")) if _float_or_none(row.get("return_pct")) is not None else 999.0,
        ),
    )
    return [
        {
            "signal_date": row.get("signal_date"),
            "entry_execute_date": row.get("entry_execute_date"),
            "vt_symbol": row.get("vt_symbol"),
            "rank": row.get("rank"),
            "score": row.get("score"),
            "path_order": row.get("path_order"),
            "return_pct": row.get("return_pct"),
            "max_runup_pct": row.get("max_runup_pct"),
            "max_drawdown_pct": row.get("max_drawdown_pct"),
            "close_return_3d": row.get("close_return_3d"),
            "max_runup_10d": row.get("max_runup_10d"),
            "max_drawdown_10d": row.get("max_drawdown_10d"),
            "entry_family": row.get("entry_family"),
            "candidate_shape": row.get("candidate_shape"),
            "support_lift_signature": row.get("support_lift_signature"),
            "setup_failure_signature": row.get("setup_failure_signature"),
            "launch_bucket": row.get("launch_bucket"),
            "close_bucket": row.get("close_bucket"),
            "ma5_distance_bucket": row.get("ma5_distance_bucket"),
            "ma_convergence_bucket": row.get("ma_convergence_bucket"),
            "market_regime": row.get("market_regime"),
            "warning_bucket": row.get("warning_bucket"),
            "day_shape": row.get("day_shape"),
        }
        for row in sorted_rows[:limit]
    ]


def _candidate_latest_change_bucket(value: float | None) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "unknown"
    if numeric < -2:
        return "down_<-2"
    if numeric < 0.4:
        return "flat_-2_0_4"
    if numeric <= 3.8:
        return "controlled_lift_0_4_3_8"
    if numeric <= 6.2:
        return "strong_lift_3_8_6_2"
    return "surge_6_2+"


def _candidate_ma5_slope_bucket(value: float | None) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "unknown"
    if numeric < -0.2:
        return "falling"
    if numeric < 0.1:
        return "flat"
    if numeric <= 0.9:
        return "turning_up"
    return "steep_up"


def _candidate_ma10_distance_bucket(value: float | None) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "unknown"
    if numeric < -2:
        return "below_ma10"
    if numeric <= 1.5:
        return "near_ma10"
    if numeric <= 4.5:
        return "lifted_1_5_4_5"
    if numeric <= 6:
        return "far_4_5_6"
    return "very_far_6+"


def _candidate_ma20_distance_bucket(value: float | None) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "unknown"
    if numeric < -3:
        return "below_ma20"
    if numeric <= 2:
        return "near_ma20"
    if numeric <= 6:
        return "lifted_2_6"
    if numeric <= 10:
        return "far_6_10"
    return "very_far_10+"


def _candidate_score_bucket(value: float | None) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "unknown"
    if numeric >= 95:
        return "95+"
    if numeric >= 90:
        return "90_95"
    if numeric >= 86:
        return "86_90"
    return "<86"


def _candidate_stock_drilldown_samples(
    rows: list[dict[str, Any]],
    bars_by_symbol: dict[str, list[Bar]],
    *,
    kind: str,
    limit: int,
) -> list[dict[str, Any]]:
    candidates = [row for row in rows if _is_evaluated_candidate_path(row)]
    if kind == "surge":
        candidates = [row for row in candidates if row.get("is_surge")]
        candidates = sorted(
            candidates,
            key=lambda row: (
                _float_or_none(row.get("max_runup_pct")) or -999.0,
                _float_or_none(row.get("return_pct")) or -999.0,
            ),
            reverse=True,
        )
    elif kind == "pure_loss":
        candidates = [row for row in candidates if row.get("is_pure_loss")]
        candidates = sorted(
            candidates,
            key=lambda row: (
                _float_or_none(row.get("return_pct")) if _float_or_none(row.get("return_pct")) is not None else 999.0,
                _float_or_none(row.get("max_drawdown_pct")) or 0.0,
            ),
        )
    elif kind == "giveback":
        candidates = [row for row in candidates if row.get("is_giveback")]
        candidates = sorted(
            candidates,
            key=lambda row: (
                -(_float_or_none(row.get("max_runup_pct")) or -999.0),
                _float_or_none(row.get("return_pct")) if _float_or_none(row.get("return_pct")) is not None else 999.0,
            ),
        )
    else:
        candidates = sorted(
            candidates,
            key=lambda row: (
                _float_or_none(row.get("return_pct")) if _float_or_none(row.get("return_pct")) is not None else 999.0,
                _float_or_none(row.get("max_drawdown_pct")) or 0.0,
            ),
        )
    samples: list[dict[str, Any]] = []
    seen: set[tuple[str, date | None]] = set()
    for row in candidates:
        symbol = str(row.get("vt_symbol") or "").strip().upper()
        signal_date = _as_date(row.get("signal_date"))
        key = (symbol, signal_date)
        if not symbol or key in seen:
            continue
        seen.add(key)
        samples.append(_candidate_stock_drilldown_row(row, bars_by_symbol.get(symbol, [])))
        if len(samples) >= limit:
            break
    return samples


def _candidate_stock_drilldown_row(row: dict[str, Any], bars: list[Bar]) -> dict[str, Any]:
    evidence = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    signal_date = _as_date(row.get("signal_date"))
    entry_date = _as_date(row.get("entry_execute_date"))
    exit_date = _as_date(row.get("exit_execute_date"))
    sorted_bars = sorted(bars, key=lambda bar: bar.trade_date)
    signal_index = _bar_index_on_or_before(sorted_bars, signal_date)
    entry_index = _bar_index_on_or_after(sorted_bars, entry_date)
    signal_bar = sorted_bars[signal_index] if signal_index is not None else None
    entry_bar = sorted_bars[entry_index] if entry_index is not None else None
    pre_bars = sorted_bars[max(0, (signal_index or 0) - 19) : (signal_index or -1) + 1] if signal_index is not None else []
    path_bars = _candidate_entry_path_bars(sorted_bars, entry_index=entry_index, exit_date=exit_date, max_days=12)
    resistance = _candidate_resistance_snapshot(evidence, signal_bar=signal_bar, pre_bars=pre_bars, path_bars=path_bars)
    return {
        "signal_date": row.get("signal_date"),
        "entry_execute_date": row.get("entry_execute_date"),
        "exit_execute_date": row.get("exit_execute_date"),
        "vt_symbol": row.get("vt_symbol"),
        "name": row.get("name") or evidence.get("name") or evidence.get("stock_name"),
        "rank": row.get("rank"),
        "score": row.get("score"),
        "return_pct": row.get("return_pct"),
        "max_drawdown_pct": row.get("max_drawdown_pct"),
        "max_runup_pct": row.get("max_runup_pct"),
        "holding_days": row.get("holding_days"),
        "exit_reason": row.get("exit_reason"),
        "labels": {
            "candidate_shape": row.get("candidate_shape"),
            "entry_family": row.get("entry_family"),
            "launch_bucket": row.get("launch_bucket"),
            "market_regime": row.get("market_regime"),
            "warning_bucket": row.get("warning_bucket"),
            "day_shape": row.get("day_shape"),
        },
        "visible_factors": _candidate_visible_factor_snapshot(evidence),
        "signal_bar": _candidate_bar_snapshot(signal_bar, evidence=evidence),
        "entry_bar": _candidate_bar_snapshot(entry_bar, evidence={}),
        "resistance": resistance,
        "path_after_entry": [_candidate_path_bar_snapshot(bar, entry_bar=entry_bar, resistance=resistance) for bar in path_bars],
        "interpretation": _candidate_stock_path_interpretation(row, evidence, resistance=resistance, path_bars=path_bars),
    }


def _candidate_visible_factor_snapshot(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_setup": evidence.get("entry_setup") or evidence.get("setup_type"),
        "entry_family": evidence.get("entry_family"),
        "low_suction_days": evidence.get("low_suction_days"),
        "low_suction_launch_confirmed": evidence.get("low_suction_launch_confirmed"),
        "low_suction_launch_quality_bucket": evidence.get("low_suction_launch_quality_bucket"),
        "close_location_in_range": evidence.get("close_location_in_range"),
        "ma5_distance_pct": evidence.get("ma5_distance_pct"),
        "ma10_distance_pct": evidence.get("ma10_distance_pct"),
        "ma20_distance_pct": evidence.get("ma20_distance_pct"),
        "ma_convergence_pct": evidence.get("ma_convergence_pct"),
        "ma5_slope_pct": evidence.get("ma5_slope_pct"),
        "latest_change_pct": evidence.get("latest_change_pct"),
        "volume_ratio_5d_20d": evidence.get("volume_ratio_5d_20d"),
        "large_bull_count_20d": evidence.get("large_bull_count_20d"),
        "recent_limit_up_20d": evidence.get("recent_limit_up_20d"),
        "near_limit_up_count_20d": evidence.get("near_limit_up_count_20d"),
        "turnover_percentile_60d": evidence.get("turnover_percentile_60d"),
        "upper_shadow_pct": evidence.get("upper_shadow_pct"),
        "risk_penalty": evidence.get("risk_penalty"),
        "risk_flags": evidence.get("risk_flags"),
        "smart_money_proxy_score": evidence.get("smart_money_proxy_score"),
        "fund_flow_score": evidence.get("fund_flow_score"),
        "hot_rank_score": evidence.get("hot_rank_score"),
        "lhb_score": evidence.get("lhb_score"),
        "dynamic_market_regime": evidence.get("dynamic_market_regime"),
        "dynamic_market_label": evidence.get("dynamic_market_label"),
        "market_warning_level": evidence.get("market_warning_level"),
        "market_warning_label": evidence.get("market_warning_label"),
        "fund_flow_state": evidence.get("fund_flow_state"),
        "fund_flow_label": evidence.get("fund_flow_label"),
        "fund_flow_streak_days": evidence.get("fund_flow_streak_days"),
    }


def _candidate_bar_snapshot(bar: Bar | None, *, evidence: dict[str, Any]) -> dict[str, Any] | None:
    if bar is None:
        return None
    return {
        "trade_date": bar.trade_date,
        "open": float(bar.open_price),
        "high": float(bar.high_price),
        "low": float(bar.low_price),
        "close": float(bar.close_price),
        "change_pct": _float_or_none(bar.change_pct) if bar.change_pct is not None else evidence.get("latest_change_pct"),
        "volume": float(bar.volume) if bar.volume is not None else None,
        "turnover": float(bar.turnover) if bar.turnover is not None else None,
        "ma5": evidence.get("ma5"),
        "ma10": evidence.get("ma10"),
        "ma20": evidence.get("ma20"),
        "ma30": evidence.get("ma30"),
        "ma60": evidence.get("ma60"),
    }


def _candidate_path_bar_snapshot(bar: Bar, *, entry_bar: Bar | None, resistance: dict[str, Any]) -> dict[str, Any]:
    entry_price = float(entry_bar.open_price) if entry_bar is not None else None
    close_return = _pct_return(float(bar.close_price), entry_price) if entry_price else None
    high_return = _pct_return(float(bar.high_price), entry_price) if entry_price else None
    low_return = _pct_return(float(bar.low_price), entry_price) if entry_price else None
    resistance_price = _float_or_none(resistance.get("nearest_resistance_price"))
    return {
        "trade_date": bar.trade_date,
        "open": float(bar.open_price),
        "high": float(bar.high_price),
        "low": float(bar.low_price),
        "close": float(bar.close_price),
        "change_pct": _float_or_none(bar.change_pct),
        "close_return_pct": close_return,
        "high_return_pct": high_return,
        "low_return_pct": low_return,
        "hit_resistance": bool(resistance_price is not None and float(bar.high_price) >= resistance_price),
    }


def _candidate_resistance_snapshot(
    evidence: dict[str, Any],
    *,
    signal_bar: Bar | None,
    pre_bars: list[Bar],
    path_bars: list[Bar],
) -> dict[str, Any]:
    signal_close = float(signal_bar.close_price) if signal_bar else None
    prior_high = max((float(bar.high_price) for bar in pre_bars), default=None)
    pivot_high = _float_or_none(evidence.get("pivot_high_20d"))
    candidates = [value for value in (prior_high, pivot_high) if value is not None]
    nearest = min((value for value in candidates if signal_close is not None and value >= signal_close), default=None)
    if nearest is None and candidates:
        nearest = max(candidates)
    first_hit = None
    if nearest is not None:
        first_hit = next((bar.trade_date for bar in path_bars if float(bar.high_price) >= nearest), None)
    return {
        "signal_close": signal_close,
        "prior_20d_high": prior_high,
        "pivot_high_20d": pivot_high,
        "nearest_resistance_price": nearest,
        "distance_to_resistance_pct": _pct_return(nearest, signal_close) if nearest is not None and signal_close else None,
        "first_hit_after_entry": first_hit,
        "drawdown_from_pivot_pct": evidence.get("drawdown_from_pivot_pct"),
    }


def _candidate_stock_path_interpretation(
    row: dict[str, Any],
    evidence: dict[str, Any],
    *,
    resistance: dict[str, Any],
    path_bars: list[Bar],
) -> list[str]:
    notes: list[str] = []
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    active_strength = _candidate_active_strength(evidence)
    warning_level = _float_or_none(evidence.get("market_warning_level")) or 0.0
    launch_bucket = str(evidence.get("low_suction_launch_quality_bucket") or "")
    resistance_distance = _float_or_none(resistance.get("distance_to_resistance_pct"))
    if row.get("is_surge"):
        notes.append("后续出现显著 MFE，说明候选池有右尾机会。")
    if row.get("is_pure_loss"):
        notes.append("最大浮盈小于 3% 且最终亏损，属于需要优先规避的纯亏路径。")
    if row.get("is_giveback"):
        notes.append("曾经冲高但最终非正收益，说明卖点/利润保护需要单独评估。")
    if active_strength >= 3 and close_location is not None and close_location <= 0.58:
        notes.append("信号日具备活跃资金和中低位承接，属于支撑抬升候选。")
    if close_location is not None and close_location > 0.75:
        notes.append("信号日收盘位置偏高，容易变成拥挤买点。")
    if ma5_distance is not None and ma5_distance > 5.5:
        notes.append("信号日远离 MA5，入场性价比下降。")
    if low_suction_days >= 6 and active_strength < 3:
        notes.append("低吸天数较久但活跃资金不足，偏滞涨低吸。")
    if launch_bucket in {"high_close_launch", "repeated_launch", "other_confirmed_launch"}:
        notes.append(f"启动质量为 {launch_bucket}，需要看是否有承接而不能只按确认加分。")
    if warning_level >= 2:
        notes.append("行情 warning 不低，需要和个股 setup 质量交互判断。")
    if resistance_distance is not None and resistance_distance <= 3.0:
        notes.append("信号日离近端压力位很近，容易先承压。")
    if path_bars and resistance.get("first_hit_after_entry"):
        notes.append(f"入场后触及近端压力位：{resistance.get('first_hit_after_entry')}")
    return notes


def _candidate_entry_path_bars(
    bars: list[Bar],
    *,
    entry_index: int | None,
    exit_date: date | None,
    max_days: int,
) -> list[Bar]:
    if entry_index is None:
        return []
    result: list[Bar] = []
    for bar in bars[entry_index:]:
        result.append(bar)
        if exit_date is not None and bar.trade_date >= exit_date:
            break
        if len(result) >= max_days:
            break
    return result


def _bar_index_on_or_before(bars: list[Bar], target: date | None) -> int | None:
    if target is None:
        return None
    result = None
    for index, bar in enumerate(bars):
        if bar.trade_date <= target:
            result = index
        else:
            break
    return result


def _bar_index_on_or_after(bars: list[Bar], target: date | None) -> int | None:
    if target is None:
        return None
    return next((index for index, bar in enumerate(bars) if bar.trade_date >= target), None)


def _candidate_rows_grouped_by_day(rows: list[dict[str, Any]]) -> dict[date, list[dict[str, Any]]]:
    grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        trade_date = _as_date(row.get("trade_date") or row.get("signal_date"))
        if trade_date is None:
            continue
        grouped[trade_date].append(row)
    return {
        trade_date: sorted(
            date_rows,
            key=lambda row: (
                _int_or_none(row.get("rank")) or 9999,
                -(_float_or_none(row.get("total_score") or row.get("score")) or 0.0),
                str(row.get("vt_symbol") or ""),
            ),
        )
        for trade_date, date_rows in grouped.items()
    }


def _candidate_factor_path_enriched_row(row: dict[str, Any], *, day_profiles: dict[date, dict[str, Any]]) -> dict[str, Any]:
    evidence = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    features = _postprocess_candidate_features(row)
    signal_date = _as_date(row.get("signal_date"))
    day_profile = day_profiles.get(signal_date, {}) if signal_date else {}
    return_pct = _float_or_none(row.get("return_pct"))
    max_drawdown = _float_or_none(row.get("max_drawdown_pct"))
    max_runup = _float_or_none(row.get("max_runup_pct"))
    return dict(row) | {
        "entry_family": str(evidence.get("entry_family") or evidence.get("entry_setup") or evidence.get("setup_type") or "unknown"),
        "market_regime": str(evidence.get("dynamic_market_regime") or "unknown"),
        "fund_flow_state": str(evidence.get("fund_flow_state") or "unknown"),
        "launch_bucket": features["launch_bucket"],
        "close_bucket": _candidate_close_bucket(features["close_location"]),
        "ma_convergence_bucket": _candidate_ma_convergence_bucket(features["ma_convergence"]),
        "ma5_distance_bucket": _candidate_ma5_distance_bucket(features["ma5_distance"]),
        "low_suction_days_bucket": _candidate_low_suction_days_bucket(features["low_suction_days"]),
        "volume_bucket": _candidate_volume_bucket(features["volume_ratio"]),
        "rank_bucket": _candidate_rank_bucket(_int_or_none(row.get("rank"))),
        "warning_bucket": f"w{int(features['warning_level'])}" if features["warning_level"] is not None else "w0",
        "active_bucket": "strong_active" if features["strong_active"] else "active" if features["active"] else "inactive",
        "candidate_shape": _candidate_shape_bucket(features),
        "day_shape": _candidate_day_shape(day_profile),
        "is_surge": bool((max_runup is not None and max_runup >= 8.0) or (return_pct is not None and return_pct >= 8.0)),
        "is_quick_surge": bool(return_pct is not None and return_pct >= 8.0),
        "is_decline": bool((return_pct is not None and return_pct <= -5.0) or (max_drawdown is not None and max_drawdown <= -8.0)),
        "is_pure_loss": bool(max_runup is not None and return_pct is not None and max_runup < 3.0 and return_pct < 0.0),
        "is_giveback": bool(max_runup is not None and return_pct is not None and max_runup >= 8.0 and return_pct <= 0.0),
        "is_deep_drawdown": bool(max_drawdown is not None and max_drawdown <= -10.0),
        "day_profile": day_profile,
    }


def _candidate_top_factor_buckets(rows: list[dict[str, Any]], *, mode: str, min_count: int = 12, limit: int = 18) -> list[dict[str, Any]]:
    factor_keys = [
        "candidate_shape",
        "active_bucket",
        "close_bucket",
        "launch_bucket",
        "low_suction_days_bucket",
        "ma_convergence_bucket",
        "ma5_distance_bucket",
        "volume_bucket",
        "entry_family",
        "market_regime",
        "warning_bucket",
        "day_shape",
        "rank_bucket",
    ]
    buckets: list[dict[str, Any]] = []
    for key in factor_keys:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get(key) or "unknown")].append(row)
        for value, bucket_rows in grouped.items():
            if len(bucket_rows) < min_count:
                continue
            metrics = _candidate_factor_metric_summary(bucket_rows)
            buckets.append({"factor": key, "value": value, **metrics})
    sort_key = {
        "surge": lambda item: (
            -(_float_or_none(item.get("surge_rate")) or 0.0),
            -(_float_or_none(item.get("average_return_pct")) or -999.0),
            -int(item.get("evaluated_count") or 0),
        ),
        "decline": lambda item: (
            -(_float_or_none(item.get("decline_rate")) or 0.0),
            _float_or_none(item.get("average_return_pct")) or 999.0,
            -int(item.get("evaluated_count") or 0),
        ),
        "pure_loss": lambda item: (
            -(_float_or_none(item.get("pure_loss_rate")) or 0.0),
            _float_or_none(item.get("average_return_pct")) or 999.0,
            -int(item.get("evaluated_count") or 0),
        ),
        "giveback": lambda item: (
            -(_float_or_none(item.get("giveback_rate")) or 0.0),
            -(_float_or_none(item.get("average_max_runup_pct")) or -999.0),
            -int(item.get("evaluated_count") or 0),
        ),
    }[mode]
    return sorted(buckets, key=sort_key)[:limit]


def _candidate_factor_pair_buckets(rows: list[dict[str, Any]], *, min_count: int = 12, limit: int = 24) -> list[dict[str, Any]]:
    pairs = [
        ("active_bucket", "close_bucket"),
        ("active_bucket", "ma_convergence_bucket"),
        ("active_bucket", "low_suction_days_bucket"),
        ("close_bucket", "launch_bucket"),
        ("launch_bucket", "market_regime"),
        ("low_suction_days_bucket", "active_bucket"),
        ("candidate_shape", "day_shape"),
        ("entry_family", "candidate_shape"),
        ("ma_convergence_bucket", "close_bucket"),
    ]
    buckets: list[dict[str, Any]] = []
    for left, right in pairs:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[(str(row.get(left) or "unknown"), str(row.get(right) or "unknown"))].append(row)
        for (left_value, right_value), bucket_rows in grouped.items():
            if len(bucket_rows) < min_count:
                continue
            metrics = _candidate_factor_metric_summary(bucket_rows)
            buckets.append(
                {
                    "factor_pair": f"{left}+{right}",
                    "value": f"{left_value}|{right_value}",
                    **metrics,
                }
            )
    return sorted(
        buckets,
        key=lambda item: (
            -((_float_or_none(item.get("surge_rate")) or 0.0) - (_float_or_none(item.get("pure_loss_rate")) or 0.0)),
            -(_float_or_none(item.get("average_return_pct")) or -999.0),
            _float_or_none(item.get("average_max_drawdown_pct")) or -999.0,
        ),
    )[:limit]


def _candidate_factor_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [row for row in rows if _is_evaluated_candidate_path(row)]
    returns = [_float_or_none(row.get("return_pct")) for row in evaluated]
    drawdowns = [_float_or_none(row.get("max_drawdown_pct")) for row in evaluated]
    runups = [_float_or_none(row.get("max_runup_pct")) for row in evaluated]
    returns = [value for value in returns if value is not None]
    drawdowns = [value for value in drawdowns if value is not None]
    runups = [value for value in runups if value is not None]
    return {
        "sample_count": len(rows),
        "evaluated_count": len(evaluated),
        "win_rate": _ratio(sum(1 for value in returns if value > 0), len(returns)),
        "average_return_pct": _avg(returns),
        "median_return_pct": _median(returns),
        "average_max_drawdown_pct": _avg(drawdowns),
        "worst_max_drawdown_pct": min(drawdowns) if drawdowns else None,
        "average_max_runup_pct": _avg(runups),
        "surge_rate": _ratio(sum(1 for row in evaluated if row.get("is_surge")), len(evaluated)),
        "decline_rate": _ratio(sum(1 for row in evaluated if row.get("is_decline")), len(evaluated)),
        "pure_loss_rate": _ratio(sum(1 for row in evaluated if row.get("is_pure_loss")), len(evaluated)),
        "giveback_rate": _ratio(sum(1 for row in evaluated if row.get("is_giveback")), len(evaluated)),
        "deep_drawdown_rate": _ratio(sum(1 for row in evaluated if row.get("is_deep_drawdown")), len(evaluated)),
    }


def _candidate_day_profile_outcome(
    rows: list[dict[str, Any]],
    *,
    day_profiles: dict[date, dict[str, Any]],
    strong: bool,
) -> list[dict[str, Any]]:
    selected_dates = {
        trade_date
        for trade_date, profile in day_profiles.items()
        if bool(profile.get("strong_day")) is strong and bool(profile.get("weak_day")) is not strong
    }
    grouped = defaultdict(list)
    for row in rows:
        signal_date = _as_date(row.get("signal_date"))
        if signal_date in selected_dates:
            grouped[signal_date].append(row)
    result = []
    for trade_date, date_rows in sorted(grouped.items()):
        result.append({"signal_date": trade_date, **_candidate_factor_metric_summary(date_rows)})
    return sorted(
        result,
        key=lambda item: (
            _float_or_none(item.get("average_return_pct")) or 0.0,
            _float_or_none(item.get("average_max_drawdown_pct")) or 0.0,
        ),
        reverse=strong,
    )[:10]


def _candidate_factor_samples(rows: list[dict[str, Any]], *, mode: str, limit: int) -> list[dict[str, Any]]:
    if mode == "surge":
        selected = [row for row in rows if row.get("is_surge")]
        selected = sorted(selected, key=lambda row: _float_or_none(row.get("max_runup_pct")) or -999.0, reverse=True)
    else:
        selected = sorted(
            rows,
            key=lambda row: (
                _float_or_none(row.get("return_pct")) if _float_or_none(row.get("return_pct")) is not None else 999.0,
                _float_or_none(row.get("max_drawdown_pct")) or 0.0,
            ),
        )
    return [
        {
            "signal_date": row.get("signal_date"),
            "vt_symbol": row.get("vt_symbol"),
            "rank": row.get("rank"),
            "score": row.get("score"),
            "return_pct": row.get("return_pct"),
            "max_drawdown_pct": row.get("max_drawdown_pct"),
            "max_runup_pct": row.get("max_runup_pct"),
            "exit_reason": row.get("exit_reason"),
            "entry_family": row.get("entry_family"),
            "candidate_shape": row.get("candidate_shape"),
            "market_regime": row.get("market_regime"),
            "warning_bucket": row.get("warning_bucket"),
            "day_shape": row.get("day_shape"),
        }
        for row in selected[:limit]
    ]


def _candidate_close_bucket(value: float | None) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "unknown"
    if numeric <= 0.35:
        return "low"
    if numeric <= 0.58:
        return "lower_mid"
    if numeric <= 0.75:
        return "mid"
    if numeric <= 0.88:
        return "high"
    return "extreme_high"


def _candidate_ma_convergence_bucket(value: float | None) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "unknown"
    if numeric < 3:
        return "tight_<3"
    if numeric <= 6:
        return "normal_3_6"
    if numeric <= 10:
        return "wide_6_10"
    if numeric <= 18:
        return "trend_10_18"
    return "very_wide_18+"


def _candidate_ma5_distance_bucket(value: float | None) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "unknown"
    if numeric < -2:
        return "below_ma5"
    if numeric <= 1.5:
        return "near_ma5"
    if numeric <= 3.5:
        return "lifted_1_5_3_5"
    if numeric <= 6:
        return "far_3_5_6"
    return "very_far_6+"


def _candidate_low_suction_days_bucket(value: float | None) -> str:
    numeric = _float_or_none(value) or 0.0
    if numeric <= 0:
        return "0"
    if numeric <= 2:
        return "1_2"
    if numeric <= 5:
        return "3_5"
    if numeric <= 10:
        return "6_10"
    return "10+"


def _candidate_volume_bucket(value: float | None) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "unknown"
    if numeric < 0.65:
        return "thin_<0_65"
    if numeric < 0.8:
        return "shrinking_0_65_0_8"
    if numeric <= 1.6:
        return "normal_0_8_1_6"
    if numeric <= 2.2:
        return "expanded_1_6_2_2"
    return "hot_2_2+"


def _candidate_rank_bucket(value: int | None) -> str:
    if value is None:
        return "unknown"
    if value <= 5:
        return "01_05"
    if value <= 10:
        return "06_10"
    if value <= 15:
        return "11_15"
    return "16_20"


def _candidate_shape_bucket(features: dict[str, Any]) -> str:
    close_location = features["close_location"]
    launch_bucket = features["launch_bucket"]
    if features["active_low_mid"]:
        return "active_low_mid_support"
    if features["active_mid"]:
        return "active_mid_trend"
    if features["high_weak_launch"]:
        return "high_close_weak_launch"
    if features["stale_quiet"]:
        return "stale_low_suction_no_active"
    if features["tight_quiet"]:
        return "tight_quiet_no_active"
    if features["active"] and close_location is not None and close_location <= 0.75:
        return "active_controlled_close"
    if launch_bucket == "unconfirmed_buildup":
        return "unconfirmed_buildup"
    if features["high_close"]:
        return "high_close_other"
    return "other"


def _candidate_day_shape(day_profile: dict[str, Any]) -> str:
    if day_profile.get("strong_day"):
        return "strong_top20_structure"
    if day_profile.get("weak_day"):
        return "weak_top20_structure"
    if day_profile.get("warning_far"):
        return "warning_far_top20_structure"
    return "mixed_top20_structure"


def _candidate_quality_matrix_variants() -> list[dict[str, Any]]:
    return [
        {
            "label": "default",
            "tail_risk": False,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "low_suction_buildup": False,
            "surge_quality": False,
        },
        {
            "label": "low_suction_buildup",
            "tail_risk": False,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "low_suction_buildup": True,
            "surge_quality": False,
        },
        {
            "label": "tail_only",
            "tail_risk": True,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "low_suction_buildup": False,
            "surge_quality": False,
        },
        {
            "label": "exit_dynamic_failed_plus_mid_profit",
            "tail_risk": False,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "dynamic_failed_launch_exit": True,
            "mid_profit_giveback": True,
        },
        {
            "label": "mid_profit_giveback_only",
            "tail_risk": False,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "mid_profit_giveback": True,
        },
        {
            "label": "mfe8_giveback_stop",
            "tail_risk": False,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "mid_profit_giveback": True,
            "mid_profit_min_high_gain_pct": 0.08,
            "mid_profit_max_current_gain_pct": 0.02,
            "mid_profit_drawdown_pct": 0.05,
        },
        {
            "label": "mfe8_keep4_giveback6_stop",
            "tail_risk": False,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "mid_profit_giveback": True,
            "mid_profit_min_high_gain_pct": 0.08,
            "mid_profit_max_current_gain_pct": 0.04,
            "mid_profit_drawdown_pct": 0.06,
        },
        {
            "label": "momentum_only",
            "tail_risk": False,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": False,
            "low_suction_buildup": False,
            "surge_quality": False,
        },
        {
            "label": "momentum_plus_exit_dynamic_mid",
            "tail_risk": False,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "dynamic_failed_launch_exit": True,
            "mid_profit_giveback": True,
        },
        {
            "label": "momentum_risk_control",
            "tail_risk": False,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": True,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
        },
        {
            "label": "momentum_risk_control_plus_exit_dynamic_mid",
            "tail_risk": False,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": True,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "dynamic_failed_launch_exit": True,
            "mid_profit_giveback": True,
        },
        {
            "label": "momentum_hard_filter",
            "tail_risk": False,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": False,
            "mainline_momentum_hard_filter": True,
            "low_suction_buildup": False,
            "surge_quality": False,
        },
        {
            "label": "surge_quality",
            "tail_risk": False,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "low_suction_buildup": False,
            "surge_quality": True,
        },
        {
            "label": "top20_day_quality_gate",
            "tail_risk": False,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "top20_day_quality": True,
        },
        {
            "label": "tail_plus_surge",
            "tail_risk": True,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "low_suction_buildup": False,
            "surge_quality": True,
        },
        {
            "label": "tail_plus_momentum",
            "tail_risk": True,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": False,
            "low_suction_buildup": False,
            "surge_quality": False,
        },
        {
            "label": "tail_plus_momentum_risk_control",
            "tail_risk": True,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": True,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
        },
        {
            "label": "tail_plus_momentum_hard_filter",
            "tail_risk": True,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": False,
            "mainline_momentum_hard_filter": True,
            "low_suction_buildup": False,
            "surge_quality": False,
        },
        {
            "label": "high_risk_d2_follow_through",
            "tail_risk": False,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "high_risk_d2_follow": True,
        },
        {
            "label": "pure_loss_weak_bucket",
            "tail_risk": False,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "pure_loss_weak_bucket": True,
        },
        {
            "label": "selective_setup_quality",
            "tail_risk": False,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "selective_setup_quality": True,
        },
        {
            "label": "momentum_risk_control_plus_pure_loss_weak_bucket",
            "tail_risk": False,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": True,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "pure_loss_weak_bucket": True,
        },
        {
            "label": "momentum_plus_selective_setup_quality",
            "tail_risk": False,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": True,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "selective_setup_quality": True,
        },
        {
            "label": "pure_loss_weak_bucket_plus_mfe8_giveback",
            "tail_risk": False,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "pure_loss_weak_bucket": True,
            "mid_profit_giveback": True,
            "mid_profit_min_high_gain_pct": 0.08,
            "mid_profit_max_current_gain_pct": 0.02,
            "mid_profit_drawdown_pct": 0.05,
        },
        {
            "label": "selective_setup_quality_plus_mfe8_giveback",
            "tail_risk": False,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "selective_setup_quality": True,
            "mid_profit_giveback": True,
            "mid_profit_min_high_gain_pct": 0.08,
            "mid_profit_max_current_gain_pct": 0.02,
            "mid_profit_drawdown_pct": 0.05,
        },
        {
            "label": "momentum_risk_control_pure_loss_plus_mfe8_giveback",
            "tail_risk": False,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": True,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "pure_loss_weak_bucket": True,
            "mid_profit_giveback": True,
            "mid_profit_min_high_gain_pct": 0.08,
            "mid_profit_max_current_gain_pct": 0.02,
            "mid_profit_drawdown_pct": 0.05,
        },
        {
            "label": "momentum_risk_control_pure_loss_plus_mfe8_keep4_giveback6",
            "tail_risk": False,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": True,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "pure_loss_weak_bucket": True,
            "mid_profit_giveback": True,
            "mid_profit_min_high_gain_pct": 0.08,
            "mid_profit_max_current_gain_pct": 0.04,
            "mid_profit_drawdown_pct": 0.06,
        },
        {
            "label": "momentum_selective_plus_mfe8_giveback",
            "tail_risk": False,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": True,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "selective_setup_quality": True,
            "mid_profit_giveback": True,
            "mid_profit_min_high_gain_pct": 0.08,
            "mid_profit_max_current_gain_pct": 0.02,
            "mid_profit_drawdown_pct": 0.05,
        },
        {
            "label": "momentum_day_quality_plus_mfe8_giveback",
            "tail_risk": False,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": True,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "top20_day_quality": True,
            "mid_profit_giveback": True,
            "mid_profit_min_high_gain_pct": 0.08,
            "mid_profit_max_current_gain_pct": 0.02,
            "mid_profit_drawdown_pct": 0.05,
        },
        {
            "label": "momentum_selective_day_quality_plus_mfe8_giveback",
            "tail_risk": False,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": True,
            "mainline_momentum_hard_filter": False,
            "low_suction_buildup": False,
            "surge_quality": False,
            "selective_setup_quality": True,
            "top20_day_quality": True,
            "mid_profit_giveback": True,
            "mid_profit_min_high_gain_pct": 0.08,
            "mid_profit_max_current_gain_pct": 0.02,
            "mid_profit_drawdown_pct": 0.05,
        },
        {
            "label": "tail_momentum_hard_pure_loss_plus_mfe8_giveback",
            "tail_risk": True,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": True,
            "mainline_momentum_hard_filter": True,
            "low_suction_buildup": False,
            "surge_quality": False,
            "pure_loss_weak_bucket": True,
            "mid_profit_giveback": True,
            "mid_profit_min_high_gain_pct": 0.08,
            "mid_profit_max_current_gain_pct": 0.02,
            "mid_profit_drawdown_pct": 0.05,
        },
        {
            "label": "tail_momentum_hard_pure_loss_plus_mfe8_keep4_giveback6",
            "tail_risk": True,
            "mainline_momentum": True,
            "mainline_momentum_risk_control": True,
            "mainline_momentum_hard_filter": True,
            "low_suction_buildup": False,
            "surge_quality": False,
            "pure_loss_weak_bucket": True,
            "mid_profit_giveback": True,
            "mid_profit_min_high_gain_pct": 0.08,
            "mid_profit_max_current_gain_pct": 0.04,
            "mid_profit_drawdown_pct": 0.06,
        },
        {
            "label": "low_suction_plus_tail",
            "tail_risk": True,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "low_suction_buildup": True,
            "surge_quality": False,
        },
        {
            "label": "weekly_relief",
            "tail_risk": False,
            "mainline_momentum": False,
            "mainline_momentum_risk_control": False,
            "weekly_relief": True,
            "low_suction_buildup": False,
            "surge_quality": False,
        },
    ]


def _candidate_variant_report(
    base_params: BacktestParams,
    candidates: list[dict[str, Any]],
    bars_by_symbol: dict[str, list[Any]],
    *,
    label: str,
    tail_risk: bool,
    mainline_momentum: bool,
    mainline_momentum_risk_control: bool,
    mainline_momentum_hard_filter: bool = False,
    surge_quality: bool,
    low_suction_buildup: bool,
    high_risk_d2_follow: bool = False,
    pure_loss_weak_bucket: bool = False,
    selective_setup_quality: bool = False,
    weekly_relief: bool = False,
    top20_day_quality: bool = False,
    dynamic_failed_launch_exit: bool = False,
    mid_profit_giveback: bool = False,
    mid_profit_min_high_gain_pct: float | None = None,
    mid_profit_max_current_gain_pct: float | None = None,
    mid_profit_drawdown_pct: float | None = None,
    top_n: int,
) -> dict[str, Any]:
    params = replace(
        base_params,
        enable_candidate_tail_risk_penalty=tail_risk,
        enable_mainline_momentum_lane=mainline_momentum,
        enable_mainline_momentum_risk_control=mainline_momentum_risk_control,
        enable_mainline_momentum_hard_filter=mainline_momentum_hard_filter,
        enable_surge_quality_lane=surge_quality,
        enable_top20_day_quality_gate=top20_day_quality,
        enable_weekly_top_fractal_relief=weekly_relief,
        enable_low_suction_buildup_quality_lane=low_suction_buildup,
        enable_high_risk_d2_follow_through_entry=high_risk_d2_follow,
        enable_pure_loss_weak_bucket_penalty=pure_loss_weak_bucket,
        enable_selective_setup_quality_lane=selective_setup_quality,
        enable_dynamic_failed_launch_exit_stop=dynamic_failed_launch_exit,
        enable_mid_profit_giveback_stop=mid_profit_giveback,
        mid_profit_giveback_min_high_gain_pct=(
            float(mid_profit_min_high_gain_pct)
            if mid_profit_min_high_gain_pct is not None
            else base_params.mid_profit_giveback_min_high_gain_pct
        ),
        mid_profit_giveback_max_current_gain_pct=(
            float(mid_profit_max_current_gain_pct)
            if mid_profit_max_current_gain_pct is not None
            else base_params.mid_profit_giveback_max_current_gain_pct
        ),
        mid_profit_giveback_drawdown_pct=(
            float(mid_profit_drawdown_pct)
            if mid_profit_drawdown_pct is not None
            else base_params.mid_profit_giveback_drawdown_pct
        ),
    )
    report = _candidate_path_report(candidates, bars_by_symbol, params, top_n=top_n)
    dates = sorted(report["daily"])
    return {
        "label": label,
        "enable_candidate_tail_risk_penalty": tail_risk,
        "enable_mainline_momentum_lane": mainline_momentum,
        "enable_mainline_momentum_risk_control": mainline_momentum_risk_control,
        "enable_mainline_momentum_hard_filter": mainline_momentum_hard_filter,
        "enable_surge_quality_lane": surge_quality,
        "enable_top20_day_quality_gate": top20_day_quality,
        "enable_weekly_top_fractal_relief": weekly_relief,
        "enable_low_suction_buildup_quality_lane": low_suction_buildup,
        "enable_high_risk_d2_follow_through_entry": high_risk_d2_follow,
        "enable_pure_loss_weak_bucket_penalty": pure_loss_weak_bucket,
        "enable_selective_setup_quality_lane": selective_setup_quality,
        "enable_dynamic_failed_launch_exit_stop": dynamic_failed_launch_exit,
        "enable_mid_profit_giveback_stop": mid_profit_giveback,
        "mid_profit_giveback_min_high_gain_pct": params.mid_profit_giveback_min_high_gain_pct,
        "mid_profit_giveback_max_current_gain_pct": params.mid_profit_giveback_max_current_gain_pct,
        "mid_profit_giveback_drawdown_pct": params.mid_profit_giveback_drawdown_pct,
        "candidate_count": report["candidate_count"],
        "evaluated_count": report["evaluated_count"],
        "candidate_day_count": len(report["daily"]),
        "overall": _candidate_overall_for_dates(report, dates),
        "overall_without_price_discontinuity": _candidate_overall_for_dates(
            _candidate_report_without_price_discontinuity(report),
            dates,
        ),
        "data_quality": _candidate_path_data_quality(report["rows"]),
    }


def _current_code_top_candidate_matrix_rows(
    base_params: BacktestParams,
    variants: list[dict[str, Any]],
    *,
    top_n: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[Any]]]:
    variant_params = {
        str(variant["label"]): replace(
            base_params,
            enable_candidate_tail_risk_penalty=bool(variant["tail_risk"]),
            enable_mainline_momentum_lane=bool(variant["mainline_momentum"]),
            enable_mainline_momentum_risk_control=bool(variant.get("mainline_momentum_risk_control", False)),
            enable_mainline_momentum_hard_filter=bool(variant.get("mainline_momentum_hard_filter", False)),
            enable_surge_quality_lane=bool(variant.get("surge_quality", False)),
            enable_top20_day_quality_gate=bool(variant.get("top20_day_quality", False)),
            enable_weekly_top_fractal_relief=bool(variant.get("weekly_relief", False)),
            enable_low_suction_buildup_quality_lane=bool(variant.get("low_suction_buildup", False)),
            enable_high_risk_d2_follow_through_entry=bool(variant.get("high_risk_d2_follow", False)),
            enable_pure_loss_weak_bucket_penalty=bool(variant.get("pure_loss_weak_bucket", False)),
            enable_selective_setup_quality_lane=bool(variant.get("selective_setup_quality", False)),
            enable_dynamic_failed_launch_exit_stop=bool(variant.get("dynamic_failed_launch_exit", False)),
            enable_mid_profit_giveback_stop=bool(variant.get("mid_profit_giveback", False)),
            mid_profit_giveback_min_high_gain_pct=float(
                variant.get("mid_profit_min_high_gain_pct", base_params.mid_profit_giveback_min_high_gain_pct)
            ),
            mid_profit_giveback_max_current_gain_pct=float(
                variant.get("mid_profit_max_current_gain_pct", base_params.mid_profit_giveback_max_current_gain_pct)
            ),
            mid_profit_giveback_drawdown_pct=float(
                variant.get("mid_profit_drawdown_pct", base_params.mid_profit_giveback_drawdown_pct)
            ),
        )
        for variant in variants
    }
    with session_scope() as session:
        vt_symbols = backtest_engine._load_symbol_universe(
            session,
            base_params.max_symbols,
            base_params.symbols,
            base_params.included_boards,
        )
        bars_by_symbol = backtest_engine._load_all_bars(
            session,
            vt_symbols,
            backtest_engine._lookback_start(base_params.start),
            base_params.end or base_params.start,
        )
        trading_days = backtest_engine._trading_days(bars_by_symbol, base_params.start, base_params.end or base_params.start)
        score_context = backtest_engine._load_score_context(session, list(bars_by_symbol))
        stock_meta = backtest_engine._load_stock_meta(session, list(bars_by_symbol))
        scoring_dates = _candidate_scoring_dates(trading_days)
        score_cache: dict[date, list[Any]] = {}
        for trade_date in scoring_dates:
            backtest_engine._score_day(session, bars_by_symbol, trade_date, base_params, score_cache, score_context)
        if any(backtest_engine._params_need_market_context(params) for params in variant_params.values()):
            score_cache = backtest_engine._score_cache_with_market_context(
                session,
                score_cache,
                *scoring_dates,
            ) or score_cache
        rows_by_variant: dict[str, list[dict[str, Any]]] = {label: [] for label in variant_params}
        for trade_date in scoring_dates:
            for label, params in variant_params.items():
                scores = backtest_engine._score_day(session, bars_by_symbol, trade_date, params, score_cache, score_context)
                for rank, score in enumerate(scores[:top_n], start=1):
                    rows_by_variant[label].append(
                        {
                            "trade_date": trade_date,
                            "vt_symbol": str(score.vt_symbol),
                            "name": (stock_meta.get(str(score.vt_symbol)) or {}).get("name"),
                            "rank": rank,
                            "action": "BUY",
                            "total_score": float(score.total_score or 0.0),
                            "reason": dict(score.evidence or {}),
                            "source": f"current_code_matrix_{label}",
                        }
                    )
    return rows_by_variant, bars_by_symbol


def _trading_dates_or_skip() -> list[date]:
    _database_or_skip()
    with session_scope() as session:
        rows = session.execute(
            select(schema.stock_daily_bars.c.trade_date)
            .group_by(schema.stock_daily_bars.c.trade_date)
            .order_by(schema.stock_daily_bars.c.trade_date)
        ).all()
    dates = [row[0] for row in rows]
    if len(dates) < 80:
        pytest.skip(f"Not enough local daily bars for strategy acceptance: {len(dates)} trading days.")
    return dates


def _database_or_skip() -> None:
    if not is_database_configured():
        pytest.skip("DATABASE_URL is not configured; run this channel inside alphaagent-api or set DATABASE_URL.")
    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL is unavailable for strategy acceptance: {exc.__class__.__name__}")


def _quick_start_date(dates: list[date]) -> date:
    window = max(_int_env("ALPHAAGENT_STRATEGY_ACCEPTANCE_WINDOW", QUICK_WINDOW_DAYS), 80)
    if len(dates) <= window:
        return dates[0]
    return dates[-window]


def _quick_max_symbols() -> int:
    return max(_int_env("ALPHAAGENT_QUICK_ACCEPTANCE_MAX_SYMBOLS", QUICK_MAX_SYMBOLS), 1)


def _full_max_symbols() -> int:
    return max(_int_env("ALPHAAGENT_FULL_ACCEPTANCE_MAX_SYMBOLS", FULL_MAX_SYMBOLS), 1)


def _best_product_baseline_or_skip() -> dict[str, Any]:
    response = list_backtests(
        limit=20,
        run_type="portfolio",
        strategy_id=DRAGON_PULLBACK_STRATEGY_ID,
        baseline_only=True,
    )
    items = response.get("items") or []
    candidates = [item for item in items if isinstance(item.get("metrics"), dict)]
    if not candidates:
        pytest.skip("No product baseline backtest is available for strategy comparison.")
    return max(candidates, key=lambda item: _performance_key(item["metrics"]))


def _candidate_cohort_comparison_or_skip(
    *,
    current_params: BacktestParams,
    baseline: dict[str, Any],
    start: date,
    end: date,
    top_n: int,
) -> dict[str, Any]:
    baseline_id = int(baseline.get("id") or 0)
    if baseline_id <= 0:
        pytest.skip("Product baseline does not expose a backtest id for candidate cohort comparison.")

    current_candidates, current_bars = _current_code_top_candidate_rows(current_params, top_n=top_n)
    baseline_candidates = _baseline_top_candidate_rows(baseline_id, start=start, end=end, top_n=top_n)
    if not current_candidates:
        pytest.skip("Current strategy produced no top candidate rows for cohort comparison.")
    if not baseline_candidates:
        pytest.skip(f"Baseline backtest #{baseline_id} has no persisted top candidate rows for cohort comparison.")

    baseline_bars = _bars_for_candidate_rows(baseline_candidates, start=start, end=end)
    current_report = _candidate_path_report(current_candidates, current_bars, current_params, top_n=top_n)
    baseline_report = _candidate_path_report(baseline_candidates, baseline_bars, current_params, top_n=top_n)
    return _paired_candidate_cohort_comparison(
        current_report,
        baseline_report,
        baseline_id=baseline_id,
        top_n=top_n,
        max_common_dates=_candidate_cohort_max_dates(),
    )


def _current_code_top_candidate_rows(params: BacktestParams, *, top_n: int) -> tuple[list[dict[str, Any]], dict[str, list[Any]]]:
    with session_scope() as session:
        vt_symbols = backtest_engine._load_symbol_universe(session, params.max_symbols, params.symbols, params.included_boards)
        bars_by_symbol = backtest_engine._load_all_bars(session, vt_symbols, backtest_engine._lookback_start(params.start), params.end or params.start)
        trading_days = backtest_engine._trading_days(bars_by_symbol, params.start, params.end or params.start)
        score_context = backtest_engine._load_score_context(session, list(bars_by_symbol))
        stock_meta = backtest_engine._load_stock_meta(session, list(bars_by_symbol))
        score_cache: dict[date, list[Any]] = {}
        rows: list[dict[str, Any]] = []
        for trade_date in _candidate_scoring_dates(trading_days):
            scores = backtest_engine._score_day(session, bars_by_symbol, trade_date, params, score_cache, score_context)
            for rank, score in enumerate(scores[:top_n], start=1):
                rows.append(
                    {
                        "trade_date": trade_date,
                        "vt_symbol": str(score.vt_symbol),
                        "name": (stock_meta.get(str(score.vt_symbol)) or {}).get("name"),
                        "rank": rank,
                        "action": "BUY",
                        "total_score": float(score.total_score or 0.0),
                        "reason": dict(score.evidence or {}),
                        "source": "current_code_no_cache_score_day",
                    }
                )
    return rows, bars_by_symbol


def _current_code_top_candidate_rows_with_context(
    params: BacktestParams,
    *,
    top_n: int,
) -> tuple[list[dict[str, Any]], dict[str, list[Any]]]:
    cache_key = _candidate_snapshot_cache_key(params, top_n=top_n)
    cached = _load_candidate_snapshot_cache(cache_key)
    if cached is not None:
        return cached

    context_params = replace(
        params,
        enable_selective_setup_quality_lane=True,
    )
    rows_by_variant, bars_by_symbol = _current_code_top_candidate_matrix_rows(
        context_params,
        [
            {
                "label": "default",
                "tail_risk": False,
                "mainline_momentum": False,
                "mainline_momentum_risk_control": False,
                "mainline_momentum_hard_filter": False,
                "low_suction_buildup": False,
                "surge_quality": False,
                "selective_setup_quality": False,
            }
        ],
        top_n=top_n,
    )
    result = (rows_by_variant["default"], bars_by_symbol)
    _save_candidate_snapshot_cache(cache_key, result)
    return result


def _candidate_snapshot_cache_key(params: BacktestParams, *, top_n: int) -> str:
    key_parts = {
        "version": CANDIDATE_SNAPSHOT_CACHE_VERSION,
        "strategy": params.strategy,
        "start": params.start.isoformat() if params.start else None,
        "end": params.end.isoformat() if params.end else None,
        "max_symbols": params.max_symbols,
        "symbols": list(params.symbols or []),
        "included_boards": list(params.included_boards or []),
        "top_n": top_n,
        "candidate_limit": params.candidate_limit,
        "min_entry_score": params.min_entry_score,
        "strict_entry": params.strict_entry,
        "execution_model": params.execution_model,
        "schema": getattr(backtest_engine, "SIGNAL_EVIDENCE_SCHEMA_VERSION", None),
        "selective_setup_quality": True,
    }
    text_key = json.dumps(key_parts, sort_keys=True, ensure_ascii=True, default=str)
    import hashlib

    return hashlib.sha256(text_key.encode("utf-8")).hexdigest()[:24]


def _load_candidate_snapshot_cache(cache_key: str) -> tuple[list[dict[str, Any]], dict[str, list[Any]]] | None:
    if _truthy_env("ALPHAAGENT_DISABLE_CANDIDATE_SNAPSHOT_CACHE"):
        return None
    path = CANDIDATE_SNAPSHOT_CACHE_DIR / f"{cache_key}.pkl"
    if not path.exists():
        return None
    try:
        with path.open("rb") as file:
            payload = pickle.load(file)
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("version") != CANDIDATE_SNAPSHOT_CACHE_VERSION:
        return None
    rows = payload.get("rows")
    bars_by_symbol = payload.get("bars_by_symbol")
    if not isinstance(rows, list) or not isinstance(bars_by_symbol, dict):
        return None
    print(f"[candidate_snapshot_cache] hit key={cache_key} rows={len(rows)} symbols={len(bars_by_symbol)}")
    return rows, bars_by_symbol


def _save_candidate_snapshot_cache(
    cache_key: str,
    result: tuple[list[dict[str, Any]], dict[str, list[Any]]],
) -> None:
    if _truthy_env("ALPHAAGENT_DISABLE_CANDIDATE_SNAPSHOT_CACHE"):
        return
    rows, bars_by_symbol = result
    CANDIDATE_SNAPSHOT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CANDIDATE_SNAPSHOT_CACHE_DIR / f"{cache_key}.pkl"
    tmp_path = path.with_suffix(".tmp")
    payload = {
        "version": CANDIDATE_SNAPSHOT_CACHE_VERSION,
        "rows": rows,
        "bars_by_symbol": bars_by_symbol,
    }
    with tmp_path.open("wb") as file:
        pickle.dump(payload, file, protocol=pickle.HIGHEST_PROTOCOL)
    tmp_path.replace(path)
    print(f"[candidate_snapshot_cache] miss_saved key={cache_key} rows={len(rows)} symbols={len(bars_by_symbol)}")


def _postprocess_candidate_pool(pool_rows: list[dict[str, Any]], *, top_n: int, mode: str) -> list[dict[str, Any]]:
    grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in pool_rows:
        trade_date = _as_date(row.get("trade_date"))
        if trade_date is not None:
            grouped[trade_date].append(row)

    selected: list[dict[str, Any]] = []
    for trade_date, rows in sorted(grouped.items()):
        sorted_rows = sorted(
            rows,
            key=lambda row: (
                _int_or_none(row.get("rank")) or 9999,
                -(_float_or_none(row.get("total_score")) or 0.0),
                str(row.get("vt_symbol") or ""),
            ),
        )
        day_profile = _postprocess_day_profile(sorted_rows[:top_n])
        scored_rows = [
            _postprocess_scored_row(row, day_profile=day_profile, mode=mode)
            for row in sorted_rows
        ]
        pick_limit = top_n
        if mode == "weak_day_cap10_overlay" and (day_profile["weak_day"] or day_profile["warning_far"]):
            pick_limit = 10
        elif mode == "weak_day_cap5_overlay" and (day_profile["weak_day"] or day_profile["warning_far"]):
            pick_limit = 5
        elif mode == "v2_cap10_overlay" and (day_profile["weak_day"] or day_profile["warning_far"]):
            pick_limit = 10
        elif mode == "v2_cap8_overlay" and (day_profile["weak_day"] or day_profile["warning_far"]):
            pick_limit = 8
        elif mode == "v3_support_lift_cap10" and (day_profile["weak_day"] or day_profile["warning_far"]):
            pick_limit = 10
        elif mode == "v3_support_lift_cap8" and (day_profile["weak_day"] or day_profile["warning_far"]):
            pick_limit = 8
        elif mode == "v4_launch_quality_cap10" and (day_profile["weak_day"] or day_profile["warning_far"]):
            pick_limit = 10
        elif mode == "v4_launch_quality_cap8" and (day_profile["weak_day"] or day_profile["warning_far"]):
            pick_limit = 8
        elif mode == "v5_v2_lift_guard_cap10" and (day_profile["weak_day"] or day_profile["warning_far"]):
            pick_limit = 10
        elif mode == "v5_v2_lift_guard_cap8" and (day_profile["weak_day"] or day_profile["warning_far"]):
            pick_limit = 8
        elif mode == "v6_v2_right_tail_guard_cap8" and (day_profile["weak_day"] or day_profile["warning_far"]):
            pick_limit = 8
        elif mode == "v7_v2_soft_right_tail_cap8" and (day_profile["weak_day"] or day_profile["warning_far"]):
            pick_limit = 8

        candidates = scored_rows if mode != "top80_strict_overlay" else [row for row in scored_rows if not row["quality_overlay_blocked"]]
        if mode in {
            "weak_day_cap10_overlay",
            "weak_day_cap5_overlay",
            "v2_cap10_overlay",
            "v2_cap8_overlay",
            "v3_support_lift_cap10",
            "v3_support_lift_cap8",
            "v4_launch_quality_cap10",
            "v4_launch_quality_cap8",
            "v5_v2_lift_guard_cap10",
            "v5_v2_lift_guard_cap8",
            "v6_v2_right_tail_guard_cap8",
            "v7_v2_soft_right_tail_cap8",
        }:
            candidates = [row for row in candidates if not row["quality_overlay_blocked"]]
        picked = sorted(
            candidates,
            key=lambda row: (
                -(_float_or_none(row.get("total_score")) or 0.0),
                _int_or_none(row.get("base_rank")) or 9999,
                str(row.get("vt_symbol") or ""),
            ),
        )[:pick_limit]
        for rank, row in enumerate(picked, start=1):
            selected.append(dict(row) | {"rank": rank, "trade_date": trade_date, "source": f"postprocess_{mode}"})
    return selected


def _postprocess_scored_row(row: dict[str, Any], *, day_profile: dict[str, Any], mode: str) -> dict[str, Any]:
    adjustment, notes = (
        _postprocess_v7_v2_soft_right_tail_adjustment(row, day_profile=day_profile, mode=mode)
        if mode == "v7_v2_soft_right_tail_cap8"
        else
        _postprocess_v6_v2_right_tail_guard_adjustment(row, day_profile=day_profile, mode=mode)
        if mode == "v6_v2_right_tail_guard_cap8"
        else
        _postprocess_v5_v2_lift_guard_adjustment(row, day_profile=day_profile, mode=mode)
        if mode in {"v5_v2_lift_guard_cap10", "v5_v2_lift_guard_cap8"}
        else
        _postprocess_v4_launch_quality_adjustment(row, day_profile=day_profile, mode=mode)
        if mode in {"v4_launch_quality_cap10", "v4_launch_quality_cap8"}
        else
        _postprocess_v3_support_lift_adjustment(row, day_profile=day_profile, mode=mode)
        if mode in {"v3_support_lift_cap10", "v3_support_lift_cap8"}
        else _postprocess_v2_overlay_adjustment(row, day_profile=day_profile, mode=mode)
        if mode in {"v2_cap10_overlay", "v2_cap8_overlay"}
        else _postprocess_quality_overlay_adjustment(row, day_profile=day_profile, mode=mode)
    )
    base_score = _float_or_none(row.get("total_score")) or 0.0
    return dict(row) | {
        "base_rank": _int_or_none(row.get("rank")),
        "base_score": base_score,
        "total_score": round(base_score + adjustment, 4),
        "quality_overlay_adjustment": round(adjustment, 4),
        "quality_overlay_notes": notes,
        "quality_overlay_day_profile": day_profile,
        "quality_overlay_blocked": (
            _postprocess_v7_v2_soft_right_tail_blocked(row, day_profile)
            if mode == "v7_v2_soft_right_tail_cap8"
            else
            _postprocess_v6_v2_right_tail_guard_blocked(row, day_profile)
            if mode == "v6_v2_right_tail_guard_cap8"
            else
            _postprocess_v5_v2_lift_guard_blocked(row, day_profile)
            if mode in {"v5_v2_lift_guard_cap10", "v5_v2_lift_guard_cap8"}
            else
            _postprocess_v4_launch_quality_blocked(row, day_profile)
            if mode in {"v4_launch_quality_cap10", "v4_launch_quality_cap8"}
            else
            _postprocess_v3_support_lift_blocked(row, day_profile)
            if mode in {"v3_support_lift_cap10", "v3_support_lift_cap8"}
            else _postprocess_v2_overlay_blocked(row, day_profile)
            if mode in {"v2_cap10_overlay", "v2_cap8_overlay"}
            else _postprocess_quality_overlay_blocked(row, day_profile)
        ),
    }


def _postprocess_quality_overlay_adjustment(
    row: dict[str, Any],
    *,
    day_profile: dict[str, Any],
    mode: str,
) -> tuple[float, list[str]]:
    features = _postprocess_candidate_features(row)
    adjustment = 0.0
    notes: list[str] = []

    if features["active_low_mid"]:
        adjustment += 4.2 if features["strong_active"] else 3.2
        notes.append("活跃中低位承接加分")
        if features["lower_mid_close"]:
            adjustment += 0.5
    elif features["active_mid"]:
        adjustment += 1.2
        notes.append("活跃中位趋势小加分")
    if (
        features["active"]
        and features["close_location"] is not None
        and features["close_location"] <= 0.75
        and features["large_bull_count"] >= 3
        and features["ma_convergence"] is not None
        and 6.0 <= features["ma_convergence"] <= 18.0
    ):
        adjustment += 1.0
        notes.append("多大阳且未高位拥挤加分")
    if (
        3.0 <= features["low_suction_days"] <= 5.0
        and features["close_location"] is not None
        and features["close_location"] <= 0.58
        and features["ma_convergence"] is not None
        and features["ma_convergence"] <= 6.0
        and features["healthy_volume"]
    ):
        adjustment += 1.2
        notes.append("3-5天低吸蓄势且收敛加分")

    if features["high_weak_launch"]:
        adjustment -= 3.2
        notes.append("高位弱启动降权")
    if features["extreme_high_far_ma5"]:
        adjustment -= 2.4
        notes.append("极高收盘且远离5日线降权")
    if features["far_ma5"] and features["high_close"]:
        adjustment -= 1.8
        notes.append("高位且偏离5日线降权")
    if features["stale_quiet"]:
        adjustment -= 3.0
        notes.append("低吸过久但缺少新激活降权")
    if features["tight_quiet"]:
        adjustment -= 2.0
        notes.append("均线过紧且缺少活跃资金降权")
    if features["launch_bucket"] == "thin_volume_launch" and (
        features["volume_ratio"] is None or features["volume_ratio"] < 0.8
    ):
        adjustment -= 1.2
        notes.append("薄量启动降权")
    if features["latest_change"] is not None and features["latest_change"] >= 8.5 and features["high_close"]:
        adjustment -= 1.0
        notes.append("信号日接近涨停后高位追买降权")
    if features["risk_penalty"] >= 10:
        adjustment -= 0.8
        notes.append("结构风险偏高降权")

    if adjustment < 0 and features["active"] and features["close_location"] is not None and features["close_location"] <= 0.75 and features["healthy_volume"]:
        relief = min(abs(adjustment), 1.8)
        adjustment += relief
        notes.append("活跃且未高位拥挤减免")
    if (
        adjustment < 0
        and features["strong_active"]
        and features["extreme_high_close"]
        and not day_profile["weak_day"]
        and features["warning_level"] <= 2
    ):
        relief = min(abs(adjustment), 1.0)
        adjustment += relief
        notes.append("强活跃高位样本右尾保护减免")

    if day_profile["strong_day"]:
        if features["active_low_mid"]:
            adjustment += 1.0
            notes.append("强候选日活跃中低位加分")
        elif features["high_weak_launch"]:
            adjustment -= 0.8
            notes.append("强候选日中的高位弱启动降权")
    if day_profile["weak_day"] or day_profile["warning_far"]:
        if features["active_low_mid"]:
            adjustment += 0.8
            notes.append("弱候选日保留活跃中低位")
        elif features["high_weak_launch"]:
            adjustment -= 2.0
            notes.append("弱候选日高位弱启动额外降权")
        elif features["stale_quiet"] or features["tight_quiet"]:
            adjustment -= 1.2
            notes.append("弱候选日安静滞涨额外降权")
        elif features["high_close"]:
            adjustment -= 0.6
            notes.append("弱候选日高位收盘降权")

    if mode == "top80_strict_overlay" and (
        features["high_weak_launch"]
        or (features["extreme_high_far_ma5"] and not features["strong_active"])
        or features["stale_quiet"]
        or features["tight_quiet"]
    ):
        adjustment -= 1.2
        notes.append("严格模式额外降权")
    elif mode == "top80_gentle_overlay":
        adjustment *= 0.65

    if not notes:
        return 0.0, []
    return max(min(adjustment, 6.0), -8.0), notes


def _postprocess_quality_overlay_blocked(row: dict[str, Any], day_profile: dict[str, Any]) -> bool:
    features = _postprocess_candidate_features(row)
    if features["active_low_mid"]:
        return False
    if day_profile["weak_day"] and features["high_weak_launch"] and (
        features["warning_level"] >= 2 or features["ma5_distance"] is None or features["ma5_distance"] > 3.5
    ):
        return True
    if features["extreme_high_far_ma5"] and features["warning_level"] >= 3 and not features["strong_active"]:
        return True
    if features["stale_quiet"] and day_profile["weak_day"]:
        return True
    return False


def _postprocess_v2_overlay_adjustment(
    row: dict[str, Any],
    *,
    day_profile: dict[str, Any],
    mode: str,
) -> tuple[float, list[str]]:
    evidence = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    features = _postprocess_candidate_features(row)
    close_location = features["close_location"]
    ma_convergence = features["ma_convergence"]
    ma5_distance = features["ma5_distance"]
    launch_bucket = features["launch_bucket"]
    warning_level = features["warning_level"]
    active_strength = _candidate_active_strength(evidence)
    low_suction_days = features["low_suction_days"]
    active = features["active"]
    low_close = close_location is not None and close_location <= 0.35
    lower_mid_close = close_location is not None and 0.35 < close_location <= 0.58
    mid_close = close_location is not None and 0.58 < close_location <= 0.75
    high_close = close_location is not None and 0.75 < close_location <= 0.88
    extreme_close = close_location is not None and close_location > 0.88
    near_ma5 = ma5_distance is None or ma5_distance <= 3.5
    far_ma5 = ma5_distance is not None and ma5_distance > 3.5
    ma_ok = ma_convergence is not None and 3.0 <= ma_convergence <= 18.0
    wide_ma_ok = ma_convergence is not None and 6.0 <= ma_convergence <= 18.0
    healthy_volume = features["healthy_volume"]
    adjustment = 0.0
    notes: list[str] = []

    if active and low_close and ma_ok and near_ma5 and healthy_volume:
        adjustment += 5.0 if active_strength >= 4.0 else 4.0
        notes.append("v2_active_low_support")
    elif active and mid_close and wide_ma_ok and near_ma5 and healthy_volume:
        adjustment += 2.6 if active_strength >= 4.0 else 1.8
        notes.append("v2_active_mid_trend")
    elif active and lower_mid_close and ma_ok and near_ma5 and healthy_volume:
        adjustment += 1.1 if features["strong_active"] else 0.3
        notes.append("v2_lower_mid_needs_strength")
    if active and close_location is not None and close_location <= 0.75 and features["large_bull_count"] >= 3.0 and wide_ma_ok:
        adjustment += 1.2
        notes.append("v2_large_bull_not_crowded")
    if launch_bucket == "unconfirmed_buildup" and active and low_close and 3.0 <= low_suction_days <= 5.0 and ma_convergence is not None and ma_convergence <= 6.0:
        adjustment += 1.8
        notes.append("v2_early_buildup_low_confirm")
    if launch_bucket == "not_low_suction" and active and close_location is not None and close_location <= 0.75 and wide_ma_ok:
        adjustment += 1.0
        notes.append("v2_mainline_active_controlled")

    if launch_bucket in {"high_close_launch", "repeated_launch"} and (high_close or extreme_close):
        adjustment -= 4.0
        notes.append("v2_high_repeated_launch_penalty")
    elif launch_bucket in {"high_close_launch", "repeated_launch"}:
        adjustment -= 2.0
        notes.append("v2_repeated_launch_penalty")
    if launch_bucket == "other_confirmed_launch" and not active:
        adjustment -= 3.5
        notes.append("v2_other_confirmed_no_active")
    elif launch_bucket == "other_confirmed_launch" and close_location is not None and close_location > 0.58:
        adjustment -= 2.0
        notes.append("v2_other_confirmed_mid_high")
    if launch_bucket == "unconfirmed_buildup" and not active and close_location is not None and close_location > 0.58:
        adjustment -= 2.6
        notes.append("v2_unconfirmed_no_active_mid_high")
    if 6.0 <= low_suction_days <= 10.0 and not (active and low_close):
        adjustment -= 2.6
        notes.append("v2_stale_low_suction_6_10")
    if extreme_close:
        adjustment -= 3.0
        notes.append("v2_extreme_close")
        if far_ma5 or warning_level >= 2.0:
            adjustment -= 1.8
            notes.append("v2_extreme_far_or_warning")
    elif high_close and far_ma5:
        adjustment -= 1.5
        notes.append("v2_high_far_ma5")
    if ma_convergence is not None and ma_convergence < 3.0 and not active:
        adjustment -= 2.2
        notes.append("v2_tight_quiet")
    if evidence.get("dynamic_market_regime") == "false_bull" and warning_level >= 2.0 and not (active and low_close):
        adjustment -= 1.5 if warning_level == 2.0 else 2.2
        notes.append("v2_false_bull_warning")
    if evidence.get("dynamic_market_regime") == "choppy_rotation" and warning_level == 2.0 and not (active and low_close):
        adjustment -= 1.2
        notes.append("v2_choppy_w2")
    if day_profile["weak_day"] or day_profile["warning_far"]:
        if active and low_close:
            adjustment += 1.0
            notes.append("v2_weak_day_keep_low_active")
        elif (high_close or extreme_close) and features["weak_launch"]:
            adjustment -= 1.8
            notes.append("v2_weak_day_high_weak")
        elif not active and close_location is not None and close_location > 0.58:
            adjustment -= 0.9
            notes.append("v2_weak_day_no_active_mid_high")
    if (
        ("v2_extreme_close" in notes and warning_level >= 2.0)
        or ("v2_stale_low_suction_6_10" in notes and not active)
        or "v2_other_confirmed_no_active" in notes
    ):
        adjustment -= 2.0
        notes.append("v2_strict_extra")

    return (max(min(adjustment, 7.0), -10.0), notes) if notes else (0.0, [])


def _postprocess_v2_overlay_blocked(row: dict[str, Any], day_profile: dict[str, Any]) -> bool:
    features = _postprocess_candidate_features(row)
    close_location = features["close_location"]
    launch_bucket = features["launch_bucket"]
    high_close = close_location is not None and close_location > 0.75
    extreme_close = close_location is not None and close_location > 0.88
    if features["active"] and close_location is not None and close_location <= 0.35:
        return False
    if launch_bucket in {"high_close_launch", "repeated_launch"} and high_close and features["warning_level"] >= 2.0:
        return True
    if extreme_close and features["warning_level"] >= 2.0 and (features["ma5_distance"] is None or features["ma5_distance"] > 1.5):
        return True
    if 6.0 <= features["low_suction_days"] <= 10.0 and not features["active"]:
        return True
    return bool(day_profile["weak_day"] and launch_bucket == "other_confirmed_launch" and not features["active"] and high_close)


def _postprocess_v5_v2_lift_guard_adjustment(
    row: dict[str, Any],
    *,
    day_profile: dict[str, Any],
    mode: str,
) -> tuple[float, list[str]]:
    adjustment, notes = _postprocess_v2_overlay_adjustment(row, day_profile=day_profile, mode=mode)
    context = _postprocess_v5_lift_guard_context(row)
    if not context["lift_guard"]:
        return adjustment, notes

    guarded_notes = list(notes)
    if "v2_stale_low_suction_6_10" in guarded_notes:
        adjustment += 2.0
        guarded_notes.append("v5_stale_lift_relief")
    if "v2_strict_extra" in guarded_notes and context["fresh_lift"]:
        adjustment += 1.2
        guarded_notes.append("v5_strict_lift_relief")
    if context["controlled_low_suction_lift"]:
        adjustment += 1.0
        guarded_notes.append("v5_controlled_low_suction_lift")
    elif context["ma5_turning_low_mid"]:
        adjustment += 0.8
        guarded_notes.append("v5_ma5_turning_low_mid")
    elif context["active_low_mid_lift"]:
        adjustment += 0.6
        guarded_notes.append("v5_active_low_mid_lift")

    if day_profile["weak_day"] or day_profile["warning_far"]:
        adjustment += 0.4
        guarded_notes.append("v5_weak_day_lift_guard")

    if not guarded_notes:
        return 0.0, []
    return max(min(adjustment, 7.0), -10.0), guarded_notes


def _postprocess_v5_v2_lift_guard_blocked(row: dict[str, Any], day_profile: dict[str, Any]) -> bool:
    context = _postprocess_v5_lift_guard_context(row)
    if context["lift_guard"]:
        return False
    return _postprocess_v2_overlay_blocked(row, day_profile)


def _postprocess_v5_lift_guard_context(row: dict[str, Any]) -> dict[str, Any]:
    evidence = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    features = _postprocess_candidate_features(row)
    close_location = features["close_location"]
    ma_convergence = features["ma_convergence"]
    ma5_distance = features["ma5_distance"]
    low_suction_days = features["low_suction_days"]
    launch_bucket = features["launch_bucket"]
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ma5_slope = _float_or_none(evidence.get("ma5_slope_pct"))
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    active_strength = _candidate_active_strength(evidence)

    low_or_lower_mid = close_location is not None and close_location <= 0.58
    high_or_extreme = close_location is not None and close_location > 0.75
    near_ma5 = ma5_distance is None or ma5_distance <= 3.5
    tradable_ma5 = ma5_distance is None or ma5_distance <= 4.5
    ma10_tradable = ma10_distance is None or ma10_distance <= 4.8
    ma20_reclaimed = ma20_distance is None or ma20_distance >= -2.5
    ma_live = ma_convergence is not None and 3.0 <= ma_convergence <= 18.0
    ma_tight_normal = ma_convergence is not None and 3.0 <= ma_convergence <= 8.0
    fresh_lift = _candidate_fresh_lift(features, latest_change=latest_change, ma5_slope=ma5_slope)
    weak_launch = launch_bucket in {
        "high_close_launch",
        "repeated_launch",
        "other_confirmed_launch",
        "thin_volume_launch",
    }
    crowded_high_failure = bool(high_or_extreme and weak_launch)
    active_low_mid_lift = bool(
        features["active"]
        and low_or_lower_mid
        and tradable_ma5
        and ma10_tradable
        and ma20_reclaimed
        and ma_live
        and features["healthy_volume"]
        and fresh_lift
    )
    controlled_low_suction_lift = bool(
        3.0 <= low_suction_days <= 10.0
        and low_or_lower_mid
        and near_ma5
        and ma10_tradable
        and ma20_reclaimed
        and ma_tight_normal
        and features["healthy_volume"]
        and fresh_lift
        and not crowded_high_failure
    )
    ma5_turning_low_mid = bool(
        low_or_lower_mid
        and near_ma5
        and ma5_slope is not None
        and ma5_slope >= 0.10
        and ma20_reclaimed
        and not crowded_high_failure
    )
    lift_guard = bool(
        not high_or_extreme
        and not (ma5_distance is not None and ma5_distance > 4.8)
        and (active_low_mid_lift or controlled_low_suction_lift or ma5_turning_low_mid)
        and not (active_strength < 2.0 and latest_change is not None and latest_change < -0.5)
    )
    return {
        "fresh_lift": fresh_lift,
        "lift_guard": lift_guard,
        "active_low_mid_lift": active_low_mid_lift,
        "controlled_low_suction_lift": controlled_low_suction_lift,
        "ma5_turning_low_mid": ma5_turning_low_mid,
    }


def _postprocess_v6_v2_right_tail_guard_adjustment(
    row: dict[str, Any],
    *,
    day_profile: dict[str, Any],
    mode: str,
) -> tuple[float, list[str]]:
    adjustment, notes = _postprocess_v2_overlay_adjustment(row, day_profile=day_profile, mode=mode)
    context = _postprocess_v6_right_tail_context(row)
    guarded_notes = list(notes)
    if context["right_tail_guard"]:
        if "v2_high_repeated_launch_penalty" in guarded_notes:
            adjustment += 2.8
            guarded_notes.append("v6_high_active_right_tail_relief")
        if "v2_repeated_launch_penalty" in guarded_notes:
            adjustment += 1.4
            guarded_notes.append("v6_repeated_active_right_tail_relief")
        if "v2_extreme_close" in guarded_notes:
            adjustment += 1.0
            guarded_notes.append("v6_extreme_active_relief")
        adjustment += 0.8
        guarded_notes.append("v6_right_tail_guard")
    if context["low_lift_guard"]:
        if "v2_stale_low_suction_6_10" in guarded_notes:
            adjustment += 1.4
            guarded_notes.append("v6_low_lift_stale_relief")
        adjustment += 0.4
        guarded_notes.append("v6_low_lift_guard")
    if context["weak_warning_reject"]:
        adjustment -= 2.4
        guarded_notes.append("v6_weak_warning_reject")
    if context["near_resistance_crowded"]:
        adjustment -= 1.0
        guarded_notes.append("v6_near_resistance_crowded")
    if not guarded_notes:
        return 0.0, []
    return max(min(adjustment, 7.0), -10.0), guarded_notes


def _postprocess_v6_v2_right_tail_guard_blocked(row: dict[str, Any], day_profile: dict[str, Any]) -> bool:
    context = _postprocess_v6_right_tail_context(row)
    if context["right_tail_guard"] or context["low_lift_guard"]:
        return False
    if context["weak_warning_reject"]:
        return True
    return _postprocess_v2_overlay_blocked(row, day_profile)


def _postprocess_v6_right_tail_context(row: dict[str, Any]) -> dict[str, Any]:
    evidence = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    features = _postprocess_candidate_features(row)
    close_location = features["close_location"]
    ma5_distance = features["ma5_distance"]
    ma_convergence = features["ma_convergence"]
    low_suction_days = features["low_suction_days"]
    launch_bucket = features["launch_bucket"]
    warning_level = features["warning_level"]
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ma5_slope = _float_or_none(evidence.get("ma5_slope_pct"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    resistance_distance = _float_or_none(evidence.get("distance_to_resistance_pct"))
    active_strength = _candidate_active_strength(evidence)
    high_close = close_location is not None and close_location > 0.75
    low_or_lower_mid = close_location is not None and close_location <= 0.58
    controlled_mid = close_location is not None and 0.58 < close_location <= 0.75
    near_ma5 = ma5_distance is None or ma5_distance <= 3.2
    tradable_ma5 = ma5_distance is None or ma5_distance <= 4.8
    ma_live = ma_convergence is not None and 3.0 <= ma_convergence <= 18.0
    ma20_reclaimed = ma20_distance is None or ma20_distance >= -2.5
    fresh_lift = _candidate_fresh_lift(features, latest_change=latest_change, ma5_slope=ma5_slope)
    active_right_tail = bool(
        high_close
        and active_strength >= 3.0
        and features["large_bull_count"] >= 3.0
        and launch_bucket in {"high_close_launch", "repeated_launch", "balanced_first_lift", "not_low_suction"}
        and tradable_ma5
        and ma_live
        and warning_level <= 1.0
        and ma20_reclaimed
    )
    low_lift_guard = bool(
        (low_or_lower_mid or controlled_mid)
        and fresh_lift
        and near_ma5
        and ma_live
        and ma20_reclaimed
        and warning_level <= 2.0
        and (features["active"] or 3.0 <= low_suction_days <= 5.0)
    )
    weak_warning_reject = bool(
        warning_level >= 3.0
        and not active_right_tail
        and not low_lift_guard
        and (
            active_strength < 3.0
            or ma5_slope is None
            or ma5_slope < 0.10
            or ma5_distance is None
            or ma5_distance < -1.5
        )
    )
    near_resistance_crowded = bool(
        high_close
        and resistance_distance is not None
        and resistance_distance <= 2.0
        and not active_right_tail
    )
    return {
        "right_tail_guard": active_right_tail,
        "low_lift_guard": low_lift_guard,
        "weak_warning_reject": weak_warning_reject,
        "near_resistance_crowded": near_resistance_crowded,
    }


def _postprocess_v7_v2_soft_right_tail_adjustment(
    row: dict[str, Any],
    *,
    day_profile: dict[str, Any],
    mode: str,
) -> tuple[float, list[str]]:
    adjustment, notes = _postprocess_v2_overlay_adjustment(row, day_profile=day_profile, mode=mode)
    context = _postprocess_v7_soft_context(row)
    adjusted_notes = list(notes)

    if context["soft_right_tail"]:
        if "v2_high_repeated_launch_penalty" in adjusted_notes:
            adjustment += 4.2
            adjusted_notes.append("v7_soft_high_right_tail_relief")
        elif "v2_repeated_launch_penalty" in adjusted_notes:
            adjustment += 2.2
            adjusted_notes.append("v7_soft_repeated_right_tail_relief")
        adjustment += 1.2
        adjusted_notes.append("v7_soft_right_tail")

    if context["soft_low_lift"]:
        if "v2_stale_low_suction_6_10" in adjusted_notes:
            adjustment += 1.2
            adjusted_notes.append("v7_soft_low_lift_stale_relief")
        adjustment += 0.6
        adjusted_notes.append("v7_soft_low_lift")

    if context["weak_warning_soft_penalty"]:
        adjustment -= 1.3
        adjusted_notes.append("v7_weak_warning_soft_penalty")

    if context["high_close_near_resistance"]:
        adjustment -= 0.8
        adjusted_notes.append("v7_high_close_near_resistance")

    if not adjusted_notes:
        return 0.0, []
    return max(min(adjustment, 7.0), -10.0), adjusted_notes


def _postprocess_v7_v2_soft_right_tail_blocked(row: dict[str, Any], day_profile: dict[str, Any]) -> bool:
    return _postprocess_v2_overlay_blocked(row, day_profile)


def _postprocess_v7_soft_context(row: dict[str, Any]) -> dict[str, Any]:
    evidence = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    features = _postprocess_candidate_features(row)
    close_location = features["close_location"]
    ma5_distance = features["ma5_distance"]
    ma_convergence = features["ma_convergence"]
    low_suction_days = features["low_suction_days"]
    launch_bucket = features["launch_bucket"]
    warning_level = features["warning_level"]
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ma5_slope = _float_or_none(evidence.get("ma5_slope_pct"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    active_strength = _candidate_active_strength(evidence)

    high_close = close_location is not None and close_location > 0.75
    low_or_lower_mid = close_location is not None and close_location <= 0.58
    near_ma5 = ma5_distance is None or ma5_distance <= 3.2
    tradable_ma5 = ma5_distance is None or ma5_distance <= 3.8
    ma_live = ma_convergence is not None and 3.0 <= ma_convergence <= 18.0
    ma20_reclaimed = ma20_distance is None or ma20_distance >= -2.5
    fresh_lift = _candidate_fresh_lift(features, latest_change=latest_change, ma5_slope=ma5_slope)
    ma5_turning = ma5_slope is not None and ma5_slope >= 0.10

    soft_right_tail = bool(
        high_close
        and active_strength >= 3.0
        and features["large_bull_count"] >= 3.0
        and launch_bucket in {"high_close_launch", "repeated_launch", "balanced_first_lift", "not_low_suction"}
        and tradable_ma5
        and ma_live
        and warning_level <= 1.0
        and ma20_reclaimed
        and (ma5_turning or latest_change is None or latest_change <= 6.2)
    )
    soft_low_lift = bool(
        low_or_lower_mid
        and fresh_lift
        and near_ma5
        and ma_live
        and ma20_reclaimed
        and warning_level <= 1.0
        and (features["active"] or (3.0 <= low_suction_days <= 5.0 and ma5_turning))
    )
    weak_warning_soft_penalty = bool(
        warning_level >= 3.0
        and not soft_right_tail
        and not soft_low_lift
        and (
            active_strength < 3.0
            or ma5_slope is None
            or ma5_slope < 0.10
            or ma5_distance is None
            or ma5_distance < -1.5
        )
    )
    high_close_near_resistance = bool(
        high_close
        and not soft_right_tail
        and _float_or_none(evidence.get("distance_to_resistance_pct")) is not None
        and (_float_or_none(evidence.get("distance_to_resistance_pct")) or 999.0) <= 2.0
    )
    return {
        "soft_right_tail": soft_right_tail,
        "soft_low_lift": soft_low_lift,
        "weak_warning_soft_penalty": weak_warning_soft_penalty,
        "high_close_near_resistance": high_close_near_resistance,
    }


def _postprocess_v3_support_lift_adjustment(
    row: dict[str, Any],
    *,
    day_profile: dict[str, Any],
    mode: str,
) -> tuple[float, list[str]]:
    evidence = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    features = _postprocess_candidate_features(row)
    close_location = features["close_location"]
    ma_convergence = features["ma_convergence"]
    ma5_distance = features["ma5_distance"]
    launch_bucket = features["launch_bucket"]
    low_suction_days = features["low_suction_days"]
    warning_level = features["warning_level"]
    active_strength = _candidate_active_strength(evidence)
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ma5_slope = _float_or_none(evidence.get("ma5_slope_pct"))
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    active = features["active"]
    low_close = close_location is not None and close_location <= 0.35
    lower_mid_close = close_location is not None and 0.35 < close_location <= 0.58
    mid_close = close_location is not None and 0.58 < close_location <= 0.75
    high_close = close_location is not None and 0.75 < close_location <= 0.88
    extreme_close = close_location is not None and close_location > 0.88
    near_ma5 = ma5_distance is None or ma5_distance <= 3.5
    tradable_ma5 = ma5_distance is None or ma5_distance <= 5.5
    far_ma5 = ma5_distance is not None and ma5_distance > 5.5
    ma_tight_to_normal = ma_convergence is not None and 3.0 <= ma_convergence <= 10.0
    ma_live_trend = ma_convergence is not None and 10.0 < ma_convergence <= 18.0
    fresh_lift = bool(
        (latest_change is not None and 0.4 <= latest_change <= 5.8)
        or (ma5_slope is not None and ma5_slope >= 0.10)
        or (ma5_distance is not None and 0.0 <= ma5_distance <= 3.2)
    )
    support_lift = bool(
        active
        and (low_close or lower_mid_close or (mid_close and active_strength >= 4.0))
        and tradable_ma5
        and (ma_tight_to_normal or ma_live_trend)
        and features["healthy_volume"]
    )
    controlled_low_suction = bool(
        3.0 <= low_suction_days <= 5.0
        and (low_close or lower_mid_close)
        and near_ma5
        and ma_convergence is not None
        and ma_convergence <= 8.0
        and features["healthy_volume"]
        and fresh_lift
    )
    stale_without_lift = bool(
        6.0 <= low_suction_days <= 10.0
        and not (active and (low_close or lower_mid_close))
        and not fresh_lift
    )
    high_crowded_launch = bool(
        (high_close or extreme_close)
        and launch_bucket in {"high_close_launch", "repeated_launch", "other_confirmed_launch", "thin_volume_launch"}
    )
    adjustment = 0.0
    notes: list[str] = []

    if support_lift:
        adjustment += 4.2 if active_strength >= 4.0 else 3.2
        notes.append("v3_support_lift_active_low_mid")
        if low_close:
            adjustment += 0.8
            notes.append("v3_low_close_asymmetry")
        if ma_tight_to_normal:
            adjustment += 0.6
            notes.append("v3_ma_3_10_support_lift")
    elif active and mid_close and ma_live_trend and tradable_ma5 and features["healthy_volume"]:
        adjustment += 1.3
        notes.append("v3_active_mid_live_trend_small")

    if controlled_low_suction:
        adjustment += 1.8
        notes.append("v3_controlled_low_suction_lift")
    elif 3.0 <= low_suction_days <= 5.0 and lower_mid_close and near_ma5 and fresh_lift:
        adjustment += 0.8
        notes.append("v3_low_suction_buildup_watch_bonus")
    if active and lower_mid_close and features["large_bull_count"] >= 3.0 and (ma_tight_to_normal or ma_live_trend):
        adjustment += 1.0
        notes.append("v3_active_large_bull_lower_mid")

    if high_crowded_launch:
        adjustment -= 3.8
        notes.append("v3_high_crowded_launch")
        if far_ma5 or warning_level >= 2.0:
            adjustment -= 1.4
            notes.append("v3_high_crowded_far_or_warning")
    elif launch_bucket in {"repeated_launch", "other_confirmed_launch"} and not support_lift:
        adjustment -= 2.2
        notes.append("v3_non_support_repeated_or_other_confirmed")
    if stale_without_lift:
        adjustment -= 3.6
        notes.append("v3_stale_low_suction_no_fresh_lift")
    elif 6.0 <= low_suction_days <= 10.0 and not (active and (low_close or lower_mid_close)):
        adjustment -= 1.4
        notes.append("v3_stale_low_suction_needs_support")
    if far_ma5:
        adjustment -= 2.6
        notes.append("v3_far_ma5")
    elif ma5_distance is not None and ma5_distance > 3.5 and (high_close or extreme_close):
        adjustment -= 1.2
        notes.append("v3_high_close_lifted_ma5")
    if extreme_close:
        adjustment -= 2.2
        notes.append("v3_extreme_close")
    if ma_convergence is not None and ma_convergence < 3.0 and not active:
        adjustment -= 2.6
        notes.append("v3_tight_quiet_no_active")
    if ma10_distance is not None and ma10_distance > 6.0 and not support_lift:
        adjustment -= 1.0
        notes.append("v3_ma10_overextended_without_support")

    if day_profile["weak_day"] or day_profile["warning_far"]:
        if support_lift:
            adjustment += 0.8
            notes.append("v3_weak_day_keep_support_lift")
        elif high_crowded_launch or stale_without_lift:
            adjustment -= 1.6
            notes.append("v3_weak_day_punish_crowded_or_stale")
        elif not active and close_location is not None and close_location > 0.58:
            adjustment -= 0.9
            notes.append("v3_weak_day_inactive_mid_high")
    if evidence.get("dynamic_market_regime") == "false_bull" and warning_level >= 2.0 and not support_lift:
        adjustment -= 1.3
        notes.append("v3_false_bull_only_without_support")
    if evidence.get("dynamic_market_regime") == "choppy_rotation" and warning_level >= 2.0 and high_crowded_launch:
        adjustment -= 1.0
        notes.append("v3_choppy_high_crowded")

    if support_lift and adjustment < 0:
        adjustment = max(adjustment, -0.5)
        notes.append("v3_support_lift_floor")

    return (max(min(adjustment, 7.0), -10.0), notes) if notes else (0.0, [])


def _postprocess_v3_support_lift_blocked(row: dict[str, Any], day_profile: dict[str, Any]) -> bool:
    evidence = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    features = _postprocess_candidate_features(row)
    close_location = features["close_location"]
    ma5_distance = features["ma5_distance"]
    launch_bucket = features["launch_bucket"]
    warning_level = features["warning_level"]
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ma5_slope = _float_or_none(evidence.get("ma5_slope_pct"))
    active_low_mid = features["active"] and close_location is not None and close_location <= 0.58
    fresh_lift = bool(
        (latest_change is not None and 0.4 <= latest_change <= 5.8)
        or (ma5_slope is not None and ma5_slope >= 0.10)
        or (ma5_distance is not None and 0.0 <= ma5_distance <= 3.2)
    )
    if active_low_mid:
        return False
    if ma5_distance is not None and ma5_distance > 6.0 and warning_level >= 2.0:
        return True
    if 6.0 <= features["low_suction_days"] <= 10.0 and not features["active"] and not fresh_lift:
        return True
    if close_location is not None and close_location > 0.88 and warning_level >= 2.0:
        return True
    if (
        day_profile["weak_day"]
        and launch_bucket in {"high_close_launch", "repeated_launch", "other_confirmed_launch"}
        and close_location is not None
        and close_location > 0.75
    ):
        return True
    return False


def _postprocess_v4_launch_quality_adjustment(
    row: dict[str, Any],
    *,
    day_profile: dict[str, Any],
    mode: str,
) -> tuple[float, list[str]]:
    evidence = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    features = _postprocess_candidate_features(row)
    close_location = features["close_location"]
    ma_convergence = features["ma_convergence"]
    ma5_distance = features["ma5_distance"]
    launch_bucket = features["launch_bucket"]
    low_suction_days = features["low_suction_days"]
    warning_level = features["warning_level"]
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ma5_slope = _float_or_none(evidence.get("ma5_slope_pct"))
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    active_strength = _candidate_active_strength(evidence)
    active = features["active"]
    strong_active = features["strong_active"] or active_strength >= 4.0
    low_close = close_location is not None and close_location <= 0.35
    lower_mid_close = close_location is not None and 0.35 < close_location <= 0.58
    mid_close = close_location is not None and 0.58 < close_location <= 0.75
    high_close = close_location is not None and 0.75 < close_location <= 0.88
    extreme_close = close_location is not None and close_location > 0.88
    near_ma5 = ma5_distance is None or ma5_distance <= 3.5
    tradable_ma5 = ma5_distance is None or ma5_distance <= 4.5
    overextended_ma5 = ma5_distance is not None and ma5_distance > 6.0
    ma_tight = ma_convergence is not None and ma_convergence < 3.0
    ma_normal = ma_convergence is not None and 3.0 <= ma_convergence <= 10.0
    ma_live = ma_convergence is not None and 10.0 < ma_convergence <= 18.0
    healthy_volume = features["healthy_volume"]
    fresh_lift = _candidate_fresh_lift(features, latest_change=latest_change, ma5_slope=ma5_slope)
    ma10_tradable = ma10_distance is None or ma10_distance <= 4.8
    ma20_reclaimed = ma20_distance is None or ma20_distance >= -2.5
    launch_failure = launch_bucket in {"high_close_launch", "repeated_launch", "other_confirmed_launch", "thin_volume_launch"}
    support_lift = bool(
        active
        and (low_close or lower_mid_close or (mid_close and strong_active))
        and tradable_ma5
        and ma10_tradable
        and ma20_reclaimed
        and (ma_normal or ma_live)
        and healthy_volume
        and fresh_lift
    )
    controlled_low_suction = bool(
        3.0 <= low_suction_days <= 5.0
        and (low_close or lower_mid_close)
        and near_ma5
        and ma10_tradable
        and ma20_reclaimed
        and ma_convergence is not None
        and 3.0 <= ma_convergence <= 8.0
        and healthy_volume
        and fresh_lift
    )
    ma5_turning_low_mid = bool(
        (low_close or lower_mid_close)
        and near_ma5
        and ma5_slope is not None
        and ma5_slope >= 0.10
        and ma20_reclaimed
    )
    active_mid_live = bool(
        active
        and mid_close
        and near_ma5
        and ma_live
        and healthy_volume
        and not launch_failure
    )
    stale_no_lift = bool(6.0 <= low_suction_days <= 10.0 and not fresh_lift and active_strength < 3.0)
    tight_no_activation = bool(ma_tight and active_strength < 3.0 and not fresh_lift)
    high_crowded = bool((high_close or extreme_close) and launch_failure)
    confirmed_no_active = bool(launch_bucket == "other_confirmed_launch" and active_strength < 3.0)
    false_bull_weak = bool(
        evidence.get("dynamic_market_regime") == "false_bull"
        and warning_level >= 2.0
        and not support_lift
        and not (active and low_close and near_ma5)
    )
    adjustment = 0.0
    notes: list[str] = []

    if support_lift:
        adjustment += 4.6 if strong_active else 3.6
        notes.append("v4_support_lift")
        if low_close:
            adjustment += 0.8
            notes.append("v4_low_close_asymmetry")
        if ma5_turning_low_mid:
            adjustment += 0.8
            notes.append("v4_ma5_turning_low_mid")
    elif ma5_turning_low_mid and not stale_no_lift and not high_crowded:
        adjustment += 2.0
        notes.append("v4_ma5_turning_watch")
    if controlled_low_suction:
        adjustment += 1.8
        notes.append("v4_controlled_low_suction_lift")
    if active_mid_live:
        adjustment += 1.4 if strong_active else 0.8
        notes.append("v4_active_mid_live_trend")
    if active and close_location is not None and close_location <= 0.75 and features["large_bull_count"] >= 3.0 and (ma_normal or ma_live):
        adjustment += 1.0
        notes.append("v4_large_bull_controlled")

    if overextended_ma5:
        adjustment -= 4.4
        notes.append("v4_ma5_overextended_6pct")
        if warning_level >= 2.0:
            adjustment -= 1.2
            notes.append("v4_overextended_warning")
    if tight_no_activation:
        adjustment -= 3.2
        notes.append("v4_tight_quiet_no_activation")
    elif ma_tight and not support_lift and high_close:
        adjustment -= 1.6
        notes.append("v4_tight_high_close")
    if high_crowded:
        adjustment -= 3.8
        notes.append("v4_high_close_crowded_launch")
        if extreme_close:
            adjustment -= 1.0
            notes.append("v4_extreme_close_crowding")
    elif launch_bucket in {"repeated_launch", "other_confirmed_launch"} and not support_lift:
        adjustment -= 2.0
        notes.append("v4_repeated_or_other_without_support")
    if confirmed_no_active:
        adjustment -= 2.0
        notes.append("v4_confirmed_no_active_money")
    if stale_no_lift:
        adjustment -= 3.4
        notes.append("v4_stale_low_suction_no_lift")
    elif 6.0 <= low_suction_days <= 10.0 and not support_lift and active_strength < 3.0:
        adjustment -= 1.6
        notes.append("v4_stale_low_suction_weak")
    if false_bull_weak:
        adjustment -= 1.8 if warning_level <= 2.0 else 2.5
        notes.append("v4_false_bull_warning_weak_setup")
    if evidence.get("dynamic_market_regime") == "choppy_rotation" and warning_level >= 2.0 and high_crowded:
        adjustment -= 1.0
        notes.append("v4_choppy_high_crowded")
    if ma10_distance is not None and ma10_distance > 6.0 and not support_lift and not active:
        adjustment -= 1.2
        notes.append("v4_ma10_overextended_no_active")
    if ma20_distance is not None and ma20_distance < -3.0:
        adjustment -= 1.2
        notes.append("v4_ma20_not_reclaimed")

    if day_profile["weak_day"] or day_profile["warning_far"]:
        if support_lift and not high_crowded and not overextended_ma5:
            adjustment += 0.8
            notes.append("v4_weak_day_keep_support_lift")
        elif high_crowded or overextended_ma5 or tight_no_activation:
            adjustment -= 1.6
            notes.append("v4_weak_day_punish_first_down_signature")
        elif stale_no_lift:
            adjustment -= 1.2
            notes.append("v4_weak_day_stale_no_lift")

    if support_lift and adjustment < 0:
        adjustment = max(adjustment, -0.8)
        notes.append("v4_support_lift_floor")
    if not notes:
        return 0.0, []
    return max(min(adjustment, 7.5), -11.0), notes


def _postprocess_v4_launch_quality_blocked(row: dict[str, Any], day_profile: dict[str, Any]) -> bool:
    evidence = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    features = _postprocess_candidate_features(row)
    close_location = features["close_location"]
    ma_convergence = features["ma_convergence"]
    ma5_distance = features["ma5_distance"]
    launch_bucket = features["launch_bucket"]
    warning_level = features["warning_level"]
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ma5_slope = _float_or_none(evidence.get("ma5_slope_pct"))
    active_strength = _candidate_active_strength(evidence)
    fresh_lift = _candidate_fresh_lift(features, latest_change=latest_change, ma5_slope=ma5_slope)
    active_low = bool(features["active"] and close_location is not None and close_location <= 0.35 and (ma5_distance is None or ma5_distance <= 3.5))
    support_lift = bool(features["active"] and close_location is not None and close_location <= 0.58 and fresh_lift and (ma5_distance is None or ma5_distance <= 4.5))
    if active_low:
        return False
    if support_lift and not (day_profile["weak_day"] and warning_level >= 3.0 and launch_bucket in {"high_close_launch", "repeated_launch"}):
        return False
    if ma5_distance is not None and ma5_distance > 6.0 and warning_level >= 2.0:
        return True
    if ma_convergence is not None and ma_convergence < 3.0 and active_strength < 3.0 and not fresh_lift and warning_level >= 2.0:
        return True
    if 6.0 <= features["low_suction_days"] <= 10.0 and active_strength < 3.0 and not fresh_lift:
        return True
    if close_location is not None and close_location > 0.88 and launch_bucket in {"high_close_launch", "repeated_launch", "other_confirmed_launch"} and warning_level >= 2.0:
        return True
    return bool(
        day_profile["weak_day"]
        and launch_bucket in {"high_close_launch", "repeated_launch", "other_confirmed_launch", "thin_volume_launch"}
        and close_location is not None
        and close_location > 0.75
        and active_strength < 4.0
    )


def _postprocess_day_profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    features = [_postprocess_candidate_features(row) for row in rows]
    count = len(features)
    if count <= 0:
        return {
            "count": 0,
            "active_ratio": 0.0,
            "low_mid_ratio": 0.0,
            "high_ratio": 0.0,
            "weak_launch_ratio": 0.0,
            "active_low_mid_ratio": 0.0,
            "active_high_weak_ratio": 0.0,
            "stale_quiet_ratio": 0.0,
            "weak_day": False,
            "strong_day": False,
            "warning_far": False,
        }
    active_ratio = _bool_ratio(features, "active")
    low_mid_ratio = _bool_ratio(features, "low_mid_close")
    high_ratio = _bool_ratio(features, "high_close")
    weak_launch_ratio = _bool_ratio(features, "weak_launch")
    active_low_mid_ratio = _bool_ratio(features, "active_low_mid")
    active_high_weak_ratio = sum(1 for item in features if item["active"] and item["high_weak_launch"]) / count
    stale_quiet_ratio = sum(1 for item in features if item["stale_quiet"] or item["tight_quiet"]) / count
    weak_day = (
        (active_ratio >= 0.55 and high_ratio >= 0.50 and weak_launch_ratio >= 0.40)
        or (high_ratio >= 0.55 and weak_launch_ratio >= 0.35)
        or (stale_quiet_ratio >= 0.35 and active_low_mid_ratio < 0.25)
    )
    strong_day = active_low_mid_ratio >= 0.30 and low_mid_ratio >= 0.45 and high_ratio <= 0.30 and weak_launch_ratio <= 0.30
    warning_far = active_high_weak_ratio >= 0.25 or (
        high_ratio >= 0.45 and weak_launch_ratio >= 0.30 and active_low_mid_ratio < 0.20
    )
    return {
        "count": count,
        "active_ratio": round(active_ratio, 4),
        "low_mid_ratio": round(low_mid_ratio, 4),
        "high_ratio": round(high_ratio, 4),
        "weak_launch_ratio": round(weak_launch_ratio, 4),
        "active_low_mid_ratio": round(active_low_mid_ratio, 4),
        "active_high_weak_ratio": round(active_high_weak_ratio, 4),
        "stale_quiet_ratio": round(stale_quiet_ratio, 4),
        "weak_day": weak_day,
        "strong_day": strong_day,
        "warning_far": warning_far,
    }


def _postprocess_candidate_features(row: dict[str, Any]) -> dict[str, Any]:
    evidence = row.get("reason") if isinstance(row.get("reason"), dict) else {}
    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    warning_level = _float_or_none(evidence.get("market_warning_level")) or 0.0
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    risk_penalty = _float_or_none(evidence.get("risk_penalty")) or 0.0
    large_bull_count = _float_or_none(evidence.get("large_bull_count_20d")) or 0.0
    strength = _candidate_active_strength(evidence)
    active = strength >= 3.0 or bool(evidence.get("recent_limit_up_20d")) or large_bull_count >= 3.0
    strong_active = strength >= 4.0 or large_bull_count >= 4.0
    weak_launch = launch_bucket in {
        "high_close_launch",
        "thin_volume_launch",
        "other_confirmed_launch",
        "repeated_launch",
        "unconfirmed_buildup",
    }
    high_close = close_location is not None and close_location > 0.75
    extreme_high_close = close_location is not None and close_location > 0.88
    low_mid_close = close_location is not None and close_location <= 0.58
    lower_mid_close = close_location is not None and 0.35 <= close_location <= 0.58
    mid_close = close_location is not None and 0.58 < close_location <= 0.75
    near_ma5 = ma5_distance is None or ma5_distance <= 3.5
    healthy_volume = volume_ratio is None or 0.65 <= volume_ratio <= 2.2
    active_low_mid = bool(
        active
        and low_mid_close
        and ma_convergence is not None
        and 3.0 <= ma_convergence <= 18.0
        and near_ma5
        and healthy_volume
    )
    active_mid = bool(
        active
        and mid_close
        and ma_convergence is not None
        and 6.0 <= ma_convergence <= 18.0
        and near_ma5
        and healthy_volume
    )
    high_weak_launch = bool(high_close and weak_launch)
    stale_quiet = bool(
        low_suction_days >= 6.0
        and not active
        and launch_bucket not in {"balanced_first_lift", "late_pullback_launch", "other_confirmed_launch"}
    )
    tight_quiet = bool(ma_convergence is not None and ma_convergence < 3.0 and not active)
    far_ma5 = bool(ma5_distance is not None and ma5_distance > 5.5)
    extreme_high_far_ma5 = bool(extreme_high_close and ma5_distance is not None and ma5_distance > 3.5)
    return {
        "launch_bucket": launch_bucket,
        "close_location": close_location,
        "ma_convergence": ma_convergence,
        "ma5_distance": ma5_distance,
        "volume_ratio": volume_ratio,
        "low_suction_days": low_suction_days,
        "warning_level": warning_level,
        "latest_change": latest_change,
        "risk_penalty": risk_penalty,
        "large_bull_count": large_bull_count,
        "active": active,
        "strong_active": strong_active,
        "weak_launch": weak_launch,
        "high_close": high_close,
        "extreme_high_close": extreme_high_close,
        "low_mid_close": low_mid_close,
        "lower_mid_close": lower_mid_close,
        "active_low_mid": active_low_mid,
        "active_mid": active_mid,
        "high_weak_launch": high_weak_launch,
        "stale_quiet": stale_quiet,
        "tight_quiet": tight_quiet,
        "far_ma5": far_ma5,
        "extreme_high_far_ma5": extreme_high_far_ma5,
        "healthy_volume": healthy_volume,
    }


def _postprocess_change_summary(
    *,
    base_keys: set[tuple[date, str]],
    variant_rows: list[dict[str, Any]],
    base_report: dict[str, Any],
    variant_report: dict[str, Any],
) -> dict[str, Any]:
    variant_keys = _candidate_identity_keys(variant_rows)
    removed_keys = base_keys - variant_keys
    added_keys = variant_keys - base_keys
    if not removed_keys and not added_keys:
        return {
            "removed_count": 0,
            "added_count": 0,
            "removed_quality": _candidate_metric_summary([]),
            "added_quality": _candidate_metric_summary([]),
        }

    removed_path_rows = [
        row
        for row in base_report["rows"]
        if (_as_date(row.get("signal_date")), str(row.get("vt_symbol") or "").strip().upper()) in removed_keys
    ]
    added_path_rows = [
        row
        for row in variant_report["rows"]
        if (_as_date(row.get("signal_date")), str(row.get("vt_symbol") or "").strip().upper()) in added_keys
    ]
    return {
        "removed_count": len(removed_keys),
        "added_count": len(added_keys),
        "removed_quality": _candidate_metric_summary(removed_path_rows),
        "added_quality": _candidate_metric_summary(added_path_rows),
    }


def _postprocess_sell_key(params: BacktestParams) -> tuple[bool, float, float, float]:
    return (
        bool(params.enable_mid_profit_giveback_stop),
        float(params.mid_profit_giveback_min_high_gain_pct),
        float(params.mid_profit_giveback_max_current_gain_pct),
        float(params.mid_profit_giveback_drawdown_pct),
    )


def _candidate_identity_keys(rows: list[dict[str, Any]]) -> set[tuple[date, str]]:
    result: set[tuple[date, str]] = set()
    for row in rows:
        trade_date = _as_date(row.get("trade_date") or row.get("signal_date"))
        symbol = str(row.get("vt_symbol") or "").strip().upper()
        if trade_date is not None and symbol:
            result.add((trade_date, symbol))
    return result


def _bool_ratio(rows: list[dict[str, Any]], key: str) -> float:
    return sum(1 for row in rows if row.get(key)) / len(rows) if rows else 0.0


def _baseline_top_candidate_rows(backtest_id: int, *, start: date, end: date, top_n: int) -> list[dict[str, Any]]:
    with session_scope() as session:
        run = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == backtest_id)).mappings().first()
        if not run:
            return []
        lower = max(start, run["start_date"])
        upper = min(end, run["end_date"])
        recommendation_rows = session.execute(
            select(schema.quant_recommendations)
            .where(
                schema.quant_recommendations.c.strategy_id == run["strategy_id"],
                schema.quant_recommendations.c.strategy_version == run["strategy_version"],
                schema.quant_recommendations.c.trade_date >= lower,
                schema.quant_recommendations.c.trade_date <= upper,
                schema.quant_recommendations.c.rank <= top_n,
                schema.quant_recommendations.c.action == "BUY",
            )
            .order_by(schema.quant_recommendations.c.trade_date, schema.quant_recommendations.c.rank, schema.quant_recommendations.c.vt_symbol)
        ).mappings().all()
        if recommendation_rows:
            return [dict(row) | {"source": "baseline_quant_recommendations"} for row in recommendation_rows]
        signal_rows = session.execute(
            select(schema.backtest_signal_events)
            .where(
                schema.backtest_signal_events.c.backtest_id == backtest_id,
                schema.backtest_signal_events.c.signal_date >= lower,
                schema.backtest_signal_events.c.signal_date <= upper,
                schema.backtest_signal_events.c.side == "BUY",
            )
            .order_by(schema.backtest_signal_events.c.signal_date, schema.backtest_signal_events.c.id)
        ).mappings().all()
    return _signal_event_top_candidate_rows([dict(row) for row in signal_rows], top_n=top_n)


def _signal_event_top_candidate_rows(rows: list[dict[str, Any]], *, top_n: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
        execution = raw.get("candidate_execution") if isinstance(raw.get("candidate_execution"), dict) else {}
        rank = _int_or_none(execution.get("execution_candidate_rank")) or _int_or_none(execution.get("raw_signal_rank"))
        if rank is None or rank > top_n:
            continue
        candidates.append(
            {
                "trade_date": _as_date(row.get("signal_date") or row.get("trade_date")),
                "vt_symbol": str(row.get("vt_symbol") or ""),
                "rank": rank,
                "action": "BUY",
                "total_score": row.get("score"),
                "reason": evidence,
                "source": "baseline_backtest_signal_events",
            }
        )
    return [row for row in candidates if row.get("trade_date") and row.get("vt_symbol")]


def _bars_for_candidate_rows(rows: list[dict[str, Any]], *, start: date, end: date) -> dict[str, list[Any]]:
    symbols = sorted({str(row.get("vt_symbol") or "").strip().upper() for row in rows if row.get("vt_symbol")})
    if not symbols:
        return {}
    with session_scope() as session:
        return backtest_engine._load_all_bars(session, symbols, backtest_engine._lookback_start(start), end)


def _candidate_path_report(
    candidates: list[dict[str, Any]],
    bars_by_symbol: dict[str, list[Any]],
    params: BacktestParams,
    *,
    top_n: int,
) -> dict[str, Any]:
    path_rows = [
        row
        for candidate in candidates
        if (row := _candidate_path_row(candidate, bars_by_symbol, params)) is not None
    ]
    daily = _candidate_daily_cohorts(path_rows, top_n=top_n)
    return {
        "rows": path_rows,
        "daily": daily,
        "top_n": top_n,
        "candidate_count": len(candidates),
        "evaluated_count": sum(1 for row in path_rows if _is_evaluated_candidate_path(row)),
    }


def _candidate_path_report_cached(
    candidates: list[dict[str, Any]],
    bars_by_symbol: dict[str, list[Any]],
    params: BacktestParams,
    *,
    top_n: int,
    path_cache: dict[tuple[tuple[Any, ...], date, str], dict[str, Any] | None],
) -> dict[str, Any]:
    path_rows = []
    sell_key = _postprocess_sell_key(params)
    for candidate in candidates:
        signal_date = _as_date(candidate.get("trade_date") or candidate.get("signal_date"))
        symbol = str(candidate.get("vt_symbol") or "").strip().upper()
        if signal_date is None or not symbol:
            continue
        cache_key = (sell_key, signal_date, symbol)
        if cache_key not in path_cache:
            path_cache[cache_key] = _candidate_path_row(candidate, bars_by_symbol, params)
        cached = path_cache[cache_key]
        if cached is None:
            continue
        path_rows.append(
            dict(cached)
            | {
                "rank": _int_or_none(candidate.get("rank")),
                "score": _float_or_none(candidate.get("total_score") or candidate.get("score")),
                "source": candidate.get("source"),
                "entry_model": cached.get("entry_model"),
            }
        )
    daily = _candidate_daily_cohorts(path_rows, top_n=top_n)
    return {
        "rows": path_rows,
        "daily": daily,
        "top_n": top_n,
        "candidate_count": len(candidates),
        "evaluated_count": sum(1 for row in path_rows if _is_evaluated_candidate_path(row)),
    }


def _candidate_path_row(
    candidate: dict[str, Any],
    bars_by_symbol: dict[str, list[Any]],
    params: BacktestParams,
) -> dict[str, Any] | None:
    signal_date = _as_date(candidate.get("trade_date") or candidate.get("signal_date"))
    symbol = str(candidate.get("vt_symbol") or "").strip().upper()
    if signal_date is None or not symbol:
        return None
    entry_row = dict(candidate)
    entry_row["trade_date"] = signal_date
    entry_row["vt_symbol"] = symbol
    cluster = CandidateCluster(
        vt_symbol=symbol,
        rows=(entry_row,),
        cluster_start_date=signal_date,
        cluster_end_date=signal_date,
        entry_row=entry_row,
    )
    result = _simulate_candidate_path_trade(
        cluster,
        bars_by_symbol.get(symbol, []),
        params=params,
        sell_reason_fn=_candidate_sell_reason,
        limit_up_open_fn=backtest_engine._is_limit_up_open,
        limit_down_open_fn=backtest_engine._is_limit_down_open,
        buy_signal_dates={signal_date},
    )
    entry_model = "legacy_next_open"
    if params.enable_high_risk_d2_follow_through_entry and _is_high_risk_follow_through_candidate(candidate):
        entry_model = "high_risk_d2_follow_through"
    discontinuity = _candidate_price_discontinuity(
        bars_by_symbol.get(symbol, []),
        vt_symbol=symbol,
        signal_date=signal_date,
        entry_execute_date=result.entry_execute_date,
        exit_execute_date=result.exit_execute_date,
    )
    return {
        "signal_date": result.entry_signal_date,
        "vt_symbol": symbol,
        "name": candidate.get("name"),
        "rank": _int_or_none(candidate.get("rank")),
        "score": _float_or_none(candidate.get("total_score") or candidate.get("score")),
        "reason": candidate.get("reason") if isinstance(candidate.get("reason"), dict) else {},
        "status": result.status,
        "entry_execute_date": result.entry_execute_date,
        "exit_execute_date": result.exit_execute_date,
        "return_pct": result.return_pct,
        "max_drawdown_pct": result.max_drawdown_pct,
        "max_runup_pct": result.max_runup_pct,
        "holding_days": result.holding_days,
        "exit_reason": result.exit_reason,
        "source": candidate.get("source"),
        "entry_model": entry_model,
        "has_price_discontinuity": bool(discontinuity),
        "first_price_discontinuity_date": discontinuity.get("trade_date") if discontinuity else None,
        "first_price_discontinuity_open_gap_pct": discontinuity.get("open_gap_pct") if discontinuity else None,
        "first_price_discontinuity_close_gap_pct": discontinuity.get("close_gap_pct") if discontinuity else None,
        "first_price_discontinuity_change_pct": discontinuity.get("change_pct") if discontinuity else None,
    }


def _simulate_candidate_path_trade(
    cluster: CandidateCluster,
    bars: list[Bar],
    *,
    params: BacktestParams,
    sell_reason_fn,
    limit_up_open_fn=None,
    limit_down_open_fn=None,
    buy_signal_dates: set[date] | None = None,
) -> IndependentTradeResult:
    if not params.enable_high_risk_d2_follow_through_entry:
        return simulate_independent_candidate_trade(
            cluster,
            bars,
            params=params,
            sell_reason_fn=sell_reason_fn,
            limit_up_open_fn=limit_up_open_fn,
            limit_down_open_fn=limit_down_open_fn,
            buy_signal_dates=buy_signal_dates,
        )
    if not _is_high_risk_follow_through_candidate(cluster.entry_row):
        return simulate_independent_candidate_trade(
            cluster,
            bars,
            params=params,
            sell_reason_fn=sell_reason_fn,
            limit_up_open_fn=limit_up_open_fn,
            limit_down_open_fn=limit_down_open_fn,
            buy_signal_dates=buy_signal_dates,
        )
    return _simulate_d2_follow_through_candidate_trade(
        cluster,
        bars,
        params=params,
        sell_reason_fn=sell_reason_fn,
        limit_up_open_fn=limit_up_open_fn,
        limit_down_open_fn=limit_down_open_fn,
        buy_signal_dates=buy_signal_dates,
    )


def _simulate_d2_follow_through_candidate_trade(
    cluster: CandidateCluster,
    bars: list[Bar],
    *,
    params: BacktestParams,
    sell_reason_fn,
    limit_up_open_fn=None,
    limit_down_open_fn=None,
    buy_signal_dates: set[date] | None = None,
) -> IndependentTradeResult:
    sorted_bars = sorted(bars, key=lambda bar: bar.trade_date)
    signal_date = _as_date(cluster.entry_row.get("trade_date") or cluster.entry_row.get("signal_date")) or cluster.cluster_start_date
    d1_index = next((index for index, bar in enumerate(sorted_bars) if bar.trade_date > signal_date), None)
    if d1_index is None:
        return _candidate_missing_trade(cluster, signal_date, "no_execute_bar")
    if d1_index >= len(sorted_bars) - 1:
        return _candidate_missing_trade(cluster, signal_date, "no_d2_execute_bar", execute_date=sorted_bars[d1_index].trade_date)

    d1_bar = sorted_bars[d1_index]
    if not _passes_d1_follow_through_confirmation(d1_bar):
        return _candidate_missing_trade(cluster, signal_date, "d1_follow_through_failed", execute_date=d1_bar.trade_date)

    entry_bar = sorted_bars[d1_index + 1]
    if limit_up_open_fn is not None and limit_up_open_fn(entry_bar):
        return _candidate_missing_trade(cluster, signal_date, "limit_up_open_blocked", execute_date=entry_bar.trade_date)

    entry_price = float(entry_bar.open_price)
    position = _candidate_path_position(cluster, entry_bar, entry_price)
    current_buy_signal_dates = buy_signal_dates or set()

    for index in range(d1_index + 1, len(sorted_bars)):
        bar = sorted_bars[index]
        position.visible_holding_bars += 1
        position.last_price = bar.close_price
        position.highest_price = max(position.highest_price, bar.high_price)
        position.lowest_price = min(position.lowest_price if position.lowest_price is not None else bar.low_price, bar.low_price)
        sell_reason = sell_reason_fn(
            position,
            bar,
            bar.trade_date,
            params,
            current_buy_signal=bar.trade_date in current_buy_signal_dates,
            replacement_available=False,
        )
        if not sell_reason or bar.trade_date <= position.entry_date:
            continue
        if index >= len(sorted_bars) - 1:
            return _candidate_open_trade(cluster, signal_date, entry_bar.trade_date, entry_price, sorted_bars[d1_index + 1 :])
        exit_bar = sorted_bars[index + 1]
        if limit_down_open_fn is not None and limit_down_open_fn(exit_bar):
            continue
        return _candidate_closed_trade(
            cluster,
            signal_date=signal_date,
            entry_execute_date=entry_bar.trade_date,
            entry_price=entry_price,
            exit_signal_date=bar.trade_date,
            exit_execute_date=exit_bar.trade_date,
            exit_price=float(exit_bar.open_price),
            exit_reason=str(sell_reason),
            window=sorted_bars[d1_index + 1 : index + 2],
        )

    return _candidate_open_trade(cluster, signal_date, entry_bar.trade_date, entry_price, sorted_bars[d1_index + 1 :])


def _is_high_risk_follow_through_candidate(candidate: dict[str, Any]) -> bool:
    evidence = candidate.get("reason") if isinstance(candidate.get("reason"), dict) else candidate
    launch_bucket = str(evidence.get("low_suction_launch_quality_bucket") or "")
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    active_strength = _candidate_active_strength(evidence)
    weak_launch = launch_bucket in {"high_close_launch", "thin_volume_launch", "other_confirmed_launch", "repeated_launch"}
    high_close = close_location is not None and close_location > 0.75
    stale_low_suction = low_suction_days >= 6 and active_strength < 3.0
    tight_quiet = ma_convergence is not None and ma_convergence < 3.0 and active_strength < 3.0
    return (high_close and (weak_launch or active_strength < 3.0)) or stale_low_suction or tight_quiet


def _candidate_price_discontinuity(
    bars: list[Bar],
    *,
    vt_symbol: str,
    signal_date: date,
    entry_execute_date: date | None,
    exit_execute_date: date | None,
) -> dict[str, Any] | None:
    if entry_execute_date is None:
        return None
    sorted_bars = sorted(bars, key=lambda bar: bar.trade_date)
    upper = exit_execute_date or (sorted_bars[-1].trade_date if sorted_bars else entry_execute_date)
    first_index = next((index for index, bar in enumerate(sorted_bars) if bar.trade_date >= entry_execute_date), None)
    if first_index is None:
        return None
    for index in range(max(first_index, 1), len(sorted_bars)):
        bar = sorted_bars[index]
        if bar.trade_date > upper:
            break
        previous = sorted_bars[index - 1]
        if previous.trade_date < signal_date:
            continue
        discontinuity = _bar_price_discontinuity(previous, bar, vt_symbol=vt_symbol)
        if discontinuity:
            return discontinuity
    return None


def _bar_price_discontinuity(previous: Bar, current: Bar, *, vt_symbol: str, threshold: float | None = None) -> dict[str, Any] | None:
    open_gap = _pct_return(float(current.open_price), float(previous.close_price))
    close_gap = _pct_return(float(current.close_price), float(previous.close_price))
    if open_gap is None or close_gap is None:
        return None
    board_threshold = threshold if threshold is not None else _price_discontinuity_threshold(vt_symbol)
    change_pct = _float_or_none(current.change_pct)
    if max(abs(open_gap), abs(close_gap)) < board_threshold:
        return None
    if change_pct is not None and abs(change_pct) >= board_threshold - 0.5:
        return None
    return {
        "trade_date": current.trade_date,
        "open_gap_pct": round(open_gap, 4),
        "close_gap_pct": round(close_gap, 4),
        "change_pct": change_pct,
        "previous_close": float(previous.close_price),
        "open_price": float(current.open_price),
        "close_price": float(current.close_price),
    }


def _price_discontinuity_threshold(vt_symbol: str) -> float:
    board = stock_board(vt_symbol)
    if board == "bse":
        return 32.0
    if board in {"star", "chinext"}:
        return 22.0
    return 12.0


def _candidate_active_strength(evidence: dict[str, Any]) -> float:
    strength = 0.0
    if evidence.get("recent_limit_up_20d") or (_float_or_none(evidence.get("near_limit_up_count_20d")) or 0.0) >= 1:
        strength += 2.0
    large_bull_count = _float_or_none(evidence.get("large_bull_count_20d")) or 0.0
    if large_bull_count >= 3:
        strength += 2.0
    elif large_bull_count >= 1:
        strength += 1.0
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    if volume_ratio is not None and volume_ratio >= 1.6:
        strength += 1.0
    if evidence.get("persistent_volume_expansion"):
        strength += 1.0
    return strength


def _passes_d1_follow_through_confirmation(bar: Bar) -> bool:
    if bar.open_price <= 0 or bar.high_price <= bar.low_price:
        return False
    intraday_return = (float(bar.close_price) / float(bar.open_price) - 1.0) * 100.0
    close_position = (float(bar.close_price) - float(bar.low_price)) / (float(bar.high_price) - float(bar.low_price))
    daily_change = _float_or_none(bar.change_pct)
    return intraday_return > -2.5 and close_position >= 0.40 and (daily_change is None or daily_change > -4.0)


def _candidate_path_position(cluster: CandidateCluster, entry_bar: Bar, entry_price: float):
    return backtest_engine.Position(
        vt_symbol=cluster.vt_symbol,
        name=None,
        volume=1,
        cost_price=entry_price,
        entry_date=entry_bar.trade_date,
        highest_price=max(entry_price, float(entry_bar.high_price)),
        lowest_price=min(entry_price, float(entry_bar.low_price)),
        reason=dict(cluster.entry_row.get("reason") or {}),
        last_price=float(entry_bar.close_price),
    )


def _candidate_missing_trade(
    cluster: CandidateCluster,
    signal_date: date,
    status: str,
    *,
    execute_date: date | None = None,
) -> IndependentTradeResult:
    return IndependentTradeResult(
        status=status,
        cluster=cluster,
        entry_signal_date=signal_date,
        entry_execute_date=execute_date,
        entry_price=None,
        exit_signal_date=None,
        exit_execute_date=None,
        exit_price=None,
        return_pct=None,
        max_drawdown_pct=None,
        max_runup_pct=None,
        holding_days=None,
        exit_reason=None,
    )


def _candidate_open_trade(
    cluster: CandidateCluster,
    signal_date: date,
    entry_execute_date: date,
    entry_price: float,
    window: list[Bar],
) -> IndependentTradeResult:
    last_close = float(window[-1].close_price) if window else entry_price
    return IndependentTradeResult(
        status="open",
        cluster=cluster,
        entry_signal_date=signal_date,
        entry_execute_date=entry_execute_date,
        entry_price=entry_price,
        exit_signal_date=None,
        exit_execute_date=None,
        exit_price=None,
        return_pct=_pct_return(last_close, entry_price),
        max_drawdown_pct=_candidate_window_drawdown_pct(window, entry_price),
        max_runup_pct=_candidate_window_runup_pct(window, entry_price),
        holding_days=len(window),
        exit_reason="open",
    )


def _candidate_closed_trade(
    cluster: CandidateCluster,
    *,
    signal_date: date,
    entry_execute_date: date,
    entry_price: float,
    exit_signal_date: date,
    exit_execute_date: date,
    exit_price: float,
    exit_reason: str,
    window: list[Bar],
) -> IndependentTradeResult:
    return IndependentTradeResult(
        status="closed",
        cluster=cluster,
        entry_signal_date=signal_date,
        entry_execute_date=entry_execute_date,
        entry_price=entry_price,
        exit_signal_date=exit_signal_date,
        exit_execute_date=exit_execute_date,
        exit_price=exit_price,
        return_pct=_pct_return(exit_price, entry_price),
        max_drawdown_pct=_candidate_window_drawdown_pct(window, entry_price),
        max_runup_pct=_candidate_window_runup_pct(window, entry_price),
        holding_days=len(window),
        exit_reason=exit_reason,
    )


def _pct_return(price: float, base: float) -> float | None:
    if base <= 0:
        return None
    return (float(price) / float(base) - 1.0) * 100.0


def _candidate_window_drawdown_pct(window: list[Bar], entry_price: float) -> float | None:
    if not window or entry_price <= 0:
        return None
    return _pct_return(min(float(bar.low_price) for bar in window), entry_price)


def _candidate_window_runup_pct(window: list[Bar], entry_price: float) -> float | None:
    if not window or entry_price <= 0:
        return None
    return _pct_return(max(float(bar.high_price) for bar in window), entry_price)


def _candidate_daily_cohorts(rows: list[dict[str, Any]], *, top_n: int) -> dict[date, dict[str, Any]]:
    grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        signal_date = _as_date(row.get("signal_date"))
        rank = _int_or_none(row.get("rank"))
        if signal_date is not None and rank is not None and rank <= top_n:
            grouped[signal_date].append(row)
    return {
        signal_date: {
            "signal_date": signal_date,
            **_candidate_metric_summary(date_rows),
        }
        for signal_date, date_rows in grouped.items()
        if any(_is_evaluated_candidate_path(row) for row in date_rows)
    }


def _paired_candidate_cohort_comparison(
    current: dict[str, Any],
    baseline: dict[str, Any],
    *,
    baseline_id: int,
    top_n: int,
    max_common_dates: int,
) -> dict[str, Any]:
    common_dates = sorted(set(current["daily"]) & set(baseline["daily"]))
    if max_common_dates > 0:
        common_dates = common_dates[-max_common_dates:]
    current_overall = _candidate_overall_for_dates(current, common_dates)
    baseline_overall = _candidate_overall_for_dates(baseline, common_dates)
    paired_days = [_candidate_day_delta(current["daily"][day], baseline["daily"][day]) for day in common_dates]
    return {
        "baseline_id": baseline_id,
        "top_n": top_n,
        "common_candidate_day_count": len(common_dates),
        "current_candidate_count": current.get("candidate_count"),
        "baseline_candidate_count": baseline.get("candidate_count"),
        "current_overall": current_overall,
        "baseline_overall": baseline_overall,
        "return_delta": _delta(current_overall.get("average_return_pct"), baseline_overall.get("average_return_pct")),
        "win_rate_delta": _delta(current_overall.get("win_rate"), baseline_overall.get("win_rate")),
        "average_drawdown_delta": _delta(current_overall.get("average_max_drawdown_pct"), baseline_overall.get("average_max_drawdown_pct")),
        "worst_drawdown_delta": _delta(current_overall.get("worst_max_drawdown_pct"), baseline_overall.get("worst_max_drawdown_pct")),
        "paired_day_drawdown_win_rate": _paired_day_win_rate(paired_days, "average_drawdown_delta"),
        "paired_day_return_win_rate": _paired_day_win_rate(paired_days, "return_delta"),
        "paired_days_sample": paired_days[:20],
        "method": (
            "无仓位候选质量同日配对：每个共同候选日分别取 top20，"
            "每只票独立 D+1 开盘入场，按当前策略卖点逐日退出；"
            "不看现金、最大持仓、满仓、已有持仓或换仓；"
            "最终以所有共同候选日的候选路径整体汇总为主，日胜负只作辅助。"
        ),
    }


def _candidate_overall_for_dates(report: dict[str, Any], dates: list[date]) -> dict[str, Any]:
    date_set = set(dates)
    rows = [row for row in report["rows"] if _as_date(row.get("signal_date")) in date_set]
    daily = [report["daily"][day] for day in dates if day in report["daily"]]
    summary = _candidate_metric_summary(rows)
    summary["candidate_day_count"] = len(daily)
    summary["average_daily_cohort_return_pct"] = _avg(item.get("average_return_pct") for item in daily)
    summary["average_daily_cohort_drawdown_pct"] = _avg(item.get("average_max_drawdown_pct") for item in daily)
    summary["worst_daily_cohort_drawdown_pct"] = _min_value(item.get("worst_max_drawdown_pct") for item in daily)
    summary["daily_cohort_win_rate"] = _ratio(
        sum(1 for item in daily if (_float_or_none(item.get("average_return_pct")) or 0.0) > 0),
        len(daily),
    )
    return summary


def _candidate_day_delta(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_date": current.get("signal_date"),
        "return_delta": _delta(current.get("average_return_pct"), baseline.get("average_return_pct")),
        "average_drawdown_delta": _delta(current.get("average_max_drawdown_pct"), baseline.get("average_max_drawdown_pct")),
        "worst_drawdown_delta": _delta(current.get("worst_max_drawdown_pct"), baseline.get("worst_max_drawdown_pct")),
        "current_average_return_pct": current.get("average_return_pct"),
        "baseline_average_return_pct": baseline.get("average_return_pct"),
        "current_average_drawdown_pct": current.get("average_max_drawdown_pct"),
        "baseline_average_drawdown_pct": baseline.get("average_max_drawdown_pct"),
    }


def _candidate_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [row for row in rows if _is_evaluated_candidate_path(row)]
    returns = [_float_or_none(row.get("return_pct")) for row in evaluated]
    drawdowns = [_float_or_none(row.get("max_drawdown_pct")) for row in evaluated]
    runups = [_float_or_none(row.get("max_runup_pct")) for row in evaluated]
    holding_days = [_float_or_none(row.get("holding_days")) for row in evaluated]
    returns = [value for value in returns if value is not None]
    drawdowns = [value for value in drawdowns if value is not None]
    runups = [value for value in runups if value is not None]
    holding_days = [value for value in holding_days if value is not None]
    return {
        "sample_count": len(rows),
        "evaluated_count": len(evaluated),
        "win_rate": _ratio(sum(1 for value in returns if value > 0), len(returns)),
        "average_return_pct": _avg(returns),
        "average_max_drawdown_pct": _avg(drawdowns),
        "worst_max_drawdown_pct": min(drawdowns) if drawdowns else None,
        "average_max_runup_pct": _avg(runups),
        "average_holding_days": _avg(holding_days),
        "return_to_drawdown": _return_to_drawdown(_avg(returns), _avg(drawdowns)),
    }


def _candidate_report_without_price_discontinuity(report: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in report["rows"] if not row.get("has_price_discontinuity")]
    daily = _candidate_daily_cohorts(rows, top_n=int(report.get("top_n") or CANDIDATE_COHORT_TOP_N))
    return {
        **report,
        "rows": rows,
        "daily": daily,
        "evaluated_count": sum(1 for row in rows if _is_evaluated_candidate_path(row)),
    }


def _candidate_path_data_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [row for row in rows if _is_evaluated_candidate_path(row)]
    discontinuity_rows = [row for row in evaluated if row.get("has_price_discontinuity")]
    return {
        "evaluated_count": len(evaluated),
        "price_discontinuity_count": len(discontinuity_rows),
        "price_discontinuity_rate": _ratio(len(discontinuity_rows), len(evaluated)),
        "price_discontinuity_quality": _candidate_metric_summary(discontinuity_rows),
        "worst_price_discontinuity_samples": _worst_price_discontinuity_samples(discontinuity_rows),
    }


def _worst_price_discontinuity_samples(rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            _float_or_none(row.get("return_pct")) if _float_or_none(row.get("return_pct")) is not None else math.inf,
            _float_or_none(row.get("first_price_discontinuity_open_gap_pct")) or 0.0,
        ),
    )
    return [
        {
            "signal_date": row.get("signal_date"),
            "vt_symbol": row.get("vt_symbol"),
            "rank": row.get("rank"),
            "return_pct": row.get("return_pct"),
            "max_drawdown_pct": row.get("max_drawdown_pct"),
            "first_price_discontinuity_date": row.get("first_price_discontinuity_date"),
            "first_price_discontinuity_open_gap_pct": row.get("first_price_discontinuity_open_gap_pct"),
            "first_price_discontinuity_close_gap_pct": row.get("first_price_discontinuity_close_gap_pct"),
        }
        for row in sorted_rows[:limit]
    ]


def _is_evaluated_candidate_path(row: dict[str, Any]) -> bool:
    return row.get("status") in {"closed", "open"} and _float_or_none(row.get("return_pct")) is not None


def _candidate_sell_reason(position, bar, current_day: date, params: BacktestParams, **kwargs):
    return backtest_engine.simulation.sell_reason_for_position(
        position,
        bar,
        current_day,
        params,
        current_buy_signal=bool(kwargs.get("current_buy_signal")),
        replacement_available=bool(kwargs.get("replacement_available")),
    )


def _performance_key(metrics: dict[str, Any]) -> tuple[float, float]:
    return (_metric(metrics, "total_return_pct"), _win_rate(metrics))


def _assert_candidate_cohort_comparable(comparison: dict[str, Any], *, limited: bool) -> None:
    assert comparison["common_candidate_day_count"] > 0, _format_candidate_comparison_failure(comparison)
    assert _finite_nested_metric(comparison, "current_overall", "average_return_pct")
    assert _finite_nested_metric(comparison, "baseline_overall", "average_return_pct")
    assert _finite_nested_metric(comparison, "current_overall", "average_max_drawdown_pct")
    assert _finite_nested_metric(comparison, "baseline_overall", "average_max_drawdown_pct")
    if limited:
        return
    assert comparison["common_candidate_day_count"] >= MIN_FULL_COMMON_COHORT_DATES, _format_candidate_comparison_failure(comparison)


def _assert_candidate_cohort_not_materially_regressed(comparison: dict[str, Any]) -> None:
    current = comparison["current_overall"]
    baseline = comparison["baseline_overall"]
    current_return = _float_or_none(current.get("average_return_pct")) or 0.0
    baseline_return = _float_or_none(baseline.get("average_return_pct")) or 0.0
    return_ratio = current_return / baseline_return if baseline_return > 0 else math.inf
    assert return_ratio >= 0.50, _format_candidate_comparison_failure(comparison)
    assert comparison["win_rate_delta"] >= -0.08, _format_candidate_comparison_failure(comparison)
    assert comparison["average_drawdown_delta"] >= -4.0, _format_candidate_comparison_failure(comparison)
    assert comparison["worst_drawdown_delta"] >= -8.0, _format_candidate_comparison_failure(comparison)


def _assert_candidate_cohort_quality_gate_passed(comparison: dict[str, Any]) -> None:
    assert comparison["return_delta"] > 0, _format_candidate_comparison_failure(comparison)
    assert comparison["win_rate_delta"] > 0, _format_candidate_comparison_failure(comparison)
    assert comparison["average_drawdown_delta"] >= 0, _format_candidate_comparison_failure(comparison)
    assert comparison["worst_drawdown_delta"] >= 0, _format_candidate_comparison_failure(comparison)


def _format_candidate_comparison_failure(comparison: dict[str, Any]) -> str:
    current = comparison.get("current_overall") or {}
    baseline = comparison.get("baseline_overall") or {}
    return (
        "No-position candidate top20 cohort comparison failed: "
        f"baseline=#{comparison.get('baseline_id')} "
        f"common_days={comparison.get('common_candidate_day_count')} "
        f"avg_return {(_float_or_none(current.get('average_return_pct')) or 0.0):.2f}% "
        f"vs {(_float_or_none(baseline.get('average_return_pct')) or 0.0):.2f}% "
        f"(delta {(_float_or_none(comparison.get('return_delta')) or 0.0):.2f}); "
        f"win_rate {(_float_or_none(current.get('win_rate')) or 0.0):.4f} "
        f"vs {(_float_or_none(baseline.get('win_rate')) or 0.0):.4f} "
        f"(delta {(_float_or_none(comparison.get('win_rate_delta')) or 0.0):.4f}); "
        f"avg_drawdown {(_float_or_none(current.get('average_max_drawdown_pct')) or 0.0):.2f}% "
        f"vs {(_float_or_none(baseline.get('average_max_drawdown_pct')) or 0.0):.2f}% "
        f"(delta {(_float_or_none(comparison.get('average_drawdown_delta')) or 0.0):.2f}); "
        f"worst_drawdown {(_float_or_none(current.get('worst_max_drawdown_pct')) or 0.0):.2f}% "
        f"vs {(_float_or_none(baseline.get('worst_max_drawdown_pct')) or 0.0):.2f}% "
        f"(delta {(_float_or_none(comparison.get('worst_drawdown_delta')) or 0.0):.2f})."
    )


def _finite_nested_metric(payload: dict[str, Any], section: str, key: str) -> bool:
    section_payload = payload.get(section) if isinstance(payload.get(section), dict) else {}
    return _float_or_none(section_payload.get(key)) is not None


def _candidate_scoring_dates(trading_days: list[date]) -> list[date]:
    days = trading_days[:-1]
    max_dates = _candidate_cohort_max_dates()
    if max_dates > 0:
        return days[-max_dates:]
    return days


def _candidate_cohort_max_dates() -> int:
    return max(_int_env("ALPHAAGENT_CANDIDATE_COHORT_MAX_DATES", 0), 0)


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _avg(values) -> float | None:
    parsed = [_float_or_none(value) for value in values]
    parsed = [value for value in parsed if value is not None]
    return sum(parsed) / len(parsed) if parsed else None


def _median(values) -> float | None:
    parsed = sorted(value for value in (_float_or_none(item) for item in values) if value is not None)
    if not parsed:
        return None
    middle = len(parsed) // 2
    if len(parsed) % 2:
        return parsed[middle]
    return (parsed[middle - 1] + parsed[middle]) / 2.0


def _min_value(values) -> float | None:
    parsed = [_float_or_none(value) for value in values]
    parsed = [value for value in parsed if value is not None]
    return min(parsed) if parsed else None


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def _delta(current: Any, baseline: Any) -> float | None:
    left = _float_or_none(current)
    right = _float_or_none(baseline)
    if left is None or right is None:
        return None
    return left - right


def _paired_day_win_rate(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_float_or_none(row.get(key)) for row in rows]
    values = [value for value in values if value is not None]
    return _ratio(sum(1 for value in values if value > 0), len(values))


def _return_to_drawdown(return_pct: float | None, drawdown_pct: float | None) -> float | None:
    parsed_return = _float_or_none(return_pct)
    parsed_drawdown = _float_or_none(drawdown_pct)
    if parsed_return is None or parsed_drawdown is None or parsed_drawdown == 0:
        return None
    return parsed_return / abs(parsed_drawdown)


def _metric(metrics: dict[str, Any], key: str) -> float:
    return float(metrics.get(key) or 0.0)


def _win_rate(metrics: dict[str, Any]) -> float:
    value = _metric(metrics, "win_rate")
    return value / 100.0 if value > 1 else value


def _truthy_env(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _require_candidate_quality_gate() -> bool:
    return _truthy_env("ALPHAAGENT_REQUIRE_CANDIDATE_QUALITY_GATE") or _truthy_env("ALPHAAGENT_REQUIRE_STRATEGY_PROMOTION")


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError:
        return default
