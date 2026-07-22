from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Sequence
from typing import Protocol
from uuid import UUID

from video_crawler.bootstrap import ApplicationContainer


class TaskContainer(Protocol):
    async def execute_run(self, run_id: UUID) -> object: ...

    async def aclose(self) -> None: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute one isolated crawl run")
    parser.add_argument("run_id", type=UUID)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one isolated crawl run using process-local dependencies."""

    arguments = build_parser().parse_args(argv)
    return asyncio.run(run_task(arguments.run_id))


async def run_task(
    run_id: UUID,
    *,
    container_factory: Callable[[], TaskContainer] = ApplicationContainer,
) -> int:
    container = container_factory()
    try:
        result = await container.execute_run(run_id)
        status = getattr(getattr(result, "status", None), "value", None)
        return 0 if status in {"success", "partial"} else 1
    except Exception:
        return 1
    finally:
        await container.aclose()


if __name__ == "__main__":
    raise SystemExit(main())
