# Worker-Owned Profile Verification Design

## Problem

The interactive `profile-login` container and the Worker mount the persistent browser
Profile volume, while the API container intentionally does not. The current
`POST /api/v1/auth-profiles/{profile_id}/verify` implementation starts Crawl4AI in
the API process. In Docker this always reads an empty container-local directory and
can incorrectly mark a valid login as `expired`.

Mounting the Profile volume into the API is forbidden. Verification must therefore be
executed by the single Worker, without weakening Profile isolation or introducing a
second scheduler.

## Chosen Architecture

Profile verification becomes asynchronous and database-backed:

1. The API validates that the Profile exists, marks it `expired`, and creates or
   reuses one pending verification request.
2. `POST /auth-profiles/{profile_id}/verify` returns HTTP 202 with that request.
3. The single Worker checks for a verification request before claiming a crawl job.
4. The Worker claims one request with `FOR UPDATE SKIP LOCKED`, starts a dedicated
   process group, and records its PID and heartbeat.
5. The child process uses the existing Adapter verification contract and the mounted
   persistent Profile. It writes `active` or `expired` to `auth_profiles` and marks
   the request `succeeded`.
6. Unexpected failures mark the request `failed` with a stable sanitized error while
   leaving the Profile `expired`.
7. The client polls
   `GET /auth-profiles/{profile_id}/verifications/{verification_id}` until a terminal
   request status is returned, then reads the included Profile status.

No Bilibili-specific behavior enters the API, Worker scheduler, repository, or
database model. The Adapter remains the only owner of login validation rules.

## Alternatives Rejected

### Mount the Profile volume into the API

This would preserve the synchronous endpoint but violates the explicit security rule
that the API container must not access browser state.

### Let `profile-login` update MySQL directly

This is operationally smaller, but it makes verification available only as a CLI side
effect and leaves the documented API contract misleading. It also couples an
interactive utility to database persistence.

### Run Crawl4AI in the Worker main process

This avoids a child entrypoint but violates the rule that the Worker main process only
schedules and supervises browser-owning child processes. A hung browser would also
block the only scheduler without process-group termination.

## API Contract

`POST /api/v1/auth-profiles/{profile_id}/verify` returns HTTP 202:

```json
{
  "verification_id": "uuid",
  "profile_id": "uuid",
  "status": "pending",
  "profile_status": "expired",
  "requested_at": "UTC timestamp",
  "started_at": null,
  "finished_at": null,
  "error_code": null,
  "error_message": null
}
```

`GET /api/v1/auth-profiles/{profile_id}/verifications/{verification_id}` returns the
same schema. Request statuses are `pending`, `running`, `succeeded`, and `failed`.
Profile statuses remain exactly `active`, `expired`, and `disabled`.

Repeated POST calls while a request is `pending` or `running` reuse that request.
After a terminal request, a new POST creates a new request. A request ID belonging to
another Profile returns `PROFILE_VERIFICATION_NOT_FOUND`.

New Profile records start as `expired`; only successful Worker verification or the
existing explicit `enable` endpoint can make them `active`.

## Persistence

Add `auth_profile_verifications`:

- `id BINARY(16)` primary key;
- `auth_profile_id BINARY(16)` foreign key;
- `status VARCHAR(20)`;
- `worker_id VARCHAR(100)` nullable;
- `process_pid INT` nullable;
- `process_group_id INT` nullable;
- `requested_at`, `started_at`, `heartbeat_at`, `finished_at` as `DATETIME(3)`;
- `error_code VARCHAR(100)` nullable;
- `error_message TEXT` nullable;
- index `(status, requested_at)` for claims;
- index `(auth_profile_id, requested_at)` for Profile-scoped lookup.

The API serializes request creation by locking the parent `auth_profiles` row. This
prevents duplicate live requests without relying on a partial unique index that MySQL
does not provide.

The Worker can reclaim a `running` request whose heartbeat is older than
`WORKER_STALE_AFTER_SECONDS`. Reclaim clears stale process identifiers and starts a new
child process. Request and Profile timestamps are normalized to MySQL millisecond
precision.

## Worker Lifecycle

The existing single Worker loop remains the only scheduler. Each loop iteration first
offers work to a generic auxiliary runner. The Profile verification runner claims at
most one request and fully supervises its child before crawl-job claiming resumes.
Therefore verification and crawling never run concurrently.

The verification child has a bounded runtime derived from two page loads plus process
termination grace. On timeout the supervisor sends SIGTERM to the full process group,
then SIGKILL if required, and marks the request failed with
`PROFILE_VERIFICATION_TIMEOUT`.

The Worker writes only sanitized codes and messages. Browser state, Cookie values,
authorization headers, and captured response bodies are never stored in MySQL or
logs.

## Failure Semantics

- Valid login: request `succeeded`, Profile `active`.
- Invalid login: request `succeeded`, Profile `expired`.
- Adapter/browser/database exception: request `failed`, Profile `expired`, stable
  generic error fields.
- Worker crash: stale `running` request becomes claimable after the configured stale
  interval.
- Missing Profile: API returns 404 `PROFILE_NOT_FOUND` and creates no request.
- Worker not running: request remains `pending`; API does not falsely report
  `expired` as a completed verification result.

## Testing

- API tests prove 202 responses, Profile-scoped lookup, reuse, and structured 404s.
- Database integration tests prove request creation, claim/reclaim, completion, and
  MySQL locking behavior.
- Worker unit tests prove verification priority, child supervision, heartbeat,
  timeout termination, and crawl-job exclusion while verification runs.
- Entrypoint tests prove valid, invalid, and exceptional verification outcomes.
- Migration tests upgrade an empty database to head and downgrade to base.
- Acceptance tests prove the API container still has no Profile volume while Worker
  and `profile-login` do.
- CI uses fake Adapters and gateways only; live Bilibili verification remains manual.

