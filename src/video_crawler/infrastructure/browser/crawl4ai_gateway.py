from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, Self, cast
from uuid import uuid4

from video_crawler.application.gateways import BrowserPage, CapturedResponse
from video_crawler.infrastructure.browser.profiles import resolve_profile_path


class _Crawler(Protocol):
    async def start(self, config: object) -> None: ...

    async def open_page(
        self, url: str, *, timeout_seconds: float, capture_network: bool
    ) -> BrowserPage: ...

    async def close(self) -> None: ...


class Crawl4AIBrowserGateway:
    """Own a short-lived Crawl4AI browser and expose only generic gateway APIs."""

    def __init__(
        self,
        *,
        profile_root: Path,
        profile_directory: str,
        crawler_factory: Callable[[], _Crawler] | None = None,
    ) -> None:
        self.profile_path = resolve_profile_path(profile_root, profile_directory)
        self._crawler_factory = crawler_factory or self._default_crawler_factory
        self._crawler: _Crawler | None = None
        self._current_page: BrowserPage | None = None
        self._responses: dict[int, list[CapturedResponse]] = {}

    @property
    def current_page(self) -> BrowserPage:
        if self._current_page is None:
            raise RuntimeError("no browser page is open")
        return self._current_page

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        await self.close()

    async def open_page(
        self,
        url: str,
        *,
        timeout_seconds: float,
        capture_network: bool = False,
    ) -> BrowserPage:
        if self._crawler is None:
            self._crawler = self._crawler_factory()
            await self._crawler.start(self._browser_config())
        page = await self._crawler.open_page(
            url,
            timeout_seconds=timeout_seconds,
            capture_network=capture_network,
        )
        self._current_page = page
        self._responses.setdefault(id(page), [])
        if capture_network:
            for response in getattr(page, "captured_responses", ()):
                self.record_response(page, response)
        return page

    async def close_page(self, page: BrowserPage) -> None:
        await page.close()
        if self._current_page is page:
            self._current_page = None

    async def close(self) -> None:
        try:
            if self._current_page is not None:
                await self.close_page(self._current_page)
        finally:
            if self._crawler is not None:
                await self._crawler.close()
                self._crawler = None

    def record_response(self, page: BrowserPage, response: Any) -> None:
        headers: Mapping[str, str] = getattr(response, "headers", {})
        self._responses.setdefault(id(page), []).append(
            CapturedResponse(
                url=str(response.url),
                status_code=int(response.status_code),
                headers=dict(headers),
                body=bytes(response.body),
            )
        )

    def responses_for(self, page: BrowserPage) -> tuple[CapturedResponse, ...]:
        return tuple(self._responses.get(id(page), ()))

    def _browser_config(self) -> object:
        return {
            "user_data_dir": str(self.profile_path),
            "use_persistent_context": True,
            "headless": True,
        }

    @staticmethod
    def _default_crawler_factory() -> _Crawler:
        from crawl4ai import (  # type: ignore[import-untyped]
            AsyncWebCrawler,
            BrowserConfig,
            CrawlerRunConfig,
        )

        class DefaultCrawler:
            def __init__(self) -> None:
                self._crawler: Any | None = None

            async def start(self, config: object) -> None:
                values = cast(Mapping[str, object], config)
                self._crawler = AsyncWebCrawler(config=BrowserConfig(**values))
                await self._crawler.start()

            async def open_page(
                self, url: str, *, timeout_seconds: float, capture_network: bool
            ) -> BrowserPage:
                if self._crawler is None:
                    raise RuntimeError("Crawl4AI browser is not started")
                session_id = str(uuid4())
                run_config = CrawlerRunConfig(
                    session_id=session_id,
                    page_timeout=int(timeout_seconds * 1000),
                    capture_network_requests=capture_network,
                )
                result = await self._crawler.arun(url=url, config=run_config)
                return _CrawlResultPage(
                    crawler=self._crawler,
                    run_config_factory=CrawlerRunConfig,
                    result=result,
                    url=url,
                    session_id=session_id,
                )

            async def close(self) -> None:
                if self._crawler is not None:
                    await self._crawler.close()
                    self._crawler = None

        return DefaultCrawler()


class _CrawlResultPage:
    def __init__(
        self,
        *,
        crawler: Any,
        run_config_factory: Callable[..., Any],
        result: Any,
        url: str,
        session_id: str,
    ) -> None:
        self._crawler = crawler
        self._run_config_factory = run_config_factory
        self._result = result
        self._url = url
        self._session_id = session_id
        self._closed = False

    @property
    def url(self) -> str:
        return str(getattr(self._result, "url", self._url))

    @property
    def html(self) -> str:
        return str(getattr(self._result, "html", ""))

    @property
    def captured_responses(self) -> tuple[CapturedResponse, ...]:
        captured: list[CapturedResponse] = []
        for entry in getattr(self._result, "network_requests", None) or ():
            if not isinstance(entry, Mapping):
                continue
            response = entry.get("response")
            values = response if isinstance(response, Mapping) else entry
            url = values.get("url") or entry.get("url")
            if not url:
                continue
            headers = values.get("headers")
            body = values.get("body", b"")
            if isinstance(body, str):
                body = body.encode()
            if not isinstance(body, bytes):
                body = b""
            captured.append(
                CapturedResponse(
                    url=str(url),
                    status_code=int(values.get("status") or values.get("status_code") or 0),
                    headers=dict(headers) if isinstance(headers, Mapping) else {},
                    body=body,
                )
            )
        return tuple(captured)

    async def evaluate(self, script: str, *args: object) -> object:
        js_code = script
        if args:
            serialized_args = json.dumps(args)
            js_code = f"(() => (\n{script}\n)(...{serialized_args}))()"
        result = await self._crawler.arun(
            url=self._url,
            config=self._run_config_factory(
                session_id=self._session_id,
                js_only=True,
                js_code=js_code,
            ),
        )
        return getattr(result, "js_execution_result", None)

    async def wait_for_selector(self, selector: str, *, timeout_seconds: float) -> None:
        self._result = await self._crawler.arun(
            url=self._url,
            config=self._run_config_factory(
                session_id=self._session_id,
                js_only=True,
                wait_for=f"css:{selector}",
                wait_for_timeout=int(timeout_seconds * 1000),
            ),
        )

    async def close(self) -> None:
        if not self._closed:
            await self._crawler.crawler_strategy.kill_session(self._session_id)
            self._closed = True
