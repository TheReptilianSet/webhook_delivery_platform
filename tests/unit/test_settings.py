from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from webhook_platform.config.settings import Settings


def test_development_settings_accept_exact_local_receiver() -> None:
    settings = Settings(environment="test", allow_test_receiver=True)
    assert settings.test_receiver_url == "http://test-receiver:8080"


def test_production_rejects_test_receiver_exception() -> None:
    with pytest.raises(ValidationError, match="development receiver"):
        Settings(environment="production")


def test_production_accepts_distinct_strong_secrets() -> None:
    settings = Settings(
        environment="production",
        allow_test_receiver=False,
        accept_test_api_keys=False,
        jwt_secret="j" * 40,
        api_key_pepper="p" * 40,
        encryption_key=base64.b64encode(b"b" * 32).decode(),
        public_base_url="https://hooks.example.com",
        database_url="postgresql+asyncpg://user:pass@db:5432/webhook?ssl=require",
        broker_url="amqps://user:pass@broker:5671//",
        allow_local_browser_origins=False,
    )
    assert settings.environment == "production"


def test_invalid_encryption_key_fails_closed() -> None:
    with pytest.raises(ValidationError, match="encryption_key"):
        Settings(encryption_key="not-base64")


@pytest.mark.parametrize(
    "override",
    [
        {},
        {"jwt_secret": "j" * 40},
        {"jwt_secret": "j" * 40, "api_key_pepper": "p" * 40},
    ],
)
def test_production_rejects_development_secrets(override: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "environment": "production",
                "allow_test_receiver": False,
                "accept_test_api_keys": False,
                "public_base_url": "https://hooks.example.com",
                "database_url": "postgresql+asyncpg://user:pass@db:5432/webhook?ssl=require",
                "broker_url": "amqps://user:pass@broker:5671//",
                "allow_local_browser_origins": False,
                **override,
            }
        )


def test_production_rejects_local_browser_origins() -> None:
    with pytest.raises(ValidationError, match="local browser origins"):
        Settings.model_validate(
            {
                "environment": "production",
                "allow_test_receiver": False,
                "accept_test_api_keys": False,
                "public_base_url": "https://hooks.example.com",
                "database_url": "postgresql+asyncpg://user:pass@db:5432/webhook?ssl=require",
                "broker_url": "amqps://user:pass@broker:5671//",
                "jwt_secret": "j" * 40,
                "api_key_pepper": "p" * 40,
                "encryption_key": base64.b64encode(b"c" * 32).decode(),
            }
        )
