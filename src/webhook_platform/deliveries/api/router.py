from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from webhook_platform.api_dependencies import current_user_id, get_session, settings_from
from webhook_platform.deliveries.api.schemas import AttemptResponse, DeliveryResponse
from webhook_platform.deliveries.application.use_cases import DeliveryUseCases
from webhook_platform.deliveries.infrastructure.repository import SqlAlchemyDeliveryRepository
from webhook_platform.shared.api.schemas import PageResponse
from webhook_platform.shared.domain.pagination import decode_cursor, encode_cursor
from webhook_platform.shared.infrastructure.security import AesGcmCipher
from webhook_platform.shared.infrastructure.uow import SqlAlchemyUnitOfWork

router = APIRouter(tags=["deliveries"])


def use_cases(request: Request, session: AsyncSession) -> DeliveryUseCases:
    settings = settings_from(request)
    return DeliveryUseCases(
        SqlAlchemyDeliveryRepository(session),
        SqlAlchemyUnitOfWork(session),
        settings,
        AesGcmCipher(settings),
    )


@router.get(
    "/organizations/{organization_id}/deliveries", response_model=PageResponse[DeliveryResponse]
)
async def list_deliveries(
    organization_id: str,
    request: Request,
    endpoint_id: str | None = None,
    event_id: str | None = None,
    delivery_status: str | None = Query(default=None, alias="status"),
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    items, next_item = await use_cases(request, session).list(
        organization_id,
        user_id,
        endpoint_id,
        event_id,
        delivery_status,
        decode_cursor(cursor),
        limit,
    )
    return {
        "items": items,
        "next_cursor": encode_cursor(next_item.created_at, next_item.id) if next_item else None,
    }


@router.get(
    "/organizations/{organization_id}/deliveries/{delivery_id}", response_model=DeliveryResponse
)
async def get_delivery(
    organization_id: str,
    delivery_id: str,
    request: Request,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await use_cases(request, session).get(organization_id, user_id, delivery_id)


@router.get(
    "/organizations/{organization_id}/deliveries/{delivery_id}/attempts",
    response_model=PageResponse[AttemptResponse],
    response_model_exclude_none=True,
)
async def list_attempts(
    organization_id: str,
    delivery_id: str,
    request: Request,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    items, next_item = await use_cases(request, session).list_attempts(
        organization_id, user_id, delivery_id, decode_cursor(cursor), limit
    )
    return {
        "items": items,
        "next_cursor": encode_cursor(next_item.created_at, next_item.id) if next_item else None,
    }


@router.post(
    "/organizations/{organization_id}/deliveries/{delivery_id}/replay",
    status_code=202,
    response_model=DeliveryResponse,
)
async def replay_delivery(
    organization_id: str,
    delivery_id: str,
    request: Request,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    result, replayed = await use_cases(request, session).replay(
        organization_id, user_id, delivery_id, idempotency_key
    )
    response.headers["Idempotency-Replayed"] = "true" if replayed else "false"
    return result
