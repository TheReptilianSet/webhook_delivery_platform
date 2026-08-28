from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.api_dependencies import (
    ProducerPrincipal,
    current_user_id,
    get_session,
    producer_principal,
    settings_from,
)
from webhook_platform.events.api.schemas import (
    EventAcceptedResponse,
    EventCreateRequest,
    EventDetailResponse,
    EventResponse,
)
from webhook_platform.events.application.use_cases import EventUseCases
from webhook_platform.events.infrastructure.repository import SqlAlchemyEventRepository
from webhook_platform.organizations.application.use_cases import OrganizationUseCases
from webhook_platform.organizations.infrastructure.repository import (
    SqlAlchemyOrganizationRepository,
)
from webhook_platform.shared.api.schemas import PageResponse
from webhook_platform.shared.domain.pagination import decode_cursor, encode_cursor
from webhook_platform.shared.infrastructure.metrics import EVENTS_ACCEPTED
from webhook_platform.shared.infrastructure.security import DefaultApiKeyIssuer
from webhook_platform.shared.infrastructure.uow import SqlAlchemyUnitOfWork

router = APIRouter(tags=["events"])


def event_use_cases(request: Request, session: AsyncSession) -> EventUseCases:
    return EventUseCases(
        SqlAlchemyEventRepository(session), SqlAlchemyUnitOfWork(session), settings_from(request)
    )


async def ensure_reader(
    organization_id: str, user_id: str, request: Request, session: AsyncSession
) -> None:
    settings = settings_from(request)
    organizations = OrganizationUseCases(
        SqlAlchemyOrganizationRepository(session),
        SqlAlchemyUnitOfWork(session),
        settings,
        DefaultApiKeyIssuer(settings),
    )
    await organizations.require_role(organization_id, user_id, {"owner", "admin", "member"})


@router.post("/events", status_code=202, response_model=EventAcceptedResponse)
async def ingest_event(
    body: EventCreateRequest,
    request: Request,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    principal: ProducerPrincipal = Depends(producer_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    result, replayed = await event_use_cases(request, session).ingest(
        principal.organization_id,
        principal.api_key_id,
        idempotency_key,
        body.type,
        body.version,
        body.occurred_at,
        body.data,
    )
    response.headers["Idempotency-Replayed"] = "true" if replayed else "false"
    EVENTS_ACCEPTED.labels(result="replayed" if replayed else "accepted").inc()
    return result


@router.get("/organizations/{organization_id}/events", response_model=PageResponse[EventResponse])
async def list_events(
    organization_id: str,
    request: Request,
    event_type: str | None = Query(default=None, alias="type"),
    occurred_from: datetime | None = Query(default=None, alias="from"),
    occurred_to: datetime | None = Query(default=None, alias="to"),
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    await ensure_reader(organization_id, user_id, request, session)
    items, next_item = await event_use_cases(request, session).list_events(
        organization_id,
        event_type,
        occurred_from,
        occurred_to,
        decode_cursor(cursor),
        limit,
    )
    return {
        "items": items,
        "next_cursor": encode_cursor(next_item.created_at, next_item.id) if next_item else None,
    }


@router.get(
    "/organizations/{organization_id}/events/{event_id}", response_model=EventDetailResponse
)
async def get_event(
    organization_id: str,
    event_id: str,
    request: Request,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    await ensure_reader(organization_id, user_id, request, session)
    return await event_use_cases(request, session).get_event(organization_id, event_id)
