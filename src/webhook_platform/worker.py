from __future__ import annotations

import asyncio

import httpx
import structlog
from celery import Celery
from celery.exceptions import Reject
from kombu import Exchange, Queue

from webhook_platform.config.settings import get_settings
from webhook_platform.deliveries.infrastructure.processor import execute_delivery
from webhook_platform.shared.infrastructure.database import create_engine, create_session_factory
from webhook_platform.shared.infrastructure.logging import configure_logging
from webhook_platform.shared.infrastructure.metrics import WORKER_IN_FLIGHT

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger("delivery_worker")
celery_app = Celery("webhook_platform", broker=settings.broker_url)
delivery_exchange = Exchange(settings.broker_exchange, type="direct", durable=True)
celery_app.conf.update(
    task_default_queue=settings.broker_queue,
    task_default_exchange=settings.broker_exchange,
    task_default_exchange_type="direct",
    task_default_routing_key=settings.broker_routing_key,
    task_queues=(
        Queue(
            settings.broker_queue,
            exchange=delivery_exchange,
            routing_key=settings.broker_routing_key,
            durable=True,
            queue_arguments={
                "x-dead-letter-exchange": settings.broker_dlx,
                "x-dead-letter-routing-key": "delivery.dead.v1",
            },
        ),
    ),
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=settings.worker_prefetch,
    task_ignore_result=True,
    worker_enable_remote_control=False,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    task_serializer="json",
    accept_content=["json"],
)


@celery_app.task(name="delivery.execute.v1", bind=True, acks_late=True)
def deliver(self: object, schema_version: int, delivery_id: str, correlation_id: str) -> None:
    if schema_version != 1 or not delivery_id or not correlation_id:
        logger.warning("delivery_command_rejected", schema_version=schema_version)
        raise Reject("invalid delivery command", requeue=False)

    async def execute() -> None:
        engine = create_engine(settings)
        factory = create_session_factory(engine)
        timeout = httpx.Timeout(
            connect=settings.http_connect_timeout,
            read=settings.http_read_timeout,
            write=settings.http_write_timeout,
            pool=settings.http_pool_timeout,
        )
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            await execute_delivery(factory, settings, client, delivery_id)
        await engine.dispose()

    WORKER_IN_FLIGHT.inc()
    try:
        asyncio.run(execute())
    finally:
        WORKER_IN_FLIGHT.dec()
