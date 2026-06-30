"""
app/repositories/base.py
========================
Generic async repository base class — implements the Repository Pattern
to decouple services from SQLAlchemy query construction.

Every concrete repository (CompanyRepository, ContactRepository, etc.)
inherits from BaseRepository[ModelType] and gets CRUD + pagination for free,
while adding domain-specific query methods of its own.
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Generic async repository providing standard CRUD operations.

    Usage:
        class CompanyRepository(BaseRepository[Company]):
            def __init__(self, session: AsyncSession):
                super().__init__(Company, session)
    """

    def __init__(self, model: type[ModelType], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    async def get(self, id: uuid.UUID, *, load_relations: list[str] | None = None) -> ModelType | None:
        stmt = select(self.model).where(self.model.id == id)
        if load_relations:
            for rel in load_relations:
                stmt = stmt.options(selectinload(getattr(self.model, rel)))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_404(self, id: uuid.UUID, *, load_relations: list[str] | None = None) -> ModelType:
        obj = await self.get(id, load_relations=load_relations)
        if obj is None:
            raise LookupError(f"{self.model.__name__} with id={id} not found")
        return obj

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        order_by: Any = None,
        filters: list[Any] | None = None,
        load_relations: list[str] | None = None,
    ) -> list[ModelType]:
        stmt = select(self.model)
        if filters:
            stmt = stmt.where(*filters)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        else:
            stmt = stmt.order_by(self.model.created_at.desc())
        if load_relations:
            for rel in load_relations:
                stmt = stmt.options(selectinload(getattr(self.model, rel)))
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, *, filters: list[Any] | None = None) -> int:
        stmt = select(func.count()).select_from(self.model)
        if filters:
            stmt = stmt.where(*filters)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def create(self, **kwargs: Any) -> ModelType:
        obj = self.model(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def update(self, obj: ModelType, **kwargs: Any) -> ModelType:
        for key, value in kwargs.items():
            if value is not None and hasattr(obj, key):
                setattr(obj, key, value)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def delete(self, obj: ModelType) -> None:
        await self.session.delete(obj)
        await self.session.flush()

    async def delete_by_id(self, id: uuid.UUID) -> bool:
        obj = await self.get(id)
        if obj is None:
            return False
        await self.delete(obj)
        return True

    async def exists(self, *, filters: list[Any]) -> bool:
        stmt = select(func.count()).select_from(self.model).where(*filters)
        result = await self.session.execute(stmt)
        return result.scalar_one() > 0

    async def bulk_create(self, items: list[dict[str, Any]]) -> list[ModelType]:
        objs = [self.model(**item) for item in items]
        self.session.add_all(objs)
        await self.session.flush()
        for obj in objs:
            await self.session.refresh(obj)
        return objs
