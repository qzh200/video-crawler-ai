import pytest

from video_crawler.adapters.registry import AdapterRegistry
from video_crawler.domain.errors import AdapterNotFoundError


class ExampleAdapter:
    platform_key = "example"

    def match(self, url: str) -> bool:
        return url.startswith("https://example.test/")


class DuplicateExampleAdapter:
    platform_key = "example"

    def match(self, url: str) -> bool:
        return False


def test_registry_resolves_matching_adapter() -> None:
    registry = AdapterRegistry([ExampleAdapter()])
    assert registry.resolve("https://example.test/v/1").platform_key == "example"


def test_registry_rejects_unknown_url() -> None:
    registry = AdapterRegistry([ExampleAdapter()])
    with pytest.raises(AdapterNotFoundError) as captured:
        registry.resolve("https://unknown.test/v/1")
    assert captured.value.url == "https://unknown.test/v/1"


def test_registry_rejects_duplicate_platform_keys_at_construction() -> None:
    with pytest.raises(ValueError, match="duplicate adapter platform_key: example"):
        AdapterRegistry([ExampleAdapter(), DuplicateExampleAdapter()])


def test_registry_registers_adapter_after_construction() -> None:
    registry = AdapterRegistry()

    registry.register(ExampleAdapter())

    assert registry.resolve("https://example.test/v/1").platform_key == "example"


def test_registry_rejects_duplicate_platform_key_on_register() -> None:
    registry = AdapterRegistry([ExampleAdapter()])

    with pytest.raises(ValueError, match="duplicate adapter platform_key: example"):
        registry.register(DuplicateExampleAdapter())
