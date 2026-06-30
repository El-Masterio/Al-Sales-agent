"""
app/models/email.py
===================
Email and EmailEvent ORM models.

Email: every outbound email sent by the system.
EmailEvent: granular open/click/bounce event log (from provider webhooks).

Threading:
  - message_id: SMTP Message-ID header (globally unique)
  - thread_id:  groups all emails in a conversation
  - in_reply_to: parent message_id (for follow-ups / replies)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    BaseModel,
    EmailStatusType,
    EmailTypeType,
    EmailStatus,
    EmailType,
    StrLen,
)

if TYPE_CHECKING:
    from app.models.campaign import Campaign, CampaignLead
    from app.models.company import Company
    from app.models.contact import Contact
    from app.models.reply import Reply
    from app.models.user import User


class Email(Base, BaseModel):
    """
    A single outbound email sent by the AI Sales Agent.

    Tracking:
        Each email gets a unique tracking_id (UUID). The email body contains:
        - An invisible 1x1 tracking pixel:  /t/{tracking_id}/open.png
        - Rewritten click links:            /t/{tracking_id}/click?url=...
        Both routes update opened_count / clicked_count and append EmailEvent rows.

    AI metadata:
        Stores the model used, token counts, and generation latency for cost
        analysis and prompt optimisation dashboards.
    """

    __tablename__ = "emails"

    # ── Foreign keys ──────────────────────────────────────────────────────────
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        index=True,
    )
    campaign_lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaign_leads.id", ondelete="SET NULL"),
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
        index=True,
    )
    sent_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        name="sent_by",
    )

    # ── Email content ─────────────────────────────────────────────────────────
    email_type: Mapped[str] = mapped_column(
        EmailTypeType,
        nullable=False,
        default=EmailType.INITIAL_OUTREACH,
    )
    subject: Mapped[str] = mapped_column(String(StrLen.MEDIUM), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    from_email: Mapped[str] = mapped_column(String(StrLen.EMAIL), nullable=False)
    from_name: Mapped[str] = mapped_column(String(StrLen.MEDIUM), nullable=False)
    to_email: Mapped[str] = mapped_column(String(StrLen.EMAIL), nullable=False)
    to_name: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM))
    reply_to: Mapped[str | None] = mapped_column(String(StrLen.EMAIL))

    # ── Threading ─────────────────────────────────────────────────────────────
    message_id: Mapped[str | None] = mapped_column(
        String(StrLen.MEDIUM), unique=True, index=True
    )
    thread_id: Mapped[str | None] = mapped_column(
        String(StrLen.MEDIUM), index=True
    )
    in_reply_to: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM))

    # ── Delivery ──────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        EmailStatusType,
        nullable=False,
        server_default=text("'draft'"),
        default=EmailStatus.DRAFT,
        index=True,
    )
    provider: Mapped[str | None] = mapped_column(String(StrLen.SHORT))
    provider_message_id: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM))

    # ── Tracking ──────────────────────────────────────────────────────────────
    tracking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        server_default=text("uuid_generate_v4()"),
        default=uuid.uuid4,
        index=True,
        unique=True,
    )
    opened_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0"), default=0
    )
    clicked_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0"), default=0
    )
    first_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── AI metadata ───────────────────────────────────────────────────────────
    ai_model: Mapped[str | None] = mapped_column(String(StrLen.SHORT))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    generation_ms: Mapped[int | None] = mapped_column(Integer)

    # ── Timestamps ────────────────────────────────────────────────────────────
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bounced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bounce_type: Mapped[str | None] = mapped_column(String(StrLen.SHORT))
    bounce_reason: Mapped[str | None] = mapped_column(Text)

    # ── Relationships ─────────────────────────────────────────────────────────
    campaign: Mapped[Campaign | None] = relationship(
        "Campaign",
        back_populates="emails",
        lazy="select",
    )
    campaign_lead: Mapped[CampaignLead | None] = relationship(
        "CampaignLead",
        back_populates="emails",
        lazy="select",
    )
    company: Mapped[Company] = relationship(
        "Company",
        back_populates="emails",
        lazy="select",
    )
    contact: Mapped[Contact | None] = relationship(
        "Contact",
        back_populates="emails",
        lazy="select",
    )
    sent_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[sent_by_id],
        lazy="select",
    )
    events: Mapped[list[EmailEvent]] = relationship(
        "EmailEvent",
        back_populates="email",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="EmailEvent.occurred_at",
    )
    replies: Mapped[list[Reply]] = relationship(
        "Reply",
        back_populates="email",
        lazy="select",
    )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def was_opened(self) -> bool:
        return self.opened_count > 0

    @property
    def was_clicked(self) -> bool:
        return self.clicked_count > 0

    @property
    def was_replied(self) -> bool:
        return bool(self.replies)

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return self.prompt_tokens + self.completion_tokens

    @property
    def is_follow_up(self) -> bool:
        return self.email_type in {
            EmailType.FOLLOW_UP_1,
            EmailType.FOLLOW_UP_2,
            EmailType.FOLLOW_UP_3,
        }

    # ── Mutators ──────────────────────────────────────────────────────────────

    def record_open(self) -> None:
        """Called when the tracking pixel is loaded."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        self.opened_count += 1
        if self.first_opened_at is None:
            self.first_opened_at = now
        self.last_opened_at = now
        if self.status in {EmailStatus.SENT, EmailStatus.DELIVERED}:
            self.status = EmailStatus.OPENED

    def record_click(self) -> None:
        """Called when a tracked link is clicked."""
        self.clicked_count += 1
        if self.status not in {EmailStatus.CLICKED, EmailStatus.REPLIED}:
            self.status = EmailStatus.CLICKED

    def record_bounce(self, bounce_type: str, reason: str | None = None) -> None:
        from datetime import datetime, timezone
        self.status = EmailStatus.BOUNCED
        self.bounced_at = datetime.now(timezone.utc)
        self.bounce_type = bounce_type
        self.bounce_reason = reason

    def mark_sent(self, provider_message_id: str | None = None) -> None:
        from datetime import datetime, timezone
        self.status = EmailStatus.SENT
        self.sent_at = datetime.now(timezone.utc)
        if provider_message_id:
            self.provider_message_id = provider_message_id

    def to_thread_context(self) -> dict[str, Any]:
        """Minimal dict for injecting thread history into follow-up prompts."""
        return {
            "email_type": self.email_type,
            "subject": self.subject,
            "body_text": self.body_text[:2000],   # truncate for token budget
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "was_opened": self.was_opened,
            "was_clicked": self.was_clicked,
        }


class EmailEvent(Base):
    """
    Granular email event log — one row per open/click/bounce event.
    Appended by webhook handlers; never updated.
    """

    __tablename__ = "email_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        default=uuid.uuid4,
    )
    email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("emails.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # event_type: opened | clicked | bounced | unsubscribed | spam_complaint
    event_type: Mapped[str] = mapped_column(
        String(StrLen.SHORT), nullable=False, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        default=datetime.utcnow,
        index=True,
    )

    # Metadata
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    click_url: Mapped[str | None] = mapped_column(String(StrLen.URL))
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # ── Relationship ──────────────────────────────────────────────────────────
    email: Mapped[Email] = relationship(
        "Email",
        back_populates="events",
        lazy="select",
    )
