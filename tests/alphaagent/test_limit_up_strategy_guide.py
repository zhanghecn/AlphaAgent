from fastapi.testclient import TestClient

from alphaagent.server.main import create_app
from alphaagent.server.services.limit_up.strategy_guide import (
    get_limit_up_strategy_guide,
)


def test_strategy_guide_separates_selection_fields_from_future_outcomes() -> None:
    guide = get_limit_up_strategy_guide()
    assert guide["strategy"]["selection_contract"] == "limit-up-core-ab-v1"
    assert guide["core_quality"]["minimum_prior_limit_count"] == 2
    assert guide["core_quality"]["maximum_prior_limit_count"] == 6
    assert guide["core_quality"]["b_tier_is_actionable"] is True

    assert guide["strategy"]["selection_no_lookahead"] is True
    assert guide["ranking"]["history_cutoff"] == "result_date < signal_date"
    groups = {row["key"]: row for row in guide["field_groups"]}
    assert groups["intraday"]["selection_allowed"] is True
    assert groups["prior"]["selection_allowed"] is True
    assert groups["outcome"]["selection_allowed"] is False
    assert "D+1官方收盘价" in groups["outcome"]["fields"]
    settlement = next(
        step for step in guide["selection_steps"] if step["order"] == 7
    )
    assert "D+1按官方日线收盘价" in settlement["rule"]
    assert "价格代理解释为必然成交" in settlement["rule"]
    recognition = next(
        step for step in guide["selection_steps"] if step["order"] == 3
    )
    assert "过去126个交易日涨停次数必须在2到6次" in recognition["rule"]
    priority = next(
        step for step in guide["selection_steps"] if step["order"] == 4
    )
    assert "A优先，B仍可交易" in priority["rule"]
    assert guide["preboard_decision"]["observation_is_buy_signal"] is False
    assert guide["preboard_decision"]["quality_pool_rule"].startswith(
        "先通过正式同源首板质量门"
    )
    assert "不生成买点" in guide["preboard_decision"]["formal_baseline"]
    assert "旧规则回退入口" in guide["preboard_decision"]["formal_baseline"]
    assert guide["ranking"]["portfolio_gate"].startswith("全量正式首板要求")
    rendered = str(guide)
    assert "known_at" not in rendered
    assert "decision_at" not in rendered
    assert all(
        "diagnostic" not in str(step.get("timing", ""))
        for step in guide["selection_steps"]
    )


def test_strategy_guide_exposes_core_ab_evidence_and_old_audit_dataset() -> None:
    guide = get_limit_up_strategy_guide()
    dataset = guide["dataset"]
    evidence = guide["core_quality"]["frozen_evidence"]

    assert evidence["closed_count"] == 78
    assert evidence["win_count"] == 56
    assert evidence["win_rate_pct"] == 71.7949
    assert evidence["status"] == "historical_pass_forward_not_passed"
    assert evidence["live_equivalent"] is False
    assert evidence["a_tier"] == {
        "closed_count": 41,
        "win_count": 35,
        "win_rate_pct": 85.3659,
    }
    assert evidence["b_tier"] == {
        "closed_count": 37,
        "win_count": 21,
        "win_rate_pct": 56.7568,
    }
    recent = guide["core_quality"]["recent_snapshot_check"]
    assert recent["closed_count"] == 24
    assert recent["win_count"] == 12
    assert recent["win_rate_pct"] == 50.0
    assert recent["status"] == "below_60_requires_natural_forward"

    assert dataset["table"] == "limit_up_signal_snapshots"
    assert "只读审计" in dataset["name"]
    assert dataset["snapshot_count"] == 643
    assert sum(row["snapshot_count"] for row in dataset["daily_snapshot_counts"]) == 643
    assert dataset["closed_through"] == "2026-07-15"
    assert dataset["closed_signal_count"] == 11
    assert dataset["win_count"] == 7
    assert dataset["win_rate_pct"] == 63.6364
    assert dataset["average_net_return_pct"] == 2.905
    historical = guide["historical_reference"]
    assert historical["trade_day_count"] == 806
    assert historical["qualified_signal_count"] == 243
    assert historical["closed_recommendation_count"] == 239
    assert historical["recommendation_win_rate_pct"] == 54.8117
    assert historical["live_equivalent"] is False
    preboard = guide["preboard_decision"]
    assert preboard["decision_version"] == "limit-up-preboard-decision-v1"
    assert preboard["observation_min_change_pct"] == 3.0
    assert preboard["observation_is_buy_signal"] is False
    assert preboard["probability_outputs"] == [
        "3分钟触板概率",
        "当日最终触板概率",
    ]
    assert "limit-up-core-ab-v1" in preboard["formal_baseline"]
    assert "radar_evidence" not in guide


def test_strategy_guide_api_is_readable_without_triggering_market_data() -> None:
    response = TestClient(create_app()).get("/api/limit-up/strategy-guide")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["strategy"]["live_version"] == "limit-up-core-ab-v1"
    assert payload["strategy"]["entry_mode"] == "sweep"
    assert payload["strategy"]["exit_mode"] == "next_close"
