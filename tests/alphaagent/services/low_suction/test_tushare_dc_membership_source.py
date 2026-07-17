from __future__ import annotations

import json
from datetime import date

import pytest

from alphaagent.server.services.data_providers.tushare_dc_membership import (
    DC_MEMBER_ROW_LIMIT,
    TushareDcMembershipClient,
    TushareDcQueryError,
    dc_membership_source_status,
    local_sector_id,
    tushare_sector_code,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


def _post_with(payload: dict[str, object]):
    def post(url: str, *, json: dict[str, object], timeout: float):
        assert url == "https://api.tushare.test"
        assert timeout == 3.0
        assert json["token"] == "secret"
        return FakeResponse(payload)

    return post


def test_dc_sector_code_mapping_is_exact_and_reversible() -> None:
    assert local_sector_id("BK1184.DC") == "BK1184"
    assert tushare_sector_code("bk1184") == "BK1184.DC"

    for invalid in ("880728.TDX", "BK1184", "BK118.DC", "BK1184.DC.extra"):
        with pytest.raises(ValueError):
            local_sector_id(invalid)


def test_source_status_does_not_expose_a_missing_or_configured_token() -> None:
    missing = dc_membership_source_status(token="")
    configured = dc_membership_source_status(token="secret")

    assert missing["status"] == "unconfigured"
    assert missing["configured"] is False
    assert configured["status"] == "ready_for_probe"
    assert configured["configured"] is True
    assert "secret" not in json.dumps(configured)
    assert "token" not in json.dumps(configured).lower()


def test_client_maps_fields_and_preserves_exact_query_parameters() -> None:
    payload = {
        "code": 0,
        "msg": None,
        "data": {
            "fields": ["trade_date", "ts_code", "con_code", "name"],
            "items": [["20250102", "BK1184.DC", "600001.SH", "A"]],
        },
    }
    client = TushareDcMembershipClient(
        token="secret",
        api_url="https://api.tushare.test",
        timeout=3.0,
        post=_post_with(payload),
    )

    result = client.query_members(
        sector_code="BK1184.DC",
        trade_date=date(2025, 1, 2),
    )

    assert result.rows == (
        {
            "trade_date": "20250102",
            "ts_code": "BK1184.DC",
            "con_code": "600001.SH",
            "name": "A",
        },
    )
    assert result.limit_reached is False


def test_client_marks_provider_limit_as_incomplete() -> None:
    payload = {
        "code": 0,
        "data": {
            "fields": ["trade_date", "ts_code", "con_code"],
            "items": [
                ["20250102", "BK1184.DC", f"{index:06d}.SZ"]
                for index in range(DC_MEMBER_ROW_LIMIT)
            ],
        },
    }
    client = TushareDcMembershipClient(
        token="secret",
        api_url="https://api.tushare.test",
        timeout=3.0,
        post=_post_with(payload),
    )

    result = client.query_members(
        sector_code="BK1184.DC",
        trade_date=date(2025, 1, 2),
    )

    assert len(result.rows) == DC_MEMBER_ROW_LIMIT
    assert result.limit_reached is True


@pytest.mark.parametrize(
    "payload",
    [
        {"code": -2001, "msg": "permission denied", "data": None},
        {"code": 0, "data": {"fields": ["ts_code", "ts_code"], "items": []}},
        {"code": 0, "data": {"fields": ["ts_code"], "items": [["A", "B"]]}},
    ],
)
def test_client_rejects_provider_errors_or_malformed_rows(
    payload: dict[str, object],
) -> None:
    client = TushareDcMembershipClient(
        token="secret",
        api_url="https://api.tushare.test",
        timeout=3.0,
        post=_post_with(payload),
    )

    with pytest.raises(TushareDcQueryError):
        client.query_index(date(2025, 1, 2))
