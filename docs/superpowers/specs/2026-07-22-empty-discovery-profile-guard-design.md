# Empty Discovery and Profile Guard Bugfix Design

Date: 2026-07-22

## Goal

Repair the Bilibili popular-page workflow that can report a successful root job while discovering no videos. The fix must also prevent inactive browser Profiles from entering or being claimed by the crawl pipeline, preserve the generic Core/Adapter boundary, and leave enough sanitized evidence to diagnose future live-site failures.

## Scope

This change covers four related behaviors:

1. reject job creation when the referenced Profile does not exist or is not `active`;
2. prevent the Worker from claiming a pending job whose Profile is not `active`;
3. make Bilibili popular discovery use bounded fallbacks and fail explicitly when all sources produce zero valid targets;
4. document the difference between UTF-8 display errors and stored data corruption.

It does not implement automatic login, CAPTCHA handling, anti-bot bypasses, scheduled retries, additional Workers, or new data collection fields.

## Profile State Enforcement

`JobService` will depend on a small application-level Profile status reader. Before reserving an idempotency key or creating a job, it will load the referenced Profile state:

- a missing Profile raises `PROFILE_NOT_FOUND`;
- an `expired` or `disabled` Profile raises `PROFILE_NOT_ACTIVE`;
- only an `active` Profile may produce a pending job.

The SQL job-claim query will independently require the joined Profile status to be `active`. This second boundary covers a Profile that becomes inactive after job creation but before Worker claim. Such a pending job remains paused and becomes claimable after the operator logs in and successfully verifies the same Profile. The Worker will not automatically authenticate or change Profile state.

The two checks are intentional defense in depth: the API provides immediate feedback for new jobs, while the claim filter protects already-persisted jobs and state races.

## Bilibili Popular Discovery

The discovery order remains entirely inside the Bilibili Adapter:

1. parse valid captured responses from the approved popular API host and path;
2. if capture does not yield candidates, wait for a bounded popular-video DOM selector and extract video links;
3. if the DOM still yields no candidates, request the public popular endpoint through the injected generic `HttpGateway` and parse its response;
4. deduplicate valid platform video identifiers, preserve order, and stop at `strategy.video_limit`.

Every network request continues to use the configured timeout, rate limiting, retry, cancellation, and redacted logging boundaries. Adapter code will not create its own HTTP client or browser and will not access SQLAlchemy or MinIO directly.

The public HTTP response used by the final fallback will be submitted through the injected Raw Artifact Gateway before parsing so a failed response can be reprocessed later. No Cookie, Authorization value, browser storage, or complete sensitive header set may be logged or stored in structured error fields.

## Empty Discovery Semantics

The Bilibili popular page is expected to contain discoverable videos. If capture, DOM, and public HTTP fallback all produce zero valid targets, the Adapter will raise a generic domain discovery error with stable code `DISCOVERY_EMPTY` and a sanitized message.

`ModuleRunner` will persist the discovery module as `failed`; the root run and root job will finish as `failed`. No successful child job is fabricated. The error details will contain only bounded diagnostic counts and source names, for example captured response count, captured candidate count, DOM candidate count, and HTTP candidate count.

The generic pipeline will not assume that every empty list is a failure. The Adapter decides by raising the generic error, matching the existing state-machine rule that an empty list may be valid for some platforms or list types.

## Diagnostics and Persistence

The fix will reuse existing module error fields and raw artifact storage rather than add a migration. Discovery failures will provide:

- stable error code `DISCOVERY_EMPTY`;
- sanitized error message;
- bounded source/count diagnostics in the error representation or structured log;
- a raw artifact reference for the public fallback response when one was received.

If the current module-state store cannot derive a stable code from a typed domain error, the implementation may add a generic error-code extraction helper without introducing Bilibili-specific logic into application, Worker, repository, or domain layers.

## UTF-8 Operations Guidance

The database and SQL export remain `utf8mb4`. The operations documentation will explain that Windows PowerShell 5.1 can misread UTF-8 files without a BOM when `Get-Content` is used without an encoding. Operators should use `Get-Content -Encoding UTF8` for SQL and Markdown inspection.

The documentation will also state that `0x...` values in Navicat exports are the expected hexadecimal representation of `BINARY(16)` UUID columns, and escaped JSON quotes are SQL string escaping rather than character corruption.

## Error Contract

The API adds one stable business error:

```json
{
  "error": {
    "code": "PROFILE_NOT_ACTIVE",
    "message": "authentication profile is not active",
    "details": {}
  }
}
```

The response status is `409 Conflict`, because the referenced Profile exists but its current state prevents job creation. `PROFILE_NOT_FOUND` remains `404`.

Discovery failure is persisted on the run/module and exposed through the existing job error response; it does not add a new public endpoint.

## Test Strategy

Implementation will follow red-green-refactor cycles with one behavior per test:

1. application/API tests prove missing and inactive Profiles reject job creation before persistence or idempotency reservation;
2. database integration tests prove pending jobs with inactive Profiles are skipped and become claimable after activation;
3. Adapter tests prove captured-response, delayed DOM, and HTTP fallback paths preserve ordering, deduplication, and `video_limit`;
4. Adapter/pipeline tests prove all-empty discovery raises `DISCOVERY_EMPTY` and produces a failed module/root result;
5. logging/error tests prove diagnostic data contains no secret header values;
6. documentation checks preserve UTF-8 text.

After targeted tests pass, run the complete test suite, Ruff formatting and lint checks, mypy, and the repository's existing architecture/secret scans. Live Bilibili access remains an explicit manual verification and is not added to CI.

## Success Criteria

- A new job cannot be created with a missing, expired, or disabled Profile.
- A pending job cannot be claimed while its Profile is inactive.
- A normal Bilibili popular response produces child video jobs up to `video_limit`.
- Zero candidates cannot produce a successful discovery module or root job.
- Failures retain sanitized, actionable evidence without exposing authentication data.
- PowerShell UTF-8 display guidance is documented without changing the correct MySQL character-set configuration.
- Core, Domain, API, Worker, and repositories remain free of Bilibili protocol details.
