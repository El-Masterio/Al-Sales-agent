"""
app/repositories/meeting_repository.py
======================================
Meeting data access methods.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import MeetingStatus
from app.models.meeting import Meeting
from app.repositories.base import BaseRepository


class MeetingRepository(BaseRepository[Meeting]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Meeting, session)

    async def get_by_google_event_id(self, google_event_id: str) -> Meeting | None:
        stmt = select(Meeting).where(Meeting.google_event_id == google_event_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_upcoming(self, rep_id: uuid.UUID | None = None, limit: int = 50) -> list[Meeting]:
        now = datetime.now(timezone.utc)
        conditions = [
            Meeting.starts_at > now,
            Meeting.status.in_([MeetingStatus.PROPOSED, MeetingStatus.CONFIRMED]),
        ]
        if rep_id:
            conditions.append(Meeting.assigned_rep_id == rep_id)
        stmt = (
            select(Meeting)
            .where(and_(*conditions))
            .order_by(Meeting.starts_at)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_needing_reminders(self) -> list[Meeting]:
        """Confirmed meetings within the next 24h that haven't had reminders sent."""
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(hours=24)
        stmt = (
            select(Meeting)
            .where(Meeting.status == MeetingStatus.CONFIRMED)
            .where(Meeting.starts_at > now)
            .where(Meeting.starts_at <= window_end)
            .where(
                (Meeting.reminder_24h_sent.is_(False))
                | (Meeting.reminder_1h_sent.is_(False))
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_rep_busy_blocks(
        self, rep_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[Meeting]:
        """Existing meetings for conflict-checking when proposing slots."""
        stmt = (
            select(Meeting)
            .where(Meeting.assigned_rep_id == rep_id)
            .where(Meeting.status.in_([MeetingStatus.PROPOSED, MeetingStatus.CONFIRMED]))
            .where(Meeting.starts_at < end)
            .where(Meeting.ends_at > start)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
