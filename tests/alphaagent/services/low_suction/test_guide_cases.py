"""低吸说明书案例（guide_cases）的纯函数与归组完整性测试。"""

from __future__ import annotations

from datetime import date, timedelta

from alphaagent.server.services.low_suction.daily_factor_comprehensive_study import (
    PERSONAL_CASES,
)
from alphaagent.server.services.low_suction.daily_factor_extended_discovery import (
    DISCOVERY_RULES,
    FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
    POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY,
    PRE_CROSS_ACCELERATION_WEAK_MARKET_RULE_KEY,
    PRICE_FIRST_STRONG_ATTACK_RULE_KEY,
    RESEARCH_THREE_MA_WRAP_RULE_KEY,
    STAGED_MA10_SUPPORT_RULE_KEY,
)
from alphaagent.server.services.low_suction.daily_picks_scanner import (
    PRODUCT_DISCOVERY_RULES,
)
from alphaagent.server.services.low_suction.guide_cases import (
    assemble_guide_payload,
    compute_forward_close_returns,
)

ALL_RULE_KEYS = {
    rule.key for rules in DISCOVERY_RULES.values() for rule in rules
}
PRODUCT_RULE_KEYS = {
    rule.key for rules in PRODUCT_DISCOVERY_RULES.values() for rule in rules
}


def _bars(closes: list[float], start: date = date(2026, 7, 1)) -> list[dict]:
    """合成连续交易日的日线序列（每元素一个交易日，无缺口）。"""

    return [
        {"trade_date": start + timedelta(days=offset), "close_price": close}
        for offset, close in enumerate(closes)
    ]


def test_forward_returns_normal_three_horizons() -> None:
    bars = _bars([10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6])

    result = compute_forward_close_returns(bars, date(2026, 7, 1))

    assert result["status"] == "available"
    assert result["d1_close_return_pct"] == 1.0
    assert result["d3_close_return_pct"] == 3.0
    assert result["d5_close_return_pct"] == 5.0


def test_forward_returns_signal_date_not_found() -> None:
    result = compute_forward_close_returns(_bars([10.0, 10.1]), date(2026, 8, 8))

    assert result["status"] == "signal_date_not_found"
    assert result["d1_close_return_pct"] is None
    assert result["d5_close_return_pct"] is None


def test_forward_returns_missing_exit_session_near_tail() -> None:
    # 信号日后只剩 2 个交易日：D+1 可得，D+3/D+5 数据不足。
    bars = _bars([10.0, 10.1, 10.2])

    result = compute_forward_close_returns(bars, date(2026, 7, 1))

    assert result["status"] == "missing_exit_session"
    assert result["d1_close_return_pct"] == 1.0
    assert result["d3_close_return_pct"] is None
    assert result["d5_close_return_pct"] is None


def test_forward_returns_raw_price_limit_outlier_blocks_farther_horizons() -> None:
    # 第 3 步收盘跳变 30%（除权污染）：D+1 正常，D+3 起全部置 None。
    bars = _bars([10.0, 10.1, 10.2, 13.3, 13.4, 13.5, 13.6])

    result = compute_forward_close_returns(bars, date(2026, 7, 1))

    assert result["status"] == "raw_price_limit_outlier"
    assert result["d1_close_return_pct"] == 1.0
    assert result["d3_close_return_pct"] is None
    assert result["d5_close_return_pct"] is None


def test_forward_returns_session_indexed_skips_suspension_gap() -> None:
    # 停牌缺口：trade_date 中间隔了日历日，但 D+N 按交易日索引计。
    bars = [
        {"trade_date": date(2026, 2, 12), "close_price": 10.0},
        {"trade_date": date(2026, 3, 2), "close_price": 10.2},
        {"trade_date": date(2026, 3, 3), "close_price": 10.3},
        {"trade_date": date(2026, 3, 4), "close_price": 10.4},
        {"trade_date": date(2026, 3, 5), "close_price": 10.5},
        {"trade_date": date(2026, 3, 6), "close_price": 10.6},
    ]

    result = compute_forward_close_returns(bars, date(2026, 2, 12))

    assert result["status"] == "available"
    assert result["d1_close_return_pct"] == 2.0
    assert result["d5_close_return_pct"] == 6.0


def test_forward_returns_invalid_signal_close_is_unavailable() -> None:
    bars = _bars([0.0, 10.1, 10.2])

    result = compute_forward_close_returns(bars, date(2026, 7, 1))

    assert result["status"] == "bars_unavailable"
    assert result["d1_close_return_pct"] is None


def test_assemble_payload_covers_every_discovery_rule() -> None:
    payload = assemble_guide_payload(_fake_returns())

    seen_keys: list[str] = []
    for family in payload["families"]:
        assert family["key"] in ("trend_pullback", "oversold_rebound")
        assert family["label"]
        for rule in family["rules"]:
            seen_keys.append(rule["rule_key"])
            assert rule["description"]
            assert rule["tier"] in ("product", "research")
            assert isinstance(rule["cases"], list)
    assert set(seen_keys) == ALL_RULE_KEYS
    assert len(seen_keys) == len(ALL_RULE_KEYS)


def test_assemble_payload_product_tiers_match_scanner() -> None:
    payload = assemble_guide_payload(_fake_returns())

    for family in payload["families"]:
        for rule in family["rules"]:
            if rule["rule_key"] in PRODUCT_RULE_KEYS:
                assert rule["tier"] == "product"
            else:
                assert rule["tier"] == "research"
            if rule["rule_key"] in (
                FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
                PRE_CROSS_ACCELERATION_WEAK_MARKET_RULE_KEY,
                PRICE_FIRST_STRONG_ATTACK_RULE_KEY,
                RESEARCH_THREE_MA_WRAP_RULE_KEY,
                POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY,
            ):
                assert rule["product_tier"] == "P1.5"
            elif rule["rule_key"] == STAGED_MA10_SUPPORT_RULE_KEY:
                assert rule["product_tier"] == "P1"
            else:
                assert rule["product_tier"] is None


def test_assemble_payload_orphans_are_cases_without_rule_keys() -> None:
    payload = assemble_guide_payload(_fake_returns())

    orphan_ids = {case["case_id"] for case in payload["orphan_cases"]}
    expected = {
        case.name for case in PERSONAL_CASES if not case.required_process_rule_keys
    }
    assert orphan_ids == expected
    assert orphan_ids  # 现状仅秦安股份一条待验证锚点（立新能源/京投发展已沉淀为 X/Y 规则）

    attached = {
        case["case_id"]
        for family in payload["families"]
        for rule in family["rules"]
        for case in rule["cases"]
    }
    assert not attached & orphan_ids
    # 每个有 rule_key 的案例都被挂到对应规则下，且键都在 DISCOVERY_RULES 内。
    for case in PERSONAL_CASES:
        if case.required_process_rule_keys:
            assert case.name in attached
            assert set(case.required_process_rule_keys) <= ALL_RULE_KEYS


def test_assemble_payload_case_fields_and_returns() -> None:
    payload = assemble_guide_payload(_fake_returns())

    sample = next(
        case
        for family in payload["families"]
        for rule in family["rules"]
        for case in rule["cases"]
        if case["case_id"] == "华电辽能 MA5 缩量回踩"
    )
    assert sample["vt_symbol"] == "600396.SSE"
    assert sample["signal_date"] == "2026-03-13"
    assert sample["setup_type"] == "trend_pullback"
    assert sample["narrative_start_date"] == "2026-02-06"
    assert sample["expected_launch_date"] == "2026-03-16"
    assert sample["returns"]["d5_close_return_pct"] == 42.0
    assert sample["returns"]["status"] == "available"


def test_assemble_payload_marks_partial_when_symbol_bars_unavailable() -> None:
    returns = _fake_returns()
    returns["华电辽能 MA5 回踩"] = {
        "d1_close_return_pct": None,
        "d3_close_return_pct": None,
        "d5_close_return_pct": None,
        "status": "bars_unavailable",
    }

    payload = assemble_guide_payload(returns)

    assert payload["status"] == "partial"


def _fake_returns() -> dict[str, dict]:
    """每个策展案例一份伪造收益，键与案例名一一对应。"""

    return {
        case.name: {
            "d1_close_return_pct": 10.0,
            "d3_close_return_pct": 20.0,
            "d5_close_return_pct": 42.0,
            "status": "available",
        }
        for case in PERSONAL_CASES
    }
