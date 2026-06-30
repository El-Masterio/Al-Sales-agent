"""
app/services/research_service.py
================================
Orchestrates the full research pipeline for a single company:
  1. Scrape company website (ScraperService)
  2. Detect tech stack from raw HTML
  3. Pass scraped text to ResearchAgent (LLM)
  4. Persist structured research results back onto the Company row
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.research_agent import research_agent
from app.models.base import LeadStatus
from app.models.company import Company
from app.repositories.company_repository import CompanyRepository
from app.services.scraper_service import ScraperService

logger = structlog.get_logger(__name__)


class ResearchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.companies = CompanyRepository(session)

    async def research_company(
        self, company_id: uuid.UUID, value_proposition: str | None = None
    ) -> Company:
        company = await self.companies.get_or_404(company_id)

        if not company.website:
            logger.warning("research_skipped_no_website", company_id=str(company_id))
            await self.companies.update(company, lead_status=LeadStatus.RESEARCHING)
            return company

        await self.companies.update(company, lead_status=LeadStatus.RESEARCHING)

        # ── Scrape ────────────────────────────────────────────────────────────
        async with ScraperService() as scraper:
            scraped_content = await scraper.scrape_company_site(company.website, max_pages=5)
            homepage = await scraper.scrape_url(company.website)
            tech_stack = scraper.detect_tech_stack(homepage.html) if homepage else []

        if not scraped_content:
            logger.warning("research_scrape_empty", company_id=str(company_id))
            await self.companies.update(
                company,
                lead_status=LeadStatus.NEW,
                last_researched_at=datetime.now(timezone.utc),
            )
            return company

        # ── AI Research ───────────────────────────────────────────────────────
        result, llm_response = await research_agent.research_company(
            company_name=company.name,
            website=company.website,
            scraped_content=scraped_content,
            our_value_proposition=value_proposition,
        )

        merged_tech_stack = list(set((company.tech_stack or []) + tech_stack + result.tech_stack))

        # ── Persist ───────────────────────────────────────────────────────────
        updated = await self.companies.update(
            company,
            description=result.description,
            products_summary=result.products_summary,
            pain_points=result.pain_points,
            tech_stack=merged_tech_stack,
            value_proposition=result.value_proposition,
            icp_score=result.icp_score,
            employee_count=result.estimated_employee_count or company.employee_count,
            last_researched_at=datetime.now(timezone.utc),
            lead_status=LeadStatus.READY_TO_CONTACT if company.contacts else LeadStatus.NEW,
            research_version=company.research_version + 1,
        )

        logger.info(
            "company_research_complete",
            company_id=str(company_id),
            icp_score=result.icp_score,
            tokens_used=llm_response.prompt_tokens + llm_response.completion_tokens,
        )

        return updated

    async def bulk_research_unresearched(self, limit: int = 50, value_proposition: str | None = None) -> int:
        companies = await self.companies.get_unresearched(limit=limit)
        completed = 0
        for company in companies:
            try:
                await self.research_company(company.id, value_proposition)
                completed += 1
            except Exception as exc:
                logger.error(
                    "bulk_research_company_failed",
                    company_id=str(company.id),
                    error=str(exc),
                )
        return completed
