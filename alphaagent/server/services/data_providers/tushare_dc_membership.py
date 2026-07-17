"""Read-only Tushare DC concept index and historical membership client."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import requests

DC_INDEX_API = "dc_index"
DC_MEMBER_API = "dc_member"
DC_MEMBER_SOURCE = "tushare.dc_member.lag1"
DC_MEMBER_ROW_LIMIT = 5_000
DC_SECTOR_SUFFIX = ".DC"
DC_SECTOR_PATTERN = re.compile(r"^BK\d{4}\.DC$")
LOCAL_SECTOR_PATTERN = re.compile(r"^BK\d{4}$")
DC_INDEX_FIELDS = (
    "ts_code,trade_date,name,leading,leading_code,pct_change,leading_pct,"
    "total_mv,turnover_rate,up_num,down_num,idx_type,level"
)
DC_MEMBER_FIELDS = "trade_date,ts_code,con_code,name"


class TushareDcQueryError(RuntimeError):
    """Raised when a Tushare DC response cannot be trusted as complete data."""


@dataclass(frozen=True)
class TushareDcQueryResult:
    api_name: str
    rows: tuple[dict[str, Any], ...]
    limit_reached: bool


def local_sector_id(ts_code: str) -> str:
    normalized = str(ts_code).strip().upper()
    if not DC_SECTOR_PATTERN.fullmatch(normalized):
        raise ValueError("Tushare DC sector code must be BKdddd.DC")
    return normalized.removesuffix(DC_SECTOR_SUFFIX)


def tushare_sector_code(sector_id: str) -> str:
    normalized = str(sector_id).strip().upper()
    if not LOCAL_SECTOR_PATTERN.fullmatch(normalized):
        raise ValueError("local sector ID must be an unsuffixed BKdddd code")
    return f"{normalized}{DC_SECTOR_SUFFIX}"


def dc_membership_source_status(*, token: str) -> dict[str, object]:
    configured = bool(str(token).strip())
    return {
        "status": "ready_for_probe" if configured else "unconfigured",
        "configured": configured,
        "required_points": 6_000,
        "apis": [DC_INDEX_API, DC_MEMBER_API],
        "strict_ready": False,
    }


class TushareDcMembershipClient:
    """Small typed wrapper around the two Tushare DC endpoints used here."""

    def __init__(
        self,
        *,
        token: str,
        api_url: str,
        timeout: float,
        post: Callable[..., Any] = requests.post,
    ) -> None:
        normalized_token = str(token).strip()
        if not normalized_token:
            raise ValueError("Tushare credentials are not configured")
        self._token = normalized_token
        self._api_url = str(api_url).strip()
        self._timeout = float(timeout)
        self._post = post

    def query_index(self, trade_date: date) -> TushareDcQueryResult:
        return self._query(
            DC_INDEX_API,
            params={
                "trade_date": _tushare_date(trade_date),
                "idx_type": "概念板块",
            },
            fields=DC_INDEX_FIELDS,
        )

    def query_members(
        self,
        *,
        sector_code: str,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> TushareDcQueryResult:
        local_sector_id(sector_code)
        params: dict[str, str] = {"ts_code": sector_code.strip().upper()}
        if trade_date is not None:
            if start_date is not None or end_date is not None:
                raise ValueError("trade_date cannot be combined with a date range")
            params["trade_date"] = _tushare_date(trade_date)
        elif start_date is not None and end_date is not None:
            if start_date > end_date:
                raise ValueError("start_date must not be after end_date")
            params["start_date"] = _tushare_date(start_date)
            params["end_date"] = _tushare_date(end_date)
        else:
            raise ValueError("one trade_date or a complete date range is required")
        return self._query(DC_MEMBER_API, params=params, fields=DC_MEMBER_FIELDS)

    def _query(
        self,
        api_name: str,
        *,
        params: Mapping[str, str],
        fields: str,
    ) -> TushareDcQueryResult:
        try:
            response = self._post(
                self._api_url,
                json={
                    "api_name": api_name,
                    "token": self._token,
                    "params": dict(params),
                    "fields": fields,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - provider errors share one boundary
            if isinstance(exc, TushareDcQueryError):
                raise
            raise TushareDcQueryError(
                f"Tushare {api_name} request failed: {exc.__class__.__name__}"
            ) from exc
        rows = self._response_rows(api_name, payload)
        return TushareDcQueryResult(
            api_name=api_name,
            rows=rows,
            limit_reached=len(rows) >= DC_MEMBER_ROW_LIMIT,
        )

    def _response_rows(
        self,
        api_name: str,
        payload: Any,
    ) -> tuple[dict[str, Any], ...]:
        if not isinstance(payload, Mapping):
            raise TushareDcQueryError(f"Tushare {api_name} returned a non-object")
        code = int(payload.get("code") or 0)
        if code != 0:
            message = str(payload.get("msg") or "provider error").replace(
                self._token,
                "[redacted]",
            )
            raise TushareDcQueryError(
                f"Tushare {api_name} failed with code {code}: {message[:200]}"
            )
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise TushareDcQueryError(f"Tushare {api_name} returned no data object")
        fields = data.get("fields")
        items = data.get("items")
        if not _is_sequence(fields) or not _is_sequence(items):
            raise TushareDcQueryError(
                f"Tushare {api_name} response is missing fields or items"
            )
        normalized_fields = tuple(str(field).strip() for field in fields)
        if not all(normalized_fields) or len(normalized_fields) != len(
            set(normalized_fields)
        ):
            raise TushareDcQueryError(
                f"Tushare {api_name} response fields are invalid"
            )
        rows: list[dict[str, Any]] = []
        for item in items:
            if not _is_sequence(item) or len(item) != len(normalized_fields):
                raise TushareDcQueryError(
                    f"Tushare {api_name} response row width is invalid"
                )
            rows.append(dict(zip(normalized_fields, item, strict=True)))
        return tuple(rows)


def _tushare_date(value: date) -> str:
    if not isinstance(value, date):
        raise TypeError("Tushare date must be a date value")
    return value.strftime("%Y%m%d")


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))
