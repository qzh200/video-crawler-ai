from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from video_crawler.adapters.base import AdapterContext
from video_crawler.adapters.bilibili import BilibiliAdapter
from video_crawler.adapters.bilibili.parsers.danmaku import iter_danmaku_items
from video_crawler.adapters.bilibili.parsers.subtitles import (
    iter_subtitle_items,
    parse_subtitle_tracks,
)
from video_crawler.application.gateways import HttpResponse
from video_crawler.domain.strategy import CrawlStrategy
from video_crawler.domain.targets import VideoTarget
from video_crawler.domain.timed_text import (
    TimedTextType,
    build_timed_text_dedup_key,
)

FIXTURES = Path(__file__).parents[3] / "fixtures" / "bilibili"
DANMAKU = (FIXTURES / "danmaku.bin").read_bytes()
SUBTITLE = (FIXTURES / "subtitle_zh.json").read_bytes()
TARGET = VideoTarget(
    platform="bilibili",
    platform_video_id="BV1FAKE00001",
    canonical_url="https://www.bilibili.com/video/BV1FAKE00001",
    platform_ids={"bvid": "BV1FAKE00001"},
)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


VIDEO_UNITS = _json_bytes(
    {
        "code": 0,
        "data": {
            "pages": [
                {"cid": 5001, "page": 1, "duration": 120},
                {"cid": 5002, "page": 2, "duration": 120},
            ]
        },
    }
)
SUBTITLE_INDEX = _json_bytes(
    {
        "code": 0,
        "data": {
            "subtitle": {
                "subtitles": [
                    {
                        "id": 7001,
                        "lan": "zh-CN",
                        "lan_doc": "Chinese",
                        "subtitle_url": "//fixtures.example/subtitle/7001.json",
                    }
                ]
            }
        },
    }
)
NO_SUBTITLES = b'{"code":0,"data":{"subtitle":{"subtitles":[]}}}'


class FakeHttp:
    def __init__(self, *, danmaku: bytes = DANMAKU) -> None:
        self.danmaku = danmaku
        self.calls: list[tuple[str, Mapping[str, str | int | float] | None]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str | int | float] | None = None,
        content: bytes | None = None,
        timeout_seconds: float,
    ) -> HttpResponse:
        del method, headers, content
        assert timeout_seconds == 30
        self.calls.append((url, params))
        if url.endswith("/x/web-interface/view"):
            body = VIDEO_UNITS
            content_type = "application/json"
        elif url.endswith("/x/v2/dm/web/seg.so"):
            body = self.danmaku
            content_type = "application/octet-stream"
        elif url.endswith("/x/player/v2"):
            body = SUBTITLE_INDEX if params and params.get("cid") == 5001 else NO_SUBTITLES
            content_type = "application/json"
        elif url == "https://fixtures.example/subtitle/7001.json":
            body = SUBTITLE
            content_type = "application/json"
        else:
            raise AssertionError(f"unexpected URL: {url}")
        return HttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": content_type},
            body=body,
        )


class FakeArtifacts:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str, str, object]] = []

    async def store(
        self,
        content: bytes,
        *,
        artifact_type: str,
        content_type: str,
        compression: str | None = None,
        metadata: object = None,
    ) -> object:
        del compression
        reference = SimpleNamespace(id=len(self.calls) + 1)
        self.calls.append((content, artifact_type, content_type, metadata))
        return reference


class RecordingCancellation:
    def __init__(self) -> None:
        self.checks = 0

    def raise_if_cancelled(self) -> None:
        self.checks += 1


def make_context(
    *, danmaku: bytes = DANMAKU
) -> tuple[AdapterContext, FakeHttp, FakeArtifacts, RecordingCancellation]:
    http = FakeHttp(danmaku=danmaku)
    artifacts = FakeArtifacts()
    cancellation = RecordingCancellation()
    context = cast(
        AdapterContext,
        SimpleNamespace(
            http=http,
            raw_artifacts=artifacts,
            cancellation=cancellation,
        ),
    )
    return context, http, artifacts, cancellation


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _field(number: int, wire_type: int, value: bytes) -> bytes:
    return _varint((number << 3) | wire_type) + value


def _encoded_danmaku_item(index: int) -> bytes:
    content = f"fixture-{index}".encode()
    item = b"".join(
        (
            _field(1, 0, _varint(index + 1)),
            _field(2, 0, _varint(index * 10)),
            _field(6, 2, _varint(8) + b"deadbeef"),
            _field(7, 2, _varint(len(content)) + content),
            _field(8, 0, _varint(1_700_000_000 + index)),
            _field(12, 2, _varint(len(str(index + 1))) + str(index + 1).encode()),
        )
    )
    return _field(1, 2, _varint(len(item)) + item)


def test_danmaku_parser_converts_timestamps_and_preserves_attributes() -> None:
    items = list(iter_danmaku_items(DANMAKU))

    assert len(items) == 2
    assert items[0].platform_item_id == "9001"
    assert items[0].start_ms == 1250
    assert items[0].text == "Synthetic danmaku one"
    assert items[0].published_at is not None
    assert items[0].published_at.isoformat() == "2023-11-14T22:13:20+00:00"
    assert items[0].sender_ref == "deadbeef"
    assert items[0].attributes == {
        "mode": 1,
        "font_size": 25,
        "color": 16777215,
        "weight": 5,
        "action": "",
        "pool": 0,
        "attr": 3,
    }
    first_key = build_timed_text_dedup_key(items[0], TimedTextType.DANMAKU)
    assert first_key == build_timed_text_dedup_key(items[0], TimedTextType.DANMAKU)


def test_subtitle_parser_converts_bounds_language_and_stable_dedup_keys() -> None:
    tracks = parse_subtitle_tracks(SUBTITLE_INDEX)
    items = list(iter_subtitle_items(SUBTITLE))

    assert len(tracks) == 1
    assert tracks[0].track_id == "7001"
    assert tracks[0].language_code == "zh-CN"
    assert tracks[0].language_name == "Chinese"
    assert tracks[0].url == "https://fixtures.example/subtitle/7001.json"
    assert [(item.start_ms, item.end_ms) for item in items] == [(1250, 3500), (4000, 4750)]
    assert items[0].platform_item_id == "cue-1"
    assert items[0].attributes == {"location": 2}
    keys = [build_timed_text_dedup_key(item, TimedTextType.SUBTITLE) for item in items]
    assert keys == [build_timed_text_dedup_key(item, TimedTextType.SUBTITLE) for item in items]
    assert len(set(keys)) == 2


@pytest.mark.asyncio
async def test_fetch_timed_text_streams_all_units_tracks_and_archives_sources() -> None:
    context, http, artifacts, cancellation = make_context()

    batches = [
        batch
        async for batch in BilibiliAdapter().fetch_timed_text(
            context,
            TARGET,
            CrawlStrategy(timed_text_batch_size=1000),
        )
    ]

    assert [batch.stream.platform_unit_id for batch in batches] == ["5001", "5001", "5002"]
    assert [batch.stream.content_type for batch in batches] == [
        TimedTextType.DANMAKU,
        TimedTextType.SUBTITLE,
        TimedTextType.DANMAKU,
    ]
    assert [batch.stream.stream_key for batch in batches] == [
        "danmaku:5001",
        "subtitle:7001",
        "danmaku:5002",
    ]
    assert batches[1].stream.language_code == "zh-CN"
    assert [len(batch.items) for batch in batches] == [2, 2, 2]
    assert [artifact_type for _, artifact_type, _, _ in artifacts.calls] == [
        "timed_text_units",
        "danmaku",
        "subtitle_index",
        "subtitle",
        "danmaku",
        "subtitle_index",
    ]
    assert all(batch.raw_artifacts for batch in batches)
    assert len(http.calls) == 6
    assert cancellation.checks >= 12


@pytest.mark.asyncio
async def test_danmaku_batches_follow_strategy_batch_size() -> None:
    body = b"".join(_encoded_danmaku_item(index) for index in range(2501))
    context, _, _, _ = make_context(danmaku=body)

    batches = [
        batch
        async for batch in BilibiliAdapter().fetch_timed_text(
            context,
            TARGET,
            CrawlStrategy(
                fetch_all_subtitles=False,
                timed_text_batch_size=1000,
            ),
        )
    ]

    assert [len(batch.items) for batch in batches] == [1000, 1000, 501, 1000, 1000, 501]
    assert [batch.stream.platform_unit_id for batch in batches] == ["5001"] * 3 + ["5002"] * 3


@pytest.mark.asyncio
async def test_strategy_switches_skip_disabled_timed_text_sources() -> None:
    context, http, artifacts, _ = make_context()

    batches = [
        batch
        async for batch in BilibiliAdapter().fetch_timed_text(
            context,
            TARGET,
            CrawlStrategy(fetch_all_danmaku=False, fetch_all_subtitles=True),
        )
    ]

    assert [batch.stream.content_type for batch in batches] == [TimedTextType.SUBTITLE]
    assert all("/x/v2/dm/web/seg.so" not in url for url, _ in http.calls)
    assert [artifact_type for _, artifact_type, _, _ in artifacts.calls] == [
        "timed_text_units",
        "subtitle_index",
        "subtitle",
        "subtitle_index",
    ]
