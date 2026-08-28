from __future__ import annotations

import builtins
import hashlib
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from webhook_platform.config.settings import Settings
from webhook_platform.endpoints.application.ports import EndpointVerifier
from webhook_platform.endpoints.domain.network import (
    ValidatedDestination,
    validate_url_syntax,
)
from webhook_platform.shared.application.crypto import Cipher
from webhook_platform.shared.application.ports import UnitOfWork
from webhook_platform.shared.domain.errors import AppError, ForbiddenError, NotFoundError
from webhook_platform.shared.domain.ids import new_id

EVENT_TYPE_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"


class EndpointRepository(Protocol):
    async def membership_role(self, organization_id: str, user_id: str) -> str | None: ...

    async def endpoint_count(self, organization_id: str) -> int: ...

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
    ) -> Any: ...

    async def endpoints(
        self, organization_id: str, cursor: tuple[datetime, str] | None, limit: int
    ) -> list[tuple[Any, list[str]]]: ...

    async def endpoint(
        self, organization_id: str, endpoint_id: str, *, lock: bool = False
    ) -> Any | None: ...

    async def secret(self, organization_id: str, endpoint_id: str) -> Any | None: ...

    async def replace_subscriptions(
        self, organization_id: str, endpoint_id: str, event_types: list[str]
    ) -> None: ...

    async def subscriptions(self, endpoint_id: str) -> builtins.list[str]: ...

    async def cancel_waiting(self, organization_id: str, endpoint_id: str) -> None: ...

    async def audit(
        self, organization_id: str, actor_id: str, action: str, resource_id: str
    ) -> None: ...


class EndpointUseCases:
    def __init__(
        self,
        repository: EndpointRepository,
        uow: UnitOfWork,
        settings: Settings,
        cipher: Cipher,
        verifier: EndpointVerifier,
        resolver: Callable[[ValidatedDestination], Awaitable[tuple[str, ...]]],
    ) -> None:
        self.repository = repository
        self.uow = uow
        self.settings = settings
        self.verifier = verifier
        self.resolver = resolver
        self.cipher = cipher

    async def _require_role(self, organization_id: str, user_id: str, roles: set[str]) -> None:
        role = await self.repository.membership_role(organization_id, user_id)
        if role is None:
            raise NotFoundError()
        if role not in roles:
            raise ForbiddenError()

    async def _validate_destination(self, url: str) -> ValidatedDestination:
        destination = validate_url_syntax(url, self.settings)
        is_test = (
            self.settings.environment in {"development", "test"}
            and self.settings.allow_test_receiver
            and destination.url.rstrip("/") == self.settings.test_receiver_url.rstrip("/")
        )
        if not is_test:
            await self.resolver(destination)
        return destination

    @staticmethod
    def _validate_event_types(event_types: list[str]) -> list[str]:
        import re

        unique = list(dict.fromkeys(event_types))
        if len(unique) != len(event_types) or not 1 <= len(unique) <= 50:
            raise AppError("invalid_event_types", "Event types must be unique", status_code=422)
        if any(
            len(item) > 128 or re.fullmatch(EVENT_TYPE_PATTERN, item) is None for item in unique
        ):
            raise AppError("invalid_event_types", "Event type format is invalid", status_code=422)
        return unique

    async def create(
        self,
        organization_id: str,
        user_id: str,
        name: str,
        url: str,
        event_types: list[str],
    ) -> dict[str, Any]:
        await self._require_role(organization_id, user_id, {"owner", "admin"})
        if await self.repository.endpoint_count(organization_id) >= self.settings.endpoint_limit:
            raise AppError("endpoint_limit_exceeded", "Endpoint limit exceeded", status_code=409)
        destination = await self._validate_destination(url)
        types = self._validate_event_types(event_types)
        plaintext_secret = secrets.token_urlsafe(32)
        endpoint_id = new_id()
        ciphertext, nonce, version = self.cipher.encrypt(
            plaintext_secret.encode(), endpoint_id.encode()
        )
        endpoint = await self.repository.create_endpoint(
            endpoint_id,
            organization_id,
            name.strip(),
            destination.url,
            types,
            ciphertext,
            nonce,
            version,
        )
        await self.repository.audit(organization_id, user_id, "endpoint.created", endpoint.id)
        await self.uow.commit()
        return {**await self._view(endpoint), "signing_secret": plaintext_secret}

    async def list(
        self,
        organization_id: str,
        user_id: str,
        cursor: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[builtins.list[dict[str, Any]], Any | None]:
        await self._require_role(organization_id, user_id, {"owner", "admin", "member"})
        rows = await self.repository.endpoints(organization_id, cursor, limit + 1)
        next_item = rows[limit - 1][0] if len(rows) > limit else None
        return [
            self._view_with_types(endpoint, types) for endpoint, types in rows[:limit]
        ], next_item

    async def get(self, organization_id: str, user_id: str, endpoint_id: str) -> dict[str, Any]:
        await self._require_role(organization_id, user_id, {"owner", "admin", "member"})
        endpoint = await self.repository.endpoint(organization_id, endpoint_id)
        if endpoint is None:
            raise NotFoundError()
        return await self._view(endpoint)

    async def update(
        self, organization_id: str, user_id: str, endpoint_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        await self._require_role(organization_id, user_id, {"owner", "admin"})
        endpoint = await self.repository.endpoint(organization_id, endpoint_id, lock=True)
        if endpoint is None or endpoint.deleted_at is not None:
            raise NotFoundError()
        if "url" in changes and changes["url"] != endpoint.url:
            destination = await self._validate_destination(changes["url"])
            endpoint.url = destination.url
            endpoint.status = "pending_verification"
        if "name" in changes:
            endpoint.name = changes["name"].strip()
        if "enabled" in changes:
            endpoint.enabled = changes["enabled"]
            if not endpoint.enabled and endpoint.status == "active":
                endpoint.status = "disabled"
                await self.repository.cancel_waiting(organization_id, endpoint.id)
            elif endpoint.enabled and endpoint.status == "disabled":
                endpoint.status = "active"
        if "event_types" in changes:
            await self.repository.replace_subscriptions(
                organization_id, endpoint.id, self._validate_event_types(changes["event_types"])
            )
        await self.repository.audit(organization_id, user_id, "endpoint.updated", endpoint.id)
        await self.uow.commit()
        return await self._view(endpoint)

    async def verify(self, organization_id: str, user_id: str, endpoint_id: str) -> dict[str, Any]:
        await self._require_role(organization_id, user_id, {"owner", "admin"})
        endpoint = await self.repository.endpoint(organization_id, endpoint_id, lock=True)
        secret_model = await self.repository.secret(organization_id, endpoint_id)
        if endpoint is None or secret_model is None or endpoint.deleted_at is not None:
            raise NotFoundError()
        await self._validate_destination(endpoint.url)
        challenge = secrets.token_urlsafe(32)
        verification_id = new_id()
        endpoint.verification_hash = hashlib.sha256(challenge.encode()).hexdigest()
        endpoint.verification_expires_at = datetime.now(UTC) + timedelta(minutes=10)
        await self.uow.commit()
        secret = self.cipher.decrypt(
            secret_model.ciphertext, secret_model.nonce, endpoint.id.encode()
        )
        if not await self.verifier.verify(
            endpoint.url, endpoint.id, secret, challenge, verification_id
        ):
            raise AppError("verification_failed", "Endpoint verification failed", status_code=422)
        current = await self.repository.endpoint(organization_id, endpoint_id, lock=True)
        if (
            current is None
            or current.verification_hash != hashlib.sha256(challenge.encode()).hexdigest()
            or current.verification_expires_at is None
            or current.verification_expires_at <= datetime.now(UTC)
        ):
            raise AppError("verification_failed", "Endpoint verification expired", status_code=422)
        current.verification_hash = None
        current.verification_expires_at = None
        current.status = "active"
        await self.repository.audit(organization_id, user_id, "endpoint.verified", current.id)
        await self.uow.commit()
        return await self._view(current)

    async def delete(self, organization_id: str, user_id: str, endpoint_id: str) -> None:
        await self._require_role(organization_id, user_id, {"owner", "admin"})
        endpoint = await self.repository.endpoint(organization_id, endpoint_id, lock=True)
        if endpoint is not None and endpoint.deleted_at is None:
            endpoint.deleted_at = datetime.now(UTC)
            endpoint.status = "deleted"
            endpoint.enabled = False
            await self.repository.cancel_waiting(organization_id, endpoint.id)
            await self.repository.audit(organization_id, user_id, "endpoint.deleted", endpoint.id)
        await self.uow.commit()

    async def _view(self, endpoint: Any) -> dict[str, Any]:
        return self._view_with_types(endpoint, await self.repository.subscriptions(endpoint.id))

    @staticmethod
    def _view_with_types(endpoint: Any, types: builtins.list[str]) -> dict[str, Any]:
        return {
            "id": endpoint.id,
            "name": endpoint.name,
            "url": endpoint.url,
            "status": endpoint.status,
            "enabled": endpoint.enabled,
            "event_types": types,
            "created_at": endpoint.created_at,
        }
