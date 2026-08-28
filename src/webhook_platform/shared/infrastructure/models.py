from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from webhook_platform.shared.domain.ids import new_id
from webhook_platform.shared.infrastructure.database import Base


class Timestamped:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserModel(Timestamped, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class RefreshTokenModel(Timestamped, Base):
    __tablename__ = "refresh_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[str | None] = mapped_column(ForeignKey("refresh_tokens.id"))


class OrganizationModel(Timestamped, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", server_default="active")
    __table_args__ = (
        CheckConstraint("status IN ('active','disabled')", name="organization_status"),
    )


class MembershipModel(Timestamped, Base):
    __tablename__ = "memberships"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        CheckConstraint("role IN ('owner','admin','member')", name="membership_role"),
    )


class ApiKeyModel(Timestamped, Base):
    __tablename__ = "api_keys"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    secret_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    digest_key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_api_keys_organization_id_id"),
    )


class WebhookEndpointModel(Timestamped, Base):
    __tablename__ = "webhook_endpoints"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending_verification")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    verification_hash: Mapped[str | None] = mapped_column(String(64))
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_delivery_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_webhook_endpoints_organization_id_id"),
        CheckConstraint(
            "status IN ('pending_verification','active','disabled','deleted')",
            name="endpoint_status",
        ),
        CheckConstraint(
            "active_delivery_count >= 0 AND active_delivery_count <= 3",
            name="endpoint_active_delivery_count",
        ),
    )


class EndpointSecretModel(Timestamped, Base):
    __tablename__ = "endpoint_secrets"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    endpoint_id: Mapped[str] = mapped_column(String(36), index=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "endpoint_id"],
            ["webhook_endpoints.organization_id", "webhook_endpoints.id"],
            ondelete="CASCADE",
        ),
        Index(
            "uq_endpoint_secrets_active",
            "endpoint_id",
            unique=True,
            postgresql_where=text("active"),
        ),
    )


class EndpointSubscriptionModel(Timestamped, Base):
    __tablename__ = "endpoint_subscriptions"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    endpoint_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "endpoint_id"],
            ["webhook_endpoints.organization_id", "webhook_endpoints.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("endpoint_id", "event_type"),
    )


class EventModel(Timestamped, Base):
    __tablename__ = "events"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    api_key_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    canonical_body: Mapped[bytes] = mapped_column(LargeBinary)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    fingerprint: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_events_organization_id_id"),
        ForeignKeyConstraint(
            ["organization_id", "api_key_id"],
            ["api_keys.organization_id", "api_keys.id"],
        ),
        UniqueConstraint(
            "organization_id",
            "api_key_id",
            "idempotency_key",
            name="uq_events_organization_key_idempotency",
        ),
        CheckConstraint("version >= 1 AND version <= 32767", name="event_version"),
    )


class DeliveryModel(Timestamped, Base):
    __tablename__ = "deliveries"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[str] = mapped_column(String(36), index=True)
    endpoint_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    replay_of: Mapped[str | None] = mapped_column(String(36), index=True)
    replay_idempotency_key: Mapped[str | None] = mapped_column(String(128))
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_deliveries_organization_id_id"),
        ForeignKeyConstraint(
            ["organization_id", "event_id"],
            ["events.organization_id", "events.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "endpoint_id"],
            ["webhook_endpoints.organization_id", "webhook_endpoints.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "replay_of"],
            ["deliveries.organization_id", "deliveries.id"],
        ),
        CheckConstraint(
            "status IN ('pending','queued','delivering','retry_scheduled','succeeded',"
            "'dead_lettered','cancelled')",
            name="delivery_status",
        ),
        CheckConstraint("attempt_count >= 0 AND attempt_count <= 6", name="delivery_attempt_count"),
        Index(
            "uq_deliveries_original_event_endpoint",
            "event_id",
            "endpoint_id",
            unique=True,
            postgresql_where=text("replay_of IS NULL"),
        ),
        Index(
            "uq_deliveries_replay_idempotency",
            "organization_id",
            "replay_of",
            "replay_idempotency_key",
            unique=True,
            postgresql_where=text("replay_of IS NOT NULL"),
        ),
    )


class DeliveryAttemptModel(Timestamped, Base):
    __tablename__ = "delivery_attempts"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    delivery_id: Mapped[str] = mapped_column(String(36), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(32), default="started")
    response_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    preview_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    preview_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    preview_key_version: Mapped[int | None] = mapped_column(Integer)
    retry_decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "delivery_id"],
            ["deliveries.organization_id", "deliveries.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "outcome IN ('started','succeeded','failed','unknown')", name="attempt_outcome"
        ),
        UniqueConstraint("delivery_id", "attempt_number"),
    )


class OutboxMessageModel(Timestamped, Base):
    __tablename__ = "outbox_messages"
    topic: Mapped[str] = mapped_column(String(100), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(128))
    __table_args__ = (
        CheckConstraint("status IN ('pending','published')", name="outbox_status"),
        CheckConstraint("publish_attempts >= 0", name="outbox_publish_attempts"),
    )


class AuditEventModel(Timestamped, Base):
    __tablename__ = "audit_events"
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    actor_type: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(36))
    request_id: Mapped[str | None] = mapped_column(String(64))
    safe_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
