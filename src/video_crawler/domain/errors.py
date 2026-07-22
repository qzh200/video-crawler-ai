from collections.abc import Mapping


class DomainError(Exception):
    """Base class for expected domain failures."""


class DomainValidationError(DomainError, ValueError):
    """Raised when a value violates a domain invariant."""


class AdapterNotFoundError(DomainError):
    """Raised when no registered Adapter accepts a source URL."""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__("no adapter matched the source URL")


class UpstreamError(DomainError):
    """Raised when an upstream platform operation fails."""


class DiscoveryEmptyError(UpstreamError):
    code = "DISCOVERY_EMPTY"
    public_message = "list discovery returned no valid targets"

    def __init__(self, details: Mapping[str, int]) -> None:
        self.details = {key: int(value) for key, value in details.items()}
        super().__init__(self.public_message)


class CancellationRequestedError(DomainError):
    """Raised by a cancellation token when the current crawl must stop."""
