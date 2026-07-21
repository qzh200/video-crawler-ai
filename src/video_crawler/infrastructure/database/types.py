from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import BINARY
from sqlalchemy.types import TypeDecorator


class UUIDBinary(TypeDecorator[UUID]):
    """Store UUID values as MySQL ``BINARY(16)`` columns."""

    impl = BINARY(16)
    cache_ok = True

    def process_bind_param(self, value: UUID | None, dialect: Any) -> bytes | None:
        del dialect
        if value is None:
            return None
        if not isinstance(value, UUID):
            raise TypeError("UUIDBinary values must be UUID instances")
        return value.bytes

    def process_result_value(self, value: bytes | None, dialect: Any) -> UUID | None:
        del dialect
        if value is None:
            return None
        return UUID(bytes=bytes(value))
