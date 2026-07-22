from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from video_crawler.adapters.base import AdapterContext
from video_crawler.adapters.bilibili.matcher import extract_bvid
from video_crawler.adapters.bilibili.resolver import (
    PLATFORM_KEY,
    canonical_video_url,
)
from video_crawler.application.gateways import BrowserPage
from video_crawler.domain.strategy import CrawlStrategy
from video_crawler.domain.targets import DiscoveredTarget, ResolvedTarget, TargetKind

_POPULAR_API_PATH = "/x/web-interface/popular"
_API_HOST = "api.bilibili.com"
_DOM_LINK_SCRIPT = """() => Array.from(
  document.querySelectorAll('a[href*="/video/BV"]'),
  element => element.href
)"""


async def discover_popular_targets(
    context: AdapterContext,
    target: ResolvedTarget,
    strategy: CrawlStrategy,
) -> AsyncIterator[DiscoveredTarget]:
    if target.kind is not TargetKind.VIDEO_LIST or target.platform != PLATFORM_KEY:
        raise ValueError("Bilibili popular discovery requires a Bilibili list target")
    context.cancellation.raise_if_cancelled()
    page = await context.browser.open_page(
        target.canonical_url,
        timeout_seconds=strategy.page_timeout_seconds,
        capture_network=True,
    )
    try:
        candidates = _captured_candidates(context, page)
        if candidates is None:
            candidates = _dom_candidates(await page.evaluate(_DOM_LINK_SCRIPT))
        seen: set[str] = set()
        position = 0
        for bvid in candidates:
            if bvid in seen:
                continue
            context.cancellation.raise_if_cancelled()
            seen.add(bvid)
            yield DiscoveredTarget(
                platform=PLATFORM_KEY,
                platform_video_id=bvid,
                canonical_url=canonical_video_url(bvid),
                position=position,
                platform_ids={"bvid": bvid},
            )
            position += 1
            if position >= strategy.video_limit:
                break
    finally:
        await page.close()


def _captured_candidates(context: AdapterContext, page: BrowserPage) -> list[str] | None:
    for response in context.network_capture.responses_for(page):
        parsed_url = urlsplit(response.url)
        if (
            response.status_code != 200
            or parsed_url.scheme != "https"
            or parsed_url.hostname != _API_HOST
            or parsed_url.path != _POPULAR_API_PATH
        ):
            continue
        parsed = _parse_popular_response(response.body)
        if parsed is not None:
            return parsed
    return None


def _parse_popular_response(body: bytes) -> list[str] | None:
    try:
        payload: Any = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, Mapping) or payload.get("code") != 0:
        return None
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return None
    entries = data.get("list")
    if not isinstance(entries, Sequence) or isinstance(entries, str | bytes):
        return None
    candidates: list[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        bvid = entry.get("bvid")
        if isinstance(bvid, str) and extract_bvid(canonical_video_url(bvid)) == bvid:
            candidates.append(bvid)
    return candidates


def _dom_candidates(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    candidates: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        absolute_url = f"https://www.bilibili.com{item}" if item.startswith("/") else item
        bvid = extract_bvid(absolute_url)
        if bvid is not None:
            candidates.append(bvid)
    return candidates
