# Generic Video Crawler Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a generic FastAPI/MySQL/MinIO video-site crawler with one supervised Worker, isolated Crawl4AI task processes, manual cancellation/resume, and a first Bilibili adapter.

**Architecture:** FastAPI persists logical jobs and serves results. A single Worker claims MySQL jobs and supervises one isolated process group per task. The task process selects a site Adapter, uses Core gateways, writes raw artifacts to MinIO, and persists normalized metrics, comments, and timed text to MySQL.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, MySQL 8, Crawl4AI, MinIO, pytest, Ruff, mypy, Docker Compose.

## Global Constraints

- No frontend, users, JWT, scheduled crawling, Redis, Celery, Kafka, or multiple Workers.
- Only metrics, comments/replies, danmaku, and subtitles are business data.
- Core and Domain contain no Bilibili-specific identifiers, endpoints, selectors, or protocol logic.
- Adapter implementations do not access SQLAlchemy sessions or MinIO clients directly.
- One Worker executes one task at a time; each task runs in its own Unix process group.
- Cancel uses SIGTERM followed by SIGKILL and preserves committed data.
- Resume is manual and skips successful modules.
- CI never contacts live Bilibili.
- All secrets and browser state stay out of Git and logs.

---

## Planned File Map

```text
src/video_crawler/
├── main.py
├── api/
├── application/
├── domain/
├── infrastructure/
│   ├── browser/
│   ├── database/
│   ├── http/
│   ├── logging/
│   ├── process/
│   └── storage/
├── adapters/
│   ├── base.py
│   ├── registry.py
│   └── bilibili/
└── worker/

migrations/
tests/
```

### Task 1: Repository bootstrap and quality gates

**Files:**
- Create: `src/video_crawler/__init__.py`
- Create: `src/video_crawler/main.py`
- Create: `src/video_crawler/core/config.py`
- Create: `tests/unit/test_config.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Modify: `Dockerfile`

**Interfaces:**
- Produces: `Settings`, `get_settings()`, and a minimal `FastAPI` application object `app`.

- [ ] **Step 1: Write the failing settings test**

```python
from video_crawler.core.config import Settings


def test_settings_rejects_invalid_delay_range() -> None:
    try:
        Settings(
            mysql_password="x",
            minio_secret_key="x",
            api_key="x",
            default_video_delay_min_seconds=3.0,
            default_video_delay_max_seconds=1.0,
        )
    except ValueError as exc:
        assert "video delay min" in str(exc)
    else:
        raise AssertionError("Settings must reject min > max")
```

- [ ] **Step 2: Run the test and verify failure**

Run: `pytest tests/unit/test_config.py -v`

Expected: import failure because `video_crawler.core.config` does not exist.

- [ ] **Step 3: Implement typed settings with exact defaults from `CONSTRAINTS.md`**

Create `Settings` as `pydantic_settings.BaseSettings`; include MySQL, MinIO, API Key, Worker, retention, and default strategy fields. Add an `after` validator that rejects min delays greater than max delays. Cache `get_settings()` with `functools.lru_cache`.

- [ ] **Step 4: Add minimal app and Alembic bootstrap**

`main.py` must expose `app = FastAPI(title="Video Crawler API", version="0.1.0")`. `migrations/env.py` must import metadata from a future central database base without creating tables yet.

- [ ] **Step 5: Run quality gates**

Run:

```bash
pytest tests/unit/test_config.py -v
ruff format --check src tests
ruff check src tests
mypy src
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml Dockerfile alembic.ini migrations src tests
git commit -m "chore: bootstrap service and quality gates"
```

### Task 2: Domain models and strategy validation

**Files:**
- Create: `src/video_crawler/domain/targets.py`
- Create: `src/video_crawler/domain/metrics.py`
- Create: `src/video_crawler/domain/comments.py`
- Create: `src/video_crawler/domain/timed_text.py`
- Create: `src/video_crawler/domain/strategy.py`
- Create: `src/video_crawler/domain/errors.py`
- Create: `tests/unit/domain/test_strategy.py`
- Create: `tests/unit/domain/test_timed_text.py`

**Interfaces:**
- Produces the exact dataclasses and enums in `docs/architecture/adapter-contract.md`.
- Produces `CrawlStrategy.from_defaults(settings)` and `CrawlStrategy.merge(overrides)`.
- Produces `build_timed_text_dedup_key(item, content_type) -> str`.

- [ ] **Step 1: Write failing strategy boundary tests**

```python
import pytest
from video_crawler.domain.strategy import CrawlStrategy


def test_video_limit_must_be_within_contract() -> None:
    with pytest.raises(ValueError, match="video_limit"):
        CrawlStrategy(video_limit=501)


def test_zero_root_comment_limit_means_unlimited() -> None:
    strategy = CrawlStrategy(max_root_comments=0)
    assert strategy.max_root_comments == 0
```

- [ ] **Step 2: Write failing dedup tests**

```python
from dataclasses import replace

from video_crawler.domain.timed_text import (
    NormalizedTimedText,
    TimedTextType,
    build_timed_text_dedup_key,
)


def test_platform_item_id_has_priority_for_dedup() -> None:
    item = NormalizedTimedText(
        platform_item_id="42",
        start_ms=1000,
        end_ms=None,
        text="hello",
        published_at=None,
        sender_ref=None,
        attributes={},
    )
    first = build_timed_text_dedup_key(item, TimedTextType.DANMAKU)
    changed = replace(item, text="changed")
    assert first == build_timed_text_dedup_key(changed, TimedTextType.DANMAKU)
```

- [ ] **Step 3: Implement immutable slot dataclasses and validation**

Use `StrEnum`, frozen dataclasses, UTC-aware datetimes, and `Mapping[str, Any]` where mutation is not needed. Validate nonnegative counts and times. Strategy defaults must match `CONSTRAINTS.md`.

- [ ] **Step 4: Run tests and static checks**

Run: `pytest tests/unit/domain -v && ruff check src tests && mypy src`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/video_crawler/domain tests/unit/domain
git commit -m "feat: define generic crawler domain models"
```

### Task 3: Adapter protocol and registry

**Files:**
- Create: `src/video_crawler/adapters/base.py`
- Create: `src/video_crawler/adapters/registry.py`
- Create: `src/video_crawler/application/gateways.py`
- Create: `tests/unit/adapters/test_registry.py`

**Interfaces:**
- Produces `VideoSiteAdapter` protocol and `AdapterContext`.
- Produces `AdapterRegistry.register(adapter)`, `AdapterRegistry.resolve(url)`, and `AdapterNotFoundError`.

- [ ] **Step 1: Write failing registry tests**

```python
import pytest
from video_crawler.adapters.registry import AdapterRegistry
from video_crawler.domain.errors import AdapterNotFoundError


class ExampleAdapter:
    platform_key = "example"

    def match(self, url: str) -> bool:
        return url.startswith("https://example.test/")


def test_registry_resolves_matching_adapter() -> None:
    registry = AdapterRegistry([ExampleAdapter()])
    assert registry.resolve("https://example.test/v/1").platform_key == "example"


def test_registry_rejects_unknown_url() -> None:
    registry = AdapterRegistry([ExampleAdapter()])
    with pytest.raises(AdapterNotFoundError):
        registry.resolve("https://unknown.test/v/1")
```

- [ ] **Step 2: Implement gateway protocols and registry**

Gateway protocols must hide Crawl4AI, SQLAlchemy, and MinIO concrete types. Registry must reject duplicate `platform_key` values at construction.

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/unit/adapters/test_registry.py -v
ruff check src tests
mypy src
git add src/video_crawler/adapters src/video_crawler/application tests/unit/adapters
git commit -m "feat: add generic adapter contract and registry"
```

### Task 4: SQLAlchemy models and initial Alembic migration

**Files:**
- Create: `src/video_crawler/infrastructure/database/base.py`
- Create: `src/video_crawler/infrastructure/database/types.py`
- Create: `src/video_crawler/infrastructure/database/models/*.py`
- Create: `migrations/versions/0001_initial_schema.py`
- Create: `tests/integration/database/test_migrations.py`
- Create: `tests/unit/database/test_uuid_type.py`

**Interfaces:**
- Produces central `Base.metadata`.
- Produces `UUIDBinary` SQLAlchemy type.
- Produces ORM models matching `sql/reference_schema.sql`.

- [ ] **Step 1: Write UUID round-trip test**

```python
from uuid import uuid4
from video_crawler.infrastructure.database.types import UUIDBinary


def test_uuid_binary_round_trip() -> None:
    value = uuid4()
    column = UUIDBinary()
    encoded = column.process_bind_param(value, None)
    assert isinstance(encoded, bytes) and len(encoded) == 16
    assert column.process_result_value(encoded, None) == value
```

- [ ] **Step 2: Write empty-database migration test**

Use Testcontainers MySQL. Run `alembic upgrade head`, inspect tables, and assert at least `crawl_jobs`, `videos`, `comments`, and `timed_text_items` exist.

- [ ] **Step 3: Implement models and migration**

Copy exact names, indexes, unique constraints, and foreign keys from `sql/reference_schema.sql`. Add check constraints where MySQL reliably enforces them; retain application validation regardless.

- [ ] **Step 4: Seed metric definitions in migration**

Insert the seven approved metric keys. Downgrade must delete those rows before dropping tables.

- [ ] **Step 5: Run database tests and commit**

```bash
pytest tests/unit/database/test_uuid_type.py -v
pytest tests/integration/database/test_migrations.py -v -m integration
alembic upgrade head
ruff check src tests
mypy src
git add src/video_crawler/infrastructure/database migrations tests
git commit -m "feat: add MySQL schema and Alembic migration"
```

### Task 5: Database session and repositories

**Files:**
- Create: `src/video_crawler/infrastructure/database/session.py`
- Create: `src/video_crawler/infrastructure/database/repositories/jobs.py`
- Create: `src/video_crawler/infrastructure/database/repositories/content.py`
- Create: `src/video_crawler/infrastructure/database/repositories/results.py`
- Create: `tests/integration/database/test_job_repository.py`
- Create: `tests/integration/database/test_result_upserts.py`

**Interfaces:**
- Produces `DatabaseSessionFactory`.
- Produces `JobRepository.claim_next(worker_id, now) -> ClaimedJob | None`.
- Produces `ResultRepository.upsert_comments`, `upsert_timed_text_batch`, and `create_metric_snapshot`.

- [ ] **Step 1: Write concurrent claim test**

Create two pending jobs, open two transactions, call `claim_next` concurrently, and assert different job IDs are returned. The query must use `FOR UPDATE SKIP LOCKED`.

- [ ] **Step 2: Write idempotent result tests**

Insert the same comment batch twice and assert one row. Insert the same timed text batch twice and assert one row. Insert two metric results and assert two snapshots.

- [ ] **Step 3: Implement repositories with explicit transaction boundaries**

Do not call `commit()` inside low-level row helpers. Public repository methods own transactions or receive a unit-of-work transaction explicitly.

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/integration/database -v -m integration
ruff check src tests
mypy src
git add src/video_crawler/infrastructure/database tests/integration/database
git commit -m "feat: add transactional MySQL repositories"
```

### Task 6: MinIO raw artifact lifecycle

**Files:**
- Create: `src/video_crawler/infrastructure/storage/minio.py`
- Create: `src/video_crawler/application/raw_artifacts.py`
- Create: `tests/integration/storage/test_minio_artifacts.py`
- Create: `tests/unit/storage/test_object_keys.py`

**Interfaces:**
- Produces `RawArtifactService.store(...) -> RawArtifactRef`.
- Produces deterministic `build_object_key(platform, captured_at, video_id, run_id, artifact_name)`.
- Produces `cleanup_expired(now) -> CleanupSummary`.

- [ ] **Step 1: Write object-key test**

Assert that a Bilibili artifact path contains `bilibili/YYYY/MM/DD/video/run/artifact` without embedding query strings or secrets.

- [ ] **Step 2: Write interrupted upload integration test**

Mock failure after temporary upload but before promotion. Assert database status is not `available` and cleanup can delete the temporary object.

- [ ] **Step 3: Implement two-phase object storage**

Upload to `.tmp/{run_id}/{artifact_id}`, verify size and SHA-256, copy to final key, delete temporary object, then mark database row available.

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/unit/storage tests/integration/storage -v
ruff check src tests
mypy src
git add src/video_crawler/infrastructure/storage src/video_crawler/application tests
git commit -m "feat: add verified MinIO raw artifact storage"
```

### Task 7: Logging, redaction, and API Key

**Files:**
- Create: `src/video_crawler/infrastructure/logging/config.py`
- Create: `src/video_crawler/infrastructure/logging/redaction.py`
- Create: `src/video_crawler/api/dependencies/auth.py`
- Create: `tests/unit/logging/test_redaction.py`
- Create: `tests/api/test_api_key.py`

**Interfaces:**
- Produces `configure_logging(settings)` and `redact_event(event_dict)`.
- Produces FastAPI dependency `require_api_key`.

- [ ] **Step 1: Write redaction tests**

Pass nested headers, URLs, and dictionaries containing Cookie, Authorization, API Key, password, and token fields. Assert none of the original values remain in serialized output.

- [ ] **Step 2: Write API Key tests**

Assert disabled mode permits requests, enabled mode rejects missing/wrong key with `401`, and accepts correct key. Use constant-time comparison.

- [ ] **Step 3: Implement and commit**

```bash
pytest tests/unit/logging tests/api/test_api_key.py -v
ruff check src tests
mypy src
git add src/video_crawler/infrastructure/logging src/video_crawler/api tests
git commit -m "feat: add structured redacted logging and API key auth"
```

### Task 8: Browser Profile validation and leases

**Files:**
- Create: `src/video_crawler/application/auth_profiles.py`
- Create: `src/video_crawler/infrastructure/browser/profiles.py`
- Create: `tests/unit/browser/test_profile_paths.py`
- Create: `tests/integration/database/test_profile_leases.py`

**Interfaces:**
- Produces `validate_profile_directory(name) -> str`.
- Produces `ProfileLeaseService.acquire`, `heartbeat`, `release`, and `reap_expired`.

- [ ] **Step 1: Write path traversal tests**

Reject `../x`, `/absolute`, `a/b`, empty strings, and names longer than 100. Accept `bilibili-main_01`.

- [ ] **Step 2: Write lease exclusivity test**

Two acquisitions for the same Profile must not both succeed. After expiry/reap, acquisition succeeds.

- [ ] **Step 3: Implement and commit**

```bash
pytest tests/unit/browser tests/integration/database/test_profile_leases.py -v
ruff check src tests
mypy src
git add src/video_crawler/application/auth_profiles.py src/video_crawler/infrastructure/browser tests
git commit -m "feat: secure browser profiles with database leases"
```

### Task 9: Crawl4AI and HTTP gateways

**Files:**
- Create: `src/video_crawler/infrastructure/browser/crawl4ai_gateway.py`
- Create: `src/video_crawler/infrastructure/http/client.py`
- Create: `src/video_crawler/application/rate_limit.py`
- Create: `tests/unit/browser/test_browser_gateway.py`
- Create: `tests/unit/http/test_retry_policy.py`

**Interfaces:**
- Implements `BrowserGateway`, `NetworkCaptureGateway`, and `HttpGateway` protocols.
- Produces `RateLimiter.wait(scope, strategy)`.

- [ ] **Step 1: Write gateway contract tests with mocks**

Assert Profile path is applied, network capture is optional, timeout comes from strategy, and sensitive headers are not logged.

- [ ] **Step 2: Write retry classification tests**

Retry transient transport errors and approved upstream statuses up to `max_retries`. Do not retry authentication expiration or target resolution errors.

- [ ] **Step 3: Implement Crawl4AI behind the gateway**

No other module may import Crawl4AI directly. Ensure browser shutdown is in `async with`/`finally` and handles cancellation.

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/unit/browser tests/unit/http -v
ruff check src tests
mypy src
git add src/video_crawler/infrastructure/browser src/video_crawler/infrastructure/http src/video_crawler/application tests
git commit -m "feat: add generic Crawl4AI and HTTP gateways"
```

### Task 10: Generic crawl pipeline

**Files:**
- Create: `src/video_crawler/application/pipeline.py`
- Create: `src/video_crawler/application/module_runner.py`
- Create: `tests/unit/application/test_pipeline.py`

**Interfaces:**
- Produces `CrawlPipeline.execute(job_context) -> PipelineResult`.
- Produces module order: discovery for list targets; metrics, comments, timed_text for video targets.

- [ ] **Step 1: Write partial-failure test**

Use a fake Adapter where metrics succeeds, comments raises `UpstreamError`, and timed text succeeds. Assert successful repositories are called, comments module is failed, and final status is partial.

- [ ] **Step 2: Write resume-skip test**

Given prior module states where metrics and timed text succeeded, assert resume invokes only comments.

- [ ] **Step 3: Implement generic orchestration**

The pipeline may know module names but not platform details. Each batch is committed independently. Cancellation is checked before and after every module and each batch.

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/unit/application/test_pipeline.py -v
ruff check src tests
mypy src
git add src/video_crawler/application tests/unit/application
git commit -m "feat: implement generic modular crawl pipeline"
```

### Task 11: Worker supervisor and forced process-group cancellation

**Files:**
- Create: `src/video_crawler/worker/main.py`
- Create: `src/video_crawler/worker/supervisor.py`
- Create: `src/video_crawler/worker/task_entrypoint.py`
- Create: `src/video_crawler/infrastructure/process/groups.py`
- Create: `tests/integration/worker/test_forced_cancel.py`
- Create: `tests/unit/worker/test_supervisor.py`

**Interfaces:**
- Produces `WorkerSupervisor.run_forever()`.
- Produces `spawn_task_process(run_id) -> SupervisedProcess`.
- Produces `terminate_process_group(pgid, grace_seconds, kill_timeout_seconds)`.

- [ ] **Step 1: Write process-group test**

Launch a helper Python child that launches a sleeping grandchild. Cancel it. Assert both PIDs disappear. The test must skip on non-POSIX platforms.

- [ ] **Step 2: Write Worker state test**

Fake repositories and process handle. Assert cancel flag changes job to cancelling, calls process-group termination, then marks cancelled and releases the Profile lease.

- [ ] **Step 3: Implement supervisor**

Use `start_new_session=True` or equivalent to create a new process group. Do not use `shell=True`. Store PID/PGID in `crawl_runs`. Heartbeat both run and lease.

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/unit/worker tests/integration/worker/test_forced_cancel.py -v
ruff check src tests
mypy src
git add src/video_crawler/worker src/video_crawler/infrastructure/process tests
git commit -m "feat: supervise isolated crawl task process groups"
```

### Task 12: FastAPI job and Profile endpoints

**Files:**
- Create: `src/video_crawler/api/router.py`
- Create: `src/video_crawler/api/routes/jobs.py`
- Create: `src/video_crawler/api/routes/auth_profiles.py`
- Create: `src/video_crawler/api/schemas/jobs.py`
- Create: `src/video_crawler/api/schemas/auth_profiles.py`
- Create: `src/video_crawler/application/jobs.py`
- Create: `tests/api/test_jobs.py`
- Create: `tests/api/test_auth_profiles.py`
- Modify: `src/video_crawler/main.py`

**Interfaces:**
- Implements create/get/cancel/resume jobs and Profile CRUD-state endpoints from `docs/api-contract.md`.
- Produces `JobService.create`, `cancel`, and `resume`.

- [ ] **Step 1: Write API validation tests**

Assert `video_limit=501`, invalid delay order, unsafe Profile directory, and invalid resume state return structured errors.

- [ ] **Step 2: Write idempotency tests**

Same key and same request returns original job. Same key and different request returns `409 IDEMPOTENCY_CONFLICT`.

- [ ] **Step 3: Implement endpoints and services**

API functions only validate/translate; business transitions belong to `JobService`.

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/api/test_jobs.py tests/api/test_auth_profiles.py -v
ruff check src tests
mypy src
git add src/video_crawler/api src/video_crawler/application/jobs.py src/video_crawler/main.py tests/api
git commit -m "feat: expose manual crawl job and profile APIs"
```

### Task 13: Result query APIs and cursor pagination

**Files:**
- Create: `src/video_crawler/application/cursors.py`
- Create: `src/video_crawler/api/routes/results.py`
- Create: `src/video_crawler/api/schemas/results.py`
- Create: `tests/unit/application/test_cursors.py`
- Create: `tests/api/test_result_queries.py`

**Interfaces:**
- Produces signed/opaque cursor encode-decode functions.
- Implements metrics, latest metrics, comments, and timed-text endpoints.

- [ ] **Step 1: Write cursor tests**

Round-trip comment cursor `(published_at, id)` and timed-text cursor `(start_ms, id)`. Reject tampered and wrong-kind cursors.

- [ ] **Step 2: Write API ordering tests**

Insert more rows than page size. Assert no duplicates or gaps across pages and maximum page size is enforced.

- [ ] **Step 3: Implement keyset pagination**

Do not use deep OFFSET. Use deterministic secondary key `id`.

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/unit/application/test_cursors.py tests/api/test_result_queries.py -v
ruff check src tests
mypy src
git add src/video_crawler/application/cursors.py src/video_crawler/api tests
git commit -m "feat: add cursor-paginated result APIs"
```

### Task 14: Health and readiness

**Files:**
- Create: `src/video_crawler/api/routes/health.py`
- Create: `src/video_crawler/application/health.py`
- Create: `tests/api/test_health.py`

**Interfaces:**
- Implements `/health/live` and `/health/ready`.

- [ ] **Step 1: Write readiness degradation tests**

Mock MySQL unavailable, migration mismatch, MinIO unavailable, and missing Bucket. Assert `503` with component status. Liveness must remain `200` while process runs.

- [ ] **Step 2: Implement checks and commit**

```bash
pytest tests/api/test_health.py -v
ruff check src tests
mypy src
git add src/video_crawler/api/routes/health.py src/video_crawler/application/health.py tests/api
git commit -m "feat: add service liveness and dependency readiness"
```

### Task 15: Bilibili matcher, auth, resolver, and popular discovery

**Files:**
- Create: `src/video_crawler/adapters/bilibili/__init__.py`
- Create: `src/video_crawler/adapters/bilibili/adapter.py`
- Create: `src/video_crawler/adapters/bilibili/matcher.py`
- Create: `src/video_crawler/adapters/bilibili/auth.py`
- Create: `src/video_crawler/adapters/bilibili/resolver.py`
- Create: `src/video_crawler/adapters/bilibili/discovery.py`
- Create: `tests/fixtures/bilibili/popular_page.json`
- Create: `tests/unit/adapters/bilibili/test_discovery.py`

**Interfaces:**
- Produces registered platform key `bilibili`.
- Resolves the approved popular URL as `video_list`.
- Emits at most `strategy.video_limit` generic `DiscoveredTarget` values.

- [ ] **Step 1: Create synthetic, redacted fixture**

Fixture must include at least three entries with generic fake BV-like identifiers and no real account data.

- [ ] **Step 2: Write matcher and discovery tests**

Assert supported Bilibili URLs match, unrelated domains do not, order is preserved, duplicates are removed, and limit is enforced.

- [ ] **Step 3: Implement using only injected gateways**

Prefer stable captured JSON parsed by Adapter. DOM extraction is a fallback. Do not place endpoint paths in Core.

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/unit/adapters/bilibili/test_discovery.py -v
ruff check src tests
mypy src
git add src/video_crawler/adapters/bilibili tests/fixtures/bilibili tests/unit/adapters/bilibili
git commit -m "feat: add Bilibili target discovery adapter"
```

### Task 16: Bilibili metrics adapter

**Files:**
- Create: `src/video_crawler/adapters/bilibili/metrics.py`
- Create: `tests/fixtures/bilibili/metrics.json`
- Create: `tests/unit/adapters/bilibili/test_metrics.py`

**Interfaces:**
- Maps platform response to seven approved metric keys.

- [ ] **Step 1: Write mapping tests**

Assert values map to `standard.*` and `bilibili.coins`. Missing public fields must become `not_public` or `fetch_failed`, never zero.

- [ ] **Step 2: Implement parser and gateway request**

Store raw response through `RawArtifactGateway`. Keep raw field paths in `MetricValue.source_path`.

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/unit/adapters/bilibili/test_metrics.py -v
ruff check src tests
mypy src
git add src/video_crawler/adapters/bilibili/metrics.py tests
git commit -m "feat: map Bilibili interaction metrics"
```

### Task 17: Bilibili comments adapter

**Files:**
- Create: `src/video_crawler/adapters/bilibili/comments.py`
- Create: `src/video_crawler/adapters/bilibili/parsers/comments.py`
- Create: `tests/fixtures/bilibili/comments_root.json`
- Create: `tests/fixtures/bilibili/comments_replies.json`
- Create: `tests/unit/adapters/bilibili/test_comments.py`

**Interfaces:**
- Streams `CommentBatch` values.
- Enforces `max_root_comments` and `fetch_all_replies`.

- [ ] **Step 1: Write pagination and tree tests**

Assert root limit 0 means unlimited, limit truncates roots only, replies for selected roots are complete, parent/root platform IDs are correct, and pagination delay calls the injected limiter.

- [ ] **Step 2: Implement parser and paginator**

Archive every raw page before normalization. Check cancellation at each page and reply batch boundary.

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/unit/adapters/bilibili/test_comments.py -v
ruff check src tests
mypy src
git add src/video_crawler/adapters/bilibili/comments.py src/video_crawler/adapters/bilibili/parsers tests
git commit -m "feat: stream Bilibili comments and replies"
```

### Task 18: Bilibili danmaku and subtitle adapter

**Files:**
- Create: `src/video_crawler/adapters/bilibili/timed_text.py`
- Create: `src/video_crawler/adapters/bilibili/parsers/danmaku.py`
- Create: `src/video_crawler/adapters/bilibili/parsers/subtitles.py`
- Create: `tests/fixtures/bilibili/danmaku.bin`
- Create: `tests/fixtures/bilibili/subtitle_zh.json`
- Create: `tests/unit/adapters/bilibili/test_timed_text.py`

**Interfaces:**
- Streams generic `TimedTextBatch` values for all video units.
- Uses one stream for each danmaku source and one stream per subtitle language/track.

- [ ] **Step 1: Write parser tests**

Use synthetic fixture bytes. Assert timestamp conversion to milliseconds, attributes preservation, subtitle start/end, language, and stable dedup keys.

- [ ] **Step 2: Write batching test**

With batch size 1000 and 2501 items, assert emitted batch sizes are 1000, 1000, and 501.

- [ ] **Step 3: Implement and archive raw sources**

Do not load unbounded structured items into memory. Parse and yield incrementally where the format permits.

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/unit/adapters/bilibili/test_timed_text.py -v
ruff check src tests
mypy src
git add src/video_crawler/adapters/bilibili/timed_text.py src/video_crawler/adapters/bilibili/parsers tests
git commit -m "feat: stream Bilibili danmaku and subtitle data"
```

### Task 19: End-to-end application wiring

**Files:**
- Create: `src/video_crawler/bootstrap.py`
- Modify: `src/video_crawler/main.py`
- Modify: `src/video_crawler/worker/task_entrypoint.py`
- Modify: `src/video_crawler/worker/main.py`
- Create: `tests/integration/test_end_to_end_fake_adapter.py`

**Interfaces:**
- Produces dependency container/factories for API and Worker.
- Registers Bilibili Adapter without importing it from Domain or Core.

- [ ] **Step 1: Write fake-adapter end-to-end test**

Create a job through API, run one Worker iteration with a fake Adapter, and query metrics/comments/timed text through API. Assert MinIO raw artifact exists.

- [ ] **Step 2: Wire production dependencies**

Avoid global database sessions or browser instances. Global immutable settings and engine/client factories are allowed.

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/integration/test_end_to_end_fake_adapter.py -v
ruff check src tests
mypy src
git add src/video_crawler tests/integration
git commit -m "feat: wire API worker storage and adapters"
```

### Task 20: Raw artifact cleanup and stale-run recovery

**Files:**
- Create: `src/video_crawler/worker/maintenance.py`
- Create: `tests/integration/worker/test_maintenance.py`

**Interfaces:**
- Produces `MaintenanceService.run_once(now)`.

- [ ] **Step 1: Write cleanup tests**

Assert expired available objects are deleted and marked expired, deletion failures are marked delete_failed, structured rows remain, temporary stale objects are removed, and retention 0 skips expiry.

- [ ] **Step 2: Write stale-run recovery tests**

Assert stale running jobs become pending only when not manually cancelled and retry budget allows; otherwise failed/cancelled as appropriate. Expired leases are released.

- [ ] **Step 3: Implement and commit**

```bash
pytest tests/integration/worker/test_maintenance.py -v
ruff check src tests
mypy src
git add src/video_crawler/worker/maintenance.py tests/integration/worker
git commit -m "feat: clean raw artifacts and recover stale tasks"
```

### Task 21: Docker Compose production path and manual Profile login command

**Files:**
- Modify: `Dockerfile`
- Modify: `compose.yaml`
- Create: `src/video_crawler/cli.py`
- Create: `tests/unit/test_cli.py`
- Create: `docs/operations.md`

**Interfaces:**
- Produces `python -m video_crawler.cli login --platform bilibili --profile bilibili-main`.

- [ ] **Step 1: Verify and pin container/runtime dependencies**

Consult official Crawl4AI and browser installation documentation at implementation time. Replace `latest` image tags with immutable supported versions. Install required Chromium system packages in the Worker image.

- [ ] **Step 2: Write CLI validation test**

Reject unsafe Profile names and unknown platforms. The command must use the same mounted Profile root as Worker and must not start a Worker loop.

- [ ] **Step 3: Implement login mode and operations guide**

Document local interactive login, container login with a display method chosen by the operator, Profile verification, API startup, backup, restore, cancellation, and troubleshooting.

- [ ] **Step 4: Validate Compose**

Run:

```bash
docker compose config
docker compose build
docker compose up -d mysql minio minio-init migrate api worker
curl -fsS http://localhost:8000/health/ready
```

Expected: Compose validates, services become healthy, readiness is 200.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile compose.yaml src/video_crawler/cli.py tests/unit/test_cli.py docs/operations.md
git commit -m "ops: complete container deployment and profile login flow"
```

### Task 22: Full acceptance suite and documentation consistency

**Files:**
- Modify: `README.md`
- Modify: `docs/api-contract.md`
- Modify: `docs/architecture/database-schema.md`
- Create: `tests/acceptance/test_contracts.py`

**Interfaces:**
- Produces a release-ready `0.1.0` implementation matching all specifications.

- [ ] **Step 1: Add contract assertions**

Assert OpenAPI contains approved routes only, database migrations contain approved tables, one Worker concurrency is enforced, and Adapter-specific strings are absent from Core/Domain paths.

- [ ] **Step 2: Run complete verification**

```bash
ruff format --check src tests
ruff check src tests
mypy src
pytest --cov=video_crawler --cov-report=term-missing
alembic upgrade head
docker compose config
```

Expected: all pass and coverage is at least 85%.

- [ ] **Step 3: Perform secret and scope scans**

```bash
grep -RInE 'Cookie:|Authorization:|MINIO_SECRET_KEY=.+' src tests docs || true
grep -RInE '\b(bvid|aid|cid)\b' src/video_crawler/core src/video_crawler/domain src/video_crawler/application src/video_crawler/worker || true
```

Expected: no leaked secret values and no Bilibili-specific identifiers in generic layers.

- [ ] **Step 4: Update documentation from actual implementation**

Document exact install, migrate, login, start, create-job, cancel, resume, query, backup, and restore commands. Do not document unimplemented features.

- [ ] **Step 5: Commit**

```bash
git add README.md docs tests/acceptance
git commit -m "docs: finalize crawler acceptance and operations guide"
```

## Plan Self-Review Result

- Every approved product constraint maps to at least one implementation task.
- Core/Adapter separation is enforced by both architecture and acceptance tests.
- Forced process-group cancellation is covered by an integration test.
- MySQL, MinIO, migrations, API, Worker, Profile, idempotency, cursor pagination, cleanup, and manual resume are covered.
- Live-site access is excluded from CI.
- No frontend, user system, scheduler, multi-Worker, or extra business data is included.
