from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from webhook_platform.config.settings import Settings
from webhook_platform.shared.infrastructure.database import database_now
from webhook_platform.shared.infrastructure.models import (
    AuditEventModel,
    DeliveryAttemptModel,
    DeliveryModel,
    EventModel,
)


async def cleanup_expired(
    factory: async_sessionmaker[AsyncSession], settings: Settings, batch_size: int = 1000
) -> int:
    async with factory() as session, session.begin():
        now = await database_now(session)
        preview_cutoff = now - timedelta(days=settings.preview_retention_days)
        preview_ids = list(
            await session.scalars(
                select(DeliveryAttemptModel.id)
                .where(
                    DeliveryAttemptModel.ended_at < preview_cutoff,
                    DeliveryAttemptModel.preview_ciphertext.is_not(None),
                )
                .order_by(DeliveryAttemptModel.ended_at, DeliveryAttemptModel.id)
                .with_for_update(skip_locked=True)
                .limit(batch_size)
            )
        )
        if preview_ids:
            await session.execute(
                update(DeliveryAttemptModel)
                .where(DeliveryAttemptModel.id.in_(preview_ids))
                .values(preview_ciphertext=None, preview_nonce=None, preview_key_version=None)
            )

        audit_cutoff = now - timedelta(days=settings.audit_retention_days)
        audit_ids = list(
            await session.scalars(
                select(AuditEventModel.id)
                .where(AuditEventModel.created_at < audit_cutoff)
                .order_by(AuditEventModel.created_at, AuditEventModel.id)
                .with_for_update(skip_locked=True)
                .limit(batch_size)
            )
        )
        if audit_ids:
            await session.execute(delete(AuditEventModel).where(AuditEventModel.id.in_(audit_ids)))

        metadata_cutoff = now - timedelta(days=settings.metadata_retention_days)
        delivery_ids = list(
            await session.scalars(
                select(DeliveryModel.id)
                .where(
                    DeliveryModel.created_at < metadata_cutoff,
                    DeliveryModel.status.in_(["succeeded", "dead_lettered", "cancelled"]),
                )
                .order_by(DeliveryModel.created_at, DeliveryModel.id)
                .with_for_update(skip_locked=True)
                .limit(batch_size)
            )
        )
        if delivery_ids:
            await session.execute(delete(DeliveryModel).where(DeliveryModel.id.in_(delivery_ids)))

        event_ids = list(
            await session.scalars(
                select(EventModel.id)
                .where(
                    EventModel.created_at < metadata_cutoff,
                    ~exists(
                        select(DeliveryModel.id).where(DeliveryModel.event_id == EventModel.id)
                    ),
                )
                .order_by(EventModel.created_at, EventModel.id)
                .with_for_update(skip_locked=True)
                .limit(batch_size)
            )
        )
        if event_ids:
            await session.execute(delete(EventModel).where(EventModel.id.in_(event_ids)))

        return len(preview_ids) + len(audit_ids) + len(delivery_ids) + len(event_ids)
