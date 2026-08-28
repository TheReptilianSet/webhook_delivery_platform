from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.shared.infrastructure.models import (
    DeliveryModel,
    EndpointSubscriptionModel,
    EventModel,
    OrganizationModel,
    OutboxMessageModel,
    WebhookEndpointModel,
)


class SqlAlchemyEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def projected_backlog(self, organization_id: str, event_type: str) -> int:
        await self.session.scalar(
            select(OrganizationModel.id)
            .where(OrganizationModel.id == organization_id)
            .with_for_update()
        )
        current = int(
            await self.session.scalar(
                select(func.count())
                .select_from(DeliveryModel)
                .where(
                    DeliveryModel.organization_id == organization_id,
                    DeliveryModel.status.not_in(["succeeded", "dead_lettered", "cancelled"]),
                )
            )
            or 0
        )
        matching = int(
            await self.session.scalar(
                select(func.count())
                .select_from(WebhookEndpointModel)
                .join(
                    EndpointSubscriptionModel,
                    EndpointSubscriptionModel.endpoint_id == WebhookEndpointModel.id,
                )
                .where(
                    WebhookEndpointModel.organization_id == organization_id,
                    WebhookEndpointModel.status == "active",
                    WebhookEndpointModel.enabled.is_(True),
                    WebhookEndpointModel.deleted_at.is_(None),
                    EndpointSubscriptionModel.organization_id == organization_id,
                    EndpointSubscriptionModel.event_type == event_type,
                )
            )
            or 0
        )
        return current + matching

    async def existing_idempotency(
        self, organization_id: str, api_key_id: str, idempotency_key: str
    ) -> EventModel | None:
        event = await self.session.scalar(
            select(EventModel).where(
                EventModel.organization_id == organization_id,
                EventModel.api_key_id == api_key_id,
                EventModel.idempotency_key == idempotency_key,
            )
        )
        if event is not None:
            cast(Any, event).delivery_count = int(
                await self.session.scalar(
                    select(func.count())
                    .select_from(DeliveryModel)
                    .where(DeliveryModel.event_id == event.id)
                )
                or 0
            )
        return event

    async def create_event_graph(
        self,
        organization_id: str,
        api_key_id: str,
        event_type: str,
        version: int,
        occurred_at: datetime,
        data: dict[str, Any],
        canonical_body: bytes,
        idempotency_key: str,
        fingerprint: str,
    ) -> tuple[EventModel, int]:
        endpoints = list(
            await self.session.scalars(
                select(WebhookEndpointModel)
                .join(
                    EndpointSubscriptionModel,
                    EndpointSubscriptionModel.endpoint_id == WebhookEndpointModel.id,
                )
                .where(
                    WebhookEndpointModel.organization_id == organization_id,
                    WebhookEndpointModel.status == "active",
                    WebhookEndpointModel.enabled.is_(True),
                    WebhookEndpointModel.deleted_at.is_(None),
                    EndpointSubscriptionModel.event_type == event_type,
                )
            )
        )
        event = EventModel(
            organization_id=organization_id,
            api_key_id=api_key_id,
            event_type=event_type,
            version=version,
            occurred_at=occurred_at,
            canonical_body=canonical_body,
            data=data,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
        )
        self.session.add(event)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise ValueError from exc
        for endpoint in endpoints:
            delivery = DeliveryModel(
                organization_id=organization_id,
                event_id=event.id,
                endpoint_id=endpoint.id,
                status="queued",
            )
            self.session.add(delivery)
            await self.session.flush()
            self.session.add(
                OutboxMessageModel(
                    topic="delivery.execute.v1",
                    aggregate_id=delivery.id,
                    payload={
                        "schema_version": 1,
                        "delivery_id": delivery.id,
                        "correlation_id": event.id,
                    },
                )
            )
        return event, len(endpoints)

    async def events(
        self,
        organization_id: str,
        event_type: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> list[EventModel]:
        query = select(EventModel).where(EventModel.organization_id == organization_id)
        if event_type:
            query = query.where(EventModel.event_type == event_type)
        if occurred_from:
            query = query.where(EventModel.occurred_at >= occurred_from)
        if occurred_to:
            query = query.where(EventModel.occurred_at <= occurred_to)
        if cursor:
            created_at, resource_id = cursor
            query = query.where(
                (EventModel.created_at < created_at)
                | ((EventModel.created_at == created_at) & (EventModel.id < resource_id))
            )
        result = await self.session.scalars(
            query.order_by(EventModel.created_at.desc(), EventModel.id.desc()).limit(limit)
        )
        return list(result)

    async def event(self, organization_id: str, event_id: str) -> EventModel | None:
        return cast(
            "EventModel | None",
            await self.session.scalar(
                select(EventModel).where(
                    EventModel.organization_id == organization_id, EventModel.id == event_id
                )
            ),
        )

    async def delivery_summary(self, organization_id: str, event_id: str) -> dict[str, int]:
        statuses = await self.session.scalars(
            select(DeliveryModel.status).where(
                DeliveryModel.organization_id == organization_id,
                DeliveryModel.event_id == event_id,
            )
        )
        return dict(Counter(statuses))
