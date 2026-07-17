from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from alphaagent.server.db import schema
from alphaagent.server.services.low_suction import forward_security_repository
from alphaagent.server.services.low_suction.baostock_security_source import (
    BaoStockSourceError,
    fetch_forward_security_snapshot,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE_DATE = date(2026, 7, 16)
OBSERVED_AT = datetime(2026, 7, 16, 19, 5, tzinfo=SHANGHAI)
MASTER_FIELDS = ["code", "code_name", "ipoDate", "outDate", "type", "status"]
DAILY_FIELDS = ["code", "tradeStatus", "code_name"]


class _Response:
    error_code = "0"
    error_msg = "success"


class _Query(_Response):
    def __init__(
        self,
        fields: list[str],
        rows: list[list[str]],
        *,
        day: str = "",
    ) -> None:
        self.fields = fields
        self.day = day
        self._rows = iter(rows)
        self._current: list[str] | None = None

    def next(self) -> bool:
        try:
            self._current = next(self._rows)
        except StopIteration:
            self._current = None
            return False
        return True

    def get_row_data(self) -> list[str]:
        assert self._current is not None
        return self._current


def _master_rows() -> list[list[str]]:
    return [
        ["sh.600000", "浦发银行", "1999-11-10", "", "1", "1"],
        ["sz.000001", "平安银行", "1991-04-03", "", "1", "1"],
        ["sh.603999", "读者传媒", "2015-12-10", "2026-07-17", "1", "0"],
        ["sh.600001", "邯郸钢铁", "1998-01-22", "2009-12-29", "1", "0"],
        ["sh.605999", "未来股份", "2027-01-01", "", "1", "1"],
        ["sz.300001", "特锐德", "2009-10-30", "", "1", "1"],
        ["sh.688001", "华兴源创", "2019-07-22", "", "1", "1"],
        ["sh.000001", "上证指数", "1991-07-15", "", "2", "1"],
    ]


def _daily_rows() -> list[list[str]]:
    return [
        ["sh.600000", "1", "*ST浦发"],
        ["sz.000001", "0", "平安银行"],
        ["sh.603999", "1", "退市读者"],
        ["sz.300001", "1", "特锐德"],
        ["sh.688001", "1", "华兴源创"],
        ["sh.000001", "1", "上证指数"],
    ]


class _FakeClient:
    def __init__(
        self,
        *,
        master_rows: list[list[str]] | None = None,
        daily_rows: list[list[str]] | None = None,
        response_day: str = SOURCE_DATE.isoformat(),
    ) -> None:
        self.master_rows = master_rows if master_rows is not None else _master_rows()
        self.daily_rows = daily_rows if daily_rows is not None else _daily_rows()
        self.response_day = response_day
        self.login_calls = 0
        self.logout_calls = 0
        self.requested_days: list[str] = []

    def login(self) -> _Response:
        self.login_calls += 1
        return _Response()

    def logout(self) -> _Response:
        self.logout_calls += 1
        return _Response()

    def query_stock_basic(self, code: str = "", code_name: str = "") -> _Query:
        del code_name
        rows = self.master_rows
        if code:
            rows = [row for row in rows if row[0] == code]
        return _Query(MASTER_FIELDS, rows)

    def query_all_stock(self, day: str) -> _Query:
        self.requested_days.append(day)
        return _Query(
            DAILY_FIELDS,
            self.daily_rows,
            day=self.response_day,
        )


def test_forward_snapshot_keeps_st_delisting_and_suspended_rows() -> None:
    client = _FakeClient()

    result = fetch_forward_security_snapshot(
        source_trade_date=SOURCE_DATE,
        observed_at=OBSERVED_AT,
        client=client,
    )

    assert result.source_trade_date == SOURCE_DATE
    assert result.observed_at == OBSERVED_AT
    assert result.expected_symbol_count == 3
    assert result.returned_symbol_count == 3
    assert result.missing_symbols == ()
    assert result.risk_warning_count == 2
    assert result.suspended_count == 1
    assert [record.vt_symbol for record in result.records] == [
        "000001.SZSE",
        "600000.SSE",
        "603999.SSE",
    ]
    records = {record.vt_symbol: record for record in result.records}
    assert records["000001.SZSE"].suspended is True
    assert records["600000.SSE"].risk_warning is True
    assert records["603999.SSE"].risk_warning is True
    assert records["603999.SSE"].delisted_on == date(2026, 7, 17)
    assert all(record.board == "main" for record in result.records)
    assert all(record.evidence_level == "strict" for record in result.records)
    assert all(
        record.source == "baostock.query_all_stock.forward"
        for record in result.records
    )
    assert client.requested_days == [SOURCE_DATE.isoformat()]
    assert client.login_calls == 1
    assert client.logout_calls == 1


def test_forward_snapshot_rejects_one_missing_active_main_board_stock() -> None:
    client = _FakeClient(
        daily_rows=[row for row in _daily_rows() if row[0] != "sz.000001"]
    )

    with pytest.raises(BaoStockSourceError, match=r"missing.*000001\.SZSE"):
        fetch_forward_security_snapshot(
            source_trade_date=SOURCE_DATE,
            observed_at=OBSERVED_AT,
            client=client,
        )

    assert client.logout_calls == 1


def test_forward_snapshot_excludes_stock_on_its_delisting_date() -> None:
    master_rows = [
        [
            *row[:3],
            SOURCE_DATE.isoformat() if row[0] == "sh.603999" else row[3],
            *row[4:],
        ]
        for row in _master_rows()
    ]
    daily_rows = [row for row in _daily_rows() if row[0] != "sh.603999"]

    result = fetch_forward_security_snapshot(
        source_trade_date=SOURCE_DATE,
        observed_at=OBSERVED_AT,
        client=_FakeClient(master_rows=master_rows, daily_rows=daily_rows),
    )

    assert result.expected_symbol_count == 2
    assert result.returned_symbol_count == 2
    assert {record.vt_symbol for record in result.records} == {
        "000001.SZSE",
        "600000.SSE",
    }


def test_forward_snapshot_rejects_duplicate_expected_code() -> None:
    client = _FakeClient(daily_rows=[*_daily_rows(), _daily_rows()[0]])

    with pytest.raises(BaoStockSourceError, match=r"duplicate.*600000\.SSE"):
        fetch_forward_security_snapshot(
            source_trade_date=SOURCE_DATE,
            observed_at=OBSERVED_AT,
            client=client,
        )


def test_forward_snapshot_rejects_duplicate_master_code() -> None:
    client = _FakeClient(master_rows=[*_master_rows(), _master_rows()[0]])

    with pytest.raises(BaoStockSourceError, match=r"master.*duplicate.*600000\.SSE"):
        fetch_forward_security_snapshot(
            source_trade_date=SOURCE_DATE,
            observed_at=OBSERVED_AT,
            client=client,
        )


def test_forward_snapshot_rejects_wrong_provider_date() -> None:
    client = _FakeClient(response_day="2026-07-15")

    with pytest.raises(BaoStockSourceError, match="response date"):
        fetch_forward_security_snapshot(
            source_trade_date=SOURCE_DATE,
            observed_at=OBSERVED_AT,
            client=client,
        )


def test_forward_snapshot_requires_same_day_post_close_observation() -> None:
    client = _FakeClient()

    with pytest.raises(BaoStockSourceError, match="post-close"):
        fetch_forward_security_snapshot(
            source_trade_date=SOURCE_DATE,
            observed_at=datetime(2026, 7, 16, 14, 59, tzinfo=SHANGHAI),
            client=client,
        )
    with pytest.raises(BaoStockSourceError, match="same Shanghai date"):
        fetch_forward_security_snapshot(
            source_trade_date=SOURCE_DATE,
            observed_at=datetime(2026, 7, 17, 8, 0, tzinfo=SHANGHAI),
            client=client,
        )

    assert client.login_calls == 0


def test_forward_snapshot_requires_timezone_aware_observation() -> None:
    client = _FakeClient()

    with pytest.raises(BaoStockSourceError, match="timezone"):
        fetch_forward_security_snapshot(
            source_trade_date=SOURCE_DATE,
            observed_at=datetime(2026, 7, 16, 19, 0),
            client=client,
        )

    assert client.login_calls == 0


def test_forward_security_snapshot_tables_define_source_isolated_keys() -> None:
    records = schema.low_suction_security_snapshots
    scopes = schema.low_suction_security_snapshot_scopes

    assert [column.name for column in records.primary_key.columns] == [
        "source_trade_date",
        "vt_symbol",
        "source",
    ]
    assert [column.name for column in scopes.primary_key.columns] == [
        "source_trade_date",
        "source",
    ]
    assert {
        "observed_at",
        "listed_on",
        "delisted_on",
        "suspended",
        "risk_warning",
        "evidence_level",
        "raw",
    }.issubset(records.c.keys())
    assert {
        "expected_symbol_count",
        "returned_symbol_count",
        "complete",
        "evidence_level",
        "raw",
    }.issubset(scopes.c.keys())


def _complete_result():
    return fetch_forward_security_snapshot(
        source_trade_date=SOURCE_DATE,
        observed_at=OBSERVED_AT,
        client=_FakeClient(),
    )


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda result: replace(
                result,
                records=(),
                expected_symbol_count=0,
                returned_symbol_count=0,
            ),
            "cannot be empty",
        ),
        (
            lambda result: replace(result, returned_symbol_count=2),
            "count mismatch",
        ),
        (
            lambda result: replace(
                result,
                records=(result.records[0], result.records[0], result.records[2]),
            ),
            "unique",
        ),
        (
            lambda result: replace(
                result,
                records=(
                    replace(
                        result.records[0],
                        source_trade_date=date(2026, 7, 15),
                    ),
                    *result.records[1:],
                ),
            ),
            "source date",
        ),
        (
            lambda result: replace(
                result,
                records=(
                    replace(result.records[0], source="another.provider"),
                    *result.records[1:],
                ),
            ),
            "source",
        ),
        (
            lambda result: replace(
                result,
                observed_at=result.observed_at.replace(tzinfo=None),
            ),
            "timezone",
        ),
        (
            lambda result: replace(
                result,
                missing_symbols=("600123.SSE",),
            ),
            "missing symbols",
        ),
        (
            lambda result: replace(
                result,
                records=(
                    replace(result.records[0], delisted_on=SOURCE_DATE),
                    *result.records[1:],
                ),
            ),
            "delisted on or before",
        ),
    ],
)
def test_repository_rejects_invalid_snapshot_before_opening_database(
    monkeypatch,
    mutate,
    message: str,
) -> None:
    result = mutate(_complete_result())
    monkeypatch.setattr(
        forward_security_repository,
        "get_engine",
        lambda: pytest.fail("invalid snapshot must not open the database"),
    )

    with pytest.raises(ValueError, match=message):
        forward_security_repository.replace_forward_security_snapshot(result)


def test_repository_atomically_replaces_only_one_source_date(monkeypatch) -> None:
    result = _complete_result()
    executed: list[tuple[Any, Any]] = []
    ensured: list[object] = []
    engine = object()

    class FakeSession:
        def execute(self, statement, parameters=None):
            executed.append((statement, parameters))

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(
        forward_security_repository,
        "MIN_FORWARD_MAIN_BOARD_SYMBOLS",
        1,
    )
    monkeypatch.setattr(forward_security_repository, "get_engine", lambda: engine)
    monkeypatch.setattr(
        forward_security_repository.schema,
        "ensure_schema_once",
        lambda value: ensured.append(value),
    )
    monkeypatch.setattr(
        forward_security_repository,
        "session_scope",
        fake_session_scope,
    )

    written = forward_security_repository.replace_forward_security_snapshot(result)

    assert written == 3
    assert ensured == [engine]
    assert len(executed) == 4
    record_delete, scope_delete, record_insert, scope_insert = executed
    assert record_delete[0].is_delete
    assert scope_delete[0].is_delete
    assert "source_trade_date" in str(record_delete[0])
    assert "source" in str(record_delete[0])
    assert "source_trade_date" in str(scope_delete[0])
    assert "source" in str(scope_delete[0])
    assert record_insert[0].is_insert
    assert len(record_insert[1]) == 3
    assert scope_insert[0].is_insert
    assert scope_insert[1]["complete"] is True
    assert scope_insert[1]["expected_symbol_count"] == 3
    assert scope_insert[1]["returned_symbol_count"] == 3
    assert scope_insert[1]["source"] == "baostock.query_all_stock.forward"
