"""
app/services/campaign_service.py
================================
Campaign lifecycle and lead-management business logic.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import CampaignStatus, LeadStatus
from app.models.campaign import Campaign, CampaignLead
from app.repositories.campaign_repository import CampaignLeadRepository, CampaignRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_repository import ContactRepository
from app.schemas.campaign import CampaignCreate, CampaignUpdate

logger = structlog.get_logger(__name__)


class CampaignService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.campaigns = CampaignRepository(session)
        self.campaign_leads = CampaignLeadRepository(session)
        self.companies = CompanyRepository(session)
        self.contacts = ContactRepository(session)

    async def create_campaign(self, owner_id: uuid.UUID, data: CampaignCreate) -> Campaign:
        return await self.campaigns.create(
            owner_id=owner_id,
            name=data.name,
            description=data.description,
            icp_criteria=data.icp_criteria.model_dump(),
            max_leads=data.max_leads,
            follow_up_days=data.follow_up_days,
            max_attempts=data.max_attempts,
            from_name=data.from_name,
            from_email=data.from_email,
            reply_to_email=data.reply_to_email,
            email_provider=data.email_provider,
            value_proposition=data.value_proposition,
            tone=data.tone,
            llm_model=data.llm_model,
        )

    async def update_campaign(self, campaign_id: uuid.UUID, data: CampaignUpdate) -> Campaign:
        campaign = await self.campaigns.get_or_404(campaign_id)
        update_data = data.model_dump(exclude_unset=True, exclude_none=True)
        if "icp_criteria" in update_data and update_data["icp_criteria"]:
            update_data["icp_criteria"] = data.icp_criteria.model_dump()
        return await self.campaigns.update(campaign, **update_data)

    async def activate_campaign(self, campaign_id: uuid.UUID) -> Campaign:
        campaign = await self.campaigns.get_or_404(campaign_id)
        campaign.activate()
        await self.session.flush()
        logger.info("campaign_activated", campaign_id=str(campaign_id))
        return campaign

    async def pause_campaign(self, campaign_id: uuid.UUID) -> Campaign:
        campaign = await self.campaigns.get_or_404(campaign_id)
        campaign.pause()
        await self.session.flush()
        return campaign

    async def add_leads(self, campaign_id: uuid.UUID, company_ids: list[uuid.UUID]) -> int:
        campaign = await self.campaigns.get_or_404(campaign_id)
        added = 0
        for company_id in company_ids:
            if campaign.is_at_capacity:
                break
            existing = await self.campaign_leads.get_by_campaign_and_company(campaign_id, company_id)
            if existing:
                continue
            primary = await self.contacts.get_primary_contact(company_id)
            await self.campaign_leads.create(
                campaign_id=campaign_id,
                company_id=company_id,
                contact_id=primary.id if primary else None,
                status=LeadStatus.NEW,
            )
            campaign.increment_stat("stat_leads_added")
            added += 1
        await self.session.flush()
        logger.info("leads_added_to_campaign", campaign_id=str(campaign_id), count=added)
        return added
