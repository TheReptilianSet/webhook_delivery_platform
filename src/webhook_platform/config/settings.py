from __future__ import annotations

import base64
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "development-jwt-secret-change-me-32-bytes"
DEFAULT_API_KEY_PEPPER = "development-api-key-pepper-change-me"
DEFAULT_ENCRYPTION_KEY = "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE="


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WEBHOOK_PLATFORM_", env_nested_delimiter="__", frozen=True
    )

    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8000"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "postgresql+asyncpg://webhook:webhook@localhost:5432/webhook"
    database_pool_size: int = 10
    database_max_overflow: int = 10
    database_pool_timeout_seconds: float = 5.0
    broker_url: str = "amqp://webhook:webhook@localhost:5672//"
    broker_exchange: str = "webhook.delivery"
    broker_queue: str = "webhook.delivery.v1"
    broker_routing_key: str = "delivery.execute.v1"
    broker_dlx: str = "webhook.delivery.dlx"
    broker_dead_queue: str = "webhook.delivery.dead.v1"
    publisher_confirm_timeout_seconds: float = 5.0
    jwt_secret: SecretStr = SecretStr(DEFAULT_JWT_SECRET)
    jwt_issuer: str = "webhook-platform"
    jwt_audience: str = "webhook-platform-api"
    access_ttl_seconds: int = 900
    refresh_ttl_seconds: int = 2_592_000
    api_key_pepper: SecretStr = SecretStr(DEFAULT_API_KEY_PEPPER)
    api_key_digest_version: int = 1
    encryption_key: SecretStr = SecretStr(DEFAULT_ENCRYPTION_KEY)
    encryption_key_version: int = 1
    event_body_limit: int = 262_144
    event_json_depth_limit: int = 20
    endpoint_limit: int = 100
    backlog_limit: int = 10_000
    producer_rate_per_second: float = 50.0
    producer_rate_burst: int = 100
    management_rate_per_second: float = 10.0
    management_rate_burst: int = 10
    login_rate_per_minute: int = 5
    response_preview_limit: int = 4096
    worker_concurrency: int = 8
    worker_prefetch: int = 1
    delivery_lease_seconds: int = 30
    outbox_batch_size: int = 100
    retry_batch_size: int = 100
    http_connect_timeout: float = 3.0
    http_read_timeout: float = 3.0
    http_write_timeout: float = 3.0
    http_pool_timeout: float = 3.0
    http_total_timeout: float = 10.0
    max_delivery_attempts: int = 6
    retry_delays_seconds: tuple[int, ...] = (30, 120, 600, 3600, 21600)
    retry_jitter_ratio: float = 0.2
    metadata_retention_days: int = 30
    preview_retention_days: int = 7
    audit_retention_days: int = 90
    allow_test_receiver: bool = True
    test_receiver_url: str = "http://test-receiver:8080"
    accept_test_api_keys: bool = True
    cors_allow_origins: tuple[str, ...] = Field(default_factory=tuple)
    cors_allow_credentials: bool = False
    allow_local_browser_origins: bool = True

    @model_validator(mode="after")
    def validate_security_profile(self) -> Settings:
        try:
            if len(base64.b64decode(self.encryption_key.get_secret_value(), validate=True)) != 32:
                raise ValueError("encryption_key must be a base64-encoded 32-byte key")
        except ValueError as exc:
            raise ValueError("encryption_key must be valid base64") from exc
        if self.environment == "production":
            if self.debug:
                raise ValueError("debug is forbidden in production")
            if self.allow_test_receiver or self.accept_test_api_keys:
                raise ValueError(
                    "development receiver and test API keys are forbidden in production"
                )
            jwt_secret = self.jwt_secret.get_secret_value()
            api_key_pepper = self.api_key_pepper.get_secret_value()
            encryption_key = self.encryption_key.get_secret_value()
            if jwt_secret == DEFAULT_JWT_SECRET or len(jwt_secret) < 32:
                raise ValueError("jwt_secret is too short for production")
            if api_key_pepper == DEFAULT_API_KEY_PEPPER or len(api_key_pepper) < 32:
                raise ValueError("api_key_pepper is too short for production")
            if encryption_key == DEFAULT_ENCRYPTION_KEY:
                raise ValueError("development encryption_key is forbidden in production")
            if not self.public_base_url.startswith("https://"):
                raise ValueError("public_base_url must use HTTPS in production")
            database_query = parse_qs(urlsplit(self.database_url).query)
            database_ssl = database_query.get("ssl", database_query.get("sslmode", []))
            if not database_ssl or database_ssl[0] not in {"require", "verify-ca", "verify-full"}:
                raise ValueError("database TLS is required in production")
            if not self.broker_url.startswith("amqps://"):
                raise ValueError("broker TLS is required in production")
            if "*" in self.cors_allow_origins and self.cors_allow_credentials:
                raise ValueError("wildcard CORS is forbidden in production")
            if self.allow_local_browser_origins:
                raise ValueError("local browser origins are forbidden in production")
            if any(
                urlsplit(origin).hostname in {"localhost", "127.0.0.1", "::1"}
                for origin in self.cors_allow_origins
            ):
                raise ValueError("localhost CORS origins are forbidden in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
