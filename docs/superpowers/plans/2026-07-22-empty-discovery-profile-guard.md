# Empty Discovery and Profile Guard Bugfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Repository policy forbids subagents and parallel agents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore Crawl4AI 0.9.2 response-body capture, prevent inactive browser Profiles and empty Bilibili popular-page discoveries from producing misleading successful crawl jobs, and preserve actionable sanitized failure evidence.

**Architecture:** Normalize Crawl4AI response events at the generic browser gateway and use text-only browser mode to avoid out-of-scope binary image capture. Add Profile-state validation at the application boundary and the SQL claim boundary. Keep Bilibili endpoint, DOM, and parsing logic inside its Adapter; represent an exhausted discovery as a generic coded domain error. Persist coded module failures onto the enclosing run so the existing job API exposes them without a migration.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x async, MySQL 8, Crawl4AI, HTTPX, MinIO, pytest, pytest-asyncio, Ruff, mypy.

## Global Constraints

- Follow `AGENTS.md > CONSTRAINTS.md > design documents > implementation plan > README.md`.
- Use test-driven development: write one failing test, run it and confirm the expected failure, implement the minimum behavior, then rerun.
- Do not use subagents, parallel agents, `rg`, live Bilibili access in CI, or real Profile/Cookie/response fixtures.
- Keep Bilibili paths, selectors, identifiers, and parsing rules under `src/video_crawler/adapters/bilibili/`.
- Do not log or persist Cookie, Authorization, API keys, complete sensitive headers, browser storage, or real credentials.
- Do not add automatic login, CAPTCHA handling, anti-bot bypasses, scheduled crawling, multiple Workers, or new business data.
- Preserve the user's unrelated `.gitignore` modification and keep every implementation task in an isolated commit.
- Database and application times remain UTC; MySQL character data remains `utf8mb4`.

---

## Planned File Map

```text
src/video_crawler/infrastructure/browser/crawl4ai_gateway.py
    Crawl4AI 0.9.2 response-event normalization and text-only browser configuration.

src/video_crawler/application/jobs.py
    Profile-state reader protocol and stable job-creation errors.

src/video_crawler/bootstrap.py
    Production Profile-state adapter and dependency wiring.

src/video_crawler/infrastructure/database/repositories/jobs.py
    Active-Profile claim filter and generic coded failure persistence.

src/video_crawler/domain/errors.py
    Generic typed discovery failure with sanitized public fields.

src/video_crawler/adapters/bilibili/discovery.py
    Captured response, bounded DOM, and public HTTP fallback orchestration.

tests/api/test_jobs.py
    Job-creation Profile-state contract tests.

tests/unit/browser/test_browser_gateway.py
    Nested response-body, event filtering, and text-only browser tests.

tests/integration/database/test_job_repository.py
    Worker claim behavior for inactive and reactivated Profiles.

tests/unit/adapters/bilibili/test_discovery.py
    Discovery fallback, artifact, empty-result, and secret-safety tests.

tests/integration/database/test_failure_persistence.py
    Module-to-run coded failure propagation.

docs/api-contract.md
    PROFILE_NOT_ACTIVE public error contract.

docs/operations.md
    UTF-8 inspection and binary UUID export guidance.
```

### Task 0: Restore Crawl4AI Response Capture Compatibility

**Files:**
- Modify: `src/video_crawler/infrastructure/browser/crawl4ai_gateway.py`
- Modify: `tests/unit/browser/test_browser_gateway.py`

**Interfaces:**
- Consumes: Crawl4AI 0.9.2 flat network event mappings.
- Produces: `_CrawlResultPage.captured_responses -> tuple[CapturedResponse, ...]` with byte bodies.
- Preserves: the platform-neutral `BrowserGateway` and `NetworkCaptureGateway` contracts.
- Configures: `BrowserConfig(text_mode=True)` through `_browser_config()`.

- [ ] **Step 1: Add failing response-normalization tests**

Add two tests to `tests/unit/browser/test_browser_gateway.py`:

```python
def test_crawl_result_page_normalizes_nested_text_response_body() -> None:
    result = SimpleNamespace(
        network_requests=[
            {
                "event_type": "response",
                "url": "https://api.example.test/state",
                "status": 200,
                "headers": {"content-type": "application/json"},
                "body": {"text": '{"active":true}'},
            }
        ]
    )
    page = _CrawlResultPage(
        crawler=FakeSessionCrawler(),
        run_config_factory=FakeRunConfig,
        result=result,
        url="https://example.test/page",
        session_id="session-1",
    )

    assert page.captured_responses == (
        CapturedResponse(
            url="https://api.example.test/state",
            status_code=200,
            headers={"content-type": "application/json"},
            body=b'{"active":true}',
        ),
    )


def test_crawl_result_page_ignores_non_response_network_events() -> None:
    result = SimpleNamespace(
        network_requests=[
            {"event_type": "request", "url": "https://example.test/request"},
            {
                "event_type": "response_capture_error",
                "url": "https://example.test/image.png",
                "error": "binary body unavailable",
            },
        ]
    )
    page = _CrawlResultPage(
        crawler=FakeSessionCrawler(),
        run_config_factory=FakeRunConfig,
        result=result,
        url="https://example.test/page",
        session_id="session-1",
    )

    assert page.captured_responses == ()
```

- [ ] **Step 2: Add the failing text-only browser configuration assertion**

In `test_browser_gateway_applies_profile_and_page_timeout`, add:

```python
assert crawler.config == {
    "user_data_dir": str(tmp_path / "profile-1"),
    "use_persistent_context": True,
    "headless": True,
    "text_mode": True,
}
```

Update the visible-login configuration assertion to include `"text_mode": True`.

- [ ] **Step 3: Run the three tests and verify RED**

Run:

```powershell
uv run pytest tests/unit/browser/test_browser_gateway.py::test_crawl_result_page_normalizes_nested_text_response_body tests/unit/browser/test_browser_gateway.py::test_crawl_result_page_ignores_non_response_network_events tests/unit/browser/test_browser_gateway.py::test_browser_gateway_applies_profile_and_page_timeout -q
```

Expected: the nested body assertion receives `b""`, the request event is incorrectly exposed as a captured response, and browser config lacks `text_mode`.

- [ ] **Step 4: Implement platform-neutral normalization**

Add this helper above `_CrawlResultPage`:

```python
def _response_body_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode()
    if isinstance(value, Mapping):
        text = value.get("text")
        if isinstance(text, str):
            return text.encode()
    return b""
```

In `_browser_config()`, add `"text_mode": True`.

In `_CrawlResultPage.captured_responses`, require a response event for flat Crawl4AI entries and replace the existing body conversion:

```python
response = entry.get("response")
if isinstance(response, Mapping):
    values = response
elif entry.get("event_type") == "response":
    values = entry
else:
    continue

body = _response_body_bytes(values.get("body", b""))
```

- [ ] **Step 5: Run browser tests and verify GREEN**

Run:

```powershell
uv run pytest tests/unit/browser/test_browser_gateway.py -q
```

Expected: all browser gateway tests pass.

- [ ] **Step 6: Run focused static checks**

Run:

```powershell
uv run ruff format --check src/video_crawler/infrastructure/browser/crawl4ai_gateway.py tests/unit/browser/test_browser_gateway.py
uv run ruff check src/video_crawler/infrastructure/browser/crawl4ai_gateway.py tests/unit/browser/test_browser_gateway.py
uv run mypy src/video_crawler/infrastructure/browser/crawl4ai_gateway.py
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit Task 0**

```powershell
git add -- src/video_crawler/infrastructure/browser/crawl4ai_gateway.py tests/unit/browser/test_browser_gateway.py
git commit -m "fix: normalize Crawl4AI captured responses"
```

### Task 1: Reject Job Creation for Missing or Inactive Profiles

**Files:**
- Modify: `src/video_crawler/application/jobs.py`
- Modify: `src/video_crawler/bootstrap.py`
- Modify: `tests/api/test_jobs.py`

**Interfaces:**
- Produces: `ProfileStateReader.get_status(profile_id: UUID) -> str | None`.
- Produces: `ProfileNotFoundError` with code `PROFILE_NOT_FOUND` and HTTP 404.
- Produces: `ProfileNotActiveError` with code `PROFILE_NOT_ACTIVE` and HTTP 409.
- Changes: `JobService(..., profile_states: ProfileStateReader, ...)`.
- Consumes later: Task 2 retains the independent SQL claim guard.

- [ ] **Step 1: Add failing API tests for missing and inactive Profiles**

Replace `UnusedProfileService` in `tests/api/test_jobs.py` with a dedicated state reader and inject it into `JobService`:

```python
class InMemoryProfileStates:
    def __init__(self, states: dict[UUID, str] | None = None) -> None:
        self.states = states if states is not None else {PROFILE_ID: "active"}

    async def get_status(self, profile_id: UUID) -> str | None:
        return self.states.get(profile_id)


def _client(
    store: InMemoryJobStore | None = None,
    profile_states: InMemoryProfileStates | None = None,
) -> tuple[TestClient, InMemoryJobStore]:
    job_store = store or InMemoryJobStore()
    states = profile_states or InMemoryProfileStates()
    ids = iter((FIRST_JOB_ID, SECOND_JOB_ID, THIRD_JOB_ID))
    service = JobService(
        store=job_store,
        profile_states=states,
        default_strategy=CrawlStrategy(),
        idempotency_ttl=timedelta(hours=24),
        clock=lambda: NOW,
        id_factory=lambda: next(ids),
    )
    app = create_app(job_service=service, profile_service=UnusedProfileService())
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app), job_store
```

Add one parametrized contract test:

```python
import pytest


@pytest.mark.parametrize(
    ("states", "expected_status", "expected_code"),
    [
        ({}, 404, "PROFILE_NOT_FOUND"),
        ({PROFILE_ID: "expired"}, 409, "PROFILE_NOT_ACTIVE"),
        ({PROFILE_ID: "disabled"}, 409, "PROFILE_NOT_ACTIVE"),
    ],
)
def test_create_requires_an_active_profile(
    states: dict[UUID, str],
    expected_status: int,
    expected_code: str,
) -> None:
    client, store = _client(profile_states=InMemoryProfileStates(states))

    response = client.post(
        "/api/v1/crawl-jobs",
        json=_valid_request(),
        headers={"Idempotency-Key": "inactive-profile"},
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert store.jobs == {}
    assert store.idempotency == {}
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
uv run pytest tests/api/test_jobs.py::test_create_requires_an_active_profile -q
```

Expected: FAIL because `JobService` does not accept `profile_states` and does not validate Profile state.

- [ ] **Step 3: Add the application-level protocol and errors**

In `src/video_crawler/application/jobs.py`, add:

```python
class ProfileStateReader(Protocol):
    async def get_status(self, profile_id: UUID) -> str | None: ...


class ProfileNotFoundError(JobServiceError):
    code = "PROFILE_NOT_FOUND"
    message = "authentication profile was not found"
    status_code = 404


class ProfileNotActiveError(JobServiceError):
    code = "PROFILE_NOT_ACTIVE"
    message = "authentication profile is not active"
    status_code = 409
```

Store the reader in `JobService.__init__`:

```python
def __init__(
    self,
    *,
    store: JobStore,
    profile_states: ProfileStateReader,
    default_strategy: CrawlStrategy,
    idempotency_ttl: timedelta,
    clock: Callable[[], datetime] | None = None,
    id_factory: Callable[[], UUID] = uuid4,
) -> None:
    self._store = store
    self._profile_states = profile_states
```

At the beginning of `JobService.create`, before generating a job ID or idempotency reservation, add:

```python
profile_status = await self._profile_states.get_status(auth_profile_id)
if profile_status is None:
    raise ProfileNotFoundError
if profile_status != "active":
    raise ProfileNotActiveError
```

- [ ] **Step 4: Wire the production Profile state reader**

Add to `_AuthProfileOperations` in `src/video_crawler/bootstrap.py`:

```python
async def get_status(self, profile_id: UUID) -> str | None:
    profile = await self.get(profile_id)
    return None if profile is None else profile.status
```

Construct `self.profile_service` before `self.job_service`, then inject it:

```python
self.profile_service = _AuthProfileOperations(self)
self.job_service = JobService(
    store=self.job_store,
    profile_states=self.profile_service,
    default_strategy=CrawlStrategy.from_defaults(self.settings),
    idempotency_ttl=timedelta(hours=self.settings.idempotency_ttl_hours),
)
```

- [ ] **Step 5: Run API tests and verify GREEN**

Run:

```powershell
uv run pytest tests/api/test_jobs.py -q
```

Expected: all job API tests pass, including 404 for a missing Profile and 409 for inactive Profiles.

- [ ] **Step 6: Run focused static checks**

Run:

```powershell
uv run ruff check src/video_crawler/application/jobs.py src/video_crawler/bootstrap.py tests/api/test_jobs.py
uv run mypy src/video_crawler/application/jobs.py src/video_crawler/bootstrap.py
```

Expected: both commands exit 0.

- [ ] **Step 7: Commit Task 1**

```powershell
git add -- src/video_crawler/application/jobs.py src/video_crawler/bootstrap.py tests/api/test_jobs.py
git commit -m "fix: require active profiles for crawl jobs"
```

### Task 2: Pause Worker Claims While a Profile Is Inactive

**Files:**
- Modify: `src/video_crawler/infrastructure/database/repositories/jobs.py`
- Modify: `tests/integration/database/test_job_repository.py`

**Interfaces:**
- Consumes: existing `AuthProfile.status` values `active`, `expired`, and `disabled`.
- Produces: `JobRepository.claim_next(...)` only transitions jobs joined to active Profiles.
- Preserves: inactive jobs remain `pending` and become claimable after a successful Profile activation/verification.

- [ ] **Step 1: Add a failing database test for pause and reactivation**

Refactor the existing fixture setup only as needed to create two Profiles and jobs, then add:

```python
@pytest.mark.asyncio
async def test_claim_next_pauses_jobs_for_inactive_profiles(
    database: DatabaseSessionFactory,
) -> None:
    now = datetime.now(UTC)
    active_profile_id = UUID(int=101)
    expired_profile_id = UUID(int=102)
    active_job_id = UUID(int=201)
    expired_job_id = UUID(int=202)
    async with database.transaction() as session:
        platform = Platform(
            platform_key=f"test-{uuid4().hex[:12]}",
            display_name="Test",
            adapter_version="1",
            created_at=now.replace(tzinfo=None),
        )
        session.add(platform)
        await session.flush()
        session.add_all(
            [
                AuthProfile(
                    id=active_profile_id,
                    platform_id=platform.id,
                    profile_name="active",
                    profile_directory=f"active-{uuid4().hex[:8]}",
                    status="active",
                    created_at=now.replace(tzinfo=None),
                    updated_at=now.replace(tzinfo=None),
                ),
                AuthProfile(
                    id=expired_profile_id,
                    platform_id=platform.id,
                    profile_name="expired",
                    profile_directory=f"expired-{uuid4().hex[:8]}",
                    status="expired",
                    created_at=now.replace(tzinfo=None),
                    updated_at=now.replace(tzinfo=None),
                ),
            ]
        )
        await session.flush()
        for job_id, profile_id in (
            (active_job_id, active_profile_id),
            (expired_job_id, expired_profile_id),
        ):
            session.add(
                CrawlJob(
                    id=job_id,
                    root_job_id=job_id,
                    platform_id=platform.id,
                    auth_profile_id=profile_id,
                    source_url="https://example.test/video",
                    job_type="video",
                    status="pending",
                    effective_strategy={},
                    created_at=now.replace(tzinfo=None),
                    updated_at=now.replace(tzinfo=None),
                )
            )

    repository = JobRepository(database)
    first = await repository.claim_next("worker", now)
    second = await repository.claim_next("worker", now)

    assert first is not None and first.id == active_job_id
    assert second is None

    async with database.transaction() as session:
        profile = await session.get(AuthProfile, expired_profile_id)
        assert profile is not None
        profile.status = "active"
    resumed = await repository.claim_next("worker", now)
    assert resumed is not None and resumed.id == expired_job_id
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
uv run pytest tests/integration/database/test_job_repository.py::test_claim_next_pauses_jobs_for_inactive_profiles -q
```

Expected: FAIL because the second claim currently returns the expired Profile's job.

- [ ] **Step 3: Add the active-Profile join to the claim query**

In `JobRepository._claim`, change the query construction to:

```python
query = (
    select(CrawlJob)
    .join(AuthProfile, CrawlJob.auth_profile_id == AuthProfile.id)
    .where(
        CrawlJob.status == "pending",
        AuthProfile.status == "active",
        (CrawlJob.next_retry_at.is_(None) | (CrawlJob.next_retry_at <= now)),
    )
    .order_by(CrawlJob.id.asc())
    .with_for_update(skip_locked=True)
    .limit(1)
)
```

- [ ] **Step 4: Run repository tests and verify GREEN**

Run:

```powershell
uv run pytest tests/integration/database/test_job_repository.py -q
```

Expected: the inactive-Profile test and the concurrent `SKIP LOCKED` test pass.

- [ ] **Step 5: Run focused static checks**

Run:

```powershell
uv run ruff check src/video_crawler/infrastructure/database/repositories/jobs.py tests/integration/database/test_job_repository.py
uv run mypy src/video_crawler/infrastructure/database/repositories/jobs.py
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- src/video_crawler/infrastructure/database/repositories/jobs.py tests/integration/database/test_job_repository.py
git commit -m "fix: pause jobs with inactive profiles"
```

### Task 3: Restore Bounded Bilibili Popular Discovery and Reject Empty Results

**Files:**
- Modify: `src/video_crawler/domain/errors.py`
- Modify: `src/video_crawler/adapters/bilibili/discovery.py`
- Modify: `tests/unit/adapters/bilibili/test_discovery.py`

**Interfaces:**
- Produces: `DiscoveryEmptyError(details: Mapping[str, int])` with `code`, `public_message`, and sanitized integer `details`.
- Produces: Bilibili fallback order captured JSON -> waited DOM -> public HTTP JSON.
- Consumes: `HttpGateway.request(...)`, `RawArtifactGateway.store(...)`, `BrowserPage.wait_for_selector(...)`.
- Produces for Task 4: coded domain errors that generic persistence can safely expose.

- [ ] **Step 1: Expand test fakes for HTTP, artifacts, logging, and bounded DOM wait**

In `tests/unit/adapters/bilibili/test_discovery.py`, import `HttpResponse` and `DiscoveryEmptyError`, then add:

```python
class FakeHttp:
    def __init__(self, response: HttpResponse | None = None) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    async def request(self, method: str, url: str, **kwargs: object) -> HttpResponse:
        self.calls.append((method, url, kwargs))
        if self.response is None:
            raise AssertionError("HTTP fallback was not expected")
        return self.response


class RecordingArtifacts:
    def __init__(self) -> None:
        self.items: list[tuple[bytes, dict[str, object]]] = []

    async def store(self, content: bytes, **kwargs: object) -> object:
        self.items.append((content, kwargs))
        return SimpleNamespace(id=1)


class RecordingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def warning(self, event: str, **values: object) -> None:
        self.events.append((event, values))
```

Update `FakePage` to record waits:

```python
self.waits: list[tuple[str, float]] = []

async def wait_for_selector(self, selector: str, *, timeout_seconds: float) -> None:
    self.waits.append((selector, timeout_seconds))
```

Update `make_context` to accept a `FakeHttp`, attach `http`, `raw_artifacts`, and `logger`, and return those fakes with the existing browser and cancellation objects.
Update every existing `make_context` call to unpack the expanded return tuple; keep the captured-response and DOM assertions unchanged.

- [ ] **Step 2: Add the failing HTTP fallback test**

```python
@pytest.mark.asyncio
async def test_discovery_uses_public_http_fallback_and_archives_response() -> None:
    page = FakePage(url=POPULAR_URL, evaluated=[])
    http = FakeHttp(
        HttpResponse(
            url="https://api.bilibili.com/x/web-interface/popular?pn=1&ps=2",
            status_code=200,
            headers={"content-type": "application/json"},
            body=FIXTURE.read_bytes(),
        )
    )
    context, _, _, artifacts, _ = make_context(page, http=http)
    target = await BilibiliAdapter().resolve_target(context, POPULAR_URL)

    discovered = [
        item
        async for item in BilibiliAdapter().discover_targets(
            context, target, CrawlStrategy(video_limit=2)
        )
    ]

    assert [item.platform_video_id for item in discovered] == [
        "BV1FAKE00001",
        "BV1FAKE00002",
    ]
    assert http.calls[0][0:2] == (
        "GET",
        "https://api.bilibili.com/x/web-interface/popular",
    )
    assert http.calls[0][2]["params"] == {"pn": 1, "ps": 2}
    assert artifacts.items[0][1]["artifact_type"] == "popular_discovery"
    assert artifacts.items[0][1]["content_type"] == "application/json"
```

- [ ] **Step 3: Add the failing all-empty test and secret-safety assertions**

```python
@pytest.mark.asyncio
async def test_discovery_raises_coded_error_when_all_sources_are_empty() -> None:
    page = FakePage(url=POPULAR_URL, evaluated=[])
    secret = "secret-cookie-value"
    http = FakeHttp(
        HttpResponse(
            url="https://api.bilibili.com/x/web-interface/popular?pn=1&ps=3",
            status_code=200,
            headers={"set-cookie": secret},
            body=b'{"code":0,"data":{"list":[]}}',
        )
    )
    context, _, _, _, logger = make_context(page, http=http)
    target = await BilibiliAdapter().resolve_target(context, POPULAR_URL)

    with pytest.raises(DiscoveryEmptyError) as raised:
        _ = [
            item
            async for item in BilibiliAdapter().discover_targets(
                context, target, CrawlStrategy(video_limit=3)
            )
        ]

    assert raised.value.code == "DISCOVERY_EMPTY"
    assert raised.value.details == {
        "captured_responses": 0,
        "captured_candidates": 0,
        "dom_candidates": 0,
        "http_candidates": 0,
    }
    assert secret not in str(raised.value)
    assert secret not in repr(logger.events)
    assert page.waits == [('a[href*="/video/BV"]', 10.0)]
```

- [ ] **Step 4: Run both tests and verify RED**

Run:

```powershell
uv run pytest tests/unit/adapters/bilibili/test_discovery.py::test_discovery_uses_public_http_fallback_and_archives_response tests/unit/adapters/bilibili/test_discovery.py::test_discovery_raises_coded_error_when_all_sources_are_empty -q
```

Expected: FAIL because the current Adapter returns an empty iterator without calling HTTP or raising a coded error.

- [ ] **Step 5: Add the generic coded discovery error**

In `src/video_crawler/domain/errors.py`, add:

```python
from collections.abc import Mapping


class DiscoveryEmptyError(UpstreamError):
    code = "DISCOVERY_EMPTY"
    public_message = "list discovery returned no valid targets"

    def __init__(self, details: Mapping[str, int]) -> None:
        self.details = {key: int(value) for key, value in details.items()}
        super().__init__(self.public_message)
```

- [ ] **Step 6: Implement bounded fallbacks and raw-response archival**

In `src/video_crawler/adapters/bilibili/discovery.py`, add constants:

```python
_POPULAR_API_URL = "https://api.bilibili.com/x/web-interface/popular"
_POPULAR_LINK_SELECTOR = 'a[href*="/video/BV"]'
_DOM_WAIT_SECONDS = 10.0
```

Add an HTTP helper:

```python
async def _http_candidates(
    context: AdapterContext,
    strategy: CrawlStrategy,
) -> tuple[list[str], int]:
    response = await context.http.request(
        "GET",
        _POPULAR_API_URL,
        params={"pn": 1, "ps": strategy.video_limit},
        timeout_seconds=strategy.request_timeout_seconds,
    )
    await context.raw_artifacts.store(
        response.body,
        artifact_type="popular_discovery",
        content_type=response.headers.get("content-type", "application/json").split(";", 1)[0],
        metadata={"status_code": response.status_code},
    )
    if response.status_code != 200:
        return [], response.status_code
    return _parse_popular_response(response.body) or [], response.status_code
```

Restructure `discover_popular_targets` so it:

```python
responses = context.network_capture.responses_for(page)
captured = _captured_candidates_from(responses)
candidates = captured
dom: list[str] = []
http: list[str] = []
if not candidates:
    await page.wait_for_selector(
        _POPULAR_LINK_SELECTOR,
        timeout_seconds=min(_DOM_WAIT_SECONDS, strategy.page_timeout_seconds),
    )
    dom = _dom_candidates(await page.evaluate(_DOM_LINK_SCRIPT))
    candidates = dom
if not candidates:
    http, _ = await _http_candidates(context, strategy)
    candidates = http
if not candidates:
    details = {
        "captured_responses": len(responses),
        "captured_candidates": len(captured),
        "dom_candidates": len(dom),
        "http_candidates": len(http),
    }
    context.logger.warning("discovery_empty", **details)
    raise DiscoveryEmptyError(details)
```

Rename/refactor `_captured_candidates` to accept the captured response sequence directly and return `[]` when no valid response exists. Retain exact host/path/status validation, existing parsing, deduplication, cancellation checks, ordering, `video_limit`, and `finally: await page.close()`.

- [ ] **Step 7: Run the full Bilibili discovery test file and verify GREEN**

Run:

```powershell
uv run pytest tests/unit/adapters/bilibili/test_discovery.py -q
```

Expected: all existing captured/DOM tests plus the HTTP and empty-result tests pass; HTTP is not called when captured or DOM candidates exist.

- [ ] **Step 8: Run focused static and architecture checks**

Run:

```powershell
uv run ruff check src/video_crawler/domain/errors.py src/video_crawler/adapters/bilibili/discovery.py tests/unit/adapters/bilibili/test_discovery.py
uv run mypy src/video_crawler/domain/errors.py src/video_crawler/adapters/bilibili/discovery.py
Get-ChildItem -Recurse -File src\video_crawler\core,src\video_crawler\domain,src\video_crawler\application,src\video_crawler\worker | Select-String -Pattern '\b(bvid|aid|cid)\b|x/web-interface/popular'
```

Expected: Ruff and mypy exit 0; the architecture scan returns no Bilibili protocol hits in generic layers.

- [ ] **Step 9: Commit Task 3**

```powershell
git add -- src/video_crawler/domain/errors.py src/video_crawler/adapters/bilibili/discovery.py tests/unit/adapters/bilibili/test_discovery.py
git commit -m "fix: fail safely when popular discovery is empty"
```

### Task 4: Persist Stable Discovery Errors on Module, Run, and Job

**Files:**
- Modify: `src/video_crawler/infrastructure/database/repositories/jobs.py`
- Create: `tests/integration/database/test_failure_persistence.py`

**Interfaces:**
- Consumes: optional exception attributes `code: str`, `public_message: str`, and `details: Mapping[str, object]`.
- Produces: generic `error_code`, safe `error_message`, and sanitized `result_summary` on `crawl_module_runs`.
- Produces: failed/partial run inherits the most recent failed module error when the run has no existing error.
- Preserves: unknown exceptions expose only their class name and `module execution failed`.

- [ ] **Step 1: Add a failing integration test for coded module persistence**

Create `tests/integration/database/test_failure_persistence.py` using the existing `database` fixture. Insert a unique Platform, active AuthProfile, root CrawlJob, and running CrawlRun. Then:

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_coded_module_failure_is_exposed_on_the_finished_run(
    database: DatabaseSessionFactory,
) -> None:
    job_id, run_id = await _insert_running_job(database)
    states = SqlAlchemyModuleStateStore(database, run_id)
    await states.mark_running("discovery")
    await states.mark_failed(
        "discovery",
        DiscoveryEmptyError(
            {
                "captured_responses": 0,
                "captured_candidates": 0,
                "dom_candidates": 0,
                "http_candidates": 0,
            }
        ),
    )

    worker_states = SqlAlchemyWorkerStateStore(database)
    await worker_states.mark_finished(job_id, run_id, "failed", datetime.now(UTC))

    async with database() as session:
        module = await session.scalar(
            select(CrawlModuleRun).where(CrawlModuleRun.crawl_run_id == run_id)
        )
        run = await session.get(CrawlRun, run_id)
        job = await session.get(CrawlJob, job_id)
    assert module is not None
    assert module.error_code == "DISCOVERY_EMPTY"
    assert module.error_message == "list discovery returned no valid targets"
    assert module.result_summary == {
        "captured_responses": 0,
        "captured_candidates": 0,
        "dom_candidates": 0,
        "http_candidates": 0,
    }
    assert run is not None and run.error_code == "DISCOVERY_EMPTY"
    assert run.error_message == "list discovery returned no valid targets"
    assert run.result_summary == {
        "module": "discovery",
        "details": module.result_summary,
    }
    assert job is not None and job.status == "failed"
```

The `_insert_running_job` helper must create only synthetic identifiers and return `(job_id, run_id)`.

- [ ] **Step 2: Run the new integration test and verify RED**

Run:

```powershell
uv run pytest tests/integration/database/test_failure_persistence.py -q
```

Expected: FAIL because module failures currently use the exception class name, discard details, and are not copied to the run.

- [ ] **Step 3: Add generic safe error extraction**

In `src/video_crawler/infrastructure/database/repositories/jobs.py`, add:

```python
from collections.abc import Mapping


def _public_error(error: Exception) -> tuple[str, str, dict[str, object] | None]:
    code = getattr(error, "code", type(error).__name__)
    message = getattr(error, "public_message", "module execution failed")
    raw_details = getattr(error, "details", None)
    details = dict(raw_details) if isinstance(raw_details, Mapping) else None
    return str(code), str(message), details
```

Use it in `SqlAlchemyModuleStateStore.mark_failed`:

```python
error_code, error_message, result_summary = _public_error(error)
await self._mark(
    module_key,
    "failed",
    finished_at=datetime.now(UTC),
    error_code=error_code,
    error_message=error_message,
    result_summary=result_summary,
)
```

Do not use `str(error)` for unknown exceptions.

- [ ] **Step 4: Propagate a failed module error when finishing the run**

Inside `SqlAlchemyWorkerStateStore.mark_finished`, after loading the run and before updating the job, query the failed module when `final_status in {"failed", "partial"}` and `run.error_code is None`:

```python
failed_module = (
    await session.execute(
        select(CrawlModuleRun)
        .where(
            CrawlModuleRun.crawl_run_id == run_id,
            CrawlModuleRun.status == "failed",
        )
        .order_by(CrawlModuleRun.id.asc())
        .limit(1)
    )
).scalar_one_or_none()
if failed_module is not None:
    run.error_code = failed_module.error_code
    run.error_message = failed_module.error_message
    run.result_summary = {
        "module": failed_module.module_key,
        "details": failed_module.result_summary or {},
    }
```

- [ ] **Step 5: Run persistence and job API tests and verify GREEN**

Run:

```powershell
uv run pytest tests/integration/database/test_failure_persistence.py tests/api/test_jobs.py -q
```

Expected: coded errors persist to module/run, job status is failed, and existing API behavior remains green.

- [ ] **Step 6: Run focused static checks**

Run:

```powershell
uv run ruff check src/video_crawler/infrastructure/database/repositories/jobs.py tests/integration/database/test_failure_persistence.py
uv run mypy src/video_crawler/infrastructure/database/repositories/jobs.py
```

Expected: both commands exit 0.

- [ ] **Step 7: Commit Task 4**

```powershell
git add -- src/video_crawler/infrastructure/database/repositories/jobs.py tests/integration/database/test_failure_persistence.py
git commit -m "fix: persist coded crawl module failures"
```

### Task 5: Document the Error Contract and UTF-8 Inspection Rules

**Files:**
- Modify: `docs/api-contract.md`
- Modify: `docs/operations.md`
- Modify: `tests/acceptance/test_contracts.py`

**Interfaces:**
- Documents: `PROFILE_NOT_ACTIVE` is HTTP 409.
- Documents: `DISCOVERY_EMPTY` appears in job/run error details, not as a new endpoint.
- Documents: PowerShell 5.1 UTF-8 inspection and Navicat `BINARY(16)` UUID exports.

- [ ] **Step 1: Add a failing documentation contract test**

In `tests/acceptance/test_contracts.py`, add:

```python
def test_operations_document_utf8_and_binary_uuid_inspection() -> None:
    operations = Path("docs/operations.md").read_text(encoding="utf-8")
    api_contract = Path("docs/api-contract.md").read_text(encoding="utf-8")

    assert "Get-Content -Encoding UTF8" in operations
    assert "BINARY(16)" in operations
    assert "0x..." in operations
    assert "PROFILE_NOT_ACTIVE" in api_contract
    assert "DISCOVERY_EMPTY" in api_contract
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
uv run pytest tests/acceptance/test_contracts.py::test_operations_document_utf8_and_binary_uuid_inspection -q
```

Expected: FAIL because the required error and encoding guidance is absent.

- [ ] **Step 3: Update the API contract**

In `docs/api-contract.md`, add to job creation/Profile semantics:

```text
创建任务前必须确认 Profile 存在且状态为 active。不存在返回 404
PROFILE_NOT_FOUND；expired 或 disabled 返回 409 PROFILE_NOT_ACTIVE。
```

Add to job error semantics:

```text
Bilibili 热门列表在捕获响应、DOM 和公开 HTTP 回退均未发现有效目标时，
discovery 模块及根任务失败，任务错误码为 DISCOVERY_EMPTY。
```

Add `PROFILE_NOT_ACTIVE` and `DISCOVERY_EMPTY` to the stable error list.

- [ ] **Step 4: Update operations guidance**

Append a UTF-8 inspection subsection to `docs/operations.md`:

```powershell
Get-Content -Encoding UTF8 .\video_crawler.sql
Get-Content -Raw -Encoding UTF8 .\README.md
```

State explicitly:

- Windows PowerShell 5.1 can misread UTF-8 without BOM when encoding is omitted.
- MySQL, Navicat export, and import should remain `utf8mb4`/UTF-8; do not double-convert text.
- `0x...` is the expected Navicat representation of `BINARY(16)` UUID data.
- escaped `\"` inside an SQL string is normal JSON/SQL escaping.

- [ ] **Step 5: Run the acceptance test and verify GREEN**

Run:

```powershell
uv run pytest tests/acceptance/test_contracts.py -q
```

Expected: all acceptance contract tests pass.

- [ ] **Step 6: Run format/diff checks and commit Task 5**

Run:

```powershell
git diff --check -- docs/api-contract.md docs/operations.md tests/acceptance/test_contracts.py
uv run ruff check tests/acceptance/test_contracts.py
```

Expected: both commands exit 0.

Commit:

```powershell
git add -- docs/api-contract.md docs/operations.md tests/acceptance/test_contracts.py
git commit -m "docs: explain crawler failures and UTF-8 exports"
```

### Task 6: Complete Verification and Manual Docker Handoff

**Files:**
- Verify only; do not modify unrelated files.

**Interfaces:**
- Proves: targeted behavior, full suite, format, lint, typing, architecture boundaries, and secret safety.
- Leaves: live Profile login and live Bilibili smoke execution as explicit operator actions.

- [ ] **Step 1: Run all targeted tests**

```powershell
uv run pytest tests/api/test_jobs.py tests/integration/database/test_job_repository.py tests/unit/adapters/bilibili/test_discovery.py tests/integration/database/test_failure_persistence.py tests/acceptance/test_contracts.py -q
```

Expected: all targeted tests pass.

- [ ] **Step 2: Run the complete automated suite**

```powershell
uv run pytest -q
```

Expected: all tests pass; only documented pre-existing skips/warnings are allowed.

- [ ] **Step 3: Run quality gates**

```powershell
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 4: Run architecture and secret scans**

```powershell
Get-ChildItem -Recurse -File src\video_crawler\core,src\video_crawler\domain,src\video_crawler\application,src\video_crawler\worker | Select-String -Pattern '\b(bvid|aid|cid)\b|x/web-interface/popular'
Get-ChildItem -Recurse -File src,tests,docs | Select-String -Pattern 'Cookie:|Authorization:|MINIO_SECRET_KEY=.+'
```

Expected: no Bilibili protocol details in generic layers and no committed secret values. Protocol names used in security documentation or synthetic redaction tests must not include real values.

- [ ] **Step 5: Confirm only scoped files and the user's pre-existing change remain**

```powershell
git status --short
git log -6 --oneline
```

Expected: implementation commits are present; no uncommitted implementation files remain; the user's pre-existing `.gitignore` modification remains untouched.

- [ ] **Step 6: Hand off the live Docker verification command**

Do not rebuild, restart, migrate, log in, or run persistent Docker services automatically. Give the operator exact PowerShell commands to:

```powershell
docker compose build api worker
docker compose up -d api worker
docker compose run --rm -e DISPLAY=host.docker.internal:0 profile-login login --platform bilibili --profile bilibili-main
```

Then instruct the operator to call the existing Profile `verify` endpoint, confirm `status=active`, create a fresh popular job with a new `Idempotency-Key`, and verify that `target_discoveries` and `videos` are nonzero. Success means the root discovery creates child jobs up to `video_limit`; failure must expose `DISCOVERY_EMPTY` instead of `success` with zero results.

## Plan Self-Review Result

- Profile creation, Worker claim, live discovery fallback, empty-result semantics, sanitized persistence, API errors, and UTF-8 guidance each map to a dedicated task.
- All new behavior starts with an explicit failing test and expected RED result.
- Type names and signatures are consistent across tasks: `ProfileStateReader`, `DiscoveryEmptyError`, `PROFILE_NOT_ACTIVE`, and `DISCOVERY_EMPTY` have one definition each.
- No database migration is needed because existing module/run JSON and error columns are reused.
- No Bilibili protocol detail is introduced outside the Adapter.
- Live network access and interactive Profile login remain manual and outside CI.
