from __future__ import annotations

import os
import time
from queue import Empty

import pytest

from scripts.local_acceptance_flow import main
from webhook_platform.config.settings import Settings
from webhook_platform.outbox.infrastructure.publisher import RabbitPublisher

pytestmark = pytest.mark.e2e


def test_compose_success_retry_dlq_replay() -> None:
    if os.getenv("WEBHOOK_PLATFORM_RUN_COMPOSE_E2E") != "1":
        pytest.skip("Compose e2e is not enabled")
    main()


def test_poison_delivery_command_is_dead_lettered() -> None:
    if os.getenv("WEBHOOK_PLATFORM_RUN_COMPOSE_E2E") != "1":
        pytest.skip("Compose e2e is not enabled")
    broker_url = os.environ["WEBHOOK_PLATFORM_TEST_BROKER_URL"]
    publisher = RabbitPublisher(Settings(environment="test", broker_url=broker_url))
    with publisher.connection() as connection:
        publisher.publish(
            connection,
            {
                "schema_version": 999,
                "delivery_id": "00000000-0000-7000-8000-000000000001",
                "correlation_id": "00000000-0000-7000-8000-000000000002",
            },
        )
        queue = connection.SimpleQueue(publisher.dead_queue)
        deadline = time.monotonic() + 15
        message = None
        while message is None and time.monotonic() < deadline:
            try:
                message = queue.get(block=True, timeout=1)
            except Empty:
                continue
        assert message is not None
        message.ack()
        queue.close()
