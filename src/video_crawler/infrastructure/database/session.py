from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Self

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from video_crawler.core.config import Settings, get_settings


class DatabaseSessionFactory:
    """Create short-lived async sessions for one database unit of work."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        engine: AsyncEngine | None = None,
    ) -> None:
        self.engine = engine or self._build_engine(settings or get_settings())
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _build_engine(settings: Settings) -> AsyncEngine:
        url = URL.create(
            drivername="mysql+asyncmy",
            username=settings.mysql_user,
            password=settings.mysql_password.get_secret_value(),
            host=settings.mysql_host,
            port=settings.mysql_port,
            database=settings.mysql_database,
            query={"charset": "utf8mb4"},
        )
        return create_async_engine(
            url,
            pool_size=settings.mysql_pool_size,
            max_overflow=settings.mysql_max_overflow,
            pool_pre_ping=True,
        )

    def __call__(self) -> AsyncSession:
        return self._sessions()

    def session(self) -> AsyncSession:
        return self._sessions()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        async with self._sessions() as session:
            async with session.begin():
                yield session

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.dispose()
