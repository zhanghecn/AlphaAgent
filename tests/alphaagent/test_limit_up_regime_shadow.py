from __future__ import annotations

from datetime import date, timedelta

from alphaagent.server.services.limit_up import regime_shadow


def test_style_context_uses_prior_twenty_observations() -> None:
    start = date(2026, 1, 1)
    rows: list[dict[str, object]] = []
    for index in range(21):
        trade_date = start + timedelta(days=index)
        rows.extend(
            [
                {
                    "vt_symbol": "000300.SSE",
                    "trade_date": trade_date,
                    "change_pct": float(index),
                },
                {
                    "vt_symbol": "000852.SSE",
                    "trade_date": trade_date,
                    "change_pct": 0.0,
                },
            ]
        )

    context = regime_shadow.build_style_context(rows, start + timedelta(days=21))

    assert context["status"] == "ready"
    assert context["prior_trade_date"] == "2026-01-21"
    assert context["style_history_count"] == 20
    assert context["style_spread_pct_points"] == 20.0
    assert context["style_percentile_20"] == 1.0


def test_attach_shadow_marks_risk_without_changing_formal_action() -> None:
    snapshot = _snapshot()

    result = regime_shadow.attach_regime_failure_shadow(
        snapshot,
        context=_ready_context(style_percentile=0.8, sealed_count=0),
    )

    signal = result["recommendations"]["actionable_recommendations"][0]
    shadow = signal["regime_failure_shadow"]
    assert signal["action"] == "buy_now"
    assert signal["portfolio_selected"] is True
    assert shadow["status"] == "ready"
    assert shadow["risk_flag"] is True
    assert shadow["execution_effect"] == "none_research_only"
    assert result["data_quality"]["regime_failure_shadow"]["risk_count"] == 1


def test_industry_context_requires_strict_scope_and_counts_primary_boards() -> None:
    prior_trade_date = date(2026, 7, 16)
    memberships = [
        {
            "vt_symbol": "600001.SSE",
            "sector_id": "BK1",
            "sector_name": "测试行业",
            "rank": 1,
        },
        {
            "vt_symbol": "600002.SSE",
            "sector_id": "BK1",
            "sector_name": "测试行业",
            "rank": 1,
        },
    ]
    scope = {
        "snapshot_date": prior_trade_date,
        "complete": True,
        "evidence_level": "strict_exclusions",
        "source": "eastmoney.push2.board",
    }

    context = regime_shadow.build_industry_context(
        memberships,
        scope,
        [{"vt_symbol": "600002.SSE", "name": "封板股票"}],
        prior_trade_date,
    )

    assert context["status"] == "ready"
    assert context["sealed_count_by_industry"] == {"BK1": 1}
    assert context["primary_industries"]["600001.SSE"]["industry_id"] == "BK1"

    blocked = regime_shadow.build_industry_context(
        memberships,
        {**scope, "complete": False},
        [{"vt_symbol": "600002.SSE", "name": "封板股票"}],
        prior_trade_date,
    )
    assert blocked["status"] == "blocked_by_membership_scope"


def test_attach_shadow_fails_closed_when_strict_industry_is_missing() -> None:
    context = _ready_context(style_percentile=0.9, sealed_count=0)
    context["primary_industries"] = {}

    result = regime_shadow.attach_regime_failure_shadow(
        _snapshot(),
        context=context,
    )

    signal = result["recommendations"]["actionable_recommendations"][0]
    shadow = signal["regime_failure_shadow"]
    assert signal["action"] == "buy_now"
    assert shadow["status"] == "blocked_by_strict_industry_membership"
    assert shadow["risk_flag"] is None
    assert result["data_quality"]["regime_failure_shadow"]["eligible_count"] == 0


def test_non_first_board_is_not_affected_by_shadow() -> None:
    snapshot = _snapshot(board_lane="two_to_three")

    result = regime_shadow.attach_regime_failure_shadow(
        snapshot,
        context=_ready_context(style_percentile=1.0, sealed_count=0),
    )

    signal = result["recommendations"]["actionable_recommendations"][0]
    assert signal["action"] == "buy_now"
    assert signal["regime_failure_shadow"]["status"] == "not_applicable"
    assert signal["regime_failure_shadow"]["risk_flag"] is None


def _snapshot(*, board_lane: str = "first_board") -> dict[str, object]:
    signal = {
        "vt_symbol": "600001.SSE",
        "name": "严格信号",
        "board_lane": board_lane,
        "action": "buy_now",
        "portfolio_selected": True,
    }
    return {
        "trade_date": "2026-07-17",
        "recommendations": {"actionable_recommendations": [signal]},
        "data_quality": {"status": "ready", "is_stale": False},
    }


def _ready_context(
    *,
    style_percentile: float,
    sealed_count: int,
) -> dict[str, object]:
    return {
        "status": "ready",
        "prior_trade_date": "2026-07-16",
        "style_spread_pct_points": 0.5,
        "style_percentile_20": style_percentile,
        "style_history_count": 20,
        "membership_scope": {
            "snapshot_date": "2026-07-16",
            "complete": True,
            "evidence_level": "strict_exclusions",
            "source": "eastmoney.push2.board",
        },
        "primary_industries": {
            "600001.SSE": {
                "industry_id": "BK1",
                "industry_name": "测试行业",
            }
        },
        "sealed_count_by_industry": {"BK1": sealed_count},
        "sealed_event_count": 40,
    }
