from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from alphaagent.server.services.low_suction.baostock_security_source import (
    BaoStockSourceError,
    fetch_reconstructed_security_history,
    fetch_security_master,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


class _Response:
    def __init__(self, error_code: str = "0", error_msg: str = "success") -> None:
        self.error_code = error_code
        self.error_msg = error_msg


class _Query(_Response):
    def __init__(
        self,
        fields: list[str],
        rows: list[list[str]],
        *,
        error_code: str = "0",
        error_msg: str = "success",
    ) -> None:
        super().__init__(error_code, error_msg)
        self.fields = fields
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


MASTER_FIELDS = ["code", "code_name", "ipoDate", "outDate", "type", "status"]
HISTORY_FIELDS = ["date", "code", "tradestatus", "isST"]


class _FakeClient:
    def __init__(self, *, history_error: bool = False) -> None:
        self.login_calls = 0
        self.logout_calls = 0
        self.history_error = history_error
        self.master_rows = [
            ["sh.600000", "浦发银行", "1999-11-10", "", "1", "1"],
            ["sh.600001", "邯郸钢铁", "1998-01-22", "2009-12-29", "1", "0"],
            ["sz.300001", "特锐德", "2009-10-30", "", "1", "1"],
            ["sh.000001", "上证指数", "1991-07-15", "", "2", "1"],
        ]

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

    def query_history_k_data_plus(
        self,
        code: str,
        fields: str,
        *,
        start_date: str,
        end_date: str,
        frequency: str,
        adjustflag: str,
    ) -> _Query:
        assert code == "sh.600000"
        assert fields == "date,code,tradestatus,isST"
        assert start_date == "2026-07-01"
        assert end_date == "2026-07-02"
        assert frequency == "d"
        assert adjustflag == "3"
        if self.history_error:
            return _Query(
                HISTORY_FIELDS,
                [],
                error_code="1001",
                error_msg="provider failure",
            )
        return _Query(
            HISTORY_FIELDS,
            [
                ["2026-07-01", code, "1", "1"],
                ["2026-07-02", code, "0", "0"],
            ],
        )


def test_master_keeps_delisted_main_board_and_labels_other_boards() -> None:
    client = _FakeClient()
    observed_at = datetime(2026, 7, 16, 12, tzinfo=SHANGHAI)

    result = fetch_security_master(client=client, observed_at=observed_at)

    assert result.total_source_rows == 4
    assert result.stock_rows == 3
    assert result.main_board_rows == 2
    assert result.delisted_main_board_rows == 1
    assert result.observed_at == observed_at
    assert [record.vt_symbol for record in result.records] == [
        "600000.SSE",
        "600001.SSE",
        "300001.SZSE",
    ]
    delisted = result.records[1]
    assert delisted.board == "main"
    assert delisted.status == "DELISTED"
    assert delisted.delisted_on == date(2009, 12, 29)
    assert result.records[2].board == "chinext"
    assert client.login_calls == 1
    assert client.logout_calls == 1


def test_daily_rows_are_reconstructed_and_keep_observation_time() -> None:
    client = _FakeClient()
    observed_at = datetime(2026, 7, 16, 12, tzinfo=SHANGHAI)

    rows = fetch_reconstructed_security_history(
        ["600000.SSE"],
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        observed_at=observed_at,
        client=client,
    )

    assert len(rows) == 2
    assert rows[0] == {
        "vt_symbol": "600000.SSE",
        "symbol": "600000",
        "exchange": "SSE",
        "name": "浦发银行",
        "status": "ST",
        "board": "main",
        "listed_on": date(1999, 11, 10),
        "delisted_on": None,
        "valid_from": date(2026, 7, 1),
        "valid_to": date(2026, 7, 2),
        "suspended": False,
        "risk_warning": True,
        "known_at": observed_at,
        "evidence_level": "reconstructed",
        "source": "baostock.query_history_k_data_plus",
        "source_record_id": "baostock:sh.600000:2026-07-01",
    }
    assert rows[1]["status"] == "SUSPENDED"
    assert rows[1]["valid_from"] == date(2026, 7, 2)
    assert rows[1]["valid_to"] == date(2026, 7, 3)
    assert rows[1]["known_at"] == observed_at
    assert rows[1]["evidence_level"] == "reconstructed"
    assert client.login_calls == 1
    assert client.logout_calls == 1


def test_provider_error_is_explicit_and_still_logs_out() -> None:
    client = _FakeClient(history_error=True)

    with pytest.raises(BaoStockSourceError, match="query_history_k_data_plus"):
        fetch_reconstructed_security_history(
            ["600000.SSE"],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 2),
            observed_at=datetime(2026, 7, 16, 12, tzinfo=SHANGHAI),
            client=client,
        )

    assert client.logout_calls == 1


def test_unsupported_exchange_is_rejected_before_provider_login() -> None:
    client = _FakeClient()

    with pytest.raises(BaoStockSourceError, match="unsupported vt_symbol"):
        fetch_reconstructed_security_history(
            ["830799.BSE"],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 2),
            observed_at=datetime(2026, 7, 16, 12, tzinfo=SHANGHAI),
            client=client,
        )

    assert client.login_calls == 0
    assert client.logout_calls == 0


def test_history_request_is_bounded() -> None:
    client = _FakeClient()

    with pytest.raises(BaoStockSourceError, match="at most 500 symbols"):
        fetch_reconstructed_security_history(
            [f"{index:06d}.SSE" for index in range(501)],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 2),
            observed_at=datetime(2026, 7, 16, 12, tzinfo=SHANGHAI),
            client=client,
        )

    assert client.login_calls == 0
