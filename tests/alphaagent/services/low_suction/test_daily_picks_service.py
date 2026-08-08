"""Focused tests for low-suction live payload paging."""

from alphaagent.server.services.low_suction.daily_picks_service import (
    _paginate_live_payload,
)


def test_live_pagination_keeps_each_family_within_cached_top_hundred() -> None:
    payload = {
        "status": "ok",
        "trend": {
            "total": 140,
            "limit": 100,
            "items": [{"rank": value} for value in range(1, 101)],
        },
        "oversold": {
            "total": 7,
            "limit": 100,
            "items": [{"rank": value} for value in range(1, 8)],
        },
    }

    paged = _paginate_live_payload(payload, trend_page=3, oversold_page=9)

    assert payload["trend"]["items"][0]["rank"] == 1
    assert paged["trend"]["page"] == 3
    assert paged["trend"]["pages"] == 5
    assert [item["rank"] for item in paged["trend"]["items"]] == list(range(41, 61))
    assert paged["oversold"]["page"] == 1
    assert paged["oversold"]["pages"] == 1
    assert [item["rank"] for item in paged["oversold"]["items"]] == list(range(1, 8))
