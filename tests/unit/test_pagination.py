from __future__ import annotations

from datetime import UTC, datetime

import pytest

from webhook_platform.shared.domain.errors import AppError
from webhook_platform.shared.domain.pagination import decode_cursor, encode_cursor


def test_cursor_round_trip_is_opaque() -> None:
    created_at = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    cursor = encode_cursor(created_at, "resource-1")

    assert "resource-1" not in cursor
    assert decode_cursor(cursor) == (created_at, "resource-1")


def test_invalid_cursor_has_stable_error() -> None:
    with pytest.raises(AppError) as error:
        decode_cursor("not-a-valid-cursor")

    assert error.value.code == "invalid_cursor"
    assert error.value.status_code == 422
