"""
app/repositories/reply_repository.py
====================================
Reply data access methods.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import ReplyClassification
from app.models.reply import Reply
from app.repositories.base import BaseRepository


class ReplyRepository(BaseRepository[Reply]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Reply, session)

    async def get_by_message_id(self, message_id: str) -> Reply | None:
        stmt = select(Reply).where(Reply.message_id == message_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_unclassified(self, limit: int = 50) -> list[Reply]:
        stmt = (
            select(Reply)
            .where(Reply.classification == ReplyClassification.UNCLASSIFIED)
            .order_by(Reply.received_at)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_pending_review(self, limit: int = 50) -> list[Reply]:
        stmt = (
            select(Reply)
            .where(Reply.reviewed.is_(False))
            .where(Reply.classification != ReplyClassification.UNCLASSIFIED)
            .order_by(Reply.received_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_company(self, company_id: uuid.UUID) -> list[Reply]:
        stmt = (
            select(Reply)
            .where(Reply.company_id == company_id)
            .order_by(Reply.received_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_classification_breakdown(self) -> dict[str, int]:
        from sqlalchemy import func

        stmt = select(Reply.classification, func.count()).group_by(Reply.classification)
        result = await self.session.execute(stmt)
        return {cls: count for cls, count in result.all()}
