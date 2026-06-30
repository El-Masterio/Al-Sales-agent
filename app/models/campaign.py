"""
app/models/campaign.py
======================
Campaign: an outreach campaign with ICP targeting criteria, sequence config,
and denormalised stats for dashboard speed.

CampaignLead: junction table tracking each lead's progress through a campaign
(attempt count, next follow-up date, stop reason).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    BaseModel,
    CampaignStatus,
    CampaignStatusType,
    LeadStatus,
    LeadStatusType,
    StrLen,
)

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.contact import Contact
    from app.models.email import Email
    from app.models.meeting import Meeting
    from app.models.reply import Reply
    from app.models.user import User


class Campaign(Base, BaseModel):
    """
    An outreach campaign — groups leads under shared ICP criteria,
    sequence timing, and AI configuration.
    """

    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(StrLen.MEDIUM), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # ── Targeting ─────────────────────────────────────────────────────────────
    icp_criteria: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'"), default=dict
    )
    max_leads: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("500"), default=500
    )

    # ── Sequence config ───────────────────────────────────────────────────────
    follow_up_days: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{3,7,14}'")
    )
    max_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("4"), default=4
    )

    # ── Email config ──────────────────────────────────────────────────────────
    from_name: Mapped[str] = mapped_column(String(StrLen.MEDIUM), nullable=False)
    from_email: Mapped[str] = mapped_column(String(StrLen.EMAIL), nullable=False)
    reply_to_email: Mapped[str | None] = mapped_column(String(StrLen.EMAIL))
    email_provider: Mapped[str] = mapped_column(
        String(StrLen.SHORT),
        nullable=False,
        server_default=text("'sendgrid'"),
        default="sendgrid",
    )

    # ── AI config ─────────────────────────────────────────────────────────────
    value_proposition: Mapped[str | None] = mapped_column(Text)
    tone: Mapped[str] = mapped_column(
        String(StrLen.SHORT),
        nullable=False,
        server_default=text("'professional'"),
        default="professional",
    )
    llm_model: Mapped[str] = mapped_column(
        String(StrLen.SHORT),
        nullable=False,
        server_default=text("'gpt-4.1'"),
        default="gpt-4.1",
    )

    status: Mapped[str] = mapped_column(
        CampaignStatusType,
        nullable=False,
        server_default=text("'draft'"),
        default=CampaignStatus.DRAFT,
        index=True,
    )

    # ── Denormalised stats ────────────────────────────────────────────────────
    stat_leads_added: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    stat_emails_sent: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    stat_emails_opened: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    stat_replies: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    stat_meetings: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )

    # ── Lifecycle timestamps ──────────────────────────────────────────────────
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Relationships ─────────────────────────────────────────────────────────
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id], lazy="select")
    campaign_leads: Mapped[list[CampaignLead]] = relationship(
        "CampaignLead",
        back_populates="campaign",
        cascade="all, delete-orphan",
        lazy="select",
    )
    emails: Mapped[list[Email]] = relationship(
        "Email", back_populates="campaign", lazy="select"
    )
    replies: Mapped[list[Reply]] = relationship(
        "Reply", back_populates="campaign", lazy="select"
    )
    meetings: Mapped[list[Meeting]] = relationship(
        "Meeting", back_populates="campaign", lazy="select"
    )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def open_rate(self) -> float:
        if self.stat_emails_sent == 0:
            return 0.0
        return round(self.stat_emails_opened / self.stat_emails_sent * 100, 1)

    @property
    def reply_rate(self) -> float:
        if self.stat_emails_sent == 0:
            return 0.0
        return round(self.stat_replies / self.stat_emails_sent * 100, 1)

    @property
    def meeting_rate(self) -> float:
        if self.stat_emails_sent == 0:
            return 0.0
        return round(self.stat_meetings / self.stat_emails_sent * 100, 1)

    @property
    def is_active(self) -> bool:
        return self.status == CampaignStatus.ACTIVE

    @property
    def is_at_capacity(self) -> bool:
        return self.stat_leads_added >= self.max_leads

    # ── Mutators ──────────────────────────────────────────────────────────────

    def activate(self) -> None:
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        self.status = CampaignStatus.ACTIVE
        if self.started_at is None:
            self.started_at = _dt.now(_tz.utc)

    def pause(self) -> None:
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        self.status = CampaignStatus.PAUSED
        self.paused_at = _dt.now(_tz.utc)

    def complete(self) -> None:
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        self.status = CampaignStatus.COMPLETED
        self.completed_at = _dt.now(_tz.utc)

    def increment_stat(self, field: str, by: int = 1) -> None:
        current = getattr(self, field, 0)
        setattr(self, field, current + by)


class CampaignLead(Base, BaseModel):
    """
    Junction table: tracks a single lead's (company's) progress within
    one campaign — attempt count, next follow-up date, stop reason.
    """

    __tablename__ = "campaign_leads"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
    )

    status: Mapped[str] = mapped_column(
        LeadStatusType,
        nullable=False,
        server_default=text("'new'"),
        default=LeadStatus.NEW,
    )
    attempt_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0"), default=0
    )
    next_follow_up: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_reason: Mapped[str | None] = mapped_column(Text)

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        default=datetime.utcnow,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    campaign: Mapped[Campaign] = relationship(
        "Campaign", back_populates="campaign_leads", lazy="select"
    )
    company: Mapped[Company] = relationship(
        "Company", back_populates="campaign_leads", lazy="select"
    )
    contact: Mapped[Contact | None] = relationship("Contact", lazy="select")
    emails: Mapped[list[Email]] = relationship(
        "Email", back_populates="campaign_lead", lazy="select"
    )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_stopped(self) -> bool:
        return self.stopped_at is not None

    @property
    def has_attempts_remaining(self) -> bool:
        return self.attempt_count < self.campaign.max_attempts

    # ── Mutators ──────────────────────────────────────────────────────────────

    def record_attempt(self) -> None:
        self.attempt_count += 1

    def schedule_next_follow_up(self, days_from_now: int) -> None:
        from datetime import datetime as _dt
        from datetime import timedelta as _td
        from datetime import timezone as _tz

        self.next_follow_up = _dt.now(_tz.utc) + _td(days=days_from_now)

    def stop(self, reason: str) -> None:
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        self.stopped_at = _dt.now(_tz.utc)
        self.stop_reason = reason
        self.next_follow_up = None
