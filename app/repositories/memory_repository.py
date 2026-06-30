"""
app/repositories/memory_repository.py
=====================================
ConversationMemory data access — including pgvector cosine similarity search.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import ConversationMemory
from app.repositories.base import BaseRepository


class MemoryRepository(BaseRepository[ConversationMemory]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ConversationMemory, session)

    async def get_by_company(
        self, company_id: uuid.UUID, memory_type: str | None = None, limit: int = 20
    ) -> list[ConversationMemory]:
        stmt = select(ConversationMemory).where(ConversationMemory.company_id == company_id)
        if memory_type:
            stmt = stmt.where(ConversationMemory.memory_type == memory_type)
        stmt = stmt.order_by(ConversationMemory.importance.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def semantic_search(
        self,
        company_id: uuid.UUID,
        query_embedding: list[float],
        *,
        memory_type: str | None = None,
        top_k: int = 5,
    ) -> list[ConversationMemory]:
        """
        Cosine-similarity search scoped to a single company's memory.
        Uses pgvector's <=> operator (cosine distance — lower is more similar).
        """
        stmt = (
            select(ConversationMemory)
            .where(ConversationMemory.company_id == company_id)
            .where(ConversationMemory.embedding.is_not(None))
        )
        if memory_type:
            stmt = stmt.where(ConversationMemory.memory_type == memory_type)
        stmt = stmt.order_by(
            ConversationMemory.embedding.cosine_distance(query_embedding)
        ).limit(top_k)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_expired(self) -> int:
        from datetime import datetime, timezone

        stmt = select(ConversationMemory).where(
            ConversationMemory.expires_at.is_not(None),
            ConversationMemory.expires_at < datetime.now(timezone.utc),
        )
        result = await self.session.execute(stmt)
        expired = list(result.scalars().all())
        for memory in expired:
            await self.session.delete(memory)
        await self.session.flush()
        return len(expired)
