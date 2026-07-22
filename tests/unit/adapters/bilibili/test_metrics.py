from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from video_crawler.adapters.base import AdapterContext
from video_crawler.adapters.bilibili import BilibiliAdapter
from video_crawler.adapters.bilibili.metrics import parse_metrics_response
from video_crawler.application.gateways import HttpResponse
from video_crawler.domain.errors import UpstreamError
from video_crawler.domain.metrics import MetricStatus
from video_crawler.domain.targets import VideoTarget

FIXTURE = Path(__file__).parents[3] / "fixtures" / "bilibili" / "metrics.json"
TARGET = VideoTarget(
    platform="bilibili",
    platform_video_id="BV1FAKE00001",
    canonical_url="https://www.bilibili.com/video/BV1FAKE00001",
    platform_ids={"bvid": "BV1FAKE00001"},
)
EXPECTED_VALUES = {
    "standard.views": 123456,
    "standard.likes": 2345,
    "standard.favorites": 456,
    "standard.shares": 67,
    "standard.comments": 89,
    "standard.timed_comments": 1012,
    "bilibili.coins": 345,
}
EXPECTED_PATHS = {
    "standard.views": "data.stat.view",
    "standard.likes": "data.stat.like",
    "standard.favorites": "data.stat.favorite",
    "standard.shares": "data.stat.share",
    "standard.comments": "data.stat.reply",
    "standard.timed_comments": "data.stat.danmaku",
    "bilibili.coins": "data.stat.coin",
}


class FakeHttp:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str, object, float]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: object = None,
        params: object = None,
        content: bytes | None = None,
        timeout_seconds: float,
    ) -> HttpResponse:
        del headers, content
        self.calls.append((method, url, params, timeout_seconds))
        return self.response


class FakeArtifacts:
    def __init__(self) -> None:
        self.reference = SimpleNamespace(id=17)
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
        self.calls.append((content, artifact_type, content_type, metadata))
        return self.reference


class RecordingCancellation:
    def __init__(self) -> None:
        self.checks = 0

    def raise_if_cancelled(self) -> None:
        self.checks += 1


def make_context(
    response: HttpResponse,
) -> tuple[AdapterContext, FakeHttp, FakeArtifacts, RecordingCancellation]:
    http = FakeHttp(response)
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


def response(body: bytes, *, status_code: int = 200) -> HttpResponse:
    return HttpResponse(
        url="https://api.bilibili.com/x/web-interface/view?bvid=BV1FAKE00001",
        status_code=status_code,
        headers={"content-type": "application/json; charset=utf-8"},
        body=body,
    )


def test_parser_maps_all_approved_metrics_with_source_paths() -> None:
    result = parse_metrics_response(FIXTURE.read_bytes())

    assert set(result) == set(EXPECTED_VALUES)
    for key, expected in EXPECTED_VALUES.items():
        metric = result[key]
        assert metric.value == expected
        assert metric.status is MetricStatus.AVAILABLE
        assert metric.source_path == EXPECTED_PATHS[key]


def test_parser_distinguishes_missing_and_invalid_values_from_zero() -> None:
    result = parse_metrics_response(b'{"code":0,"data":{"stat":{"view":0,"like":"hidden"}}}')

    assert result["standard.views"].value == 0
    assert result["standard.views"].status is MetricStatus.AVAILABLE
    assert result["standard.likes"].value is None
    assert result["standard.likes"].status is MetricStatus.FETCH_FAILED
    assert result["standard.favorites"].value is None
    assert result["standard.favorites"].status is MetricStatus.NOT_PUBLIC


@pytest.mark.asyncio
async def test_fetch_metrics_uses_gateway_and_archives_raw_response() -> None:
    raw = FIXTURE.read_bytes()
    context, http, artifacts, cancellation = make_context(response(raw))

    result = await BilibiliAdapter().fetch_metrics(context, TARGET)

    assert result.values["standard.views"].value == 123456
    assert result.raw_artifacts == (artifacts.reference,)
    assert http.calls == [
        (
            "GET",
            "https://api.bilibili.com/x/web-interface/view",
            {"bvid": "BV1FAKE00001"},
            30,
        )
    ]
    assert artifacts.calls == [
        (
            raw,
            "metrics",
            "application/json; charset=utf-8",
            {"platform_video_id": "BV1FAKE00001"},
        )
    ]
    assert cancellation.checks == 2


@pytest.mark.asyncio
async def test_fetch_metrics_archives_rejected_response_before_raising() -> None:
    raw = b'{"code":-404,"message":"not found"}'
    context, _, artifacts, _ = make_context(response(raw, status_code=404))

    with pytest.raises(UpstreamError, match="status 404"):
        await BilibiliAdapter().fetch_metrics(context, TARGET)

    assert artifacts.calls[0][0] == raw
