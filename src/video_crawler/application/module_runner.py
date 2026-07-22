from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from video_crawler.application.gateways import CancellationToken
from video_crawler.domain.errors import CancellationRequestedError


class ModuleStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class ModuleStateStore(Protocol):
    async def mark_running(self, module_key: str) -> None: ...

    async def mark_success(self, module_key: str) -> None: ...

    async def mark_failed(self, module_key: str, error: Exception) -> None: ...

    async def mark_cancelled(self, module_key: str, error: BaseException) -> None: ...

    async def mark_skipped(self, module_key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ModuleResult:
    module_key: str
    status: ModuleStatus
    error: Exception | None = None


class ModuleRunner:
    def __init__(self, state_store: ModuleStateStore) -> None:
        self._state_store = state_store

    async def run(
        self,
        module_key: str,
        operation: Callable[[], Awaitable[None]],
        cancellation: CancellationToken,
    ) -> ModuleResult:
        cancellation.raise_if_cancelled()
        await self._state_store.mark_running(module_key)
        try:
            await operation()
            cancellation.raise_if_cancelled()
        except (CancellationRequestedError, asyncio.CancelledError) as error:
            await self._state_store.mark_cancelled(module_key, error)
            raise
        except Exception as error:
            await self._state_store.mark_failed(module_key, error)
            return ModuleResult(module_key, ModuleStatus.FAILED, error)
        await self._state_store.mark_success(module_key)
        cancellation.raise_if_cancelled()
        return ModuleResult(module_key, ModuleStatus.SUCCESS)

    async def skip(self, module_key: str, cancellation: CancellationToken) -> ModuleResult:
        cancellation.raise_if_cancelled()
        await self._state_store.mark_skipped(module_key)
        cancellation.raise_if_cancelled()
        return ModuleResult(module_key, ModuleStatus.SKIPPED)
