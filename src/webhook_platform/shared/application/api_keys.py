from __future__ import annotations

from typing import Protocol


class ApiKeyIssuer(Protocol):
    def issue(self) -> tuple[str, str, str]: ...
