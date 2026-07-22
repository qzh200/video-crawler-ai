from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Protocol
from uuid import UUID, uuid4

from video_crawler.domain.strategy import CrawlStrategy


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: UUID
    auth_profile_id: UUID
    source_url: str
    status: str
    strategy_version: int
    effective_strategy: dict[str, object]
    root_job_id: UUID
    parent_job_id: UUID | None
    created_at: datetime
    updated_at: datetime
    cancel_requested: bool = False
    cancel_requested_at: datetime | None = None
    cancelled_at: datetime | None = None
    progress: dict[str, object] = field(default_factory=dict)
    module_states: dict[str, str] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class IdempotencyReservation:
    key: str
    request_hash: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class JobCreateResult:
    record: JobRecord
    created: bool


class JobStore(Protocol):
    async def create(
        self,
        record: JobRecord,
        reservation: IdempotencyReservation | None,
    ) -> JobCreateResult: ...

    async def get(self, job_id: UUID) -> JobRecord | None: ...

    async def save(
        self,
        record: JobRecord,
        *,
        reset_incomplete_modules: bool = False,
    ) -> JobRecord: ...


class ProfileStateReader(Protocol):
    async def get_status(self, profile_id: UUID) -> str | None: ...


class JobServiceError(Exception):
    code = "JOB_ERROR"
    message = "crawl job operation failed"
    status_code = 400

    def __init__(self) -> None:
        super().__init__(self.message)


class IdempotencyConflictError(JobServiceError):
    code = "IDEMPOTENCY_CONFLICT"
    message = "idempotency key was already used for a different request"
    status_code = 409


class JobNotFoundError(JobServiceError):
    code = "JOB_NOT_FOUND"
    message = "crawl job was not found"
    status_code = 404


class JobNotCancellableError(JobServiceError):
    code = "JOB_NOT_CANCELLABLE"
    message = "crawl job cannot be cancelled from its current state"
    status_code = 409


class JobNotResumableError(JobServiceError):
    code = "JOB_NOT_RESUMABLE"
    message = "crawl job cannot be resumed from its current state"
    status_code = 409


class ProfileNotFoundError(JobServiceError):
    code = "PROFILE_NOT_FOUND"
    message = "authentication profile was not found"
    status_code = 404


class ProfileNotActiveError(JobServiceError):
    code = "PROFILE_NOT_ACTIVE"
    message = "authentication profile is not active"
    status_code = 409


class JobService:
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
        if idempotency_ttl <= timedelta(0):
            raise ValueError("idempotency TTL must be positive")
        self._store = store
        self._profile_states = profile_states
        self._default_strategy = default_strategy
        self._idempotency_ttl = idempotency_ttl
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory

    async def create(
        self,
        *,
        source_url: str,
        auth_profile_id: UUID,
        video_limit: int | None,
        strategy_overrides: Mapping[str, object],
        idempotency_key: str | None,
    ) -> JobCreateResult:
        profile_status = await self._profile_states.get_status(auth_profile_id)
        if profile_status is None:
            raise ProfileNotFoundError
        if profile_status != "active":
            raise ProfileNotActiveError
        overrides = dict(strategy_overrides)
        if video_limit is not None:
            overrides["video_limit"] = video_limit
        strategy = self._default_strategy.merge(overrides)
        effective_strategy = asdict(strategy)
        now = self._clock()
        job_id = self._id_factory()
        record = JobRecord(
            id=job_id,
            auth_profile_id=auth_profile_id,
            source_url=source_url,
            status="pending",
            strategy_version=1,
            effective_strategy=effective_strategy,
            root_job_id=job_id,
            parent_job_id=None,
            created_at=now,
            updated_at=now,
        )
        reservation = None
        if idempotency_key is not None:
            reservation = IdempotencyReservation(
                key=idempotency_key,
                request_hash=_request_hash(source_url, auth_profile_id, effective_strategy),
                created_at=now,
                expires_at=now + self._idempotency_ttl,
            )
        return await self._store.create(record, reservation)

    async def get(self, job_id: UUID) -> JobRecord:
        record = await self._store.get(job_id)
        if record is None:
            raise JobNotFoundError
        return record

    async def cancel(self, job_id: UUID) -> JobRecord:
        record = await self.get(job_id)
        now = self._clock()
        if record.status == "pending":
            updated = replace(
                record,
                status="cancelled",
                cancel_requested=True,
                cancel_requested_at=now,
                cancelled_at=now,
                updated_at=now,
            )
        elif record.status == "running":
            updated = replace(
                record,
                status="cancelling",
                cancel_requested=True,
                cancel_requested_at=now,
                updated_at=now,
            )
        else:
            raise JobNotCancellableError
        return await self._store.save(updated)

    async def resume(
        self,
        job_id: UUID,
        strategy_overrides: Mapping[str, object],
    ) -> JobRecord:
        record = await self.get(job_id)
        if record.status not in {"partial", "failed", "cancelled"}:
            raise JobNotResumableError
        strategy = self._default_strategy.merge(record.effective_strategy).merge(strategy_overrides)
        now = self._clock()
        updated = replace(
            record,
            status="pending",
            effective_strategy=asdict(strategy),
            cancel_requested=False,
            cancel_requested_at=None,
            cancelled_at=None,
            updated_at=now,
        )
        return await self._store.save(updated, reset_incomplete_modules=True)


def _request_hash(
    source_url: str,
    auth_profile_id: UUID,
    effective_strategy: Mapping[str, object],
) -> str:
    payload = {
        "source_url": source_url,
        "auth_profile_id": str(auth_profile_id),
        "effective_strategy": effective_strategy,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(serialized.encode()).hexdigest()
