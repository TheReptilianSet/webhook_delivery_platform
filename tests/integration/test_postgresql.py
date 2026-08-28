from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from webhook_platform.outbox.infrastructure.repository import claim_outbox
from webhook_platform.shared.infrastructure.models import (
    EndpointSecretModel,
    OrganizationModel,
    OutboxMessageModel,
    WebhookEndpointModel,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def database() -> AsyncIterator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]]]:
    url = os.getenv("WEBHOOK_PLATFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("WEBHOOK_PLATFORM_TEST_DATABASE_URL is not configured")
    engine = create_async_engine(url)
    try:
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def test_initial_migration_contains_all_product_tables(
    database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    engine, _ = database
    async with engine.connect() as connection:
        table_names = set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
    assert {
        "users",
        "refresh_tokens",
        "organizations",
        "memberships",
        "api_keys",
        "webhook_endpoints",
        "endpoint_secrets",
        "endpoint_subscriptions",
        "events",
        "deliveries",
        "delivery_attempts",
        "outbox_messages",
        "audit_events",
    } <= table_names


async def test_application_rollback_leaves_no_partial_row(
    database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, factory = database
    marker = "rollback-integration-marker"
    async with factory() as session:
        session.add(OrganizationModel(name=marker))
        await session.flush()
        await session.rollback()
    async with factory() as session:
        found = await session.scalar(
            select(OrganizationModel.id).where(OrganizationModel.name == marker)
        )
    assert found is None


async def test_concurrent_outbox_claims_are_disjoint(
    database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, factory = database
    async with factory() as session, session.begin():
        session.add_all(
            [
                OutboxMessageModel(
                    topic="integration.claim",
                    aggregate_id=f"00000000-0000-7000-8000-{index:012d}",
                    payload={"index": index},
                )
                for index in range(2)
            ]
        )
    first, second = await asyncio.gather(claim_outbox(factory, 1), claim_outbox(factory, 1))
    assert len(first) == len(second) == 1
    assert first[0]["id"] != second[0]["id"]


async def test_database_rejects_cross_organization_endpoint_reference(
    database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _, factory = database
    async with factory() as session:
        first = OrganizationModel(name="tenant-constraint-a")
        second = OrganizationModel(name="tenant-constraint-b")
        session.add_all([first, second])
        await session.flush()
        endpoint = WebhookEndpointModel(
            organization_id=first.id,
            name="receiver",
            url="https://example.com/webhook",
            status="pending_verification",
        )
        session.add(endpoint)
        await session.flush()
        session.add(
            EndpointSecretModel(
                organization_id=second.id,
                endpoint_id=endpoint.id,
                ciphertext=b"ciphertext",
                nonce=b"012345678901",
                key_version=1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
