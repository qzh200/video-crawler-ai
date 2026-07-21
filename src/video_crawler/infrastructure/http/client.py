from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from video_crawler.application.gateways import BoundLogger, HttpResponse, RateLimiter
from video_crawler.domain.strategy import CrawlStrategy

_RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


def should_retry(*, status_code: int | None, error: BaseException | None) -> bool:
    if status_code is not None:
        return status_code in _RETRYABLE_STATUSES
    return isinstance(
        error,
        (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError),
    )


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_retries: int = 3
    base_delay_seconds: float = 0.25

    @property
    def attempts(self) -> int:
        return self.max_retries + 1


class HttpxGateway:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        retry_policy: RetryPolicy | None = None,
        rate_limiter: RateLimiter | None = None,
        strategy: CrawlStrategy | None = None,
        logger: BoundLogger | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self.retry_policy = retry_policy or RetryPolicy()
        self.rate_limiter = rate_limiter
        self.strategy = strategy or CrawlStrategy()
        self.logger = logger

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
        if self.rate_limiter is not None:
            await self.rate_limiter.wait("request", self.strategy)
        for attempt in range(self.retry_policy.attempts):
            try:
                response = await self._client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    content=content,
                    timeout=timeout_seconds,
                )
                self._log_response(method, url, response.status_code)
                if (
                    not should_retry(status_code=response.status_code, error=None)
                    or attempt == self.retry_policy.max_retries
                ):
                    return HttpResponse(
                        url=str(response.url),
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        body=response.content,
                    )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                if attempt == self.retry_policy.max_retries or not should_retry(
                    status_code=None, error=exc
                ):
                    raise
            await asyncio.sleep(self.retry_policy.base_delay_seconds * (2**attempt))
        raise RuntimeError("unreachable retry loop")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _log_response(self, method: str, url: str, status_code: int) -> None:
        if self.logger is None:
            return
        parsed = urlsplit(url)
        self.logger.info(
            "http_request",
            method=method,
            host=parsed.netloc,
            path=parsed.path,
            status_code=status_code,
        )
