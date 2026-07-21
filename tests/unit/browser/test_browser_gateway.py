from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from video_crawler.application.gateways import CapturedResponse
from video_crawler.infrastructure.browser.crawl4ai_gateway import (
    Crawl4AIBrowserGateway,
    _CrawlResultPage,
)


class FakePage:
    url = "https://example.test/page"
    html = "<html />"
    captured_responses: tuple[CapturedResponse, ...] = ()

    async def evaluate(self, script: str, *args: object) -> object:
        return {"script": script, "args": args}

    async def wait_for_selector(self, selector: str, *, timeout_seconds: float) -> None:
        self.selector = selector
        self.timeout_seconds = timeout_seconds

    async def close(self) -> None:
        self.closed = True


class FakeCrawler:
    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.config: object | None = None
        self.page = FakePage()

    async def start(self, config: object) -> None:
        self.started = True
        self.config = config

    async def open_page(
        self, url: str, *, timeout_seconds: float, capture_network: bool
    ) -> FakePage:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.capture_network = capture_network
        return self.page

    async def close(self) -> None:
        self.closed = True


class FakeRunConfig:
    def __init__(self, **values: object) -> None:
        self.values = values


class FakeSessionCrawler:
    def __init__(self) -> None:
        self.configs: list[FakeRunConfig] = []
        self.crawler_strategy = SimpleNamespace(kill_session=self.kill_session)
        self.killed_session: str | None = None

    async def arun(self, *, url: str, config: FakeRunConfig) -> object:
        self.url = url
        self.configs.append(config)
        return SimpleNamespace(js_execution_result={"value": 7})

    async def kill_session(self, session_id: str) -> None:
        self.killed_session = session_id


@pytest.mark.asyncio
async def test_browser_gateway_applies_profile_and_page_timeout(tmp_path: Path) -> None:
    crawler = FakeCrawler()
    gateway = Crawl4AIBrowserGateway(
        profile_root=tmp_path,
        profile_directory="profile-1",
        crawler_factory=lambda: crawler,
    )

    page = await gateway.open_page(
        "https://example.test/page",
        timeout_seconds=12.5,
        capture_network=False,
    )

    assert page.url == "https://example.test/page"
    assert crawler.started is True
    assert crawler.url == "https://example.test/page"
    assert crawler.timeout_seconds == 12.5
    assert crawler.capture_network is False
    assert gateway.profile_path.name == "profile-1"
    assert "profile-1" in repr(crawler.config)


@pytest.mark.asyncio
async def test_browser_gateway_exposes_optional_network_capture(tmp_path: Path) -> None:
    crawler = FakeCrawler()
    crawler.page.captured_responses = (
        CapturedResponse(
            url="https://example.test/api",
            status_code=200,
            headers={"x": "y"},
            body=b"{}",
        ),
    )
    gateway = Crawl4AIBrowserGateway(
        profile_root=tmp_path,
        profile_directory="profile-1",
        crawler_factory=lambda: crawler,
    )

    await gateway.open_page("https://example.test/page", timeout_seconds=5, capture_network=True)

    captured = gateway.responses_for(gateway.current_page)
    assert captured[0].url == "https://example.test/api"
    assert captured[0].body == b"{}"


@pytest.mark.asyncio
async def test_browser_gateway_closes_page_and_crawler(tmp_path: Path) -> None:
    crawler = FakeCrawler()
    gateway = Crawl4AIBrowserGateway(
        profile_root=tmp_path,
        profile_directory="profile-1",
        crawler_factory=lambda: crawler,
    )

    page = await gateway.open_page("https://example.test/page", timeout_seconds=5)
    await gateway.close_page(page)
    await gateway.close()

    assert crawler.page.closed is True
    assert crawler.closed is True


@pytest.mark.asyncio
async def test_crawl_result_page_reuses_session_for_interaction() -> None:
    crawler = FakeSessionCrawler()
    page = _CrawlResultPage(
        crawler=crawler,
        run_config_factory=FakeRunConfig,
        result=SimpleNamespace(html="<html />"),
        url="https://example.test/page",
        session_id="session-1",
    )

    evaluated = await page.evaluate("() => 7")
    await page.wait_for_selector("#ready", timeout_seconds=4.5)
    await page.close()

    assert evaluated == {"value": 7}
    assert crawler.configs[0].values["session_id"] == "session-1"
    assert crawler.configs[0].values["js_only"] is True
    assert crawler.configs[1].values["wait_for"] == "css:#ready"
    assert crawler.configs[1].values["wait_for_timeout"] == 4500
    assert crawler.killed_session == "session-1"
