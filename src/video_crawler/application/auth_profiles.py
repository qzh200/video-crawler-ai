from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from video_crawler.infrastructure.database.models import AuthProfileLease
from video_crawler.infrastructure.database.session import DatabaseSessionFactory


class ProfileLeaseService:
    """Manage exclusive database-backed browser Profile leases."""

    def __init__(
        self,
        sessions: DatabaseSessionFactory,
        *,
        lease_ttl: timedelta,
    ) -> None:
        if lease_ttl <= timedelta(0):
            raise ValueError("lease TTL must be positive")
        self.sessions = sessions
        self.lease_ttl = lease_ttl

    async def acquire(
        self,
        auth_profile_id: UUID,
        worker_id: str,
        crawl_run_id: UUID,
        now: datetime,
        *,
        process_pid: int | None = None,
        session: AsyncSession | None = None,
    ) -> bool:
        if session is not None:
            return await self._acquire(
                session,
                auth_profile_id,
                worker_id,
                crawl_run_id,
                now,
                process_pid,
            )
        async with self.sessions.transaction() as owned_session:
            return await self._acquire(
                owned_session,
                auth_profile_id,
                worker_id,
                crawl_run_id,
                now,
                process_pid,
            )

    async def _acquire(
        self,
        session: AsyncSession,
        auth_profile_id: UUID,
        worker_id: str,
        crawl_run_id: UUID,
        now: datetime,
        process_pid: int | None,
    ) -> bool:
        now = self._to_database_precision(now)
        lease = AuthProfileLease(
            auth_profile_id=auth_profile_id,
            worker_id=worker_id,
            crawl_run_id=crawl_run_id,
            process_pid=process_pid,
            acquired_at=now,
            heartbeat_at=now,
            expires_at=now + self.lease_ttl,
        )
        try:
            async with session.begin_nested():
                session.add(lease)
                await session.flush()
        except IntegrityError as exc:
            if self._is_duplicate_key(exc):
                return False
            raise
        return True

    async def heartbeat(
        self,
        auth_profile_id: UUID,
        crawl_run_id: UUID,
        now: datetime,
        *,
        process_pid: int | None = None,
        session: AsyncSession | None = None,
    ) -> bool:
        if session is not None:
            return await self._heartbeat(session, auth_profile_id, crawl_run_id, now, process_pid)
        async with self.sessions.transaction() as owned_session:
            return await self._heartbeat(
                owned_session, auth_profile_id, crawl_run_id, now, process_pid
            )

    async def _heartbeat(
        self,
        session: AsyncSession,
        auth_profile_id: UUID,
        crawl_run_id: UUID,
        now: datetime,
        process_pid: int | None,
    ) -> bool:
        now = self._to_database_precision(now)
        values: dict[str, object] = {
            "heartbeat_at": now,
            "expires_at": now + self.lease_ttl,
        }
        if process_pid is not None:
            values["process_pid"] = process_pid
        result = cast(
            CursorResult[Any],
            await session.execute(
                update(AuthProfileLease)
                .where(
                    AuthProfileLease.auth_profile_id == auth_profile_id,
                    AuthProfileLease.crawl_run_id == crawl_run_id,
                )
                .values(**values)
            ),
        )
        return result.rowcount == 1

    async def release(
        self,
        auth_profile_id: UUID,
        crawl_run_id: UUID,
        *,
        session: AsyncSession | None = None,
    ) -> bool:
        if session is not None:
            return await self._release(session, auth_profile_id, crawl_run_id)
        async with self.sessions.transaction() as owned_session:
            return await self._release(owned_session, auth_profile_id, crawl_run_id)

    @staticmethod
    async def _release(
        session: AsyncSession,
        auth_profile_id: UUID,
        crawl_run_id: UUID,
    ) -> bool:
        result = cast(
            CursorResult[Any],
            await session.execute(
                delete(AuthProfileLease).where(
                    AuthProfileLease.auth_profile_id == auth_profile_id,
                    AuthProfileLease.crawl_run_id == crawl_run_id,
                )
            ),
        )
        return result.rowcount == 1

    async def reap_expired(
        self,
        now: datetime,
        *,
        session: AsyncSession | None = None,
    ) -> int:
        if session is not None:
            return await self._reap_expired(session, now)
        async with self.sessions.transaction() as owned_session:
            return await self._reap_expired(owned_session, now)

    @staticmethod
    async def _reap_expired(session: AsyncSession, now: datetime) -> int:
        now = ProfileLeaseService._to_database_precision(now)
        result = cast(
            CursorResult[Any],
            await session.execute(
                delete(AuthProfileLease).where(AuthProfileLease.expires_at <= now)
            ),
        )
        return result.rowcount

    @staticmethod
    def _is_duplicate_key(exc: IntegrityError) -> bool:
        original = exc.orig
        args = cast(tuple[object, ...], getattr(original, "args", ()))
        return bool(args) and args[0] == 1062

    @staticmethod
    def _to_database_precision(value: datetime) -> datetime:
        return value.replace(microsecond=(value.microsecond // 1000) * 1000)
