from __future__ import annotations

from datetime import UTC, datetime

import pytest

from webhook_platform.deliveries.domain.retry import (
    is_retryable,
    is_success,
    parse_retry_after,
    retry_delay,
)


@pytest.mark.parametrize("status", [200, 201, 204, 299])
def test_success_matrix(status: int) -> None:
    assert is_success(status)


@pytest.mark.parametrize("status", [408, 425, 429, 500, 503, 599])
def test_retryable_status_matrix(status: int) -> None:
    assert is_retryable(status)


@pytest.mark.parametrize("status", [300, 301, 400, 401, 404, 422])
def test_terminal_status_matrix(status: int) -> None:
    assert not is_retryable(status)


def test_network_error_is_retryable() -> None:
    assert is_retryable(None, network_error=True)


def test_retry_delay_uses_defined_schedule_and_jitter() -> None:
    delays = (30, 120, 600, 3600, 21600)
    assert retry_delay(1, delays, 0.2, random_value=0).total_seconds() == 30
    assert retry_delay(2, delays, 0.2, random_value=1).total_seconds() == 144


def test_retry_after_can_increase_but_is_capped() -> None:
    delay = retry_delay(1, (30,), 0, retry_after_seconds=999999)
    assert delay.total_seconds() == 21600


def test_retry_after_accepts_http_date_and_rejects_invalid_value() -> None:
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    assert parse_retry_after("Thu, 27 Aug 2026 12:02:00 GMT", now) == 120
    assert parse_retry_after("not-a-date", now) is None
