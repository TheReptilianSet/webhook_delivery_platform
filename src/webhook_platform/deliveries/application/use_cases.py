from __future__ import annotations

import base64
import builtins
from datetime import datetime
from typing import Any, Protocol

from webhook_platform.config.settings import Settings
from webhook_platform.shared.application.crypto import Cipher, CiphertextUnavailable
from webhook_platform.shared.application.ports import UnitOfWork
from webhook_platform.shared.domain.errors import AppError, ForbiddenError, NotFoundError

TERMINAL = {"succeeded", "dead_lettered", "cancelled"}


class DeliveryRepository(Protocol):
    async def membership_role(self, organization_id: str, user_id: str) -> str | None: ...

    async def deliveries(
        self,
        organization_id: str,
        endpoint_id: str | None,
        event_id: str | None,
        status: str | None,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> builtins.list[Any]: ...

    async def delivery(
        self, organization_id: str, delivery_id: str, *, lock: bool = False
    ) -> Any | None: ...

    async def attempts(
        self,
        organization_id: str,
        delivery_id: str,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> builtins.list[Any]: ...

    async def create_replay(self, source: Any, idempotency_key: str) -> Any: ...

    async def existing_replay(
        self, organization_id: str, source_id: str, idempotency_key: str
    ) -> Any | None: ...

    async def audit(
        self, organization_id: str, actor_id: str, action: str, resource_id: str
    ) -> None: ...


class DeliveryUseCases:
    def __init__(
        self, repository: DeliveryRepository, uow: UnitOfWork, settings: Settings, cipher: Cipher
    ) -> None:
        self.repository = repository
        self.uow = uow
        self.settings = settings
        self.cipher = cipher

    async def _role(self, organization_id: str, user_id: str, allowed: set[str]) -> str:
        role = await self.repository.membership_role(organization_id, user_id)
        if role is None:
            raise NotFoundError()
        if role not in allowed:
            raise ForbiddenError()
        return role

    async def list(
        self,
        organization_id: str,
        user_id: str,
        endpoint_id: str | None,
        event_id: str | None,
        status: str | None,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[builtins.list[dict[str, Any]], Any | None]:
        await self._role(organization_id, user_id, {"owner", "admin", "member"})
        rows = await self.repository.deliveries(
            organization_id, endpoint_id, event_id, status, cursor, limit + 1
        )
        next_item = rows[limit - 1] if len(rows) > limit else None
        return [self._view(item) for item in rows[:limit]], next_item

    async def get(self, organization_id: str, user_id: str, delivery_id: str) -> dict[str, Any]:
        await self._role(organization_id, user_id, {"owner", "admin", "member"})
        item = await self.repository.delivery(organization_id, delivery_id)
        if item is None:
            raise NotFoundError()
        return self._view(item)

    async def list_attempts(
        self,
        organization_id: str,
        user_id: str,
        delivery_id: str,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[builtins.list[dict[str, Any]], Any | None]:
        role = await self._role(organization_id, user_id, {"owner", "admin", "member"})
        if await self.repository.delivery(organization_id, delivery_id) is None:
            raise NotFoundError()
        rows = await self.repository.attempts(organization_id, delivery_id, cursor, limit + 1)
        next_item = rows[limit - 1] if len(rows) > limit else None
        result: builtins.list[dict[str, Any]] = []
        for item in rows[:limit]:
            preview: str | None = None
            preview_error: str | None = None
            if role in {"owner", "admin"} and item.preview_ciphertext is not None:
                try:
                    if item.preview_key_version != self.settings.encryption_key_version:
                        raise CiphertextUnavailable
                    plaintext = self.cipher.decrypt(
                        item.preview_ciphertext,
                        item.preview_nonce,
                        f"{delivery_id}:{item.id}".encode(),
                    )
                    preview = base64.b64encode(plaintext).decode()
                except (CiphertextUnavailable, ValueError, TypeError):
                    preview_error = "unavailable"
            view = {
                "id": item.id,
                "attempt_number": item.attempt_number,
                "started_at": item.started_at,
                "ended_at": item.ended_at,
                "outcome": item.outcome,
                "response_status": item.response_status,
                "latency_ms": item.latency_ms,
                "error_code": item.error_code,
                "retry_decision": item.retry_decision,
                "response_preview_available": role in {"owner", "admin"}
                and item.preview_ciphertext is not None,
                "response_preview": preview,
                "response_preview_encoding": "base64" if preview is not None else None,
                "response_preview_error": preview_error,
            }
            if role == "member":
                view.pop("response_preview")
                view.pop("response_preview_encoding")
                view.pop("response_preview_error")
            result.append(view)
        return result, next_item

    async def replay(
        self, organization_id: str, user_id: str, delivery_id: str, idempotency_key: str
    ) -> tuple[dict[str, Any], bool]:
        await self._role(organization_id, user_id, {"owner", "admin"})
        if not 16 <= len(idempotency_key) <= 128:
            raise AppError("invalid_idempotency_key", "Idempotency-Key is invalid", status_code=422)
        existing = await self.repository.existing_replay(
            organization_id, delivery_id, idempotency_key
        )
        if existing is not None:
            return self._view(existing), True
        source = await self.repository.delivery(organization_id, delivery_id, lock=True)
        if source is None:
            raise NotFoundError()
        if source.status not in TERMINAL:
            raise AppError(
                "delivery_not_terminal", "Only terminal deliveries can be replayed", status_code=409
            )
        try:
            replay = await self.repository.create_replay(source, idempotency_key)
            await self.repository.audit(organization_id, user_id, "delivery.replayed", replay.id)
            await self.uow.commit()
        except ValueError:
            await self.uow.rollback()
            replay = await self.repository.existing_replay(
                organization_id, delivery_id, idempotency_key
            )
            if replay is None:
                raise
            return self._view(replay), True
        return self._view(replay), False

    @staticmethod
    def _view(item: Any) -> dict[str, Any]:
        return {
            "id": item.id,
            "event_id": item.event_id,
            "endpoint_id": item.endpoint_id,
            "status": item.status,
            "attempt_count": item.attempt_count,
            "next_attempt_at": item.next_attempt_at,
            "replay_of": item.replay_of,
            "created_at": item.created_at,
        }
