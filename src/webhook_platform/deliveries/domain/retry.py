from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime


def is_success(status: int | None) -> bool:
    return status is not None and 200 <= status < 300


def is_retryable(status: int | None, *, network_error: bool = False) -> bool:
    return network_error or status in {408, 425, 429} or (status is not None and status >= 500)


def retry_delay(
    failed_attempt: int,
    delays: tuple[int, ...],
    jitter_ratio: float,
    *,
    retry_after_seconds: int | None = None,
    random_value: float | None = None,
) -> timedelta:
    base = delays[min(failed_attempt - 1, len(delays) - 1)]
    sample = random.random() if random_value is None else random_value
    jittered = base + int(base * jitter_ratio * sample)
    if retry_after_seconds is not None:
        jittered = max(jittered, min(retry_after_seconds, 21600))
    return timedelta(seconds=jittered)


def parse_retry_after(value: str | None, now: datetime) -> int | None:
    if not value:
        return None
    if value.isdigit():
        return min(int(value), 21600)
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    seconds = max(0, int((retry_at - now).total_seconds()))
    return min(seconds, 21600)
