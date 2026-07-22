from __future__ import annotations

import asyncio

from video_crawler.worker.supervisor import WorkerSupervisor


def run(supervisor: WorkerSupervisor) -> None:
    """Run the single configured supervisor until the process is stopped."""

    asyncio.run(supervisor.run_forever())
