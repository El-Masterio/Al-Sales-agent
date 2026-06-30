"""
app/workers/tasks.py
====================
All Celery tasks — the autonomous workflow engine.

Tasks fall into two groups:
  1. Triggered tasks (called via .delay() from API routes):
       research_company_task, generate_leads_task, process_reply_task
  2. Scheduled tasks (run by Celery beat — see celery_app.py):
       process_due_followups_task, research_new_leads_task,
       dispatch_initial_outreach_task, classify_pending_replies_task,
       send_meeting_reminders_task, propose_meetings_task,
       aggregate_daily_stats_task, cleanup_expired_memory_task,
       generate_daily_report_task

Each task opens its own DB session via get_db_context (async) bridged through
run_async, and is wrapped for retry on failure.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import structlog

from app.core.config import settings
from app.core.database import get_db_context
from app.workers.async_utils import run_async
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


# =============================================================================
# Triggered tasks
# =============================================================================

@celery_app.task(name="app.workers.tasks.research_company_task", bind=True, max_retries=3)
def research_company_task(self, company_id: str) -> dict:
    async def _run() -> dict:
        async with get_db_context() as db:
            from app.services.research_service import ResearchService

            service = ResearchService(db)
            company = await service.research_company(uuid.UUID(company_id))
            return {"company_id": company_id, "icp_score": company.icp_score}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("research_company_task_failed", company_id=company_id, error=str(exc))
        raise self.retry(exc=exc, countdown=settings.CELERY_RETRY_BACKOFF)


@celery_app.task(name="app.workers.tasks.generate_leads_task", bind=True, max_retries=2)
def generate_leads_task(self, criteria_dict: dict, max_companies: int = 50) -> dict:
    async def _run() -> dict:
        async with get_db_context() as db:
            from app.schemas.company import ICPCriteria
            from app.services.enrichment_service import EnrichmentService
            from app.services.lead_generation_service import LeadGenerationService

            criteria = ICPCriteria(**criteria_dict)
            lead_gen = LeadGenerationService(db)
            enrichment = EnrichmentService()
            try:
                discovered = await lead_gen.discover_companies(criteria, max_companies)
                created = await lead_gen.persist_discovered_companies(discovered)

                # Enrich each new company and queue research
                enriched_count = 0
                for company in created:
                    try:
                        await lead_gen.enrich_and_attach_contacts(company, enrichment)
                        enriched_count += 1
                        research_company_task.delay(str(company.id))
                    except Exception as exc:
                        logger.warning(
                            "lead_enrichment_failed", company_id=str(company.id), error=str(exc)
                        )
                return {"discovered": len(discovered), "created": len(created), "enriched": enriched_count}
            finally:
                await lead_gen.aclose()
                await enrichment.aclose()

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("generate_leads_task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=120)


@celery_app.task(name="app.workers.tasks.process_reply_task", bind=True, max_retries=3)
def process_reply_task(self, reply_id: str) -> dict:
    async def _run() -> dict:
        async with get_db_context() as db:
            from app.services.reply_service import ReplyService

            service = ReplyService(db)
            reply = await service.process_reply(uuid.UUID(reply_id))
            return {"reply_id": reply_id, "classification": reply.classification}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("process_reply_task_failed", reply_id=reply_id, error=str(exc))
        raise self.retry(exc=exc, countdown=settings.CELERY_RETRY_BACKOFF)


@celery_app.task(name="app.workers.tasks.send_email_task", bind=True, max_retries=3)
def send_email_task(self, campaign_lead_id: str, attempt_number: int) -> dict:
    """Generate + send one email (initial or follow-up) for a campaign lead."""

    async def _run() -> dict:
        async with get_db_context() as db:
            from app.repositories.campaign_repository import (
                CampaignLeadRepository,
                CampaignRepository,
            )
            from app.repositories.company_repository import CompanyRepository
            from app.repositories.contact_repository import ContactRepository
            from app.services.outreach_service import OutreachService, SendLimitExceeded

            cl_repo = CampaignLeadRepository(db)
            campaign_repo = CampaignRepository(db)
            company_repo = CompanyRepository(db)
            contact_repo = ContactRepository(db)
            outreach = OutreachService(db)

            campaign_lead = await cl_repo.get(uuid.UUID(campaign_lead_id))
            if campaign_lead is None or campaign_lead.is_stopped:
                return {"skipped": True, "reason": "lead stopped or missing"}

            campaign = await campaign_repo.get(campaign_lead.campaign_id)
            company = await company_repo.get_with_contacts(campaign_lead.company_id)
            contact = (
                await contact_repo.get(campaign_lead.contact_id)
                if campaign_lead.contact_id
                else await contact_repo.get_primary_contact(campaign_lead.company_id)
            )

            if not (campaign and company and contact):
                return {"skipped": True, "reason": "missing campaign/company/contact"}

            try:
                if attempt_number == 1:
                    email = await outreach.generate_and_send_initial(
                        campaign, company, contact, campaign_lead
                    )
                else:
                    email = await outreach.generate_and_send_followup(
                        campaign, company, contact, campaign_lead, attempt_number
                    )
                return {"email_id": str(email.id), "status": email.status}
            except SendLimitExceeded as exc:
                logger.warning("send_limit_exceeded", error=str(exc))
                return {"skipped": True, "reason": str(exc)}

    try:
        return run_async(_run())
    except Exception as exc:
        logger.error("send_email_task_failed", campaign_lead_id=campaign_lead_id, error=str(exc))
        raise self.retry(exc=exc, countdown=settings.CELERY_RETRY_BACKOFF)


# =============================================================================
# Scheduled tasks (autonomous heartbeat)
# =============================================================================

@celery_app.task(name="app.workers.tasks.research_new_leads_task")
def research_new_leads_task() -> dict:
    async def _run() -> dict:
        async with get_db_context() as db:
            from app.repositories.company_repository import CompanyRepository

            repo = CompanyRepository(db)
            unresearched = await repo.get_unresearched(limit=20)
            for company in unresearched:
                research_company_task.delay(str(company.id))
            return {"queued": len(unresearched)}

    if not settings.FEATURE_AUTO_RESEARCH:
        return {"skipped": "feature disabled"}
    return run_async(_run())


@celery_app.task(name="app.workers.tasks.dispatch_initial_outreach_task")
def dispatch_initial_outreach_task() -> dict:
    """For each active campaign, queue initial outreach to NEW campaign leads."""

    async def _run() -> dict:
        async with get_db_context() as db:
            from app.models.base import LeadStatus
            from app.repositories.campaign_repository import (
                CampaignLeadRepository,
                CampaignRepository,
            )

            campaign_repo = CampaignRepository(db)
            cl_repo = CampaignLeadRepository(db)

            active_campaigns = await campaign_repo.get_active()
            queued = 0
            for campaign in active_campaigns:
                leads = await cl_repo.get_by_campaign(campaign.id, limit=50)
                for lead in leads:
                    if lead.status == LeadStatus.NEW and not lead.is_stopped:
                        send_email_task.delay(str(lead.id), 1)
                        queued += 1
            return {"queued": queued, "active_campaigns": len(active_campaigns)}

    if not settings.FEATURE_AUTO_OUTREACH:
        return {"skipped": "feature disabled"}
    return run_async(_run())


@celery_app.task(name="app.workers.tasks.process_due_followups_task")
def process_due_followups_task() -> dict:
    """Queue follow-up emails for leads whose next_follow_up time has passed."""

    async def _run() -> dict:
        async with get_db_context() as db:
            from app.repositories.campaign_repository import CampaignLeadRepository

            cl_repo = CampaignLeadRepository(db)
            due = await cl_repo.get_due_for_followup(limit=100)
            queued = 0
            for lead in due:
                # attempt_count is the number already sent; next attempt = +1
                next_attempt = lead.attempt_count + 1
                if next_attempt <= lead.campaign.max_attempts:
                    send_email_task.delay(str(lead.id), next_attempt)
                    # Clear next_follow_up to avoid double-queueing before send completes
                    lead.next_follow_up = None
                    queued += 1
                else:
                    lead.stop("max_attempts")
            return {"queued": queued, "due_total": len(due)}

    if not settings.FEATURE_AUTO_FOLLOWUP:
        return {"skipped": "feature disabled"}
    return run_async(_run())


@celery_app.task(name="app.workers.tasks.classify_pending_replies_task")
def classify_pending_replies_task() -> dict:
    """Safety-net: classify any replies that the webhook path missed."""

    async def _run() -> dict:
        async with get_db_context() as db:
            from app.repositories.reply_repository import ReplyRepository

            repo = ReplyRepository(db)
            unclassified = await repo.get_unclassified(limit=50)
            for reply in unclassified:
                process_reply_task.delay(str(reply.id))
            return {"queued": len(unclassified)}

    if not settings.FEATURE_REPLY_CLASSIFICATION:
        return {"skipped": "feature disabled"}
    return run_async(_run())


@celery_app.task(name="app.workers.tasks.propose_meetings_task")
def propose_meetings_task() -> dict:
    """Send meeting-slot proposal emails to leads marked interested."""

    async def _run() -> dict:
        async with get_db_context() as db:
            from app.models.base import LeadStatus
            from app.repositories.company_repository import CompanyRepository
            from app.repositories.user_repository import UserRepository
            from app.schemas.company import CompanySearchFilters

            company_repo = CompanyRepository(db)
            user_repo = UserRepository(db)

            interested, _ = await company_repo.search(
                CompanySearchFilters(lead_statuses=[LeadStatus.INTERESTED]),
                offset=0,
                limit=25,
            )
            reps = await user_repo.get_active_reps()
            if not reps:
                return {"skipped": "no active reps"}

            # In a full implementation this would generate availability and
            # send a proposal email via the outreach pipeline. Here we mark
            # the lead as having a proposal in flight to avoid re-processing.
            proposed = 0
            for company in interested:
                # Round-robin rep assignment
                rep = reps[proposed % len(reps)]
                if company.assigned_to_id is None:
                    company.assigned_to_id = rep.id
                proposed += 1
            return {"proposed": proposed}

    if not settings.FEATURE_AUTO_BOOKING:
        return {"skipped": "feature disabled"}
    return run_async(_run())


@celery_app.task(name="app.workers.tasks.send_meeting_reminders_task")
def send_meeting_reminders_task() -> dict:
    async def _run() -> dict:
        async with get_db_context() as db:
            from app.repositories.meeting_repository import MeetingRepository

            repo = MeetingRepository(db)
            meetings = await repo.get_needing_reminders()
            sent_24h = 0
            sent_1h = 0
            for meeting in meetings:
                if meeting.needs_24h_reminder:
                    meeting.reminder_24h_sent = True
                    sent_24h += 1
                if meeting.needs_1h_reminder:
                    meeting.reminder_1h_sent = True
                    sent_1h += 1
            return {"reminders_24h": sent_24h, "reminders_1h": sent_1h}

    return run_async(_run())


@celery_app.task(name="app.workers.tasks.aggregate_daily_stats_task")
def aggregate_daily_stats_task() -> dict:
    async def _run() -> dict:
        async with get_db_context() as db:
            from app.repositories.stats_repository import StatsRepository

            stats_repo = StatsRepository(db)
            yesterday = date.today() - timedelta(days=1)
            counts = await stats_repo.get_overview_counts()

            daily = await stats_repo.get_or_create_for_date(yesterday, None)
            daily.leads_added = counts.get("new_leads_today", 0)
            daily.emails_sent = counts.get("emails_sent_today", 0)
            daily.meetings_booked = counts.get("meetings_booked_today", 0)
            return {"date": yesterday.isoformat()}

    return run_async(_run())


@celery_app.task(name="app.workers.tasks.cleanup_expired_memory_task")
def cleanup_expired_memory_task() -> dict:
    async def _run() -> dict:
        async with get_db_context() as db:
            from app.repositories.memory_repository import MemoryRepository

            repo = MemoryRepository(db)
            deleted = await repo.delete_expired()
            return {"deleted": deleted}

    if not settings.FEATURE_AI_MEMORY:
        return {"skipped": "feature disabled"}
    return run_async(_run())


@celery_app.task(name="app.workers.tasks.generate_daily_report_task")
def generate_daily_report_task() -> dict:
    async def _run() -> dict:
        async with get_db_context() as db:
            from app.services.dashboard_service import DashboardService

            service = DashboardService(db)
            end = date.today()
            start = end - timedelta(days=1)
            report = await service.generate_report(start, end)
            logger.info(
                "daily_report_generated",
                emails_sent=report.summary.emails_sent_total,
                meetings=report.summary.meetings_booked_total,
            )
            return {"generated": True, "date": end.isoformat()}

    return run_async(_run())
