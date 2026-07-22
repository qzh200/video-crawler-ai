from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from video_crawler.adapters.base import AdapterContext
from video_crawler.adapters.bilibili import BilibiliAdapter
from video_crawler.adapters.bilibili.parsers.comments import (
    parse_reply_page,
    parse_root_page,
)
from video_crawler.application.gateways import HttpResponse
from video_crawler.domain.strategy import CrawlStrategy
from video_crawler.domain.targets import VideoTarget

FIXTURES = Path(__file__).parents[3] / "fixtures" / "bilibili"
ROOT_PAGE_ONE = (FIXTURES / "comments_root.json").read_bytes()
REPLY_PAGE_ONE = (FIXTURES / "comments_replies.json").read_bytes()
ROOT_PAGE_TWO = json.dumps(
    {
        "code": 0,
        "data": {
            "cursor": {"is_end": True, "next": 0},
            "replies": [
                {
                    "rpid": 1003,
                    "root": 0,
                    "parent": 0,
                    "member": {"mid": "9003", "uname": "FixtureRootThree"},
                    "content": {"message": "Synthetic root comment three"},
                    "like": 0,
                    "rcount": 0,
                    "ctime": 1700000400,
                    "state": 0,
                }
            ],
        },
    }
).encode()
REPLY_PAGE_TWO = json.dumps(
    {
        "code": 0,
        "data": {
            "page": {"num": 2, "size": 2, "count": 3},
            "replies": [
                {
                    "rpid": 2003,
                    "root": 1001,
                    "parent": 1001,
                    "member": {"mid": "9103", "uname": "FixtureReplyThree"},
                    "content": {"message": "Synthetic final reply"},
                    "like": 0,
                    "rcount": 0,
                    "ctime": 1700000500,
                    "state": 0,
                }
            ],
        },
    }
).encode()
IDENTITY_RESPONSE = b'{"code":0,"data":{"aid":7001}}'
TARGET = VideoTarget(
    platform="bilibili",
    platform_video_id="BV1FAKE00001",
    canonical_url="https://www.bilibili.com/video/BV1FAKE00001",
    platform_ids={"bvid": "BV1FAKE00001", "aid": 7001},
)


class FakeHttp:
    def __init__(self, bodies: list[bytes]) -> None:
        self.bodies = list(bodies)
        self.calls: list[tuple[str, str, Mapping[str, str | int | float] | None]] = []

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
        del headers, content
        assert timeout_seconds == 30
        self.calls.append((method, url, params))
        body = self.bodies.pop(0)
        return HttpResponse(
            url=url,
            status_code=200,
            headers={"content-type": "application/json"},
            body=body,
        )


class FakeArtifacts:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str, object]] = []

    async def store(
        self,
        content: bytes,
        *,
        artifact_type: str,
        content_type: str,
        compression: str | None = None,
        metadata: object = None,
    ) -> object:
        del content_type, compression
        self.calls.append((content, artifact_type, metadata))
        return SimpleNamespace(id=len(self.calls))


class FakeLimiter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, CrawlStrategy]] = []

    async def wait(self, scope: str, strategy: CrawlStrategy) -> None:
        self.calls.append((scope, strategy))


class RecordingCancellation:
    def __init__(self) -> None:
        self.checks = 0

    def raise_if_cancelled(self) -> None:
        self.checks += 1


def make_context(
    bodies: list[bytes],
) -> tuple[AdapterContext, FakeHttp, FakeArtifacts, FakeLimiter, RecordingCancellation]:
    http = FakeHttp(bodies)
    artifacts = FakeArtifacts()
    limiter = FakeLimiter()
    cancellation = RecordingCancellation()
    context = cast(
        AdapterContext,
        SimpleNamespace(
            http=http,
            raw_artifacts=artifacts,
            rate_limiter=limiter,
            cancellation=cancellation,
        ),
    )
    return context, http, artifacts, limiter, cancellation


def test_parsers_preserve_root_and_parent_platform_ids() -> None:
    roots = parse_root_page(ROOT_PAGE_ONE)
    replies = parse_reply_page(REPLY_PAGE_ONE, root_platform_comment_id="1001")

    assert [item.platform_comment_id for item in roots.items] == ["1001", "1002"]
    assert all(item.root_platform_comment_id is None for item in roots.items)
    assert all(item.parent_platform_comment_id is None for item in roots.items)
    assert roots.items[0].author_platform_id == "9001"
    assert roots.items[0].author_name == "FixtureRootOne"
    assert roots.items[0].published_at is not None
    assert roots.items[0].published_at.isoformat() == "2023-11-14T22:13:20+00:00"
    assert roots.next_cursor == "2"
    assert roots.has_more

    assert [item.platform_comment_id for item in replies.items] == ["2001", "2002"]
    assert [item.root_platform_comment_id for item in replies.items] == ["1001", "1001"]
    assert [item.parent_platform_comment_id for item in replies.items] == ["1001", "2001"]
    assert replies.next_cursor == "2"
    assert replies.has_more


@pytest.mark.asyncio
async def test_zero_root_limit_streams_all_roots_and_all_replies() -> None:
    context, http, artifacts, limiter, cancellation = make_context(
        [ROOT_PAGE_ONE, REPLY_PAGE_ONE, REPLY_PAGE_TWO, ROOT_PAGE_TWO]
    )
    strategy = CrawlStrategy(max_root_comments=0, fetch_all_replies=True)

    batches = [batch async for batch in BilibiliAdapter().fetch_comments(context, TARGET, strategy)]
    items = [item for batch in batches for item in batch.items]

    assert [item.platform_comment_id for item in items] == [
        "1001",
        "1002",
        "2001",
        "2002",
        "2003",
        "1003",
    ]
    assert len(http.calls) == 4
    assert len(artifacts.calls) == 4
    assert [artifact_type for _, artifact_type, _ in artifacts.calls] == [
        "comments_root",
        "comments_replies",
        "comments_replies",
        "comments_root",
    ]
    assert [scope for scope, _ in limiter.calls] == ["comment_page"] * 3
    assert cancellation.checks >= 8


@pytest.mark.asyncio
async def test_root_limit_truncates_roots_but_keeps_selected_root_replies_complete() -> None:
    context, http, _, limiter, _ = make_context([ROOT_PAGE_ONE, REPLY_PAGE_ONE, REPLY_PAGE_TWO])
    strategy = CrawlStrategy(max_root_comments=1, fetch_all_replies=True)

    batches = [batch async for batch in BilibiliAdapter().fetch_comments(context, TARGET, strategy)]
    items = [item for batch in batches for item in batch.items]

    assert [item.platform_comment_id for item in items] == ["1001", "2001", "2002", "2003"]
    assert [item.root_platform_comment_id for item in items[1:]] == ["1001"] * 3
    assert len(http.calls) == 3
    assert len(limiter.calls) == 2


@pytest.mark.asyncio
async def test_fetch_all_replies_false_requests_only_root_pages() -> None:
    context, http, _, limiter, _ = make_context([ROOT_PAGE_ONE, ROOT_PAGE_TWO])
    strategy = CrawlStrategy(max_root_comments=0, fetch_all_replies=False)

    batches = [batch async for batch in BilibiliAdapter().fetch_comments(context, TARGET, strategy)]
    items = [item for batch in batches for item in batch.items]

    assert [item.platform_comment_id for item in items] == ["1001", "1002", "1003"]
    assert all("/reply/reply" not in url for _, url, _ in http.calls)
    assert len(limiter.calls) == 1


@pytest.mark.asyncio
async def test_missing_aid_is_resolved_and_archived_through_injected_gateways() -> None:
    target = VideoTarget(
        platform="bilibili",
        platform_video_id="BV1FAKE00001",
        canonical_url="https://www.bilibili.com/video/BV1FAKE00001",
        platform_ids={"bvid": "BV1FAKE00001"},
    )
    context, http, artifacts, limiter, _ = make_context([IDENTITY_RESPONSE, ROOT_PAGE_TWO])

    batches = [
        batch
        async for batch in BilibiliAdapter().fetch_comments(
            context,
            target,
            CrawlStrategy(max_root_comments=0, fetch_all_replies=False),
        )
    ]

    assert [item.platform_comment_id for batch in batches for item in batch.items] == ["1003"]
    assert http.calls[0][1] == "https://api.bilibili.com/x/web-interface/view"
    assert [artifact_type for _, artifact_type, _ in artifacts.calls] == [
        "comments_identity",
        "comments_root",
    ]
    assert len(limiter.calls) == 1
