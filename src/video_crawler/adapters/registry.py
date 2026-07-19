from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from video_crawler.domain.errors import AdapterNotFoundError


class AdapterMatcher(Protocol):
    platform_key: str

    def match(self, url: str) -> bool: ...


class AdapterRegistry[AdapterT: AdapterMatcher]:
    def __init__(self, adapters: Iterable[AdapterT] = ()) -> None:
        self._adapters: dict[str, AdapterT] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: AdapterT) -> None:
        if adapter.platform_key in self._adapters:
            raise ValueError(f"duplicate adapter platform_key: {adapter.platform_key}")
        self._adapters[adapter.platform_key] = adapter

    def resolve(self, url: str) -> AdapterT:
        for adapter in self._adapters.values():
            if adapter.match(url):
                return adapter
        raise AdapterNotFoundError(url)
