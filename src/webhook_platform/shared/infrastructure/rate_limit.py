from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass

from webhook_platform.shared.domain.errors import AppError
from webhook_platform.shared.infrastructure.metrics import LIMIT_REJECTIONS


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class InMemoryRateLimiter:
    """Process-local token buckets; deployments must size limits per API replica."""

    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._lock = asyncio.Lock()

    async def require(self, key: str, *, rate: float, capacity: int) -> None:
        now = time.monotonic()
        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(float(capacity), now)
                self._buckets[key] = bucket
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(float(capacity), bucket.tokens + elapsed * rate)
            bucket.updated_at = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return
            retry_after = max(1, math.ceil((1.0 - bucket.tokens) / rate))
        LIMIT_REJECTIONS.labels(kind=key.partition(":")[0]).inc()
        raise AppError(
            "rate_limit_exceeded",
            "Rate limit exceeded",
            status_code=429,
            details={"retry_after": retry_after},
        )
