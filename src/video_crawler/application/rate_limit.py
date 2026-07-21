from __future__ import annotations

import asyncio
import random
from collections import defaultdict
from collections.abc import Callable

from video_crawler.domain.strategy import CrawlStrategy


class RateLimiter:
    """Serialize requests per scope and apply the strategy's delay window."""

    def __init__(self, *, random_fn: Callable[[float, float], float] = random.uniform) -> None:
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._random = random_fn

    async def wait(self, scope: str, strategy: CrawlStrategy) -> None:
        if scope in {"comment", "comment_page"}:
            minimum = strategy.comment_page_delay_min_seconds
            maximum = strategy.comment_page_delay_max_seconds
        elif scope in {"request", "video", "video_page"}:
            minimum = strategy.video_delay_min_seconds
            maximum = strategy.video_delay_max_seconds
        else:
            return
        async with self._locks[scope]:
            await asyncio.sleep(self._random(minimum, maximum))
