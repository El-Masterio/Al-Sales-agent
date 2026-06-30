"""
app/models/reply.py
===================
Reply ORM model — inbound emails from leads, classified by AI into
actionable categories (interested, not_interested, wants_demo, etc.)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    BaseModel,
    ReplyClassType,
    ReplyClassification,
    StrLen,
)

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.company import Company
    from app.models.contact import Contact
    from app.models.email import Email
    from app.models.user import User


class Reply(Base, BaseModel):
    """
    An inbound email reply from a lead.

    Classification pipeline:
        1. Webhook receives inbound email (SendGrid Inbound Parse / SES)
        2. Raw email persisted here with classification='unclassified'
        3. Celery task sends body_text to LLM classifier
        4. classification, confidence, sentiment, ai_summary populated
        5. action_taken executed automatically based on classification
        6. Optionally flagged for human review (reviewed=False)
    """

    __tablename__ = "replies"

    # ── Foreign keys ──────────────────────────────────────────────────────────
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("emails.id", ondelete="SET NULL"),
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
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        index=True,
    )

    # ── Raw inbound ───────────────────────────────────────────────────────────
    from_email: Mapped[str] = mapped_column(String(StrLen.EMAIL), nullable=False)
    from_name: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM))
    subject: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM))
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(
        String(StrLen.MEDIUM), unique=True, index=True
    )
    in_reply_to: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        default=datetime.utcnow,
        index=True,
    )

    # ── AI classification ─────────────────────────────────────────────────────
    classification: Mapped[str] = mapped_column(
        ReplyClassType,
        nullable=False,
        server_default=text("'unclassified'"),
        default=ReplyClassification.UNCLASSIFIED,
        index=True,
    )
    classification_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    sentiment_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_suggested_action: Mapped[str | None] = mapped_column(Text)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classification_model: Mapped[str | None] = mapped_column(String(StrLen.SHORT))

    # ── Action taken ──────────────────────────────────────────────────────────
    action_taken: Mapped[str | None] = mapped_column(Text)
    actioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actioned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        name="actioned_by",
    )

    # ── Human review ──────────────────────────────────────────────────────────
    reviewed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False, index=True
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        name="reviewed_by",
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    override_classification: Mapped[str | None] = mapped_column(ReplyClassType)

    # ── Relationships ─────────────────────────────────────────────────────────
    email: Mapped[Email | None] = relationship(
        "Email", back_populates="replies", lazy="select"
    )
    company: Mapped[Company] = relationship(
        "Company", back_populates="replies", lazy="select"
    )
    contact: Mapped[Contact | None] = relationship(
        "Contact", back_populates="replies", lazy="select"
    )
    campaign: Mapped[Campaign | None] = relationship(
        "Campaign", back_populates="replies", lazy="select"
    )
    actioned_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[actioned_by_id], lazy="select"
    )
    reviewed_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[reviewed_by_id], lazy="select"
    )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def effective_classification(self) -> str:
        """Human override takes precedence over AI classification."""
        return self.override_classification or self.classification

    @property
    def is_positive(self) -> bool:
        return self.effective_classification in {
            ReplyClassification.INTERESTED,
            ReplyClassification.WANTS_DEMO,
            ReplyClassification.NEEDS_PRICING,
            ReplyClassification.POSITIVE_GENERAL,
        }

    @property
    def is_negative(self) -> bool:
        return self.effective_classification in {
            ReplyClassification.NOT_INTERESTED,
            ReplyClassification.NEGATIVE_GENERAL,
            ReplyClassification.UNSUBSCRIBE,
        }

    @property
    def requires_immediate_action(self) -> bool:
        """True for replies that should trigger an automated action ASAP."""
        return self.effective_classification in {
            ReplyClassification.WANTS_DEMO,
            ReplyClassification.INTERESTED,
            ReplyClassification.NEEDS_PRICING,
            ReplyClassification.UNSUBSCRIBE,
        }

    @property
    def should_stop_sequence(self) -> bool:
        """True if follow-up emails should stop after this reply."""
        return self.effective_classification != ReplyClassification.OUT_OF_OFFICE

    # ── Mutators ──────────────────────────────────────────────────────────────

    def apply_classification(
        self,
        classification: ReplyClassification,
        confidence: float,
        sentiment: float | None,
        summary: str | None,
        suggested_action: str | None,
        model: str,
    ) -> None:
        from datetime import datetime, timezone
        self.classification = classification
        self.classification_confidence = confidence
        self.sentiment_score = sentiment
        self.ai_summary = summary
        self.ai_suggested_action = suggested_action
        self.classification_model = model
        self.classified_at = datetime.now(timezone.utc)

    def mark_actioned(self, action: str, user_id: uuid.UUID | None = None) -> None:
        from datetime import datetime, timezone
        self.action_taken = action
        self.actioned_at = datetime.now(timezone.utc)
        self.actioned_by_id = user_id

    def mark_reviewed(self, user_id: uuid.UUID, override: ReplyClassification | None = None) -> None:
        from datetime import datetime, timezone
        self.reviewed = True
        self.reviewed_by_id = user_id
        self.reviewed_at = datetime.now(timezone.utc)
        if override:
            self.override_classification = override
