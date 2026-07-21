from uuid import uuid4

import pytest

from video_crawler.infrastructure.database.types import UUIDBinary


def test_uuid_binary_round_trip() -> None:
    value = uuid4()
    column = UUIDBinary()
    encoded = column.process_bind_param(value, None)
    assert isinstance(encoded, bytes) and len(encoded) == 16
    assert column.process_result_value(encoded, None) == value


def test_uuid_binary_preserves_none() -> None:
    column = UUIDBinary()
    assert column.process_bind_param(None, None) is None
    assert column.process_result_value(None, None) is None


def test_uuid_binary_rejects_non_uuid_values() -> None:
    with pytest.raises(TypeError, match="UUID"):
        UUIDBinary().process_bind_param("not-a-uuid", None)  # type: ignore[arg-type]
