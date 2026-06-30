"""
app/ai/outreach_agent.py
========================
Generates personalized outreach and follow-up emails using research context
and conversation memory. Never uses templates — every prompt injects fresh
company-specific facts.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.ai.llm_router import LLMResponse, llm_router
from app.ai.prompts import follow_up_prompt, initial_outreach_prompt
from app.core.config import settings
from app.models.base import EmailType

logger = structlog.get_logger(__name__)


class OutreachAgent:
    async def generate_initial_email(
        self,
        sender_name: str,
        sender_company: str,
        company_context: dict[str, Any],
        contact_context: dict[str, Any],
        value_proposition: str,
        tone: str = "professional",
        model: str | None = None,
    ) -> tuple[dict[str, str], LLMResponse]:
        system, user = initial_outreach_prompt(
            sender_name=sender_name,
            sender_company=sender_company,
            company_context=company_context,
            contact_context=contact_context,
            value_proposition=value_proposition,
            tone=tone,
        )
        response = await llm_router.complete(
            system=system,
            user=user,
            temperature=settings.LLM_CREATIVE_TEMPERATURE,
            model=model,
            json_mode=True,
        )
        return self._parse_email_json(response), response

    async def generate_follow_up_email(
        self,
        sender_name: str,
        sender_company: str,
        company_context: dict[str, Any],
        contact_context: dict[str, Any],
        attempt_number: int,
        previous_emails: list[dict[str, Any]],
        value_proposition: str,
        tone: str = "professional",
        model: str | None = None,
    ) -> tuple[dict[str, str], LLMResponse]:
        system, user = follow_up_prompt(
            sender_name=sender_name,
            sender_company=sender_company,
            company_context=company_context,
            contact_context=contact_context,
            attempt_number=attempt_number,
            previous_emails=previous_emails,
            value_proposition=value_proposition,
            tone=tone,
        )
        response = await llm_router.complete(
            system=system,
            user=user,
            temperature=settings.LLM_CREATIVE_TEMPERATURE,
            model=model,
            json_mode=True,
        )
        return self._parse_email_json(response), response

    def email_type_for_attempt(self, attempt_number: int) -> EmailType:
        mapping = {
            1: EmailType.INITIAL_OUTREACH,
            2: EmailType.FOLLOW_UP_1,
            3: EmailType.FOLLOW_UP_2,
            4: EmailType.FOLLOW_UP_3,
        }
        return mapping.get(attempt_number, EmailType.FOLLOW_UP_3)

    @staticmethod
    def _parse_email_json(response: LLMResponse) -> dict[str, str]:
        try:
            data = json.loads(response.text)
            return {
                "subject": data["subject"].strip(),
                "body_text": data["body_text"].strip(),
            }
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(
                "outreach_agent_invalid_json",
                error=str(exc),
                raw_response=response.text[:500],
            )
            raise ValueError("LLM did not return valid email JSON") from exc

    @staticmethod
    def render_html(body_text: str, signature_name: str, signature_company: str) -> str:
        """
        Convert plain-text body into minimal, clean HTML.
        Deliberately avoids heavy styling — looks like a human wrote it.
        """
        paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
        html_paragraphs = "".join(f"<p>{p}</p>" for p in paragraphs)
        return f"""<html><body style="font-family: Arial, sans-serif; font-size: 14px; color: #222; line-height: 1.5;">
{html_paragraphs}
<p>Best,<br>{signature_name}<br>{signature_company}</p>
</body></html>"""


outreach_agent = OutreachAgent()
