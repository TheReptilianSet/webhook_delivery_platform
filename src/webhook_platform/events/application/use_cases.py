from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from webhook_platform.config.settings import Settings
from webhook_platform.events.domain.canonical_json import canonicalize, event_fingerprint
from webhook_platform.shared.application.ports import UnitOfWork
from webhook_platform.shared.domain.errors import AppError, NotFoundError

EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


class EventRepository(Protocol):
    async def projected_backlog(self, organization_id: str, event_type: str) -> int: ...

    async def existing_idempotency(
        self, organization_id: str, api_key_id: str, idempotency_key: str
    ) -> Any | None: ...

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
    ) -> tuple[Any, int]: ...

    async def events(
        self,
        organization_id: str,
        event_type: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> list[Any]: ...

    async def event(self, organization_id: str, event_id: str) -> Any | None: ...

    async def delivery_summary(self, organization_id: str, event_id: str) -> dict[str, int]: ...


class EventUseCases:
    def __init__(self, repository: EventRepository, uow: UnitOfWork, settings: Settings) -> None:
        self.repository = repository
        self.uow = uow
        self.settings = settings

    async def ingest(
        self,
        organization_id: str,
        api_key_id: str,
        idempotency_key: str,
        event_type: str,
        version: int,
        occurred_at: datetime,
        data: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        if not 16 <= len(idempotency_key) <= 128 or any(
            ord(char) < 33 or ord(char) > 126 for char in idempotency_key
        ):
            raise AppError("invalid_idempotency_key", "Idempotency-Key is invalid", status_code=422)
        if len(event_type) > 128 or EVENT_TYPE_PATTERN.fullmatch(event_type) is None:
            raise AppError("invalid_event_type", "Event type is invalid", status_code=422)
        if not 1 <= version <= 32767:
            raise AppError("invalid_event_version", "Event version is invalid", status_code=422)
        if occurred_at.tzinfo is None:
            raise AppError(
                "invalid_occurred_at", "occurred_at must include timezone", status_code=422
            )
        occurred_at = occurred_at.astimezone(UTC)
        if occurred_at > datetime.now(UTC) + timedelta(minutes=5):
            raise AppError(
                "invalid_occurred_at", "occurred_at is too far in the future", status_code=422
            )
        document = {
            "data": data,
            "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
            "type": event_type,
            "version": version,
        }
        body = canonicalize(
            document,
            size_limit=self.settings.event_body_limit,
            depth_limit=self.settings.event_json_depth_limit,
        )
        fingerprint = event_fingerprint(organization_id, api_key_id, body)
        existing = await self.repository.existing_idempotency(
            organization_id, api_key_id, idempotency_key
        )
        if existing is not None:
            return self._idempotent_result(existing, fingerprint), True
        if (
            await self.repository.projected_backlog(organization_id, event_type)
            > self.settings.backlog_limit
        ):
            raise AppError(
                "backlog_limit_exceeded",
                "Organization delivery backlog limit exceeded",
                status_code=429,
                details={"retry_after": 30},
            )
        try:
            event, delivery_count = await self.repository.create_event_graph(
                organization_id,
                api_key_id,
                event_type,
                version,
                occurred_at,
                data,
                body,
                idempotency_key,
                fingerprint,
            )
            await self.uow.commit()
        except ValueError:
            await self.uow.rollback()
            existing = await self.repository.existing_idempotency(
                organization_id, api_key_id, idempotency_key
            )
            if existing is None:
                raise
            return self._idempotent_result(existing, fingerprint), True
        return {
            "event_id": event.id,
            "status": "accepted",
            "delivery_count": delivery_count,
            "created_at": event.created_at,
        }, False

    @staticmethod
    def _idempotent_result(event: Any, fingerprint: str) -> dict[str, Any]:
        if not hmac_compare(event.fingerprint, fingerprint):
            raise AppError(
                "idempotency_conflict",
                "Idempotency key was used with different event content",
                status_code=409,
            )
        return {
            "event_id": event.id,
            "status": "accepted",
            "delivery_count": getattr(event, "delivery_count", 0),
            "created_at": event.created_at,
        }

    async def list_events(
        self,
        organization_id: str,
        event_type: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], Any | None]:
        rows = await self.repository.events(
            organization_id, event_type, occurred_from, occurred_to, cursor, limit + 1
        )
        next_item = rows[limit - 1] if len(rows) > limit else None
        return [self._view(item) for item in rows[:limit]], next_item

    async def get_event(self, organization_id: str, event_id: str) -> dict[str, Any]:
        event = await self.repository.event(organization_id, event_id)
        if event is None:
            raise NotFoundError()
        return {
            **self._view(event),
            "delivery_summary": await self.repository.delivery_summary(organization_id, event_id),
        }

    @staticmethod
    def _view(event: Any) -> dict[str, Any]:
        return {
            "id": event.id,
            "type": event.event_type,
            "version": event.version,
            "occurred_at": event.occurred_at,
            "data": event.data,
            "created_at": event.created_at,
        }


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)
