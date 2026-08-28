from __future__ import annotations

import hashlib
import hmac

import pytest

from webhook_platform.config.settings import Settings
from webhook_platform.shared.application.crypto import CiphertextUnavailable
from webhook_platform.shared.infrastructure.security import (
    AesGcmCipher,
    api_key_digest,
    new_api_key,
    parse_api_key,
    verification_signature,
    webhook_signature,
)


def test_aes_gcm_round_trip_with_resource_aad() -> None:
    cipher = AesGcmCipher(Settings(environment="test"))
    ciphertext, nonce, version = cipher.encrypt(b"secret", b"endpoint-1")
    assert version == 1
    assert cipher.decrypt(ciphertext, nonce, b"endpoint-1") == b"secret"
    with pytest.raises(CiphertextUnavailable):
        cipher.decrypt(ciphertext, nonce, b"endpoint-2")


def test_aes_gcm_uses_unique_nonce() -> None:
    cipher = AesGcmCipher(Settings(environment="test"))
    first = cipher.encrypt(b"secret", b"resource")
    second = cipher.encrypt(b"secret", b"resource")
    assert first[1] != second[1]
    assert first[0] != second[0]


def test_webhook_signature_matches_golden_vector() -> None:
    material = b'1700000000.event.delivery.{"a":1}'
    expected = "v1=" + hmac.new(b"secret", material, hashlib.sha256).hexdigest()
    assert webhook_signature(b"secret", "1700000000", "event", "delivery", b'{"a":1}') == expected


def test_verification_signature_matches_contract() -> None:
    material = b"1700000000.verification.{}"
    expected = "v1=" + hmac.new(b"secret", material, hashlib.sha256).hexdigest()
    assert verification_signature(b"secret", "1700000000", "verification", b"{}") == expected


def test_api_key_is_parseable_and_digest_is_peppered() -> None:
    settings = Settings(environment="test")
    plaintext, prefix, digest = new_api_key(settings)
    parsed = parse_api_key(plaintext)
    assert parsed is not None
    assert parsed[0] == prefix
    assert api_key_digest(settings, parsed[1]) == digest
    assert parsed[1] not in digest
