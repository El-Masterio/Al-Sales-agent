"""
app/repositories/email_repository.py
====================================
Email and EmailEvent data access methods.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import Email, EmailEvent
from app.models.base import EmailStatus
from app.repositories.base import BaseRepository


class EmailRepository(BaseRepository[Email]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Email, session)

    async def get_by_tracking_id(self, tracking_id: uuid.UUID) -> Email | None:
        stmt = select(Email).where(Email.tracking_id == tracking_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_message_id(self, message_id: str) -> Email | None:
        stmt = select(Email).where(Email.message_id == message_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_thread(self, thread_id: str) -> list[Email]:
        stmt = (
            select(Email)
            .where(Email.thread_id == thread_id)
            .order_by(Email.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_company(self, company_id: uuid.UUID) -> list[Email]:
        stmt = (
            select(Email)
            .where(Email.company_id == company_id)
            .order_by(Email.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_sent_today(self, campaign_id: uuid.UUID | None = None) -> int:
        """Used to enforce daily send limits."""
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        conditions = [Email.sent_at >= today_start, Email.status != EmailStatus.DRAFT]
        if campaign_id:
            conditions.append(Email.campaign_id == campaign_id)
        stmt = select(func.count()).select_from(Email).where(and_(*conditions))
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count_sent_this_hour(self, campaign_id: uuid.UUID | None = None) -> int:
        hour_start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        conditions = [Email.sent_at >= hour_start, Email.status != EmailStatus.DRAFT]
        if campaign_id:
            conditions.append(Email.campaign_id == campaign_id)
        stmt = select(func.count()).select_from(Email).where(and_(*conditions))
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def add_event(
        self,
        email_id: uuid.UUID,
        event_type: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        click_url: str | None = None,
        raw_payload: dict | None = None,
    ) -> EmailEvent:
        event = EmailEvent(
            email_id=email_id,
            event_type=event_type,
            ip_address=ip_address,
            user_agent=user_agent,
            click_url=click_url,
            raw_payload=raw_payload,
        )
        self.session.add(event)
        await self.session.flush()
        return event
