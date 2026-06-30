"""
app/services/lead_generation_service.py
=======================================
Lead generation orchestration: searches for companies matching ICP criteria,
scrapes their websites, enriches contact data, and persists deduplicated
Company + Contact records.

Search providers:
  - Google Custom Search API (general company discovery via search operators)
  - Crunchbase (funding-stage / industry filtering)

This service does NOT call the LLM directly for research — that's the
ResearchAgent's job, invoked by a separate Celery task after a company
is created here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
import structlog
import tldextract
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.models.base import LeadStatus
from app.models.company import Company
from app.models.contact import Contact
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_repository import ContactRepository
from app.schemas.company import ICPCriteria
from app.services.enrichment_service import EnrichmentService

logger = structlog.get_logger(__name__)


@dataclass
class DiscoveredCompany:
    name: str
    website: str
    domain: str
    industry: str | None = None
    snippet: str | None = None


class LeadGenerationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.companies = CompanyRepository(session)
        self.contacts = ContactRepository(session)
        self._http = httpx.AsyncClient(timeout=15.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── Discovery ─────────────────────────────────────────────────────────────

    def _build_search_queries(self, criteria: ICPCriteria) -> list[str]:
        """
        Build Google search queries from ICP criteria using search operators
        to surface company websites (not directories or news articles).
        """
        queries = []
        base_terms = criteria.keywords or criteria.industries

        for term in base_terms or ["B2B SaaS company"]:
            for title in (criteria.target_titles or [""]):
                query_parts = [f'"{term}"', "company", "-jobs", "-careers"]
                if title:
                    query_parts.append(f'"{title}"')
                if criteria.target_countries:
                    query_parts.append(criteria.target_countries[0])
                queries.append(" ".join(query_parts))

        return queries[:10]   # cap query fan-out

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def _google_search(self, query: str, num_results: int = 10) -> list[dict]:
        """
        Uses Google Custom Search JSON API.
        Requires GOOGLE_AI_API_KEY reused as CSE key + a configured CSE ID
        (in production, separate keys would be used — kept consolidated here
        for brevity; swap for a dedicated GOOGLE_CSE_API_KEY / GOOGLE_CSE_ID
        pair in production .env).
        """
        if not settings.GOOGLE_AI_API_KEY:
            logger.debug("google_search_not_configured")
            return []

        try:
            response = await self._http.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": settings.GOOGLE_AI_API_KEY,
                    "cx": "",  # CSE ID — must be configured separately
                    "q": query,
                    "num": min(num_results, 10),
                },
            )
            response.raise_for_status()
            return response.json().get("items", [])
        except httpx.HTTPStatusError as exc:
            logger.warning("google_search_failed", query=query, status=exc.response.status_code)
            return []
        except Exception as exc:
            logger.error("google_search_unexpected_error", query=query, error=str(exc))
            return []

    def _extract_domain(self, url: str) -> str:
        ext = tldextract.extract(url)
        return f"{ext.domain}.{ext.suffix}"

    def _parse_search_result(self, item: dict) -> DiscoveredCompany | None:
        link = item.get("link", "")
        if not link:
            return None

        domain = self._extract_domain(link)
        # Filter out obvious non-company domains (directories, social media, news)
        excluded_domains = {
            "linkedin.com", "facebook.com", "twitter.com", "x.com",
            "wikipedia.org", "youtube.com", "indeed.com", "glassdoor.com",
            "crunchbase.com", "bloomberg.com", "forbes.com",
        }
        if domain in excluded_domains:
            return None

        title = item.get("title", "")
        # Clean common title suffixes like " | Home" or " - Official Site"
        name = re.split(r"[\|\-–—]", title)[0].strip()

        return DiscoveredCompany(
            name=name or domain,
            website=f"https://{domain}",
            domain=domain,
            snippet=item.get("snippet"),
        )

    async def discover_companies(self, criteria: ICPCriteria, max_companies: int = 50) -> list[DiscoveredCompany]:
        """
        Run search queries derived from ICP criteria, parse results into
        DiscoveredCompany candidates, deduplicate by domain.
        """
        queries = self._build_search_queries(criteria)
        seen_domains: set[str] = set()
        discovered: list[DiscoveredCompany] = []

        for query in queries:
            if len(discovered) >= max_companies:
                break
            results = await self._google_search(query)
            for item in results:
                company = self._parse_search_result(item)
                if company and company.domain not in seen_domains:
                    seen_domains.add(company.domain)
                    discovered.append(company)
                if len(discovered) >= max_companies:
                    break

        logger.info("companies_discovered", count=len(discovered), queries_run=len(queries))
        return discovered

    # ── Persistence ───────────────────────────────────────────────────────────

    async def persist_discovered_companies(
        self, discovered: list[DiscoveredCompany]
    ) -> list[Company]:
        """
        Insert discovered companies as new leads, skipping any whose domain
        already exists in the database.
        """
        created: list[Company] = []
        for d in discovered:
            existing = await self.companies.get_by_domain(d.domain)
            if existing:
                continue
            company = await self.companies.create(
                name=d.name,
                website=d.website,
                domain=d.domain,
                lead_status=LeadStatus.NEW,
            )
            created.append(company)

        logger.info("companies_persisted", count=len(created))
        return created

    async def enrich_and_attach_contacts(
        self, company: Company, enrichment: EnrichmentService
    ) -> list[Contact]:
        """
        Run enrichment for a single company, attach discovered contacts,
        and update company metadata from Clearbit/Crunchbase.
        """
        clearbit_data, hunter_contacts, funding_data = await enrichment.enrich_company_full(
            domain=company.domain or "", company_name=company.name
        )

        # Update company metadata
        if clearbit_data:
            await self.companies.update(
                company,
                employee_count=clearbit_data.employee_count,
                annual_revenue_usd=clearbit_data.annual_revenue_usd,
                founded_year=clearbit_data.founded_year,
                industry=clearbit_data.industry or company.industry,
            )
        if funding_data:
            await self.companies.update(
                company,
                funding_stage=funding_data.get("funding_stage"),
                total_funding_usd=funding_data.get("total_funding_usd"),
            )

        # Create contact records
        created_contacts: list[Contact] = []
        for idx, hc in enumerate(hunter_contacts):
            existing = await self.contacts.get_by_email(hc.email)
            if existing:
                continue
            seniority = Contact.infer_seniority(hc.title or "")
            department = Contact.infer_department(hc.title or "")
            contact = await self.contacts.create(
                company_id=company.id,
                first_name=hc.first_name,
                last_name=hc.last_name,
                title=hc.title,
                email=hc.email,
                email_verified=hc.confidence >= 70,
                linkedin_url=hc.linkedin_url,
                seniority=seniority,
                department=department,
                is_decision_maker=seniority in {"c-level", "vp", "director"},
                is_primary_contact=(idx == 0 and seniority in {"c-level", "vp", "director"}),
                enrichment_source="hunter",
            )
            created_contacts.append(contact)

        # If no contact was marked primary but we have contacts, promote the
        # highest-confidence / most senior one
        if created_contacts and not any(c.is_primary_contact for c in created_contacts):
            best = max(created_contacts, key=lambda c: c.is_decision_maker)
            await self.contacts.set_primary_contact(company.id, best.id)

        if created_contacts:
            await self.companies.update(company, lead_status=LeadStatus.READY_TO_CONTACT)

        return created_contacts
