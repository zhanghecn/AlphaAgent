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
