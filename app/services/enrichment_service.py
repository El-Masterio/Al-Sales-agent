"""
app/services/enrichment_service.py
==================================
Lead enrichment via third-party APIs:
  - Hunter.io: find/verify email addresses for a domain
  - Clearbit: company + person enrichment
  - Crunchbase: funding and company metadata

Each provider method degrades gracefully (returns None / empty list) if
the API key isn't configured or the request fails, so enrichment never
blocks the broader lead generation pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class EnrichedContact:
    first_name: str
    last_name: str | None
    email: str
    title: str | None
    confidence: int   # 0-100, Hunter's confidence score
    linkedin_url: str | None = None


@dataclass
class EnrichedCompany:
    employee_count: int | None
    annual_revenue_usd: int | None
    founded_year: int | None
    industry: str | None
    logo_url: str | None


class EnrichmentService:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=20.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    # ── Hunter.io ─────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def find_emails_hunter(self, domain: str, max_results: int = 10) -> list[EnrichedContact]:
        if not settings.HUNTER_API_KEY:
            logger.debug("hunter_not_configured")
            return []

        try:
            response = await self._client.get(
                "https://api.hunter.io/v2/domain-search",
                params={
                    "domain": domain,
                    "api_key": settings.HUNTER_API_KEY,
                    "limit": max_results,
                },
            )
            response.raise_for_status()
            data = response.json().get("data", {})

            contacts = []
            for email_entry in data.get("emails", []):
                contacts.append(
                    EnrichedContact(
                        first_name=email_entry.get("first_name") or "Unknown",
                        last_name=email_entry.get("last_name"),
                        email=email_entry["value"],
                        title=email_entry.get("position"),
                        confidence=email_entry.get("confidence", 0),
                        linkedin_url=email_entry.get("linkedin"),
                    )
                )
            return contacts
        except httpx.HTTPStatusError as exc:
            logger.warning("hunter_request_failed", domain=domain, status=exc.response.status_code)
            return []
        except Exception as exc:
            logger.error("hunter_unexpected_error", domain=domain, error=str(exc))
            return []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def verify_email_hunter(self, email: str) -> bool:
        """Returns True if Hunter considers the email deliverable."""
        if not settings.HUNTER_API_KEY:
            return False
        try:
            response = await self._client.get(
                "https://api.hunter.io/v2/email-verifier",
                params={"email": email, "api_key": settings.HUNTER_API_KEY},
            )
            response.raise_for_status()
            result = response.json().get("data", {}).get("result")
            return result in {"deliverable", "risky"}
        except Exception as exc:
            logger.warning("hunter_verify_failed", email=email, error=str(exc))
            return False

    # ── Clearbit ──────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def enrich_company_clearbit(self, domain: str) -> EnrichedCompany | None:
        if not settings.CLEARBIT_API_KEY:
            logger.debug("clearbit_not_configured")
            return None

        try:
            response = await self._client.get(
                f"https://company.clearbit.com/v2/companies/find",
                params={"domain": domain},
                headers={"Authorization": f"Bearer {settings.CLEARBIT_API_KEY}"},
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()

            return EnrichedCompany(
                employee_count=data.get("metrics", {}).get("employees"),
                annual_revenue_usd=data.get("metrics", {}).get("annualRevenue"),
                founded_year=data.get("foundedYear"),
                industry=data.get("category", {}).get("industry"),
                logo_url=data.get("logo"),
            )
        except httpx.HTTPStatusError as exc:
            logger.warning("clearbit_request_failed", domain=domain, status=exc.response.status_code)
            return None
        except Exception as exc:
            logger.error("clearbit_unexpected_error", domain=domain, error=str(exc))
            return None

    # ── Crunchbase ────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def get_funding_crunchbase(self, company_name: str) -> dict | None:
        if not settings.CRUNCHBASE_API_KEY:
            logger.debug("crunchbase_not_configured")
            return None

        try:
            response = await self._client.get(
                "https://api.crunchbase.com/api/v4/searches/organizations",
                params={"query": company_name, "user_key": settings.CRUNCHBASE_API_KEY},
            )
            response.raise_for_status()
            entities = response.json().get("entities", [])
            if not entities:
                return None

            org = entities[0].get("properties", {})
            return {
                "funding_stage": org.get("last_funding_type"),
                "total_funding_usd": org.get("funding_total", {}).get("value_usd"),
                "last_funding_date": org.get("last_funding_at"),
            }
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "crunchbase_request_failed", company=company_name, status=exc.response.status_code
            )
            return None
        except Exception as exc:
            logger.error("crunchbase_unexpected_error", company=company_name, error=str(exc))
            return None

    # ── Orchestrated full enrichment ──────────────────────────────────────────

    async def enrich_company_full(
        self, domain: str, company_name: str
    ) -> tuple[EnrichedCompany | None, list[EnrichedContact], dict | None]:
        """Run all enrichment providers concurrently for one company."""
        import asyncio

        company_task = self.enrich_company_clearbit(domain)
        contacts_task = self.find_emails_hunter(domain)
        funding_task = self.get_funding_crunchbase(company_name)

        company, contacts, funding = await asyncio.gather(
            company_task, contacts_task, funding_task
        )
        return company, contacts, funding
