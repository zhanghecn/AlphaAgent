"""Tests for the Phase 0 factor stability gate research."""

from __future__ import annotations

from alphaagent.server.services.limit_up import (
    leader_first_board_factor_stability_research as stab,
)


def _sample(
    trade_date: str,
    value: float | None,
    *,
    is_leader: bool = False,
    d1: float | None = 1.0,
    key: str = "factor_x",
) -> dict:
    return {
        "vt_symbol": "600001.SSE",
        "trade_date": trade_date,
        key: value,
        "is_leader": is_leader,
        "d1_open_return_pct": d1,
    }


# ── 滞后温度 ───────────────────────────────────────────────────────────


def test_attach_lagged_temperature_uses_previous_trading_day() -> None:
    samples = [
        {"trade_date": "2026-07-27", "is_sealed": True},
        {"trade_date": "2026-07-28", "is_sealed": True},
        {"trade_date": "2026-07-28", "is_sealed": True},
        {"trade_date": "2026-07-29", "is_sealed": True},
        {"trade_date": "2026-07-30", "is_sealed": True},
        {"trade_date": "2026-07-31", "is_sealed": True},
        {"trade_date": "2026-08-03", "is_sealed": True},
    ]
    events = [
        {"trade_date": "2026-07-28", "is_sealed": True},
        {"trade_date": "2026-07-28", "is_sealed": True},
        {"trade_date": "2026-07-31", "is_sealed": True},
    ]
    enriched = stab.attach_lagged_temperature(samples, events)
    by_date = {row["trade_date"]: row for row in enriched}
    # 首日无滞后值
    assert by_date["2026-07-27"]["market_first_board_count_d_lag1"] is None
    # D-1 首板数：07-28 看 07-27 的 1 只；07-29 看 07-28 的 2 只
    assert by_date["2026-07-28"]["market_first_board_count_d_lag1"] == 1
    assert by_date["2026-07-29"]["market_first_board_count_d_lag1"] == 2
    # 隔周末：08-03 的 D-1 是 07-31
    assert by_date["2026-08-03"]["market_first_board_count_d_lag1"] == 1
    # 封板数滞后
    assert by_date["2026-07-29"]["market_sealed_count_d_lag1"] == 2
    # ma5 不足 5 天为 None；08-03 有完整 5 天窗口
    assert by_date["2026-07-31"]["market_first_board_count_ma5"] is None
    assert by_date["2026-08-03"]["market_first_board_count_ma5"] == 1.2  # (1+2+1+1+1)/5


# ── 月度切分 ───────────────────────────────────────────────────────────


def test_split_holdout_months_last_three_are_test() -> None:
    samples = [
        _sample(f"2026-{month:02d}-15", 1.0) for month in range(1, 8)
    ] + [_sample("2025-12-15", 1.0)]
    train, test = stab.split_holdout_months(samples, test_months=3)
    assert test == ["2026-05", "2026-06", "2026-07"]
    assert train == ["2025-12", "2026-01", "2026-02", "2026-03", "2026-04"]


# ── 逐月稳定性 ─────────────────────────────────────────────────────────


def test_monthly_factor_stability_agreement() -> None:
    samples: list[dict] = []
    # 每月 60 负样本低值 + 5 正样本高值 → 方向恒 higher
    for month in ("2026-01", "2026-02", "2026-03"):
        for day in range(1, 61):
            samples.append(_sample(f"{month}-{day:02d}"[:10], 1.0, is_leader=False))
        for day in range(1, 6):
            samples.append(_sample(f"{month}-{day:02d}", 9.0, is_leader=True))
    report = stab.monthly_factor_stability(samples, "factor_x")
    assert report["full_direction"] == "higher"
    assert report["valid_months"] == 3
    assert report["agree_months"] == 3
    assert report["monthly_agreement"] == 1.0


def test_monthly_factor_stability_skips_thin_months() -> None:
    samples = [_sample("2026-01-05", 1.0), _sample("2026-01-06", 2.0, is_leader=True)]
    report = stab.monthly_factor_stability(samples, "factor_x")
    assert report["valid_months"] == 0
    assert report["monthly_agreement"] is None
    assert report["months"][0]["direction"] == "skip"


# ── 阈值稳定性 ─────────────────────────────────────────────────────────


def test_threshold_stability_train_boundaries_on_test() -> None:
    train = [_sample("2026-01-15", float(index)) for index in range(100)]
    # test：值越大越容易成龙（0-49 全负，50-99 全正）
    test = [
        _sample("2026-05-15", float(index), is_leader=index >= 50)
        for index in range(100)
    ]
    report = stab.threshold_stability(train, test, "factor_x")
    assert len(report["boundaries"]) == 4
    rates = [row["leader_rate"] for row in report["test_buckets"]]
    assert rates[0] == 0.0
    assert rates[-1] == 1.0
    assert report["spearman"] is not None and report["spearman"] > 0.9


# ── 秩相关 ─────────────────────────────────────────────────────────────


def test_ranks_average_ties() -> None:
    assert stab._ranks([10.0, 20.0, 20.0, 40.0]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_perfect_monotone() -> None:
    assert round(stab._spearman_pairs([1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0]), 6) == 1.0
    assert round(stab._spearman_pairs([1.0, 2.0, 3.0, 4.0], [8.0, 6.0, 4.0, 2.0]), 6) == -1.0


def test_collinearity_matrix_flags_same_clan() -> None:
    samples = [
        {"a": float(index), "b": float(index) * 2, "c": float(100 - index)}
        for index in range(50)
    ]
    pairs = stab.collinearity_matrix(samples, ("a", "b", "c"))
    lookup = {(item["left"], item["right"]): item for item in pairs}
    assert lookup[("a", "b")]["same_clan"] is True
    assert lookup[("a", "b")]["spearman"] == 1.0
    assert lookup[("a", "c")]["same_clan"] is True  # 完全负相关也是同族
    assert lookup[("a", "c")]["spearman"] == -1.0


# ── 双目标标签 ─────────────────────────────────────────────────────────


def test_label_values_d1_win() -> None:
    samples = [
        _sample("2026-07-01", 1.0, d1=2.0),
        _sample("2026-07-01", 2.0, d1=-1.0),
        _sample("2026-07-01", 3.0, d1=None),
    ]
    pos, neg = stab._label_values(samples, "factor_x", "d1_win")
    assert pos == [1.0]
    assert neg == [2.0]


# ── 白名单裁决 ─────────────────────────────────────────────────────────


def _gate_report(
    *,
    train_auc: float = 0.6,
    test_auc: float = 0.58,
    agreement: float = 0.8,
    dual_consistent: bool = True,
) -> dict:
    direction = "higher" if train_auc > 0.5 else "lower"
    return {
        "holdout": {
            "train_auc": train_auc,
            "test_auc": test_auc,
            "train_direction": direction,
            "test_direction": "higher" if test_auc > 0.5 else "lower",
            "direction_consistent": (train_auc - 0.5) * (test_auc - 0.5) > 0,
        },
        "monthly": {"monthly_agreement": agreement},
        "dual_target": {"direction_consistent": dual_consistent},
    }


def test_evaluate_whitelist_pass_and_reject_reasons() -> None:
    reports = {
        "good_factor": _gate_report(),
        "flipped_factor": _gate_report(test_auc=0.4),
        "weak_factor": _gate_report(test_auc=0.52),
        "unstable_factor": _gate_report(agreement=0.5),
        "dual_conflict": _gate_report(dual_consistent=False),
        "market_first_board_count_d_lag1": _gate_report(dual_consistent=False),
    }
    decisions = stab.evaluate_whitelist(reports)
    by_key = {item["factor_key"]: item for item in decisions}
    assert by_key["good_factor"]["passed"] is True
    assert by_key["flipped_factor"]["passed"] is False
    assert "holdout方向不一致" in by_key["flipped_factor"]["reject_reasons"]
    assert by_key["weak_factor"]["passed"] is False
    assert by_key["unstable_factor"]["passed"] is False
    assert by_key["dual_conflict"]["passed"] is False
    # 风控门因子豁免双目标一致
    assert by_key["market_first_board_count_d_lag1"]["passed"] is True
    assert by_key["market_first_board_count_d_lag1"]["role"] == "risk_gate"


def test_suggest_clan_weights_picks_strongest_representative() -> None:
    decisions = [
        {"factor_key": "drawdown_from_126d_high_pct", "passed": True},
        {"factor_key": "return_20d_pct", "passed": True},
        {"factor_key": "market_first_board_count_d_lag1", "passed": True},
    ]
    collinearity = [
        {
            "left": "drawdown_from_126d_high_pct",
            "right": "return_20d_pct",
            "spearman": 0.85,
            "same_clan": True,
        }
    ]
    holdout = {
        "drawdown_from_126d_high_pct": {"test_auc": 0.59},
        "return_20d_pct": {"test_auc": 0.56},
        "market_first_board_count_d_lag1": {"test_auc": 0.44},
    }
    clans = stab.suggest_clan_weights(decisions, collinearity, holdout)
    by_name = {item["clan"]: item for item in clans}
    assert by_name["strength"]["representative"] == "drawdown_from_126d_high_pct"
    assert by_name["strength"]["weight_cap"] == 0.4
    assert by_name["temperature"]["representative"] == "market_first_board_count_d_lag1"
