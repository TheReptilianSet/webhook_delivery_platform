from __future__ import annotations

from typing import Protocol


class UnitOfWork(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
