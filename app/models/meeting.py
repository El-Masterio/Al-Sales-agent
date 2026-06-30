"""
app/models/meeting.py
=====================
Meeting ORM model — booked meetings synced with Google Calendar.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, MeetingStatusType, MeetingStatus, StrLen

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.company import Company
    from app.models.contact import Contact
    from app.models.note import Note
    from app.models.reply import Reply
    from app.models.user import User


class Meeting(Base, BaseModel):
    """
    A booked meeting with a lead, synced to Google Calendar.

    Booking flow:
        1. Reply classified as wants_demo / interested
        2. Booking service queries rep's Google Calendar free/busy
        3. Available slots offered to lead via email
        4. Lead picks a slot (via reply or booking link)
        5. Meeting created here + Google Calendar event created
        6. Reminders scheduled at 24h and 1h before starts_at
    """

    __tablename__ = "meetings"

    # ── Foreign keys ──────────────────────────────────────────────────────────
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        index=True,
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        index=True,
    )
    reply_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("replies.id", ondelete="SET NULL"),
    )
    assigned_rep_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        name="assigned_rep",
        index=True,
    )

    # ── Scheduling ────────────────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(StrLen.MEDIUM), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        MeetingStatusType,
        nullable=False,
        server_default=text("'proposed'"),
        default=MeetingStatus.PROPOSED,
        index=True,
    )
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("30"), default=30
    )
    timezone: Mapped[str] = mapped_column(
        String(StrLen.SHORT), nullable=False, server_default=text("'UTC'"), default="UTC"
    )

    # ── Location ──────────────────────────────────────────────────────────────
    location_type: Mapped[str] = mapped_column(
        String(StrLen.SHORT), nullable=False, server_default=text("'video'"), default="video"
    )
    meeting_url: Mapped[str | None] = mapped_column(String(StrLen.URL))
    phone_number: Mapped[str | None] = mapped_column(String(StrLen.PHONE))
    address: Mapped[str | None] = mapped_column(Text)

    # ── Calendar integration ──────────────────────────────────────────────────
    google_event_id: Mapped[str | None] = mapped_column(
        String(StrLen.MEDIUM), unique=True, index=True
    )
    google_calendar_id: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM))
    ics_uid: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM), unique=True)

    # ── Outcome ───────────────────────────────────────────────────────────────
    outcome: Mapped[str | None] = mapped_column(Text)
    outcome_notes: Mapped[str | None] = mapped_column(Text)
    next_steps: Mapped[str | None] = mapped_column(Text)
    deal_value_usd: Mapped[int | None] = mapped_column(Integer)

    # ── Reminders ─────────────────────────────────────────────────────────────
    reminder_24h_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    reminder_1h_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    company: Mapped[Company] = relationship(
        "Company", back_populates="meetings", lazy="select"
    )
    contact: Mapped[Contact | None] = relationship(
        "Contact", back_populates="meetings", lazy="select"
    )
    campaign: Mapped[Campaign | None] = relationship(
        "Campaign", back_populates="meetings", lazy="select"
    )
    reply: Mapped[Reply | None] = relationship("Reply", lazy="select")
    assigned_rep: Mapped[User | None] = relationship(
        "User", foreign_keys=[assigned_rep_id], lazy="select"
    )
    note_records: Mapped[list[Note]] = relationship(
        "Note",
        back_populates="meeting",
        cascade="all, delete-orphan",
        lazy="select",
        primaryjoin="Note.meeting_id == Meeting.id",
    )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_upcoming(self) -> bool:
        from datetime import datetime, timezone
        return self.starts_at > datetime.now(timezone.utc) and self.status in {
            MeetingStatus.PROPOSED,
            MeetingStatus.CONFIRMED,
            MeetingStatus.RESCHEDULED,
        }

    @property
    def is_past(self) -> bool:
        from datetime import datetime, timezone
        return self.starts_at < datetime.now(timezone.utc)

    @property
    def needs_24h_reminder(self) -> bool:
        from datetime import datetime, timezone, timedelta
        if self.reminder_24h_sent or self.status != MeetingStatus.CONFIRMED:
            return False
        now = datetime.now(timezone.utc)
        return now >= self.starts_at - timedelta(hours=24) and now < self.starts_at

    @property
    def needs_1h_reminder(self) -> bool:
        from datetime import datetime, timezone, timedelta
        if self.reminder_1h_sent or self.status != MeetingStatus.CONFIRMED:
            return False
        now = datetime.now(timezone.utc)
        return now >= self.starts_at - timedelta(hours=1) and now < self.starts_at

    # ── Mutators ──────────────────────────────────────────────────────────────

    def confirm(self, google_event_id: str | None = None) -> None:
        self.status = MeetingStatus.CONFIRMED
        if google_event_id:
            self.google_event_id = google_event_id

    def cancel(self, reason: str | None = None) -> None:
        self.status = MeetingStatus.CANCELLED
        if reason:
            self.outcome_notes = reason

    def complete(self, outcome: str, notes: str | None = None, next_steps: str | None = None) -> None:
        self.status = MeetingStatus.COMPLETED
        self.outcome = outcome
        self.outcome_notes = notes
        self.next_steps = next_steps

    def reschedule(self, new_start: datetime, new_end: datetime) -> None:
        self.starts_at = new_start
        self.ends_at = new_end
        self.status = MeetingStatus.RESCHEDULED
        self.reminder_24h_sent = False
        self.reminder_1h_sent = False
