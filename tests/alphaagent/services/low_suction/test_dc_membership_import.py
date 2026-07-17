from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from alphaagent.server.services.data_providers.tushare_dc_membership import (
    DC_MEMBER_ROW_LIMIT,
    TushareDcQueryResult,
)
from alphaagent.server.services.low_suction.dc_membership_import import (
    DcMembershipImportError,
    LocalConcept,
    build_dc_membership_payload,
    membership_source_status,
    validate_dc_membership_payload,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeClient:
    def __init__(
        self,
        *,
        index_by_date: dict[date, tuple[dict[str, object], ...]],
        members_by_date: dict[date, tuple[dict[str, object], ...]],
        limit_ranges: bool = False,
    ) -> None:
        self.index_by_date = index_by_date
        self.members_by_date = members_by_date
        self.limit_ranges = limit_ranges
        self.member_calls: list[tuple[date | None, date | None, date | None]] = []

    def query_index(self, trade_date: date) -> TushareDcQueryResult:
        return TushareDcQueryResult(
            api_name="dc_index",
            rows=self.index_by_date.get(trade_date, ()),
            limit_reached=False,
        )

    def query_members(
        self,
        *,
        sector_code: str,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> TushareDcQueryResult:
        assert sector_code == "BK1184.DC"
        self.member_calls.append((trade_date, start_date, end_date))
        if trade_date is not None:
            dates = (trade_date,)
        else:
            assert start_date is not None and end_date is not None
            dates = tuple(
                current
                for current in sorted(self.members_by_date)
                if start_date <= current <= end_date
            )
        rows = tuple(row for current in dates for row in self.members_by_date[current])
        return TushareDcQueryResult(
            api_name="dc_member",
            rows=rows,
            limit_reached=self.limit_ranges and trade_date is None,
        )


def _concept() -> LocalConcept:
    return LocalConcept(
        sector_id="BK1184",
        name="人形机器人",
        first_bar_date=date(2024, 12, 2),
        last_bar_date=date(2026, 7, 15),
    )


def _index_row(source_date: date) -> dict[str, object]:
    return {
        "trade_date": source_date.strftime("%Y%m%d"),
        "ts_code": "BK1184.DC",
        "name": "人形机器人",
        "idx_type": "概念板块",
    }


def _member_row(source_date: date, symbol: str = "600001.SH") -> dict[str, object]:
    return {
        "trade_date": source_date.strftime("%Y%m%d"),
        "ts_code": "BK1184.DC",
        "con_code": symbol,
        "name": "A",
    }


def test_payload_uses_exact_source_date_and_validates_atomic_scope() -> None:
    source_date = date(2026, 7, 14)
    research_date = date(2026, 7, 15)
    client = FakeClient(
        index_by_date={source_date: (_index_row(source_date),)},
        members_by_date={source_date: (_member_row(source_date),)},
    )

    payload = build_dc_membership_payload(
        client=client,
        research_source_dates={research_date: source_date},
        concepts=(_concept(),),
        fetched_at=datetime(2026, 7, 16, 12, tzinfo=SHANGHAI),
    )
    report = validate_dc_membership_payload(payload, dry_run=True)

    assert payload.mapping_pct == 100.0
    assert payload.required_pairs == ((research_date, "BK1184"),)
    assert payload.records[0].in_date == research_date
    assert payload.scopes[0].source_trade_date == source_date
    assert report.status == "ready_for_atomic_replace"
    assert report.scope_coverage_pct == 100.0


def test_payload_rejects_an_unmapped_active_local_concept() -> None:
    source_date = date(2026, 7, 14)
    research_date = date(2026, 7, 15)
    client = FakeClient(index_by_date={source_date: ()}, members_by_date={})

    with pytest.raises(DcMembershipImportError, match="exact mapping"):
        build_dc_membership_payload(
            client=client,
            research_source_dates={research_date: source_date},
            concepts=(_concept(),),
        )


def test_payload_rejects_duplicate_constituents() -> None:
    source_date = date(2026, 7, 14)
    research_date = date(2026, 7, 15)
    duplicate = (_member_row(source_date), _member_row(source_date))
    client = FakeClient(
        index_by_date={source_date: (_index_row(source_date),)},
        members_by_date={source_date: duplicate},
    )

    with pytest.raises(ValueError, match="duplicate"):
        build_dc_membership_payload(
            client=client,
            research_source_dates={research_date: source_date},
            concepts=(_concept(),),
        )


def test_one_date_response_at_provider_limit_is_rejected() -> None:
    source_date = date(2026, 7, 14)
    research_date = date(2026, 7, 15)

    class LimitedClient(FakeClient):
        def query_members(self, **kwargs) -> TushareDcQueryResult:
            return TushareDcQueryResult(
                api_name="dc_member",
                rows=tuple(
                    _member_row(source_date, f"{index:06d}.SZ")
                    for index in range(DC_MEMBER_ROW_LIMIT)
                ),
                limit_reached=True,
            )

    client = LimitedClient(
        index_by_date={source_date: (_index_row(source_date),)},
        members_by_date={},
    )

    with pytest.raises(DcMembershipImportError, match="row limit"):
        build_dc_membership_payload(
            client=client,
            research_source_dates={research_date: source_date},
            concepts=(_concept(),),
        )


def test_limited_range_is_split_until_each_window_is_complete() -> None:
    source_dates = (date(2026, 7, 13), date(2026, 7, 14))
    research_dates = (date(2026, 7, 14), date(2026, 7, 15))
    client = FakeClient(
        index_by_date={current: (_index_row(current),) for current in source_dates},
        members_by_date={current: (_member_row(current),) for current in source_dates},
        limit_ranges=True,
    )

    payload = build_dc_membership_payload(
        client=client,
        research_source_dates=dict(zip(research_dates, source_dates, strict=True)),
        concepts=(_concept(),),
    )

    assert len(payload.scopes) == 2
    assert client.member_calls == [
        (None, source_dates[0], source_dates[1]),
        (source_dates[0], None, None),
        (source_dates[1], None, None),
    ]


def test_source_status_is_unconfigured_without_touching_database(monkeypatch) -> None:
    class Settings:
        tushare_token = ""
        tushare_api_url = "https://api.tushare.pro"
        tushare_timeout_seconds = 12.0

    monkeypatch.setattr(
        "alphaagent.server.services.low_suction.dc_membership_import.get_settings",
        lambda: Settings(),
    )

    status = membership_source_status()

    assert status["status"] == "unconfigured"
    assert status["strict_ready"] is False
