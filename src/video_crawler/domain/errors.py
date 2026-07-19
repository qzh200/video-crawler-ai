class DomainError(Exception):
    """Base class for expected domain failures."""


class DomainValidationError(DomainError, ValueError):
    """Raised when a value violates a domain invariant."""
