from __future__ import annotations

import pytest

from webhook_platform.events.domain.canonical_json import canonicalize, event_fingerprint
from webhook_platform.shared.domain.errors import AppError


def test_canonical_json_is_stable_utf8_and_sorted() -> None:
    first = canonicalize({"z": 1, "a": "Привет"}, size_limit=1024, depth_limit=20)
    second = canonicalize({"a": "Привет", "z": 1}, size_limit=1024, depth_limit=20)
    assert first == second == '{"a":"Привет","z":1}'.encode()


def test_canonical_json_rejects_non_finite_number() -> None:
    with pytest.raises(AppError) as error:
        canonicalize({"value": float("nan")}, size_limit=1024, depth_limit=20)
    assert error.value.code == "invalid_event"


def test_canonical_json_rejects_excessive_depth() -> None:
    with pytest.raises(AppError) as error:
        canonicalize({"a": {"b": {"c": 1}}}, size_limit=1024, depth_limit=2)
    assert error.value.code == "invalid_event"


def test_canonical_json_rejects_oversize() -> None:
    with pytest.raises(AppError) as error:
        canonicalize({"value": "long"}, size_limit=4, depth_limit=20)
    assert error.value.code == "event_too_large"


def test_fingerprint_is_tenant_and_key_bound() -> None:
    body = b"{}"
    assert event_fingerprint("org-a", "key", body) != event_fingerprint("org-b", "key", body)
    assert event_fingerprint("org", "key-a", body) != event_fingerprint("org", "key-b", body)
