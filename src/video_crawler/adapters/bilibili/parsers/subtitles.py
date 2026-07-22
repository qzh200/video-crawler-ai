from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from video_crawler.domain.errors import UpstreamError
from video_crawler.domain.timed_text import NormalizedTimedText


@dataclass(frozen=True, slots=True)
class SubtitleTrack:
    track_id: str
    language_code: str
    language_name: str | None
    url: str


def parse_subtitle_tracks(body: bytes) -> tuple[SubtitleTrack, ...]:
    payload = _mapping_payload(body, "subtitle index")
    if payload.get("code") != 0:
        raise UpstreamError("Bilibili subtitle index request was rejected")
    data = payload.get("data")
    subtitle = data.get("subtitle") if isinstance(data, Mapping) else None
    raw_tracks = subtitle.get("subtitles") if isinstance(subtitle, Mapping) else None
    if raw_tracks is None:
        return ()
    if not isinstance(raw_tracks, list):
        raise UpstreamError("invalid Bilibili subtitle track list")
    tracks: list[SubtitleTrack] = []
    for raw_track in raw_tracks:
        if not isinstance(raw_track, Mapping):
            raise UpstreamError("invalid Bilibili subtitle track")
        track_id = _identifier(raw_track.get("id"))
        language_code = raw_track.get("lan")
        raw_url = raw_track.get("subtitle_url")
        if track_id is None or not isinstance(language_code, str) or not language_code:
            raise UpstreamError("incomplete Bilibili subtitle track")
        if not isinstance(raw_url, str) or not raw_url:
            raise UpstreamError("Bilibili subtitle track did not contain a URL")
        url = f"https:{raw_url}" if raw_url.startswith("//") else raw_url
        if not url.startswith("https://"):
            raise UpstreamError("Bilibili subtitle track URL must use HTTPS")
        language_name = raw_track.get("lan_doc")
        tracks.append(
            SubtitleTrack(
                track_id=track_id,
                language_code=language_code,
                language_name=language_name if isinstance(language_name, str) else None,
                url=url,
            )
        )
    return tuple(tracks)


def iter_subtitle_items(body: bytes) -> Iterator[NormalizedTimedText]:
    payload = _mapping_payload(body, "subtitle body")
    raw_items = payload.get("body")
    if not isinstance(raw_items, list):
        raise UpstreamError("invalid Bilibili subtitle body")
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            raise UpstreamError("invalid Bilibili subtitle item")
        text = raw_item.get("content")
        if not isinstance(text, str):
            raise UpstreamError("Bilibili subtitle item did not contain text")
        start_ms = _milliseconds(raw_item.get("from"), "from")
        end_ms = _milliseconds(raw_item.get("to"), "to")
        item_id = _identifier(raw_item.get("id"))
        attributes = {
            str(key): value
            for key, value in raw_item.items()
            if key not in {"id", "from", "to", "content"}
        }
        yield NormalizedTimedText(
            platform_item_id=item_id,
            start_ms=start_ms,
            end_ms=end_ms,
            text=text,
            published_at=None,
            sender_ref=None,
            attributes=attributes,
        )


def _mapping_payload(body: bytes, source: str) -> Mapping[str, Any]:
    try:
        payload: Any = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UpstreamError(f"invalid Bilibili {source} response") from exc
    if not isinstance(payload, Mapping):
        raise UpstreamError(f"invalid Bilibili {source} response")
    return payload


def _milliseconds(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise UpstreamError(f"invalid Bilibili subtitle {field} timestamp")
    try:
        milliseconds = Decimal(str(value)) * 1000
    except InvalidOperation as exc:
        raise UpstreamError(f"invalid Bilibili subtitle {field} timestamp") from exc
    if not milliseconds.is_finite() or milliseconds < 0:
        raise UpstreamError(f"invalid Bilibili subtitle {field} timestamp")
    return int(milliseconds)


def _identifier(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | str) and str(value):
        return str(value)
    return None
