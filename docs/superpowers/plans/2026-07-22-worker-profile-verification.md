# Worker-Owned Profile Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` and execute inline. This repository forbids subagents, delegation, and parallel agents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Docker Profile verification execute in the only component that mounts persistent browser state while preserving the API/Profile isolation boundary.

**Architecture:** The API writes a database-backed verification request and returns HTTP 202. The single Worker prioritizes one request, supervises a dedicated verification process group, and the child uses the existing generic Adapter contract to update the Profile and request. API clients poll a Profile-scoped request endpoint for the terminal result.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, MySQL 8, Crawl4AI, pytest, Ruff, mypy, Docker Compose.

## Global Constraints

- The API container never mounts or reads browser Profile state.
- The Worker and `profile-login` remain the only containers mounting `browser_profiles`.
- Only one Worker exists and it executes verification and crawling serially.
- Crawl4AI runs in a supervised child process, never in the Worker main process.
- Request state is generic; Bilibili login rules remain in the Adapter.
- Profile status remains limited to `active`, `expired`, and `disabled`.
- No Cookie, token, captured body, or sensitive header is persisted or logged.
- Every behavior change follows RED, GREEN, focused checks, and an isolated commit.
- CI never contacts live Bilibili.

---

### Task 1: Persist Profile Verification Requests

**Files:**
- Create: `src/video_crawler/infrastructure/database/models/profile_verifications.py`
- Create: `src/video_crawler/infrastructure/database/repositories/profile_verifications.py`
- Create: `migrations/versions/0002_profile_verifications.py`
- Modify: `src/video_crawler/infrastructure/database/models/__init__.py`
- Modify: `tests/integration/database/test_migrations.py`
- Create: `tests/integration/database/test_profile_verifications.py`
- Modify: `sql/reference_schema.sql`

**Interfaces:**
- Produces `AuthProfileVerification` ORM model.
- Produces `ClaimedProfileVerification(verification_id, profile_id, profile_directory, platform)`.
- Produces `ProfileVerificationRepository.request`, `get`, `claim_next`, `record_process`, `heartbeat`, `mark_succeeded`, and `mark_failed`.

- [ ] **Step 1: Write migration and repository failure tests**

Add `auth_profile_verifications` to `EXPECTED_TABLES`. Test that `request(profile_id, now)` locks the Profile, changes it to `expired`, creates one `pending` request, and reuses it on a second call. Test that terminal requests allow a new request.

Test `claim_next(worker_id, now, stale_before)` for:

```python
assert claimed.verification_id == request_id
assert claimed.profile_directory == "bilibili-main"
assert row.status == "running"
assert row.worker_id == "worker-1"
```

Also prove a stale `running` row is reclaimed and a fresh `running` row is not.

- [ ] **Step 2: Run tests and verify RED**

```powershell
uv run pytest tests/integration/database/test_profile_verifications.py tests/integration/database/test_migrations.py -q
```

Expected: collection or assertion failure because the model, migration, repository, and table do not exist.

- [ ] **Step 3: Add the migration and ORM model**

Create revision `0002_profile_verifications` with `down_revision = "0001_initial_schema"`. Use `BINARY(16)` UUIDs, `DATETIME(3)`, the exact columns and indexes in the design, and `ON DELETE RESTRICT` semantics. Downgrade drops indexes then the table.

- [ ] **Step 4: Implement transactional request and claim operations**

`request` must lock `AuthProfile` by primary key, return `None` for a missing Profile, reuse the newest `pending/running` row, otherwise insert a UUID request, and set the Profile to `expired` in the same transaction.

`claim_next` must select only `pending` or stale `running` candidates, order by `requested_at`, use `FOR UPDATE SKIP LOCKED`, set Worker/timestamps, clear stale process identifiers, and return the joined platform/profile data.

Completion methods must update only a matching `running` row. `mark_succeeded` updates the Profile and request atomically; `mark_failed` forces the Profile to `expired` and stores only caller-supplied safe code/message.

- [ ] **Step 5: Run database tests and verify GREEN**

```powershell
uv run pytest tests/integration/database/test_profile_verifications.py tests/integration/database/test_migrations.py -q
uv run ruff check src/video_crawler/infrastructure/database tests/integration/database/test_profile_verifications.py tests/integration/database/test_migrations.py
uv run mypy src/video_crawler/infrastructure/database
```

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- migrations/versions/0002_profile_verifications.py sql/reference_schema.sql src/video_crawler/infrastructure/database tests/integration/database/test_migrations.py tests/integration/database/test_profile_verifications.py
git commit -m "feat: persist profile verification requests"
```

### Task 2: Expose Asynchronous Verification API

**Files:**
- Modify: `src/video_crawler/api/schemas/auth_profiles.py`
- Modify: `src/video_crawler/api/routes/auth_profiles.py`
- Modify: `src/video_crawler/bootstrap.py`
- Modify: `tests/api/test_auth_profiles.py`
- Create: `tests/integration/database/test_auth_profile_operations.py`

**Interfaces:**
- Produces `AuthProfileVerificationResponse` with request state and current Profile status.
- Changes `POST /auth-profiles/{profile_id}/verify` to HTTP 202.
- Produces `GET /auth-profiles/{profile_id}/verifications/{verification_id}`.

- [ ] **Step 1: Write failing API tests**

Change the fake service contract from `verify` to:

```python
async def request_verification(self, profile_id: UUID) -> AuthProfileVerificationResponse | None: ...
async def get_verification(self, profile_id: UUID, verification_id: UUID) -> AuthProfileVerificationResponse | None: ...
```

Assert POST returns 202 and `status == "pending"`. Assert GET returns the same request. Assert missing Profiles use `PROFILE_NOT_FOUND` and mismatched request IDs use `PROFILE_VERIFICATION_NOT_FOUND`.

Add a database-backed test proving new Profiles start `expired`, repeated POST operations reuse live requests, and no browser gateway is invoked in the API path.

- [ ] **Step 2: Run tests and verify RED**

```powershell
uv run pytest tests/api/test_auth_profiles.py tests/integration/database/test_auth_profile_operations.py -q
```

Expected: failures because the response schema and service methods are absent and POST still runs live verification.

- [ ] **Step 3: Implement the schema and routes**

Use request status literals `pending`, `running`, `succeeded`, and `failed`. Include `profile_status`, timestamps, and optional safe error fields. Return HTTP 202 from POST and HTTP 200 from GET.

- [ ] **Step 4: Rewire `_AuthProfileOperations`**

Inject `ProfileVerificationRepository`. Remove live browser execution from the POST call. Convert repository rows to the response schema. Create Profiles as `expired`, not `active`.

Keep `ApplicationContainer.verify_profile(profile)` as a Worker-child-only primitive; it must no longer be reachable from API request handling.

- [ ] **Step 5: Run API tests and verify GREEN**

```powershell
uv run pytest tests/api/test_auth_profiles.py tests/integration/database/test_auth_profile_operations.py tests/api/test_jobs.py -q
uv run ruff check src/video_crawler/api src/video_crawler/bootstrap.py tests/api/test_auth_profiles.py tests/integration/database/test_auth_profile_operations.py
uv run mypy src/video_crawler/api src/video_crawler/bootstrap.py
```

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- src/video_crawler/api src/video_crawler/bootstrap.py tests/api/test_auth_profiles.py tests/integration/database/test_auth_profile_operations.py
git commit -m "feat: queue profile verification from api"
```

### Task 3: Execute Verification in a Supervised Worker Child

**Files:**
- Create: `src/video_crawler/worker/profile_verification.py`
- Create: `src/video_crawler/worker/profile_verification_entrypoint.py`
- Modify: `src/video_crawler/infrastructure/process/groups.py`
- Modify: `src/video_crawler/worker/supervisor.py`
- Modify: `src/video_crawler/worker/main.py`
- Modify: `src/video_crawler/bootstrap.py`
- Create: `tests/unit/worker/test_profile_verification.py`
- Create: `tests/unit/worker/test_profile_verification_entrypoint.py`
- Modify: `tests/unit/worker/test_supervisor.py`
- Modify: `tests/unit/test_worker_main.py`

**Interfaces:**
- Produces `ProfileVerificationRunner.run_once() -> bool`.
- Produces `spawn_profile_verification_process(verification_id) -> SupervisedProcess`.
- Produces `ApplicationContainer.execute_profile_verification(verification_id)`.
- Adds an optional generic `auxiliary_runner` to `WorkerSupervisor`.

- [ ] **Step 1: Write failing runner tests**

Test that a claimed request spawns a child, records PID/group, heartbeats while running, and finishes without claiming a crawl job in the same iteration. Test nonzero exit uses `PROFILE_VERIFICATION_PROCESS_FAILED`. Test elapsed timeout terminates the full group and uses `PROFILE_VERIFICATION_TIMEOUT`.

- [ ] **Step 2: Write failing entrypoint tests**

Use a fake container to assert the request UUID is parsed, execution is called once, resources close, success returns 0, and exceptions return 1 without exposing exception text.

- [ ] **Step 3: Run tests and verify RED**

```powershell
uv run pytest tests/unit/worker/test_profile_verification.py tests/unit/worker/test_profile_verification_entrypoint.py tests/unit/worker/test_supervisor.py tests/unit/test_worker_main.py -q
```

Expected: import and behavior failures because the runner and entrypoint do not exist.

- [ ] **Step 4: Implement the generic auxiliary scheduling hook**

Before crawl claiming, `WorkerSupervisor.run_once` calls `auxiliary_runner.run_once()`. If it returns true, return true immediately. Existing crawl behavior remains unchanged when no runner is configured.

- [ ] **Step 5: Implement process supervision and child execution**

The runner claims one request, spawns the fixed module entrypoint with `shell=False` and `start_new_session=True`, records process data, heartbeats at the configured interval, and terminates the process group on timeout.

`ApplicationContainer.execute_profile_verification` loads the claimed Profile, invokes the existing Adapter verification primitive, and atomically completes the request as `active` or `expired`. Sanitized unexpected failures use `PROFILE_VERIFICATION_FAILED` and `Profile verification failed`.

- [ ] **Step 6: Wire production Worker startup**

Construct one `ProfileVerificationRunner` from the shared repository/settings and pass it to the only `WorkerSupervisor`. Derive timeout as `2 * default_page_timeout_seconds + task_terminate_grace_seconds + task_kill_timeout_seconds`.

- [ ] **Step 7: Run Worker tests and verify GREEN**

```powershell
uv run pytest tests/unit/worker tests/unit/test_worker_main.py tests/integration/worker -q
uv run ruff check src/video_crawler/worker src/video_crawler/infrastructure/process/groups.py src/video_crawler/bootstrap.py tests/unit/worker tests/unit/test_worker_main.py
uv run mypy src/video_crawler/worker src/video_crawler/infrastructure/process/groups.py src/video_crawler/bootstrap.py
```

- [ ] **Step 8: Commit Task 3**

```powershell
git add -- src/video_crawler/worker src/video_crawler/infrastructure/process/groups.py src/video_crawler/bootstrap.py tests/unit/worker tests/unit/test_worker_main.py
git commit -m "feat: verify profiles in worker subprocesses"
```

### Task 4: Document the Asynchronous Operator Flow

**Files:**
- Modify: `README.md`
- Modify: `docs/api-contract.md`
- Modify: `docs/operations.md`
- Modify: `docs/architecture/database-schema.md`
- Modify: `tests/acceptance/test_contracts.py`

**Interfaces:**
- Documents HTTP 202, polling, Worker requirement, stable errors, migration, and Docker volume ownership.

- [ ] **Step 1: Write failing acceptance assertions**

Assert documentation contains `auth_profile_verifications`, `PROFILE_VERIFICATION_NOT_FOUND`, HTTP `202`, the polling route, and an explicit statement that verification stays pending while Worker is stopped.

- [ ] **Step 2: Run acceptance tests and verify RED**

```powershell
uv run pytest tests/acceptance/test_contracts.py -q
```

- [ ] **Step 3: Update documentation and PowerShell examples**

Examples must capture the POST response as `$verification`, poll the request endpoint until `succeeded/failed`, then require `profile_status -eq 'active'`. State that API never mounts Profile state and that `docker compose up -d ... worker` is mandatory.

- [ ] **Step 4: Run acceptance tests and verify GREEN**

```powershell
uv run pytest tests/acceptance/test_contracts.py -q
git diff --check
```

- [ ] **Step 5: Commit Task 4**

```powershell
git add -- README.md docs/api-contract.md docs/operations.md docs/architecture/database-schema.md tests/acceptance/test_contracts.py
git commit -m "docs: explain worker profile verification"
```

### Task 5: Complete Automated Verification and Docker Handoff

**Files:**
- Verify only.

- [ ] **Step 1: Run targeted tests**

```powershell
uv run pytest tests/api/test_auth_profiles.py tests/api/test_jobs.py tests/integration/database/test_profile_verifications.py tests/integration/database/test_auth_profile_operations.py tests/integration/database/test_migrations.py tests/unit/worker tests/unit/test_worker_main.py tests/acceptance/test_contracts.py -q
```

- [ ] **Step 2: Run the complete suite and quality gates**

```powershell
uv run pytest -q
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src
git diff --check
```

- [ ] **Step 3: Verify architecture and secret boundaries**

Confirm `compose.yaml` mounts `browser_profiles` only into Worker and `profile-login`. Scan Core/Domain/Application/Worker for Bilibili identifiers and production sources for secret-shaped values. Confirm the worktree is clean.

- [ ] **Step 4: Hand off live Docker validation**

The operator rebuilds API/Worker, runs migration `0002_profile_verifications`, starts Worker, submits verification, polls to `succeeded`, confirms `profile_status=active`, then creates a fresh crawl job. No live login, destructive Docker cleanup, or Bilibili network smoke runs in CI.

## Plan Self-Review Result

- Every design requirement maps to a task and a RED/GREEN cycle.
- Request/model/status names are consistent across migration, repository, API, Worker, and docs.
- The plan does not mount Profile state into the API or run Crawl4AI in the Worker main process.
- The plan introduces no site-specific logic outside the Adapter.
- No placeholders or delegated work remain.

