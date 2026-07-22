from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from video_crawler.domain.errors import UpstreamError
from video_crawler.domain.timed_text import NormalizedTimedText


def iter_danmaku_items(body: bytes) -> Iterator[NormalizedTimedText]:
    view = memoryview(body)
    position = 0
    while position < len(view):
        field_number, wire_type, value, position = _read_field(view, position)
        if field_number == 1 and wire_type == 2:
            if not isinstance(value, memoryview):
                raise UpstreamError("invalid Bilibili danmaku element")
            yield _parse_item(value)


def _parse_item(message: memoryview) -> NormalizedTimedText:
    values: dict[int, int | str] = {}
    position = 0
    while position < len(message):
        field_number, wire_type, value, position = _read_field(message, position)
        if field_number in {1, 2, 3, 4, 5, 8, 9, 11, 13} and wire_type == 0:
            if isinstance(value, int):
                values[field_number] = value
        elif field_number in {6, 7, 10, 12} and wire_type == 2:
            if isinstance(value, memoryview):
                try:
                    values[field_number] = value.tobytes().decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise UpstreamError("invalid Bilibili danmaku text encoding") from exc

    progress = _integer(values, 2, default=0)
    content = values.get(7)
    if not isinstance(content, str):
        raise UpstreamError("Bilibili danmaku element did not contain text")
    item_id = values.get(12)
    if not isinstance(item_id, str) or not item_id:
        numeric_id = _integer(values, 1, default=0)
        item_id = str(numeric_id) if numeric_id else None
    timestamp = _integer(values, 8, default=0)
    try:
        published_at = datetime.fromtimestamp(timestamp, UTC) if timestamp else None
    except (OverflowError, OSError, ValueError) as exc:
        raise UpstreamError("invalid Bilibili danmaku publication time") from exc
    sender = values.get(6)
    return NormalizedTimedText(
        platform_item_id=item_id,
        start_ms=progress,
        end_ms=None,
        text=content,
        published_at=published_at,
        sender_ref=sender if isinstance(sender, str) and sender else None,
        attributes={
            "mode": _integer(values, 3, default=0),
            "font_size": _integer(values, 4, default=0),
            "color": _integer(values, 5, default=0),
            "weight": _integer(values, 9, default=0),
            "action": _text(values, 10),
            "pool": _integer(values, 11, default=0),
            "attr": _integer(values, 13, default=0),
        },
    )


def _read_field(
    view: memoryview,
    position: int,
) -> tuple[int, int, int | memoryview, int]:
    key, position = _read_varint(view, position)
    field_number = key >> 3
    wire_type = key & 0x07
    if field_number == 0:
        raise UpstreamError("invalid Bilibili danmaku protobuf field")
    if wire_type == 0:
        value, position = _read_varint(view, position)
        return field_number, wire_type, value, position
    if wire_type == 1:
        return field_number, wire_type, _slice(view, position, 8), position + 8
    if wire_type == 2:
        length, position = _read_varint(view, position)
        return field_number, wire_type, _slice(view, position, length), position + length
    if wire_type == 5:
        return field_number, wire_type, _slice(view, position, 4), position + 4
    raise UpstreamError("unsupported Bilibili danmaku protobuf wire type")


def _read_varint(view: memoryview, position: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while position < len(view) and shift < 70:
        byte = view[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
        shift += 7
    raise UpstreamError("truncated Bilibili danmaku protobuf varint")


def _slice(view: memoryview, position: int, length: int) -> memoryview:
    end = position + length
    if length < 0 or end > len(view):
        raise UpstreamError("truncated Bilibili danmaku protobuf field")
    return view[position:end]


def _integer(values: dict[int, int | str], field: int, *, default: int) -> int:
    value = values.get(field)
    return value if isinstance(value, int) else default


def _text(values: dict[int, int | str], field: int) -> str:
    value = values.get(field)
    return value if isinstance(value, str) else ""
