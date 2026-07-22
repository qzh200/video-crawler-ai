from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Protocol

from video_crawler.adapters.base import AdapterContext
from video_crawler.adapters.bilibili.parsers.comments import (
    parse_reply_page,
    parse_root_page,
)
from video_crawler.adapters.bilibili.resolver import PLATFORM_KEY
from video_crawler.application.gateways import HttpResponse, MetadataValue
from video_crawler.domain.artifacts import RawArtifactRef
from video_crawler.domain.comments import CommentBatch, NormalizedComment
from video_crawler.domain.errors import UpstreamError
from video_crawler.domain.strategy import CrawlStrategy
from video_crawler.domain.targets import VideoTarget

_ROOT_COMMENTS_URL = "https://api.bilibili.com/x/v2/reply/main"
_REPLIES_URL = "https://api.bilibili.com/x/v2/reply/reply"
_PAGE_SIZE = 20


class _PageFetcher(Protocol):
    async def __call__(
        self,
        url: str,
        params: Mapping[str, str | int | float],
        *,
        artifact_type: str,
        metadata: Mapping[str, MetadataValue],
    ) -> tuple[HttpResponse, RawArtifactRef]: ...


async def fetch_bilibili_comments(
    context: AdapterContext,
    target: VideoTarget,
    strategy: CrawlStrategy,
) -> AsyncIterator[CommentBatch]:
    if target.platform != PLATFORM_KEY:
        raise ValueError("Bilibili comments require a Bilibili video target")
    aid = _target_aid(target)
    request_count = 0

    async def fetch_page(
        url: str,
        params: Mapping[str, str | int | float],
        *,
        artifact_type: str,
        metadata: Mapping[str, MetadataValue],
    ) -> tuple[HttpResponse, RawArtifactRef]:
        nonlocal request_count
        if request_count:
            await context.rate_limiter.wait("comment_page", strategy)
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
        request_count += 1
        context.cancellation.raise_if_cancelled()
        if response.status_code != 200:
            raise UpstreamError(f"Bilibili comments request returned status {response.status_code}")
        return response, artifact

    root_cursor: str | None = None
    selected_roots = 0
    while True:
        response, artifact = await fetch_page(
            _ROOT_COMMENTS_URL,
            {
                "type": 1,
                "oid": aid,
                "next": int(root_cursor) if root_cursor is not None else 0,
                "mode": 3,
                "ps": _PAGE_SIZE,
            },
            artifact_type="comments_root",
            metadata={
                "platform_video_id": target.platform_video_id,
                "cursor": root_cursor or "0",
            },
        )
        page = parse_root_page(response.body)
        roots = _select_roots(page.items, selected_roots, strategy.max_root_comments)
        selected_roots += len(roots)
        limit_reached = (
            strategy.max_root_comments > 0 and selected_roots >= strategy.max_root_comments
        )
        context.cancellation.raise_if_cancelled()
        if roots:
            yield CommentBatch(
                items=roots,
                cursor=None if limit_reached else page.next_cursor,
                has_more=page.has_more and not limit_reached,
                raw_artifacts=(artifact,),
            )

        if strategy.fetch_all_replies:
            for root in roots:
                if root.reply_count == 0:
                    continue
                async for reply_batch in _fetch_replies(
                    context,
                    target,
                    strategy,
                    aid,
                    root.platform_comment_id,
                    fetch_page,
                ):
                    yield reply_batch

        if limit_reached or not page.has_more or page.next_cursor is None:
            break
        root_cursor = page.next_cursor


async def _fetch_replies(
    context: AdapterContext,
    target: VideoTarget,
    strategy: CrawlStrategy,
    aid: int,
    root_id: str,
    fetch_page: _PageFetcher,
) -> AsyncIterator[CommentBatch]:
    page_number = 1
    while True:
        response, artifact = await fetch_page(
            _REPLIES_URL,
            {
                "type": 1,
                "oid": aid,
                "root": int(root_id),
                "pn": page_number,
                "ps": _PAGE_SIZE,
            },
            artifact_type="comments_replies",
            metadata={
                "platform_video_id": target.platform_video_id,
                "root_platform_comment_id": root_id,
                "page": page_number,
            },
        )
        page = parse_reply_page(response.body, root_platform_comment_id=root_id)
        context.cancellation.raise_if_cancelled()
        yield CommentBatch(
            items=page.items,
            cursor=page.next_cursor,
            has_more=page.has_more,
            raw_artifacts=(artifact,),
        )
        if not page.has_more or page.next_cursor is None:
            break
        page_number = int(page.next_cursor)


def _select_roots(
    roots: tuple[NormalizedComment, ...],
    selected: int,
    limit: int,
) -> tuple[NormalizedComment, ...]:
    if limit == 0:
        return roots
    remaining = max(limit - selected, 0)
    return roots[:remaining]


def _target_aid(target: VideoTarget) -> int:
    aid = target.platform_ids.get("aid")
    if isinstance(aid, int) and not isinstance(aid, bool) and aid > 0:
        return aid
    if isinstance(aid, str) and aid.isdigit() and int(aid) > 0:
        return int(aid)
    raise ValueError("Bilibili comments require platform_ids['aid']")


def _content_type(headers: Mapping[str, str]) -> str:
    for name, value in headers.items():
        if name.lower() == "content-type":
            return value
    return "application/json"
