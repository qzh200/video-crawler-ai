from __future__ import annotations

import hmac
from typing import Never

from fastapi import Header, HTTPException
from starlette.status import HTTP_401_UNAUTHORIZED

from video_crawler.core.config import get_settings


def _reject_api_key() -> Never:
    raise HTTPException(
        status_code=HTTP_401_UNAUTHORIZED,
        detail={
            "error": {
                "code": "UNAUTHORIZED",
                "message": "a valid API key is required",
                "request_id": None,
                "details": {},
            }
        },
        headers={"WWW-Authenticate": "ApiKey"},
    )


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.api_key_enabled:
        return
    if x_api_key is None:
        _reject_api_key()
    expected = settings.api_key.get_secret_value()
    if not hmac.compare_digest(x_api_key, expected):
        _reject_api_key()
