from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from webhook_platform.config.settings import Settings
from webhook_platform.shared.infrastructure.database import database_now
from webhook_platform.shared.infrastructure.metrics import STALE_LEASES
from webhook_platform.shared.infrastructure.models import (
    DeliveryAttemptModel,
    DeliveryModel,
    OutboxMessageModel,
    WebhookEndpointModel,
)


async def schedule_due(factory: async_sessionmaker[AsyncSession], settings: Settings) -> int:
    async with factory() as session, session.begin():
        now = await database_now(session)
        deliveries = list(
            await session.scalars(
                select(DeliveryModel)
                .where(
                    DeliveryModel.status == "retry_scheduled",
                    DeliveryModel.next_attempt_at <= now,
                )
                .order_by(DeliveryModel.next_attempt_at, DeliveryModel.id)
                .with_for_update(skip_locked=True)
                .limit(settings.retry_batch_size)
            )
        )
        for delivery in deliveries:
            delivery.status = "queued"
            delivery.next_attempt_at = None
            session.add(
                OutboxMessageModel(
                    topic="delivery.execute.v1",
                    aggregate_id=delivery.id,
                    payload={
                        "schema_version": 1,
                        "delivery_id": delivery.id,
                        "correlation_id": delivery.event_id,
                    },
                )
            )
        return len(deliveries)


async def reconcile_stale(factory: async_sessionmaker[AsyncSession], settings: Settings) -> int:
    async with factory() as session, session.begin():
        now = await database_now(session)
        deliveries = list(
            await session.scalars(
                select(DeliveryModel)
                .where(
                    DeliveryModel.status == "delivering",
                    DeliveryModel.lease_until < now,
                )
                .with_for_update(skip_locked=True)
                .limit(settings.retry_batch_size)
            )
        )
        for delivery in deliveries:
            attempt = await session.scalar(
                select(DeliveryAttemptModel)
                .where(
                    DeliveryAttemptModel.delivery_id == delivery.id,
                    DeliveryAttemptModel.outcome == "started",
                )
                .order_by(DeliveryAttemptModel.attempt_number.desc())
                .limit(1)
            )
            endpoint = await session.scalar(
                select(WebhookEndpointModel)
                .where(WebhookEndpointModel.id == delivery.endpoint_id)
                .with_for_update()
            )
            if attempt is not None:
                attempt.outcome = "unknown"
                attempt.ended_at = now
                attempt.error_code = "stale_lease"
                attempt.retry_decision = {
                    "retry": delivery.attempt_count < settings.max_delivery_attempts
                }
            if endpoint is not None:
                endpoint.active_delivery_count = max(0, endpoint.active_delivery_count - 1)
            delivery.lease_until = None
            if delivery.attempt_count < settings.max_delivery_attempts:
                delivery.status = "retry_scheduled"
                delivery.next_attempt_at = now
            else:
                delivery.status = "dead_lettered"
        if deliveries:
            STALE_LEASES.inc(len(deliveries))
        return len(deliveries)
