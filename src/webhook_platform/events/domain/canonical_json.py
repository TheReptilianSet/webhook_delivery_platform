from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from webhook_platform.shared.domain.errors import AppError


def _depth(value: Any, current: int = 1) -> int:
    if isinstance(value, dict):
        return max([current, *(_depth(item, current + 1) for item in value.values())])
    if isinstance(value, list):
        return max([current, *(_depth(item, current + 1) for item in value)])
    if isinstance(value, float) and not math.isfinite(value):
        raise AppError("invalid_event", "NaN and Infinity are not allowed", status_code=422)
    return current


def canonicalize(value: dict[str, Any], *, size_limit: int, depth_limit: int) -> bytes:
    if _depth(value) > depth_limit:
        raise AppError("invalid_event", "JSON nesting is too deep", status_code=422)
    try:
        result = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode()
    except (TypeError, ValueError) as exc:
        raise AppError("invalid_event", "Event is not valid JSON", status_code=422) from exc
    if len(result) > size_limit:
        raise AppError("event_too_large", "Event body is too large", status_code=413)
    return result


def event_fingerprint(organization_id: str, api_key_id: str, body: bytes) -> str:
    material = b"POST\n" + organization_id.encode() + b"\n" + api_key_id.encode() + b"\n" + body
    return hashlib.sha256(material).hexdigest()
