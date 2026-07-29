from fastapi.testclient import TestClient

from alphaagent.server.main import create_app
from alphaagent.server.services.limit_up.strategy_guide import (
    get_limit_up_strategy_guide,
)


def test_strategy_guide_separates_selection_fields_from_future_outcomes() -> None:
    guide = get_limit_up_strategy_guide()
    assert guide["strategy"]["selection_contract"] == "limit-up-core-abc-v2"
    assert guide["core_quality"]["minimum_prior_limit_count"] == 2
    assert guide["core_quality"]["maximum_prior_limit_count"] == 6
    assert guide["core_quality"]["b_tier_is_actionable"] is True
    assert guide["core_quality"]["c_tier_is_actionable"] is True
    assert guide["core_quality"]["c_daily_limit"] == 1
    assert guide["core_quality"]["minimum_quality_win_probability"] == 0.50
    assert guide["core_quality"]["quality_estimate_prior_strength"] == 10

    assert guide["strategy"]["selection_no_lookahead"] is True
    assert guide["ranking"]["history_cutoff"] == "result_date < signal_date"
    groups = {row["key"]: row for row in guide["field_groups"]}
    assert groups["intraday"]["selection_allowed"] is True
    assert groups["prior"]["selection_allowed"] is True
    assert groups["execution_safety"]["selection_allowed"] is True
    assert groups["execution_safety"]["selection_role"] == "runtime_safety_only"
    assert "实时快照不超过20秒" in groups["execution_safety"]["fields"]
    assert groups["outcome"]["selection_allowed"] is False
    assert "D+1官方收盘价" in groups["outcome"]["fields"]
    settlement = next(
        step for step in guide["selection_steps"] if step["order"] == 8
    )
    assert "D+1按官方日线收盘价" in settlement["rule"]
    assert "价格代理解释为必然成交" in settlement["rule"]
    recognition = next(
        step for step in guide["selection_steps"] if step["order"] == 3
    )
    assert "过去126个交易日涨停2到6次" in recognition["rule"]
    priority = next(
        step for step in guide["selection_steps"] if step["order"] == 4
    )
    assert "质量胜率低于50%" in priority["rule"]
    preboard = next(
        step for step in guide["selection_steps"] if step["order"] == 5
    )
    assert preboard["title"] == "触板前公开可靠候选"
    assert "唯一缺少的正式条件必须是真实触板" in preboard["rule"]
    trigger = next(
        step for step in guide["selection_steps"] if step["order"] == 6
    )
    assert trigger["title"] == "真实触板后形成正式买点"
    assert "公共质量结论为正式可买" in trigger["rule"]
    assert guide["ranking"]["portfolio_gate"].startswith("公共A/B/C质量胜率")
    rendered = str(guide)
    assert "known_at" not in rendered
    assert "decision_at" not in rendered
    assert all(
        "diagnostic" not in str(step.get("timing", ""))
        for step in guide["selection_steps"]
    )


def test_strategy_guide_exposes_core_abc_evidence_and_forward_status() -> None:
    guide = get_limit_up_strategy_guide()
    evidence = guide["core_quality"]["frozen_evidence"]

    assert evidence["closed_count"] == 140
    assert evidence["win_count"] == 96
    assert evidence["win_rate_pct"] == 68.5714
    assert evidence["status"] == "historical_proxy_pass_forward_unconfirmed"
    assert evidence["evidence_role"] == "current_v2_historical_replay"
    assert evidence["source_contract"] == "limit-up-core-abc-v2"
    assert evidence["live_equivalent"] is False
    assert evidence["a_tier"] == {
        "closed_count": 41,
        "win_count": 35,
        "win_rate_pct": 85.3659,
    }
    assert evidence["b_tier"] == {
        "closed_count": 30,
        "win_count": 18,
        "win_rate_pct": 60.0,
    }
    assert evidence["c_tier"] == {
        "closed_count": 69,
        "win_count": 43,
        "win_rate_pct": 62.3188,
    }
    assert evidence["single_position"] == {
        "closed_count": 78,
        "win_count": 54,
        "win_rate_pct": 69.2308,
        "total_return_pct": 350.83,
        "max_drawdown_pct": -19.2428,
    }
    assert evidence["two_positions"] == {
        "closed_count": 94,
        "win_count": 69,
        "win_rate_pct": 73.4043,
        "total_return_pct": 195.3585,
        "max_drawdown_pct": -8.8761,
    }
    forward = guide["core_quality"]["forward_status"]
    assert forward["start_date"] == "2026-07-27"
    assert forward["closed_count"] == 0
    assert forward["win_count"] == 0
    assert forward["win_rate_pct"] is None
    assert forward["minimum_closed_count"] == 15
    assert forward["minimum_trade_days"] == 10
    assert forward["status"] == "collecting_forward"
    assert "radar_evidence" not in guide


def test_strategy_guide_api_is_readable_without_triggering_market_data() -> None:
    response = TestClient(create_app()).get("/api/limit-up/strategy-guide")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["strategy"]["live_version"] == "limit-up-core-abc-v2"
    assert payload["strategy"]["entry_mode"] == "sweep"
    assert payload["strategy"]["exit_mode"] == "next_close"
