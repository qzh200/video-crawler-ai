from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass
from math import ceil
from typing import Any

from video_crawler.adapters.base import AdapterContext
from video_crawler.adapters.bilibili.parsers.danmaku import iter_danmaku_items
from video_crawler.adapters.bilibili.parsers.subtitles import (
    SubtitleTrack,
    iter_subtitle_items,
    parse_subtitle_tracks,
)
from video_crawler.adapters.bilibili.resolver import PLATFORM_KEY
from video_crawler.application.gateways import HttpResponse, MetadataValue
from video_crawler.domain.artifacts import RawArtifactRef
from video_crawler.domain.errors import UpstreamError
from video_crawler.domain.strategy import CrawlStrategy
from video_crawler.domain.targets import VideoTarget
from video_crawler.domain.timed_text import (
    NormalizedTimedText,
    TimedTextBatch,
    TimedTextStreamDescriptor,
    TimedTextType,
)

_VIDEO_UNITS_URL = "https://api.bilibili.com/x/web-interface/view"
_DANMAKU_URL = "https://api.bilibili.com/x/v2/dm/web/seg.so"
_SUBTITLE_INDEX_URL = "https://api.bilibili.com/x/player/v2"
_DANMAKU_SEGMENT_SECONDS = 360


@dataclass(frozen=True, slots=True)
class _VideoUnit:
    platform_unit_id: str
    duration_seconds: int


async def fetch_bilibili_timed_text(
    context: AdapterContext,
    target: VideoTarget,
    strategy: CrawlStrategy,
) -> AsyncIterator[TimedTextBatch]:
    if target.platform != PLATFORM_KEY:
        raise ValueError("Bilibili timed text requires a Bilibili video target")
    if not strategy.fetch_all_danmaku and not strategy.fetch_all_subtitles:
        return

    response, _ = await _fetch_and_archive(
        context,
        _VIDEO_UNITS_URL,
        params={"bvid": target.platform_video_id},
        strategy=strategy,
        artifact_type="timed_text_units",
        metadata={"platform_video_id": target.platform_video_id},
    )
    units = _parse_video_units(response.body)
    for unit in units:
        context.cancellation.raise_if_cancelled()
        if strategy.fetch_all_danmaku:
            async for batch in _fetch_danmaku(context, target, unit, strategy):
                yield batch
        if strategy.fetch_all_subtitles:
            async for batch in _fetch_subtitles(context, target, unit, strategy):
                yield batch


async def _fetch_danmaku(
    context: AdapterContext,
    target: VideoTarget,
    unit: _VideoUnit,
    strategy: CrawlStrategy,
) -> AsyncIterator[TimedTextBatch]:
    segment_count = max(1, ceil(unit.duration_seconds / _DANMAKU_SEGMENT_SECONDS))
    descriptor = TimedTextStreamDescriptor(
        platform_unit_id=unit.platform_unit_id,
        content_type=TimedTextType.DANMAKU,
        stream_key=f"danmaku:{unit.platform_unit_id}",
        language_code=None,
        source_type="protobuf",
        attributes={"segment_count": segment_count},
    )
    buffered: list[NormalizedTimedText] = []
    batch_artifacts: list[RawArtifactRef] = []
    for segment_index in range(1, segment_count + 1):
        response, artifact = await _fetch_and_archive(
            context,
            _DANMAKU_URL,
            params={
                "type": 1,
                "oid": int(unit.platform_unit_id),
                "segment_index": segment_index,
            },
            strategy=strategy,
            artifact_type="danmaku",
            metadata={
                "platform_video_id": target.platform_video_id,
                "platform_unit_id": unit.platform_unit_id,
                "segment_index": segment_index,
            },
        )
        for item in iter_danmaku_items(response.body):
            if not buffered:
                batch_artifacts = [artifact]
            elif artifact not in batch_artifacts:
                batch_artifacts.append(artifact)
            buffered.append(item)
            if len(buffered) == strategy.timed_text_batch_size:
                context.cancellation.raise_if_cancelled()
                yield TimedTextBatch(
                    stream=descriptor,
                    items=tuple(buffered),
                    raw_artifacts=tuple(batch_artifacts),
                )
                buffered.clear()
                batch_artifacts.clear()
    if buffered:
        context.cancellation.raise_if_cancelled()
        yield TimedTextBatch(
            stream=descriptor,
            items=tuple(buffered),
            raw_artifacts=tuple(batch_artifacts),
        )


async def _fetch_subtitles(
    context: AdapterContext,
    target: VideoTarget,
    unit: _VideoUnit,
    strategy: CrawlStrategy,
) -> AsyncIterator[TimedTextBatch]:
    response, index_artifact = await _fetch_and_archive(
        context,
        _SUBTITLE_INDEX_URL,
        params={"bvid": target.platform_video_id, "cid": int(unit.platform_unit_id)},
        strategy=strategy,
        artifact_type="subtitle_index",
        metadata={
            "platform_video_id": target.platform_video_id,
            "platform_unit_id": unit.platform_unit_id,
        },
    )
    for track in parse_subtitle_tracks(response.body):
        async for batch in _fetch_subtitle_track(
            context,
            target,
            unit,
            track,
            index_artifact,
            strategy,
        ):
            yield batch


async def _fetch_subtitle_track(
    context: AdapterContext,
    target: VideoTarget,
    unit: _VideoUnit,
    track: SubtitleTrack,
    index_artifact: RawArtifactRef,
    strategy: CrawlStrategy,
) -> AsyncIterator[TimedTextBatch]:
    response, artifact = await _fetch_and_archive(
        context,
        track.url,
        params=None,
        strategy=strategy,
        artifact_type="subtitle",
        metadata={
            "platform_video_id": target.platform_video_id,
            "platform_unit_id": unit.platform_unit_id,
            "track_id": track.track_id,
            "language_code": track.language_code,
        },
    )
    descriptor = TimedTextStreamDescriptor(
        platform_unit_id=unit.platform_unit_id,
        content_type=TimedTextType.SUBTITLE,
        stream_key=f"subtitle:{track.track_id}",
        language_code=track.language_code,
        source_type="json",
        attributes={"track_id": track.track_id, "language_name": track.language_name},
    )
    for items in _batches(iter_subtitle_items(response.body), strategy.timed_text_batch_size):
        context.cancellation.raise_if_cancelled()
        yield TimedTextBatch(
            stream=descriptor,
            items=items,
            raw_artifacts=(index_artifact, artifact),
        )


async def _fetch_and_archive(
    context: AdapterContext,
    url: str,
    *,
    params: Mapping[str, str | int | float] | None,
    strategy: CrawlStrategy,
    artifact_type: str,
    metadata: Mapping[str, MetadataValue],
) -> tuple[HttpResponse, RawArtifactRef]:
    context.cancellation.raise_if_cancelled()
    response = await context.http.request(
        "GET",
        url,
        params=params,
        timeout_seconds=strategy.request_timeout_seconds,
    )
    artifact = await context.raw_artifacts.store(
        response.body,
        artifact_type=artifact_type,
        content_type=_content_type(response.headers),
        metadata=metadata,
    )
    context.cancellation.raise_if_cancelled()
    if response.status_code != 200:
        raise UpstreamError(
            f"Bilibili {artifact_type} request returned status {response.status_code}"
        )
    return response, artifact


def _parse_video_units(body: bytes) -> tuple[_VideoUnit, ...]:
    try:
        payload: Any = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UpstreamError("invalid Bilibili video unit response") from exc
    if not isinstance(payload, Mapping) or payload.get("code") != 0:
        raise UpstreamError("Bilibili video unit request was rejected")
    data = payload.get("data")
    raw_units = data.get("pages") if isinstance(data, Mapping) else None
    if not isinstance(raw_units, list) or not raw_units:
        raise UpstreamError("Bilibili video unit response did not contain pages")
    units: list[_VideoUnit] = []
    for raw_unit in raw_units:
        if not isinstance(raw_unit, Mapping):
            raise UpstreamError("invalid Bilibili video unit")
        cid = raw_unit.get("cid")
        duration = raw_unit.get("duration")
        if (
            isinstance(cid, bool)
            or not isinstance(cid, int)
            or cid <= 0
            or isinstance(duration, bool)
            or not isinstance(duration, int)
            or duration < 0
        ):
            raise UpstreamError("invalid Bilibili video unit identifiers")
        units.append(_VideoUnit(platform_unit_id=str(cid), duration_seconds=duration))
    return tuple(units)


def _batches(
    items: Iterator[NormalizedTimedText],
    batch_size: int,
) -> Iterator[tuple[NormalizedTimedText, ...]]:
    batch: list[NormalizedTimedText] = []
    for item in items:
        batch.append(item)
        if len(batch) == batch_size:
            yield tuple(batch)
            batch.clear()
    if batch:
        yield tuple(batch)


def _content_type(headers: Mapping[str, str]) -> str:
    for name, value in headers.items():
        if name.lower() == "content-type":
            return value
    return "application/octet-stream"
