"""
app/repositories/campaign_repository.py
=======================================
Campaign and CampaignLead data access methods.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.campaign import Campaign, CampaignLead
from app.models.base import CampaignStatus
from app.repositories.base import BaseRepository


class CampaignRepository(BaseRepository[Campaign]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Campaign, session)

    async def get_active(self) -> list[Campaign]:
        stmt = select(Campaign).where(Campaign.status == CampaignStatus.ACTIVE)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_with_stats(self, campaign_id: uuid.UUID) -> Campaign | None:
        return await self.get(campaign_id)


class CampaignLeadRepository(BaseRepository[CampaignLead]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(CampaignLead, session)

    async def get_by_campaign_and_company(
        self, campaign_id: uuid.UUID, company_id: uuid.UUID
    ) -> CampaignLead | None:
        stmt = select(CampaignLead).where(
            and_(
                CampaignLead.campaign_id == campaign_id,
                CampaignLead.company_id == company_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_due_for_followup(self, limit: int = 100) -> list[CampaignLead]:
        """
        Leads whose next_follow_up timestamp has passed and haven't been
        stopped (replied, unsubscribed, max attempts reached).
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(CampaignLead)
            .where(CampaignLead.next_follow_up <= now)
            .where(CampaignLead.stopped_at.is_(None))
            .options(
                selectinload(CampaignLead.company),
                selectinload(CampaignLead.contact),
                selectinload(CampaignLead.campaign),
            )
            .order_by(CampaignLead.next_follow_up)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_campaign(
        self, campaign_id: uuid.UUID, *, offset: int = 0, limit: int = 50
    ) -> list[CampaignLead]:
        stmt = (
            select(CampaignLead)
            .where(CampaignLead.campaign_id == campaign_id)
            .options(selectinload(CampaignLead.company), selectinload(CampaignLead.contact))
            .order_by(CampaignLead.added_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
