from __future__ import annotations

import os

import pytest

from webhook_platform.config.settings import Settings
from webhook_platform.outbox.infrastructure.publisher import RabbitPublisher

pytestmark = pytest.mark.integration


def test_persistent_celery_command_round_trip() -> None:
    broker_url = os.getenv("WEBHOOK_PLATFORM_TEST_BROKER_URL")
    if not broker_url:
        pytest.skip("WEBHOOK_PLATFORM_TEST_BROKER_URL is not configured")
    suffix = "integration"
    settings = Settings(
        environment="test",
        broker_url=broker_url,
        broker_exchange=f"webhook.delivery.{suffix}",
        broker_queue=f"webhook.delivery.v1.{suffix}",
        broker_routing_key=f"delivery.execute.v1.{suffix}",
        broker_dlx=f"webhook.delivery.dlx.{suffix}",
        broker_dead_queue=f"webhook.delivery.dead.v1.{suffix}",
    )
    publisher = RabbitPublisher(settings)
    payload = {
        "schema_version": 1,
        "delivery_id": "00000000-0000-7000-8000-000000000001",
        "correlation_id": "00000000-0000-7000-8000-000000000002",
    }
    with publisher.connection() as connection:
        publisher.publish(connection, payload)
        simple_queue = connection.SimpleQueue(publisher.queue)
        message = simple_queue.get(block=True, timeout=5)
        try:
            assert message.headers["task"] == "delivery.execute.v1"
            assert message.properties["delivery_mode"] == 2
        finally:
            message.ack()
            simple_queue.close()
            publisher.queue(connection).delete(if_unused=False, if_empty=False)
            publisher.dead_queue(connection).delete(if_unused=False, if_empty=False)
            publisher.exchange(connection).delete(if_unused=False)
            publisher.dlx(connection).delete(if_unused=False)
