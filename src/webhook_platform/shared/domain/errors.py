from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class NotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__("resource_not_found", "Resource not found", status_code=404)


class ForbiddenError(AppError):
    def __init__(self) -> None:
        super().__init__("forbidden", "Insufficient permissions", status_code=403)
