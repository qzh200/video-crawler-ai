from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException
from starlette.status import HTTP_401_UNAUTHORIZED

from video_crawler.core.config import get_settings

_LOG = logging.getLogger(__name__)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.api_key_enabled:
        return None
    if x_api_key is None:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="missing api key")
    # constant-time compare
    expected = settings.api_key.get_secret_value()
    try:
        ok = hmac.compare_digest(x_api_key, expected)
    except Exception:  # defensive
        _LOG.exception("api key comparison failed")
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="invalid api key") from None
    if not ok:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="invalid api key")
    return None
