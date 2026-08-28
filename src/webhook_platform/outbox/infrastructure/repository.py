from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from webhook_platform.shared.infrastructure.database import database_now
from webhook_platform.shared.infrastructure.models import OutboxMessageModel


async def claim_outbox(
    factory: async_sessionmaker[AsyncSession], batch_size: int, lease_seconds: int = 30
) -> list[dict[str, Any]]:
    async with factory() as session, session.begin():
        now = await database_now(session)
        rows = list(
            await session.scalars(
                select(OutboxMessageModel)
                .where(
                    OutboxMessageModel.status == "pending",
                    OutboxMessageModel.available_at <= now,
                    or_(
                        OutboxMessageModel.lease_until.is_(None),
                        OutboxMessageModel.lease_until < now,
                    ),
                )
                .order_by(OutboxMessageModel.available_at, OutboxMessageModel.id)
                .with_for_update(skip_locked=True)
                .limit(batch_size)
            )
        )
        lease_until = now + timedelta(seconds=lease_seconds)
        result = []
        for row in rows:
            row.lease_until = lease_until
            row.publish_attempts += 1
            result.append({"id": row.id, "topic": row.topic, "payload": dict(row.payload)})
        return result


async def finish_outbox(
    factory: async_sessionmaker[AsyncSession],
    message_id: str,
    *,
    published: bool,
    error: str | None = None,
) -> None:
    async with factory() as session, session.begin():
        row = await session.scalar(
            select(OutboxMessageModel).where(OutboxMessageModel.id == message_id).with_for_update()
        )
        if row is None or row.status != "pending":
            return
        if published:
            row.status = "published"
            row.published_at = await database_now(session)
        row.lease_until = None
        row.last_error = error[:128] if error else None
