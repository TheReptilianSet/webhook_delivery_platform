from __future__ import annotations

from pydantic import BaseModel


class PageResponse[ItemT](BaseModel):
    items: list[ItemT]
    next_cursor: str | None = None
