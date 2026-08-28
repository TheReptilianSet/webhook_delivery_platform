from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.shared.infrastructure.models import (
    AuditEventModel,
    DeliveryAttemptModel,
    DeliveryModel,
    MembershipModel,
    OutboxMessageModel,
)
from webhook_platform.shared.infrastructure.request_context import get_request_id


class SqlAlchemyDeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def membership_role(self, organization_id: str, user_id: str) -> str | None:
        return cast(
            "str | None",
            await self.session.scalar(
                select(MembershipModel.role).where(
                    MembershipModel.organization_id == organization_id,
                    MembershipModel.user_id == user_id,
                )
            ),
        )

    async def deliveries(
        self,
        organization_id: str,
        endpoint_id: str | None,
        event_id: str | None,
        status: str | None,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> list[DeliveryModel]:
        query = select(DeliveryModel).where(DeliveryModel.organization_id == organization_id)
        if endpoint_id:
            query = query.where(DeliveryModel.endpoint_id == endpoint_id)
        if event_id:
            query = query.where(DeliveryModel.event_id == event_id)
        if status:
            query = query.where(DeliveryModel.status == status)
        if cursor:
            created_at, resource_id = cursor
            query = query.where(
                (DeliveryModel.created_at < created_at)
                | ((DeliveryModel.created_at == created_at) & (DeliveryModel.id < resource_id))
            )
        return list(
            await self.session.scalars(
                query.order_by(DeliveryModel.created_at.desc(), DeliveryModel.id.desc()).limit(
                    limit
                )
            )
        )

    async def delivery(
        self, organization_id: str, delivery_id: str, *, lock: bool = False
    ) -> DeliveryModel | None:
        query = select(DeliveryModel).where(
            DeliveryModel.organization_id == organization_id, DeliveryModel.id == delivery_id
        )
        if lock:
            query = query.with_for_update()
        return cast("DeliveryModel | None", await self.session.scalar(query))

    async def attempts(
        self,
        organization_id: str,
        delivery_id: str,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> list[DeliveryAttemptModel]:
        query = select(DeliveryAttemptModel).where(
            DeliveryAttemptModel.organization_id == organization_id,
            DeliveryAttemptModel.delivery_id == delivery_id,
        )
        if cursor:
            created_at, resource_id = cursor
            query = query.where(
                (DeliveryAttemptModel.created_at > created_at)
                | (
                    (DeliveryAttemptModel.created_at == created_at)
                    & (DeliveryAttemptModel.id > resource_id)
                )
            )
        return list(
            await self.session.scalars(
                query.order_by(DeliveryAttemptModel.created_at, DeliveryAttemptModel.id).limit(
                    limit
                )
            )
        )

    async def create_replay(self, source: DeliveryModel, idempotency_key: str) -> DeliveryModel:
        replay = DeliveryModel(
            organization_id=source.organization_id,
            event_id=source.event_id,
            endpoint_id=source.endpoint_id,
            status="queued",
            replay_of=source.id,
            replay_idempotency_key=idempotency_key,
        )
        self.session.add(replay)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise ValueError from exc
        self.session.add(
            OutboxMessageModel(
                topic="delivery.execute.v1",
                aggregate_id=replay.id,
                payload={
                    "schema_version": 1,
                    "delivery_id": replay.id,
                    "correlation_id": source.event_id,
                },
            )
        )
        return replay

    async def existing_replay(
        self, organization_id: str, source_id: str, idempotency_key: str
    ) -> DeliveryModel | None:
        return cast(
            "DeliveryModel | None",
            await self.session.scalar(
                select(DeliveryModel).where(
                    DeliveryModel.organization_id == organization_id,
                    DeliveryModel.replay_of == source_id,
                    DeliveryModel.replay_idempotency_key == idempotency_key,
                )
            ),
        )

    async def audit(
        self, organization_id: str, actor_id: str, action: str, resource_id: str
    ) -> None:
        self.session.add(
            AuditEventModel(
                organization_id=organization_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type="delivery",
                resource_id=resource_id,
                request_id=get_request_id(),
                safe_metadata={},
            )
        )
