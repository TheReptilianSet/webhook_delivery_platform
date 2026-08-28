from __future__ import annotations

import pytest

from webhook_platform.shared.domain.errors import AppError
from webhook_platform.shared.infrastructure.rate_limit import InMemoryRateLimiter


async def test_token_bucket_rejects_after_capacity_is_consumed() -> None:
    limiter = InMemoryRateLimiter()
    await limiter.require("tenant", rate=0.01, capacity=2)
    await limiter.require("tenant", rate=0.01, capacity=2)

    with pytest.raises(AppError) as error:
        await limiter.require("tenant", rate=0.01, capacity=2)

    assert error.value.status_code == 429
    assert error.value.code == "rate_limit_exceeded"
    assert error.value.details["retry_after"] == 100


async def test_token_buckets_are_isolated_by_key() -> None:
    limiter = InMemoryRateLimiter()
    await limiter.require("tenant-a", rate=0.01, capacity=1)

    await limiter.require("tenant-b", rate=0.01, capacity=1)
