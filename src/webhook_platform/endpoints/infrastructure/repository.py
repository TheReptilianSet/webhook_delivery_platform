from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.shared.infrastructure.models import (
    AuditEventModel,
    DeliveryModel,
    EndpointSecretModel,
    EndpointSubscriptionModel,
    MembershipModel,
    WebhookEndpointModel,
)
from webhook_platform.shared.infrastructure.request_context import get_request_id


class SqlAlchemyEndpointRepository:
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

    async def endpoint_count(self, organization_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(WebhookEndpointModel)
                .where(
                    WebhookEndpointModel.organization_id == organization_id,
                    WebhookEndpointModel.deleted_at.is_(None),
                )
            )
            or 0
        )

    async def create_endpoint(
        self,
        endpoint_id: str,
        organization_id: str,
        name: str,
        url: str,
        event_types: list[str],
        ciphertext: bytes,
        nonce: bytes,
        key_version: int,
    ) -> WebhookEndpointModel:
        endpoint = WebhookEndpointModel(
            id=endpoint_id, organization_id=organization_id, name=name, url=url
        )
        self.session.add(endpoint)
        await self.session.flush()
        self.session.add(
            EndpointSecretModel(
                organization_id=organization_id,
                endpoint_id=endpoint.id,
                ciphertext=ciphertext,
                nonce=nonce,
                key_version=key_version,
            )
        )
        self.session.add_all(
            [
                EndpointSubscriptionModel(
                    organization_id=organization_id,
                    endpoint_id=endpoint.id,
                    event_type=event_type,
                )
                for event_type in event_types
            ]
        )
        return endpoint

    async def endpoints(
        self, organization_id: str, cursor: tuple[datetime, str] | None, limit: int
    ) -> list[tuple[WebhookEndpointModel, list[str]]]:
        query = select(WebhookEndpointModel).where(
            WebhookEndpointModel.organization_id == organization_id,
            WebhookEndpointModel.deleted_at.is_(None),
        )
        if cursor:
            created_at, resource_id = cursor
            query = query.where(
                (WebhookEndpointModel.created_at < created_at)
                | (
                    (WebhookEndpointModel.created_at == created_at)
                    & (WebhookEndpointModel.id < resource_id)
                )
            )
        rows = list(
            await self.session.scalars(
                query.order_by(
                    WebhookEndpointModel.created_at.desc(), WebhookEndpointModel.id.desc()
                ).limit(limit)
            )
        )
        return [(row, await self.subscriptions(row.id)) for row in rows]

    async def endpoint(
        self, organization_id: str, endpoint_id: str, *, lock: bool = False
    ) -> WebhookEndpointModel | None:
        query = select(WebhookEndpointModel).where(
            WebhookEndpointModel.organization_id == organization_id,
            WebhookEndpointModel.id == endpoint_id,
        )
        if lock:
            query = query.with_for_update()
        return cast("WebhookEndpointModel | None", await self.session.scalar(query))

    async def secret(self, organization_id: str, endpoint_id: str) -> EndpointSecretModel | None:
        return cast(
            "EndpointSecretModel | None",
            await self.session.scalar(
                select(EndpointSecretModel).where(
                    EndpointSecretModel.organization_id == organization_id,
                    EndpointSecretModel.endpoint_id == endpoint_id,
                    EndpointSecretModel.active.is_(True),
                )
            ),
        )

    async def replace_subscriptions(
        self, organization_id: str, endpoint_id: str, event_types: list[str]
    ) -> None:
        await self.session.execute(
            delete(EndpointSubscriptionModel).where(
                EndpointSubscriptionModel.organization_id == organization_id,
                EndpointSubscriptionModel.endpoint_id == endpoint_id,
            )
        )
        self.session.add_all(
            [
                EndpointSubscriptionModel(
                    organization_id=organization_id,
                    endpoint_id=endpoint_id,
                    event_type=value,
                )
                for value in event_types
            ]
        )

    async def subscriptions(self, endpoint_id: str) -> list[str]:
        return list(
            await self.session.scalars(
                select(EndpointSubscriptionModel.event_type)
                .where(EndpointSubscriptionModel.endpoint_id == endpoint_id)
                .order_by(EndpointSubscriptionModel.event_type)
            )
        )

    async def cancel_waiting(self, organization_id: str, endpoint_id: str) -> None:
        await self.session.execute(
            update(DeliveryModel)
            .where(
                DeliveryModel.organization_id == organization_id,
                DeliveryModel.endpoint_id == endpoint_id,
                DeliveryModel.status.in_(["pending", "queued", "retry_scheduled"]),
            )
            .values(status="cancelled", lease_until=None, next_attempt_at=None)
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
                resource_type="endpoint",
                resource_id=resource_id,
                request_id=get_request_id(),
                safe_metadata={},
            )
        )
