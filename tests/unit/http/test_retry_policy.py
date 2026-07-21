from __future__ import annotations

import httpx
import pytest
import respx

from video_crawler.application.rate_limit import RateLimiter as ApplicationRateLimiter
from video_crawler.domain.strategy import CrawlStrategy
from video_crawler.infrastructure.http.client import HttpxGateway, RetryPolicy, should_retry


class RecordingLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def info(self, event: str, **values: object) -> None:
        self.events.append({"event": event, **values})


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_retry_policy_retries_transient_statuses(status: int) -> None:
    assert should_retry(status_code=status, error=None) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_retry_policy_does_not_retry_permanent_statuses(status: int) -> None:
    assert should_retry(status_code=status, error=None) is False


def test_retry_policy_retries_transport_errors() -> None:
    assert should_retry(status_code=None, error=httpx.ConnectTimeout("timeout")) is True


def test_retry_policy_does_not_retry_authentication_errors() -> None:
    error = httpx.HTTPStatusError("expired", request=None, response=None)
    assert should_retry(status_code=401, error=error) is False


def test_retry_policy_respects_max_retries() -> None:
    policy = RetryPolicy(max_retries=2)
    assert policy.attempts == 3


@pytest.mark.asyncio
@respx.mock
async def test_http_gateway_retries_transient_response() -> None:
    route = respx.get("https://example.test/data").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, content=b"ok")]
    )
    gateway = HttpxGateway(
        client=httpx.AsyncClient(),
        retry_policy=RetryPolicy(max_retries=1, base_delay_seconds=0),
    )

    response = await gateway.request("GET", "https://example.test/data", timeout_seconds=5)

    assert route.call_count == 2
    assert response.status_code == 200
    assert response.body == b"ok"


@pytest.mark.asyncio
@respx.mock
async def test_http_gateway_does_not_log_sensitive_headers() -> None:
    respx.get("https://example.test/private").mock(return_value=httpx.Response(200))
    logger = RecordingLogger()
    gateway = HttpxGateway(client=httpx.AsyncClient(), logger=logger)  # type: ignore[arg-type]

    await gateway.request(
        "GET",
        "https://example.test/private?token=secret",
        headers={"Authorization": "Bearer secret", "Cookie": "session=secret"},
        timeout_seconds=5,
    )

    assert logger.events == [
        {
            "event": "http_request",
            "method": "GET",
            "host": "example.test",
            "path": "/private",
            "status_code": 200,
        }
    ]


@pytest.mark.asyncio
async def test_rate_limiter_uses_scope_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("video_crawler.application.rate_limit.asyncio.sleep", record_sleep)
    limiter = ApplicationRateLimiter(random_fn=lambda minimum, maximum: minimum)

    await limiter.wait("comment_page", CrawlStrategy())

    assert sleeps == [0.8]
