from __future__ import annotations

import argparse
from collections.abc import Sequence
from uuid import UUID


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute one isolated crawl run")
    parser.add_argument("run_id", type=UUID)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the run identity; Task 19 supplies the application dependency wiring."""

    build_parser().parse_args(argv)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
