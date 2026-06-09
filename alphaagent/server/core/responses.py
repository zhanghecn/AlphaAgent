"""Consistent API response helpers."""

from typing import Any


def ok(data: Any, request_id: str = "req_local") -> dict[str, Any]:
    """Build a successful API response."""

    return {
        "success": True,
        "data": data,
        "error": None,
        "request_id": request_id,
    }


def fail(
    code: str,
    message: str,
    detail: dict[str, Any] | None = None,
    request_id: str = "req_local",
) -> dict[str, Any]:
    """Build a failed API response."""

    return {
        "success": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "detail": detail or {},
        },
        "request_id": request_id,
    }

