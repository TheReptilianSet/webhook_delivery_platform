from __future__ import annotations

import base64

import pytest

from webhook_platform.config.settings import Settings
from webhook_platform.endpoints.domain.network import is_public_address, validate_url_syntax
from webhook_platform.shared.domain.errors import AppError


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "192.0.2.1",
        "::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "2001:db8::1",
    ],
)
def test_prohibited_addresses_are_not_public(address: str) -> None:
    assert not is_public_address(address)


@pytest.mark.parametrize("address", ["1.1.1.1", "8.8.8.8", "2606:4700:4700::1111"])
def test_global_addresses_are_public(address: str) -> None:
    assert is_public_address(address)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/hook",
        "https://user:password@example.com/hook",
        "https://example.com:8443/hook",
        "https://example.com/hook#fragment",
        "file:///etc/passwd",
        "//example.com/hook",
    ],
)
def test_production_url_syntax_rejects_unsafe_forms(url: str) -> None:
    settings = Settings(
        environment="production",
        allow_test_receiver=False,
        accept_test_api_keys=False,
        allow_local_browser_origins=False,
        public_base_url="https://webhooks.example.com",
        database_url="postgresql+asyncpg://app:secret@db.example.com/webhook?ssl=verify-full",
        broker_url="amqps://app:secret@rabbit.example.com//",
        jwt_secret="j" * 40,
        api_key_pepper="p" * 40,
        encryption_key=base64.b64encode(b"production-encryption-key-000010").decode(),
    )
    with pytest.raises(AppError) as error:
        validate_url_syntax(url, settings)
    assert error.value.code == "unsafe_destination"


def test_development_allows_only_exact_receiver() -> None:
    settings = Settings(environment="test", allow_test_receiver=True)
    destination = validate_url_syntax("http://test-receiver:8080", settings)
    assert destination.host == "test-receiver"
    with pytest.raises(AppError):
        validate_url_syntax("http://test-receiver:8081", settings)
