from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Sequence
from typing import Protocol
from uuid import UUID

from video_crawler.bootstrap import ApplicationContainer


class VerificationContainer(Protocol):
    async def execute_profile_verification(self, verification_id: UUID) -> None: ...

    async def aclose(self) -> None: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute one Profile verification")
    parser.add_argument("verification_id", type=UUID)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return asyncio.run(run_verification(arguments.verification_id))


async def run_verification(
    verification_id: UUID,
    *,
    container_factory: Callable[[], VerificationContainer] = ApplicationContainer,
) -> int:
    container = container_factory()
    try:
        await container.execute_profile_verification(verification_id)
        return 0
    except Exception:
        return 1
    finally:
        await container.aclose()


if __name__ == "__main__":
    raise SystemExit(main())
