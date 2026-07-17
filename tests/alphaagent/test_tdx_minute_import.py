from __future__ import annotations

import pytest

from alphaagent.server.services.data_providers import tdx_minute_import
from alphaagent.server.services.minute_provider_imports import (
    MinuteProviderImportError,
    minute_gap_fetch_interval,
)


def test_tdx_interval_categories_preserve_one_minute_and_add_five_minute() -> None:
    assert tdx_minute_import.SUPPORTED_INTERVALS == {"1m": 8, "5m": 0}


def test_full_five_minute_session_requires_48_unique_bars() -> None:
    assert tdx_minute_import.required_tdx_tail_bars("5m", "09:35", "15:00") == 48
    assert tdx_minute_import.required_tdx_tail_bars("5m", "14:30", "14:30") == 1


def test_existing_one_minute_gap_contract_still_requires_one_tail_bar() -> None:
    assert tdx_minute_import.required_tdx_tail_bars("1m", "14:30", "14:30") == 1


def test_provider_interval_validation_accepts_five_minutes_only_when_requested() -> None:
    assert minute_gap_fetch_interval("tdx", "1m") == "1m"
    assert minute_gap_fetch_interval("tdx", "5m") == "5m"
    with pytest.raises(MinuteProviderImportError, match="Unsupported minute gap interval"):
        minute_gap_fetch_interval("tdx", "15m")


def test_tdx_connection_skips_host_that_cannot_serve_bars(monkeypatch) -> None:
    from pytdx.config import hosts
    from pytdx import hq

    instances = []

    class FakeApi:
        def __init__(self, *, raise_exception: bool) -> None:
            assert raise_exception is True
            self.ip = ""
            self.disconnected = False
            instances.append(self)

        def connect(self, ip: str, port: int, *, time_out: float) -> bool:
            del port, time_out
            self.ip = ip
            return True

        def get_security_bars(
            self,
            category: int,
            market: int,
            symbol: str,
            start: int,
            count: int,
        ) -> list[dict[str, object]]:
            assert (category, market, symbol, start, count) == (8, 0, "002747", 0, 1)
            if self.ip == "bad-host":
                raise RuntimeError("bar command unavailable")
            return []

        def disconnect(self) -> None:
            self.disconnected = True

    monkeypatch.setattr(
        hosts,
        "hq_hosts",
        [("bad", "bad-host", 7709), ("good", "good-host", 7709)],
    )
    monkeypatch.setattr(hq, "TdxHq_API", FakeApi)

    api, selected = tdx_minute_import._connect_tdx(
        timeout_seconds=1,
        probe=(8, 0, "002747"),
    )

    assert selected == {"name": "good", "ip": "good-host", "port": 7709}
    assert api is instances[1]
    assert instances[0].disconnected is True
