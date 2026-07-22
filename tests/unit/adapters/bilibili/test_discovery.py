from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from video_crawler.adapters.base import AdapterContext
from video_crawler.adapters.bilibili import BilibiliAdapter
from video_crawler.application.gateways import CapturedResponse
from video_crawler.domain.strategy import CrawlStrategy
from video_crawler.domain.targets import TargetKind

POPULAR_URL = "https://www.bilibili.com/v/popular/all"
VIDEO_URL = "https://www.bilibili.com/video/BV1FAKE00001"
FIXTURE = Path(__file__).parents[3] / "fixtures" / "bilibili" / "popular_page.json"


class FakePage:
    def __init__(self, *, url: str, evaluated: object = None) -> None:
        self.url = url
        self.html = ""
        self.evaluated = evaluated
        self.closed = False

    async def evaluate(self, script: str, *args: object) -> object:
        del script, args
        return self.evaluated

    async def wait_for_selector(self, selector: str, *, timeout_seconds: float) -> None:
        del selector, timeout_seconds

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.calls: list[tuple[str, float, bool]] = []

    async def open_page(
        self,
        url: str,
        *,
        timeout_seconds: float,
        capture_network: bool = False,
    ) -> FakePage:
        self.calls.append((url, timeout_seconds, capture_network))
        return self.page


class FakeNetworkCapture:
    def __init__(self, *responses: CapturedResponse) -> None:
        self.responses = responses

    def responses_for(self, page: FakePage) -> tuple[CapturedResponse, ...]:
        del page
        return self.responses


class RecordingCancellation:
    def __init__(self) -> None:
        self.checks = 0

    def raise_if_cancelled(self) -> None:
        self.checks += 1


def make_context(
    page: FakePage,
    *responses: CapturedResponse,
) -> tuple[AdapterContext, FakeBrowser, RecordingCancellation]:
    browser = FakeBrowser(page)
    cancellation = RecordingCancellation()
    context = cast(
        AdapterContext,
        SimpleNamespace(
            browser=browser,
            network_capture=FakeNetworkCapture(*responses),
            cancellation=cancellation,
        ),
    )
    return context, browser, cancellation


def captured_json(
    path: str,
    body: bytes,
    *,
    host: str = "api.bilibili.com",
) -> CapturedResponse:
    return CapturedResponse(
        url=f"https://{host}{path}",
        status_code=200,
        headers={"content-type": "application/json"},
        body=body,
    )


def test_matcher_accepts_approved_urls_and_rejects_lookalike_domains() -> None:
    adapter = BilibiliAdapter()

    assert adapter.match(POPULAR_URL)
    assert adapter.match(f"{VIDEO_URL}?spm_id_from=fixture")
    assert not adapter.match("https://www.bilibili.com.evil.test/v/popular/all")
    assert not adapter.match("https://example.test/video/BV1FAKE00001")
    assert not adapter.match("https://www.bilibili.com/read/cv1")


@pytest.mark.asyncio
async def test_resolver_returns_generic_list_and_video_targets() -> None:
    adapter = BilibiliAdapter()
    context = cast(AdapterContext, SimpleNamespace())

    popular = await adapter.resolve_target(context, f"{POPULAR_URL}/?from=fixture")
    video = await adapter.resolve_target(context, f"{VIDEO_URL}/?from=fixture")

    assert popular.kind is TargetKind.VIDEO_LIST
    assert popular.canonical_url == POPULAR_URL
    assert popular.platform_video_id is None
    assert popular.platform_ids == {}
    assert video.kind is TargetKind.SINGLE_VIDEO
    assert video.canonical_url == VIDEO_URL
    assert video.platform_video_id == "BV1FAKE00001"
    assert video.platform_ids == {"bvid": "BV1FAKE00001"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("is_login", "expected"), [(True, True), (False, False)])
async def test_auth_uses_captured_navigation_json(is_login: bool, expected: bool) -> None:
    body = (
        b'{"code":0,"data":{"isLogin":true}}'
        if is_login
        else b'{"code":0,"data":{"isLogin":false}}'
    )
    page = FakePage(url="https://www.bilibili.com/")
    context, browser, _ = make_context(
        page,
        captured_json("/x/web-interface/nav", body),
    )

    result = await BilibiliAdapter().verify_auth(context)

    assert result.is_valid is expected
    assert result.reason == (None if expected else "not_authenticated")
    assert result.extra == {}
    assert browser.calls == [("https://www.bilibili.com/", 30, True)]
    assert page.closed


@pytest.mark.asyncio
async def test_auth_falls_back_to_explicit_dom_markers() -> None:
    page = FakePage(
        url="https://www.bilibili.com/",
        evaluated={"hasAvatar": True, "hasLoginEntry": False},
    )
    context, _, _ = make_context(page)

    result = await BilibiliAdapter().verify_auth(context)

    assert result.is_valid
    assert result.reason is None
    assert page.closed


@pytest.mark.asyncio
async def test_auth_ignores_navigation_json_from_lookalike_domain() -> None:
    page = FakePage(
        url="https://www.bilibili.com/",
        evaluated={"hasAvatar": False, "hasLoginEntry": True},
    )
    context, _, _ = make_context(
        page,
        captured_json(
            "/x/web-interface/nav",
            b'{"code":0,"data":{"isLogin":true}}',
            host="api.bilibili.com.evil.test",
        ),
    )

    result = await BilibiliAdapter().verify_auth(context)

    assert not result.is_valid
    assert result.reason == "not_authenticated"


@pytest.mark.asyncio
async def test_discovery_preserves_order_removes_duplicates_and_enforces_limit() -> None:
    page = FakePage(url=POPULAR_URL)
    context, browser, cancellation = make_context(
        page,
        captured_json("/x/web-interface/popular?pn=1&ps=20", FIXTURE.read_bytes()),
    )
    adapter = BilibiliAdapter()
    target = await adapter.resolve_target(context, POPULAR_URL)

    discovered = [
        item
        async for item in adapter.discover_targets(
            context,
            target,
            CrawlStrategy(video_limit=3),
        )
    ]

    assert [item.platform_video_id for item in discovered] == [
        "BV1FAKE00001",
        "BV1FAKE00002",
        "BV1FAKE00003",
    ]
    assert [item.position for item in discovered] == [0, 1, 2]
    assert [item.canonical_url for item in discovered] == [
        "https://www.bilibili.com/video/BV1FAKE00001",
        "https://www.bilibili.com/video/BV1FAKE00002",
        "https://www.bilibili.com/video/BV1FAKE00003",
    ]
    assert all(item.platform == "bilibili" for item in discovered)
    assert cancellation.checks == 4
    assert browser.calls == [(POPULAR_URL, 60, True)]
    assert page.closed


@pytest.mark.asyncio
async def test_discovery_falls_back_to_dom_links() -> None:
    page = FakePage(
        url=POPULAR_URL,
        evaluated=[
            "/video/BV1FAKE00003",
            "https://www.bilibili.com/video/BV1FAKE00002?from=fixture",
        ],
    )
    context, _, _ = make_context(page)
    adapter = BilibiliAdapter()
    target = await adapter.resolve_target(context, POPULAR_URL)

    discovered = [
        item
        async for item in adapter.discover_targets(
            context,
            target,
            CrawlStrategy(video_limit=2),
        )
    ]

    assert [item.platform_video_id for item in discovered] == [
        "BV1FAKE00003",
        "BV1FAKE00002",
    ]
    assert page.closed


@pytest.mark.asyncio
async def test_discovery_ignores_popular_json_from_lookalike_domain() -> None:
    page = FakePage(url=POPULAR_URL, evaluated=["/video/BV1FAKE00003"])
    context, _, _ = make_context(
        page,
        captured_json(
            "/x/web-interface/popular",
            FIXTURE.read_bytes(),
            host="api.bilibili.com.evil.test",
        ),
    )
    adapter = BilibiliAdapter()
    target = await adapter.resolve_target(context, POPULAR_URL)

    discovered = [
        item
        async for item in adapter.discover_targets(
            context,
            target,
            CrawlStrategy(video_limit=3),
        )
    ]

    assert [item.platform_video_id for item in discovered] == ["BV1FAKE00003"]
