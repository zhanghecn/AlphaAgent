"""上穿前价格先行两子型（X/Y）规则谓词与产品接入测试。

特征值取自 2026-08 三个观察个案的真实快照（立新能源 7-15 / 京投发展 8-7 /
秦安股份 8-6），验证规则恰好覆盖目标形态、且 regime 门与排序层级正确。
"""

from __future__ import annotations

from datetime import date, timedelta

from alphaagent.server.services.low_suction.daily_factor_extended_discovery import (
    PRE_CROSS_ACCELERATION_WEAK_MARKET_RULE_KEY,
    PRICE_FIRST_STRONG_ATTACK_RULE_KEY,
    _attack_vote_count,
    process_rule_predicates,
)
from alphaagent.server.services.low_suction.daily_picks_scanner import (
    LowSuctionCandidate,
    _WeakMarketRegimeReader,
    _candidate_priority_tier,
)


def _lixianneng_features() -> dict[str, object]:
    """立新能源 2026-07-15 真实特征快照（votes=3：gap/放量/宽开口）。"""

    return {
        "long_bear_alignment": True,
        "ma10_below_ma20": True,
        "ma10_ma20_signed_distance_pct": -3.5015,
        "ma10_crossed_ma20_after_long_bear_age_sessions_15d": None,
        "ma10_ma20_gap_narrowing_3d_pct": 1.1692,
        "ma10_ma30_gap_narrowing_5d_pct": 7.1404,
        "close_to_ma10_pct": 1.4536,
        "ma10_low_touch": True,
        "ma20_low_touch": False,
        "close_off_low_pct": 2.7027,
        "daily_return_pct": 2.0896,
        "turnover_rate_pct": 2.45,
        "close_to_ma30_pct": -10.1733,
        "signal_day_not_limit_up_closed": True,
        "ma_cluster_spread_pct": 6.3791,
        "ma10_slope_2d_pct": -0.9112,
        "last_volume_change_pct": 146.3928,
        "volume_ratio_5d_10d": 0.9684,
    }


def _jingtou_features() -> dict[str, object]:
    """京投发展 2026-08-07 真实特征快照（votes=3：gap/MA10 加速/宽开口）。"""

    return {
        "long_bear_alignment": True,
        "ma10_below_ma20": True,
        "ma10_ma20_signed_distance_pct": -1.795,
        "ma10_crossed_ma20_after_long_bear_age_sessions_15d": None,
        "ma10_ma20_gap_narrowing_3d_pct": 6.8249,
        "ma10_ma30_gap_narrowing_5d_pct": 15.8856,
        "close_to_ma10_pct": 8.5167,
        "ma10_low_touch": False,
        "ma20_low_touch": True,
        "close_off_low_pct": 6.2575,
        "daily_return_pct": 0.6842,
        "turnover_rate_pct": 2.33,
        "close_to_ma30_pct": -3.9695,
        "signal_day_not_limit_up_closed": True,
        "ma_cluster_spread_pct": 5.9909,
        "ma10_slope_2d_pct": 2.7658,
        "last_volume_change_pct": -0.0446,
        "volume_ratio_5d_10d": 0.9136,
    }


def _qinan_features() -> dict[str, object]:
    """秦安股份 2026-08-06 真实特征快照（votes=2：放量/MA10 加速，刚上穿）。"""

    return {
        "long_bear_alignment": True,
        "ma10_below_ma20": False,
        "ma10_ma20_signed_distance_pct": 0.3095,
        "ma10_crossed_ma20_after_long_bear_age_sessions_15d": 0,
        "ma10_ma20_gap_narrowing_3d_pct": 2.8622,
        "ma10_ma30_gap_narrowing_5d_pct": 3.844,
        "close_to_ma10_pct": 4.0052,
        "ma10_low_touch": True,
        "ma20_low_touch": True,
        "close_off_low_pct": 3.6997,
        "daily_return_pct": 1.5991,
        "turnover_rate_pct": 1.86,
        "close_to_ma30_pct": 2.3521,
        "signal_day_not_limit_up_closed": True,
        "ma_cluster_spread_pct": 1.086,
        "ma10_slope_2d_pct": 1.653,
        "last_volume_change_pct": 169.3081,
        "volume_ratio_5d_10d": 1.2234,
    }


def test_rule_x_matches_lixianneng_snapshot_via_votes() -> None:
    predicates = process_rule_predicates(
        PRE_CROSS_ACCELERATION_WEAK_MARKET_RULE_KEY,
        _lixianneng_features(),
    )
    assert all(predicates.values()), [
        key for key, ok in predicates.items() if not ok
    ]
    assert _attack_vote_count(_lixianneng_features()) == 3


def test_rule_x_matches_qinan_snapshot_via_votes() -> None:
    """秦安刚上穿（age=0）也满足 X 的形态层；是否入场由产品层 regime 门决定。"""

    predicates = process_rule_predicates(
        PRE_CROSS_ACCELERATION_WEAK_MARKET_RULE_KEY,
        _qinan_features(),
    )
    assert all(predicates.values()), [
        key for key, ok in predicates.items() if not ok
    ]
    assert _attack_vote_count(_qinan_features()) == 2


def test_rule_x_slope_path_covers_low_vote_acceleration() -> None:
    features = {
        **_lixianneng_features(),
        # 投票降到 1（仅 MA10 加速），但量比 < 1.1 → slope-path 成立
        "ma10_ma30_gap_narrowing_5d_pct": 4.0,
        "ma_cluster_spread_pct": 3.0,
        "last_volume_change_pct": 10.0,
        "ma10_slope_2d_pct": 1.8,
        "volume_ratio_5d_10d": 0.95,
    }
    predicates = process_rule_predicates(
        PRE_CROSS_ACCELERATION_WEAK_MARKET_RULE_KEY,
        features,
    )
    assert all(predicates.values())
    assert _attack_vote_count(features) == 1


def test_rule_x_rejects_overheated_volume_without_votes() -> None:
    features = {
        **_lixianneng_features(),
        "ma10_ma30_gap_narrowing_5d_pct": 4.0,
        "ma_cluster_spread_pct": 3.0,
        "last_volume_change_pct": 10.0,
        "ma10_slope_2d_pct": 1.8,
        "volume_ratio_5d_10d": 1.25,  # 量能过热，slope-path 关闭
    }
    predicates = process_rule_predicates(
        PRE_CROSS_ACCELERATION_WEAK_MARKET_RULE_KEY,
        features,
    )
    assert not all(predicates.values())
    assert predicates["attack_votes_at_least_2_or_slope_path"] is False


def test_rule_y_matches_jingtou_snapshot() -> None:
    predicates = process_rule_predicates(
        PRICE_FIRST_STRONG_ATTACK_RULE_KEY,
        _jingtou_features(),
    )
    assert all(predicates.values()), [
        key for key, ok in predicates.items() if not ok
    ]


def test_rule_y_rejects_close_not_leading_enough() -> None:
    predicates = process_rule_predicates(
        PRICE_FIRST_STRONG_ATTACK_RULE_KEY,
        {**_jingtou_features(), "close_to_ma10_pct": 5.9},
    )
    assert predicates["close_to_ma10_at_least_6_pct"] is False
    assert not all(predicates.values())


def test_rule_y_rejects_flat_ma10_slope() -> None:
    predicates = process_rule_predicates(
        PRICE_FIRST_STRONG_ATTACK_RULE_KEY,
        {**_jingtou_features(), "ma10_slope_2d_pct": 1.2},
    )
    assert predicates["ma10_slope_2d_accelerating"] is False
    assert not all(predicates.values())


def test_base_predicates_reject_chasing_beyond_10pct() -> None:
    predicates = process_rule_predicates(
        PRICE_FIRST_STRONG_ATTACK_RULE_KEY,
        {**_jingtou_features(), "close_to_ma10_pct": 10.5},
    )
    assert predicates["close_leads_ma10_1_4_to_10_pct"] is False


def test_weak_market_regime_reader_is_fail_closed() -> None:
    below = date(2026, 7, 14)
    reader = _WeakMarketRegimeReader({below: "below_ma20"})
    assert reader.is_weak_market(below) is True
    # 当日无分类 → 回退最近已确认日（仍弱市）
    assert reader.is_weak_market(below + timedelta(days=1)) is True
    # 无更早分类可用 → fail-closed
    assert reader.is_weak_market(below - timedelta(days=1)) is False
    empty = _WeakMarketRegimeReader({})
    assert empty.is_weak_market(below) is False
    above_reader = _WeakMarketRegimeReader({below: "above_ma20"})
    assert above_reader.is_weak_market(below) is False


def _candidate(rule_keys: tuple[str, ...]) -> LowSuctionCandidate:
    from alphaagent.server.services.low_suction.daily_picks_scoring import (
        QuietStreak,
    )

    return LowSuctionCandidate(
        vt_symbol="001258.SZSE",
        trade_date=date(2026, 7, 15),
        setup_type="oversold_rebound",
        rule_key=rule_keys[0],
        matched_rule_keys=rule_keys,
        score=30.0,
        band="0-39",
        streak=QuietStreak(total=0, yin=0, yang=0),
        components=(),
        close_price=6.84,
        daily_return_pct=2.09,
        turnover_rate_pct=2.45,
        candle_range_pct=3.51,
        d1_trade_date=None,
        d1_close_return_pct=None,
    )


def test_pre_cross_lead_rules_share_p15_tier() -> None:
    first_leg = _candidate(("first_leg_two_ma_body_wrap_before_ma30",))
    rule_x = _candidate((PRE_CROSS_ACCELERATION_WEAK_MARKET_RULE_KEY,))
    rule_y = _candidate((PRICE_FIRST_STRONG_ATTACK_RULE_KEY,))
    staged = _candidate(("staged_ma10_support_before_ma30_convergence_shrink",))

    assert _candidate_priority_tier(first_leg) == 20
    assert _candidate_priority_tier(rule_x) == 20
    assert _candidate_priority_tier(rule_y) == 20
    assert _candidate_priority_tier(staged) == 10
    # X/Y 与 P1.5 同层共用换手率 3% 接近度决胜（tier==20 才启用）
    from alphaagent.server.services.low_suction.daily_picks_scanner import (
        candidate_ranking_key,
    )

    assert candidate_ranking_key(rule_x)[2] == abs(2.45 - 3.0)
    assert candidate_ranking_key(staged)[2] == 0.0


def _scan_snapshot(features: dict[str, object], signal_date: date):
    from types import SimpleNamespace

    return SimpleNamespace(
        symbol="001258.SZSE",
        trade_date=signal_date,
        position=0,
        history=(
            {
                "trade_date": signal_date,
                "open_price": 10.0,
                "close_price": 10.2,
                "high_price": 10.3,
                "low_price": 9.9,
                "volume": 1_000.0,
            },
        ),
        features=features,
        prior_features=None,
        d1_close_return_pct=1.0,
        d1_label_status="available",
    )


def _scan_with_regime(monkeypatch, matched_rules, regime_map, signal_date):
    import alphaagent.server.services.low_suction.daily_picks_scanner as scanner

    snapshot = _scan_snapshot(
        {
            "close_price": 10.2,
            "daily_return_pct": 2.0,
            "turnover_rate_pct": 2.0,
            "candle_range_pct": 2.0,
        },
        signal_date,
    )
    monkeypatch.setattr(
        scanner,
        "_iter_candidate_snapshots",
        lambda *args, **kwargs: iter((snapshot,)),
    )
    monkeypatch.setattr(
        scanner,
        "matching_discovery_rule_keys",
        lambda features, setup_type, *, prior_features=None, rules=None: (
            matched_rules if setup_type == "oversold_rebound" else ()
        ),
    )
    monkeypatch.setattr(
        scanner,
        "_attack_vote_count",
        lambda features: 3,
    )
    return scanner.scan_low_suction_candidates(
        [],
        (signal_date, signal_date + timedelta(days=1)),
        [],
        target_dates={signal_date},
        market_regimes=regime_map,
    )


def test_scan_rule_x_gated_by_weak_market_regime(monkeypatch) -> None:
    signal_date = date(2026, 7, 15)
    matched = (PRE_CROSS_ACCELERATION_WEAK_MARKET_RULE_KEY,)

    admitted = _scan_with_regime(
        monkeypatch, matched, {signal_date: "below_ma20"}, signal_date
    )
    assert len(admitted) == 1
    assert admitted[0].rule_key == PRE_CROSS_ACCELERATION_WEAK_MARKET_RULE_KEY
    # 攻击强度投票进入综合分（3 票 × 2 分）
    vote_component = next(
        c for c in admitted[0].components if c.key == "attack_votes"
    )
    assert vote_component.points == 6.0

    blocked_above = _scan_with_regime(
        monkeypatch, matched, {signal_date: "above_ma20"}, signal_date
    )
    assert blocked_above == []

    blocked_missing = _scan_with_regime(monkeypatch, matched, {}, signal_date)
    assert blocked_missing == []


def test_scan_rule_y_is_regime_agnostic(monkeypatch) -> None:
    signal_date = date(2026, 8, 7)
    matched = (PRICE_FIRST_STRONG_ATTACK_RULE_KEY,)

    for regime_map in ({signal_date: "above_ma20"}, {}, {signal_date: "below_ma20"}):
        admitted = _scan_with_regime(
            monkeypatch, matched, regime_map, signal_date
        )
        assert len(admitted) == 1
        assert admitted[0].rule_key == PRICE_FIRST_STRONG_ATTACK_RULE_KEY
