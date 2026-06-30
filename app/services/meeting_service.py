"""
app/services/meeting_service.py
===============================
Meeting booking orchestration on top of CalendarService:
  - Get a rep's available slots (Google free/busy + local meeting conflicts)
  - Book a meeting (DB row + Google Calendar event)
  - Cancel / reschedule
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import LeadStatus, MeetingStatus
from app.models.meeting import Meeting
from app.repositories.company_repository import CompanyRepository
from app.repositories.meeting_repository import MeetingRepository
from app.repositories.user_repository import UserRepository
from app.schemas.meeting import AvailabilityRequest, AvailabilitySlot, MeetingBookRequest
from app.services.calendar_service import calendar_service

logger = structlog.get_logger(__name__)


class MeetingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.meetings = MeetingRepository(session)
        self.users = UserRepository(session)
        self.companies = CompanyRepository(session)

    async def get_availability(self, req: AvailabilityRequest) -> tuple[str, list[AvailabilitySlot]]:
        rep = await self.users.get_or_404(req.rep_id)
        if not rep.has_calendar_connected:
            # Fall back to local-only availability (no external busy data)
            logger.info("availability_no_calendar", rep_id=str(req.rep_id))
            busy_blocks: list[tuple[datetime, datetime]] = []
        else:
            now = datetime.now(timezone.utc)
            window_end = now + timedelta(days=req.days_ahead)
            busy_blocks = calendar_service.get_busy_blocks(
                rep.google_calendar_token,
                rep.google_calendar_id or "primary",
                now,
                window_end,
            )

        # Also exclude locally-booked meetings
        now = datetime.now(timezone.utc)
        local_meetings = await self.meetings.get_rep_busy_blocks(
            req.rep_id, now, now + timedelta(days=req.days_ahead)
        )
        for m in local_meetings:
            busy_blocks.append((m.starts_at, m.ends_at))

        slots = calendar_service.generate_available_slots(
            busy_blocks,
            duration_minutes=req.duration_minutes,
            days_ahead=req.days_ahead,
            earliest_hour=req.earliest_hour_local,
            latest_hour=req.latest_hour_local,
        )
        return rep.timezone, slots

    async def book_meeting(self, req: MeetingBookRequest) -> Meeting:
        rep = await self.users.get_or_404(req.assigned_rep_id)
        company = await self.companies.get_or_404(req.company_id)

        ends_at = req.starts_at + timedelta(minutes=req.duration_minutes)

        meeting = await self.meetings.create(
            company_id=req.company_id,
            contact_id=req.contact_id,
            campaign_id=req.campaign_id,
            reply_id=req.reply_id,
            assigned_rep_id=req.assigned_rep_id,
            title=req.title,
            description=req.description,
            status=MeetingStatus.PROPOSED,
            starts_at=req.starts_at,
            ends_at=ends_at,
            duration_minutes=req.duration_minutes,
            timezone=req.timezone,
            location_type=req.location_type,
        )

        # Create the Google Calendar event if the rep has a connected calendar
        if rep.has_calendar_connected and req.contact_id:
            contact = next((c for c in company.contacts if c.id == req.contact_id), None)
            attendee_email = contact.email if contact else None
            if attendee_email:
                try:
                    event = calendar_service.create_event(
                        rep.google_calendar_token,
                        rep.google_calendar_id or "primary",
                        title=req.title,
                        description=req.description or "",
                        start=req.starts_at,
                        end=ends_at,
                        attendee_email=attendee_email,
                        timezone_str=req.timezone,
                        with_meet_link=(req.location_type == "video"),
                    )
                    meeting.confirm(google_event_id=event["google_event_id"])
                    meeting.meeting_url = event.get("meet_link")
                    meeting.google_calendar_id = rep.google_calendar_id or "primary"
                except Exception as exc:
                    logger.error("calendar_event_creation_failed", error=str(exc))

        # Advance lead status
        company.lead_status = LeadStatus.MEETING_SCHEDULED
        if meeting.campaign_id:
            from app.repositories.campaign_repository import CampaignRepository

            campaign_repo = CampaignRepository(self.session)
            campaign = await campaign_repo.get(meeting.campaign_id)
            if campaign:
                campaign.increment_stat("stat_meetings")

        await self.session.flush()
        logger.info("meeting_booked", meeting_id=str(meeting.id), company_id=str(req.company_id))
        return meeting

    async def cancel_meeting(self, meeting_id: uuid.UUID, reason: str | None = None) -> Meeting:
        meeting = await self.meetings.get_or_404(meeting_id)
        rep = await self.users.get(meeting.assigned_rep_id) if meeting.assigned_rep_id else None

        if meeting.google_event_id and rep and rep.has_calendar_connected:
            try:
                calendar_service.cancel_event(
                    rep.google_calendar_token,
                    meeting.google_calendar_id or "primary",
                    meeting.google_event_id,
                )
            except Exception as exc:
                logger.error("calendar_event_cancel_failed", error=str(exc))

        meeting.cancel(reason)
        await self.session.flush()
        return meeting


meeting_service_factory = MeetingService
