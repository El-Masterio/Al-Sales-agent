"""
app/ai/research_agent.py
========================
Company research agent — turns raw scraped website content into structured
research output (pain points, tech stack, ICP score, value proposition).
"""

from __future__ import annotations

import json

import structlog

from app.ai.llm_router import LLMResponse, llm_router
from app.ai.prompts import company_research_prompt
from app.core.config import settings
from app.schemas.company import CompanyResearchResult

logger = structlog.get_logger(__name__)


class ResearchAgent:
    """
    Analyzes scraped company data and produces structured research output
    used downstream by the outreach generator.
    """

    async def research_company(
        self,
        company_name: str,
        website: str | None,
        scraped_content: str,
        our_value_proposition: str | None = None,
    ) -> tuple[CompanyResearchResult, LLMResponse]:
        system, user = company_research_prompt(
            company_name=company_name,
            website=website,
            scraped_content=scraped_content,
            our_value_proposition=our_value_proposition,
        )

        response = await llm_router.complete(
            system=system,
            user=user,
            temperature=settings.LLM_RESEARCH_TEMPERATURE,
            json_mode=True,
        )

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.error(
                "research_agent_invalid_json",
                company=company_name,
                raw_response=response.text[:500],
            )
            data = {}

        result = CompanyResearchResult(
            description=data.get("description"),
            products_summary=data.get("products_summary"),
            pain_points=data.get("pain_points", []),
            tech_stack=data.get("tech_stack", []),
            value_proposition=data.get("value_proposition"),
            icp_score=int(data.get("icp_score", 0)),
            estimated_employee_count=data.get("estimated_employee_count"),
        )

        logger.info(
            "company_researched",
            company=company_name,
            icp_score=result.icp_score,
            model=response.model,
            tokens=response.prompt_tokens + response.completion_tokens,
        )

        return result, response


research_agent = ResearchAgent()
