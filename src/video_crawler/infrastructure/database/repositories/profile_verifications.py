from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult

from video_crawler.infrastructure.database.models import (
    AuthProfile,
    AuthProfileVerification,
    Platform,
)
from video_crawler.infrastructure.database.session import DatabaseSessionFactory


@dataclass(frozen=True, slots=True)
class ProfileVerificationRecord:
    verification_id: UUID
    profile_id: UUID
    status: str
    profile_status: str
    worker_id: str | None
    requested_at: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class ClaimedProfileVerification:
    verification_id: UUID
    profile_id: UUID
    platform: str
    profile_directory: str
    worker_id: str


class ProfileVerificationRepository:
    def __init__(self, sessions: DatabaseSessionFactory) -> None:
        self.sessions = sessions

    async def request(
        self,
        profile_id: UUID,
        now: datetime,
    ) -> ProfileVerificationRecord | None:
        current = _db_time(now)
        async with self.sessions.transaction() as session:
            profile = (
                await session.execute(
                    select(AuthProfile)
                    .where(AuthProfile.id == profile_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if profile is None:
                return None
            profile.status = "expired"
            profile.updated_at = current
            verification = (
                await session.execute(
                    select(AuthProfileVerification)
                    .where(
                        AuthProfileVerification.auth_profile_id == profile_id,
                        AuthProfileVerification.status.in_(("pending", "running")),
                    )
                    .order_by(AuthProfileVerification.requested_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if verification is None:
                verification = AuthProfileVerification(
                    id=uuid4(),
                    auth_profile_id=profile_id,
                    status="pending",
                    requested_at=current,
                )
                session.add(verification)
                await session.flush()
            return _record(verification, profile.status)

    async def get(
        self,
        profile_id: UUID,
        verification_id: UUID,
    ) -> ProfileVerificationRecord | None:
        async with self.sessions() as session:
            row = (
                await session.execute(
                    select(AuthProfileVerification, AuthProfile.status)
                    .join(AuthProfile, AuthProfileVerification.auth_profile_id == AuthProfile.id)
                    .where(
                        AuthProfileVerification.id == verification_id,
                        AuthProfileVerification.auth_profile_id == profile_id,
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        return _record(row[0], row[1])

    async def claim_next(
        self,
        worker_id: str,
        now: datetime,
        *,
        stale_before: datetime,
    ) -> ClaimedProfileVerification | None:
        current = _db_time(now)
        stale = _db_time(stale_before)
        async with self.sessions.transaction() as session:
            row = (
                await session.execute(
                    select(AuthProfileVerification, AuthProfile, Platform)
                    .join(
                        AuthProfile,
                        AuthProfileVerification.auth_profile_id == AuthProfile.id,
                    )
                    .join(Platform, AuthProfile.platform_id == Platform.id)
                    .where(
                        or_(
                            AuthProfileVerification.status == "pending",
                            (
                                (AuthProfileVerification.status == "running")
                                & or_(
                                    AuthProfileVerification.heartbeat_at.is_(None),
                                    AuthProfileVerification.heartbeat_at <= stale,
                                )
                            ),
                        )
                    )
                    .order_by(AuthProfileVerification.requested_at.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).one_or_none()
            if row is None:
                return None
            verification, profile, platform = row
            verification.status = "running"
            verification.worker_id = worker_id
            verification.process_pid = None
            verification.process_group_id = None
            verification.started_at = current
            verification.heartbeat_at = current
            verification.finished_at = None
            verification.error_code = None
            verification.error_message = None
            return ClaimedProfileVerification(
                verification_id=verification.id,
                profile_id=profile.id,
                platform=platform.platform_key,
                profile_directory=profile.profile_directory,
                worker_id=worker_id,
            )

    async def record_process(
        self,
        verification_id: UUID,
        pid: int,
        process_group_id: int,
        now: datetime,
    ) -> bool:
        return await self._update_running(
            verification_id,
            process_pid=pid,
            process_group_id=process_group_id,
            heartbeat_at=_db_time(now),
        )

    async def heartbeat(self, verification_id: UUID, now: datetime) -> bool:
        return await self._update_running(
            verification_id,
            heartbeat_at=_db_time(now),
        )

    async def mark_succeeded(
        self,
        verification_id: UUID,
        *,
        is_valid: bool,
        now: datetime,
    ) -> bool:
        current = _db_time(now)
        async with self.sessions.transaction() as session:
            verification = await session.get(
                AuthProfileVerification,
                verification_id,
                with_for_update=True,
            )
            if verification is None or verification.status != "running":
                return False
            profile = await session.get(
                AuthProfile,
                verification.auth_profile_id,
                with_for_update=True,
            )
            if profile is None:
                return False
            profile.status = "active" if is_valid else "expired"
            profile.last_verified_at = current
            profile.updated_at = current
            verification.status = "succeeded"
            verification.heartbeat_at = current
            verification.finished_at = current
            verification.error_code = None
            verification.error_message = None
            return True

    async def mark_failed(
        self,
        verification_id: UUID,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> bool:
        current = _db_time(now)
        async with self.sessions.transaction() as session:
            verification = await session.get(
                AuthProfileVerification,
                verification_id,
                with_for_update=True,
            )
            if verification is None or verification.status != "running":
                return False
            profile = await session.get(
                AuthProfile,
                verification.auth_profile_id,
                with_for_update=True,
            )
            if profile is not None:
                profile.status = "expired"
                profile.updated_at = current
            verification.status = "failed"
            verification.heartbeat_at = current
            verification.finished_at = current
            verification.error_code = error_code
            verification.error_message = error_message
            return True

    async def _update_running(self, verification_id: UUID, **values: object) -> bool:
        async with self.sessions.transaction() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(AuthProfileVerification)
                    .where(
                        AuthProfileVerification.id == verification_id,
                        AuthProfileVerification.status == "running",
                    )
                    .values(**values)
                ),
            )
        return bool(result.rowcount)


def _record(
    verification: AuthProfileVerification,
    profile_status: str,
) -> ProfileVerificationRecord:
    return ProfileVerificationRecord(
        verification_id=verification.id,
        profile_id=verification.auth_profile_id,
        status=verification.status,
        profile_status=profile_status,
        worker_id=verification.worker_id,
        requested_at=_required_api_time(verification.requested_at),
        started_at=_api_time(verification.started_at),
        heartbeat_at=_api_time(verification.heartbeat_at),
        finished_at=_api_time(verification.finished_at),
        error_code=verification.error_code,
        error_message=verification.error_message,
    )


def _db_time(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def _api_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_api_time(value: datetime) -> datetime:
    converted = _api_time(value)
    if converted is None:
        raise ValueError("required database timestamp was null")
    return converted
