"""
app/services/outreach_service.py
================================
High-level outreach orchestration:
  - Generate a personalized email via OutreachAgent
  - Persist the Email row (draft → queued → sent)
  - Enforce daily/hourly send limits
  - Dispatch through EmailService
  - Update campaign + campaign_lead state
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.outreach_agent import outreach_agent
from app.core.config import settings
from app.models.base import EmailStatus, EmailType, LeadStatus
from app.models.campaign import Campaign, CampaignLead
from app.models.company import Company
from app.models.contact import Contact
from app.models.email import Email
from app.repositories.campaign_repository import CampaignLeadRepository, CampaignRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.email_repository import EmailRepository
from app.services.email_service import email_service

logger = structlog.get_logger(__name__)


class SendLimitExceeded(Exception):
    pass


class OutreachService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.companies = CompanyRepository(session)
        self.contacts = ContactRepository(session)
        self.emails = EmailRepository(session)
        self.campaigns = CampaignRepository(session)
        self.campaign_leads = CampaignLeadRepository(session)

    # ── Limit enforcement ─────────────────────────────────────────────────────

    async def _check_send_limits(self, campaign_id: uuid.UUID | None) -> None:
        daily = await self.emails.count_sent_today()
        if daily >= settings.EMAIL_DAILY_SEND_LIMIT:
            raise SendLimitExceeded(f"Daily send limit ({settings.EMAIL_DAILY_SEND_LIMIT}) reached")
        hourly = await self.emails.count_sent_this_hour()
        if hourly >= settings.EMAIL_HOURLY_SEND_LIMIT:
            raise SendLimitExceeded(f"Hourly send limit ({settings.EMAIL_HOURLY_SEND_LIMIT}) reached")

    # ── Generation + persistence ──────────────────────────────────────────────

    async def generate_and_send_initial(
        self,
        campaign: Campaign,
        company: Company,
        contact: Contact,
        campaign_lead: CampaignLead,
    ) -> Email:
        """Generate and send the first outreach email to a lead."""
        await self._check_send_limits(campaign.id)

        if not contact.is_emailable:
            raise ValueError(f"Contact {contact.id} is not emailable")

        # ── Generate ──────────────────────────────────────────────────────────
        email_content, llm_response = await outreach_agent.generate_initial_email(
            sender_name=campaign.from_name,
            sender_company=campaign.from_email.split("@")[-1],
            company_context=company.to_outreach_context(),
            contact_context=contact.to_prompt_context(),
            value_proposition=campaign.value_proposition or "",
            tone=campaign.tone,
            model=campaign.llm_model,
        )

        body_html = outreach_agent.render_html(
            email_content["body_text"], campaign.from_name, campaign.from_email.split("@")[-1]
        )

        return await self._persist_and_dispatch(
            campaign=campaign,
            company=company,
            contact=contact,
            campaign_lead=campaign_lead,
            email_type=EmailType.INITIAL_OUTREACH,
            subject=email_content["subject"],
            body_text=email_content["body_text"],
            body_html=body_html,
            llm_response=llm_response,
        )

    async def generate_and_send_followup(
        self,
        campaign: Campaign,
        company: Company,
        contact: Contact,
        campaign_lead: CampaignLead,
        attempt_number: int,
    ) -> Email:
        """Generate and send follow-up email #N."""
        await self._check_send_limits(campaign.id)

        if not contact.is_emailable:
            raise ValueError(f"Contact {contact.id} is not emailable")

        # Gather previous emails in this thread for context
        previous = await self.emails.get_by_company(company.id)
        previous_context = [e.to_thread_context() for e in previous[:5]]

        email_content, llm_response = await outreach_agent.generate_follow_up_email(
            sender_name=campaign.from_name,
            sender_company=campaign.from_email.split("@")[-1],
            company_context=company.to_outreach_context(),
            contact_context=contact.to_prompt_context(),
            attempt_number=attempt_number,
            previous_emails=previous_context,
            value_proposition=campaign.value_proposition or "",
            tone=campaign.tone,
            model=campaign.llm_model,
        )

        body_html = outreach_agent.render_html(
            email_content["body_text"], campaign.from_name, campaign.from_email.split("@")[-1]
        )

        email_type = outreach_agent.email_type_for_attempt(attempt_number)

        # Maintain threading — link to the first email's thread
        thread_id = previous[-1].thread_id if previous else None
        in_reply_to = previous[0].message_id if previous else None

        return await self._persist_and_dispatch(
            campaign=campaign,
            company=company,
            contact=contact,
            campaign_lead=campaign_lead,
            email_type=email_type,
            subject=email_content["subject"],
            body_text=email_content["body_text"],
            body_html=body_html,
            llm_response=llm_response,
            thread_id=thread_id,
            in_reply_to=in_reply_to,
        )

    async def _persist_and_dispatch(
        self,
        *,
        campaign: Campaign,
        company: Company,
        contact: Contact,
        campaign_lead: CampaignLead,
        email_type: EmailType,
        subject: str,
        body_text: str,
        body_html: str,
        llm_response,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
    ) -> Email:
        # Create the email row first (draft state)
        email = await self.emails.create(
            campaign_id=campaign.id,
            campaign_lead_id=campaign_lead.id,
            company_id=company.id,
            contact_id=contact.id,
            email_type=email_type,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            from_email=campaign.from_email,
            from_name=campaign.from_name,
            to_email=contact.email,
            to_name=contact.full_name,
            reply_to=campaign.reply_to_email,
            status=EmailStatus.QUEUED,
            ai_model=llm_response.model,
            prompt_tokens=llm_response.prompt_tokens,
            completion_tokens=llm_response.completion_tokens,
            generation_ms=llm_response.generation_ms,
            provider=campaign.email_provider,
        )

        # Prepare with tracking + threading
        outgoing, message_id = email_service.prepare_email(
            to_email=contact.email,
            to_name=contact.full_name,
            from_email=campaign.from_email,
            from_name=campaign.from_name,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            tracking_id=email.tracking_id,
            reply_to=campaign.reply_to_email,
            in_reply_to=in_reply_to,
        )

        email.message_id = message_id
        email.thread_id = thread_id or message_id   # first email seeds the thread

        # Dispatch
        result = await email_service.send(outgoing, message_id, provider=campaign.email_provider)

        if result.success:
            email.mark_sent(result.provider_message_id)
            campaign_lead.record_attempt()
            campaign_lead.status = LeadStatus.CONTACTED
            campaign.increment_stat("stat_emails_sent")
            if company.lead_status == LeadStatus.READY_TO_CONTACT:
                company.lead_status = LeadStatus.CONTACTED

            # Schedule next follow-up if attempts remain
            if campaign_lead.attempt_count < campaign.max_attempts:
                next_idx = campaign_lead.attempt_count - 1
                follow_up_days = campaign.follow_up_days
                if 0 <= next_idx < len(follow_up_days):
                    campaign_lead.schedule_next_follow_up(follow_up_days[next_idx])
                else:
                    campaign_lead.stop("max_attempts")
            else:
                campaign_lead.stop("max_attempts")
        else:
            email.status = EmailStatus.FAILED
            email.bounce_reason = result.error
            logger.error("outreach_send_failed", email_id=str(email.id), error=result.error)

        await self.session.flush()
        return email
