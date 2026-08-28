from __future__ import annotations

import uuid

from webhook_platform.shared.domain.ids import new_id


def test_new_id_is_uuidv7_compatible() -> None:
    value = uuid.UUID(new_id())
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_new_ids_are_unique() -> None:
    assert len({new_id() for _ in range(100)}) == 100
