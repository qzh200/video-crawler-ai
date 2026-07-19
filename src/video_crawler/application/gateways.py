from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from video_crawler.domain.artifacts import RawArtifactRef
from video_crawler.domain.strategy import CrawlStrategy

type MetadataValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class CapturedResponse:
    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class HttpResponse:
    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class BrowserPage(Protocol):
    @property
    def url(self) -> str: ...

    @property
    def html(self) -> str: ...

    async def evaluate(self, script: str, *args: object) -> object: ...

    async def wait_for_selector(self, selector: str, *, timeout_seconds: float) -> None: ...

    async def close(self) -> None: ...


class BrowserGateway(Protocol):
    async def open_page(
        self,
        url: str,
        *,
        timeout_seconds: float,
        capture_network: bool = False,
    ) -> BrowserPage: ...


class NetworkCaptureGateway(Protocol):
    def responses_for(self, page: BrowserPage) -> tuple[CapturedResponse, ...]: ...


class HttpGateway(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str | int | float] | None = None,
        content: bytes | None = None,
        timeout_seconds: float,
    ) -> HttpResponse: ...


class RawArtifactGateway(Protocol):
    async def store(
        self,
        content: bytes,
        *,
        artifact_type: str,
        content_type: str,
        compression: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> RawArtifactRef: ...


class RateLimiter(Protocol):
    async def wait(self, scope: str, strategy: CrawlStrategy) -> None: ...


class CancellationToken(Protocol):
    def raise_if_cancelled(self) -> None: ...


class BoundLogger(Protocol):
    def bind(self, **values: object) -> BoundLogger: ...

    def info(self, event: str, **values: object) -> None: ...

    def warning(self, event: str, **values: object) -> None: ...

    def error(self, event: str, **values: object) -> None: ...


class AuthProfileContext(Protocol):
    @property
    def profile_id(self) -> str: ...

    @property
    def platform(self) -> str: ...

    @property
    def profile_directory(self) -> str: ...
