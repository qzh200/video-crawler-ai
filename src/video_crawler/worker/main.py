from __future__ import annotations

import asyncio
from collections.abc import Callable

from video_crawler.bootstrap import ApplicationContainer
from video_crawler.worker.supervisor import WorkerSupervisor


def run(supervisor: WorkerSupervisor) -> None:
    """Run the single configured supervisor until the process is stopped."""

    asyncio.run(supervisor.run_forever())


async def run_production(
    container_factory: Callable[[], ApplicationContainer] = ApplicationContainer,
) -> None:
    container = container_factory()
    try:
        await container.create_supervisor().run_forever()
    finally:
        await container.aclose()


def main() -> None:
    asyncio.run(run_production())


if __name__ == "__main__":
    main()
