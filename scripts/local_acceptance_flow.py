from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime

import httpx

API = os.getenv("WEBHOOK_PLATFORM_LOCAL_FLOW_API_BASE", "http://localhost:8000/api/v1")
RECEIVER = os.getenv("WEBHOOK_PLATFORM_LOCAL_FLOW_RECEIVER_BASE", "http://localhost:8080")


def wait_for_status(
    client: httpx.Client, token: str, organization_id: str, delivery_id: str, expected: str
) -> dict[str, object]:
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(90):
        response = client.get(
            f"{API}/organizations/{organization_id}/deliveries/{delivery_id}", headers=headers
        )
        response.raise_for_status()
        payload: dict[str, object] = response.json()
        if payload["status"] == expected:
            return payload
        time.sleep(1)
    raise RuntimeError(f"delivery {delivery_id} did not reach {expected}")


def find_delivery(client: httpx.Client, token: str, organization_id: str, event_id: str) -> str:
    response = client.get(
        f"{API}/organizations/{organization_id}/deliveries",
        params={"event_id": event_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    items = response.json()["items"]
    if not items:
        raise RuntimeError("event did not create a delivery")
    return str(items[0]["id"])


def main() -> None:
    suffix = str(int(time.time()))
    email = f"media-flow-{suffix}@example.com"
    with httpx.Client(timeout=15) as client:
        registration = client.post(
            f"{API}/auth/register",
            json={
                "email": email,
                "password": "correct-horse-battery-staple",
                "organization_name": "Media Processing Workspace",
            },
        )
        registration.raise_for_status()
        organization_id = registration.json()["organization"]["id"]
        login = client.post(
            f"{API}/auth/login",
            json={
                "email": email,
                "password": "correct-horse-battery-staple",
            },
        )
        login.raise_for_status()
        access = login.json()["access_token"]
        management_headers = {"Authorization": f"Bearer {access}"}
        key_response = client.post(
            f"{API}/organizations/{organization_id}/api-keys",
            headers=management_headers,
            json={"name": "Media pipeline", "scopes": ["events:write"]},
        )
        key_response.raise_for_status()
        producer_key = key_response.json()["key"]
        endpoint_response = client.post(
            f"{API}/organizations/{organization_id}/endpoints",
            headers=management_headers,
            json={
                "name": "Local receiver",
                "url": "http://test-receiver:8080",
                "event_types": ["media.processing.completed"],
            },
        )
        endpoint_response.raise_for_status()
        endpoint_id = endpoint_response.json()["id"]
        signing_secret = endpoint_response.json()["signing_secret"]
        verify = client.post(
            f"{API}/organizations/{organization_id}/endpoints/{endpoint_id}/verify",
            headers=management_headers,
        )
        verify.raise_for_status()

        client.post(
            f"{RECEIVER}/control",
            json={
                "mode": "success",
                "clear": True,
                "signing_secret": signing_secret,
            },
        ).raise_for_status()
        event = client.post(
            f"{API}/events",
            headers={
                "Authorization": f"Bearer {producer_key}",
                "Idempotency-Key": f"success-{suffix}-0001",
            },
            json={
                "type": "media.processing.completed",
                "version": 1,
                "occurred_at": datetime.now(UTC).isoformat(),
                "data": {"scenario": "success"},
            },
        )
        event.raise_for_status()
        delivery_id = find_delivery(client, access, organization_id, event.json()["event_id"])
        wait_for_status(client, access, organization_id, delivery_id, "succeeded")

        client.post(f"{RECEIVER}/control", json={"mode": "failure"}).raise_for_status()
        failed_event = client.post(
            f"{API}/events",
            headers={
                "Authorization": f"Bearer {producer_key}",
                "Idempotency-Key": f"failure-{suffix}-0001",
            },
            json={
                "type": "media.processing.completed",
                "version": 1,
                "occurred_at": datetime.now(UTC).isoformat(),
                "data": {"scenario": "dead-letter"},
            },
        )
        failed_event.raise_for_status()
        failed_delivery = find_delivery(
            client, access, organization_id, failed_event.json()["event_id"]
        )
        wait_for_status(client, access, organization_id, failed_delivery, "dead_lettered")

        client.post(f"{RECEIVER}/control", json={"mode": "success"}).raise_for_status()
        replay = client.post(
            f"{API}/organizations/{organization_id}/deliveries/{failed_delivery}/replay",
            headers={**management_headers, "Idempotency-Key": f"replay-{suffix}-0001"},
        )
        replay.raise_for_status()
        wait_for_status(client, access, organization_id, replay.json()["id"], "succeeded")
        print("Local acceptance flow passed: success, retry/DLQ, and replay succeeded.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Local acceptance flow failed: {exc}", file=sys.stderr)
        raise
