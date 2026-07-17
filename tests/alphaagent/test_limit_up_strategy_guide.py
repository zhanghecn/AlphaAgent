from fastapi.testclient import TestClient

from alphaagent.server.main import create_app
from alphaagent.server.services.limit_up.strategy_guide import (
    get_limit_up_strategy_guide,
)


def test_strategy_guide_separates_selection_fields_from_future_outcomes() -> None:
    guide = get_limit_up_strategy_guide()

    assert guide["strategy"]["selection_no_lookahead"] is True
    assert guide["ranking"]["history_cutoff"] == "result_date < signal_date"
    groups = {row["key"]: row for row in guide["field_groups"]}
    assert groups["intraday"]["selection_allowed"] is True
    assert groups["prior"]["selection_allowed"] is True
    assert groups["outcome"]["selection_allowed"] is False
    assert "D+1官方收盘价" in groups["outcome"]["fields"]


def test_strategy_guide_exposes_the_frozen_v15_dataset_fingerprint() -> None:
    guide = get_limit_up_strategy_guide()
    dataset = guide["dataset"]

    assert dataset["table"] == "limit_up_signal_snapshots"
    assert dataset["snapshot_count"] == 643
    assert sum(row["snapshot_count"] for row in dataset["daily_snapshot_counts"]) == 643
    assert dataset["closed_through"] == "2026-07-15"
    assert dataset["closed_signal_count"] == 11
    assert dataset["win_count"] == 7
    assert dataset["win_rate_pct"] == 63.6364
    assert dataset["average_net_return_pct"] == 2.905
    historical = guide["historical_reference"]
    assert historical["trade_day_count"] == 800
    assert historical["qualified_signal_count"] == 168
    assert historical["live_equivalent"] is False


def test_strategy_guide_api_is_readable_without_triggering_market_data() -> None:
    response = TestClient(create_app()).get("/api/limit-up/strategy-guide")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["strategy"]["live_version"] == "limit-up-live-v15"
    assert payload["strategy"]["entry_mode"] == "sweep"
    assert payload["strategy"]["exit_mode"] == "next_close"
