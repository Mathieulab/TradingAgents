"""Small structured response helpers for future MCP wrappers."""

from __future__ import annotations

from typing import Any


def ok(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "data": data,
        "error": None,
        "meta": meta or {},
    }


def fail(
    message: str,
    *,
    code: str = "ERROR",
    details: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
        "meta": meta or {},
    }
