"""Repository base.

Workspace scoping is enforced here rather than in routers. A router that forgets
a filter is one review away from a cross-tenant leak; a repository that cannot
be constructed without a workspace makes the leak hard to write in the first
place.

`tests/test_workspace_scoping.py` reflects over every subclass and fails if a
public query method does not apply the filter — the rule is checked mechanically,
not remembered.
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class WorkspaceScopedRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, db: AsyncSession, workspace_id: uuid.UUID) -> None:
        if workspace_id is None:  # pragma: no cover - defensive
            raise ValueError("workspace_id is required")
        self.db = db
        self.workspace_id = workspace_id

    def scoped(self) -> Select[tuple[ModelT]]:
        """Every read starts here. There is no unscoped entry point on purpose."""
        return select(self.model).where(
            self.model.workspace_id == self.workspace_id  # type: ignore[attr-defined]
        )

    async def get(self, record_id: uuid.UUID) -> ModelT | None:
        """Returns None for a record in another workspace, exactly as it would
        for one that does not exist. Distinguishing the two would confirm the
        existence of records the caller cannot see."""
        return await self.db.scalar(
            self.scoped().where(self.model.id == record_id)  # type: ignore[attr-defined]
        )

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[ModelT]:
        result = await self.db.execute(self.scoped().limit(limit).offset(offset))
        return list(result.scalars())

    def add(self, **values: Any) -> ModelT:
        """Stamps the workspace so a caller cannot create a record in another."""
        instance = self.model(**{**values, "workspace_id": self.workspace_id})
        self.db.add(instance)
        return instance
