from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pwdlib import PasswordHash

from webhook_platform.config.settings import Settings
from webhook_platform.shared.application.crypto import CiphertextUnavailable

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(settings: Settings, user_id: str) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.access_ttl_seconds)
    payload = {
        "sub": user_id,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": datetime.now(UTC),
        "exp": expires_at,
        "type": "access",
    }
    encoded = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    return encoded, expires_at


def decode_access_token(settings: Settings, token: str) -> str:
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )
    if payload.get("type") != "access" or not isinstance(payload.get("sub"), str):
        raise jwt.InvalidTokenError
    return str(payload["sub"])


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def new_api_key(settings: Settings) -> tuple[str, str, str]:
    prefix = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    environment_prefix = "whk_live_" if settings.environment == "production" else "whk_test_"
    plaintext = f"{environment_prefix}{prefix}.{secret}"
    return plaintext, prefix, api_key_digest(settings, secret)


class DefaultApiKeyIssuer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def issue(self) -> tuple[str, str, str]:
        return new_api_key(self.settings)


def api_key_digest(settings: Settings, secret: str) -> str:
    return hmac.new(
        settings.api_key_pepper.get_secret_value().encode(),
        secret.encode(),
        hashlib.sha256,
    ).hexdigest()


def parse_api_key(value: str) -> tuple[str, str] | None:
    if value.startswith("whk_live_"):
        value = value[len("whk_live_") :]
    elif value.startswith("whk_test_"):
        value = value[len("whk_test_") :]
    else:
        return None
    prefix, separator, secret = value.partition(".")
    return (prefix, secret) if separator and prefix and secret else None


class AesGcmCipher:
    def __init__(self, settings: Settings) -> None:
        self._key = base64.b64decode(settings.encryption_key.get_secret_value(), validate=True)
        self.key_version = settings.encryption_key_version
        self._cipher = AESGCM(self._key)

    def encrypt(self, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes, int]:
        nonce = secrets.token_bytes(12)
        return self._cipher.encrypt(nonce, plaintext, aad), nonce, self.key_version

    def decrypt(self, ciphertext: bytes, nonce: bytes, aad: bytes) -> bytes:
        try:
            return self._cipher.decrypt(nonce, ciphertext, aad)
        except InvalidTag as exc:
            raise CiphertextUnavailable from exc


def webhook_signature(
    secret: bytes, timestamp: str, event_id: str, delivery_id: str, raw_body: bytes
) -> str:
    material = b".".join([timestamp.encode(), event_id.encode(), delivery_id.encode(), raw_body])
    return "v1=" + hmac.new(secret, material, hashlib.sha256).hexdigest()


def verification_signature(secret: bytes, timestamp: str, verification_id: str, body: bytes) -> str:
    material = b".".join([timestamp.encode(), verification_id.encode(), body])
    return "v1=" + hmac.new(secret, material, hashlib.sha256).hexdigest()
