from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from video_crawler.adapters.base import AdapterContext

_HOME_URL = "https://www.bilibili.com/"
_API_HOST = "api.bilibili.com"
_NAV_PATH = "/x/web-interface/nav"


@dataclass(frozen=True, slots=True)
class BilibiliAuthVerification:
    is_valid: bool
    reason: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


async def verify_bilibili_auth(context: AdapterContext) -> BilibiliAuthVerification:
    page = await context.browser.open_page(
        _HOME_URL,
        timeout_seconds=30,
        capture_network=True,
    )
    try:
        for response in context.network_capture.responses_for(page):
            parsed_url = urlsplit(response.url)
            if (
                response.status_code != 200
                or parsed_url.scheme != "https"
                or parsed_url.hostname != _API_HOST
                or parsed_url.path != _NAV_PATH
            ):
                continue
            is_login = _parse_login_state(response.body)
            if is_login is not None:
                return _result(is_login)
        dom_state = await page.evaluate(
            """() => ({
  hasAvatar: Boolean(document.querySelector('.header-avatar-wrap')),
  hasLoginEntry: Boolean(document.querySelector('.header-login-entry'))
})"""
        )
        is_login = _parse_dom_state(dom_state)
        if is_login is not None:
            return _result(is_login)
        return BilibiliAuthVerification(False, "verification_unavailable")
    finally:
        await page.close()


def _parse_login_state(body: bytes) -> bool | None:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    is_login = data.get("isLogin")
    return is_login if isinstance(is_login, bool) else None


def _result(is_valid: bool) -> BilibiliAuthVerification:
    return BilibiliAuthVerification(
        is_valid=is_valid,
        reason=None if is_valid else "not_authenticated",
    )


def _parse_dom_state(value: object) -> bool | None:
    if not isinstance(value, Mapping):
        return None
    has_avatar = value.get("hasAvatar")
    has_login_entry = value.get("hasLoginEntry")
    if not isinstance(has_avatar, bool) or not isinstance(has_login_entry, bool):
        return None
    return has_avatar and not has_login_entry
