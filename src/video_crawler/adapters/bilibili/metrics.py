from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from video_crawler.adapters.base import AdapterContext
from video_crawler.adapters.bilibili.resolver import PLATFORM_KEY
from video_crawler.domain.errors import UpstreamError
from video_crawler.domain.metrics import MetricResult, MetricStatus, MetricValue
from video_crawler.domain.targets import VideoTarget

_METRICS_URL = "https://api.bilibili.com/x/web-interface/view"
_METRIC_FIELDS = (
    ("standard.views", "view"),
    ("standard.likes", "like"),
    ("standard.favorites", "favorite"),
    ("standard.shares", "share"),
    ("standard.comments", "reply"),
    ("standard.timed_comments", "danmaku"),
    ("bilibili.coins", "coin"),
)


def parse_metrics_response(body: bytes) -> dict[str, MetricValue]:
    try:
        payload: Any = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UpstreamError("invalid Bilibili metrics response") from exc
    if not isinstance(payload, Mapping) or payload.get("code") != 0:
        raise UpstreamError("Bilibili metrics request was rejected")
    data = payload.get("data")
    stat = data.get("stat") if isinstance(data, Mapping) else None
    if not isinstance(stat, Mapping):
        raise UpstreamError("Bilibili metrics response did not contain stat data")

    values: dict[str, MetricValue] = {}
    for metric_key, field_name in _METRIC_FIELDS:
        source_path = f"data.stat.{field_name}"
        if field_name not in stat:
            values[metric_key] = MetricValue(
                value=None,
                status=MetricStatus.NOT_PUBLIC,
                source_path=source_path,
            )
            continue
        raw_value = stat[field_name]
        if isinstance(raw_value, int) and not isinstance(raw_value, bool) and raw_value >= 0:
            values[metric_key] = MetricValue(
                value=raw_value,
                status=MetricStatus.AVAILABLE,
                source_path=source_path,
            )
        else:
            values[metric_key] = MetricValue(
                value=None,
                status=MetricStatus.FETCH_FAILED,
                source_path=source_path,
            )
    return values


async def fetch_bilibili_metrics(
    context: AdapterContext,
    target: VideoTarget,
) -> MetricResult:
    if target.platform != PLATFORM_KEY:
        raise ValueError("Bilibili metrics require a Bilibili video target")
    context.cancellation.raise_if_cancelled()
    response = await context.http.request(
        "GET",
        _METRICS_URL,
        params={"bvid": target.platform_video_id},
        timeout_seconds=30,
    )
    artifact = await context.raw_artifacts.store(
        response.body,
        artifact_type="metrics",
        content_type=_content_type(response.headers),
        metadata={"platform_video_id": target.platform_video_id},
    )
    context.cancellation.raise_if_cancelled()
    if response.status_code != 200:
        raise UpstreamError(f"Bilibili metrics request returned status {response.status_code}")
    return MetricResult(
        values=parse_metrics_response(response.body),
        raw_artifacts=(artifact,),
    )


def _content_type(headers: Mapping[str, str]) -> str:
    for name, value in headers.items():
        if name.lower() == "content-type":
            return value
    return "application/json"
