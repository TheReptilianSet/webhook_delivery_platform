from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from webhook_platform.config.settings import Settings
from webhook_platform.shared.domain.errors import AppError


@dataclass(frozen=True)
class ValidatedDestination:
    url: str
    host: str
    port: int


def is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    prohibited = (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_multicast
        or address.is_reserved
    )
    return bool(address.is_global and not prohibited)


def validate_url_syntax(url: str, settings: Settings) -> ValidatedDestination:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise AppError(
            "unsafe_destination", "Endpoint URL is not allowed", status_code=422
        ) from exc
    if parsed.username or parsed.password or parsed.fragment or not parsed.hostname:
        raise AppError("unsafe_destination", "Endpoint URL is not allowed", status_code=422)
    normalized = urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, "")
    )
    test_base = settings.test_receiver_url.rstrip("/")
    if (
        settings.environment in {"development", "test"}
        and settings.allow_test_receiver
        and normalized.rstrip("/") == test_base
    ):
        return ValidatedDestination(normalized, parsed.hostname, port or 80)
    if parsed.scheme.lower() != "https" or (port or 443) != 443:
        raise AppError("unsafe_destination", "Endpoint URL is not allowed", status_code=422)
    return ValidatedDestination(normalized, parsed.hostname, 443)
