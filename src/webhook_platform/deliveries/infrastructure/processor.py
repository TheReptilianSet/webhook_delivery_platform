from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from webhook_platform.config.settings import Settings
from webhook_platform.deliveries.domain.retry import (
    is_retryable,
    is_success,
    parse_retry_after,
    retry_delay,
)
from webhook_platform.endpoints.domain.network import validate_url_syntax
from webhook_platform.endpoints.infrastructure.network import resolve_and_validate
from webhook_platform.shared.application.crypto import CiphertextUnavailable
from webhook_platform.shared.domain.errors import AppError
from webhook_platform.shared.infrastructure.database import database_now
from webhook_platform.shared.infrastructure.metrics import (
    ATTEMPT_DURATION,
    CAPACITY_DEFERRALS,
    DELIVERY_OUTCOMES,
    DLQ_TRANSITIONS,
    RETRIES,
    SSRF_REJECTIONS,
)
from webhook_platform.shared.infrastructure.models import (
    DeliveryAttemptModel,
    DeliveryModel,
    EndpointSecretModel,
    EventModel,
    WebhookEndpointModel,
)
from webhook_platform.shared.infrastructure.security import AesGcmCipher, webhook_signature


@dataclass(frozen=True)
class ClaimedDelivery:
    delivery_id: str
    attempt_id: str
    attempt_number: int
    event_id: str
    endpoint_id: str
    url: str
    raw_body: bytes
    secret: bytes


async def claim_delivery(
    factory: async_sessionmaker[AsyncSession], settings: Settings, delivery_id: str
) -> ClaimedDelivery | None:
    cipher = AesGcmCipher(settings)
    async with factory() as session, session.begin():
        now = await database_now(session)
        delivery = await session.scalar(
            select(DeliveryModel).where(DeliveryModel.id == delivery_id).with_for_update()
        )
        if delivery is None or delivery.status != "queued":
            return None
        endpoint = await session.scalar(
            select(WebhookEndpointModel)
            .where(WebhookEndpointModel.id == delivery.endpoint_id)
            .with_for_update()
        )
        if endpoint is None or endpoint.status != "active" or not endpoint.enabled:
            delivery.status = "cancelled"
            return None
        if endpoint.active_delivery_count >= 3:
            CAPACITY_DEFERRALS.inc()
            delivery.status = "retry_scheduled"
            delivery.next_attempt_at = now + timedelta(seconds=1)
            return None
        event = await session.get(EventModel, delivery.event_id)
        secret_model = await session.scalar(
            select(EndpointSecretModel).where(
                EndpointSecretModel.endpoint_id == endpoint.id,
                EndpointSecretModel.active.is_(True),
            )
        )
        if event is None:
            delivery.status = "dead_lettered"
            return None
        if secret_model is None:
            delivery.attempt_count += 1
            delivery.status = "dead_lettered"
            session.add(
                DeliveryAttemptModel(
                    organization_id=delivery.organization_id,
                    delivery_id=delivery.id,
                    attempt_number=delivery.attempt_count,
                    ended_at=now,
                    outcome="failed",
                    error_code="secret_unavailable",
                    retry_decision={"retry": False, "reason": "secret_unavailable"},
                )
            )
            return None
        try:
            if secret_model.key_version != settings.encryption_key_version:
                raise ValueError("secret key version is unavailable")
            secret = cipher.decrypt(
                secret_model.ciphertext, secret_model.nonce, endpoint.id.encode()
            )
        except (CiphertextUnavailable, ValueError):
            delivery.attempt_count += 1
            delivery.status = "dead_lettered"
            session.add(
                DeliveryAttemptModel(
                    organization_id=delivery.organization_id,
                    delivery_id=delivery.id,
                    attempt_number=delivery.attempt_count,
                    ended_at=now,
                    outcome="failed",
                    error_code="secret_unavailable",
                    retry_decision={"retry": False, "reason": "secret_unavailable"},
                )
            )
            return None
        delivery.attempt_count += 1
        delivery.status = "delivering"
        delivery.lease_until = now + timedelta(seconds=settings.delivery_lease_seconds)
        endpoint.active_delivery_count += 1
        attempt = DeliveryAttemptModel(
            organization_id=delivery.organization_id,
            delivery_id=delivery.id,
            attempt_number=delivery.attempt_count,
            outcome="started",
        )
        session.add(attempt)
        await session.flush()
        return ClaimedDelivery(
            delivery.id,
            attempt.id,
            attempt.attempt_number,
            event.id,
            endpoint.id,
            endpoint.url,
            bytes(event.canonical_body),
            secret,
        )


async def execute_delivery(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    client: httpx.AsyncClient,
    delivery_id: str,
) -> None:
    claimed = await claim_delivery(factory, settings, delivery_id)
    if claimed is None:
        return
    timestamp = str(int(datetime.now(UTC).timestamp()))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "webhook-delivery-platform/0.1",
        "Webhook-Event-Id": claimed.event_id,
        "Webhook-Delivery-Id": claimed.delivery_id,
        "Webhook-Timestamp": timestamp,
        "Webhook-Attempt": str(claimed.attempt_number),
        "Webhook-Signature": webhook_signature(
            claimed.secret,
            timestamp,
            claimed.event_id,
            claimed.delivery_id,
            claimed.raw_body,
        ),
    }
    started = time.monotonic()
    response_status: int | None = None
    response_preview = b""
    error_code: str | None = None
    retry_after: int | None = None
    try:
        async with asyncio.timeout(settings.http_total_timeout):
            destination = validate_url_syntax(claimed.url, settings)
            is_test = destination.url.rstrip("/") == settings.test_receiver_url.rstrip("/")
            if not (
                settings.environment in {"development", "test"}
                and settings.allow_test_receiver
                and is_test
            ):
                await resolve_and_validate(destination)
            async with client.stream(
                "POST", claimed.url, content=claimed.raw_body, headers=headers
            ) as response:
                response_status = response.status_code
                preview = bytearray()
                async for chunk in response.aiter_bytes():
                    remaining = settings.response_preview_limit - len(preview)
                    if remaining > 0:
                        preview.extend(chunk[:remaining])
                response_preview = bytes(preview)
                if response.status_code in {429, 503}:
                    retry_after = parse_retry_after(
                        response.headers.get("Retry-After"), datetime.now(UTC)
                    )
    except AppError:
        SSRF_REJECTIONS.inc()
        error_code = "unsafe_destination"
    except (TimeoutError, httpx.TimeoutException, httpx.NetworkError):
        error_code = "network_error"
    except httpx.HTTPError:
        error_code = "http_error"
    elapsed_ms = int((time.monotonic() - started) * 1000)
    await finalize_delivery(
        factory,
        settings,
        claimed,
        response_status,
        response_preview,
        error_code,
        elapsed_ms,
        retry_after,
    )


async def finalize_delivery(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    claimed: ClaimedDelivery,
    response_status: int | None,
    response_preview: bytes,
    error_code: str | None,
    latency_ms: int,
    retry_after: int | None,
) -> None:
    cipher = AesGcmCipher(settings)
    async with factory() as session, session.begin():
        now = await database_now(session)
        delivery = await session.scalar(
            select(DeliveryModel).where(DeliveryModel.id == claimed.delivery_id).with_for_update()
        )
        endpoint = await session.scalar(
            select(WebhookEndpointModel)
            .where(WebhookEndpointModel.id == claimed.endpoint_id)
            .with_for_update()
        )
        attempt = await session.get(DeliveryAttemptModel, claimed.attempt_id)
        if delivery is None or endpoint is None or attempt is None or attempt.outcome != "started":
            return
        attempt.ended_at = now
        attempt.response_status = response_status
        attempt.latency_ms = latency_ms
        attempt.error_code = error_code
        if response_preview:
            ciphertext, nonce, version = cipher.encrypt(
                response_preview, f"{delivery.id}:{attempt.id}".encode()
            )
            attempt.preview_ciphertext = ciphertext
            attempt.preview_nonce = nonce
            attempt.preview_key_version = version
        network_error = error_code in {"network_error", "http_error"}
        if is_success(response_status):
            delivery.status = "succeeded"
            attempt.outcome = "succeeded"
            attempt.retry_decision = {"retry": False, "reason": "success"}
            DELIVERY_OUTCOMES.labels(outcome="succeeded").inc()
        elif (
            is_retryable(response_status, network_error=network_error)
            and delivery.attempt_count < settings.max_delivery_attempts
        ):
            delay = retry_delay(
                delivery.attempt_count,
                settings.retry_delays_seconds,
                settings.retry_jitter_ratio,
                retry_after_seconds=retry_after,
            )
            delivery.status = "retry_scheduled"
            delivery.next_attempt_at = now + delay
            attempt.outcome = "failed"
            attempt.retry_decision = {"retry": True, "delay_seconds": int(delay.total_seconds())}
            RETRIES.inc()
            DELIVERY_OUTCOMES.labels(outcome="retry_scheduled").inc()
        else:
            delivery.status = "dead_lettered"
            attempt.outcome = "failed"
            attempt.retry_decision = {"retry": False, "reason": error_code or "terminal_status"}
            DLQ_TRANSITIONS.inc()
            DELIVERY_OUTCOMES.labels(outcome="dead_lettered").inc()
        ATTEMPT_DURATION.labels(outcome=attempt.outcome).observe(latency_ms / 1000)
        delivery.lease_until = None
        endpoint.active_delivery_count = max(0, endpoint.active_delivery_count - 1)
