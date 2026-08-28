from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime

from webhook_platform.shared.domain.errors import AppError

Cursor = tuple[datetime, str]


def encode_cursor(created_at: datetime, resource_id: str) -> str:
    raw = json.dumps(
        {"created_at": created_at.isoformat(), "id": resource_id},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(value: str | None) -> Cursor | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        created_at = datetime.fromisoformat(payload["created_at"])
        resource_id = payload["id"]
        if created_at.tzinfo is None or not isinstance(resource_id, str) or not resource_id:
            raise ValueError
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise AppError("invalid_cursor", "Cursor is invalid", status_code=422) from exc
    return created_at, resource_id
