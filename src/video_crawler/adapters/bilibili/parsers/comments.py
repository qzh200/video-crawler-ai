from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from video_crawler.domain.comments import NormalizedComment
from video_crawler.domain.errors import UpstreamError


@dataclass(frozen=True, slots=True)
class ParsedCommentPage:
    items: tuple[NormalizedComment, ...]
    next_cursor: str | None
    has_more: bool


def parse_root_page(body: bytes) -> ParsedCommentPage:
    data = _response_data(body)
    items = _parse_items(data.get("replies"), root_override=None)
    cursor = data.get("cursor")
    if not isinstance(cursor, Mapping):
        return ParsedCommentPage(items, None, False)
    is_end = cursor.get("is_end") is True
    next_value = _platform_id(cursor.get("next"))
    has_more = not is_end and next_value is not None
    return ParsedCommentPage(items, next_value if has_more else None, has_more)


def parse_reply_page(body: bytes, *, root_platform_comment_id: str) -> ParsedCommentPage:
    data = _response_data(body)
    items = _parse_items(data.get("replies"), root_override=root_platform_comment_id)
    page = data.get("page")
    if not isinstance(page, Mapping):
        return ParsedCommentPage(items, None, False)
    number = _nonnegative_int(page.get("num"))
    size = _nonnegative_int(page.get("size"))
    count = _nonnegative_int(page.get("count"))
    has_more = (
        number is not None
        and size is not None
        and count is not None
        and size > 0
        and number * size < count
    )
    next_cursor = str(number + 1) if has_more and number is not None else None
    return ParsedCommentPage(items, next_cursor, has_more)


def _response_data(body: bytes) -> Mapping[str, Any]:
    try:
        payload: Any = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UpstreamError("invalid Bilibili comments response") from exc
    if not isinstance(payload, Mapping) or payload.get("code") != 0:
        raise UpstreamError("Bilibili comments request was rejected")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise UpstreamError("Bilibili comments response did not contain data")
    return data


def _parse_items(value: object, *, root_override: str | None) -> tuple[NormalizedComment, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    items: list[NormalizedComment] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        platform_comment_id = _platform_id(entry.get("rpid"))
        if platform_comment_id is None:
            continue
        root_id = _platform_id(entry.get("root")) if root_override is not None else None
        parent_id = _platform_id(entry.get("parent")) if root_override is not None else None
        member = entry.get("member")
        member_values = member if isinstance(member, Mapping) else {}
        content = entry.get("content")
        content_values = content if isinstance(content, Mapping) else {}
        state = entry.get("state")
        items.append(
            NormalizedComment(
                platform_comment_id=platform_comment_id,
                root_platform_comment_id=root_id or root_override,
                parent_platform_comment_id=parent_id or root_override,
                author_platform_id=_platform_id(member_values.get("mid")),
                author_name=_optional_string(member_values.get("uname")),
                content=_optional_string(content_values.get("message")) or "",
                like_count=_nonnegative_int(entry.get("like")),
                reply_count=_nonnegative_int(entry.get("rcount")),
                published_at=_published_at(entry.get("ctime")),
                status="active" if state == 0 else "unavailable",
                attributes={"state": state} if isinstance(state, int) else {},
            )
        )
    return tuple(items)


def _platform_id(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized if normalized and normalized != "0" else None
    return None


def _nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _published_at(value: object) -> datetime | None:
    timestamp = _nonnegative_int(value)
    return datetime.fromtimestamp(timestamp, tz=UTC) if timestamp is not None else None
