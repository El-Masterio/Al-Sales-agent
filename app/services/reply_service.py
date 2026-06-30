"""
app/services/reply_service.py
=============================
Handles inbound replies end-to-end:
  1. Persist raw inbound email as a Reply
  2. Run it through the reply-handling LangGraph (classify → memory → decide)
  3. Persist classification + extracted memories
  4. Execute the decided next action (stop sequence, mark statuses, flag, etc.)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.memory_agent import memory_agent
from app.ai.sales_graph import reply_handling_graph
from app.models.base import LeadStatus, ReplyClassification
from app.models.memory import ConversationMemory
from app.models.reply import Reply
from app.repositories.campaign_repository import CampaignLeadRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.email_repository import EmailRepository
from app.repositories.memory_repository import MemoryRepository
from app.repositories.reply_repository import ReplyRepository
from app.schemas.email import InboundEmailWebhook

logger = structlog.get_logger(__name__)


class ReplyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.replies = ReplyRepository(session)
        self.emails = EmailRepository(session)
        self.companies = CompanyRepository(session)
        self.contacts = ContactRepository(session)
        self.campaign_leads = CampaignLeadRepository(session)
        self.memories = MemoryRepository(session)

    async def ingest_inbound(self, inbound: InboundEmailWebhook) -> Reply | None:
        """
        Persist an inbound email as a Reply, linking it to the original
        outbound email / company / contact where possible.
        """
        # Deduplicate by message_id
        if inbound.message_id:
            existing = await self.replies.get_by_message_id(inbound.message_id)
            if existing:
                logger.info("reply_already_ingested", message_id=inbound.message_id)
                return existing

        # Resolve contact + company by sender email
        contact = await self.contacts.get_by_email(inbound.from_email)
        if contact is None:
            logger.warning("reply_unknown_sender", email=inbound.from_email)
            return None

        # Resolve the original email via In-Reply-To header
        original_email = None
        if inbound.in_reply_to:
            original_email = await self.emails.get_by_message_id(inbound.in_reply_to)

        reply = await self.replies.create(
            email_id=original_email.id if original_email else None,
            company_id=contact.company_id,
            contact_id=contact.id,
            campaign_id=original_email.campaign_id if original_email else None,
            from_email=inbound.from_email,
            from_name=inbound.from_name,
            subject=inbound.subject,
            body_text=inbound.body_text,
            body_html=inbound.body_html,
            message_id=inbound.message_id,
            in_reply_to=inbound.in_reply_to,
            received_at=inbound.received_at or datetime.now(timezone.utc),
        )

        logger.info("reply_ingested", reply_id=str(reply.id), company_id=str(contact.company_id))
        return reply

    async def process_reply(self, reply_id: uuid.UUID) -> Reply:
        """
        Run the full reply-handling pipeline on a persisted reply:
        classify, extract memory, decide and execute the next action.
        """
        reply = await self.replies.get_or_404(reply_id)
        company = await self.companies.get_or_404(reply.company_id)

        # Build thread history for context
        thread_history = []
        if reply.email_id:
            original = await self.emails.get(reply.email_id)
            if original and original.thread_id:
                thread = await self.emails.get_thread(original.thread_id)
                thread_history = [e.to_thread_context() for e in thread]

        # ── Run LangGraph reply-handling pipeline ─────────────────────────────
        graph_state = await reply_handling_graph.ainvoke(
            {
                "company_id": str(company.id),
                "reply_body": reply.body_text,
                "reply_subject": reply.subject,
                "thread_history": thread_history,
                "company_context": company.to_outreach_context(),
                "extracted_memories": [],
            }
        )

        # ── Persist classification ────────────────────────────────────────────
        classification_data = graph_state.get("classification_result")
        if classification_data:
            reply.apply_classification(
                classification=ReplyClassification(classification_data["classification"]),
                confidence=classification_data["confidence"],
                sentiment=classification_data["sentiment"],
                summary=classification_data["summary"],
                suggested_action=classification_data["suggested_action"],
                model="langgraph-pipeline",
            )

        # ── Persist extracted memories ────────────────────────────────────────
        extracted = graph_state.get("extracted_memories", [])
        if extracted:
            embeddings = await memory_agent.embed_memories(extracted)
            for mem, embedding in zip(extracted, embeddings, strict=False):
                memory = ConversationMemory(
                    company_id=company.id,
                    contact_id=reply.contact_id,
                    memory_type=mem["type"],
                    content=mem["content"],
                    embedding=embedding,
                    source_type="reply",
                    source_id=reply.id,
                    importance=int(mem.get("importance", 5)),
                )
                self.session.add(memory)

        # ── Execute next action ───────────────────────────────────────────────
        next_action = graph_state.get("next_action", "flag_for_human")
        await self._execute_action(reply, company, next_action)

        await self.session.flush()
        logger.info(
            "reply_processed",
            reply_id=str(reply_id),
            classification=reply.classification,
            action=next_action,
        )
        return reply

    async def _execute_action(self, reply: Reply, company, action: str) -> None:
        """Execute the action decided by the reply-handling graph."""
        # Stop any active follow-up sequence for this lead (except OOO)
        if action != "continue_sequence" and reply.campaign_id:
            cl = await self.campaign_leads.get_by_campaign_and_company(
                reply.campaign_id, company.id
            )
            if cl and not cl.is_stopped:
                cl.stop("replied")

        if action == "propose_meeting":
            company.lead_status = LeadStatus.INTERESTED
            reply.mark_actioned("Lead marked interested — meeting proposal queued")
            # The actual meeting-proposal email is dispatched by a worker task
            # that watches for interested leads (decoupled side effect).

        elif action == "send_pricing_then_propose_meeting":
            company.lead_status = LeadStatus.INTERESTED
            reply.mark_actioned("Pricing requested — pricing + meeting proposal queued")

        elif action == "snooze_lead":
            reply.mark_actioned("Lead snoozed (maybe later)")

        elif action == "mark_not_interested":
            company.lead_status = LeadStatus.NOT_INTERESTED
            reply.mark_actioned("Lead marked not interested — sequence stopped")

        elif action == "unsubscribe_contact":
            if reply.contact_id:
                contact = await self.contacts.get(reply.contact_id)
                if contact:
                    contact.mark_unsubscribed()
            company.lead_status = LeadStatus.UNSUBSCRIBED
            reply.mark_actioned("Contact unsubscribed")

        elif action == "continue_sequence":
            reply.mark_actioned("Out-of-office detected — sequence continues")

        else:  # flag_for_human
            reply.mark_actioned("Flagged for human review")
            reply.reviewed = False
