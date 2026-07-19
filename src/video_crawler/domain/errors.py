class DomainError(Exception):
    """Base class for expected domain failures."""


class DomainValidationError(DomainError, ValueError):
    """Raised when a value violates a domain invariant."""


class AdapterNotFoundError(DomainError):
    """Raised when no registered Adapter accepts a source URL."""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__("no adapter matched the source URL")
