"""
app/repositories/company_repository.py
======================================
Company-specific data access methods on top of BaseRepository.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import LeadStatus
from app.models.company import Company
from app.repositories.base import BaseRepository
from app.schemas.company import CompanySearchFilters


class CompanyRepository(BaseRepository[Company]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Company, session)

    async def get_by_domain(self, domain: str) -> Company | None:
        """Used for deduplication during lead generation."""
        stmt = select(Company).where(Company.domain == domain)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_contacts(self, company_id: uuid.UUID) -> Company | None:
        stmt = (
            select(Company)
            .where(Company.id == company_id)
            .options(selectinload(Company.contacts))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def search(
        self,
        filters: CompanySearchFilters,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Company], int]:
        """Search companies with filters, returns (results, total_count)."""
        conditions: list[Any] = []

        if filters.industries:
            conditions.append(Company.industry.in_(filters.industries))
        if filters.company_sizes:
            conditions.append(Company.company_size.in_(filters.company_sizes))
        if filters.lead_statuses:
            conditions.append(Company.lead_status.in_(filters.lead_statuses))
        if filters.tech_stack:
            # overlap operator — any of these techs present in company.tech_stack
            conditions.append(Company.tech_stack.overlap(filters.tech_stack))
        if filters.min_icp_score is not None:
            conditions.append(Company.icp_score >= filters.min_icp_score)
        if filters.assigned_to_id is not None:
            conditions.append(Company.assigned_to_id == filters.assigned_to_id)
        if filters.search_query:
            conditions.append(Company.name.ilike(f"%{filters.search_query}%"))

        base_stmt = select(Company)
        count_stmt = select(func.count()).select_from(Company)
        if conditions:
            base_stmt = base_stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))

        total = (await self.session.execute(count_stmt)).scalar_one()

        result_stmt = (
            base_stmt.order_by(Company.icp_score.desc().nullslast(), Company.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        results = (await self.session.execute(result_stmt)).scalars().all()
        return list(results), total

    async def get_unresearched(self, limit: int = 50) -> list[Company]:
        """Companies that need AI research before outreach can begin."""
        stmt = (
            select(Company)
            .where(Company.last_researched_at.is_(None))
            .where(Company.lead_status == LeadStatus.NEW)
            .order_by(Company.created_at)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_stale_research(self, days: int = 90, limit: int = 50) -> list[Company]:
        """Companies whose research is old and should be refreshed."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(Company)
            .where(Company.last_researched_at < cutoff)
            .where(Company.lead_status.notin_([
                LeadStatus.CLOSED_WON, LeadStatus.CLOSED_LOST,
                LeadStatus.NOT_INTERESTED, LeadStatus.UNSUBSCRIBED,
            ]))
            .order_by(Company.last_researched_at)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_ready_for_outreach(self, campaign_id: uuid.UUID, limit: int = 50) -> list[Company]:
        """
        Companies that are researched, have a primary contact with a verified
        email, and are not yet in this campaign.
        """
        from app.models.campaign import CampaignLead
        from app.models.contact import Contact

        already_in_campaign = (
            select(CampaignLead.company_id)
            .where(CampaignLead.campaign_id == campaign_id)
        )

        stmt = (
            select(Company)
            .join(Contact, Contact.company_id == Company.id)
            .where(Company.lead_status == LeadStatus.READY_TO_CONTACT)
            .where(Contact.is_primary_contact.is_(True))
            .where(Contact.email.is_not(None))
            .where(Contact.email_verified.is_(True))
            .where(Contact.unsubscribed.is_(False))
            .where(Company.id.notin_(already_in_campaign))
            .order_by(Company.icp_score.desc().nullslast())
            .limit(limit)
            .distinct()
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def bulk_upsert_by_domain(self, companies: list[dict[str, Any]]) -> list[Company]:
        """
        Insert companies discovered by lead generation, skipping any whose
        domain already exists. Returns the list of newly created companies.
        """
        created: list[Company] = []
        for data in companies:
            domain = data.get("domain")
            if domain:
                existing = await self.get_by_domain(domain)
                if existing:
                    continue
            obj = await self.create(**data)
            created.append(obj)
        return created

    async def get_pipeline_counts(self) -> dict[str, int]:
        """Count of companies grouped by lead_status — for pipeline view."""
        stmt = select(Company.lead_status, func.count()).group_by(Company.lead_status)
        result = await self.session.execute(stmt)
        return {status: count for status, count in result.all()}
